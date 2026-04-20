# Skill: Kotlin Android Developer

**Role:** Gerador de código Kotlin idiomático, seguro e pronto para produção em apps Android.  
**Objetivo:** Produzir código que siga as convenções Kotlin/Android, use corretamente Coroutines, Flow, Jetpack e evite antipadrões comuns da plataforma.

---

## 1. NOMENCLATURA

| Elemento | Padrão | Exemplo |
|---|---|---|
| Classes, objetos, interfaces | `PascalCase` | `UserRepository`, `LoginViewModel` |
| Funções e variáveis | `camelCase` | `fetchUserById`, `isLoading` |
| Constantes (`const val`) | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Pacotes | `lowercase.separado.por.ponto` | `com.empresa.feature.login` |
| Parâmetros de tipo genérico | Letra única maiúscula | `T`, `R`, `E` |
| Arquivos de extensão | `NomeDoTipoExtensions.kt` | `StringExtensions.kt` |

---

## 2. FORMATAÇÃO

- Indentação: **4 espaços**
- Comprimento máximo de linha: **120 chars**
- Chaves na mesma linha do bloco: `if (x) {`
- `when` preferido a cadeias de `if/else if`
- Sem ponto e vírgula — Kotlin não usa
- Trailing comma permitida e incentivada em listas, parâmetros e `when`
- Uma classe/interface por arquivo (exceto sealed classes e seus subtipos)

---

## 3. NULL SAFETY

```kotlin
// Prefira tipos não-nulos por padrão
fun findUser(id: String): User  // não User?

// Retorne Result ou sealed class para ausência — nunca null de função pública
fun findUser(id: String): Result<User> = runCatching { repository.get(id) }

// Use let/also/run/apply para operar em nullable sem forçar !!
user?.let { sendWelcomeEmail(it) }

// !! é proibido fora de testes — se chegar até !! o design está errado
val name = user!!.name  // ❌ proibido em produção
```

- `lateinit` apenas para injeção de dependência com garantia de inicialização antes do uso
- `by lazy` para inicialização diferida thread-safe de propriedades imutáveis

---

## 4. COROUTINES E FLOW

```kotlin
// ViewModel — scope correto para UI-bound work
class LoginViewModel(private val repo: UserRepository) : ViewModel() {

    private val _state = MutableStateFlow<LoginUiState>(LoginUiState.Idle)
    val state: StateFlow<LoginUiState> = _state.asStateFlow()

    fun login(email: String, password: String) {
        viewModelScope.launch {
            _state.value = LoginUiState.Loading
            repo.login(email, password)
                .onSuccess { _state.value = LoginUiState.Success(it) }
                .onFailure { _state.value = LoginUiState.Error(it.message) }
        }
    }
}

// Repository — retorne Flow para streams, suspend fun para one-shot
interface UserRepository {
    fun observeUsers(): Flow<List<User>>
    suspend fun login(email: String, password: String): Result<User>
}

// Use withContext para mudar dispatcher — nunca bloqueie Main
suspend fun loadFile(path: String): ByteArray = withContext(Dispatchers.IO) {
    File(path).readBytes()
}
```

- **Nunca** `GlobalScope.launch` — use `viewModelScope`, `lifecycleScope` ou scope injetado
- **Nunca** `runBlocking` fora de testes e `main()`
- **Nunca** `Thread.sleep()` dentro de coroutine — use `delay()`
- Prefira `StateFlow` a `LiveData` para estado de UI em código novo
- Use `callbackFlow` para adaptar APIs de callback a Flow

---

## 5. ARQUITETURA (MVVM + Clean)

```
app/
├── data/
│   ├── remote/          # Retrofit services, DTOs
│   ├── local/           # Room DAOs, entities
│   └── repository/      # Implementações de repositório
├── domain/
│   ├── model/           # Entidades de domínio (sem deps de framework)
│   ├── repository/      # Interfaces de repositório
│   └── usecase/         # Um UseCase por operação de negócio
├── presentation/
│   ├── feature/
│   │   ├── FeatureFragment.kt
│   │   ├── FeatureViewModel.kt
│   │   └── FeatureUiState.kt   # sealed class/interface
│   └── navigation/
└── di/                  # Módulos Hilt
```

