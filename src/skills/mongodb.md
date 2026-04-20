# Skill: MongoDB / DocumentDB

**Role:** Escrever, operar e revisar código MongoDB idiomático, seguro e compatível com AWS DocumentDB.  
**Ativação:** Sempre que precisar gerar código, executar queries ou revisar implementações MongoDB/DocumentDB — em Python, Node.js ou C#.

> ⚠️ **AWS DocumentDB:** Este ecossistema usa DocumentDB (compatível com MongoDB 4.0/5.0), não MongoDB nativo. Features incompatíveis causarão erros em produção. Restrições marcadas ao longo desta skill.

---

## 1. CONEXÃO

**Regra:** sempre singleton — nunca crie um novo `MongoClient` por requisição.

### Python (PyMongo)
```python
from pymongo import MongoClient
import os

_client: MongoClient | None = None

def get_db(uri: str | None = None, db_name: str | None = None):
    global _client
    if _client is None:
        _client = MongoClient(
            uri or os.environ["MONGO_URI"],
            serverSelectionTimeoutMS=5000,
        )
    return _client[db_name or os.environ["MONGO_DB_NAME"]]
```

Para conexão via campos separados:
```python
uri = f"mongodb://{user}:{password}@{host}:{port}/{dbname}?authSource=admin&retryWrites=false"
```

> O `retryWrites=false` é obrigatório para AWS DocumentDB — nunca remova.

### Node.js (Mongoose)
```typescript
import mongoose from 'mongoose';

export async function connectDb(): Promise<void> {
    if (mongoose.connection.readyState !== 0) return;
    await mongoose.connect(process.env.MONGO_URI!, { serverSelectionTimeoutMS: 5000 });
}
```

---

## 2. LEITURA

### Sempre projete — nunca traga o documento inteiro se não precisar
```python
# ❌ Traz tudo
users = db.users.find({"status": "active"})

# ✅ Projete só o necessário
users = db.users.find(
    {"status": "active"},
    {"_id": 1, "name": 1, "email": 1}
)
```

```typescript
const users = await User.find({ status: 'active' }, 'name email').lean();
```

### Busca por ID
```python
from bson import ObjectId
doc = db.colecao.find_one({"_id": ObjectId(id_str)})
```

### Paginação — keyset em vez de skip
```python
# ❌ Full scan até o offset — lento em coleções grandes
db.orders.find().skip(5000).limit(100)

# ✅ Keyset — usa índice
db.orders.find({"_id": {"$gt": ultimo_id}}).limit(100).sort("_id", 1)
```

### Leitura em volume — cursor com batch_size
```python
# ❌ Carrega tudo na memória
all_docs = list(db.colecao.find({}))

# ✅ Itera com batch controlado
cursor = db.colecao.find({}).batch_size(500)
for doc in cursor:
    process(doc)
```

### Aggregation pipeline
```python
pipeline = [
    {"$match": {"status": "active", "user_id": user_id}},  # filtra cedo — usa índice
    {"$project": {"name": 1, "total": 1}},                  # reduz antes de processar
    {"$group": {"_id": "$category", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 10},
]
results = list(db.orders.aggregate(pipeline))
```

Ordem correta: `$match` → `$project` → `$lookup` → `$group` → `$sort` → `$limit`

### Verificar plano de query
```python
# ⚠️ DocumentDB suporta apenas "queryPlanner" — "executionStats" NÃO existe
db.colecao.find({"campo": "valor"}).explain("queryPlanner")
```
- `COLLSCAN` = falta índice
- `IXSCAN` = índice sendo usado corretamente

---

## 3. ESCRITA

### Insert simples
```python
result = db.colecao.insert_one({"nome": "João", "email": "joao@email.com"})
```

### Upsert
```python
db.colecao.update_one(
    {"email": email},
    {"$set": {"name": name, "updated_at": datetime.utcnow()}},
    upsert=True
)
```

