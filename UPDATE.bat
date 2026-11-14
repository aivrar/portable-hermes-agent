@setlocal & set "PORTABLE_HERMES_ROOT=%~dp0." & pushd "%~dp0" && .\portable_hermes\launch\update.cmd %*
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                     
@echo.
@echo   Portable Hermes: the previous updater has installed the new launchers.
@echo   Run UPDATE.bat once more. It finishes the update: the portable
@echo   Python is upgraded if the newest Hermes core needs it, then the core.
@echo.
@pause
@exit /b 0
rem Everything after the first line is only read by an UPDATE.bat from
rem Portable Hermes v1.4.18 or older that replaced this file while it was
rem running: cmd.exe continues such a script at its old byte offset in the
rem new file. Lines of spaces are no-ops, so any offset up to 6000 lands
rem in blank lines and then reaches this message. Do not move the message
rem before offset 6000 or put commands in the blank part. A fresh run never
rem gets here: line 1 hands the window over to update.cmd for good.
