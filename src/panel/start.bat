@echo off
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%.."

set VENV_PYTHON=.venv\Scripts\python.exe
if exist "%VENV_PYTHON%" (
    set PYTHON="%VENV_PYTHON%"
) else (
    set PYTHON=python
)

echo 🚀 COIA Panel → http://localhost:5005 ^(python: %PYTHON%^)
%PYTHON% panel\server.py
