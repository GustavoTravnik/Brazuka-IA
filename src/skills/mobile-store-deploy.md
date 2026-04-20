# Skill: Mobile Store Deploy — Google Play & Apple App Store

**Role:** Especialista em publicação e automação de deploy de apps móveis nas lojas Google Play e Apple App Store.  
**Objetivo:** Garantir que o processo de build, assinatura, versionamento e publicação seja reproduzível, seguro e automatizável via CI/CD — para apps Flutter, Kotlin (Android) e Swift (iOS).

---

## 1. VERSIONAMENTO

### Semântica de versão mobile

```
MAJOR.MINOR.PATCH  →  ex: 2.5.1
```

| Campo | Quando incrementar |
|---|---|
| `MAJOR` | Reescrita, breaking change de experiência ou API |
| `MINOR` | Nova feature para o usuário |
| `PATCH` | Bugfix, hotfix, ajuste de UI sem nova funcionalidade |

### Android — `build.gradle` ou `build.gradle.kts`

```kotlin
android {
    defaultConfig {
        versionCode = 47          // inteiro incremental — obrigatório no Play
        versionName = "2.5.1"    // exibido ao usuário
    }
}
```

- `versionCode` deve ser **sempre maior** que o código da versão anterior na track
- Nunca reutilize um `versionCode` já publicado — o Play rejeita

### iOS — `pubspec.yaml` (Flutter) ou Xcode

```yaml
# Flutter — pubspec.yaml
version: 2.5.1+47   # formato: versionName+buildNumber
```

```
# Xcode — Info.plist / INFOPLIST_KEY_*
CFBundleShortVersionString = 2.5.1   # versionName
CFBundleVersion             = 47     # buildNumber (inteiro incremental)
```

- `CFBundleVersion` (build number) deve ser maior que o da última build enviada ao TestFlight

---

## 2. ASSINATURA — ANDROID (KEYSTORE)

```bash
# Gerar keystore (apenas uma vez — guarde com segurança)
keytool -genkey -v \
  -keystore release.keystore \
  -alias release-key \
  -keyalg RSA -keysize 2048 \
  -validity 10000

# Nunca versione o .keystore nem o key.properties
```

```properties
# key.properties — fora do repositório, injetado por CI/CD
storeFile=../release.keystore
storePassword=${KEYSTORE_PASSWORD}
keyAlias=release-key
keyPassword=${KEY_PASSWORD}
```

```kotlin
// build.gradle.kts — leitura via arquivo externo
val keyProperties = Properties().apply {
    load(rootProject.file("key.properties").inputStream())
}

signingConfigs {
    create("release") {
        storeFile     = file(keyProperties["storeFile"] as String)
        storePassword = keyProperties["storePassword"] as String
        keyAlias      = keyProperties["keyAlias"] as String
        keyPassword   = keyProperties["keyPassword"] as String
    }
}

buildTypes {
    release {
        signingConfig = signingConfigs.getByName("release")
        isMinifyEnabled = true
        proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
    }
}
```

---

## 3. ASSINATURA — IOS (CERTIFICATES & PROVISIONING)

### Tipos de perfil

| Perfil | Uso |
|---|---|
| `Development` | Testes em dispositivo físico durante desenvolvimento |
| `Ad Hoc` | Distribuição interna para dispositivos registrados |
| `App Store` | Submissão à App Store Connect |
| `Enterprise` | Distribuição interna corporativa (Apple Developer Enterprise) |

### Fluxo de assinatura automática (Xcode)

```
Xcode → Signing & Capabilities → Automatically manage signing: ON
Team: [Selecione o time correto]
```

- Para CI/CD: use **Match** (Fastlane) para sincronizar certificados e profiles via repositório criptografado
- Nunca exporte o `.p12` sem senha — armazene no vault de secrets do CI

### Fastlane Match (recomendado)

```ruby
# Matchfile
git_url("git@github.com:empresa/ios-certificates.git")
type("appstore")  # development | adhoc | appstore | enterprise
app_identifier(["com.empresa.app"])
username("ci@empresa.com")
```

