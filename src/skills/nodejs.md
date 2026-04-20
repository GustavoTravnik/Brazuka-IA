# Skill: Node.js / TypeScript Developer

**Role:** Escrever e revisar código Node.js/TypeScript idiomático, performático e seguro.  
**Ativação:** Sempre que precisar gerar ou revisar código Node.js/TypeScript.

---

## 1. NOMENCLATURA

| Elemento | Padrão | Exemplo |
|---|---|---|
| Variáveis e funções | `camelCase` | `getUserById`, `isActive` |
| Classes e tipos/interfaces | `PascalCase` | `UserService`, `OrderDto` |
| Constantes de módulo | `UPPER_SNAKE_CASE` | `MAX_RETRIES` |
| Arquivos de componente React | `PascalCase.tsx` | `UserCard.tsx` |
| Demais arquivos | `kebab-case.ts` | `user-service.ts` |
| Enums | `PascalCase` com valores `PascalCase` | `OrderStatus.Pending` |

---

## 2. TYPESCRIPT — CONFIGURAÇÃO MÍNIMA

```json
{
  "compilerOptions": {
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noImplicitReturns": true,
    "exactOptionalPropertyTypes": true
  }
}
```

- **Nunca** `as any` — modele o tipo correto ou use `unknown` com narrowing
- **Nunca** `!` (non-null assertion) sem certeza absoluta do valor em runtime
- **Nunca** `@ts-ignore` sem comentário explicando o motivo
- Prefira `interface` para contratos de objeto, `type` para unions e aliases

---

## 3. ASYNC / AWAIT

```typescript
// ✅ Correto — error handling em async
async function fetchUser(id: string): Promise<User> {
  try {
    const response = await api.get(`/users/${id}`);
    return response.data;
  } catch (error) {
    logger.error({ error, id }, 'Falha ao buscar usuário');
    throw error;
  }
}

// ✅ Paralelismo quando operações são independentes
const [user, orders] = await Promise.all([getUser(id), getOrders(id)]);
```

- **Nunca** `await` dentro de `forEach` — use `Promise.all` + `map`
- **Nunca** deixe Promise sem `.catch()` ou `try/catch`
- Em Express: sempre passe erros de handlers async para `next(err)`
- **Nunca** use operações síncronas bloqueantes (`fs.readFileSync`, `crypto.pbkdf2Sync`) em handlers de requisição

---

## 4. TRATAMENTO DE ERROS

```typescript
// Callback — sempre cheque o erro
fs.readFile(path, (err, data) => {
    if (err) {
        logger.error({ err, path }, 'Falha na leitura');
        return callback(err);
    }
    callback(null, data);
});

// Express — middleware de erro
app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
    logger.error({ err }, 'Erro não tratado');
    res.status(500).json({ message: 'Erro interno' }); // nunca expor stack
});
```

- **Nunca** exponha stack trace ao cliente (`res.json(err)` é proibido)
- Use logger estruturado (Pino ou Winston) — **nunca** `console.log` em produção

---

## 5. PADRÕES DE PERFORMANCE

| Situação | ❌ Evitar | ✅ Usar |
|---|---|---|
| Operações async independentes | `await a; await b;` | `await Promise.all([a, b])` |
| Arquivo grande | `fs.readFile` inteiro | stream (`fs.createReadStream`) |
| Cache sem limite | objeto crescendo em memória | `lru-cache` com TTL e tamanho máximo |
| N+1 em ORM | query dentro de loop | batch com `findMany` + `IN` |
| JSON grande em hot path | `JSON.stringify` frequente | cache do resultado serializado |
| Import dinâmico em loop | `require()` a cada chamada | import no topo do módulo |

---

## 6. GERENCIAMENTO DE MEMÓRIA

```typescript
// Event listeners — sempre remover quando não mais necessário
const handler = () => { ... };
emitter.on('event', handler);
emitter.off('event', handler); // ao destruir

// Intervals — sempre limpar
const timer = setInterval(fn, 1000);
clearInterval(timer); // ao destruir
```

- **Nunca** adicione event listener dentro de loop sem garantia de remoção
- Cache em memória sempre com tamanho máximo e TTL
- Evite closures de longa duração retendo referências a objetos grandes

---

## 7. QUALIDADE

- Use `const` por padrão; `let` quando o valor muda; **nunca** `var`
- Use sempre `===` e `!==`, nunca `==`
- Prefira `for...of` a `forEach` quando precisar de `break` ou `continue`
- Uma exportação principal por arquivo
- Dependências de produção em `dependencies`; ferramentas em `devDependencies`

