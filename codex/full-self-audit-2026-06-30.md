# Full Self-Audit - Portable Major Update

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`
Branch: `major-update/upstream-2026-06-30`
Upstream base: `885e80df74f017d5e897d39928f49b0212e9bedb`

## Audit Scope

This audit rechecked the portable-mode update after the concern that update
preservation for custom extension tooling was not fully hooked up. The review
covered command wiring, launchers, update paths, backup/migration behavior,
tool exposure boundaries, docs, and focused regression tests.

## Findings From This Audit

1. Root-level `extensions/` was not safe as the primary durable extension
   payload path.
   - Git ignores it, so normal ignored files stay in place, but a future
     upstream tracked file at the same path could collide with a legacy local
     file.
   - Fix: primary extension payloads now live under `.hermes/extensions/`.
   - Legacy root-level `extensions/` is backup and migration input only.

2. `hermes update --backup` did not create a focused portable runtime archive.
   - Upstream's normal pre-update backup covers portable `.hermes/`, but not
     legacy root-level `extensions/`.
   - Fix: when `HERMES_HOME == <portable-root>/.hermes`, the existing
     pre-update backup hook also writes `.hermes/backups/portable-runtime-*.zip`.

3. Portable backup archive names could collide on quick repeated runs.
   - Fix: backup names now include microseconds and still check for an unused
     path before writing.

4. Users with legacy root-level `extensions/` needed a visible migration hint.
   - Fix: `hermes portable status` warns when root-level `extensions/` exists
     and points to `hermes portable migrate --apply`.

5. Prior known issue from the earlier self-audit remains fixed:
   - PowerShell/CMD desktop command rendering now uses `-Root <root> -Desktop`
     so launcher parameter binding does not consume `desktop` as the root path.

6. Native Windows portable status could report the WSL `bash.exe` launcher
   instead of Git Bash.
   - Fix: portable diagnostics and the local terminal backend now prefer
     explicit/bundled/known Git for Windows locations and skip
     `C:\Windows\System32\bash.exe` as a fallback.

7. Desktop update relaunch tests exposed host-vs-target path handling.
   - Fix: Linux/macOS relaunch release paths now use POSIX path semantics even
     when tests run on Windows; Windows targets use Win32 path semantics.
   - Bash syntax linting now uses stdin instead of host-specific temp paths.

8. Empty root-level `extensions/` directories produced a noisy legacy warning.
   - Fix: `portable status` and backup summaries treat empty directories as
     empty, while non-empty legacy extension payloads still warn and migrate.

## Final Behavior Map

- Primary portable state: `<portable-root>/.hermes/`
- Primary portable extension payloads: `<portable-root>/.hermes/extensions/`
- Legacy extension payloads: `<portable-root>/extensions/`
  - included in `portable backup`
  - copied by `portable migrate --apply` to
    `.hermes/extensions/legacy-root-extensions/`
  - warned about by `portable status`
- ZIP fallback update preservation:
  - preserves `.hermes`, `extensions`, and `python_embedded`
- Git update preservation:
  - `.hermes/` and `python_embedded/` are ignored runtime state and remain in
    place
  - source edits and non-ignored untracked files are handled by upstream stash
    behavior
  - `update --backup` in portable mode also creates a portable runtime archive

## Verification

Passed:

- `python -m pytest tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py tests\tools\test_portable_registry_boundary.py tests\tools\test_registry.py tests\tools\test_tool_search.py tests\cli\test_cli_yolo_toggle.py tests\tools\test_command_guards.py tests\test_packaging_metadata.py tests\hermes_cli\test_update_zip_symlink_reject.py tests\hermes_cli\test_update_zip_atomic_replace.py tests\hermes_cli\test_backup.py::TestRunPreUpdateBackup -q --basetemp E:\tmp\pytest-portable-selfaudit-focused-final-2`
  - Result: `176 passed in 19.73s`
- `python -m py_compile hermes_cli\portable.py hermes_cli\subcommands\portable.py hermes_cli\main.py tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py tests\hermes_cli\test_backup.py tests\tools\test_portable_registry_boundary.py tests\hermes_cli\test_update_zip_symlink_reject.py`
  - Result: passed
- `git diff --check`
  - Result: passed; Git reported line-ending warnings only.
- `rg -n "^(<<<<<<<|=======$|>>>>>>>)" hermes_cli docs tests scripts README.md codex`
  - Result: no conflict markers.
- `rg -n "HERMES_PORTABLE|registry\.register|run_python|tool_maker|update_hermes|HERMES_YOLO_MODE" hermes_cli\portable.py hermes_cli\subcommands\portable.py scripts\portable`
  - Result: no matches.

Passed CLI/launcher smokes:

- `python -m hermes_cli.main portable init --root E:\tmp\portable-selfaudit-init2 --apply --json`
- `python -m hermes_cli.main portable backup --root E:\tmp\portable-selfaudit-backup2 --json`
- `python -m hermes_cli.main portable migrate --root E:\tmp\portable-selfaudit-migrate2 --apply --json`
- `python -m hermes_cli.main portable status --root E:\tmp\portable-selfaudit-migrate2 --json`
- `powershell -ExecutionPolicy Bypass -NoProfile -File scripts\portable\hermes-portable.ps1 -Root E:\tmp\portable-hermes-major-update portable backup --help`
- `powershell -ExecutionPolicy Bypass -NoProfile -File scripts\portable\hermes-portable.ps1 -Root E:\tmp\portable-hermes-major-update update --help`
- `cmd /c scripts\portable\hermes-portable.cmd -Root E:\tmp\portable-hermes-major-update portable backup --help`
- `python -m hermes_cli.main portable desktop-command --root E:\tmp\portable-hermes-major-update --shell powershell --skip-build`
- `python -m hermes_cli.main portable extensions --json --timeout 0.05`

Additional 2026-07-01 validation passed:

- Remaining `tests/tools` t-z files were run individually, including
  WhatsApp media, Windows compatibility/native support, write approval/deny,
  X search/XAI storage, yolo mode, and zombie cleanup.
- `tests/tools/test_zombie_process_cleanup.py`
  - Result: `12 passed in 11.16s`
- `tests/hermes_cli/test_portable.py`
  - Result: passed after the Git Bash and empty legacy-directory fixes
- `tests/tools/test_find_shell.py`
  - Result: passed with coverage for preferring Git Bash over WSL bash
- `tests/tools/test_windows_compat.py tests/tools/test_windows_native_support.py tests/tools/test_find_shell.py`
  - Result: passed together
- `node --test apps/desktop/electron/update-relaunch.test.cjs`
  - Result: passed
- `npm --workspace apps/desktop run typecheck`
  - Result: passed after local desktop workspace dependency install
- `npm --workspace apps/desktop run test:desktop:platforms`
  - Result: passed
- `npm --workspace apps/desktop run build`
  - Result: passed
- `scripts\portable\hermes-portable.ps1 -Status`
  - Result: portable home active, supported Python, Git Bash resolved to
    `C:\Program Files\Git\bin\bash.exe`, and no empty-extension warning

## Residual Risks

- The full `tests/` suite was not a clean signal in this checkout because the
  broader dev/test environment lacks optional test dependencies already noted
  in the phase-10 audit (`acp`, `concurrent_log_handler`, `pytest_asyncio`,
  `tzdata`, and a Windows `which` assumption).
- Direct source-code customizations under upstream-owned paths can still
  conflict with upstream changes when the stash is restored. Durable portable
  customization should live under `.hermes/plugins`, `.hermes/skills`, MCP
  config, or `.hermes/extensions/`.
- `python_embedded/` is preserved in place by update paths and can be included
  in manual `portable backup --include-python`, but the automatic portable
  runtime backup does not include it by default because embedded Python folders
  can be large and are usually reinstallable.
- Electron desktop was typechecked, platform-tested, and build-tested. A full
  interactive GUI launch was not opened from the chat runner.

## Audit Result

The update-preservation gap is now closed for the intended portable model:
custom runtime state and extension payloads belong under `.hermes/`, legacy
root extensions are detected and recoverable, and `update --backup` creates a
portable-specific runtime archive when launched in portable mode.
