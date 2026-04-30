# Windows Portable Install — Diagnosis & Fixes

**Date:** 2026-04-30  
**Environment:** Windows 11 Enterprise, non-admin account, no WSL, no Docker  
**Repo version:** v0.4.0

---

## Overview

Three independent bugs prevent a fresh Windows install from starting correctly:

| # | Symptom | Root Cause | Fixed In |
|---|---------|------------|----------|
| 1 | `hermes.bat` → `ModuleNotFoundError: No module named 'hermes_cli'` | `pip install -e .` does not add the project root to embedded Python's `sys.path` | `install.bat` |
| 2 | `hermes_gui.bat` → `ModuleNotFoundError: No module named 'tkinter'` | `msiexec /a` extraction silently incomplete; `zlib1.dll` never reached `python_embedded\` | `install.bat` |
| 3 | `read_file`, `write_file`, `terminal` all fail silently | `_find_bash()` resolves `C:\Windows\system32\bash.exe` (WSL stub) before Git for Windows; WSL stub exits with "logon type not allowed" on machines where the user lacks the interactive logon right | `tools/environments/local.py` + `.env.example` |

---

## Bug 1 — `hermes_cli` not found

### Symptom

```
C:\...\portable-hermes-agent>hermes.bat
  Loading Hermes Agent...
python.exe: Error while finding module specification for 'hermes_cli.main'
(ModuleNotFoundError: No module named 'hermes_cli')
```

### Root cause

Embedded Python distributions (`.zip` + `._pth` based) do not support
PEP 660 editable installs the same way as regular Python environments.
Running `pip install -e .` creates `hermes_agent.egg-info/` at the repo
root and writes metadata, but **does not add an `.egg-link` or `.pth`
file to `Lib\site-packages\`** under the embedded Python on some Windows
configurations. The project root therefore never appears in `sys.path`.

### Verification

```python
import hermes_cli  # ModuleNotFoundError
import sys
print(sys.path)    # repo root is absent
```

### Fix applied

`install.bat` Step 7 now explicitly writes
`python_embedded\Lib\site-packages\hermes_project.pth` after the
`pip install -e .` command. A `.pth` file is the standard Python
mechanism for adding directories to `sys.path`; it works in embedded
environments where editable-install `.egg-link` files do not.

```batch
:: Guarantee the project root is on sys.path regardless of editable-install outcome
set "PTH_FILE=%PYTHON_DIR%\Lib\site-packages\hermes_project.pth"
if not exist "!PTH_FILE!" (
    echo %SCRIPT_DIR%> "!PTH_FILE!"
    echo [OK] hermes_project.pth created.
)
```

### Manual fix (for existing installs)

Create the file `python_embedded\Lib\site-packages\hermes_project.pth`
with a single line containing the absolute path to the repo root:

```
C:\path\to\portable-hermes-agent
```

Or run from the repo directory:

```batch
echo %CD%> python_embedded\Lib\site-packages\hermes_project.pth
```

---

## Bug 2 — `tkinter` not found

### Symptom

```
C:\...\portable-hermes-agent>hermes_gui.bat
Traceback (most recent call last):
  ...
  import tkinter as tk
ModuleNotFoundError: No module named 'tkinter'
GUI exited with an error. Check the output above.
```

### Root cause

The embedded Python `.zip` distribution deliberately omits Tkinter.
`install.bat` Step 5 attempts to extract it from Python's official
`tcltk.msi` using `msiexec /a` (administrative install — does not
require elevation). On Windows 11 Enterprise with restrictive Group
Policy or Windows Installer service settings, **`start /wait msiexec /a`
may return before extraction completes**, leaving `_tcltk_temp\DLLs\`
empty or absent. The `if exist "!TCLTK_TEMP!\DLLs"` guard then fails
silently, printing only `[WARN] Tkinter extraction failed`.

Even when extraction succeeds, `_tkinter.pyd` depends on **`zlib1.dll`**
at DLL-load time. This file is present in `_tcltk_temp\DLLs\` alongside
`tcl86t.dll` and `tk86t.dll`. The installer's `copy /Y *.dll` command
copies it, but if the extraction was incomplete (see above), none of the
three DLLs reach `python_embedded\`.

### Verification

```
python_embedded\DLLs\   → empty of tcl86t.dll / tk86t.dll / zlib1.dll
python_embedded\        → same files absent
python_embedded\Lib\tkinter\  → absent
python_embedded\tcl\    → absent
```

```python
import tkinter
# ImportError: DLL load failed while importing _tkinter:
#   The specified module could not be found.
```

### Fix applied

`install.bat` Step 5 now uses **PowerShell `Start-Process -Wait`**
instead of `start /wait msiexec` to ensure the extraction is synchronous
and captures the exit code reliably:

```batch
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process msiexec.exe -ArgumentList '/a','\"!TCLTK_MSI!\"','/qn','TARGETDIR=\"!TCLTK_TEMP!\"' -Wait -NoNewWindow"
```

The rest of the copy logic is unchanged; once extraction completes
correctly, all three DLLs (`tcl86t.dll`, `tk86t.dll`, `zlib1.dll`)
reach both `python_embedded\` and `python_embedded\DLLs\`.

### Manual fix (for existing installs)

```powershell
$root   = "C:\path\to\portable-hermes-agent"
$pydir  = "$root\python_embedded"
$msi    = "$root\tcltk_tmp.msi"
$tmp    = "$root\_tcltk_tmp"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest "https://www.python.org/ftp/python/3.13.12/amd64/tcltk.msi" -OutFile $msi
Start-Process msiexec.exe -ArgumentList "/a","`"$msi`"","/qn","TARGETDIR=`"$tmp`"" -Wait -NoNewWindow

