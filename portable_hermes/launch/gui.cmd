@echo off
:: hermes_gui.bat: start the desktop GUI.
::
:: Run through the one-line hermes_gui.bat (or START.bat) in the install
:: folder, which sets PORTABLE_HERMES_ROOT and makes the install folder the
:: current directory. hermes_gui.vbs sets HERMES_PORTABLE_HIDDEN: no window,
:: so never wait for a key press (prepare.cmd opens START.bat when setup or a
:: problem needs to be shown).
setlocal disabledelayedexpansion
for %%I in ("%PORTABLE_HERMES_ROOT%") do set "PH_ROOT=%%~fI"
call .\portable_hermes\launch\env.cmd %*
if errorlevel 1 exit /b 1
setlocal enabledelayedexpansion
(
    call .\portable_hermes\launch\prepare.cmd gui
    if errorlevel 1 exit /b 1
    set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PH_ROOT%\node_modules\.bin;%PATH%"
    set "PIP_TARGET=%PYTHON_DIR%\Lib\site-packages"
    set "PYTHONPATH=%PYTHON_DIR%\Lib\site-packages"
    set "TERMINAL_CWD=%PH_ROOT%\"
    chcp 65001 >nul 2>&1
    rem Launch-time repair: restore portable files an upstream update replaced.
    rem Fast, and never fails the launch; problems with the portable tools are
    rem always printed.
    "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." repair --quiet
    "%PYTHON_EXE%" -c "from gui.app import main; main()" %*
    set "PH_RC=!ERRORLEVEL!"
    if not "!PH_RC!"=="0" (
        echo.
        echo GUI exited with an error. Check the output above.
        if defined PH_PAUSE pause
    )
    exit /b !PH_RC!
)
