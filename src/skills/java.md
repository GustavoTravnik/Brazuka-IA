# Skill: Java Developer

**Role:** Escrever e revisar código Java idiomático, performático e seguro.  
**Ativação:** Sempre que precisar gerar ou revisar código Java.

---

## 1. NOMENCLATURA

| Elemento | Padrão | Exemplo |
|---|---|---|
| Classes e interfaces | `PascalCase` | `UserService`, `OrderRepository` |
| Métodos e variáveis | `camelCase` | `getUserById`, `isActive` |
| Constantes (`static final`) | `UPPER_SNAKE_CASE` | `MAX_RETRIES` |
| Pacotes | `lowercase.separado.por.ponto` | `com.empresa.pedidos` |
| Tipos genéricos | Letra única maiúscula ou sufixo `Type` | `T`, `E`, `KeyType` |

---

## 2. FORMATAÇÃO

- Indentação: **4 espaços** (padrão Oracle) ou **2 espaços** (Google Style) — seguir o do projeto
- Comprimento máximo de linha: **100 chars**
- Chaves na mesma linha do bloco (K&R/Java): `if (x) {`
- Chaves obrigatórias em **todos** os blocos `if`/`for`/`while`, mesmo de uma linha
- Linha em branco entre membros distintos da classe
- **Nunca** imports com wildcard (`import java.util.*`)
- Imports: static → java/javax → terceiros → locais

---

## 3. NULL SAFETY E OPTIONAL

```java
// Prefira Optional em retornos que podem ser ausentes
public Optional<User> findById(Long id) {
    return repository.findById(id);
}

// Nunca Optional.get() sem verificação
user.orElseThrow(() -> new UserNotFoundException(id));
user.ifPresent(u -> process(u));
String name = user.map(User::getName).orElse("Anônimo");

// Valide parâmetros de entrada
public void process(String input) {
    Objects.requireNonNull(input, "input não pode ser nulo");
}
```

- Anote parâmetros com `@NonNull`/`@Nullable` em APIs públicas
- **Nunca** retorne `null` de método público — use `Optional` ou coleção vazia

---

## 4. GERENCIAMENTO DE RECURSOS

```java
// Sempre try-with-resources para Closeable
try (var conn = dataSource.getConnection();
     var stmt = conn.prepareStatement(sql)) {
    stmt.setLong(1, userId);
    try (var rs = stmt.executeQuery()) {
        // processar
    }
}
```

- **Nunca** `close()` manual sem `try-with-resources` — vaza recurso em exceção

---

## 5. EXCEÇÕES

```java
// Exceção de domínio
public class UserNotFoundException extends RuntimeException {
    public UserNotFoundException(Long id) {
        super("Usuário não encontrado: " + id);
    }
}

// Sempre preserve a causa ao re-lançar
try {
    riskyOperation();
} catch (IOException e) {
    throw new ServiceException("Falha ao processar", e); // nunca omitir 'e'
}
```

- **Nunca** `catch (Exception e) {}` — engole silenciosamente
- **Nunca** `catch (Exception e) { e.printStackTrace(); }` — use logger
- **Nunca** `throw new RuntimeException("msg")` sem a causa como segundo argumento
- **Nunca** `return` dentro de `finally` — suprime a exceção do `try`

---

## 6. JPA / SPRING DATA

```java
// Projeção com DTO em vez de entidade completa
@Query("SELECT new com.app.dto.UserDto(u.id, u.name) FROM User u WHERE u.active = true")
List<UserDto> findActiveUserDtos();

// Evitar N+1 — fetch join
@Query("SELECT o FROM Order o JOIN FETCH o.items WHERE o.status = :status")
List<Order> findWithItems(@Param("status") OrderStatus status);

// Batch insert
repository.saveAll(listaDeEntidades);
```

- `@Transactional` apenas em métodos de serviço — **nunca** em `private` ou em controllers
- Sempre paginação em queries que podem retornar muitos registros: `Pageable pageable`

---

## 7. PADRÕES DE PERFORMANCE

| Situação | ❌ Evitar | ✅ Usar |
|---|---|---|
| Strings em loop | `s = s + x` | `StringBuilder` |
| Busca em coleção | `ArrayList.contains()` em loop | `HashSet.contains()` |
| HashMap com volume conhecido | `new HashMap<>()` sem capacidade | `new HashMap<>(capacidade, 0.75f)` |
| Data/hora thread-safe | `SimpleDateFormat` | `DateTimeFormatter` |
| Comparação de String | `str1 == str2` | `str1.equals(str2)` |
| Coleção imutável | `Collections.unmodifiableList(...)` | `List.of(...)` (Java 9+) |

---

## 8. CONCORRÊNCIA

