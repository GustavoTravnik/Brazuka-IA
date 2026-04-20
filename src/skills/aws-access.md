# Skill: AWS Access — MCP com fallback para CLI

**Role:** Acesso a recursos AWS de forma resiliente.  
**Ativação:** Sempre que precisar consultar CloudWatch Logs, SQS, S3, Lambda ou qualquer recurso AWS.

---

## Princípio central

O MCP AWS disponível (`aws`) expõe ferramentas de **CDK e documentação**, não de operações em runtime (CloudWatch, SQS, S3, etc.). Para qualquer operação de investigação em produção, use **AWS CLI via shell_execute**.

---

## 1. HIERARQUIA DE ACESSO

```
1. MCP AWS (aws_*)  →  apenas se a tool cobrir o caso (CDK, Bedrock, Lambda layers)
2. AWS CLI via shell_execute  →  para TUDO relacionado a logs, filas, buckets, runtime
3. Sem acesso  →  documente a limitação na sprint e tente obter credenciais
```

### Quando usar MCP AWS
Somente para as tools disponíveis:
- `CDKGeneralGuidance`, `ExplainCDKNagRule`, `CheckCDKNagSuppressions`
- `GenerateBedrockAgentSchema`, `GetAwsSolutionsConstructPattern`
- `SearchGenAICDKConstructs`, `LambdaLayerDocumentationProvider`

### Para tudo mais → AWS CLI direto

---

## 2. VERIFICAR CREDENCIAIS ANTES DE QUALQUER OPERAÇÃO

```bash
# Sempre verificar antes de usar CLI
aws sts get-caller-identity 2>&1
```

**Se retornar erro de credenciais:**
- Verifique o perfil ativo: `aws configure list`
- Tente perfil padrão: `AWS_PROFILE=default aws sts get-caller-identity`
- Liste perfis disponíveis: `cat ~/.aws/credentials | grep '^\[' && cat ~/.aws/config | grep '^\['`
- Se nenhum funcionar: registre na sprint que o acesso AWS está indisponível e prossiga sem ele

---

## 3. CLOUDWATCH LOGS — PADRÕES DE USO

### Listar log groups de um serviço
```bash
aws logs describe-log-groups \
  --query 'logGroups[*].logGroupName' \
  --output text | tr '\t' '\n' | grep <termo>
```

### Buscar por palavras-chave em janela de tempo
```bash
START=$(date -d "2 hours ago" +%s000)
END=$(date +%s000)

aws logs filter-log-events \
  --log-group-name /aws/lambda/<nome> \
  --start-time $START \
  --end-time $END \
  --filter-pattern "<termo>" \
  --limit 50 \
  --query 'events[*].{time:timestamp,msg:message}' \
  --output table
```

### Tail rápido (últimas entradas)
```bash
aws logs tail /aws/lambda/<nome> --limit 30
```

### CloudWatch Insights para queries complexas
```bash
QUERY_ID=$(aws logs start-query \
  --log-group-name /aws/lambda/<nome> \
  --start-time $(date -d "2 hours ago" +%s) \
  --end-time $(date +%s) \
  --query-string 'fields @timestamp, @message | filter @message like /ERROR/ | limit 20' \
  --output text)

sleep 5  # aguarda processamento

aws logs get-query-results --query-id $QUERY_ID \
  --query 'results[*][*].value' \
  --output table
```

---

## 4. SQS — VERIFICAR FILAS E DLQ

```bash
# Listar filas por prefixo
aws sqs list-queues --queue-name-prefix prod- \
  --query 'QueueUrls' --output text | tr '\t' '\n'

# Contar mensagens na DLQ
aws sqs get-queue-attributes \
  --queue-url <url-da-dlq> \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages'

# Ler uma mensagem da DLQ sem deletar
aws sqs receive-message \
  --queue-url <url-da-dlq> \
  --max-number-of-messages 1 \
  --query 'Messages[0].Body'
```

---

## 5. LAMBDA — INVOCAÇÃO E STATUS

```bash
# Listar Lambdas por prefixo
aws lambda list-functions \
  --query 'Functions[?starts_with(FunctionName, `prod-`)].FunctionName' \
  --output text | tr '\t' '\n'

# Ver configuração de uma Lambda
aws lambda get-function-configuration \
  --function-name <nome> \
  --query '{Runtime:Runtime,Timeout:Timeout,Memory:MemorySize,Env:Environment}'
```

---

## 6. FLUXO DE INVESTIGAÇÃO RECOMENDADO

```
1. aws sts get-caller-identity            # confirma acesso
2. aws logs describe-log-groups | grep X  # localiza o log group
3. aws logs filter-log-events ...         # busca nos logs com janela de tempo
4. aws sqs get-queue-attributes (DLQ)     # verifica mensagens presas
5. aws logs start-query / get-query-results # query complexa se necessário
```

---

## 7. QUANDO NÃO HÁ ACESSO AWS

Se `aws sts get-caller-identity` falhar após todas as tentativas:

1. Registre na sprint: `"[HH:MM] acesso AWS indisponível — sem credenciais válidas"`
2. Prossiga com as fontes alternativas disponíveis: código-fonte local, MongoDB, Jira
3. Documente no relatório final quais logs **precisariam** ser verificados e os log groups exatos
4. Nunca invente dados de logs — documente a lacuna explicitamente
