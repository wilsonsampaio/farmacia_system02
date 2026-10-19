@echo off
REM ============================================================================
REM  FarmaciaSystem — inicializador (Windows)
REM  Uso:  iniciar.bat           sobe na porta 5000
REM        iniciar.bat 8080      sobe na porta 8080
REM  Na primeira execucao cria a pasta data\ com banco, fotos e dados de
REM  exemplo (28 medicamentos, clientes, vendas dos ultimos 60 dias).
REM ============================================================================
setlocal
cd /d "%~dp0"

set "PORTA=%~1"
if "%PORTA%"=="" set "PORTA=5000"

echo ============================================================
echo   FARMACIASYSTEM - Sistema de Gestao de Farmacia
echo ============================================================

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

REM 1) usa o venv se ele ja tiver o Flask
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import flask" >nul 2>nul
    if not errorlevel 1 set "PY=venv\Scripts\python.exe"
)

REM 2) se o Python escolhido nao tem Flask, tenta montar o venv
%PY% -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo   Instalando dependencias em .\venv (primeira execucao)...
    %PY% -m venv venv
    if errorlevel 1 (
        echo   ERRO: nao foi possivel criar o virtualenv.
        echo   Instale o Python 3 em https://www.python.org/downloads/
        echo   e marque "Add python.exe to PATH" na instalacao.
        pause
        exit /b 1
    )
    venv\Scripts\python.exe -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo   ERRO ao instalar as dependencias. Verifique sua internet.
        pause
        exit /b 1
    )
    set "PY=venv\Scripts\python.exe"
)

echo   Python          : %PY%
echo   Porta           : %PORTA%
echo   Acessos iniciais: admin/admin123 ^| gerente/gerente123 ^| caixa/caixa123
echo ============================================================
echo   Os computadores da rede acessam pelo IP desta maquina.
echo   Pressione CTRL+C para encerrar.
echo ============================================================

set "FARMACIA_PORTA=%PORTA%"
%PY% run.py

pause
