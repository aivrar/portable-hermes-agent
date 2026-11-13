@setlocal & set "PORTABLE_HERMES_ROOT=%~dp0." & pushd "%~dp0" && call .\portable_hermes\launch\cli.cmd %* & call exit /b %%errorlevel%%
