@echo off
:: Portable Hermes installer. Re-runnable: every step skips what is already
:: in place. Paths are passed to PowerShell and Python through environment
:: variables and arguments, never pasted into code, so install folders with
:: spaces, apostrophes, parentheses, ampersands or brackets work. Folders
:: whose path contains ! %% or ^^ are refused by env.cmd before anything runs.
::
::   install.bat [--yes]               full install or repair
::   install.bat --runtime-upgrade     used by launch\runtime.cmd only: build
::                                     the pinned Python from nothing, then
::                                     install the core. Exit code 11 means the
::                                     core was installed but a later step failed.
setlocal disabledelayedexpansion
pushd "%~dp0"
for %%I in ("%~dp0.") do set "PH_ROOT=%%~fI"
call .\portable_hermes\launch\env.cmd %*
if errorlevel 1 exit /b 1

:: An interrupted update is settled first. The recovery may put back an older
:: copy of this very file, so it runs inside one parenthesised block (read
:: completely before it runs), which then starts install.bat again.
if exist "%PH_STATE%\journal.json" if exist "%PYTHON_EXE%" if exist "%PH_STATE%\recover.py" (
    echo   Finishing an update that was interrupted...
    set "PORTABLE_HERMES_NO_HOOK=1"
    "%PYTHON_EXE%" -I -X utf8 "%PH_STATE%\recover.py" "%PH_ROOT%\."
    if errorlevel 1 (
        if defined PH_PAUSE pause
        exit /b 1
    )
    set "PORTABLE_HERMES_NO_HOOK="
    call .\install.bat %*
    call exit /b %%ERRORLEVEL%%
)

setlocal enabledelayedexpansion
set "PH_UPGRADE="
for %%A in (%*) do if /i "%%~A"=="--runtime-upgrade" set "PH_UPGRADE=1"
if defined PH_UPGRADE (
    set "PH_PAUSE="
    set "HERMES_PORTABLE_NONINTERACTIVE=1"
)
set "PH_CORE_DONE="

if not defined PH_PYTHON_PIN (
    echo ERROR: portable_hermes\manifests\python-runtime.txt is missing. Extract the
    echo        complete Portable Hermes release again.
    goto :fail
)
set "PYTHON_VERSION=%PH_PYTHON_PIN%"
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do set "PYTHON_MINOR=%%a%%b"

echo.
echo ============================================
if defined PH_UPGRADE (
    echo   Hermes Agent - Portable Python upgrade
) else (
    echo   Hermes Agent - Windows Installer
)
echo ============================================
echo.
echo   This script sets up EVERYTHING from scratch:
echo   - Embedded Python %PYTHON_VERSION% (portable, no system install)
echo   - Tkinter GUI support
echo   - The latest Hermes Agent core from NousResearch/hermes-agent
echo   - All Python dependencies + extras, LM Studio SDK
echo   - Skills sync, environment configuration, default permissions
echo.
echo   No admin rights needed. No system changes.
echo   Everything stays inside this folder.
echo.
echo   Unattended install: install.bat --yes  (or HERMES_PORTABLE_NONINTERACTIVE=1)
echo   Core source overrides: HERMES_PORTABLE_CORE_ZIP, HERMES_PORTABLE_CORE_REF
echo.

:: A first install (or a Python upgrade) is marked until it finishes, so the
:: launchers run setup again instead of starting a half-installed folder.
set "PH_MARKED="
if not exist "%PYTHON_EXE%" (
    if not exist "%PH_STATE%" mkdir "%PH_STATE%"
    > "%PH_STATE%\installing" echo install.bat started %DATE% %TIME%
    set "PH_MARKED=1"
)

set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
set "PYTHON_ZIP=%PH_ROOT%\python_embedded.zip"
set "TCLTK_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/amd64/tcltk.msi"
set "TCLTK_MSI=%PH_ROOT%\tcltk.msi"
set "TCLTK_TEMP=%PH_ROOT%\_tcltk_temp"

:: ============================================
:: Step 1: Download Embedded Python
:: ============================================
if exist "%PYTHON_EXE%" (
    echo [OK] Embedded Python already installed.
    goto :check_pip
)

