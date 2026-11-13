@echo off
:: UPDATE.bat: the portable wrapper first, then (optionally) the Hermes core.
:: If the newest core needs a newer portable Python, the updater exits with
:: code 4 and runtime.cmd upgrades python_embedded in place.
::
:: Run through the one-line UPDATE.bat in the install folder, which sets
:: PORTABLE_HERMES_ROOT and makes the install folder the current directory.
:: The main part is one parenthesised block: the wrapper update replaces this
:: file and the other launch scripts while the block runs, which cannot
:: change a block cmd.exe has already read.
setlocal disabledelayedexpansion
for %%I in ("%PORTABLE_HERMES_ROOT%") do set "PH_ROOT=%%~fI"
call .\portable_hermes\launch\env.cmd %*
if errorlevel 1 exit /b 1
setlocal enabledelayedexpansion
title Portable Hermes Agent Update
(
    echo.
    echo  ============================================
    echo   Portable Hermes Agent - Update
    echo  ============================================
    echo.
    call .\portable_hermes\launch\prepare.cmd update
    if errorlevel 1 (
        if defined PH_PAUSE pause
        exit /b 1
    )
    set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PH_ROOT%\node_modules\.bin;%PATH%"
    chcp 65001 >nul 2>&1
    echo   Two separate update channels:
    echo     1. Portable wrapper - launchers, GUI, portable tools, aivrar releases
    echo     2. Hermes core - the agent itself, NousResearch/hermes-agent, optional
    echo   Your settings, keys, chats, extensions and custom tools are not touched.
    echo.
    "%PYTHON_EXE%" -c "%PH_UPDATE_BOOT%" "%PH_ROOT%\." %*
    set "PH_RC=!ERRORLEVEL!"
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
