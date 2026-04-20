# Skill: CDK for Terraform (CDKTF) — TypeScript

**Role:** Gerador de infraestrutura como código com CDKTF em TypeScript.  
**Objetivo:** Criar e editar arquivos CDKTF organizados, hierárquicos e reutilizáveis — preferindo sempre extrair constructs e métodos em vez de repetir blocos de recurso.

---

## 1. ESTRUTURA DE PROJETO

```
infrastructure/
├── main.ts                   # Entry point — instancia App e Stacks
├── cdktf.json                # Configuração do CDKTF (providers, output)
├── package.json
├── tsconfig.json
├── stacks/
│   ├── base-stack.ts         # Stack base (opcional — compartilha config comum)
│   ├── network-stack.ts
│   └── application-stack.ts
├── constructs/               # Blocos reutilizáveis por domínio
│   ├── network/
│   │   ├── vpc.construct.ts
│   │   └── subnet.construct.ts
│   ├── compute/
│   │   └── lambda.construct.ts
│   └── messaging/
│       └── sqs.construct.ts
└── config/
    ├── environments.ts       # Configurações por ambiente (dev, stag, prod)
    └── constants.ts          # Constantes globais
```

---

## 2. ENTRY POINT — main.ts

```typescript
import { App } from "cdktf";
import { NetworkStack } from "./stacks/network-stack";
import { ApplicationStack } from "./stacks/application-stack";
import { getEnvironmentConfig } from "./config/environments";

const app = new App();
const env = process.env.ENVIRONMENT ?? "dev";
const config = getEnvironmentConfig(env);

new NetworkStack(app, `network-${env}`, { config });
new ApplicationStack(app, `application-${env}`, { config });

app.synth();
```

---

## 3. CONFIGURAÇÃO POR AMBIENTE

```typescript
// config/environments.ts
export interface EnvironmentConfig {
  env: string;
  region: string;
  accountId: string;
  vpcCidr: string;
  lambdaMemory: number;
}

const configs: Record<string, EnvironmentConfig> = {
  dev: {
    env: "dev",
    region: "us-east-1",
    accountId: "111111111111",
    vpcCidr: "10.0.0.0/16",
    lambdaMemory: 256,
  },
  stag: {
    env: "stag",
    region: "us-east-1",
    accountId: "222222222222",
    vpcCidr: "10.1.0.0/16",
    lambdaMemory: 512,
  },
  prod: {
    env: "prod",
    region: "us-east-1",
    accountId: "333333333333",
    vpcCidr: "10.2.0.0/16",
    lambdaMemory: 1024,
  },
};

export function getEnvironmentConfig(env: string): EnvironmentConfig {
  const config = configs[env];
  if (!config) throw new Error(`Ambiente desconhecido: ${env}`);
  return config;
}
```

---

## 4. STACK — PADRÃO DE CRIAÇÃO

```typescript
// stacks/application-stack.ts
import { TerraformStack, S3Backend } from "cdktf";
import { Construct } from "constructs";
import { AwsProvider } from "@cdktf/provider-aws/lib/provider";
import { EnvironmentConfig } from "../config/environments";
import { LambdaConstruct } from "../constructs/compute/lambda.construct";
import { SqsConstruct } from "../constructs/messaging/sqs.construct";

interface ApplicationStackProps {
  config: EnvironmentConfig;
}

export class ApplicationStack extends TerraformStack {
  constructor(scope: Construct, id: string, { config }: ApplicationStackProps) {
    super(scope, id);

    // Provider
    new AwsProvider(this, "aws", {
      region: config.region,
    });

    // Backend remoto
    new S3Backend(this, {
      bucket: `terraform-state-${config.accountId}`,
      key: `${config.env}/application.tfstate`,
      region: config.region,
      encrypt: true,
    });

    // Recursos — instancie constructs, não recursos diretamente
    const processorQueue = new SqsConstruct(this, "processor-queue", {
      name: `${config.env}-processor`,
      config,
      withDlq: true,
    });

    new LambdaConstruct(this, "processor-lambda", {
      name: `${config.env}-processor`,
      config,
      sqsArn: processorQueue.queue.arn,
    });
  }
}
```

**Regras:**
- Stack nunca cria recursos diretamente — sempre instancia **constructs**
- Toda config variável por ambiente vem de `EnvironmentConfig`
- Backend S3 configurado em todo stack de produção

---

## 5. CONSTRUCT — BLOCO REUTILIZÁVEL

O construct é a unidade central de reutilização. Encapsule um grupo de recursos relacionados:

