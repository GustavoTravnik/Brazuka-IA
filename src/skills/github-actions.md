# Skill: GitHub Actions

**Objetivo:** Criar e editar workflows GitHub Actions seguros e reutilizáveis, com suporte a deploy no AWS via Serverless Framework, no GCP via OIDC e provisionamento de infraestrutura com CDKTF TypeScript.

---

## 1. ESTRUTURA DE ARQUIVOS

```
.github/
└── workflows/
    ├── ci.yml              # Testes e build (dispara em PR e push)
    ├── deploy-stag.yml     # Deploy staging
    ├── deploy-prod.yml     # Deploy produção
    └── reusable/
        └── build-dotnet.yml  # Workflow reutilizável
```

Prefira **um arquivo por responsabilidade** a um monolítico.

---

## 2. CREDENCIAIS — SEMPRE VIA SECRETS

**Nunca** coloque senhas, tokens ou chaves diretamente no YAML:

```yaml
# ✅ Correto
env:
  AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}

# ✅ Correto — via action oficial
- uses: aws-actions/configure-aws-credentials@v4
  with:
    aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    aws-region: us-east-1

# ❌ Errado — nunca hardcode
env:
  AWS_ACCESS_KEY_ID: AKIAIOSFODNN7EXAMPLE
```

---

## 3. ESTRUTURA BASE DE UM WORKFLOW

```yaml
name: CI

on:
  push:
    branches: [staging, main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: "8.0.x"
      - run: dotnet restore
      - run: dotnet test --no-restore
```

---

## 4. TRIGGERS COMUNS

```yaml
on:
  push:
    branches: [main, staging]
    paths:                      # só executa se esses paths mudaram
      - "src/**"
      - ".github/workflows/**"

  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]

  schedule:
    - cron: "0 6 * * 1-5"      # Seg-Sex às 6h UTC

  workflow_dispatch:
    inputs:
      environment:
        required: true
        type: choice
        options: [stag, prod]
```

---

## 5. JOBS PARALELOS, SEQUENCIAIS E MATRIX

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        dotnet: ["6.0.x", "8.0.x"]
      fail-fast: false
    steps:
      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: ${{ matrix.dotnet }}

  deploy:
    needs: [test, build]   # sequencial — aguarda ambos
    runs-on: ubuntu-latest
    steps: [...]
```

---

## 6. CACHE, ARTIFACTS E ENVIRONMENTS

```yaml
# Cache de dependências
- uses: actions/cache@v4
  with:
    path: ~/.nuget/packages
    key: ${{ runner.os }}-nuget-${{ hashFiles('**/*.csproj') }}

# Artifact entre jobs
- uses: actions/upload-artifact@v4
  with:
    name: deploy-package
    path: bin/serverless/deploy-package.zip
    retention-days: 1   # temporário — não deixar padrão 90 dias

# Environment com proteção
jobs:
  deploy-prod:
    environment:
      name: production   # requer aprovação manual configurada no GitHub
```

---

## 7. WORKFLOWS REUTILIZÁVEIS

```yaml
# .github/workflows/reusable/build-dotnet.yml
on:
  workflow_call:
    inputs:
      project-path:
        required: true
        type: string
    secrets:
      NUGET_TOKEN:
        required: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: "8.0.x"
      - run: dotnet build ${{ inputs.project-path }} -c Release
```

```yaml
# Chamando o workflow reutilizável
jobs:
  build-api:
    uses: ./.github/workflows/reusable/build-dotnet.yml
    with:
      project-path: src/Empresa.Servico.Api
    secrets:
      NUGET_TOKEN: ${{ secrets.NUGET_TOKEN }}
```

---

## 8. DEPLOY AWS COM SERVERLESS

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    aws-region: us-east-1

- name: Install Serverless
  run: |
    export TOOL_DIR=.tmp-serverless-tools
    mkdir -p $TOOL_DIR
    npm install --no-save --prefix $TOOL_DIR serverless@3.38.0 serverless-prune-plugin@2.0.2

- name: Deploy
  run: |
    cd src/Empresa.Servico.Processor
    ../../.tmp-serverless-tools/node_modules/.bin/serverless deploy --stage ${{ env.STAGE }}
```

---

## 9. AUTENTICAÇÃO GCP — WORKLOAD IDENTITY FEDERATION (OIDC)

Prefira OIDC a chaves JSON — não exige rotação e é mais seguro:

### Configuração no GCP (uma vez por projeto)
```bash
# 1. Criar pool
gcloud iam workload-identity-pools create "github-pool" \
  --project="${GCP_PROJECT_ID}" --location="global"

# 2. Criar provider
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project="${GCP_PROJECT_ID}" --location="global" \
  --workload-identity-pool="github-pool" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# 3. Vincular Service Account ao pool
gcloud iam service-accounts add-iam-policy-binding \
  "meu-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${GCP_PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/minha-org/meu-repo"
```

### Uso no workflow
```yaml
permissions:
  contents: read
  id-token: write   # obrigatório para OIDC

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WIF_PROVIDER }}
          service_account: ${{ secrets.GCP_SA }}

      - uses: google-github-actions/setup-gcloud@v2
```

Secrets a registrar: `GCP_WIF_PROVIDER` e `GCP_SA`.

---

## 10. DEPLOY GCP — CLOUD RUN / CLOUD FUNCTIONS / GKE

