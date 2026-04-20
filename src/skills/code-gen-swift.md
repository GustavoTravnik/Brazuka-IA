# Skill: Swift iOS Developer

**Role:** Gerador de código Swift idiomático, seguro e pronto para produção em apps iOS/iPadOS.  
**Objetivo:** Produzir código que siga as convenções Swift, use corretamente Concurrency, Combine/async-await, SwiftUI e evite antipadrões comuns da plataforma Apple.

---

## 1. NOMENCLATURA

| Elemento | Padrão | Exemplo |
|---|---|---|
| Types (class, struct, enum, protocol) | `UpperCamelCase` | `UserRepository`, `LoginViewModel` |
| Funções, métodos e variáveis | `lowerCamelCase` | `fetchUser(by:)`, `isLoading` |
| Constantes de módulo | `lowerCamelCase` ou `UPPER_SNAKE_CASE` em `enum` sem casos | `maxRetryCount` |
| Protocolos de capacidade | Sufixo `-able`, `-ing` ou `-Delegate` | `Fetchable`, `UserDelegate` |
| Extensões | Mesmo arquivo quando relacionadas ao tipo; arquivo separado `Type+Feature.swift` caso contrário | `User+Validation.swift` |

---

## 2. FORMATAÇÃO

- Indentação: **4 espaços** (padrão Xcode)
- Comprimento máximo de linha: **120 chars**
- Chaves na mesma linha: `if condition {`
- Sem ponto e vírgula
- `guard` preferido a `if let` quando o fluxo deve retornar/lançar em caso de ausência
- Trailing comma em listas multilinhas
- Imports em ordem alfabética; Foundation e UIKit/SwiftUI primeiro

---

## 3. VALUE TYPES vs REFERENCE TYPES

```swift
// Prefira struct para dados — imutáveis por padrão, copiados, thread-safe
struct User {
    let id: String
    let name: String
    let email: String
}

// Use class apenas quando identidade, herança ou ciclo de vida compartilhado for necessário
final class UserRepository {
    // ...
}

// Marque classes como final por padrão — habilite herança explicitamente se necessário
final class LoginViewModel: ObservableObject { }
```

- `enum` para modelar estados e erros de domínio — evita valores inválidos impossíveis de representar
- `actor` para estado mutável compartilhado entre concorrentes

---

## 4. OPTIONALS E SEGURANÇA

```swift
// guard let para falha antecipada
func process(token: String?) {
    guard let token else { return }
    // token é String não-opcional aqui
}

// Nunca force unwrap fora de testes e IBOutlets com garantia visual
let name = user!.name  // ❌ proibido em produção

// if let apenas para ramificação com dois caminhos válidos
if let cached = cache[id] {
    return cached
}

// Nil coalescing para valores padrão
let displayName = user.nickname ?? user.name

// Retorne Result<T, Error> de operações falíveis em vez de Optional
func fetchUser(id: String) async -> Result<User, UserError>
```

---

## 5. CONCORRÊNCIA MODERNA (SWIFT CONCURRENCY)

```swift
// async/await — o padrão para código novo
func fetchUser(id: String) async throws -> User {
    let dto = try await apiService.getUser(id: id)
    return dto.toDomain()
}

// Task para operações disparadas de contexto síncrono
func onLoginTapped() {
    Task {
        await viewModel.login(email: email, password: password)
    }
}

// actor para estado mutável compartilhado — elimina race conditions
actor UserCache {
    private var storage: [String: User] = [:]

    func get(id: String) -> User? { storage[id] }
    func set(_ user: User) { storage[user.id] = user }
}

// MainActor para atualizar UI
@MainActor
final class LoginViewModel: ObservableObject {
    @Published private(set) var state: LoginState = .idle

    func login(email: String, password: String) async {
        state = .loading
        do {
            let user = try await loginUseCase(email: email, password: password)
            state = .success(user)
        } catch {
            state = .failure(error)
        }
    }
}
```

- **Nunca** `DispatchQueue.main.async` em código novo — use `@MainActor`
- **Nunca** `DispatchQueue.global().async` em código novo — use `Task.detached` ou `async let`
- **Nunca** misture `completion handlers` com `async/await` sem adaptador explícito (`withCheckedContinuation`)
- Use `async let` para paralelizar operações independentes

---

## 6. ARQUITETURA (MVVM + Clean)

