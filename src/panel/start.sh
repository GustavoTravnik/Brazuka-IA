#!/bin/bash
# Inicia o COIA Panel na porta 5005
cd "$(dirname "$0")/.."

VENV_PYTHON=".venv/bin/python3"
if [ -f "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
else
    PYTHON="python3"
fi

echo "🚀 COIA Panel → http://localhost:5005 (python: $PYTHON)"
"$PYTHON" panel/server.py