echo [STEP 1/10] Downloading Python %PYTHON_VERSION% embedded...
set "PH_URL=%PYTHON_URL%"
set "PH_OUT=%PYTHON_ZIP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "try { (New-Object Net.WebClient).DownloadFile($env:PH_URL, $env:PH_OUT) } catch { Write-Host $_.Exception.Message; exit 1 }"
if not exist "%PYTHON_ZIP%" (
    echo ERROR: Failed to download Python. Check your internet connection.
    goto :fail
)

echo [STEP 1/10] Extracting Python...
set "PH_ZIP=%PYTHON_ZIP%"
set "PH_DEST=%PYTHON_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Expand-Archive -LiteralPath $env:PH_ZIP -DestinationPath $env:PH_DEST -Force -ErrorAction Stop } catch { Write-Host $_.Exception.Message; exit 1 }"
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python extraction failed.
    goto :fail
)
del "%PYTHON_ZIP%" 2>nul

:: ============================================
:: Step 2: Configure ._pth for site-packages
:: ============================================
echo [STEP 2/10] Configuring Python for package installation...

if not exist "%PYTHON_DIR%\Lib\site-packages" mkdir "%PYTHON_DIR%\Lib\site-packages"
if not exist "%PYTHON_DIR%\DLLs" mkdir "%PYTHON_DIR%\DLLs"

set "PH_PYDIR=%PYTHON_DIR%"
set "PH_MINOR=%PYTHON_MINOR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$pth = Get-ChildItem -LiteralPath $env:PH_PYDIR -Filter 'python*._pth' | Select-Object -First 1;" ^
    "if ($pth) {" ^
    "  $zip = Get-ChildItem -LiteralPath $env:PH_PYDIR -Filter 'python*.zip' | Select-Object -First 1;" ^
    "  $zipName = if ($zip) { $zip.Name } else { 'python' + $env:PH_MINOR + '.zip' };" ^
    "  $content = @($zipName, '.', 'Lib', 'Lib\site-packages', 'DLLs', '', 'import site');" ^
    "  Set-Content -LiteralPath $pth.FullName -Value $content -Encoding ASCII;" ^
    "  Write-Host '   Configured:' $pth.Name" ^
    "}"

:: ============================================
:: Step 3: Bootstrap pip
:: ============================================
:check_pip
"%PYTHON_EXE%" -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [STEP 3/10] Installing pip...
    set "PH_URL=https://bootstrap.pypa.io/get-pip.py"
    set "PH_OUT=%PYTHON_DIR%\get-pip.py"
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
        "try { (New-Object Net.WebClient).DownloadFile($env:PH_URL, $env:PH_OUT) } catch { Write-Host $_.Exception.Message; exit 1 }"
    "%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --quiet
    if errorlevel 1 (
        echo ERROR: Failed to install pip.
        goto :fail
    )
    del "%PYTHON_DIR%\get-pip.py" 2>nul
    "%PYTHON_EXE%" -m pip install --upgrade pip --quiet 2>nul
) else (
    echo [OK] pip already available.
)

:: ============================================
:: Step 4: Install setuptools (needed for editable installs)
:: ============================================
echo [STEP 4/10] Installing build tools...
"%PYTHON_EXE%" -m pip install setuptools wheel --quiet 2>nul
if errorlevel 1 (
    echo ERROR: Failed to install Python build tools.
    goto :fail
)

:: ============================================
:: Step 5: Install Tkinter (GUI support)
:: ============================================
if exist "%PYTHON_DIR%\Lib\tkinter" (
    echo [OK] Tkinter already installed.
    goto :check_tk
)
echo [STEP 5/10] Installing Tkinter GUI support...
set "PH_URL=%TCLTK_URL%"
set "PH_OUT=%TCLTK_MSI%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "try { (New-Object Net.WebClient).DownloadFile($env:PH_URL, $env:PH_OUT) } catch { Write-Host $_.Exception.Message; exit 1 }"
if not exist "%TCLTK_MSI%" (
    echo ERROR: Could not download Tkinter.
    goto :fail
)
:: PowerShell Start-Process -Wait for reliable synchronous extraction:
:: "start /wait msiexec /a" can return before extraction completes on
:: Windows 11 Enterprise with restrictive Group Policy, leaving DLLs absent.
set "PH_MSI=%TCLTK_MSI%"
set "PH_TCLTMP=%TCLTK_TEMP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$q = [char]34; $msiArgs = @('/a', ($q + $env:PH_MSI + $q), '/qn', ('TARGETDIR=' + $q + $env:PH_TCLTMP + $q));" ^
    "$p = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -WindowStyle Hidden -PassThru; if ($p.ExitCode -ne 0) { exit $p.ExitCode }"
