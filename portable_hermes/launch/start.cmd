@echo off
:: START.bat: first-time setup when needed, then the GUI (or the CLI when the
:: GUI is not part of this folder).
::
:: Started (not CALLed) by the one-line START.bat in the install folder,
:: which sets PORTABLE_HERMES_ROOT and makes the install folder the current
:: directory. The arguments go to the GUI or CLI untouched: that script is
:: started without CALL, which hands the window over to it.
setlocal disabledelayedexpansion
for %%I in ("%PORTABLE_HERMES_ROOT%") do set "PH_ROOT=%%~fI"
call .\portable_hermes\launch\env.cmd
if errorlevel 1 exit /b 1
title Portable Hermes Agent
:: GitHub's source download cannot be installed: install.bat says so (exit
:: code 12) before the welcome text promises a setup. Same test as there.
:: Started without CALL: the window is handed over to install.bat.
if not exist "%PH_ROOT%\tools\update_hermes_tool.py" if not exist "%PH_ROOT%\portable_hermes\release.json" if not exist "%PH_ROOT%\.git" .\install.bat
set "PH_FIRST="
if not exist "%PYTHON_EXE%" set "PH_FIRST=1"
if exist "%PH_STATE%\installing" set "PH_FIRST=1"
if defined PH_FIRST (
    echo.
    echo  ============================================
    echo   Portable Hermes Agent - First Time Setup
    echo  ============================================
    echo.
    echo   Welcome. This is your first time running
    echo   Hermes Agent. I need to download a few
    echo   things to get started:
    echo.
    echo     - Python %PH_PYTHON_PIN%, portable, stays in this folder
    echo     - The latest Hermes Agent core from NousResearch
    echo     - AI libraries and dependencies
    echo     - LM Studio SDK, for local models
    echo.
    echo   This takes about 5-10 minutes on a fast
    echo   connection. Nothing is installed system-wide.
    echo.
    if defined PH_PAUSE (
        echo   Press any key to begin setup...
        pause >nul
    )
)
echo.
echo   Starting Hermes Agent...
echo.
if exist "%PH_ROOT%\gui\app.py" .\portable_hermes\launch\gui.cmd %*
.\portable_hermes\launch\cli.cmd %*