```bash
# Instalar/renovar certificados no agente de CI
bundle exec fastlane match appstore --readonly
```

---

## 4. BUILD DE PRODUÇÃO

### Android

```bash
# APK (legado — evite para novas submissões)
./gradlew assembleRelease

# AAB — formato obrigatório para novas apps no Google Play desde agosto/2021
./gradlew bundleRelease

# Artefato: app/build/outputs/bundle/release/app-release.aab
```

### iOS (via xcodebuild)

```bash
# Archive
xcodebuild \
  -workspace App.xcworkspace \
  -scheme App \
  -configuration Release \
  -archivePath build/App.xcarchive \
  archive

# Export IPA
xcodebuild \
  -exportArchive \
  -archivePath build/App.xcarchive \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath build/ipa

# ExportOptions.plist — define método de distribuição
# method: app-store | ad-hoc | enterprise | development
```

### Flutter

```bash
# Android AAB
flutter build appbundle --release

# iOS IPA
flutter build ipa --release --export-options-plist=ExportOptions.plist
```

---

## 5. PUBLICAÇÃO — GOOGLE PLAY (FASTLANE SUPPLY)

### Tracks disponíveis

| Track | Audiência |
|---|---|
| `internal` | Até 100 testadores internos; liberação imediata |
| `alpha` | Testadores opt-in (closed testing) |
| `beta` | Testadores opt-in (open testing) |
| `production` | Todos os usuários; rollout gradual configurável |

```bash
# Publicar AAB na track internal
bundle exec fastlane supply \
  --aab app/build/outputs/bundle/release/app-release.aab \
  --track internal \
  --json_key gplay-service-account.json \
  --package_name com.empresa.app

# Promover de internal para production com rollout de 10%
bundle exec fastlane supply \
  --track internal \
  --track_promote_to production \
  --rollout 0.1 \
  --json_key gplay-service-account.json \
  --package_name com.empresa.app
```

### Service Account

1. Google Play Console → Setup → API access → Link to Google Cloud project
2. Google Cloud Console → IAM → Create service account → Role: **Release Manager**
3. Baixe o JSON da service account → armazene no vault de CI, nunca no repositório

---

## 6. PUBLICAÇÃO — APPLE APP STORE (FASTLANE DELIVER / PILOT)

### TestFlight (beta)

```bash
# Upload para TestFlight
bundle exec fastlane pilot upload \
  --ipa build/ipa/App.ipa \
  --api_key_path fastlane/app-store-connect-key.json \
  --skip_waiting_for_build_processing true
```

### App Store Connect (produção)

```bash
# Upload e submissão para revisão
bundle exec fastlane deliver \
  --ipa build/ipa/App.ipa \
  --api_key_path fastlane/app-store-connect-key.json \
  --submit_for_review true \
  --automatic_release false \
  --force true
```

### App Store Connect API Key (recomendado — sem 2FA)

1. App Store Connect → Users and Access → Keys → Generate API Key
2. Baixe o `.p8` → armazene no vault, nunca no repositório
3. Anote `Key ID` e `Issuer ID` — necessários para autenticação

```json
// fastlane/app-store-connect-key.json (gerado pelo fastlane)
{
  "key_id": "XXXXXXXXXX",
  "issuer_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
}
```

---

## 7. CI/CD — GITHUB ACTIONS

### Android — Build e Publish

```yaml
name: Android Release

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'

      - name: Decode Keystore
        run: echo "${{ secrets.KEYSTORE_BASE64 }}" | base64 -d > release.keystore

      - name: Write key.properties
        run: |
          echo "storeFile=../../release.keystore" > android/key.properties
          echo "storePassword=${{ secrets.KEYSTORE_PASSWORD }}" >> android/key.properties
          echo "keyAlias=${{ secrets.KEY_ALIAS }}" >> android/key.properties
          echo "keyPassword=${{ secrets.KEY_PASSWORD }}" >> android/key.properties

      - uses: subosito/flutter-action@v2   # ou actions/setup-java para Kotlin puro
        with:
          flutter-version: '3.x'

      - run: flutter pub get
      - run: flutter build appbundle --release

      - name: Publish to Play Store
        uses: r0adkll/upload-google-play@v1
        with:
          serviceAccountJsonPlainText: ${{ secrets.GPLAY_SERVICE_ACCOUNT_JSON }}
          packageName: com.empresa.app
          releaseFiles: build/app/outputs/bundle/release/app-release.aab
          track: internal
```

