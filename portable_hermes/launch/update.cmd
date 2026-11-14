@echo off
:: UPDATE.bat: the portable wrapper first, then (optionally) the Hermes core.
:: If the newest core needs a newer portable Python, the updater exits with
:: code 4 and update-finish.cmd runs runtime.cmd, which upgrades
:: python_embedded in place.
::
:: Started (not CALLed) by the one-line UPDATE.bat, or by cli.cmd for
:: "hermes.bat update", with PORTABLE_HERMES_ROOT set and the install folder
:: as the current directory. The arguments reach the updater untouched (never
:: passed through CALL, never inside parentheses); --yes / -y are also read
:: here with a shift loop, so a path such as C:\x\file(1).zip is harmless.
setlocal disabledelayedexpansion
for %%I in ("%PORTABLE_HERMES_ROOT%") do set "PH_ROOT=%%~fI"
:yes_loop
if [%1]==[] goto :yes_done
if /i "%~1"=="--yes" set "HERMES_PORTABLE_NONINTERACTIVE=1"
if /i "%~1"=="-y" set "HERMES_PORTABLE_NONINTERACTIVE=1"
shift
goto :yes_loop
:yes_done
call .\portable_hermes\launch\env.cmd
if errorlevel 1 exit /b 1
title Portable Hermes Agent Update
echo.
echo  ============================================
echo   Portable Hermes Agent - Update
echo  ============================================
echo.
set "PH_SESSION="
:: Everything from here to the exit is ONE line, read completely before it
:: runs: the wrapper update replaces this file and the rest of this folder
:: while the updater runs. What happens afterwards is in update-finish.cmd,
:: read after the update (so it is the new copy; see env.cmd).
call .\portable_hermes\launch\prepare.cmd update && call .\portable_hermes\launch\session.cmd update && "%PYTHON_EXE%" -c "%PH_UPDATE_BOOT%" "%PH_ROOT%\." %* & call .\portable_hermes\launch\update-finish.cmd & call exit /b %%ERRORLEVEL%%