if not exist "%TCLTK_TEMP%\DLLs" (
    echo ERROR: Tkinter extraction failed.
    del "%TCLTK_MSI%" 2>nul
    goto :fail
)
xcopy /E /Y /Q "%TCLTK_TEMP%\DLLs\*" "%PYTHON_DIR%\DLLs\" >nul 2>nul
copy /Y "%TCLTK_TEMP%\DLLs\*.dll" "%PYTHON_DIR%\" >nul 2>nul
copy /Y "%TCLTK_TEMP%\DLLs\*.pyd" "%PYTHON_DIR%\" >nul 2>nul
xcopy /E /Y /Q /I "%TCLTK_TEMP%\Lib\tkinter\*" "%PYTHON_DIR%\Lib\tkinter\" >nul 2>nul
xcopy /E /Y /Q /I "%TCLTK_TEMP%\tcl\*" "%PYTHON_DIR%\tcl\" >nul 2>nul
if not exist "%PYTHON_DIR%\libs" mkdir "%PYTHON_DIR%\libs"
xcopy /E /Y /Q "%TCLTK_TEMP%\libs\*" "%PYTHON_DIR%\libs\" >nul 2>nul
rmdir /S /Q "%TCLTK_TEMP%" 2>nul
del "%TCLTK_MSI%" 2>nul
echo [OK] Tkinter installed.

:check_tk
"%PYTHON_EXE%" -c "import tkinter; tkinter.Tcl()" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Embedded Python cannot load Tkinter after installation.
    goto :fail
)

:: ============================================
:: Step 6: Git submodules (developer clones only)
:: ============================================
echo [STEP 6/10] Checking git submodules...
if not exist "%PH_ROOT%\.git" (
    echo [OK] Release install - no submodules needed.
    goto :after_submodules
)
where git >nul 2>&1
if %errorlevel% equ 0 (
    git submodule update --init --recursive --quiet 2>nul
    if exist "%PH_ROOT%\mini-swe-agent\pyproject.toml" (
        echo [OK] Submodules initialized.
    ) else (
        echo [INFO] Submodules not available - some features may be limited.
    )
) else (
    echo [INFO] Git not found - skipping submodules.
)
:after_submodules

:: ============================================
:: Step 6b: Create run_py.sh helper (Unix line endings)
:: ============================================
echo [STEP 6b] Creating Python helper script...
"%PYTHON_EXE%" -c "import sys; q = chr(34); open(sys.argv[1], 'wb').write(('#!/bin/bash' + chr(10) + q + '$(dirname ' + q + '$0' + q + ')/python_embedded/python.exe' + q + ' ' + q + '$@' + q + chr(10)).encode('ascii'))" "%PH_ROOT%\run_py.sh"
echo [OK] run_py.sh created.

:: ============================================
:: Step 7: Hermes core + Python dependencies
:: ============================================
:: Put this folder on the embedded interpreter's path (rewritten every run so a
:: moved or renamed folder keeps working).
set "PTH_FILE=%PYTHON_DIR%\Lib\site-packages\hermes_project.pth"
"%PYTHON_EXE%" -c "import sys; open(sys.argv[1], 'w', encoding='utf-8').write(sys.argv[2] + chr(10))" "%PTH_FILE%" "%PH_ROOT%"
if errorlevel 1 (
    echo ERROR: Could not write hermes_project.pth.
    goto :fail
)

echo [STEP 7/10] Installing the Hermes core and its Python dependencies...
echo        (downloads NousResearch/hermes-agent; several minutes on first run)
"%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." core install
set "CORE_EXIT=%ERRORLEVEL%"
if "%CORE_EXIT%"=="4" if not defined PH_UPGRADE (
    rem The newest core needs a newer portable Python: upgrade it in place.
    call .\portable_hermes\launch\runtime.cmd
    set "PH_RUNTIME_EXIT=!ERRORLEVEL!"
    if defined PH_PAUSE pause
    exit /b !PH_RUNTIME_EXIT!
)
if "%CORE_EXIT%"=="3" if not defined PH_UPGRADE (
    echo [WARN] The newest Hermes core could not be installed; the existing core was kept.
    goto :core_done
)
if not "%CORE_EXIT%"=="0" (
    echo ERROR: Failed to install the Hermes core. See the reason above.
    goto :fail
)
:core_done
set "PH_CORE_DONE=1"