### iOS — Build e Publish

```yaml
name: iOS Release

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4

      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.x'

      - name: Install certificates via Fastlane Match
        env:
          MATCH_PASSWORD: ${{ secrets.MATCH_PASSWORD }}
          MATCH_GIT_BASIC_AUTHORIZATION: ${{ secrets.MATCH_GIT_AUTH }}
        run: bundle exec fastlane match appstore --readonly

      - run: flutter pub get
      - run: flutter build ipa --release --export-options-plist=ExportOptions.plist

      - name: Upload to TestFlight
        env:
          APP_STORE_CONNECT_API_KEY_KEY_ID: ${{ secrets.ASC_KEY_ID }}
          APP_STORE_CONNECT_API_KEY_ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          APP_STORE_CONNECT_API_KEY_KEY: ${{ secrets.ASC_PRIVATE_KEY }}
        run: bundle exec fastlane pilot upload --ipa build/ios/ipa/*.ipa --skip_waiting_for_build_processing true
```

---

## 8. SECRETS — O QUE NUNCA VAI NO REPOSITÓRIO

| Secret | Onde armazenar |
|---|---|
| `release.keystore` | CI Secrets (base64 encoded) |
| `key.properties` | Gerado em runtime no CI |
| `gplay-service-account.json` | CI Secrets |
| `app-store-connect-key.json` / `.p8` | CI Secrets |
| Certificados `.p12` e provisioning profiles | Fastlane Match (repo criptografado) |
| `MATCH_PASSWORD` | CI Secrets |

- Nunca comite arquivos `.keystore`, `.p12`, `.p8` ou JSONs de service account
- Adicione ao `.gitignore`: `*.keystore`, `key.properties`, `*.p8`, `*.p12`, `gplay*.json`, `fastlane/app-store-connect-key.json`

---

## 9. PRÉ-CHECKLIST DE SUBMISSÃO

### Google Play

- [ ] `versionCode` maior que o da última publicação?
- [ ] AAB assinado com keystore de produção (não debug)?
- [ ] `minSdk` compatível com a faixa de dispositivos alvo?
- [ ] Screenshots e descritivos atualizados no Console?
- [ ] Política de privacidade acessível e atualizada?
- [ ] Permissões declaradas no manifest justificadas na ficha da loja?

### Apple App Store

- [ ] `CFBundleVersion` (build number) maior que o da última build no TestFlight/Store?
- [ ] Provisioning profile do tipo `App Store` usado no archive?
- [ ] Todos os devices e simuladores testados (iPhone, iPad se universal)?
- [ ] Screenshots nos tamanhos exigidos (6.9", 6.5", 5.5", iPad Pro se necessário)?
- [ ] Política de privacidade declarada no App Store Connect?
- [ ] Dados de login de teste fornecidos para o revisor (se o app requer autenticação)?
- [ ] Nenhuma referência a outras plataformas (Android, Play Store) nos textos do app?
- [ ] Export Compliance respondido corretamente (criptografia)?

---

## 10. CHECKLIST DE AUTOMAÇÃO CI/CD

- [ ] Nenhum secret hardcoded no YAML de pipeline?
- [ ] Keystore decodificado em runtime e deletado ao final do job?
- [ ] `versionCode`/`buildNumber` incrementado automaticamente (pode usar `GITHUB_RUN_NUMBER`)?
- [ ] Build de release testado antes do upload (`flutter test`, `./gradlew test`)?
- [ ] Upload para track `internal` antes de `production`?
- [ ] Notificação de sucesso/falha configurada (Slack, e-mail)?
- [ ] Rollout gradual configurado para produção (iniciar com 10–20%)?
