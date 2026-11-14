@echo off
:: Checks every launcher runs before importing any Python code from this folder.
::
:: CALLed by cli.cmd, gui.cmd and update.cmd (after env.cmd) with one argument:
:: cli, gui or update. Exit code 0: ready to start. Exit code 1: stop; a
:: message was shown (or, for the hidden GUI start, START.bat was opened so
:: the message can be seen).
::
:: 1. A Python upgrade was interrupted (.portable\runtime-plan.cmd exists):
::    runtime.cmd resume finishes it or puts the previous Python back.
:: 2. Setup: no portable Python yet, install.bat did not finish last time
::    (.portable\installing exists), or no Hermes core (run_agent.py missing:
::    a git clone, whose repository holds only the wrapper): run install.bat
::    first. install.bat exit code 12: GitHub's source download, it said so.
:: 3. An update was interrupted (.portable\journal.json exists): settle it with
::    the standalone .portable\recover.py, which needs nothing but the Python
::    standard library, so a half-replaced portable_hermes package cannot get
::    in the way. Never start Hermes on top of an unsettled update.
:: 4. Python packages were left half changed (.portable\deps-pending.json):
::    say so; UPDATE.bat finishes the change.
:: 5. Half of the hand-over from v1.4.18 or older: their updater put these
::    launchers (from the repository's main ZIP, so no release.json) next to
::    the old core. Say that UPDATE.bat must run once more. If that core
::    cannot start (tools\registry.py missing), do not start it at all.
::
:: Everything below is one parenthesised block: cmd.exe reads it completely
:: before running it, so files replaced while it runs cannot change it.
setlocal disabledelayedexpansion
(
    if exist "%PH_STATE%\runtime-plan.cmd" if defined HERMES_PORTABLE_HIDDEN (
        set "HERMES_PORTABLE_HIDDEN="
        start "Portable Hermes" "%ComSpec%" /d /c call "%PH_ROOT%\START.bat"
        exit /b 1
    )
    if exist "%PH_STATE%\runtime-plan.cmd" (
        echo.
        echo   An upgrade of the portable Python was interrupted. Settling it first.
        call .\portable_hermes\launch\runtime.cmd resume
        if errorlevel 3 (
            echo.
            echo   Hermes was not started. See the message above.
            echo.
            if defined PH_PAUSE pause
            exit /b 1
        )
    )
    set "PH_NEED_SETUP="
    if not exist "%PYTHON_EXE%" set "PH_NEED_SETUP=1"
    if exist "%PH_STATE%\installing" set "PH_NEED_SETUP=1"
    if not exist "%PH_ROOT%\run_agent.py" set "PH_NEED_SETUP=1"
    if defined PH_NEED_SETUP if defined HERMES_PORTABLE_HIDDEN (
        set "HERMES_PORTABLE_HIDDEN="
        start "Portable Hermes" "%ComSpec%" /d /c call "%PH_ROOT%\START.bat"
        exit /b 1
    )
    if defined PH_NEED_SETUP (
        if exist "%PYTHON_EXE%" if exist "%PH_STATE%\installing" (
            echo.
            echo   The last setup of this folder did not finish. Running it again now.
            echo.
        )
        if exist "%PYTHON_EXE%" if not exist "%PH_STATE%\installing" (
            echo.
            echo   This folder has no Hermes core yet. Running setup to install it now.
            echo.
        )
        call .\install.bat
        if errorlevel 12 if not errorlevel 13 exit /b 1
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
    if /i not "%~1"=="update" if not exist "%PH_ROOT%\portable_hermes\release.json" if not exist "%PH_ROOT%\.git" if exist "%PH_ROOT%\run_agent.py" (
        if not exist "%PH_ROOT%\tools\registry.py" if defined HERMES_PORTABLE_HIDDEN (
            set "HERMES_PORTABLE_HIDDEN="
            start "Portable Hermes" "%ComSpec%" /d /c call "%PH_ROOT%\START.bat"
            exit /b 1
        )
        echo.
        echo   NOTE: the update is not finished. Run UPDATE.bat once more.
        echo.
        if not exist "%PH_ROOT%\tools\registry.py" (
            echo   Hermes was not started: its core is incomplete until UPDATE.bat has
            echo   run once more. Your settings and data are kept.
            echo.
            if defined PH_PAUSE pause
            exit /b 1
        )
    )
    exit /b 0
)
