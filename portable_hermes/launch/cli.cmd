@echo off
:: hermes.bat: the Hermes command line, plus the portable commands
:: setup, install, update and help.
::
:: Run through the one-line hermes.bat in the install folder, which sets
:: PORTABLE_HERMES_ROOT and makes the install folder the current directory.
:: Delayed expansion stays off so arguments containing ! reach Hermes intact.
:: The main part is one parenthesised block, so files replaced while it runs
:: (an update started from inside Hermes) cannot change it.
setlocal disabledelayedexpansion
for %%I in ("%PORTABLE_HERMES_ROOT%") do set "PH_ROOT=%%~fI"
call .\portable_hermes\launch\env.cmd %*
if errorlevel 1 exit /b 1

:: "hermes update" is the portable updater (UPDATE.bat): the wrapper channel
:: first, then an optional core refresh. Upstream's own updater would swap
:: the whole tree from NousResearch and drop the portable files.
if /i "%~1"=="update" call .\portable_hermes\launch\update.cmd %* & call exit /b %%ERRORLEVEL%%
if /i "%~1"=="install" call .\install.bat & call exit /b %%ERRORLEVEL%%
if /i "%~1"=="help" goto :help

(
    call .\portable_hermes\launch\prepare.cmd cli
    if errorlevel 1 exit /b 1

    rem Create the selected Hermes home and copy older portable-root config.
    if not exist "%HERMES_HOME%" mkdir "%HERMES_HOME%"
    if not exist "%HERMES_HOME%\.env" (
        if exist "%PH_ROOT%\.env" (
            copy "%PH_ROOT%\.env" "%HERMES_HOME%\.env" >nul
        ) else if exist "%PH_ROOT%\.env.example" (
            copy "%PH_ROOT%\.env.example" "%HERMES_HOME%\.env" >nul
        )
    )
    if not exist "%HERMES_HOME%\config.yaml" (
        if exist "%PH_ROOT%\cli-config.yaml" (
            copy "%PH_ROOT%\cli-config.yaml" "%HERMES_HOME%\config.yaml" >nul
        ) else if exist "%PH_ROOT%\cli-config.yaml.example" (
            copy "%PH_ROOT%\cli-config.yaml.example" "%HERMES_HOME%\config.yaml" >nul
        )
    )
    if not exist "%HERMES_HOME%\SOUL.md" if exist "%PH_ROOT%\assets\SOUL.md" (
        copy "%PH_ROOT%\assets\SOUL.md" "%HERMES_HOME%\SOUL.md" >nul
    )

    rem Clear stray API keys from other tools such as LM Studio or OpenAI CLI.
    rem Hermes reads its own credentials from the Hermes home .env; keys from
    rem the user's shell cause auth mismatches and silent failures.
    set "OPENAI_API_KEY="
    set "OPENAI_BASE_URL="
    set "ANTHROPIC_API_KEY="
    set "ANTHROPIC_TOKEN="

    rem Portable Python and node tools first on PATH; pip stays in this folder.
    set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PH_ROOT%\node_modules\.bin;%PATH%"
    set "PIP_TARGET=%PYTHON_DIR%\Lib\site-packages"
    set "PYTHONPATH=%PYTHON_DIR%\Lib\site-packages"
    if not defined TERMINAL_CWD set "TERMINAL_CWD=%PH_ROOT%\"
    chcp 65001 >nul 2>&1

    if /i "%~1"=="setup" (
        echo Running Hermes setup wizard...
        "%PYTHON_EXE%" -m hermes_cli.main setup
        call exit /b %%ERRORLEVEL%%
    )
    rem Launch-time repair: restore portable files an upstream update replaced.
    rem Fast, and never fails the launch; problems with the portable tools are
    rem always printed.
    "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." repair --quiet
    echo   Loading Hermes Agent...
    "%PYTHON_EXE%" -m hermes_cli.main %*
    call exit /b %%ERRORLEVEL%%
)

:help
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
exit /b 0
