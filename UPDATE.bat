@echo off
setlocal enabledelayedexpansion
title Portable Hermes Agent Update

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python_embedded"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

:: Non-interactive: UPDATE.bat --yes, or HERMES_PORTABLE_NONINTERACTIVE=1.
set "PH_PAUSE=1"
if defined HERMES_PORTABLE_NONINTERACTIVE if not "%HERMES_PORTABLE_NONINTERACTIVE%"=="0" set "PH_PAUSE="
for %%A in (%*) do (
    if /i "%%~A"=="--yes" set "PH_PAUSE="
    if /i "%%~A"=="-y" set "PH_PAUSE="
)
if not defined PH_PAUSE set "HERMES_PORTABLE_NONINTERACTIVE=1"

echo.
echo  ============================================
echo   Portable Hermes Agent - Update
echo  ============================================
echo.

if not exist "%PYTHON_EXE%" (
    echo   Portable Python is not installed yet.
    echo   Running first-time setup instead...
    echo.
    call "%SCRIPT_DIR%install.bat"
    if not exist "%PYTHON_EXE%" (
        echo.
        echo   Setup failed. Update cannot continue.
        if defined PH_PAUSE pause
        exit /b 1
    )
)

set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%SCRIPT_DIR%node_modules\.bin;%PATH%"
set "HERMES_PYTHON=%PYTHON_EXE%"
set "HERMES_ROOT=%SCRIPT_DIR%"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul 2>&1

cd /d "%SCRIPT_DIR%"
echo   Two separate update channels:
echo     1. Portable wrapper - launchers, GUI, portable tools (aivrar releases)
echo     2. Hermes core - the agent itself (NousResearch/hermes-agent), optional
echo   Your settings, keys, chats, extensions and custom tools are not touched.
echo.
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); from portable_hermes.__main__ import main; sys.exit(main(sys.argv[1:]))" "%SCRIPT_DIR%." update %*
set "UPDATE_EXIT=%ERRORLEVEL%"

echo.
if "%UPDATE_EXIT%"=="0" (
    echo   Update finished.
) else (
    echo   Update finished with problems ^(exit code %UPDATE_EXIT%^). See the messages above.
)
echo.
if defined PH_PAUSE pause
exit /b %UPDATE_EXIT%
