# Skill: PostgreSQL

**Role:** Escrever, operar e revisar código PostgreSQL idiomático, seguro e performático.  
**Ativação:** Sempre que precisar gerar código, executar queries ou revisar implementações PostgreSQL — em Python ou Node.js.

---

## 1. CONEXÃO

**Python — pool singleton (nunca conexão avulsa por requisição):**
```python
import os
from psycopg2 import pool

_pool: pool.ThreadedConnectionPool | None = None

def get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=os.environ["PG_DSN"],
        )
    return _pool

def get_conn():
    return get_pool().getconn()

def release_conn(conn):
    get_pool().putconn(conn)
```

**Conexão via campos separados (quando não há DSN):**
```python
import psycopg2
import psycopg2.extras

def get_conn(host, dbname, user, password, port=5432):
    return psycopg2.connect(
        host=host, port=port, dbname=dbname,
        user=user, password=password, connect_timeout=10,
    )
```

**Node.js — Pool:**
```typescript
import { Pool } from 'pg';

const pool = new Pool({
    connectionString: process.env.PG_DSN,
    max: 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
});

export { pool };
```

Variáveis esperadas: `PG_DSN` ou `PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER`, `PG_PASSWORD`.

---

## 2. QUERIES — SEMPRE PARAMETRIZADAS

```python
# ✅ Parâmetros via tupla — nunca f-string ou %
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute(
        "SELECT id, name, email FROM users WHERE status = %s AND role = %s",
        ("active", role)
    )
    rows = cur.fetchall()
```

```typescript
// ✅ Parâmetros posicionais
const { rows } = await pool.query(
    'SELECT id, name, email FROM users WHERE status = $1 AND role = $2',
    ['active', role]
);
```

**Regra absoluta:** nunca construa SQL via f-string, concatenação ou template string com dado do usuário.

Use `RealDictCursor` por padrão para retornar dicts em vez de tuples.

---

## 3. PAGINAÇÃO — KEYSET EM VEZ DE OFFSET

```python
# ❌ Full scan até o offset — lento em tabelas grandes
cur.execute("SELECT * FROM orders ORDER BY id LIMIT 100 OFFSET 5000")

# ✅ Keyset — usa índice, O(log n)
cur.execute(
    "SELECT * FROM orders WHERE id > %s ORDER BY id LIMIT %s",
    (last_id, page_size)
)
```

Use `OFFSET` apenas para páginas pequenas (< 10) em tabelas pequenas (< 100k linhas).

---

## 4. LEITURA DE VOLUME — SERVER-SIDE CURSOR

```python
# ❌ Carrega tudo na memória
cur.execute("SELECT * FROM big_table")
rows = cur.fetchall()

# ✅ Server-side cursor com iteração controlada
with conn.cursor(name="stream_cursor") as cur:
    cur.itersize = 500
    cur.execute("SELECT * FROM big_table WHERE status = %s", ("active",))
    for row in cur:
        process(row)
```

---

## 5. ESCRITA EM LOTE

```python
import psycopg2.extras

# Lote até 10k linhas — execute_values
psycopg2.extras.execute_values(
    cur,
    "INSERT INTO events (user_id, type, ts) VALUES %s",
    [(row["user_id"], row["type"], row["ts"]) for row in events],
    page_size=500
)

# Bulk massivo (> 10k linhas) — COPY
import io, csv
buf = io.StringIO()
writer = csv.writer(buf)
for row in data:
    writer.writerow([row["col1"], row["col2"]])
buf.seek(0)
cur.copy_expert("COPY tabela (col1, col2) FROM STDIN WITH CSV", buf)
```

```typescript
// Node.js — unnest para batch insert
const ids = items.map(i => i.id);
const names = items.map(i => i.name);
await pool.query(
    'INSERT INTO items (id, name) SELECT * FROM unnest($1::int[], $2::text[])',
    [ids, names]
);
```

---

## 6. UPSERT

```python
cur.execute("""
    INSERT INTO products (sku, name, price)
    VALUES (%s, %s, %s)
    ON CONFLICT (sku) DO UPDATE SET
        name = EXCLUDED.name,
        price = EXCLUDED.price,
        updated_at = NOW()
""", (sku, name, price))
```

---

## 7. TRANSAÇÕES

```python
conn = get_conn()
try:
    with conn:  # commit automático ao sair, rollback em exceção
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET balance = balance - %s WHERE id = %s", (amount, src))
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE id = %s", (amount, dst))
except psycopg2.Error as e:
    print(f"Erro: {e.pgcode} — {e.pgerror}")
finally:
    release_conn(conn)
```