---

## 8. SEGURANÇA — NUNCA FAZER

- `eval()` ou `new Function(input)` com dado do usuário
- `child_process.exec()` com input sem sanitização — use `execFile` com args separados
- Query SQL/NoSQL via template string com dado externo
- Path construído de input do usuário sem validação — path traversal
- `JSON.parse()` sem `try/catch` em dado externo
- `Object.assign({}, req.body)` sem validação de schema — prototype pollution
- Secrets em código-fonte ou `.env` commitado
- `res.json(err)` que expõe stack trace ao cliente

---

## 9. LINT E FERRAMENTAS

```bash
npx tsc --noEmit
npx eslint . --ext .js,.ts,.tsx
npx prettier --check .
```

**ESLint rules críticas:**
- `no-console` — logs de debug em produção
- `no-unused-vars` / `@typescript-eslint/no-unused-vars`
- `eqeqeq` — uso de `==` em vez de `===`
- `no-var`
- `prefer-const`

---

## 10. REVIEW — CHECKLIST DE PROBLEMAS COMUNS

### Async e Event Loop
- [ ] Operação bloqueante no event loop: `fs.readFileSync` em handler de requisição
- [ ] `Promise` sem `.catch()` — unhandled rejection derruba o processo no Node 15+
- [ ] `await` dentro de `forEach`
- [ ] `async` em construtor de classe

### Tratamento de Erros
- [ ] `try/catch` vazio ou com `console.log` e sem re-throw
- [ ] Erro de callback ignorado
- [ ] Express: erro em handler assíncrono sem `next(err)`
- [ ] `process.on('uncaughtException')` para silenciar erros

### Memory Leaks
- [ ] Event listener sem remoção garantida
- [ ] `setInterval` sem `clearInterval`
- [ ] Cache em memória sem TTL ou limite

### Segurança
- [ ] `eval()` ou `new Function(input)` com dado externo
- [ ] `exec()` com input sem sanitização
- [ ] Query SQL/NoSQL via template string
- [ ] `JSON.parse()` sem `try/catch`
- [ ] Prototype pollution via `Object.assign({}, req.body)`
- [ ] `res.json(err)` expondo stack trace

### TypeScript
- [ ] `as any` sem justificativa
- [ ] `!` em valor que pode ser `null`/`undefined` em runtime
- [ ] `@ts-ignore` sem explicação

### Performance
- [ ] `await` em loop sequencial onde `Promise.all` permitiria paralelismo
- [ ] `JSON.stringify` de objeto grande em hot path
- [ ] Leitura de arquivo com `fs.readFile` quando stream resolveria
- [ ] N+1 em ORM

---

## 11. FORMATO DE SAÍDA PARA CODE REVIEW

```
## Code Review — Node.js

### Problemas encontrados

| # | Arquivo/Trecho | Severidade | Problema | Correção sugerida |
|---|---|---|---|---|
| 1 | `userRouter.ts:55` | CRÍTICO | `await` dentro de `forEach` não aguarda Promises | Substituir por `await Promise.all(items.map(async ...))` |
| 2 | `db.js:23` | CRÍTICO | Query SQL via template string com input do usuário | Usar prepared statement com parâmetros `?` |

### Prompt de correções

Corrija os seguintes problemas no código Node.js:

1. [CRÍTICO] Em `<arquivo>:<linha>`: <descrição e como corrigir>
2. [MAIOR] Em `<arquivo>:<linha>`: <descrição e como corrigir>

Priorize os itens CRÍTICOS. Mantenha o estilo e convenções existentes.
```

**Severidades:**
- **CRÍTICO:** crash do processo, falha de segurança, memory leak, perda de erro silenciosa
- **MAIOR:** degradação de performance, antipadrão que compromete manutenção
- **MENOR:** convenção, tipagem fraca, qualidade de log

---

## 12. CHECKLIST ANTES DE ENTREGAR

- [ ] `tsc --noEmit` sem erros?
- [ ] Nenhum `as any` ou `@ts-ignore` sem justificativa?
- [ ] Todo `async` com `try/catch` ou `.catch()`?
- [ ] Nenhum `await` dentro de `forEach`?
- [ ] Operações independentes usando `Promise.all`?
- [ ] Nenhum `console.log` em produção?
- [ ] Nenhum event listener sem remoção garantida?
- [ ] Nenhum `var`?
- [ ] `===` em todas as comparações?
- [ ] Sem secrets em código ou arquivos commitados?