```typescript
// constructs/messaging/sqs.construct.ts
import { Construct } from "constructs";
import { SqsQueue } from "@cdktf/provider-aws/lib/sqs-queue";
import { EnvironmentConfig } from "../../config/environments";

interface SqsConstructProps {
  name: string;
  config: EnvironmentConfig;
  withDlq?: boolean;
  visibilityTimeoutSeconds?: number;
  messageRetentionSeconds?: number;
}

export class SqsConstruct extends Construct {
  public readonly queue: SqsQueue;
  public readonly dlq?: SqsQueue;

  constructor(scope: Construct, id: string, props: SqsConstructProps) {
    super(scope, id);

    const {
      name,
      config,
      withDlq = false,
      visibilityTimeoutSeconds = 60,
      messageRetentionSeconds = 1209600, // 14 dias
    } = props;

    // Cria DLQ primeiro se necessário
    if (withDlq) {
      this.dlq = this.createQueue(`${name}-dlq`, {
        visibilityTimeoutSeconds: 900,
        messageRetentionSeconds,
      });
    }

    this.queue = this.createQueue(name, {
      visibilityTimeoutSeconds,
      messageRetentionSeconds,
      redrivePolicy: this.dlq
        ? JSON.stringify({
            deadLetterTargetArn: this.dlq.arn,
            maxReceiveCount: 10,
          })
        : undefined,
    });
  }

  // Método privado extraído — evita duplicação entre queue e dlq
  private createQueue(
    name: string,
    opts: {
      visibilityTimeoutSeconds: number;
      messageRetentionSeconds: number;
      redrivePolicy?: string;
    }
  ): SqsQueue {
    return new SqsQueue(this, name, {
      name,
      visibilityTimeoutSeconds: opts.visibilityTimeoutSeconds,
      messageRetentionSeconds: opts.messageRetentionSeconds,
      redrivePolicy: opts.redrivePolicy,
      tags: this.buildTags(name),
    });
  }

  // Método reutilizável de tags — extraia sempre que tags forem repetidas
  private buildTags(name: string): Record<string, string> {
    return {
      Name: name,
      ManagedBy: "cdktf",
    };
  }
}
```

---

## 6. CONSTRUCT COMPLEXO — COM MÉTODOS AUXILIARES

Quando um construct tem muitos recursos, extraia a criação em métodos privados:

```typescript
// constructs/compute/lambda.construct.ts
import { Construct } from "constructs";
import { LambdaFunction } from "@cdktf/provider-aws/lib/lambda-function";
import { LambdaEventSourceMapping } from "@cdktf/provider-aws/lib/lambda-event-source-mapping";
import { IamRole } from "@cdktf/provider-aws/lib/iam-role";
import { IamRolePolicy } from "@cdktf/provider-aws/lib/iam-role-policy";
import { CloudwatchLogGroup } from "@cdktf/provider-aws/lib/cloudwatch-log-group";
import { EnvironmentConfig } from "../../config/environments";

interface LambdaConstructProps {
  name: string;
  config: EnvironmentConfig;
  handler?: string;
  runtime?: string;
  sqsArn?: string;
  environment?: Record<string, string>;
  timeoutSeconds?: number;
}

export class LambdaConstruct extends Construct {
  public readonly fn: LambdaFunction;
  public readonly role: IamRole;

  constructor(scope: Construct, id: string, props: LambdaConstructProps) {
    super(scope, id);

    const {
      name,
      config,
      handler = "index.handler",
      runtime = "nodejs20.x",
      sqsArn,
      environment = {},
      timeoutSeconds = 30,
    } = props;

    // Cada grupo de recursos em um método privado
    this.role = this.createExecutionRole(name, sqsArn);
    const logGroup = this.createLogGroup(name);

    this.fn = this.createFunction({
      name,
      config,
      handler,
      runtime,
      environment,
      timeoutSeconds,
      logGroupName: logGroup.name,
    });

    if (sqsArn) {
      this.createSqsTrigger(sqsArn);
    }
  }

  private createExecutionRole(name: string, sqsArn?: string): IamRole {
    const role = new IamRole(this, "role", {
      name: `${name}-role`,
      assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [{
          Effect: "Allow",
          Principal: { Service: "lambda.amazonaws.com" },
          Action: "sts:AssumeRole",
        }],
      }),
    });

    // Política base — sempre
    new IamRolePolicy(this, "base-policy", {
      role: role.id,
      policy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Action: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            Resource: "*",
          },
          // Permissão SQS apenas se houver trigger
          ...(sqsArn ? [{
            Effect: "Allow",
            Action: ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
            Resource: sqsArn,
          }] : []),
        ],
      }),
    });

    return role;
  }

  private createLogGroup(name: string): CloudwatchLogGroup {
    return new CloudwatchLogGroup(this, "log-group", {
      name: `/aws/lambda/${name}`,
      retentionInDays: 14,
    });
  }

  private createFunction(opts: {
    name: string;
    config: EnvironmentConfig;
    handler: string;
    runtime: string;
    environment: Record<string, string>;
    timeoutSeconds: number;
    logGroupName: string;
  }): LambdaFunction {
    return new LambdaFunction(this, "fn", {
      functionName: opts.name,
      handler: opts.handler,
      runtime: opts.runtime,
      role: this.role.arn,
      memorySize: opts.config.lambdaMemory,
      timeout: opts.timeoutSeconds,
      filename: "dist/lambda.zip",
      environment: {
        variables: {
          ENVIRONMENT: opts.config.env,
          ...opts.environment,
        },
      },
      tags: { Name: opts.name, ManagedBy: "cdktf" },
      dependsOn: [], // populate se necessário
    });
  }

  private createSqsTrigger(sqsArn: string): LambdaEventSourceMapping {
    return new LambdaEventSourceMapping(this, "sqs-trigger", {
      eventSourceArn: sqsArn,
      functionName: this.fn.arn,
      batchSize: 1,
    });
  }
}
```