```kotlin
// UseCase — um arquivo, uma responsabilidade
class LoginUseCase(private val repository: UserRepository) {
    suspend operator fun invoke(email: String, password: String): Result<User> =
        repository.login(email, password)
}

// UiState como sealed interface
sealed interface LoginUiState {
    object Idle : LoginUiState
    object Loading : LoginUiState
    data class Success(val user: User) : LoginUiState
    data class Error(val message: String?) : LoginUiState
}
```

---

## 6. JETPACK COMPOSE (UI)

```kotlin
// Composable sem estado próprio — recebe estado e callbacks
@Composable
fun LoginScreen(
    state: LoginUiState,
    onLoginClick: (String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    // ...
}

// ViewModel conectado na camada de navegação, não dentro do composable folha
@Composable
fun LoginRoute(viewModel: LoginViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LoginScreen(
        state = state,
        onLoginClick = viewModel::login,
    )
}

// Efeitos apenas quando necessário — prefira lógica no ViewModel
LaunchedEffect(state) {
    if (state is LoginUiState.Success) navController.navigate(Route.Home)
}
```

- `remember` para estado local efêmero que não sobrevive a recomposição de processo
- `rememberSaveable` quando precisar sobreviver a death de processo
- Funções composable sem estado são testáveis e reutilizáveis — priorize isso

---

## 7. ROOM (BANCO LOCAL)

```kotlin
@Entity(tableName = "users")
data class UserEntity(
    @PrimaryKey val id: String,
    val name: String,
    val email: String,
    val createdAt: Long,
)

@Dao
interface UserDao {
    @Query("SELECT * FROM users WHERE id = :id")
    suspend fun getById(id: String): UserEntity?

    @Query("SELECT * FROM users ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<UserEntity>>  // Flow para stream reativo

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(user: UserEntity)

    @Delete
    suspend fun delete(user: UserEntity)
}
```

- Nunca acesse o banco na thread principal — Room lança exceção por padrão
- Use `Flow` nos DAOs para observar mudanças em tempo real
- Migrations obrigatórias a cada alteração de schema — nunca use `fallbackToDestructiveMigration` em produção

---

## 8. RETROFIT (HTTP)

```kotlin
interface UserApiService {
    @GET("users/{id}")
    suspend fun getUser(@Path("id") id: String): Response<UserDto>

    @POST("auth/login")
    suspend fun login(@Body request: LoginRequest): Response<AuthDto>
}

// Trate Response<T> — nunca assuma sucesso sem verificar
suspend fun login(email: String, password: String): Result<User> {
    return runCatching {
        val response = api.login(LoginRequest(email, password))
        if (response.isSuccessful) {
            response.body()?.toDomain() ?: error("Corpo vazio na resposta")
        } else {
            error("Erro HTTP ${response.code()}: ${response.errorBody()?.string()}")
        }
    }
}
```

---

## 9. INJEÇÃO DE DEPENDÊNCIA (HILT)

```kotlin
@HiltAndroidApp
class App : Application()

@AndroidEntryPoint
class LoginFragment : Fragment()

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val loginUseCase: LoginUseCase,
) : ViewModel()

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {
    @Provides
    @Singleton
    fun provideRetrofit(): Retrofit = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .addConverterFactory(GsonConverterFactory.create())
        .build()
}
```

---

## 10. SEGURANÇA — NUNCA FAZER

- Hardcode de API keys, tokens ou secrets no código-fonte ou `BuildConfig` público
- Logar dados sensíveis (CPF, token, senha) sem mascaramento
- `http://` em produção — sempre `https://`
- Armazenar tokens de acesso em `SharedPreferences` sem criptografia — use `EncryptedSharedPreferences`
- `allowBackup="true"` sem restrições no `AndroidManifest.xml`
- Desabilitar validação de certificado SSL para "simplificar" desenvolvimento

---

## 11. CHECKLIST ANTES DE ENTREGAR

- [ ] Nenhum `!!` (non-null assertion) fora de testes?
- [ ] Nenhum `GlobalScope` ou `runBlocking` fora de testes/main?
- [ ] `viewModelScope`/`lifecycleScope` usados corretamente?
- [ ] Flow coletado com `collectAsStateWithLifecycle` (não `collectAsState` sem lifecycle)?
- [ ] Room sem `fallbackToDestructiveMigration` em produção?
- [ ] Retrofit tratando `Response<T>` e não assumindo sucesso?
- [ ] Nenhum secret hardcoded no código ou manifest?
- [ ] UseCase com responsabilidade única?
- [ ] UiState modelado como sealed class/interface?
- [ ] Build sem warnings (`./gradlew build --warning-mode all`)?
