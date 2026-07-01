# Phase 9 - Documentation And Metadata

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`

## Objective

Update user-facing documentation so the portable update reflects current upstream Hermes and accurately credits the portable overlay.

## Implemented

- Added `docs/portable-mode.md`.
  - Folder-local layout.
  - Quick start.
  - Launchers.
  - Install/repair command generation.
  - Electron desktop handoff.
  - Local extension readiness checks.
  - Migration.
  - Safety guarantees.
  - Credits portable update to `aivrar` and notes the old `rookiemann` name.
- Updated `README.md`.
  - Added a concise "Portable Folder Mode" section.
  - Links to `docs/portable-mode.md`.
  - States portable mode does not fork the agent loop, register extra model tools, or set YOLO mode.
- Updated `apps/desktop/README.md`.
  - Points portable users to `hermes portable desktop-command`.
  - Keeps Electron desktop as the supported GUI path.
- Updated `MANIFEST.in`.
  - Adds `recursive-include scripts/portable *` so source distributions include the portable launchers.
- Added tests in `tests/hermes_cli/test_portable_launchers.py`.
  - Portable docs must credit `aivrar`.
  - Portable docs must mention installed `hermes portable status`.
  - Portable docs must state the `HERMES_YOLO_MODE` safety rule.
  - Sdist manifest must include portable launchers.

## Smoke Tests

Environment note: no local `venv` exists in the worktree or main checkout; tests used the available `Python 3.13.11`.

- `python -m py_compile tests\hermes_cli\test_portable_launchers.py`
  - Passed.
- `python -m pytest tests\hermes_cli\test_portable_launchers.py tests\test_packaging_metadata.py -q --basetemp E:\tmp\pytest-portable-docs-phase9-final`
  - Passed: `13 passed in 1.29s`.
- Source scan:
  - Confirmed `aivrar`, `rookiemann`, `hermes portable status`, `HERMES_YOLO_MODE`, and `recursive-include scripts/portable *` appear where expected.
- `git diff --check`
  - Passed with only Git's existing line-ending warnings for edited text files and `hermes_cli/main.py`.

## Independent Self-Audit

Direct doc review after smoke tests found:

- README keeps upstream Nous Research branding intact.
- Portable overlay credit uses the user's current name, `aivrar`, while explaining the old `rookiemann` name for continuity.
- Docs do not claim the stale fork still owns the agent core.
- Docs direct GUI users to upstream Electron desktop, not Tkinter.
- Docs explain extension manifests as disabled-by-default readiness checks, not auto-installers.
- Docs make migration dry-run first.

## Phase 9 Acceptance

Phase 9 is complete:

- User-facing portable docs exist.
- README and desktop docs point to the current portable flow.
- Portable launcher files are included in source distributions.
- Credit/name metadata is accurate.
