@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================
echo   Hermes Agent - Windows Installer
echo ============================================
echo.
echo   This script sets up EVERYTHING from scratch:
echo   - Embedded Python 3.13 (portable, no system install)
echo   - Tkinter GUI support
echo   - All Python dependencies + extras
echo   - LM Studio SDK
echo   - Node.js dependencies (browser tools)
echo   - Git submodules (mini-swe-agent)
echo   - Skills sync (89+ skills)
echo   - Environment configuration
echo   - Default permissions
echo.
echo   No admin rights needed. No system changes.
echo   Everything stays inside this folder.
echo.

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python_embedded"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

set "PYTHON_VERSION=3.13.12"
set "PYTHON_URL=https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip"
set "PYTHON_ZIP=%SCRIPT_DIR%python_embedded.zip"
set "TCLTK_URL=https://www.python.org/ftp/python/3.13.12/amd64/tcltk.msi"

:: ============================================
:: Step 1: Download Embedded Python
:: ============================================
if exist "%PYTHON_EXE%" (
    echo [OK] Embedded Python already installed.
    goto :check_pip
)

echo [STEP 1/10] Downloading Python %PYTHON_VERSION% embedded...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "$ProgressPreference = 'SilentlyContinue';" ^
    "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_ZIP%'"

if not exist "%PYTHON_ZIP%" (
    echo ERROR: Failed to download Python. Check your internet connection.
    pause
    exit /b 1
)

echo [STEP 1/10] Extracting Python...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Expand-Archive -Path '%PYTHON_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python extraction failed.
    pause
    exit /b 1
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
    "  if (-not $zipName) { $zipName = 'python313.zip' };" ^
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
        "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%PYTHON_DIR%\get-pip.py'"
    "%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --quiet
    if errorlevel 1 (
        echo ERROR: Failed to install pip.
        pause
        exit /b 1
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

:: ============================================
:: Step 5: Install Tkinter (GUI support)
:: ============================================
if not exist "%PYTHON_DIR%\Lib\tkinter" (
    echo [STEP 5/10] Installing Tkinter GUI support...
    set "TCLTK_MSI=%SCRIPT_DIR%tcltk.msi"
    set "TCLTK_TEMP=%SCRIPT_DIR%_tcltk_temp"

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference = 'SilentlyContinue';" ^
        "Invoke-WebRequest -Uri '%TCLTK_URL%' -OutFile '%TCLTK_MSI%'"

    if exist "!TCLTK_MSI!" (
        :: Use PowerShell Start-Process -Wait for reliable synchronous extraction.
        :: "start /wait msiexec /a" can return before extraction completes on
        :: Windows 11 Enterprise with restrictive Group Policy, leaving DLLs absent.
        powershell -NoProfile -ExecutionPolicy Bypass -Command ^
            "Start-Process msiexec.exe -ArgumentList '/a','\"!TCLTK_MSI!\"','/qn','TARGETDIR=\"!TCLTK_TEMP!\"' -Wait -NoNewWindow"
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
            echo [WARN] Tkinter extraction failed - GUI may not work.
        )
        rmdir /S /Q "!TCLTK_TEMP!" 2>nul
        del "!TCLTK_MSI!" 2>nul
    ) else (
        echo [WARN] Could not download Tkinter - GUI may not work.
    )
) else (
    echo [OK] Tkinter already installed.
)

:: ============================================
:: Step 6: Git submodules
:: ============================================
echo [STEP 6/10] Initializing git submodules...
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

:: ============================================
:: Step 6b: Create run_py.sh helper (Unix line endings!)
:: ============================================
echo [STEP 6b] Creating Python helper script...
"%PYTHON_EXE%" -c "f=open(r'%SCRIPT_DIR%run_py.sh','wb');f.write(b'#!/bin/bash\n\"$(dirname \"$0\")/python_embedded/python.exe\" \"$@\"\n');f.close()"
echo [OK] run_py.sh created.

:: ============================================
:: Step 7: Install ALL Python dependencies
:: ============================================
echo [STEP 7/10] Installing Python dependencies...
echo        (this may take several minutes on first run)

:: Main package
"%PYTHON_EXE%" -m pip install -e "%SCRIPT_DIR%." --quiet 2>nul
if errorlevel 1 (
    "%PYTHON_EXE%" -m pip install -r "%SCRIPT_DIR%requirements.txt" --quiet 2>nul
)