### Update parcial — sempre $set, nunca replace desnecessário
```python
# ❌ Substitui tudo
db.users.replace_one({"_id": id}, full_document)

# ✅ Atualiza só o necessário
db.users.update_one({"_id": id}, {"$set": {"status": "inactive"}})
```

### Escrita em lote — bulk_write
```python
from pymongo import InsertOne, UpdateOne

ops = [
    UpdateOne({"sku": item["sku"]}, {"$set": item}, upsert=True)
    for item in items
]
# ordered=False apenas em batches homogêneos (todos do mesmo tipo)
# ⚠️ DocumentDB: use ordered=True em batches mistos (insert+update+delete)
result = db.products.bulk_write(ops, ordered=False)
```

```typescript
const ops = items.map(item => ({
    updateOne: { filter: { sku: item.sku }, update: { $set: item }, upsert: true }
}));
await Product.bulkWrite(ops, { ordered: false });
```

Use `bulk_write` para qualquer operação com mais de 10 documentos.

---

## 4. ÍNDICES

```python
db.orders.create_index("status")                                  # simples
db.orders.create_index([("user_id", 1), ("created_at", -1)])     # composto
db.users.create_index("email", unique=True)                       # único
list(db.colecao.index_information().keys())                       # listar existentes
```

```typescript
// Mongoose — definir no schema
const orderSchema = new Schema({ ... }, {
    indexes: [
        { key: { userId: 1, createdAt: -1 } },
        { key: { email: 1 }, unique: true },
    ]
});
```

> ❌ **DocumentDB não suporta TTL indexes** (`expireAfterSeconds`). Alternativa: job/Lambda periódico com `delete_many` por filtro de data.

---

## 5. MANIPULAÇÃO DE COLEÇÕES

```python
"minha_colecao" in db.list_collection_names()    # verificar existência
db.colecao.count_documents({"status": "ativo"})  # contar
db.colecao.drop()                                 # ⚠️ confirmar com usuário antes

# ❌ $sample NÃO existe no DocumentDB
# ✅ Amostragem compatível
sample = list(db.colecao.find({}).limit(5))
```

---

## 6. SERIALIZAÇÃO

```python
import json
from bson import json_util

# Simples — converte ObjectId e datetime para string
json.dumps(doc, default=str)

# Com tipos BSON preservados
json.dumps(doc, default=json_util.default)
```

---

## 7. $LOOKUP — RESTRIÇÃO CRÍTICA DO DOCUMENTDB

```python
# ✅ COMPATÍVEL — forma simples
{"$lookup": {
    "from": "products",
    "localField": "product_id",
    "foreignField": "_id",
    "as": "product"
}}

# ❌ INCOMPATÍVEL — forma com sub-pipeline não existe no DocumentDB
{"$lookup": {
    "from": "products",
    "let": {"pid": "$product_id"},
    "pipeline": [{"$match": {"$expr": {"$eq": ["$_id", "$$pid"]}}}],
    "as": "product"
}}
```

---

## 8. GERAÇÃO DE CÓDIGO — PADRÕES

### Nomenclatura de métodos de repositório
- `findByIdAsync(id)` / `findOneAsync(query)` / `findByXxxAsync(...)`
- `findAllAsync(...)` / `findAllPaginatedAsync(...)`
- `insertOneAsync(entity)` / `upsertAsync(entity)`
- `updateXxxAsync(...)` — sempre com `$set`, nunca replace inteiro
- `deleteAsync(id)` / `addXxxAsync(...)` — push em array
- `anyWithXxxAsync(...)` — retorna bool

### Singleton do cliente
```python
# ❌ Por requisição
def handler(event):
    client = MongoClient(uri)  # nova conexão a cada invocação

# ✅ Singleton fora do handler
_client = None
def get_client():
    global _client
    if _client is None:
        _client = MongoClient(uri)
    return _client
```

