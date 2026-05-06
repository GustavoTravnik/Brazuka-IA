@echo off
set SCRIPT_DIR=%~dp0
set VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo ❌ venv não encontrado em %SCRIPT_DIR%.venv
    echo    Execute dentro de %SCRIPT_DIR%:
    echo      python -m venv .venv
    echo      .venv\Scripts\activate
    echo      pip install -r requirements.txt
    exit /b 1
)

"%VENV_PYTHON%" "%SCRIPT_DIR%app.py" %*