```typescript
const client = await pool.connect();
try {
    await client.query('BEGIN');
    await client.query('UPDATE accounts SET balance = balance - $1 WHERE id = $2', [amount, src]);
    await client.query('UPDATE accounts SET balance = balance + $1 WHERE id = $2', [amount, dst]);
    await client.query('COMMIT');
} catch (e) {
    await client.query('ROLLBACK');
    throw e;
} finally {
    client.release();
}
```

Não use `autocommit=True` para operações de escrita críticas. Sempre libere a conexão no `finally`.

---

## 8. ÍNDICES

```sql
-- Simples
CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);

-- Composto (igualdade primeiro, range depois)
CREATE INDEX IF NOT EXISTS idx_orders_user_status ON orders (user_id, status);

-- Parcial (menor, mais rápido para subset específico)
CREATE INDEX IF NOT EXISTS idx_orders_pending ON orders (created_at)
WHERE status = 'pending';

-- Nunca bloquear leituras ao criar índice em produção
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_name ON table (col);
```

Verifique o plano antes de finalizar:
```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;
```
`Seq Scan` em tabela grande = adicione ou revise o índice.

---

## 9. DDL ÚTIL

```sql
-- Verificar se tabela existe
SELECT EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'minha_tabela'
);

-- Adicionar coluna sem lock
ALTER TABLE tabela ADD COLUMN IF NOT EXISTS nova_col TEXT DEFAULT NULL;

-- Listar índices
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'tabela';

-- Listar colunas e tipos
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'tabela'
ORDER BY ordinal_position;
```

---

## 10. SERIALIZAÇÃO

```python
import json
from decimal import Decimal
from datetime import datetime

def serialize(obj):
    if isinstance(obj, Decimal): return float(obj)
    if isinstance(obj, datetime): return obj.isoformat()
    raise TypeError(f"Tipo não serializável: {type(obj)}")

json.dumps(rows, default=serialize)
```

```typescript
// pg converte tipos básicos, mas Decimal vem como string
const price = parseFloat(row.price);
```

---

## 11. REVIEW — CHECKLIST DE PROBLEMAS COMUNS

| Categoria | Problema | Severidade |
|---|---|---|
| Segurança | SQL via f-string/concatenação com dado externo | CRÍTICO |
| Segurança | `DROP`, `TRUNCATE` ou `DELETE` sem `WHERE` sem confirmação | CRÍTICO |
| Segurança | Secrets de conexão em código | CRÍTICO |
| Segurança | Expor mensagens de erro do Postgres ao cliente | MAIOR |
| Performance | `OFFSET` em tabelas grandes — use keyset | MAIOR |
| Performance | `fetchall()` em tabela grande — use server-side cursor | MAIOR |
| Performance | Loop de `INSERT` — use `execute_values` ou `COPY` | MAIOR |
| Performance | `autocommit=True` em operações críticas | MAIOR |
| Performance | `Seq Scan` em tabela grande — adicione índice | MAIOR |
| Recursos | Conexão não liberada no `finally` | CRÍTICO |
| Recursos | Pool não configurado — conexão por requisição | MAIOR |

---

## 12. SEGURANÇA — NUNCA FAZER

- SQL via f-string, concatenação ou template string com dado externo
- `autocommit=True` em operações que devem ser atômicas
- Expor mensagens de erro do Postgres ao cliente (contêm schema e nomes de tabela)
- Secrets de conexão em código ou repositório
- `DROP`, `TRUNCATE` ou `DELETE` sem `WHERE` sem confirmação explícita do usuário

---

## 13. CHECKLIST ANTES DE ENTREGAR

- [ ] Conexão via pool, não `connect()` por requisição?
- [ ] Todas as queries usam `%s` / `$1` com parâmetros, sem interpolação?
- [ ] Queries de leitura usam `RealDictCursor`?
- [ ] Índices criados para os campos usados em `WHERE` e `ORDER BY`?
- [ ] `EXPLAIN ANALYZE` rodado para queries em tabelas grandes?
- [ ] Paginação usa keyset em vez de `OFFSET` para grandes volumes?
- [ ] Leitura em volume usa server-side cursor, não `fetchall()`?
- [ ] Inserts em lote usam `execute_values` ou `COPY`, não loop?
- [ ] Operações atômicas dentro de transação explícita?
- [ ] Conexão liberada no `finally`?
- [ ] Credenciais em variáveis de ambiente?
