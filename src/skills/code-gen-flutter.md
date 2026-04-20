# Skill: Flutter Developer

**Role:** Gerador de código Flutter/Dart idiomático, performático e pronto para produção em apps iOS e Android.  
**Objetivo:** Produzir código que siga as convenções Dart/Flutter, use corretamente gerenciamento de estado, null safety e evite antipadrões comuns da plataforma.

---

## 1. NOMENCLATURA

| Elemento | Padrão | Exemplo |
|---|---|---|
| Classes, mixins, extensions, enums | `UpperCamelCase` | `UserRepository`, `LoginCubit` |
| Variáveis, funções, parâmetros | `lowerCamelCase` | `fetchUser`, `isLoading` |
| Constantes | `lowerCamelCase` (Dart não usa SCREAMING_SNAKE) | `maxRetryCount` |
| Arquivos e pastas | `snake_case` | `login_screen.dart`, `user_repository.dart` |
| Extensões privadas | Prefixo `_` | `_UserExtension` |

---

## 2. FORMATAÇÃO

- Indentação: **2 espaços** (padrão Dart/Flutter)
- Comprimento máximo de linha: **80 chars** (`dart format` impõe automaticamente)
- Trailing comma obrigatória em listas e parâmetros multilinhas — habilita formatação correta do `dart format`
- Use `dart format .` antes de todo commit
- Imports em ordem: SDK Dart → packages Flutter/third-party → imports internos (separados por linha em branco)

```dart
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'package:myapp/domain/user.dart';
```

---

## 3. NULL SAFETY

```dart
// ✅ Tipos não-nulos por padrão — Dart sound null safety
String name = 'João';        // nunca nulo
String? nickname;            // pode ser nulo

// Null-aware operators
final display = user.nickname ?? user.name;
user.address?.city?.let(print);

// late — apenas quando a inicialização é garantida antes do uso
late final UserRepository _repository;

// Nunca force unwrap sem razão
final value = maybeNull!;  // ❌ lança se nulo — use apenas quando logicamente impossível ser nulo
```

---

## 4. GERENCIAMENTO DE ESTADO — BLOC/CUBIT

```dart
// Cubit — para estados simples sem eventos complexos
class LoginCubit extends Cubit<LoginState> {
  LoginCubit(this._loginUseCase) : super(const LoginState.idle());

  final LoginUseCase _loginUseCase;

  Future<void> login(String email, String password) async {
    emit(const LoginState.loading());
    final result = await _loginUseCase(email: email, password: password);
    result.fold(
      (failure) => emit(LoginState.failure(failure.message)),
      (user) => emit(LoginState.success(user)),
    );
  }
}

// Estado como sealed class (Dart 3+) ou freezed
@freezed
sealed class LoginState with _$LoginState {
  const factory LoginState.idle() = _Idle;
  const factory LoginState.loading() = _Loading;
  const factory LoginState.success(User user) = _Success;
  const factory LoginState.failure(String message) = _Failure;
}

// View — BlocConsumer para estado + efeitos colaterais
class LoginView extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return BlocConsumer<LoginCubit, LoginState>(
      listener: (context, state) {
        if (state is _Success) {
          context.go(Routes.home);
        }
      },
      builder: (context, state) => switch (state) {
        _Idle() || _Failure() => _LoginForm(),
        _Loading() => const CircularProgressIndicator(),
        _Success() => const SizedBox.shrink(),
      },
    );
  }
}
```

- **Nunca** `setState` para lógica de negócio — apenas para estado efêmero de UI local
- **Nunca** `BuildContext` dentro de `async` sem verificar `mounted`
- **Nunca** acesse `BlocProvider.of` dentro de callbacks assíncronos sem capturar antes

---

## 5. ARQUITETURA (CLEAN + FEATURE-FIRST)

```
lib/
├── core/
│   ├── di/              # Injeção de dependência (get_it + injectable)
│   ├── network/         # DioClient, interceptors, endpoints
│   ├── error/           # Failure classes, Either
│   └── utils/           # Extensions, helpers sem framework
├── features/
│   ├── login/
│   │   ├── data/
│   │   │   ├── datasources/   # Remote e local data sources
│   │   │   ├── models/        # DTOs com fromJson/toJson
│   │   │   └── repositories/  # Implementações
│   │   ├── domain/
│   │   │   ├── entities/      # Entidades puras sem deps de framework
│   │   │   ├── repositories/  # Interfaces (abstract class)
│   │   │   └── usecases/      # Um arquivo por caso de uso
│   │   └── presentation/
│   │       ├── cubit/
│   │       ├── pages/
│   │       └── widgets/
└── main.dart
```

