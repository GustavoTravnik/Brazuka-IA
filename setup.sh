#!/bin/bash
set -e

# --- Verificação e instalação do Python ---
if ! command -v python3 &>/dev/null; then
    echo "⚠️  Python3 não encontrado. Instalando..."

    if command -v apt &>/dev/null; then
        sudo apt update -q && sudo apt install -y python3 python3-venv python3-pip
    elif command -v brew &>/dev/null; then
        brew install python3
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm python
    else
        echo "❌ Gerenciador de pacotes não reconhecido. Instale o Python3 manualmente: https://www.python.org/downloads/"
        exit 1
    fi

    echo "✅ Python3 instalado: $(python3 --version)"
else
    echo "✅ Python3 encontrado: $(python3 --version)"
fi

echo "🔧 Criando ambiente virtual..."
python3 -m venv .venv

echo "📦 Instalando dependências..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r src/requirements.txt

if [ ! -f src/.env ]; then
    echo "⚙️  Copiando src/.env.dev para src/.env..."
    cp src/.env.dev src/.env
    echo "✅ Arquivo src/.env criado. Edite-o com suas configurações antes de iniciar."
else
    echo "ℹ️  src/.env já existe — nenhuma alteração feita."
fi

echo ""
echo "✅ Setup concluído!"
echo "   Ative o ambiente: source .venv/bin/activate"

# --- Aliases no .bashrc ---
echo ""
read -rp "Deseja adicionar os aliases 'coia' e 'coia-web' ao seu ~/.bashrc? [s/N] " resposta

if [[ "$resposta" =~ ^[sS]$ ]]; then
    PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
    ALIAS_COIA="alias coia=\"$PROJECT_DIR/src/coia.sh\""
    ALIAS_COIA_WEB="alias coia-web=\"$PROJECT_DIR/src/coia-web.sh\""

    if grep -qF "alias coia=" ~/.bashrc; then
        echo "ℹ️  Alias 'coia' já existe no ~/.bashrc — nenhuma alteração feita."
    else
        echo "" >> ~/.bashrc
        echo "# COIA — AI CLI Assistant" >> ~/.bashrc
        echo "$ALIAS_COIA" >> ~/.bashrc
        echo "$ALIAS_COIA_WEB" >> ~/.bashrc
        echo "✅ Aliases adicionados ao ~/.bashrc."
        echo "   Recarregue com: source ~/.bashrc"
    fi
else
    echo "ℹ️  Aliases não adicionados."
    echo "   Para adicionar manualmente, coloque no seu ~/.bashrc:"
    PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
    echo "   alias coia=\"$PROJECT_DIR/src/coia.sh\""
    echo "   alias coia-web=\"$PROJECT_DIR/src/coia-web.sh\""
fi