```
App/
├── Data/
│   ├── Network/         # URLSession services, DTOs, decodificadores
│   ├── Persistence/     # CoreData / SwiftData contexts e entities
│   └── Repository/      # Implementações concretas de repositório
├── Domain/
│   ├── Model/           # Structs de domínio (sem deps de framework)
│   ├── Repository/      # Protocolos de repositório
│   └── UseCase/         # Um arquivo por operação de negócio
├── Presentation/
│   ├── Feature/
│   │   ├── FeatureView.swift
│   │   ├── FeatureViewModel.swift
│   │   └── FeatureState.swift   # enum de estado
│   └── Navigation/
└── DI/                  # Composição de dependências (puro Swift ou Needle/Swinject)
```

```swift
// UseCase como struct callable
struct LoginUseCase {
    let repository: UserRepositoryProtocol

    func callAsFunction(email: String, password: String) async throws -> User {
        try await repository.login(email: email, password: password)
    }
}

// Estado como enum com valores associados
enum LoginState: Equatable {
    case idle
    case loading
    case success(User)
    case failure(String)
}
```

---

## 7. SWIFTUI

```swift
// View sem estado próprio — recebe binding ou callbacks
struct LoginView: View {
    @StateObject private var viewModel: LoginViewModel

    var body: some View {
        VStack(spacing: 16) {
            TextField("E-mail", text: $viewModel.email)
            SecureField("Senha", text: $viewModel.password)
            Button("Entrar") {
                Task { await viewModel.login() }
            }
            .disabled(viewModel.state == .loading)
        }
        .padding()
    }
}

// Prefira @StateObject para objetos criados pela view
// @ObservedObject para objetos injetados externamente
// @EnvironmentObject apenas para dependências globais (tema, sessão)
```

- Extraia subviews em computed properties ou tipos separados quando o `body` ultrapassar ~50 linhas
- Prefira `ViewModifier` a duplicar estilo entre views
- Evite lógica de negócio dentro de `body` — delegue ao ViewModel

---

## 8. NETWORKING (URLSESSION)

```swift
struct APIClient {
    private let session: URLSession
    private let decoder: JSONDecoder

    func request<T: Decodable>(_ endpoint: Endpoint) async throws -> T {
        let (data, response) = try await session.data(for: endpoint.urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw APIError.httpError(statusCode: httpResponse.statusCode)
        }
        return try decoder.decode(T.self, from: data)
    }
}

// Endpoint como enum ou struct para centralizar URLs e parâmetros
struct Endpoint {
    let path: String
    let method: HTTPMethod
    let body: Encodable?
}
```

- Nunca coloque URLs hardcoded espalhadas pelo código — centralize em `Endpoint`
- Sempre trate os status codes HTTP explicitamente
- Use `URLSession.shared` apenas em protótipos — injete `URLSession` para testabilidade

---

## 9. PERSISTÊNCIA (SWIFTDATA / COREDATA)

```swift
// SwiftData — preferido para projetos iOS 17+
@Model
final class UserRecord {
    var id: String
    var name: String
    var email: String
    var createdAt: Date

    init(id: String, name: String, email: String) {
        self.id = id
        self.name = name
        self.email = email
        self.createdAt = .now
    }
}

// Acesso via ModelContext — sempre em background para operações pesadas
func saveUser(_ user: User, in context: ModelContext) throws {
    let record = UserRecord(id: user.id, name: user.name, email: user.email)
    context.insert(record)
    try context.save()
}
```

---

## 10. SEGURANÇA — NUNCA FAZER

- Hardcode de API keys ou tokens no código-fonte ou em arquivos `.plist` versionados
- Armazenar tokens de acesso em `UserDefaults` — use **Keychain**
- `http://` em produção — configure `App Transport Security` e use sempre `https://`
- Logar dados sensíveis (token, CPF, senha) sem mascaramento
- Desabilitar `NSAllowsArbitraryLoads` no `Info.plist` em produção
- Expor stack traces de erro ao usuário final

---

## 11. CHECKLIST ANTES DE ENTREGAR

- [ ] Nenhum force unwrap (`!`) fora de testes e IBOutlets garantidos?
- [ ] Toda atualização de UI em `@MainActor` ou thread principal?
- [ ] `Task` com ciclo de vida gerenciado (cancelado no `onDisappear` quando necessário)?
- [ ] Tokens armazenados no Keychain, não em UserDefaults?
- [ ] URLSession injetada para testabilidade?
- [ ] Nenhuma URL hardcoded fora de `Endpoint`?
- [ ] SwiftData/CoreData acessados em background para operações de escrita pesada?
- [ ] `final` em todas as classes sem herança intencional?
- [ ] Build sem warnings (`xcodebuild clean build | xcpretty`)?
- [ ] Nenhuma credencial em arquivos `.plist` ou `.xcconfig` versionados?