---

## 9. REVIEW — CHECKLIST DE PROBLEMAS COMUNS

| Categoria | Problema | Severidade |
|---|---|---|
| Performance | `list(cursor)` sem `batch_size` em coleção grande | MAIOR |
| Performance | `skip()` em vez de keyset pagination | MAIOR |
| Performance | `find()` sem projeção em listagem | MAIOR |
| Performance | `$lookup` antes de `$match` no pipeline | MAIOR |
| Segurança | `{"$where": user_input}` — NoSQL injection | CRÍTICO |
| Segurança | Senha em texto plano no documento | CRÍTICO |
| Segurança | URI de conexão hardcoded | CRÍTICO |
| Segurança | `delete_many({})` sem filtro sem confirmação | CRÍTICO |
| Compatibilidade | TTL index (`expireAfterSeconds`) | CRÍTICO |
| Compatibilidade | `.explain("executionStats")` | MAIOR |
| Compatibilidade | `$lookup` com `let`/`pipeline` | CRÍTICO |
| Compatibilidade | `$sample` no aggregation | CRÍTICO |
| Compatibilidade | `$where` / JavaScript no servidor | CRÍTICO |
| Compatibilidade | `bulk_write(ordered=False)` com ops mistas | MAIOR |

---

## 10. RESTRIÇÕES COMPLETAS DO AWS DOCUMENTDB

| Feature | Status | Alternativa |
|---|---|---|
| TTL Indexes (`expireAfterSeconds`) | ❌ Não suportado | Job/Lambda com `delete_many` por data |
| `$sample` no aggregation | ❌ Não suportado | `find({}).limit(N)` |
| `$lookup` com `let`/`pipeline` | ❌ Não suportado | Forma simples (`from/localField/foreignField`) |
| `.explain("executionStats")` | ❌ Não suportado | `.explain("queryPlanner")` |
| `$where` / JavaScript no servidor | ❌ Não suportado | Filtros com operadores nativos |
| `bulk_write` `ordered=False` com ops mistas | ⚠️ Instável | `ordered=True` ou separar por tipo |
| `findAndModify` / `find_one_and_update` | ⚠️ Só em compat. 4.0+ | Verificar versão do cluster |

---

## 11. SEGURANÇA — NUNCA FAZER

- Construir filtros com input do usuário via f-string — use dicts Python como filtro
- `$where` com qualquer dado externo
- Secrets de conexão em código ou repositório
- Expor `_id` interno em APIs públicas sem avaliar necessidade
- Armazenar senhas em texto plano
- Executar `drop()`, `delete_many({})` sem filtro ou `update_many` sem filtro sem confirmação explícita

---

## 12. CHECKLIST ANTES DE ENTREGAR

- [ ] `MongoClient` é singleton, não criado por requisição?
- [ ] URI e credenciais em variáveis de ambiente?
- [ ] `retryWrites=false` na URI de conexão com DocumentDB?
- [ ] Todas as queries de listagem têm projeção definida?
- [ ] Índices criados para os campos usados em `$match` e `sort`?
- [ ] Paginação usa keyset em vez de `skip`?
- [ ] Leitura em volume usa cursor com `batch_size`, não `list(cursor)`?
- [ ] Operações em lote usam `bulk_write`?
- [ ] Pipeline com `$match` como primeiro estágio?
- [ ] Updates parciais usam `$set`, não `replace_one` com documento inteiro?
- [ ] Nenhum operador construído de input do usuário?

### ✅ Compatibilidade DocumentDB
- [ ] Nenhum TTL index — expiração via job com `delete_many`?
- [ ] `.explain()` usa apenas `"queryPlanner"`?
- [ ] `$lookup` usa apenas forma simples (sem `let`/`pipeline`)?
- [ ] Nenhum `$where` ou `$sample`?
- [ ] `bulk_write` com ops mistas usa `ordered=True`?
