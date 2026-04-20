# Skill: Prod Safety — Regras de Segurança em Produção

**Role:** Garantir que investigações usem dados reais e que nenhuma escrita ocorra em produção sem autorização explícita.  
**Ativação:** Sempre que acessar banco de dados, logs ou qualquer recurso de produção durante investigação ou operação.

---

## PRINCÍPIO CENTRAL

> Staging não tem os dados do cliente afetado. Banco de produção tem dados reais. Qualquer escrita errada é irreversível ou cara de reverter.

Duas regras absolutas:
1. **Investigações usam produção** — staging serve para entender schema, nunca para confirmar dados de cliente
2. **Escrita em produção exige autorização textual explícita** — permissão para ler não implica permissão para escrever

---

## 1. IDENTIFICAR O AMBIENTE ANTES DE QUALQUER OPERAÇÃO

### MongoDB / DocumentDB
```python
uri = os.environ.get("MONGO_URI", "")

if any(x in uri for x in ["prod", "production"]):
    env = "PRODUÇÃO ⚠️"
elif any(x in uri for x in ["stag", "staging", "dev"]):
    env = "STAGING (não representa dados de cliente)"
else:
    env = "DESCONHECIDO — trate como produção"
```

Nomes de banco por ambiente:
| Ambiente | Padrão de nome |
|---|---|
| Produção | `prod-*` (ex: `prod-collection`, `prod-financial`) |
| Staging | `stag-*`, `staging-*`, `dev-*` |

### CloudWatch / AWS
```bash
# Logs de prod geralmente têm prefixo prod-
aws logs describe-log-groups --query 'logGroups[*].logGroupName' \
  --output text | tr '\t' '\n' | grep "^/aws/lambda/prod-"
```

**Em caso de dúvida sobre o ambiente, trate como produção.**

---

## 2. PRIORIDADE DE ACESSO PARA INVESTIGAÇÕES

```
1. Produção    →  use sempre — é a fonte da verdade para dados de clientes reais
2. Staging     →  apenas para entender o schema/estrutura dos dados
                  NUNCA para buscar clientes ou transações reais
3. Código-fonte →  para entender o fluxo quando sem acesso a nenhum ambiente
```

### ✅ O que é válido em staging durante investigação
- Entender o schema de uma collection (`find({}).limit(1)`)
- Entender campos disponíveis e seus tipos
- Testar a sintaxe de uma query antes de rodar em prod

### ❌ O que nunca fazer em staging durante investigação
- Buscar por CNPJ, CPF, ID ou nome de cliente do issue
- Afirmar que "não encontrou registros" baseado em staging
- Usar contagens de staging para dimensionar impacto

---

## 3. QUANDO NÃO HÁ ACESSO A PRODUÇÃO

Se só houver URI de staging disponível:

1. **Documente explicitamente** na sprint:
   ```
   [HH:MM] sem acesso a prod — MONGO_URI disponível aponta para staging.
   Dados consultados são de staging apenas para mapear estrutura.
   Busca pelos clientes afetados não é possível sem acesso a prod.
   ```

2. **Use staging somente para schema** — nunca para concluir que dados não existem

3. **Liste o que precisaria ser verificado em prod:**
   ```
   Verificações pendentes em produção:
   - db["prod-collection"].PaymentPlans.find({"loan.borrower.companyDocument": "14225663000119"})
   - db["prod-financial"].PaymentPlans.find({"status": "WAITING", "expiresAt": {"$lt": hoje}})
   ```

---

## 4. REGRA ABSOLUTA — ESCRITA EM PRODUÇÃO

**Nunca execute operações de escrita em banco de produção sem que o usuário escreva explicitamente que autoriza.**

Não basta que a tarefa "implique" a alteração. Não basta que o dado esteja claramente errado.

### ✅ Autorização válida (explícita e inequívoca)
```
"pode alterar em produção"
"autorizo a atualização no banco de prod"
"execute o update em produção"
"pode rodar o script em prod"
"sim, pode aplicar"
```

