@echo off
:: The end of a GUI start. CALLed by gui.cmd on its pre-parsed line once the
:: GUI, or a check before it, ended; that exit code is in ERRORLEVEL and is
:: passed on. PH_SESSION (set by session.cmd) says whether the GUI ran.
set "PH_RC=%ERRORLEVEL%"
if not "%PH_RC%"=="0" if defined PH_SESSION (
    echo.
    echo GUI exited with an error. Check the output above.
    if defined PH_PAUSE pause
)
exit /b %PH_RC%
