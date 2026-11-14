@echo off
:: The environment a Hermes process starts with, set in the caller's scope.
::
:: CALLed by cli.cmd, gui.cmd and update.cmd on their one pre-parsed line,
:: after prepare.cmd and right before Python starts, with one argument that
:: is never the user's: cli, cli-setup, gui or update. Always exit code 0.
:: Ends by setting PH_SESSION to that argument, so the step after Python
:: (gui-exit.cmd, update-finish.cmd) can tell "Python ran" from "a check
:: before it stopped".
set "PH_SESSION="
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PH_ROOT%\node_modules\.bin;%PATH%"
chcp 65001 >nul 2>&1
if /i "%~1"=="update" goto :update

:: pip installs stay in the portable Python.
set "PIP_TARGET=%PYTHON_DIR%\Lib\site-packages"
set "PYTHONPATH=%PYTHON_DIR%\Lib\site-packages"
if /i "%~1"=="gui" goto :gui

:: ---- cli, cli-setup ----
if not defined TERMINAL_CWD set "TERMINAL_CWD=%PH_ROOT%\"
:: Create the selected Hermes home and copy older portable-root config.
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
:: Clear stray API keys from other tools such as LM Studio or OpenAI CLI.
:: Hermes reads its own credentials from the Hermes home .env; keys from the
:: user's shell cause auth mismatches and silent failures.
set "OPENAI_API_KEY="
set "OPENAI_BASE_URL="
set "ANTHROPIC_API_KEY="
set "ANTHROPIC_TOKEN="
if /i "%~1"=="cli-setup" (
    echo Running Hermes setup wizard...
    set "PH_SESSION=cli-setup"
    exit /b 0
)
:: Launch-time repair: restore portable files an upstream update replaced.
:: Fast, and never fails the launch; problems with the portable tools are
:: always printed.
"%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." repair --quiet
echo   Loading Hermes Agent...
set "PH_SESSION=cli"
exit /b 0

:gui
set "TERMINAL_CWD=%PH_ROOT%\"
"%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." repair --quiet
set "PH_SESSION=gui"
exit /b 0

:update
echo   Two separate update channels:
echo     1. Portable wrapper - launchers, GUI, portable tools, aivrar releases
echo     2. Hermes core - the agent itself, NousResearch/hermes-agent, optional
echo   Your settings, keys, chats, extensions and custom tools are not touched.
echo.
set "PH_SESSION=update"
exit /b 0