```yaml
# Cloud Run
- uses: google-github-actions/deploy-cloudrun@v2
  with:
    service: meu-servico
    region: us-east1
    image: us-east1-docker.pkg.dev/${{ env.GCP_PROJECT_ID }}/apps/meu-servico:${{ github.sha }}
    secrets: |
      DB_PASSWORD=projects/${{ env.GCP_PROJECT_ID }}/secrets/db-password:latest

# Cloud Functions (Gen 2)
- uses: google-github-actions/deploy-cloud-functions@v3
  with:
    name: minha-funcao
    runtime: nodejs20
    region: us-east1
    source_dir: functions/
    entry_point: handler

# GKE
- uses: google-github-actions/get-gke-credentials@v2
  with:
    cluster_name: meu-cluster
    location: us-east1

- run: |
    kubectl set image deployment/meu-servico meu-servico=<imagem>:${{ github.sha }}
    kubectl rollout status deployment/meu-servico
```

**Permissões mínimas do Service Account GCP:**

| Operação | Role mínima |
|---|---|
| Cloud Run | `roles/run.developer` |
| Cloud Functions | `roles/cloudfunctions.developer` |
| Artifact Registry | `roles/artifactregistry.writer` |
| Secret Manager | `roles/secretmanager.secretAccessor` |
| GKE | `roles/container.developer` |
| State bucket (CDKTF) | `roles/storage.objectAdmin` no bucket |

---

## 11. CDKTF — PROVISIONAMENTO DE INFRA NO WORKFLOW

```yaml
- uses: actions/setup-node@v4
  with:
    node-version: "20.x"
    cache: "npm"
    cache-dependency-path: infrastructure/package-lock.json

- name: Instalar dependências
  working-directory: infrastructure
  run: npm ci   # não npm install — garante lock

- name: Instalar CDKTF CLI
  run: npm install -g cdktf-cli@0.20.10  # fixe a versão

# Plan em PRs
- name: CDKTF Plan
  id: plan
  working-directory: infrastructure
  run: cdktf plan --auto-approve 2>&1 | tee plan-output.txt
  env:
    ENVIRONMENT: ${{ env.STAGE }}

# Comentar plan no PR
- uses: actions/github-script@v7
  if: always()
  with:
    script: |
      const fs = require('fs');
      const plan = fs.readFileSync('infrastructure/plan-output.txt', 'utf8');
      github.rest.issues.createComment({
        issue_number: context.issue.number,
        owner: context.repo.owner,
        repo: context.repo.repo,
        body: `## CDKTF Plan\n\`\`\`\n${plan.slice(-10000)}\n\`\`\``
      });

# Deploy em push
- name: CDKTF Deploy
  working-directory: infrastructure
  run: cdktf deploy --auto-approve
  env:
    ENVIRONMENT: ${{ env.STAGE }}
```

**Regra:** `cancel-in-progress: false` para workflows de infra — nunca cancele provisioning em andamento.

Cache de providers:
```yaml
- uses: actions/cache@v4
  with:
    path: |
      infrastructure/.gen
      infrastructure/cdktf.out
    key: ${{ runner.os }}-cdktf-${{ hashFiles('infrastructure/cdktf.json') }}
```

---

## 12. VARIÁVEIS POR AMBIENTE

```yaml
jobs:
  deploy:
    environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'staging' }}
    env:
      STAGE: ${{ github.ref == 'refs/heads/main' && 'prod' || 'stag' }}
      GCP_PROJECT_ID: ${{ github.ref == 'refs/heads/main' && secrets.GCP_PROJECT_ID_PROD || secrets.GCP_PROJECT_ID_STAG }}
      GCP_WIF_PROVIDER: ${{ github.ref == 'refs/heads/main' && secrets.GCP_WIF_PROVIDER_PROD || secrets.GCP_WIF_PROVIDER_STAG }}
      GCP_SA: ${{ github.ref == 'refs/heads/main' && secrets.GCP_SA_PROD || secrets.GCP_SA_STAG }}
```

Separe sempre secrets por ambiente: `_STAG` / `_PROD`.

---

## 13. SEGURANÇA — BOAS PRÁTICAS

- **Fixe versões de actions** com SHA completo em produção
- **Permissões mínimas** — declare explicitamente no job
- **OIDC em vez de chaves de longa duração** para AWS e GCP
- **Nunca** `pull_request_target` com código de PR externo sem revisão
- **Não faça `echo` de secrets** — GitHub mascara, mas evite expor em logs
- Secrets de runtime referenciados via Secret Manager, não como env var de build

---

## 14. NOTIFICAÇÕES E STATUS

```yaml
- name: Notify failure
  if: failure()
  uses: slackapi/slack-github-action@v1
  with:
    payload: |
      { "text": "Deploy falhou em ${{ github.ref }} — ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" }
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

Condições: `if: success()`, `if: failure()`, `if: always()`, `if: cancelled()`

---

## 15. CHECKLIST ANTES DE ENTREGAR

- [ ] Nenhum secret, senha ou chave diretamente no YAML?
- [ ] `concurrency` configurado para cancelar runs duplicadas (exceto infra)?
- [ ] Jobs independentes em paralelo, sequenciais com `needs:`?
- [ ] Cache de dependências configurado?
- [ ] Artifacts com `retention-days` definido?
- [ ] `environment:` com proteção nos deploys de produção?
- [ ] `paths:` nos triggers para não rodar sem necessidade?
- [ ] Versões de actions fixadas?
- [ ] Para GCP: Workload Identity Federation em vez de chave JSON?
- [ ] `permissions: id-token: write` declarado no job que usa OIDC?
- [ ] Secrets separados por ambiente (`_STAG` / `_PROD`)?
- [ ] Service Account com roles mínimas, sem `roles/owner`?
- [ ] Para CDKTF: `cancel-in-progress: false`?
- [ ] Para CDKTF: `--auto-approve` em todos os comandos?
- [ ] Para CDKTF: `npm ci` (não `npm install`)?
