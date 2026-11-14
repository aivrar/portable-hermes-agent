@echo off
:: hermes.bat: the Hermes command line, plus the portable commands
:: setup, install, update and help.
::
:: Started (not CALLed) by the one-line hermes.bat in the install folder,
:: which sets PORTABLE_HERMES_ROOT and makes the install folder the current
:: directory. The user's arguments are never parsed twice: never passed
:: through CALL, never inside parentheses, delayed expansion off. So percent
:: signs, carets, exclamation marks, parentheses and wildcards in them reach
:: Hermes as typed.
setlocal disabledelayedexpansion
for %%I in ("%PORTABLE_HERMES_ROOT%") do set "PH_ROOT=%%~fI"
call .\portable_hermes\launch\env.cmd
if errorlevel 1 exit /b 1

:: "hermes update" is the portable updater (UPDATE.bat): the wrapper channel
:: first, then an optional core refresh. Upstream's own updater would swap
:: the whole tree from NousResearch and drop the portable files. Starting a
:: script without CALL hands the window over to it; this file ends here.
if /i "%~1"=="update" .\portable_hermes\launch\update.cmd %*
if /i "%~1"=="install" .\install.bat
if /i "%~1"=="help" goto :help

set "PH_CLI_MODE=cli"
if /i "%~1"=="setup" set "PH_CLI_MODE=cli-setup"
set "PH_SESSION="
:: Everything from here to the exit is ONE line: cmd.exe reads a whole line
:: before it runs it, so a file replaced while Hermes runs (an update started
:: from inside Hermes) cannot change what happens next.
call .\portable_hermes\launch\prepare.cmd cli && call .\portable_hermes\launch\session.cmd %PH_CLI_MODE% && "%PYTHON_EXE%" -m hermes_cli.main %* & call exit /b %%ERRORLEVEL%%

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