### ❌ Não conta como autorização
```
"corrija isso"           → não diz onde
"resolve o problema"     → pode ser só código
"aplica a correção"      → pode ser deploy, não banco
"tá, pode ir"            → contexto ambíguo
"faz aí"                 → sem referência explícita
```

---

## 5. OPERAÇÕES QUE EXIGEM AUTORIZAÇÃO

Qualquer escrita em banco de produção:

| Operação | Exemplos |
|---|---|
| Inserção | `insertOne`, `insertMany`, `INSERT INTO` |
| Atualização | `updateOne`, `updateMany`, `UPDATE SET`, `replaceOne` |
| Remoção | `deleteOne`, `deleteMany`, `DELETE FROM` |
| Estrutura | `drop`, `ALTER TABLE`, `TRUNCATE`, `CREATE INDEX` |
| Migração | scripts de migração, seed, `mongorestore` apontando para prod |
| Upsert | `upsert`, `findOneAndUpdate`, `ON CONFLICT DO UPDATE` |

---

## 6. FLUXO AO IDENTIFICAR NECESSIDADE DE ESCRITA

### Passo 1 — Monte a operação, não execute
```javascript
// ✅ Script pronto para revisão — NÃO executado
db["prod-collection"].Loans.updateMany(
  { "status": "PENDING", "expiresAt": { "$lt": new Date("2024-01-01") } },
  { "$set": { "status": "EXPIRED", "updatedAt": new Date() } }
)
// Impacto estimado: verificar com countDocuments antes
```

### Passo 2 — Informe o impacto estimado
```javascript
// Rode isso primeiro para estimar impacto
db["prod-collection"].Loans.countDocuments(
  { "status": "PENDING", "expiresAt": { "$lt": new Date("2024-01-01") } }
)
```

### Passo 3 — Solicite autorização explícita
```
⚠️  AÇÃO REQUER AUTORIZAÇÃO

Operação preparada (não executada):
  updateMany em prod-collection.Loans
  Filtro: status=PENDING + expiresAt < 2024-01-01
  Impacto estimado: 347 documentos

Para executar, confirme com: "pode alterar em produção" ou "autorizo a execução".
```

### Passo 4 — Execute e registre
```
[HH:MM] Escrita em produção executada
  Operação: updateMany em prod-collection.Loans
  Filtro: { status: PENDING, expiresAt: { $lt: 2024-01-01 } }
  Documentos afetados: 347
  Autorização: "[trecho exato da mensagem do usuário]"
```

---

## 7. CASOS ESPECIAIS

**Migrações agendadas:** mesmo que a tarefa seja "executar a migration", exibe o script, informa o impacto e aguarda autorização.

**Scripts automáticos:** documente claramente que aponta para produção e requer revisão humana antes de agendamento.

**Rollback:** operações de rollback em produção **também exigem autorização** — reverter dado errado com dado igualmente incerto é uma escrita.

---

## 8. VARIÁVEIS DE AMBIENTE — REFERÊNCIA

| Variável | Ambiente |
|---|---|
| `MONGO_URI` | Verificar o valor — pode ser staging ou prod |
| `MONGO_URI_PROD` | Produção (quando separado explicitamente) |
| `MONGO_URI_STAG` | Staging |
| `MONGODB_URI` | DocumentDB — verificar o endpoint |

```bash
echo $MONGO_URI | grep -oE "(prod|stag|staging|production)"
```

---

## 9. CHECKLIST ANTES DE QUALQUER OPERAÇÃO

### Para investigação (leitura)
- [ ] Confirmei que o URI/banco consultado é de **produção**?
- [ ] Se for staging, marquei resultados como `[STAGING — não representa prod]`?
- [ ] Não usei ausência de dados em staging como evidência de que o dado não existe?
- [ ] Se sem acesso a prod, documentei as queries que precisariam ser executadas?

### Para escrita em produção
- [ ] O usuário escreveu **explicitamente** que autoriza a alteração?
- [ ] O script/query foi exibido ao usuário **antes** de executar?
- [ ] O impacto estimado foi calculado e informado?
- [ ] Tenho certeza que o URI/banco alvo é produção?
- [ ] A autorização foi registrada no log da operação?
