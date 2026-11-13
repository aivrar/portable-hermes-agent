@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================
echo   Hermes Agent - Windows Installer
echo ============================================
echo.
echo   This script sets up EVERYTHING from scratch:
echo   - Embedded Python 3.14 (portable, no system install)
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

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python_embedded"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
if not defined HERMES_HOME set "HERMES_HOME=%USERPROFILE%\.hermes"

:: Non-interactive mode never waits for a key press.
set "PH_PAUSE=1"
if defined HERMES_PORTABLE_NONINTERACTIVE if not "%HERMES_PORTABLE_NONINTERACTIVE%"=="0" set "PH_PAUSE="
for %%A in (%*) do (
    if /i "%%~A"=="--yes" set "PH_PAUSE="
    if /i "%%~A"=="-y" set "PH_PAUSE="
)
if not defined PH_PAUSE set "HERMES_PORTABLE_NONINTERACTIVE=1"

:: Current upstream Hermes runs on Python 3.14 only.
set "PYTHON_VERSION=3.14.9"
set "PYTHON_MINOR=314"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
set "PYTHON_ZIP=%SCRIPT_DIR%python_embedded.zip"
set "TCLTK_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/amd64/tcltk.msi"
set "TCLTK_MSI=%SCRIPT_DIR%tcltk.msi"
set "TCLTK_TEMP=%SCRIPT_DIR%_tcltk_temp"

:: ============================================
:: Step 1: Download Embedded Python
:: ============================================
if exist "%PYTHON_EXE%" (
    echo [OK] Embedded Python already installed.
    "%PYTHON_EXE%" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 14) else 5)" >nul 2>&1
    if errorlevel 5 (
        echo [WARN] This folder uses an older portable Python. It is kept as it is.
        echo        Current upstream Hermes needs Python 3.14, so the core stays at the
        echo        newest version this runtime can run. For the newest core, extract a
        echo        new Portable Hermes release into a new folder and run START.bat.
    )
    goto :check_pip
)

echo [STEP 1/10] Downloading Python %PYTHON_VERSION% embedded...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "$ProgressPreference = 'SilentlyContinue';" ^
    "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_ZIP%' -UseBasicParsing -ErrorAction Stop"

if not exist "%PYTHON_ZIP%" (
    echo ERROR: Failed to download Python. Check your internet connection.
    goto :fail
)

echo [STEP 1/10] Extracting Python...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Expand-Archive -Path '%PYTHON_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"

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

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$pthFiles = Get-ChildItem '%PYTHON_DIR%\python*._pth';" ^
    "if ($pthFiles.Count -gt 0) {" ^
    "  $pth = $pthFiles[0];" ^
    "  $zipName = (Get-ChildItem '%PYTHON_DIR%\python*.zip' | Select-Object -First 1).Name;" ^
    "  if (-not $zipName) { $zipName = 'python%PYTHON_MINOR%.zip' };" ^
    "  $content = @($zipName, '.', 'Lib', 'Lib\site-packages', 'DLLs', '', 'import site');" ^
    "  $content | Set-Content -Path $pth.FullName -Encoding ASCII;" ^
    "  Write-Host '   Configured:' $pth.Name" ^
    "}"

:: ============================================
:: Step 3: Bootstrap pip
:: ============================================
:check_pip
"%PYTHON_EXE%" -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [STEP 3/10] Installing pip...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
        "$ProgressPreference = 'SilentlyContinue';" ^
        "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%PYTHON_DIR%\get-pip.py' -UseBasicParsing -ErrorAction Stop"
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
if not exist "%PYTHON_DIR%\Lib\tkinter" (
    echo [STEP 5/10] Installing Tkinter GUI support...

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
        "$ProgressPreference = 'SilentlyContinue';" ^
        "Invoke-WebRequest -Uri '%TCLTK_URL%' -OutFile '%TCLTK_MSI%' -UseBasicParsing -ErrorAction Stop"

    if exist "!TCLTK_MSI!" (
        :: Use PowerShell Start-Process -Wait for reliable synchronous extraction.
        :: "start /wait msiexec /a" can return before extraction completes on
        :: Windows 11 Enterprise with restrictive Group Policy, leaving DLLs absent.
        powershell -NoProfile -ExecutionPolicy Bypass -Command ^
            "$p = Start-Process msiexec.exe -ArgumentList '/a','\"!TCLTK_MSI!\"','/qn','TARGETDIR=\"!TCLTK_TEMP!\"' -Wait -WindowStyle Hidden -PassThru; if ($p.ExitCode -ne 0) { exit $p.ExitCode }"
        if exist "!TCLTK_TEMP!\DLLs" (
            xcopy /E /Y /Q "!TCLTK_TEMP!\DLLs\*" "%PYTHON_DIR%\DLLs\" >nul 2>nul
            copy /Y "!TCLTK_TEMP!\DLLs\*.dll" "%PYTHON_DIR%\" >nul 2>nul
            copy /Y "!TCLTK_TEMP!\DLLs\*.pyd" "%PYTHON_DIR%\" >nul 2>nul
            xcopy /E /Y /Q "!TCLTK_TEMP!\Lib\tkinter\*" "%PYTHON_DIR%\Lib\tkinter\" >nul 2>nul
            xcopy /E /Y /Q "!TCLTK_TEMP!\tcl\*" "%PYTHON_DIR%\tcl\" >nul 2>nul
            if not exist "%PYTHON_DIR%\libs" mkdir "%PYTHON_DIR%\libs"
            xcopy /E /Y /Q "!TCLTK_TEMP!\libs\*" "%PYTHON_DIR%\libs\" >nul 2>nul
            echo [OK] Tkinter installed.
        ) else (
            echo ERROR: Tkinter extraction failed.
            del "!TCLTK_MSI!" 2>nul
            goto :fail
        )
        rmdir /S /Q "!TCLTK_TEMP!" 2>nul
        del "!TCLTK_MSI!" 2>nul
    ) else (
        echo ERROR: Could not download Tkinter.
        goto :fail
    )
) else (
    echo [OK] Tkinter already installed.
)

