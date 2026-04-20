# Skill: .NET / C# Developer

**Role:** Escrever e revisar código C#/.NET idiomático, performático e seguro.  
**Ativação:** Sempre que precisar gerar ou revisar código C#/.NET, independente do tipo de projeto.

---

## 1. NOMENCLATURA

| Elemento | Padrão | Exemplo |
|---|---|---|
| Classes, métodos, propriedades, eventos | `PascalCase` | `UserService`, `GetById` |
| Campos privados | `_camelCase` | `_repository` |
| Parâmetros e variáveis locais | `camelCase` | `userId`, `isActive` |
| Constantes e `static readonly` | `PascalCase` | `MaxRetries` |
| Interfaces | `IPascalCase` | `IUserRepository` |
| Tipos genéricos | `TPascalCase` ou letra única | `TResult`, `T` |

---

## 2. FORMATAÇÃO

- Indentação: **4 espaços**, nunca tabs
- Chaves em **linha própria** (estilo Allman): `if (x)\n{`
- Uma declaração por linha
- `using` directives: System primeiro → third-party → locais, separados por linha em branco
- Linha máxima: **120 chars** — checar `.editorconfig` do projeto

---

## 3. ASYNC / AWAIT

```csharp
// ✅ Correto
public async Task<User> GetUserAsync(int id, CancellationToken ct = default)
{
    return await _repository.FindAsync(id, ct);
}
```

- Todo método async retorna `Task` ou `Task<T>` — nunca `async void` (exceto event handlers)
- **Nunca** `.Result` ou `.Wait()` — causa deadlock em contextos síncronos
- **Nunca** `await` dentro de `lock`
- Sempre propague `CancellationToken` em métodos de I/O
- Em bibliotecas (não aplicações): use `ConfigureAwait(false)`
- Não use `Task.Run` para encapsular código já assíncrono
- Operações independentes: `await Task.WhenAll(a, b)` em vez de `await a; await b;`

---

## 4. INJEÇÃO DE DEPENDÊNCIA

```csharp
builder.Services.AddScoped<IOrderService, OrderService>();
```

| Lifetime | Quando usar |
|---|---|
| `Singleton` | Stateless, thread-safe, sem dependências Scoped |
| `Scoped` | Por requisição HTTP — padrão para serviços de domínio |
| `Transient` | Stateful, leve, criado a cada uso |

- **Nunca** instancie manualmente o que deve ser injetado
- **Nunca** injete Scoped em Singleton (captive dependency)
- **Nunca** use `ServiceLocator`/`IServiceProvider` dentro de serviço

---

## 5. ENTITY FRAMEWORK CORE

```csharp
// Leitura sem modificação — sempre AsNoTracking
var users = await _db.Users
    .AsNoTracking()
    .Where(u => u.IsActive)
    .ToListAsync(ct);

// Evitar N+1 — Include explícito
var orders = await _db.Orders
    .Include(o => o.Items)
    .Where(o => o.Status == OrderStatus.Pending)
    .ToListAsync(ct);

// SaveChanges fora de loops
foreach (var item in items) { item.Status = Status.Done; }
await _db.SaveChangesAsync(ct);
```

- Nunca `.ToList()` antes de filtrar — filtre primeiro, materialize depois
- Nunca raw SQL sem parâmetros — use `FromSqlInterpolated` ou EF puro
- Use `IQueryable` no repositório, não `IEnumerable`

---

## 6. GERENCIAMENTO DE RECURSOS

```csharp
// Sempre using para IDisposable
await using var connection = new SqlConnection(connStr);
using var stream = File.OpenRead(path);

// HttpClient — nunca instanciar manualmente
var client = _httpClientFactory.CreateClient("api");
```

- Todo `IDisposable` dentro de `using` ou `await using`
- Nunca instancie `HttpClient` diretamente — use `IHttpClientFactory`
- Conexões de banco sempre dentro de `using`
- Streams sempre fechados mesmo em exceção

---

## 7. PADRÕES DE PERFORMANCE

| Situação | ❌ Evitar | ✅ Usar |
|---|---|---|
| Strings em loop | `s += item` | `StringBuilder` |
| Filtrar coleção | `.ToList()` antes de filtrar | Filtre na query (IQueryable) |
| Leitura sem modificação | `.Find()` com tracking | `.AsNoTracking()` |
| Múltiplas chamadas async | `await a; await b;` | `await Task.WhenAll(a, b)` |
| Tempo atual | `DateTime.Now` | `DateTime.UtcNow` |
| Coleções grandes | `new List<T>()` | `new List<T>(capacidade)` |
| Null safety em cadeia | `obj.Prop1.Prop2` | null-check ou `?.` |

---

