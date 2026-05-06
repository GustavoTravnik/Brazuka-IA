$ErrorActionPreference = "Stop"

# --- Criando ambiente virtual ---
if (!(Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual..." -ForegroundColor Cyan
    python3 -m venv ./src/.venv
}

# Verifica se o pip3 realmente existe antes de tentar usar
$pipPath = ".\src\.venv\Scripts\pip.exe"

if (!(Test-Path $pipPath)) {
    Write-Host "Erro: O ambiente virtual foi criado, mas o pip nao foi encontrado em $pipPath." -ForegroundColor Red
    Write-Host "Tentando reparar o ambiente virtual..." -ForegroundColor Yellow
    python3 -m venv --clear .venv
    
    if (!(Test-Path $pipPath)) {
        Write-Host "Falha critica: Nao foi possivel criar o ambiente virtual com pip." -ForegroundColor Red
        exit 1
    }
}

# --- Instalando dependencias ---
Write-Host "Instalando dependencias..." -ForegroundColor Cyan
# Usando o caminho absoluto para evitar erro de reconhecimento
$absPipPath = (Resolve-Path $pipPath).Path
& $absPipPath install --upgrade pip -q
& $absPipPath install -r src\requirements.txt

# --- Configuracao do .env ---
if (!(Test-Path "src\.env")) {
    Write-Host "Copiando src\.env.dev para src\.env..." -ForegroundColor Yellow
    Copy-Item "src\.env.dev" "src\.env"
    Write-Host "Arquivo src\.env criado." -ForegroundColor Green
} else {
    Write-Host "Arquivo src\.env ja existe - nenhuma alteracao feita." -ForegroundColor Blue
}

Write-Host "`nSetup concluido!" -ForegroundColor Green

Write-Host "Ative o ambiente: .\.venv\Scripts\Activate.ps1"

# --- Aliases (Profile do PowerShell) ---
Write-Host ""
$resposta = Read-Host "Deseja adicionar os aliases 'coia' e 'coia-web' ao seu perfil do PowerShell? [s/N]"

if ($resposta -eq "s" -or $resposta -eq "S") {
    # Garante que temos um caminho de perfil, mesmo que $PROFILE esteja vazio
    $PROFILE_PATH = $PROFILE
    if ([string]::IsNullOrEmpty($PROFILE_PATH)) {
        $PROFILE_PATH = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "WindowsPowerShell\Microsoft.PowerShell_profile.ps1"
    }

    # Cria o arquivo e as pastas do perfil se nao existirem
    if (!(Test-Path $PROFILE_PATH)) {
        Write-Host "Criando arquivo de perfil em: $PROFILE_PATH" -ForegroundColor Yellow
        $parentDir = Split-Path -Parent $PROFILE_PATH
        if (!(Test-Path $parentDir)) { 
            New-Item -Path $parentDir -ItemType Directory -Force | Out-Null
        }
        New-Item -Path $PROFILE_PATH -ItemType File -Force | Out-Null
    }

    $PROJECT_DIR = Get-Location
    $ALIAS_CONTENT = @"

# COIA - AI CLI Assistant
function coia { & "$PROJECT_DIR\src\coia.bat" `$args }
function coia-web { & "$PROJECT_DIR\src\coia-web.bat" `$args }
"@

    # Verifica se ja existe para nao duplicar
    $existente = Get-Content $PROFILE_PATH -ErrorAction SilentlyContinue
    if ($existente -like "*function coia {*") {
        Write-Host "Aliases ja existem no seu perfil." -ForegroundColor Blue
    } else {
        Add-Content -Path $PROFILE_PATH -Value $ALIAS_CONTENT
        Write-Host "Aliases adicionados ao perfil com sucesso!" -ForegroundColor Green
        Write-Host "Reinicie o terminal ou rode: . `"$PROFILE_PATH`"" -ForegroundColor Cyan
    }
} else {
    Write-Host "Aliases nao adicionados." -ForegroundColor Blue
}