set "TCL_LIBRARY=%PYTHON_DIR%\tcl\tcl8.6"
set "TK_LIBRARY=%PYTHON_DIR%\tcl\tk8.6"
"%PYTHON_EXE%" -c "import tkinter; tkinter.Tcl()" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Embedded Python cannot load Tkinter after installation.
    goto :fail
)

:: ============================================
:: Step 6: Git submodules (developer clones only)
:: ============================================
echo [STEP 6/10] Checking git submodules...
if not exist "%SCRIPT_DIR%.git" (
    echo [OK] Release install - no submodules needed.
    goto :after_submodules
)
where git >nul 2>&1
if %errorlevel% equ 0 (
    cd /d "%SCRIPT_DIR%"
    git submodule update --init --recursive --quiet 2>nul
    if exist "%SCRIPT_DIR%mini-swe-agent\pyproject.toml" (
        echo [OK] Submodules initialized.
    ) else (
        echo [INFO] Submodules not available - some features may be limited.
    )
) else (
    echo [INFO] Git not found - skipping submodules.
)
:after_submodules

:: ============================================
:: Step 6b: Create run_py.sh helper (Unix line endings!)
:: ============================================
echo [STEP 6b] Creating Python helper script...
"%PYTHON_EXE%" -c "f=open(r'%SCRIPT_DIR%run_py.sh','wb');f.write(b'#!/bin/bash\n\"$(dirname \"$0\")/python_embedded/python.exe\" \"$@\"\n');f.close()"
echo [OK] run_py.sh created.

:: ============================================
:: Step 7: Hermes core + Python dependencies
:: ============================================
:: Put this folder on the embedded interpreter's path (rewritten every run so a
:: moved or renamed folder keeps working).
set "PTH_FILE=%PYTHON_DIR%\Lib\site-packages\hermes_project.pth"
"%PYTHON_EXE%" -c "import sys; open(sys.argv[1], 'w', encoding='utf-8').write(sys.argv[2] + chr(10))" "!PTH_FILE!" "%SCRIPT_DIR%."
if errorlevel 1 (
    echo ERROR: Could not write hermes_project.pth.
    goto :fail
)

echo [STEP 7/10] Installing the Hermes core and its Python dependencies...
echo        (downloads NousResearch/hermes-agent; several minutes on first run)
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); from portable_hermes.__main__ import main; sys.exit(main(sys.argv[1:]))" "%SCRIPT_DIR%." core install
set "CORE_EXIT=%ERRORLEVEL%"
if "%CORE_EXIT%"=="3" (
    echo [WARN] The newest Hermes core could not be installed; the existing core was kept.
) else if not "%CORE_EXIT%"=="0" (
    echo ERROR: Failed to install the Hermes core. See the reason above.
    goto :fail
)

:: Developer clones only: the optional mini-swe-agent submodule.
if exist "%SCRIPT_DIR%mini-swe-agent\pyproject.toml" (
    "%PYTHON_EXE%" -m pip install -e "%SCRIPT_DIR%mini-swe-agent" --quiet 2>nul
)

echo [OK] Hermes core and Python dependencies installed.

