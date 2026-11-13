@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python_embedded"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
if not defined HERMES_HOME set "HERMES_HOME=%USERPROFILE%\.hermes"

:: Check if Python is installed
if not exist "%PYTHON_EXE%" (
    echo Python not found. Running first-time setup...
    call "%SCRIPT_DIR%install.bat"
    if not exist "%PYTHON_EXE%" exit /b 1
)

:: Set up PATH (portable Python + node tools FIRST - overrides system)
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%SCRIPT_DIR%node_modules\.bin;%PATH%"

:: Lock ALL pip installs to portable Python
set "PIP_TARGET=%PYTHON_DIR%\Lib\site-packages"
set "PYTHONPATH=%PYTHON_DIR%\Lib\site-packages"
set "HERMES_PYTHON=%PYTHON_EXE%"
set "HERMES_ROOT=%SCRIPT_DIR%"

:: Encoding and Tcl/Tk
set "PYTHONIOENCODING=utf-8"
set "TCL_LIBRARY=%PYTHON_DIR%\tcl\tcl8.6"
set "TK_LIBRARY=%PYTHON_DIR%\tcl\tk8.6"

:: Terminal tool working directory
set "TERMINAL_CWD=%SCRIPT_DIR%"

cd /d "%SCRIPT_DIR%"
chcp 65001 >nul 2>&1

:: Launch-time repair: restore portable files an upstream update replaced and
:: settle an interrupted update. Fast, and never blocks or fails the launch.
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); from portable_hermes.__main__ import main; main(['repair', '--quiet'])" "%SCRIPT_DIR%." 2>nul

:: Launch Hermes GUI
"%PYTHON_EXE%" -c "from gui.app import main; main()" %*

if errorlevel 1 (
    echo.
    echo GUI exited with an error. Check the output above.
    pause
)

endlocal
