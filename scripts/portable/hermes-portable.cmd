@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_DIR%hermes-portable.ps1" %*
exit /b %ERRORLEVEL%
