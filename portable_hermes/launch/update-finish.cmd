@echo off
:: The end of UPDATE.bat, after the updater (or a check before it) ended.
::
:: CALLed by update.cmd on its pre-parsed line; the updater's exit code is in
:: ERRORLEVEL. Exit code 4 (the newest core needs a newer portable Python)
:: starts runtime.cmd, whose exit code replaces it.
::
:: INTERFACE BETWEEN WRAPPER VERSIONS: a wrapper update replaces this folder
:: while update.cmd runs, so the running, older update.cmd calls the NEW copy
:: of this file. Keep its name and its exit codes, and read only variables
:: that env.cmd and session.cmd have always set (PH_SESSION, PH_PAUSE,
:: PYTHON_EXE, PH_BOOT, PH_ROOT and the others listed in env.cmd).
set "PH_RC=%ERRORLEVEL%"
if not defined PH_SESSION (
    rem prepare.cmd stopped before the updater ran and said why.
    if defined PH_PAUSE pause
    exit /b %PH_RC%
)
setlocal enabledelayedexpansion
(
    if "!PH_RC!"=="4" (
        echo.
        call .\portable_hermes\launch\runtime.cmd
        set "PH_RC=!ERRORLEVEL!"
    )
    echo.
    if "!PH_RC!"=="0" (
        echo   Update finished.
    ) else if "!PH_RC!"=="5" (
        echo   Update finished. The portable Python and the Hermes core were left as they are.
    ) else (
        echo   Update finished with problems ^(exit code !PH_RC!^). See the messages above.
    )
    echo.
    if defined PH_PAUSE pause
    exit /b !PH_RC!
)