:: Guarantee the project root is on sys.path regardless of editable-install outcome.
:: Embedded Python does not create .egg-link / .pth files the same way as regular
:: Python, so pip install -e . may succeed (exit 0) but leave hermes_cli unreachable.
set "PTH_FILE=%PYTHON_DIR%\Lib\site-packages\hermes_project.pth"
if not exist "!PTH_FILE!" (
    echo %SCRIPT_DIR%> "!PTH_FILE!"
    echo [OK] hermes_project.pth created.
)

:: All optional extras
"%PYTHON_EXE%" -m pip install -e "%SCRIPT_DIR%.[messaging,cron,cli,mcp,honcho,pty,tts-premium,homeassistant]" --quiet 2>nul

:: Mini-swe-agent
if exist "%SCRIPT_DIR%mini-swe-agent\pyproject.toml" (
    "%PYTHON_EXE%" -m pip install -e "%SCRIPT_DIR%mini-swe-agent" --quiet 2>nul
)

:: Extra packages needed for Windows GUI
"%PYTHON_EXE%" -m pip install Pillow ddgs lmstudio --quiet 2>nul

echo [OK] Python dependencies installed.

:: ============================================
:: Step 8: Node.js dependencies
:: ============================================
echo [STEP 8/10] Installing Node.js dependencies...
where node >nul 2>&1
if %errorlevel% equ 0 (
    if exist "%SCRIPT_DIR%package.json" (
        cd /d "%SCRIPT_DIR%"
        npm install --quiet 2>nul
        echo [OK] Node.js dependencies installed.
    )
) else (
    echo [INFO] Node.js not found - browser tools and WhatsApp bridge won't be available.
    echo        Install Node.js from https://nodejs.org/ and re-run this installer.
)

:: ============================================
:: Step 9: Environment and config files
:: ============================================
echo [STEP 9/10] Setting up configuration...

:: .env
if not exist "%SCRIPT_DIR%.env" (
    if exist "%SCRIPT_DIR%.env.example" (
        copy "%SCRIPT_DIR%.env.example" "%SCRIPT_DIR%.env" >nul
        echo [OK] Created .env from template.
    )
) else (
    echo [OK] .env already exists.
)

:: cli-config.yaml
if not exist "%SCRIPT_DIR%cli-config.yaml" (
    if exist "%SCRIPT_DIR%cli-config.yaml.example" (
        copy "%SCRIPT_DIR%cli-config.yaml.example" "%SCRIPT_DIR%cli-config.yaml" >nul
        :: Fix Unicode chars that break on Windows
        "%PYTHON_EXE%" -c "p=r'%SCRIPT_DIR%cli-config.yaml';f=open(p,'r',encoding='utf-8');c=f.read();f.close();c=c.replace('\u2014','--').replace('\u2192','->');f=open(p,'w',encoding='utf-8');f.write(c);f.close()" 2>nul
        echo [OK] Created cli-config.yaml.
    )
)

:: Create ~/.hermes directory
if not exist "%USERPROFILE%\.hermes" mkdir "%USERPROFILE%\.hermes"

:: Default permissions
if not exist "%USERPROFILE%\.hermes\permissions.json" (
    "%PYTHON_EXE%" -c "import json;json.dump({'read':2,'write':1,'install':1,'execute':2,'remove':1,'network':2},open(r'%USERPROFILE%\.hermes\permissions.json','w'),indent=2)" 2>nul
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
        xcopy /E /Y /Q "%SCRIPT_DIR%skills\*" "%USERPROFILE%\.hermes\skills\" >nul 2>nul
    )
)
echo [OK] Skills synced.

:: ============================================
:: Done!
:: ============================================
echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo   What's installed:
echo     - Python 3.13 (portable)
echo     - Tkinter GUI
echo     - 100 AI tools across 20+ toolsets
echo     - 88+ skills
echo     - LM Studio SDK
echo     - Browser automation
echo.
echo   To start:
echo     hermes_gui.bat     Desktop GUI (recommended)
echo     hermes.bat         Command-line interface
echo.
echo   First time? The app will guide you through
echo   setting up your API keys on first launch.
echo.

pause
endlocal
