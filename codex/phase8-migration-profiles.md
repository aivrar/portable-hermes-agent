# Phase 8 - Config, Profiles, And Migration

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`

## Objective

Give existing portable users a conservative migration path into folder-local `.hermes` without breaking upstream profile behavior or silently reading/writing the wrong home directory.

## Implemented

- Added `hermes portable migrate`.
  - Dry-run by default.
  - `--json` for machine-readable reports.
  - `--apply` copies detected state.
  - `--overwrite` is required to replace existing targets.
  - Sources are never deleted.
- Root-level legacy candidates:
  - `.env` -> `.hermes/.env`
  - `config.yaml` -> `.hermes/config.yaml`
  - `permissions.json` -> `.hermes/permissions.json`
  - `sessions/` -> `.hermes/sessions/`
  - `memories/` -> `.hermes/memories/`
  - `memory/` -> `.hermes/memories/legacy-memory/`
- Explicit old-home migration:
  - `--legacy-home <path>`
  - Supports old locations such as `%USERPROFILE%\.hermes` without probing the real user home implicitly.
  - Copies `.env`, `config.yaml`, `permissions.json`, `sessions/`, and `skills/` from that explicit old home.
- Added tests for dry-run, copy-without-delete, target preservation, and explicit legacy-home copying.

## Smoke Tests

Environment note: no local `venv` exists in the worktree or main checkout; tests used the available `Python 3.13.11`.

- `python -m py_compile hermes_cli\portable.py hermes_cli\subcommands\portable.py tests\hermes_cli\test_portable.py`
  - Passed.
- `python -m pytest tests\hermes_cli\test_portable.py -q --basetemp E:\tmp\pytest-portable-phase8-final`
  - Passed: `21 passed in 1.85s`.
- Root-level dry-run smoke:
  - Created `E:\tmp\portable-phase8-migration\.env`.
  - `python -m hermes_cli.main portable migrate --root E:\tmp\portable-phase8-migration --json`
  - Passed and reported `.env` as `would-copy`.
- Apply smoke:
  - Created `E:\tmp\portable-phase8-migration-apply\config.yaml`.
  - `python -m hermes_cli.main portable migrate --root E:\tmp\portable-phase8-migration-apply --apply --json`
  - Passed and copied config to `.hermes\config.yaml` while preserving the source.
- Explicit legacy-home dry-run smoke:
  - Created `E:\tmp\portable-phase8-old-home\permissions.json`.
  - `python -m hermes_cli.main portable migrate --root E:\tmp\portable-phase8-legacy-root --legacy-home E:\tmp\portable-phase8-old-home --json`
  - Passed and reported `permissions.json` as `would-copy`.
- Source scan:
  - No hardcoded `Path.home() / ".hermes"` path in portable code.
  - Portable code continues to use folder-local `.hermes` via `portable_home_for_root(...)`.
- `git diff --check`
  - Passed with only Git's existing line-ending warnings for `.gitignore` and `hermes_cli/main.py`.

## Independent Self-Audit

Direct code review after smoke tests found:

- Migration is opt-in and non-destructive.
- Dry-run is the default, satisfying the requirement to report before moving/copying state.
- `--legacy-home` is explicit so the command does not inspect a real user home by surprise.
- Existing targets are preserved unless `--overwrite` is explicit.
- The migration code does not alter upstream profile roots or profile-list behavior.
- No config version bump is needed because no new persistent config key was added.
- The command works with portable `HERMES_HOME` rather than a separate portable env switch.

## Phase 8 Acceptance

Phase 8 is complete:

- Existing root-level portable state can be discovered and copied.
- Old user-home state can be migrated from an explicit path.
- Keys, sessions, skills, memory, and permission policy have a migration path.
- Profiles and portable mode remain isolated through `HERMES_HOME=<root>\.hermes`.