```java
// Campos compartilhados entre threads
private final AtomicInteger counter = new AtomicInteger(0);
private final Map<String, Value> cache = new ConcurrentHashMap<>();

// Minimize o escopo do synchronized
synchronized (lock) {
    // apenas o trecho crítico
}
```

- `SimpleDateFormat` é **não thread-safe** — instancie localmente ou use `DateTimeFormatter`
- `HashMap` em contexto concorrente — use `ConcurrentHashMap`

---

## 9. SEGURANÇA — NUNCA FAZER

- SQL via concatenação de string — use `PreparedStatement` ou JPA
- Deserialização de `ObjectInputStream` com dado não confiável
- `Math.random()` para tokens de segurança — use `SecureRandom`
- Logar dado sensível sem mascaramento
- Secrets hardcoded
- Getter que expõe campo mutável: retorne cópia defensiva `return new ArrayList<>(this.items)`

---

## 10. LINT E FERRAMENTAS

```bash
mvn compile checkstyle:check spotbugs:check -q
# ou
gradle check
```

- **`mvn checkstyle:check`** / **`gradle checkstyleMain`** — convenções de estilo
- **`SpotBugs`** / **`PMD`** — análise estática de bugs

---

## 11. REVIEW — CHECKLIST DE PROBLEMAS COMUNS

### Exceções
- [ ] `catch (Exception e) {}` ou com `e.printStackTrace()` sem re-throw
- [ ] Re-lançamento sem preservar a causa: `throw new Ex("msg")` sem `e`
- [ ] `return` dentro de `finally`
- [ ] Exceção genérica onde específica seria mais precisa

### Null Safety
- [ ] `Optional.get()` sem verificação
- [ ] Método público retornando `null`
- [ ] Cadeia sem null-check: `obj.getProp().getValue()`

### Recursos
- [ ] `Connection`, `InputStream` ou qualquer `Closeable` sem `try-with-resources`
- [ ] `close()` manual — vaza em exceção

### JPA / Spring Data
- [ ] N+1: navegação dentro de loop sem `JOIN FETCH`
- [ ] `save()` dentro de loop — use `saveAll()`
- [ ] `@Transactional` em método `private` — não funciona via proxy Spring
- [ ] `@Transactional` em controller
- [ ] JPQL via concatenação com dado externo

### Concorrência
- [ ] `SimpleDateFormat` como campo estático — não thread-safe
- [ ] `HashMap` em contexto multithreaded
- [ ] Getter expondo campo mutável sem cópia defensiva

### Segurança
- [ ] SQL via concatenação
- [ ] `Math.random()` para tokens
- [ ] Dado sensível logado sem mascaramento
- [ ] Secret hardcoded

### Performance
- [ ] Concatenação de `String` em loop com `+`
- [ ] `ArrayList.contains()` em loop
- [ ] `.size()` recalculado a cada iteração

---

## 12. FORMATO DE SAÍDA PARA CODE REVIEW

```
## Code Review — Java

### Problemas encontrados

| # | Arquivo/Trecho | Severidade | Problema | Correção sugerida |
|---|---|---|---|---|
| 1 | `UserService.java:88` | CRÍTICO | `catch (Exception e) {}` engole o erro | Logar e re-lançar |
| 2 | `OrderRepository.java:43` | MAIOR | N+1 sem JOIN FETCH | Adicionar `JOIN FETCH o.items` na query |

### Prompt de correções

Corrija os seguintes problemas no código Java:

1. [CRÍTICO] Em `<arquivo>:<linha>`: <descrição e como corrigir>
2. [MAIOR] Em `<arquivo>:<linha>`: <descrição e como corrigir>

Priorize os itens CRÍTICOS. Mantenha o estilo e convenções existentes.
```

**Severidades:**
- **CRÍTICO:** exceção em produção, falha de segurança, deadlock, vazamento de recurso
- **MAIOR:** N+1, antipadrão Spring/JPA, concorrência incorreta, degradação de performance
- **MENOR:** convenção, `Optional` não usado onde caberia

---

## 13. CHECKLIST ANTES DE ENTREGAR

- [ ] Nenhum `catch` silencioso?
- [ ] Causa original preservada ao re-lançar?
- [ ] Todo `Closeable` dentro de `try-with-resources`?
- [ ] Nenhum retorno `null` de método público?
- [ ] `Optional.get()` nunca chamado sem verificação?
- [ ] Nenhum `SimpleDateFormat` como campo estático?
- [ ] N+1 eliminado com fetch join ou `saveAll`?
- [ ] `@Transactional` apenas em métodos de serviço não-privados?
- [ ] Strings comparadas com `.equals()`, nunca `==`?
- [ ] Sem secrets hardcoded?
- [ ] Sem imports wildcards?
- [ ] Build sem warnings?
