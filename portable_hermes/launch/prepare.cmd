@echo off
:: Checks every launcher runs before importing any Python code from this folder.
::
:: CALLed by cli.cmd, gui.cmd and update.cmd (after env.cmd) with one argument:
:: cli, gui or update. Exit code 0: ready to start. Exit code 1: stop; a
:: message was shown (or, for the hidden GUI start, START.bat was opened so
:: the message can be seen).
::
:: 1. Setup: no portable Python yet, or install.bat did not finish last time
::    (.portable\installing exists): run install.bat first.
:: 2. An update was interrupted (.portable\journal.json exists): settle it with
::    the standalone .portable\recover.py, which needs nothing but the Python
::    standard library, so a half-replaced portable_hermes package cannot get
::    in the way. Never start Hermes on top of an unsettled update.
:: 3. Python packages were left half changed (.portable\deps-pending.json):
::    say so; UPDATE.bat finishes the change.
::
:: Everything below is one parenthesised block: cmd.exe reads it completely
:: before running it, so files replaced while it runs cannot change it.
setlocal disabledelayedexpansion
(
    set "PH_NEED_SETUP="
    if not exist "%PYTHON_EXE%" set "PH_NEED_SETUP=1"
    if exist "%PH_STATE%\installing" set "PH_NEED_SETUP=1"
    if defined PH_NEED_SETUP if defined HERMES_PORTABLE_HIDDEN (
        set "HERMES_PORTABLE_HIDDEN="
        start "Portable Hermes" "%ComSpec%" /d /c call "%PH_ROOT%\START.bat"
        exit /b 1
    )
    if defined PH_NEED_SETUP (
        if exist "%PYTHON_EXE%" (
            echo.
            echo   The last setup of this folder did not finish. Running it again now.
            echo.
        )
        call .\install.bat
        if errorlevel 1 (
            echo.
            echo   Setup did not finish, so Hermes was not started. Check your internet
            echo   connection and the messages above, then start Hermes again.
            echo.
            exit /b 1
        )
        if not exist "%PYTHON_EXE%" exit /b 1
    )
    if exist "%PH_STATE%\journal.json" if defined HERMES_PORTABLE_HIDDEN (
        if not exist "%PH_STATE%\recover.py" (
            set "HERMES_PORTABLE_HIDDEN="
            start "Portable Hermes" "%ComSpec%" /d /c call "%PH_ROOT%\START.bat"
            exit /b 1
        )
        set "PORTABLE_HERMES_NO_HOOK=1"
        "%PYTHON_EXE%" -I -X utf8 "%PH_STATE%\recover.py" "%PH_ROOT%\." >nul 2>&1
        if errorlevel 1 (
            set "HERMES_PORTABLE_HIDDEN="
            start "Portable Hermes" "%ComSpec%" /d /c call "%PH_ROOT%\START.bat"
            exit /b 1
        )
        set "PORTABLE_HERMES_NO_HOOK="
    )
    if exist "%PH_STATE%\journal.json" (
        echo   Finishing an update that was interrupted...
        if not exist "%PH_STATE%\recover.py" (
            echo.
            echo   Portable Hermes: an update was interrupted, and the file needed to undo
            echo   it ^(.portable\recover.py^) is missing. Hermes was not started.
            echo   Run install.bat to repair this folder. Your settings and data are kept.
            echo.
            if defined PH_PAUSE pause
            exit /b 1
        )
        set "PORTABLE_HERMES_NO_HOOK=1"
        "%PYTHON_EXE%" -I -X utf8 "%PH_STATE%\recover.py" "%PH_ROOT%\."
        if errorlevel 1 (
            echo.
            echo   Hermes was not started because the interrupted update could not be
            echo   settled. See the message above.
            echo.
            if defined PH_PAUSE pause
            exit /b 1
        )
        set "PORTABLE_HERMES_NO_HOOK="
    )
    if exist "%PH_STATE%\deps-pending.json" if /i not "%~1"=="update" (
        echo.
        echo   NOTE: an earlier update was interrupted while it was changing Python
        echo   packages. Some features may not work until you run UPDATE.bat, which
        echo   finishes the change.
        echo.
    )
    exit /b 0
)
