@echo off
:: hermes_gui.bat: start the desktop GUI.
::
:: Started (not CALLed) by the one-line hermes_gui.bat, or by start.cmd, with
:: PORTABLE_HERMES_ROOT set and the install folder as the current directory.
:: hermes_gui.vbs sets HERMES_PORTABLE_HIDDEN: no window, so never wait for a
:: key press (prepare.cmd opens START.bat when setup or a problem needs to be
:: shown). The user's arguments are never parsed twice: never passed through
:: CALL, never inside parentheses, delayed expansion off.
setlocal disabledelayedexpansion
for %%I in ("%PORTABLE_HERMES_ROOT%") do set "PH_ROOT=%%~fI"
call .\portable_hermes\launch\env.cmd
if errorlevel 1 exit /b 1
set "PH_SESSION="
:: Everything from here to the exit is ONE line, read completely before it
:: runs, so files replaced while the GUI runs cannot change what happens next.
call .\portable_hermes\launch\prepare.cmd gui && call .\portable_hermes\launch\session.cmd gui && "%PYTHON_EXE%" -c "from gui.app import main; main()" %* & call .\portable_hermes\launch\gui-exit.cmd & call exit /b %%ERRORLEVEL%%