# Copy DLLs (tcl86t.dll, tk86t.dll, zlib1.dll, _tkinter.pyd)
Copy-Item "$tmp\DLLs\*" "$pydir\"     -Force
Copy-Item "$tmp\DLLs\*" "$pydir\DLLs\" -Force

# Copy Tkinter Python package
Copy-Item "$tmp\Lib\tkinter\*" "$pydir\Lib\tkinter\" -Recurse -Force

# Copy Tcl/Tk runtime data
Copy-Item "$tmp\tcl\*" "$pydir\tcl\" -Recurse -Force

# Cleanup
Remove-Item $tmp -Recurse -Force
Remove-Item $msi -Force

# Verify
python_embedded\python.exe -c "import tkinter; print('OK:', tkinter.TkVersion)"
```

---

## Bug 3 — File tools / terminal fail on Windows (WSL bash resolved before Git Bash)

### Symptom

`read_file`, `write_file`, `search_files`, `terminal`, and `patch` all
appear in the tools list and register successfully, but every call
returns `"File not found"` or exits with a non-zero code — even for
files that clearly exist.

### Root cause

`tools/environments/local.py:_find_bash()` resolves the shell to use
for file and terminal tool execution. The Windows branch calls
`shutil.which("bash")` to find bash on `PATH`. On Windows 11,
`C:\Windows\System32\bash.exe` (the WSL stub) appears **before** Git
for Windows in `PATH` and is therefore returned first.

When WSL is installed but the user's account lacks the
`SeInteractiveLogonRight` privilege (common in enterprise environments
where interactive logon is restricted to the console), `system32\bash.exe`
exits immediately with a UTF-16 error message:

```
Falha de logon: não foi concedido ao usuário o tipo de logon solicitado neste computador.
(Logon failure: the user has not been granted the requested logon type at this computer.)
```

Exit code is `1`, so **every shell command run by the file and terminal
tools returns "command not found" or empty output**, and `wc -c` in
`read_file` exits non-zero → `"File not found"` for every path.

Git for Windows bash (at `%LOCALAPPDATA%\Programs\Git\bin\bash.exe` for
user-level installs) works correctly but is never reached because
`shutil.which` returns the WSL stub first.

### Verification

```python
import subprocess
r = subprocess.run(
    [r"C:\Windows\System32\bash.exe", "-c", "echo hello"],
    capture_output=True, text=True, timeout=5
)
print(r.returncode)   # 1
print(r.stdout)       # UTF-16 "Logon failure" message (garbage bytes)
```

### Fix applied

`_find_bash()` on Windows now checks **known Git for Windows install
paths first** (before `shutil.which`), prioritising the user-level path
(`%LOCALAPPDATA%\Programs\Git`) because user installs are more common
in corporate environments where admin rights are unavailable:

```python
# Check known Git for Windows install locations BEFORE shutil.which
# so that system32\bash.exe (WSL stub) is not returned on machines
# where WSL is installed but the user lacks the interactive logon right.
for candidate in (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Git", "bin", "bash.exe"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "bin", "bash.exe"),
):
    if candidate and os.path.isfile(candidate):
        return candidate

# shutil.which as last resort (may return WSL bash on some systems)
found = shutil.which("bash")
if found:
    return found
```

Additionally, `.env.example` now documents `HERMES_GIT_BASH_PATH` so
users with non-standard Git installs can point directly to their
`bash.exe` without editing source code.

### Manual fix (for existing installs)

Add to `~/.hermes/.env`:

```
HERMES_GIT_BASH_PATH=C:\Users\<your-username>\AppData\Local\Programs\Git\bin\bash.exe
```

Replace the path with the output of:

```batch
where bash
```

(use the Git for Windows entry, not `System32\bash.exe`)

---

## Test results after fixes

| Test | Result |
|------|--------|
| `hermes version` | v0.4.0 ✅ |
| `hermes doctor` | All core tools loaded, 45 sessions in DB ✅ |
| `import tkinter; tkinter.TkVersion` | `8.6` ✅ |
| `import hermes_cli` | OK ✅ |
| `AIAgent.chat("Qual é a raiz quadrada de 144?")` | `"A raiz quadrada de 144 é 12."` ✅ |
| LLM API (Kimi `moonshot-v1-8k`) | Token response received ✅ |
| Tool spinner / display | `(◔_◔) cogitating...` rendered correctly ✅ |
| `read_file` after git-bash fix | File read correctly ✅ |

---

## Environment details

```
OS:          Windows 11 Enterprise 10.0.26100
Python:      3.13.12 (embedded)
Git:         C:\Users\<user>\AppData\Local\Programs\Git\cmd\git.exe (user install)
Node.js:     present (agent-browser OK)
WSL:         installed stub present but user lacks interactive logon right
Docker:      not available
LLM:         Kimi / Moonshot (moonshot-v1-8k) via KIMI_API_KEY
```
