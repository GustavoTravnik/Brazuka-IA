@echo off
set SCRIPT_DIR=%~dp0
echo.
echo Adicionando aliases temporarios para esta sessao do CMD...
doskey coia="%SCRIPT_DIR%coia.bat" $*
doskey coia-web="%SCRIPT_DIR%coia-web.bat" $*
echo ✅ coia e coia-web estao prontos para uso neste terminal.
echo.
echo Para tornar permanente, adicione a pasta "%SCRIPT_DIR%" ao seu PATH.
pause