---

## 7. PRINCÍPIOS DE REFATORAÇÃO

### Extraia em construct quando:
- Um grupo de recursos aparece mais de uma vez
- Um recurso tem muitas propriedades configuráveis
- Um recurso depende de outros recursos criados juntos (ex: SQS + DLQ + Policy)

### Extraia em método privado quando:
- Um construct tem mais de 3 recursos
- A lógica de criação de um recurso é complexa
- Há variações condicionais (`if (withDlq)`)

### Use interfaces para props:
```typescript
// Sempre defina uma interface para as props do construct
interface MinhaConstructProps {
  name: string;
  config: EnvironmentConfig;
  // Opcionais com valor padrão no destructuring
  timeout?: number;
  withFeatureX?: boolean;
}
```

### Exponha outputs via propriedades públicas:
```typescript
export class SqsConstruct extends Construct {
  public readonly queue: SqsQueue;   // acessível por outros constructs
  public readonly dlq?: SqsQueue;
}

// Uso em outro construct ou stack:
const sqs = new SqsConstruct(this, "minha-fila", { ... });
console.log(sqs.queue.arn); // acesso tipado
```

### Nunca repita tags — extraia um método:
```typescript
private tags(extra?: Record<string, string>): Record<string, string> {
  return {
    Environment: this.config.env,
    ManagedBy: "cdktf",
    ...extra,
  };
}
```

---

## 8. OUTPUTS E VARIÁVEIS

```typescript
import { TerraformOutput, TerraformVariable } from "cdktf";

// Variável de input (útil para secrets não hardcoded)
const dbPassword = new TerraformVariable(this, "db-password", {
  type: "string",
  sensitive: true,
  description: "Senha do banco de dados",
});

// Output exportado do stack
new TerraformOutput(this, "queue-url", {
  value: processorQueue.queue.url,
  description: "URL da fila do processor",
});
```

---

## 9. REFERÊNCIAS ENTRE STACKS

Para passar valores entre stacks, use `TerraformOutput` + data source ou passe via props:

```typescript
// stack A — exporta
new TerraformOutput(this, "vpc-id", {
  value: this.vpc.id,
  // sem sensitive — pode ser referenciado
});

// stack B — recebe como prop (padrão preferido)
interface AppStackProps {
  config: EnvironmentConfig;
  vpcId: string;  // passado pelo main.ts
}

// main.ts — orquestra
const network = new NetworkStack(app, `network-${env}`, { config });
new ApplicationStack(app, `application-${env}`, {
  config,
  vpcId: network.vpcId,  // propriedade pública do NetworkStack
});
```

---

## 10. cdktf.json

```json
{
  "language": "typescript",
  "app": "npx ts-node main.ts",
  "projectId": "seu-projeto-id",
  "sendCrashReports": false,
  "terraformProviders": [
    "hashicorp/aws@~> 5.0"
  ],
  "terraformModules": [],
  "output": "cdktf.out"
}
```

---

## 11. ANTIPADRÕES — NUNCA FAZER

```typescript
// ❌ Criar recursos diretamente na Stack — dificulta reuso
export class AppStack extends TerraformStack {
  constructor(scope, id, props) {
    super(scope, id);
    new SqsQueue(this, "fila", { name: "prod-fila", ... }); // resource direto
    new SqsQueue(this, "fila-dlq", { name: "prod-fila-dlq", ... }); // duplicação
  }
}

// ✅ Usar construct
new SqsConstruct(this, "fila", { name: "prod-fila", withDlq: true });

// ❌ Hardcode de environment na infra
new LambdaFunction(this, "fn", { memorySize: 1024 }); // sem variação por env

// ✅ Usar config
new LambdaFunction(this, "fn", { memorySize: config.lambdaMemory });

// ❌ Copiar bloco de tags em todo recurso
tags: { Environment: "prod", ManagedBy: "cdktf", Name: "fila" }

// ✅ Extrair método
tags: this.tags({ Name: "fila" })
```

---

## 12. CHECKLIST ANTES DE ENTREGAR

- [ ] Recursos estão encapsulados em constructs, não diretamente na stack?
- [ ] Constructs com muitos recursos têm métodos privados por grupo?
- [ ] Props do construct têm interface TypeScript definida?
- [ ] Valores variáveis por ambiente vêm de `EnvironmentConfig`?
- [ ] Recursos públicos (ARNs, URLs) expostos como propriedades tipadas?
- [ ] Tags extraídas em método, não repetidas em cada recurso?
- [ ] Backend S3 configurado nos stacks?
- [ ] `main.ts` apenas instancia stacks, sem lógica de recurso?
- [ ] Nenhuma string de ambiente hardcoded (`"prod"`, `"us-east-1"` inline)?
- [ ] `cdktf synth` ou `cdktf plan` roda sem erros de tipo TypeScript?
