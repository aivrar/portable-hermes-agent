@echo off
:: In-place upgrade of the portable Python (python_embedded).
::
:: CALLed by update.cmd and install.bat (after env.cmd, current directory =
:: the install folder) when the newest Hermes core needs a newer Python than
:: this folder has (core install exit code 4). See portable_hermes/runtime.py,
:: which decides and words every step; this file only renames folders, because
:: no Python may run from python_embedded while it is renamed.
::
:: Exit codes: 0 upgraded; 1 not upgraded, nothing changed; 3 the new Python
:: and core are installed but a later setup step failed (install.bat must run
:: again, the launchers do it); 4 could not put the previous Python back, the
:: message says what to rename by hand; 5 the user said no, nothing changed.
::
:: One parenthesised block: install.bat installs files while it runs.
setlocal enabledelayedexpansion
(
    set "PH_OLD_NAME="
    "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." runtime plan
    if errorlevel 1 (
        echo   The Python upgrade could not be prepared. Nothing was changed.
        exit /b 1
    )
    if exist ".portable\runtime-plan.cmd" call ".portable\runtime-plan.cmd"
    if not defined PH_OLD_NAME (
        echo   The Python upgrade could not be prepared. Nothing was changed.
        exit /b 1
    )
    if defined PH_PAUSE (
        set "PH_ANSWER="
        set /p "PH_ANSWER=  Upgrade the portable Python to !PH_TARGET! now? [y/N] "
        if /i not "!PH_ANSWER!"=="y" if /i not "!PH_ANSWER!"=="yes" (
            echo.
            echo   Nothing was changed. The Hermes core stays at the version you have.
            echo   Run UPDATE.bat --core when you are ready to upgrade.
            exit /b 5
        )
    ) else (
        echo   Unattended: upgrading the portable Python to !PH_TARGET!.
    )
    set "PH_HAD_INSTALLING="
    if exist ".portable\installing" set "PH_HAD_INSTALLING=1"
    set "PH_HAD_DEPS="
    if exist ".portable\deps-pending.json" (
        set "PH_HAD_DEPS=1"
        copy /y ".portable\deps-pending.json" ".portable\deps-pending.before-runtime-upgrade.json" >nul
    )
    echo.
    echo   Moving python_embedded to !PH_OLD_NAME! ...
    ren "python_embedded" "!PH_OLD_NAME!" 2>nul
    if not exist "!PH_OLD_NAME!\python.exe" (
        echo.
        echo   python_embedded could not be renamed: a program is still using it.
        echo   Close Hermes ^(GUI, CLI, gateway^) and run UPDATE.bat again.
        echo   Nothing was changed.
        exit /b 1
    )
    echo.
    call .\install.bat --runtime-upgrade
    set "PH_RC=!ERRORLEVEL!"
    if "!PH_RC!"=="0" (
        "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." runtime done --old "!PH_OLD_NAME!"
        exit /b 0
    )
    if "!PH_RC!"=="11" (
        "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." runtime partial --old "!PH_OLD_NAME!"
        exit /b 3
    )
    rem The new core did not commit: put the previous Python back as it was.
    echo.
    echo   Undoing the Python upgrade...
    if exist "python_embedded" ren "python_embedded" "!PH_FAILED_NAME!" 2>nul
    if exist "python_embedded" (
        echo.
        echo   The incomplete new python_embedded could not be moved aside. Close every
        echo   Hermes window, then in this folder rename python_embedded to
        echo   !PH_FAILED_NAME! and !PH_OLD_NAME! to python_embedded.
        exit /b 4
    )
    ren "!PH_OLD_NAME!" "python_embedded" 2>nul
    if not exist "python_embedded\python.exe" (
        echo.
        echo   The previous Python could not be put back. Close every Hermes window,
        echo   then in this folder rename !PH_OLD_NAME! to python_embedded.
        exit /b 4
    )
    if not defined PH_HAD_INSTALLING if exist ".portable\installing" del ".portable\installing"
    if defined PH_HAD_DEPS (
        move /y ".portable\deps-pending.before-runtime-upgrade.json" ".portable\deps-pending.json" >nul
    ) else (
        if exist ".portable\deps-pending.json" del ".portable\deps-pending.json"
    )
    "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." runtime undone --failed "!PH_FAILED_NAME!"
    exit /b 1
)