## 8. SEGURANÇA — NUNCA FAZER

- SQL via interpolação de string com dado do usuário
- Secrets em `appsettings.json` — use `Secret Manager`, variáveis de ambiente ou vault
- `JsonSerializerSettings` com `TypeNameHandling.All` — execução arbitrária
- CORS com `AllowAnyOrigin` + `AllowCredentials` simultaneamente
- Logar dado sensível (senha, token, CPF) sem mascaramento
- `#pragma warning disable` sem comentário justificando

---

## 9. LINT E FERRAMENTAS

```bash
dotnet build --no-incremental
dotnet format --verify-no-changes
```

- **`dotnet format`** — formatação oficial (built-in desde .NET 6)
- **EditorConfig** (`.editorconfig`) — indentação, charset, line endings
- **Roslyn Analyzers** — warnings de qualidade no build
- **`<TreatWarningsAsErrors>true</TreatWarningsAsErrors>`** — em produção
- **`<Nullable>enable</Nullable>`** — nullable reference types habilitado

---

## 10. REVIEW — CHECKLIST DE PROBLEMAS COMUNS

### Async/Await
- [ ] `async void` fora de event handlers
- [ ] `.Result` ou `.Wait()` em código assíncrono — deadlock
- [ ] `await` dentro de `lock`
- [ ] Falta de `ConfigureAwait(false)` em bibliotecas
- [ ] `Task.Run` desnecessário para código já assíncrono

### LINQ e Collections
- [ ] `ToList()` antes de filtrar — materializa antes de precisar
- [ ] `IEnumerable` onde `IQueryable` permitiria filtro no banco
- [ ] `.Count()` a cada iteração de `foreach` — O(n²)
- [ ] `First()` sem `OrDefault` quando coleção pode ser vazia

### Entity Framework Core
- [ ] N+1: navegação dentro de loop sem `Include()`
- [ ] `.ToList()` antes de filtrar — traz todos do banco
- [ ] Tracking desnecessário em leitura — use `.AsNoTracking()`
- [ ] `SaveChanges` dentro de loop

### Null Safety
- [ ] Dereferência sem null-check em tipos nullable
- [ ] Cadeia `obj.Prop1.Prop2` sem null-check
- [ ] Nullable reference types habilitado mas avisos ignorados com `!`

### Gerenciamento de Recursos
- [ ] `IDisposable` sem `using`
- [ ] `HttpClient` instanciado dentro de método
- [ ] Conexão de banco sem `using`
- [ ] Stream não fechado em exceção

### Injeção de Dependência
- [ ] `Scoped` injetado em `Singleton` — captive dependency
- [ ] `new` em classe que deveria ser injetada
- [ ] `ServiceLocator` manual

### Performance
- [ ] String concatenado em loop — use `StringBuilder`
- [ ] `DateTime.Now` em lógica de domínio — use `DateTime.UtcNow`
- [ ] Boxing desnecessário de value types

---

## 11. FORMATO DE SAÍDA PARA CODE REVIEW

```
## Code Review — .NET

### Problemas encontrados

| # | Arquivo/Trecho | Severidade | Problema | Correção sugerida |
|---|---|---|---|---|
| 1 | `UserService.cs:42` | CRÍTICO | `.Result` em método async causa deadlock | Substituir por `await` |
| 2 | `OrderRepository.cs:18` | MAIOR | Query sem `.AsNoTracking()` em leitura | Adicionar `.AsNoTracking()` após `DbSet` |

### Prompt de correções

Corrija os seguintes problemas no código .NET:

1. [CRÍTICO] Em `<arquivo>:<linha>`: <descrição e como corrigir>
2. [MAIOR] Em `<arquivo>:<linha>`: <descrição e como corrigir>

Priorize os itens CRÍTICOS. Mantenha o estilo e convenções existentes.
```

**Severidades:**
- **CRÍTICO:** exceção em produção, falha de segurança, deadlock, vazamento de recurso
- **MAIOR:** degradação de performance, antipadrão que compromete manutenção
- **MENOR:** convenção, legibilidade, otimização não urgente

---

## 12. CHECKLIST ANTES DE ENTREGAR

- [ ] Nenhum `async void` fora de event handlers?
- [ ] Nenhum `.Result` ou `.Wait()`?
- [ ] `CancellationToken` propagado em métodos de I/O?
- [ ] Todo `IDisposable` dentro de `using`?
- [ ] Queries de leitura com `AsNoTracking()`?
- [ ] Nenhum `Include` faltando?
- [ ] `SaveChanges` fora de loops?
- [ ] Nenhum secret em código ou `appsettings.json`?
- [ ] `dotnet build` sem warnings?
- [ ] Nomenclatura seguindo convenções C#?
