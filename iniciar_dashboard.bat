@echo off
setlocal

cd /d "%~dp0"

echo ============================================
echo   Dashboard de Suporte Tecnico - Movidesk
echo ============================================
echo.

where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PY=py"
    ) else (
        echo [ERRO] Python nao foi encontrado neste computador.
        echo Instale em https://python.org ^(marque "Add to PATH" na instalacao^) e tente novamente.
        pause
        exit /b 1
    )
)

echo Verificando/instalando dependencias (pode demorar na primeira vez)...
%PY% -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERRO] Falha ao instalar as dependencias. Verifique sua conexao com a internet.
    pause
    exit /b 1
)

echo.
echo Iniciando o dashboard... o navegador vai abrir automaticamente.
echo Para encerrar, feche esta janela ou pressione Ctrl+C.
echo.

%PY% -m streamlit run dashboard.py

pause
