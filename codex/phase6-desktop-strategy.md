# Phase 6 - GUI/Desktop Strategy

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`

## Objective

Align the portable GUI story with current upstream Electron desktop instead of reviving the stale fork-era Tkinter GUI and its private agent semantics.

## Product Decision

The only supported primary GUI path for this update is upstream Electron desktop:

- `hermes desktop`
- Electron renderer under `apps/desktop`
- Backend through upstream `serve` / gateway APIs
- Approval requests through upstream gateway approval bridge
- State pinned by `HERMES_HOME=<portable-root>\.hermes`

The old Tkinter portable shell is not ported.

## Implemented

- Added `hermes portable desktop-command`.
  - Prints a portable Electron launch command.
  - Pins `--hermes-root` to the portable root.
  - Pins `--cwd` to the portable root.
  - Supports desktop flags:
    - `--source`
    - `--skip-build`
    - `--force-build`
    - `--build-only`
  - Does not build or launch Electron by itself.
- Added PowerShell launcher shortcut:
  - `scripts\portable\hermes-portable.ps1 -Desktop`
  - Expands to upstream `hermes desktop --hermes-root <root> --cwd <root>`.
- Added tests for rendered desktop commands.

## Smoke Tests

Environment note: desktop `node_modules` are not installed in this worktree, so Electron was not built or launched in this phase.

- `python -m pytest tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py -q --basetemp E:\tmp\pytest-portable-phase6`
  - Passed: `18 passed`.
- `python -m py_compile hermes_cli\portable.py hermes_cli\subcommands\portable.py tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py`
  - Passed.
- PowerShell parser check:
  - `powershell -NoProfile -Command '$null = [scriptblock]::Create((Get-Content -Raw scripts\portable\hermes-portable.ps1)); Write-Output ps1-ok'`
  - Passed.
- `python -m hermes_cli.main portable desktop-command --shell powershell --skip-build`
  - Passed and printed a portable `hermes-portable.ps1 desktop ...` command.
- `python -m hermes_cli.main portable desktop-command --shell cmd --source --build-only`
  - Passed and printed a portable CMD launcher command.
- `python -m hermes_cli.main portable desktop-command --shell bash --force-build`
  - Passed and printed a portable shell launcher command.
- Source audit:
  - No `tkinter`, `customtkinter`, or `portable_gui` appears in the new portable implementation.
  - No `HERMES_YOLO_MODE` appears in the new portable launchers or portable command implementation.
- `git diff --check`
  - Passed with only Git's existing line-ending warnings for `.gitignore` and `hermes_cli/main.py`.

## Independent Self-Audit

Direct code review after smoke tests found:

- The new desktop surface is a command renderer and launcher handoff only.
- It does not import or reimplement desktop internals.
- It does not bypass approval, session, prompt caching, or gateway behavior.
- It keeps upstream desktop in charge of onboarding, terminal, messaging, MCP, projects, sessions, and updates.
- It pins desktop root and cwd explicitly so the Electron backend resolves the same portable checkout and folder-local state.
- No stale Tkinter GUI code was introduced.

## Phase 6 Acceptance

Phase 6 is complete:

- There is one primary GUI path: upstream Electron desktop.
- Portable mode integrates with that GUI through command/env handoff.
- GUI behavior no longer forks core agent semantics.
- Desktop build/launch was not run because Node dependencies are absent; rendered command and launcher syntax were smoke-tested.
