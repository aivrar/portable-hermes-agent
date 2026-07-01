# Update Preservation Audit

Date: 2026-06-30

## Question

Can users or the agent update Hermes inside the portable repo without losing
folder-local extension payloads, skills, plugins, or other custom runtime
state?

## Findings

- Git-based `hermes update` stashes uncommitted tracked edits and untracked
  non-ignored files with `git stash push --include-untracked`, then restores the
  stash after a successful update unless the user explicitly configures
  `updates.non_interactive_local_changes: discard`.
- Ignored runtime folders are not swept into that autostash. This is fine for
  `.hermes/`, which is runtime state and should never become upstream source.
  It is not future-proof for a top-level `extensions/` directory, because a
  future upstream tracked file at the same path could collide with an ignored
  local file.
- The primary portable extension payload path is therefore
  `.hermes/extensions/`. Root-level `extensions/` is legacy-only and is covered
  by backup and migration, but new durable portable payloads should not live
  there.
- Upstream `hermes update --backup` already backs up `HERMES_HOME`. In portable
  mode that covers `.hermes/`, including config, `.env`, sessions, skills,
  plugins, and `.hermes/extensions/`, but it does not cover legacy root-level
  `extensions/`.
- The Windows ZIP fallback replaces top-level directories from the update ZIP
  unless they are in a preserve set. Portable runtime directory names must be
  preserve-only even if a future upstream archive adds same-named entries.

## Changes Made

- Moved the expected primary extension payload directory to
  `.hermes/extensions/`.
- Kept root-level `extensions/` as a legacy migration and backup source only.
  `hermes portable migrate --apply` copies it to
  `.hermes/extensions/legacy-root-extensions/`.
- Added `.hermes`, `extensions`, and `python_embedded` to the ZIP fallback
  preserve set in `hermes_cli/main.py`.
- Added `hermes portable backup`:
  - backs up `.hermes/` and legacy root-level `extensions/`
  - writes unique `portable-runtime-*.zip` archives under `.hermes/backups/`
  - excludes prior backup archives to avoid recursive backups
  - optionally includes `python_embedded/` with `--include-python`
- Extended the existing `hermes update --backup` hook. When portable mode is
  active (`HERMES_HOME == <portable-root>/.hermes`), it now creates the normal
  upstream pre-update backup and a focused portable runtime archive.
- Updated `docs/portable-mode.md` and `README.md` with the safer update flow:
  - `scripts\portable\hermes-portable.ps1 -Root . update --backup`
  - optional manual archive: `scripts\portable\hermes-portable.ps1 -Root . portable backup`

## Tests Added

- Portable backups include `.hermes/` and `.hermes/extensions/`.
- Portable backups include legacy root-level `extensions/` if present.
- Backup archives skip previous backups and do not overwrite quick repeated
  runs.
- `python_embedded/` is included only when requested.
- Portable migration copies legacy root-level `extensions/` under
  `.hermes/extensions/legacy-root-extensions/`.
- `hermes update --backup` creates a portable runtime archive when portable
  mode is active.
- Invalid `updates.backup_keep` config does not prevent the portable runtime
  backup from being created.
- ZIP fallback preserves `.hermes/`, root-level `extensions/`, and
  `python_embedded/`.
- Launcher tests verify extension directories are created under `.hermes/` and
  that portable sources do not register tools, set YOLO mode, or call updater
  helper tools.
- Native Windows portable status and terminal execution now prefer Git Bash
  over the WSL `bash.exe` launcher, preventing update/extension shell commands
  from accidentally crossing into WSL path semantics.
- Empty root-level `extensions/` directories no longer trigger legacy migration
  warnings; non-empty legacy payloads still warn, back up, and migrate.

## Verification Snapshot

- `python -m pytest tests\hermes_cli\test_portable.py tests\hermes_cli\test_backup.py::TestRunPreUpdateBackup tests\hermes_cli\test_update_zip_symlink_reject.py -q --basetemp E:\tmp\pytest-portable-selfaudit-prebackup-2`
  - Result: `39 passed in 6.36s`
- `python -m py_compile hermes_cli\portable.py hermes_cli\main.py tests\hermes_cli\test_portable.py tests\hermes_cli\test_backup.py tests\hermes_cli\test_update_zip_symlink_reject.py`
  - Result: passed
- 2026-07-01 focused reruns:
  - `tests\hermes_cli\test_portable.py`: passed
  - `tests\tools\test_find_shell.py`: passed
  - `tests\tools\test_windows_compat.py tests\tools\test_windows_native_support.py tests\tools\test_find_shell.py`: passed
  - `scripts\portable\hermes-portable.ps1 -Status`: Git Bash resolved to
    `C:\Program Files\Git\bin\bash.exe`

## Remaining Guidance

Source-code customizations placed directly under tracked upstream paths such as
`tools/` are update-stashed and restored by default, but they can still conflict
with upstream changes. Durable portable custom behavior should live under
`.hermes/plugins`, `.hermes/skills`, MCP config, or `.hermes/extensions/`.
