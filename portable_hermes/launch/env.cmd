@echo off
:: Shared launcher settings for Portable Hermes.
::
:: CALLed, without arguments, (with delayed expansion OFF and PH_ROOT set to
:: the install folder, no trailing backslash) by the other scripts in this
:: folder and by install.bat. It sets variables in the caller's scope and
:: changes nothing on disk. Exit code 1: this folder (or HERMES_HOME) cannot
:: be used.
::
:: INTERFACE BETWEEN WRAPPER VERSIONS. The variables set here (PH_ROOT is the
:: caller's) are read by scripts of a different wrapper version: a wrapper
:: update replaces this folder while UPDATE.bat runs, and the update.cmd line
:: that is already running then calls the NEW update-finish.cmd, which calls
:: the new runtime.cmd and install.bat, with the variables the OLD env.cmd
:: set. Keep every variable below, with its meaning, and give new ones a
:: default in the scripts that read them. The same goes for the names and
:: exit codes of update-finish.cmd, runtime.cmd and install.bat.
::
:: Install folders may contain spaces, apostrophes, parentheses, ampersands,
:: brackets, commas, semicolons, equals signs and non-ASCII letters. The
:: characters ! % ^ are refused up front: cmd.exe treats them as syntax in
:: places a batch file cannot fully protect.

:: Unattended (never prompt or pause): HERMES_PORTABLE_NONINTERACTIVE set to
:: anything but 0/false/no. install.bat and update.cmd set it for --yes / -y
:: before calling this; the Hermes launchers never read their arguments for
:: it, because those arguments belong to Hermes.
set "PH_PAUSE=1"
if defined HERMES_PORTABLE_NONINTERACTIVE (
    if /i not "%HERMES_PORTABLE_NONINTERACTIVE%"=="0" if /i not "%HERMES_PORTABLE_NONINTERACTIVE%"=="false" if /i not "%HERMES_PORTABLE_NONINTERACTIVE%"=="no" set "PH_PAUSE="
)
if not defined PH_PAUSE set "HERMES_PORTABLE_NONINTERACTIVE=1"
:: The GUI's hidden-window start (hermes_gui.vbs) can neither show text nor
:: wait for a key press.
if defined HERMES_PORTABLE_HIDDEN set "PH_PAUSE="

if not "%PH_ROOT:!=%"=="%PH_ROOT%" goto :bad_root
call set "PH_CHECK=%PH_ROOT%"
if not "%PH_CHECK%"=="%PH_ROOT%" goto :bad_root
set "PH_CHECK="

set "SCRIPT_DIR=%PH_ROOT%\"
set "PYTHON_DIR=%PH_ROOT%\python_embedded"
set "PYTHON_EXE=%PH_ROOT%\python_embedded\python.exe"
set "PH_STATE=%PH_ROOT%\.portable"
set "PH_LAUNCH=%PH_ROOT%\portable_hermes\launch"
if not defined HERMES_HOME set "HERMES_HOME=%USERPROFILE%\.hermes"
if not "%HERMES_HOME:!=%"=="%HERMES_HOME%" goto :bad_home

:: The portable Python version this release installs (one pin, also read by
:: portable_hermes.core and portable_hermes.runtime).
set "PH_PYTHON_PIN="
if exist "%PH_ROOT%\portable_hermes\manifests\python-runtime.txt" set /p "PH_PYTHON_PIN="<"%PH_ROOT%\portable_hermes\manifests\python-runtime.txt"

set "PYTHONIOENCODING=utf-8"
set "HERMES_PYTHON=%PYTHON_EXE%"
set "HERMES_ROOT=%SCRIPT_DIR%"
set "TCL_LIBRARY=%PYTHON_DIR%\tcl\tcl8.6"
set "TK_LIBRARY=%PYTHON_DIR%\tcl\tk8.6"

:: Run portable_hermes from this folder. The embedded interpreter's ._pth file
:: puts it in isolated mode, so the folder is passed as the first argument.
set "PH_BOOT=import sys; sys.path.insert(0, sys.argv.pop(1)); from portable_hermes.__main__ import main; sys.exit(main(sys.argv[1:]))"
set "PH_UPDATE_BOOT=import sys; sys.path.insert(0, sys.argv.pop(1)); from portable_hermes.__main__ import main; a = sys.argv[1:]; a = a[1:] if a[:1] and a[0].lower() == 'update' else a; sys.exit(main(['update'] + a))"
exit /b 0

:bad_root
echo.
echo   Portable Hermes cannot run from this folder:
echo     "%PH_ROOT%"
echo   Its path contains one of the characters ! %% ^^ which Windows batch files
echo   cannot handle safely. Move or rename the folder (for example to
echo   C:\PortableHermes) and start it again. Nothing was changed.
echo.
if defined PH_PAUSE pause
exit /b 1

:bad_home
echo.
echo   Portable Hermes cannot use this Hermes home folder:
echo     "%HERMES_HOME%"
echo   Its path contains ! which Windows batch files cannot handle safely.
echo   Set HERMES_HOME to a folder without ! and start again. Nothing was changed.
echo.
if defined PH_PAUSE pause
exit /b 1