:: Developer clones only: the optional mini-swe-agent submodule.
if exist "%PH_ROOT%\mini-swe-agent\pyproject.toml" (
    "%PYTHON_EXE%" -m pip install -e "%PH_ROOT%\mini-swe-agent" --quiet 2>nul
)

echo [OK] Hermes core and Python dependencies installed.

:: ============================================
:: Step 8: Node.js dependencies
:: ============================================
echo [STEP 8/10] Installing Node.js dependencies...
set "NODE_DONE="
if exist "%PH_ROOT%\pnpm-workspace.yaml" (
    echo [INFO] This Hermes core manages its Node.js packages with pnpm workspaces.
    echo        Skipped: optional for the portable bundle. Browser tools that need
    echo        Node.js packages stay unavailable until they are installed.
    goto :node_install_complete
)
"%PYTHON_EXE%" -c "import sys, hermes_constants; sys.exit(0 if hasattr(hermes_constants, 'bootstrap_hermes_managed_node') else 7)" >nul 2>&1
if errorlevel 7 (
    echo [INFO] This Hermes core has no managed Node.js bootstrap. Skipped - optional.
    goto :node_install_complete
)
echo        Provisioning a portable Hermes-managed Node.js runtime...
set "NPM_PATH_FILE=%PH_STATE%\npm-path.tmp"
if not exist "%PH_STATE%" mkdir "%PH_STATE%"
"%PYTHON_EXE%" -c "import sys; from pathlib import Path; from hermes_constants import bootstrap_hermes_managed_node; Path(sys.argv[1]).write_text(bootstrap_hermes_managed_node() or '', encoding='utf-8')" "%NPM_PATH_FILE%" 2>nul
set "NPM_CMD="
if exist "%NPM_PATH_FILE%" set /p "NPM_CMD="<"%NPM_PATH_FILE%"
del "%NPM_PATH_FILE%" 2>nul
if not defined NPM_CMD goto :node_install_failed
if not exist "%NPM_CMD%" goto :node_install_failed
for %%I in ("%NPM_CMD%") do set "MANAGED_NODE_DIR=%%~dpI"
set "PATH=%MANAGED_NODE_DIR%;%PATH%"
call "%NPM_CMD%" install --quiet 2>nul
if errorlevel 1 goto :node_dependencies_failed
set "NODE_DONE=1"
echo [OK] Portable Node.js dependencies installed.
goto :node_install_complete

:node_install_failed
echo ERROR: Could not provision the portable Node.js runtime.
goto :fail

:node_dependencies_failed
echo ERROR: Failed to install Node.js dependencies.
goto :fail

:node_install_complete

:: ============================================
:: Step 9: Environment and config files
:: ============================================
echo [STEP 9/10] Setting up configuration...

if not exist "%HERMES_HOME%" mkdir "%HERMES_HOME%"

:: Active-profile .env. Copy an older portable-root file forward when present.
if not exist "%HERMES_HOME%\.env" (
    if exist "%PH_ROOT%\.env" (
        copy "%PH_ROOT%\.env" "%HERMES_HOME%\.env" >nul
    ) else if exist "%PH_ROOT%\.env.example" (
        copy "%PH_ROOT%\.env.example" "%HERMES_HOME%\.env" >nul
    )
) else (
    echo [OK] .env already exists in Hermes home.
)