:: ============================================
:: Step 8: Node.js dependencies
:: ============================================
echo [STEP 8/10] Installing Node.js dependencies...
set "NODE_DONE="
if exist "%SCRIPT_DIR%pnpm-workspace.yaml" (
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
set "NPM_PATH_FILE=%SCRIPT_DIR%.portable_npm_path.tmp"
"%PYTHON_EXE%" -c "from pathlib import Path; from hermes_constants import bootstrap_hermes_managed_node; Path(r'%NPM_PATH_FILE%').write_text(bootstrap_hermes_managed_node() or '', encoding='utf-8')" 2>nul
set "NPM_CMD="
if exist "%NPM_PATH_FILE%" set /p "NPM_CMD="<"%NPM_PATH_FILE%"
del "%NPM_PATH_FILE%" 2>nul
if not defined NPM_CMD goto :node_install_failed
if not exist "%NPM_CMD%" goto :node_install_failed
for %%I in ("%NPM_CMD%") do set "MANAGED_NODE_DIR=%%~dpI"
set "PATH=%MANAGED_NODE_DIR%;%PATH%"
cd /d "%SCRIPT_DIR%"
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
    if exist "%SCRIPT_DIR%.env" (
        copy "%SCRIPT_DIR%.env" "%HERMES_HOME%\.env" >nul
    ) else if exist "%SCRIPT_DIR%.env.example" (
        copy "%SCRIPT_DIR%.env.example" "%HERMES_HOME%\.env" >nul
    )
) else (
    echo [OK] .env already exists in Hermes home.
)

:: Active-profile config.yaml. Preserve and migrate the legacy portable config.
if not exist "%HERMES_HOME%\config.yaml" (
    if exist "%SCRIPT_DIR%cli-config.yaml" (
        copy "%SCRIPT_DIR%cli-config.yaml" "%HERMES_HOME%\config.yaml" >nul
    ) else if exist "%SCRIPT_DIR%cli-config.yaml.example" (
        copy "%SCRIPT_DIR%cli-config.yaml.example" "%HERMES_HOME%\config.yaml" >nul
    )
    if exist "%HERMES_HOME%\config.yaml" (
        :: Fix Unicode chars that break on older Windows consoles.
        "%PYTHON_EXE%" -c "p=r'%HERMES_HOME%\config.yaml';f=open(p,'r',encoding='utf-8');c=f.read();f.close();c=c.replace('\u2014','--').replace('\u2192','->');f=open(p,'w',encoding='utf-8');f.write(c);f.close()" 2>nul
        echo [OK] Created config.yaml in Hermes home.
    )
)

:: Default personality
if not exist "%HERMES_HOME%\SOUL.md" (
    if exist "%SCRIPT_DIR%assets\SOUL.md" (
        copy "%SCRIPT_DIR%assets\SOUL.md" "%HERMES_HOME%\SOUL.md" >nul
    )
)

:: Default permissions
if not exist "%HERMES_HOME%\permissions.json" (
    "%PYTHON_EXE%" -c "import json;json.dump({'read':2,'write':1,'install':1,'execute':2,'remove':1,'network':2},open(r'%HERMES_HOME%\permissions.json','w'),indent=2)" 2>nul
    echo [OK] Default permissions created.
)

:: ============================================
:: Step 10: Sync skills
:: ============================================
echo [STEP 10/10] Syncing skills...
cd /d "%SCRIPT_DIR%"
"%PYTHON_EXE%" "%SCRIPT_DIR%tools\skills_sync.py" 2>nul
if errorlevel 1 (
    :: Fallback: manual copy
    if exist "%SCRIPT_DIR%skills" (
        xcopy /E /Y /Q "%SCRIPT_DIR%skills\*" "%HERMES_HOME%\skills\" >nul 2>nul
    )
)
echo [OK] Skills synced.

:: ============================================
:: Final verification - never claim success for a partial install
:: ============================================
echo [VERIFY] Checking embedded agent runtime, GUI, profile, and portable skills...
:: Fresh-process check of the installed tree: core imports, portable tools in
:: the default CLI and GUI tool selection, GUI modules, Python version.
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); from portable_hermes.__main__ import main; sys.exit(main(sys.argv[1:]))" "%SCRIPT_DIR%." verify
if errorlevel 1 (
    echo ERROR: Agent runtime verification failed. Run install.bat again to repair it.
    goto :fail
)
"%PYTHON_EXE%" -c "import os, tkinter; from pathlib import Path; import gui.app, hermes_cli; tkinter.Tcl(); h=Path(os.environ['HERMES_HOME']); required=['.env','config.yaml','permissions.json','SOUL.md','skills/getting-started/SKILL.md','skills/lm-studio/SKILL.md','skills/extensions/portable-comfyui/SKILL.md','skills/extensions/music-server/SKILL.md','skills/extensions/tts-server/SKILL.md']+(['node/node.exe','node/npm.cmd'] if os.environ.get('NODE_DONE') else []); missing=[p for p in required if not (h/p).is_file()]; assert not missing, 'missing profile files: '+', '.join(missing)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Installation verification failed. Run install.bat again to repair it.
    goto :fail
)
if defined NODE_DONE if not exist "%SCRIPT_DIR%node_modules\.package-lock.json" (
    echo ERROR: Node.js dependency verification failed. Run install.bat again to repair it.
    goto :fail
)
echo [OK] Embedded GUI, profile, and portable skills verified.

:: ============================================
:: Done!
:: ============================================
echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo   What's installed:
echo     - Python 3.14 (portable)
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
exit /b 1
