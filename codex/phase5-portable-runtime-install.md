# Phase 5 - Portable Runtime And Installer

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`

## Objective

Provide a deterministic folder-local portable runtime path without forking upstream's installer logic or mixing state locations.

## Product Decision

Primary portable mode is Option B from the plan:

`HERMES_HOME=<portable-root>\.hermes`

The upstream native desktop/CLI installer remains the source of truth for dependency installation. The portable layer adds:

- Launchers that pin state to the folder-local `.hermes`.
- A non-mutating command that prints the upstream installer invocation with portable paths.
- Readiness checks that block clearly when required dependencies are missing.

## Implemented

- Added `scripts/portable/hermes-portable.ps1`.
  - Resolves the portable root from the script location or explicit `-Root`.
  - Creates `.hermes`, `.hermes/logs`, `.hermes/plugins`, `.hermes/skills`, and `extensions`.
  - Sets only `HERMES_HOME`.
  - Accepts `-Status` for a readiness preflight.
  - Finds a supported Python in `venv`, `.venv`, `python_embedded`, `py -3.13/-3.12/-3.11`, `python`, or `python3`.
  - Enforces Python `>=3.11,<3.14`.
- Added `scripts/portable/hermes-portable.cmd`.
  - CMD wrapper around the PowerShell launcher.
- Added `scripts/portable/hermes-portable.sh`.
  - POSIX launcher for macOS/Linux-style checkouts.
- Added `hermes portable install-command`.
  - Prints the upstream `install.ps1` or `install.sh` command with:
    - `-HermesHome <root>\.hermes`
    - `-InstallDir <root>`
    - `-NonInteractive`
    - `-SkipSetup` by default
  - Supports `--include-desktop`.
  - Supports `--run-setup` for explicit interactive setup.
  - Does not run the installer.
- Updated `.gitignore` to exclude portable runtime artifacts:
  - `.hermes/` already existed.
  - Added `extensions/`.
  - Added `python_embedded/`.
- Added `tests/hermes_cli/test_portable_launchers.py`.

## Smoke Tests

Environment note: no local `venv` exists in the worktree or main checkout; tests used the available `Python 3.13.11`.

- `python -m py_compile hermes_cli\portable.py hermes_cli\subcommands\portable.py tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py`
  - Passed.
- `python -m pytest tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py -q --basetemp E:\tmp\pytest-portable-phase5-final`
  - Passed: `16 passed in 1.70s`.
- `python -m hermes_cli.main portable install-command --shell powershell --include-desktop`
  - Passed and printed a command targeting `E:\tmp\portable-hermes-major-update\.hermes` and `E:\tmp\portable-hermes-major-update`.
- `python -m hermes_cli.main portable install-command --shell bash`
  - Passed and printed the equivalent `install.sh` command.
- `python -m hermes_cli.main portable install-command --shell pwsh`
  - Passed and printed a `pwsh` command.
- `powershell -ExecutionPolicy Bypass -NoProfile -File scripts\portable\hermes-portable.ps1 -Status`
  - Passed with `Portable home active: yes` and all required executables found.
- `cmd /c scripts\portable\hermes-portable.cmd -Status`
  - Passed with the same readiness status.
- `git check-ignore -v .hermes/ extensions/ python_embedded/`
  - Passed; all portable runtime paths are ignored.
- `git diff --check`
  - Passed with only Git's existing line-ending warnings for `.gitignore` and `hermes_cli/main.py`.

## Independent Self-Audit

Direct code review after smoke tests found:

- The launchers create only folder-local runtime directories.
- The launchers set only the existing `HERMES_HOME`; they do not set `HERMES_YOLO_MODE` or add a portable-specific env switch.
- `install-command` prints a command only. It does not install packages, run git, mutate the repo, or start external services.
- The generated installer command delegates to upstream installer scripts, preserving the upstream uv/Python/Node/Git/ripgrep/ffmpeg work instead of duplicating it.
- `.cmd` delegates to the PowerShell launcher and returns its exit code.
- The POSIX launcher mirrors the same state layout and Python version gate.
- The PowerShell launcher was smoke-tested through both PowerShell and CMD on Windows.

## Phase 5 Acceptance

Phase 5 is complete:

- State location is deterministic and folder-local.
- Fresh setup has a clear, explicit upstream installer command for the portable root.
- Launchers can start Hermes with portable state after dependencies are present.
- Required dependency gaps surface through `portable status`.
- Runtime artifacts are ignored and cannot accidentally become source changes.
