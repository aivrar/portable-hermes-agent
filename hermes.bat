@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python_embedded"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
if not defined HERMES_HOME set "HERMES_HOME=%USERPROFILE%\.hermes"

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

:: "hermes update" goes to the portable updater: the wrapper channel first,
:: then an optional core refresh. Upstream's own updater would swap the whole
:: tree from NousResearch and drop the portable files until the next launch.
if /i "%~1"=="update" goto :portable_update

if /i "%~1"=="help" (
    echo.
    echo   Hermes Agent - Windows Launcher
    echo   =========================================
    echo.
    echo   Usage:
    echo     hermes.bat              Launch interactive CLI
    echo     hermes.bat setup        Run the setup wizard
    echo     hermes.bat install      Run full install/reinstall
    echo     hermes.bat update       Update Portable Hermes, then optionally the core
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

:: Create the selected Hermes home and migrate older portable-root config.
if not exist "%HERMES_HOME%" mkdir "%HERMES_HOME%"
if not exist "%HERMES_HOME%\.env" (
    if exist "%SCRIPT_DIR%.env" (
        copy "%SCRIPT_DIR%.env" "%HERMES_HOME%\.env" >nul
    ) else if exist "%SCRIPT_DIR%.env.example" (
        copy "%SCRIPT_DIR%.env.example" "%HERMES_HOME%\.env" >nul
    )
)

if not exist "%HERMES_HOME%\config.yaml" (
    if exist "%SCRIPT_DIR%cli-config.yaml" (
        copy "%SCRIPT_DIR%cli-config.yaml" "%HERMES_HOME%\config.yaml" >nul
    ) else if exist "%SCRIPT_DIR%cli-config.yaml.example" (
        copy "%SCRIPT_DIR%cli-config.yaml.example" "%HERMES_HOME%\config.yaml" >nul
    )
)

:: Copy the default personality if missing.
if not exist "%HERMES_HOME%\SOUL.md" (
    if exist "%SCRIPT_DIR%assets\SOUL.md" (
        copy "%SCRIPT_DIR%assets\SOUL.md" "%HERMES_HOME%\SOUL.md" >nul
    )
)

:: Clear stray API keys from other tools (LM Studio, OpenAI CLI, etc.)
:: Hermes manages its own credentials via ~/.hermes/.env - external keys
:: from the user's shell cause auth mismatches and silent failures.
set "OPENAI_API_KEY="
set "OPENAI_BASE_URL="
set "ANTHROPIC_API_KEY="
set "ANTHROPIC_TOKEN="

:: Set up PATH for embedded Python + node tools (must be FIRST to override system)
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%SCRIPT_DIR%node_modules\.bin;%PATH%"

:: Lock pip installs to portable Python
set "PIP_TARGET=%PYTHON_DIR%\Lib\site-packages"
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

:: Launch-time repair: restore portable files an upstream update replaced and
:: settle an interrupted update. Fast, and never blocks or fails the launch.
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); from portable_hermes.__main__ import main; main(['repair', '--quiet'])" "%SCRIPT_DIR%." 2>nul

echo   Loading Hermes Agent...
"%PYTHON_EXE%" -m hermes_cli.main %*

endlocal
goto :eof

:portable_update
if not exist "%PYTHON_EXE%" (
    echo Python not found. Running first-time install...
    call "%SCRIPT_DIR%install.bat"
    goto :eof
)
cd /d "%SCRIPT_DIR%"
set "PYTHONIOENCODING=utf-8"
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); from portable_hermes.__main__ import main; sys.exit(main(sys.argv[1:]))" "%SCRIPT_DIR%." %*
exit /b %ERRORLEVEL%
