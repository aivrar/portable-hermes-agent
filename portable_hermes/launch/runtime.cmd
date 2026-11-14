@echo off
:: In-place upgrade of the portable Python (python_embedded).
::
:: CALLed (after env.cmd, current directory = the install folder):
::   runtime.cmd          by update-finish.cmd and install.bat when the newest
::                        Hermes core needs a newer Python than this folder
::                        has (core install exit code 4);
::   runtime.cmd resume   by prepare.cmd and install.bat when
::                        .portable\runtime-plan.cmd exists: an upgrade was
::                        interrupted (window closed, power lost). No question
::                        is asked again.
:: portable_hermes/runtime.py decides and words every step; this file only
:: renames folders, because no Python may run from python_embedded while it
:: is renamed.
::
:: .portable\runtime-plan.cmd is the marker of an upgrade in progress: written
:: before python_embedded is renamed, removed on every exit path that settles
:: the upgrade. It is kept only when a folder could not be renamed back (exit
:: code 4), so the next start tries again. The batch state the undo needs
:: (which markers existed before, whether the undo had started) is appended
:: to it, so a resume knows it too.
::
:: Exit codes: 0 upgraded; 1 not upgraded, nothing changed (or the previous
:: Python is back); 3 the new Python and core are installed but a later setup
:: step failed (install.bat must run again, the launchers do it); 4 a folder
:: could not be renamed, the message says what to rename by hand; 5 the user
:: said no, nothing changed.
::
:: Every folder rename is tried up to 10 times, a second apart: right after
:: a Python ran from the folder (or was just extracted), Windows or a virus
:: scanner can hold python.exe for a moment.
::
:: One parenthesised block: install.bat installs files while it runs.
setlocal enabledelayedexpansion
set "PH_MODE=%~1"
set "PH_PLAN=.portable\runtime-plan.cmd"
set "PH_RESUME_FILE=.portable\runtime-resume.cmd"
(
    set "PH_OLD_NAME="
    set "PH_FAILED_NAME="
    set "PH_ASIDE_NAME="
    set "PH_TARGET="
    set "PH_HAD_INSTALLING="
    set "PH_HAD_DEPS="
    set "PH_UNDOING="
    set "PH_FORWARD="
    set "PH_STEP="
    if /i "!PH_MODE!"=="resume" (
        rem ---- an interrupted upgrade: decide with the previous Python ----
        if exist "%PH_PLAN%" call "%PH_PLAN%"
        if not defined PH_OLD_NAME (
            echo   The note .portable\runtime-plan.cmd of an interrupted Python upgrade
            echo   cannot be read. Hermes was not started. If a folder python_embedded.old-...
            echo   exists, rename it to python_embedded ^(after moving an incomplete
            echo   python_embedded aside^), then rename the note and start Hermes again.
            exit /b 4
        )
        set "PH_RESUME="
        set "PH_RESUME_PY="
        if exist "%PYTHON_EXE%" set "PH_RESUME_PY=%PYTHON_EXE%"
        if exist "!PH_OLD_NAME!\python.exe" set "PH_RESUME_PY=%PH_ROOT%\!PH_OLD_NAME!\python.exe"
        if not defined PH_RESUME_PY (
            rem No Python at all: nothing to put back; setup builds one from nothing.
            echo   No portable Python is left in this folder; setup installs a new one.
            set "PH_RESUME=discard"
        ) else (
            set "PH_UNDO_FLAG="
            if defined PH_UNDOING set "PH_UNDO_FLAG=--undoing"
            set "PORTABLE_HERMES_NO_HOOK=1"
            "!PH_RESUME_PY!" -c "%PH_BOOT%" "%PH_ROOT%\." runtime resume --old "!PH_OLD_NAME!" --failed "!PH_FAILED_NAME!" --target "!PH_TARGET!" !PH_UNDO_FLAG!
            if errorlevel 1 (
                echo.
                echo   The interrupted Python upgrade could not be checked ^(see above^).
                echo   Hermes was not started. Nothing was changed.
                exit /b 4
            )
            set "PORTABLE_HERMES_NO_HOOK="
            if exist "%PH_RESUME_FILE%" call "%PH_RESUME_FILE%"
        )
        if "!PH_RESUME!"=="discard" (
            if exist "%PH_PLAN%" del "%PH_PLAN%"
            if exist "%PH_RESUME_FILE%" del "%PH_RESUME_FILE%"
            exit /b 1
        )
        if "!PH_RESUME!"=="forward" (
            set "PH_FORWARD=1"
            set "PH_STEP=install"
        )
        if "!PH_RESUME!"=="rebuild" (
            if exist "python_embedded" if defined PH_ASIDE_NAME (
                echo   Moving the incomplete python_embedded to !PH_ASIDE_NAME! ...
                for /l %%T in (1,1,10) do if exist "python_embedded" if not exist "!PH_ASIDE_NAME!" (
                    ren "python_embedded" "!PH_ASIDE_NAME!" 2>nul
                    if exist "python_embedded" ping -n 2 127.0.0.1 >nul
                )
            )
            if exist "python_embedded" (
                echo.
                echo   The incomplete python_embedded could not be moved: a program is still
                echo   using it. Close every Hermes window and start Hermes again.
                exit /b 4
            )
            set "PH_STEP=install"
        )
        if "!PH_RESUME!"=="undo" set "PH_STEP=undo"
        if not defined PH_STEP (
            echo   The interrupted Python upgrade could not be checked. Hermes was not
            echo   started. Nothing was changed.
            exit /b 4
        )
        echo.
    ) else (
        rem ---- a new upgrade: explain, ask, move python_embedded aside ----
        "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." runtime plan
        if errorlevel 1 (
            echo   The Python upgrade could not be prepared. Nothing was changed.
            if exist "%PH_PLAN%" del "%PH_PLAN%"
            exit /b 1
        )
        if exist "%PH_PLAN%" call "%PH_PLAN%"
        if not defined PH_OLD_NAME (
            echo   The Python upgrade could not be prepared. Nothing was changed.
            if exist "%PH_PLAN%" del "%PH_PLAN%"
            exit /b 1
        )
        if defined PH_PAUSE (
            set "PH_ANSWER="
            set /p "PH_ANSWER=  Upgrade the portable Python to !PH_TARGET! now? [y/N] "
            if /i not "!PH_ANSWER!"=="y" if /i not "!PH_ANSWER!"=="yes" (
                echo.
                echo   Nothing was changed. The Hermes core stays at the version you have.
                echo   Run UPDATE.bat --core when you are ready to upgrade.
                if exist "%PH_PLAN%" del "%PH_PLAN%"
                exit /b 5
            )
        ) else (
            echo   Unattended: upgrading the portable Python to !PH_TARGET!.
        )
        if exist ".portable\installing" (
            set "PH_HAD_INSTALLING=1"
            >>"%PH_PLAN%" echo set "PH_HAD_INSTALLING=1"
        )
        if exist ".portable\deps-pending.json" (
            set "PH_HAD_DEPS=1"
            >>"%PH_PLAN%" echo set "PH_HAD_DEPS=1"
            copy /y ".portable\deps-pending.json" ".portable\deps-pending.before-runtime-upgrade.json" >nul
        )
        echo.
        echo   Moving python_embedded to !PH_OLD_NAME! ...
        for /l %%T in (1,1,10) do if exist "python_embedded" if not exist "!PH_OLD_NAME!" (
            ren "python_embedded" "!PH_OLD_NAME!" 2>nul
            if exist "python_embedded" ping -n 2 127.0.0.1 >nul
        )
        if not exist "!PH_OLD_NAME!\python.exe" (
            echo.
            echo   python_embedded could not be renamed: a program is still using it.
            echo   Close Hermes ^(GUI, CLI, gateway^) and run UPDATE.bat again.
            echo   Nothing was changed.
            if exist "%PH_PLAN%" del "%PH_PLAN%"
            exit /b 1
        )
        echo.
        set "PH_STEP=install"
    )
    rem ---- build the new runtime and install the core ----
    if "!PH_STEP!"=="install" (
        call .\install.bat --runtime-upgrade
        set "PH_RC=!ERRORLEVEL!"
        if "!PH_RC!"=="0" (
            "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." runtime done --old "!PH_OLD_NAME!"
            if exist "%PH_PLAN%" del "%PH_PLAN%"
            if exist "%PH_RESUME_FILE%" del "%PH_RESUME_FILE%"
            exit /b 0
        )
        rem 11: the core committed, a later step failed. The previous Python
        rem cannot run the new core, so only forward from here.
        if "!PH_RC!"=="11" set "PH_FORWARD=1"
        if defined PH_FORWARD (
            "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." runtime partial --old "!PH_OLD_NAME!"
            if exist "%PH_PLAN%" del "%PH_PLAN%"
            if exist "%PH_RESUME_FILE%" del "%PH_RESUME_FILE%"
            exit /b 3
        )
        >>"%PH_PLAN%" echo set "PH_UNDOING=1"
    )
    rem ---- the new core did not commit: put the previous Python back ----
    echo.
    echo   Undoing the Python upgrade...
    if exist "!PH_OLD_NAME!\python.exe" (
        for /l %%T in (1,1,10) do if exist "python_embedded" if not exist "!PH_FAILED_NAME!" (
            ren "python_embedded" "!PH_FAILED_NAME!" 2>nul
            if exist "python_embedded" ping -n 2 127.0.0.1 >nul
        )
        if exist "python_embedded" (
            echo.
            echo   The incomplete new python_embedded could not be moved aside. Close every
            echo   Hermes window, then in this folder rename python_embedded to
            echo   !PH_FAILED_NAME! and !PH_OLD_NAME! to python_embedded.
            exit /b 4
        )
        for /l %%T in (1,1,10) do if exist "!PH_OLD_NAME!" if not exist "python_embedded" (
            ren "!PH_OLD_NAME!" "python_embedded" 2>nul
            if exist "!PH_OLD_NAME!" ping -n 2 127.0.0.1 >nul
        )
        if not exist "python_embedded\python.exe" (
            echo.
            echo   The previous Python could not be put back. Close every Hermes window,
            echo   then in this folder rename !PH_OLD_NAME! to python_embedded.
            exit /b 4
        )
    )
    if not defined PH_HAD_INSTALLING if exist ".portable\installing" del ".portable\installing"
    if defined PH_HAD_DEPS (
        if exist ".portable\deps-pending.before-runtime-upgrade.json" move /y ".portable\deps-pending.before-runtime-upgrade.json" ".portable\deps-pending.json" >nul
    ) else (
        if exist ".portable\deps-pending.json" del ".portable\deps-pending.json"
    )
    if exist "%PH_PLAN%" del "%PH_PLAN%"
    if exist "%PH_RESUME_FILE%" del "%PH_RESUME_FILE%"
    "%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." runtime undone --failed "!PH_FAILED_NAME!"
    exit /b 1
)
