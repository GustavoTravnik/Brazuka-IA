#!/bin/bash
# Wrapper portável do COIA Web Panel — resolve o venv automaticamente.
# Adicione ao .bashrc:
#   alias coia-web="/caminho/para/coia/src/coia-web.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ venv não encontrado em $SCRIPT_DIR/.venv"
    echo "   Execute dentro de $SCRIPT_DIR:"
    echo "     python3 -m venv .venv"
    echo "     source .venv/bin/activate"
    echo "     pip install -r requirements.txt"
    exit 1
fi

echo "🚀 COIA Panel → http://localhost:5005"
exec "$VENV_PYTHON" "$SCRIPT_DIR/panel/server.py" "$@"