```dart
// UseCase — callable class com Either para erros
class LoginUseCase {
  const LoginUseCase(this._repository);

  final UserRepository _repository;

  Future<Either<Failure, User>> call({
    required String email,
    required String password,
  }) =>
      _repository.login(email: email, password: password);
}
```

---

## 6. WIDGETS — BOAS PRÁTICAS

```dart
// Prefira StatelessWidget — só use StatefulWidget para estado efêmero de UI
class PrimaryButton extends StatelessWidget {
  const PrimaryButton({
    required this.label,
    required this.onPressed,
    super.key,
  });

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return ElevatedButton(
      onPressed: onPressed,
      child: Text(label),
    );
  }
}

// const widgets — sempre que possível; Flutter pula a reconstrução
const SizedBox(height: 16)
const Text('Entrar')

// Extraia widgets em classes, não em métodos — métodos burlam a otimização do engine
// ❌
Widget _buildButton() => ElevatedButton(...);

// ✅
class _LoginButton extends StatelessWidget { ... }
```

- Sempre passe `key` em widgets de lista dinâmica (`ListView.builder`)
- Use `RepaintBoundary` em animações pesadas para isolar a repintura
- Prefira `ListView.builder` a `ListView` com children para listas potencialmente grandes

---

## 7. NETWORKING (DIO)

```dart
@singleton
class DioClient {
  DioClient(AppConfig config) {
    _dio = Dio(BaseOptions(
      baseUrl: config.apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 30),
    ))
      ..interceptors.addAll([
        AuthInterceptor(),
        LogInterceptor(requestBody: !config.isProduction),
      ]);
  }

  late final Dio _dio;

  Future<Response<T>> get<T>(String path) => _dio.get(path);
  Future<Response<T>> post<T>(String path, {Object? data}) =>
      _dio.post(path, data: data);
}

// Data source — trate DioException explicitamente
Future<UserDto> getUser(String id) async {
  try {
    final response = await _client.get<Map<String, dynamic>>('/users/$id');
    return UserDto.fromJson(response.data!);
  } on DioException catch (e) {
    throw _mapToFailure(e);
  }
}
```

---

## 8. INJEÇÃO DE DEPENDÊNCIA (GET_IT + INJECTABLE)

```dart
// Anote as classes
@singleton
class DioClient { ... }

@lazySingleton
class UserRemoteDataSource { ... }

@injectable
class LoginUseCase { ... }

// Gere com: flutter pub run build_runner build --delete-conflicting-outputs

// Registre o Cubit via BlocProvider na árvore de widgets
BlocProvider(
  create: (context) => getIt<LoginCubit>(),
  child: const LoginPage(),
)
```

---

## 9. PERSISTÊNCIA LOCAL

```dart
// SharedPreferences — apenas para dados simples não-sensíveis
final prefs = await SharedPreferences.getInstance();
await prefs.setString('locale', 'pt-BR');

// flutter_secure_storage — para tokens e dados sensíveis
const storage = FlutterSecureStorage();
await storage.write(key: 'access_token', value: token);

// drift (SQLite) — para dados estruturados locais
@DriftDatabase(tables: [Users, Orders])
class AppDatabase extends _$AppDatabase { ... }
```

- **Nunca** armazene tokens em `SharedPreferences` — use `flutter_secure_storage`
- Migrations obrigatórias no Drift ao alterar schema

---

## 10. SEGURANÇA — NUNCA FAZER

- Hardcode de API keys ou secrets em `dart` files ou `pubspec.yaml`
- Armazenar tokens em `SharedPreferences`
- Usar `http://` em produção — configure `network_security_config` (Android) e ATS (iOS)
- Logar dados sensíveis com `print()` ou `log()` em produção
- Expor stack traces completos ao usuário
- `flutter build apk --debug` ou `--profile` para publicar na store

---

## 11. CHECKLIST ANTES DE ENTREGAR

- [ ] `dart format .` executado sem alterações pendentes?
- [ ] `dart analyze` sem erros ou warnings?
- [ ] Nenhum `BuildContext` usado após `await` sem verificação de `mounted`?
- [ ] Tokens em `flutter_secure_storage`, não em `SharedPreferences`?
- [ ] Widgets extraídos como classes, não como métodos privados?
- [ ] `const` aplicado em todos os widgets elegíveis?
- [ ] `key` passado em todos os widgets dentro de listas dinâmicas?
- [ ] `Either<Failure, T>` nos UseCases de domínio?
- [ ] Cubit emitindo estados imutáveis (freezed ou const)?
- [ ] `flutter build apk --release` e `flutter build ipa` executando sem erros?
