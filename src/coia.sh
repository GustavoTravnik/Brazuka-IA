#!/bin/bash
# Wrapper portável do COIA — resolve o venv automaticamente sem precisar de `source`.
# Adicione ao .bashrc:
#   alias coia="/caminho/para/coia/src/coia.sh"
#   alias coia-web="/caminho/para/coia/src/coia-web.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Sobe o proxy do agente em background (ignora se já estiver rodando)
openco-proxy start &>/dev/null &

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ venv não encontrado em $SCRIPT_DIR/.venv"
    echo "   Execute dentro de $SCRIPT_DIR:"
    echo "     python3 -m venv .venv"
    echo "     source .venv/bin/activate"
    echo "     pip install -r requirements.txt"
    exit 1
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/app.py" "$@"
