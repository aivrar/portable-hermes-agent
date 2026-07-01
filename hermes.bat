@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python_embedded"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

:: Handle commands
if /i "%~1"=="setup" (
    if not exist "%PYTHON_EXE%" (
        echo Python not found. Running first-time install...
        call "%SCRIPT_DIR%install.bat"
        goto :eof
    )
    echo Running Hermes setup wizard...
    cd /d "%SCRIPT_DIR%"
    "%PYTHON_EXE%" -m hermes_cli.main setup
    goto :eof
)

if /i "%~1"=="install" (
    echo Running full install...
    call "%SCRIPT_DIR%install.bat"
    goto :eof
)

if /i "%~1"=="help" (
    echo.
    echo   Hermes Agent - Windows Launcher
    echo   =========================================
    echo.
    echo   Usage:
    echo     hermes.bat              Launch interactive CLI
    echo     hermes.bat setup        Run the setup wizard
    echo     hermes.bat install      Run full install/reinstall
    echo     hermes.bat model        Choose LLM provider/model
    echo     hermes.bat tools        Configure enabled tools
    echo     hermes.bat gateway      Start messaging gateway
    echo     hermes.bat doctor       Diagnose issues
    echo     hermes.bat help         Show this help
    echo.
    echo   Any other arguments are passed through to the Hermes CLI.
    echo.
    goto :eof
)

:: Check if Python is installed
if not exist "%PYTHON_EXE%" (
    echo Python not found. Running first-time setup...
    echo.
    call "%SCRIPT_DIR%install.bat" %*
    goto :eof
)

:: Auto-create .env from template if missing
if not exist "%SCRIPT_DIR%.env" (
    if exist "%SCRIPT_DIR%.env.example" (
        copy "%SCRIPT_DIR%.env.example" "%SCRIPT_DIR%.env" >nul
    )
)

:: Auto-create cli-config.yaml from template if missing
if not exist "%SCRIPT_DIR%cli-config.yaml" (
    if exist "%SCRIPT_DIR%cli-config.yaml.example" (
        copy "%SCRIPT_DIR%cli-config.yaml.example" "%SCRIPT_DIR%cli-config.yaml" >nul
    )
)

:: Create ~/.hermes and copy default personality if missing
if not exist "%USERPROFILE%\.hermes" mkdir "%USERPROFILE%\.hermes"
if not exist "%USERPROFILE%\.hermes\SOUL.md" (
    if exist "%SCRIPT_DIR%assets\SOUL.md" (
        copy "%SCRIPT_DIR%assets\SOUL.md" "%USERPROFILE%\.hermes\SOUL.md" >nul
    )
)

:: Clear stray API keys from other tools (LM Studio, OpenAI CLI, etc.)
:: Hermes manages its own credentials via ~/.hermes/.env — external keys
:: from the user's shell cause auth mismatches and silent failures.
set "OPENAI_API_KEY="
set "OPENAI_BASE_URL="
set "ANTHROPIC_API_KEY="
set "ANTHROPIC_TOKEN="

:: Set up PATH for embedded Python + node tools (must be FIRST to override system)
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%SCRIPT_DIR%node_modules\.bin;%PATH%"

:: Lock pip installs to portable Python
set "PIP_TARGET=%PYTHON_DIR%\Lib\site-packages"
set "PIP_PREFIX=%PYTHON_DIR%"
set "PYTHONPATH=%PYTHON_DIR%\Lib\site-packages"

:: Expose portable Python path so tools and the agent can find it
set "HERMES_PYTHON=%PYTHON_EXE%"
set "HERMES_ROOT=%SCRIPT_DIR%"

:: Set terminal working directory
if not defined TERMINAL_CWD set "TERMINAL_CWD=%SCRIPT_DIR%"

:: Fix Windows console encoding for Unicode (box-drawing chars, emojis)
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul 2>&1

:: Launch Hermes
cd /d "%SCRIPT_DIR%"
echo   Loading Hermes Agent...
"%PYTHON_EXE%" -m hermes_cli.main %*

endlocal