:: Active-profile config.yaml. Preserve and migrate the legacy portable config.
if not exist "%HERMES_HOME%\config.yaml" (
    if exist "%PH_ROOT%\cli-config.yaml" (
        copy "%PH_ROOT%\cli-config.yaml" "%HERMES_HOME%\config.yaml" >nul
    ) else if exist "%PH_ROOT%\cli-config.yaml.example" (
        copy "%PH_ROOT%\cli-config.yaml.example" "%HERMES_HOME%\config.yaml" >nul
    )
    if exist "%HERMES_HOME%\config.yaml" (
        rem Replace characters that break on older Windows consoles.
        "%PYTHON_EXE%" -c "import sys; p = sys.argv[1]; c = open(p, encoding='utf-8').read(); open(p, 'w', encoding='utf-8').write(c.replace(chr(0x2014), '--').replace(chr(0x2192), '->'))" "%HERMES_HOME%\config.yaml" 2>nul
        echo [OK] Created config.yaml in Hermes home.
    )
)

:: Default personality
if not exist "%HERMES_HOME%\SOUL.md" (
    if exist "%PH_ROOT%\assets\SOUL.md" (
        copy "%PH_ROOT%\assets\SOUL.md" "%HERMES_HOME%\SOUL.md" >nul
    )
)

:: Default permissions
if not exist "%HERMES_HOME%\permissions.json" (
    "%PYTHON_EXE%" -c "import json, sys; json.dump({'read': 2, 'write': 1, 'install': 1, 'execute': 2, 'remove': 1, 'network': 2}, open(sys.argv[1], 'w'), indent=2)" "%HERMES_HOME%\permissions.json" 2>nul
    echo [OK] Default permissions created.
)

:: ============================================
:: Step 10: Sync skills
:: ============================================
echo [STEP 10/10] Syncing skills...
"%PYTHON_EXE%" "%PH_ROOT%\tools\skills_sync.py" 2>nul
if errorlevel 1 (
    rem Fallback: copy only skills the Hermes home does not have yet; never
    rem overwrite a skill file that is already there.
    if exist "%PH_ROOT%\skills" (
        robocopy "%PH_ROOT%\skills" "%HERMES_HOME%\skills" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
    )
)
echo [OK] Skills synced.

:: ============================================
:: Final verification - never claim success for a partial install
:: ============================================
echo [VERIFY] Checking embedded agent runtime, GUI, profile, and portable skills...
:: Fresh-process check of the installed tree: core imports, what the portable
:: GUI and tools import from the core, portable tools in the default CLI and
:: GUI tool selection, GUI modules, Python version.
"%PYTHON_EXE%" -c "%PH_BOOT%" "%PH_ROOT%\." verify
if errorlevel 1 (
    echo ERROR: Agent runtime verification failed. Run install.bat again to repair it.
    goto :fail
)
"%PYTHON_EXE%" -c "import os, tkinter; from pathlib import Path; import gui.app, hermes_cli; tkinter.Tcl(); h=Path(os.environ['HERMES_HOME']); required=['.env','config.yaml','permissions.json','SOUL.md','skills/getting-started/SKILL.md','skills/lm-studio/SKILL.md','skills/extensions/portable-comfyui/SKILL.md','skills/extensions/music-server/SKILL.md','skills/extensions/tts-server/SKILL.md']+(['node/node.exe','node/npm.cmd'] if os.environ.get('NODE_DONE') else []); missing=[p for p in required if not (h/p).is_file()]; assert not missing, 'missing profile files: '+', '.join(missing)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Installation verification failed. Run install.bat again to repair it.
    goto :fail
)
if defined NODE_DONE if not exist "%PH_ROOT%\node_modules\.package-lock.json" (
    echo ERROR: Node.js dependency verification failed. Run install.bat again to repair it.
    goto :fail
)
echo [OK] Embedded GUI, profile, and portable skills verified.

if exist "%PH_STATE%\installing" del "%PH_STATE%\installing"

:: ============================================
:: Done!
:: ============================================
echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo   What's installed:
echo     - Python %PYTHON_VERSION% (portable)
echo     - Tkinter GUI
echo     - The latest Hermes Agent core plus the portable tools
echo     - Skills and the LM Studio SDK
echo.
echo   Updates: UPDATE.bat (portable wrapper first, then optionally the core)
echo.
echo   To start:
echo     hermes_gui.bat     Desktop GUI (recommended)
echo     hermes.bat         Command-line interface
echo.
echo   First time? The app will guide you through
echo   setting up your API keys on first launch.
echo.

if defined PH_PAUSE pause
endlocal
exit /b 0

:fail
if defined PH_PAUSE pause
if defined PH_CORE_DONE exit /b 11
exit /b 1
