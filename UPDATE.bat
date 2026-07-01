@echo off
setlocal enabledelayedexpansion
title Portable Hermes Agent Update

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python_embedded"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

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
        pause
        exit /b 1
    )
)

set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%SCRIPT_DIR%node_modules\.bin;%PATH%"
set "PIP_TARGET=%PYTHON_DIR%\Lib\site-packages"
set "PIP_PREFIX=%PYTHON_DIR%"
set "PYTHONPATH=%PYTHON_DIR%\Lib\site-packages"
set "HERMES_PYTHON=%PYTHON_EXE%"
set "HERMES_ROOT=%SCRIPT_DIR%"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul 2>&1

cd /d "%SCRIPT_DIR%"
echo   Updating from this Portable Hermes Agent repository...
echo   Runtime folders and custom tools are backed up/preserved.
echo.
"%PYTHON_EXE%" -m hermes_cli.main update --backup --yes %*
set "UPDATE_EXIT=%ERRORLEVEL%"

echo.
if "%UPDATE_EXIT%"=="0" (
    echo   Update complete.
) else (
    echo   Update failed with exit code %UPDATE_EXIT%.
)
echo.
pause
exit /b %UPDATE_EXIT%
