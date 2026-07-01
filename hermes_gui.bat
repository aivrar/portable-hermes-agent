@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python_embedded"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

:: Check if Python is installed
if not exist "%PYTHON_EXE%" (
    echo Python not found. Running first-time setup...
    call "%SCRIPT_DIR%install.bat"
    if not exist "%PYTHON_EXE%" exit /b 1
)

:: Set up PATH (portable Python + node tools FIRST — overrides system)
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%SCRIPT_DIR%node_modules\.bin;%PATH%"

:: Lock ALL pip installs to portable Python
set "PIP_TARGET=%PYTHON_DIR%\Lib\site-packages"
set "PIP_PREFIX=%PYTHON_DIR%"
set "PYTHONPATH=%PYTHON_DIR%\Lib\site-packages"

:: Encoding and Tcl/Tk
set "PYTHONIOENCODING=utf-8"
set "TCL_LIBRARY=%PYTHON_DIR%\tcl\tcl8.6"
set "TK_LIBRARY=%PYTHON_DIR%\tcl\tk8.6"

:: Terminal tool working directory
set "TERMINAL_CWD=%SCRIPT_DIR%"

:: Launch Hermes GUI
cd /d "%SCRIPT_DIR%"
"%PYTHON_EXE%" "%SCRIPT_DIR%gui\app.py" %*

if errorlevel 1 (
    echo.
    echo GUI exited with an error. Check the output above.
    pause
)

endlocal
