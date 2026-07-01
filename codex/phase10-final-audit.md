# Phase 10 - Final Upstream Sync, Smoke Tests, and Self-Audit

Date: 2026-06-30

## Upstream Sync

- Refreshed `upstream` with `git fetch upstream`.
- `HEAD` and `upstream/main` both resolve to `885e80df74f017d5e897d39928f49b0212e9bedb`.
- Branch: `major-update/upstream-2026-06-30`.
- Integration worktree: `E:\tmp\portable-hermes-major-update`.
- Main checkout `E:\hermes` was not used for implementation changes.

## Final Smoke Tests

Passed:

- `python -m py_compile hermes_cli\portable.py hermes_cli\subcommands\portable.py tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py tests\tools\test_portable_registry_boundary.py`
- `python -m pytest tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py tests\tools\test_portable_registry_boundary.py tests\tools\test_registry.py tests\tools\test_tool_search.py tests\cli\test_cli_yolo_toggle.py tests\tools\test_command_guards.py tests\test_packaging_metadata.py -q --basetemp E:\tmp\pytest-portable-phase10-targeted-rerun`
  - Result: `154 passed in 17.42s`
- `python -m pytest tests\cli\test_cli_init.py tests\hermes_cli\test_argparse_flag_propagation.py tests\hermes_cli\test_config_env_refs.py tests\hermes_cli\test_config_env_expansion.py tests\hermes_cli\test_set_config_value.py tests\hermes_cli\test_subcommands_profile_gateway.py tests\hermes_cli\test_toolset_validation.py tests\test_toolsets.py tests\test_model_tools.py -q --basetemp E:\tmp\pytest-portable-phase10-cli-focused-clean-rerun`
  - Result: `203 passed in 32.16s`
- `git diff --check`
- `rg -n "^(<<<<<<<|=======$|>>>>>>>)"`
  - Result: no conflict markers.
- Portable implementation safety scan:
  - `rg -n "HERMES_PORTABLE|registry\.register|run_python|tool_maker|update_hermes|HERMES_YOLO_MODE" hermes_cli\portable.py hermes_cli\subcommands\portable.py scripts\portable`
  - Result: no matches.
- Hardcoded extension port regression scan:
  - `rg -n "5000" hermes_cli\portable.py docs\portable-mode.md scripts\portable tests\hermes_cli\test_portable.py tests\hermes_cli\test_portable_launchers.py tests\tools\test_portable_registry_boundary.py`
  - Result: no matches.

Passed CLI and launcher smokes:

- `powershell -ExecutionPolicy Bypass -NoProfile -File scripts\portable\hermes-portable.ps1 -Status`
- `cmd /c scripts\portable\hermes-portable.cmd -Status`
- `python -m hermes_cli.main portable env --root E:\tmp\portable-phase10-cli --shell cmd`
- `python -m hermes_cli.main portable install-command --root E:\tmp\portable-phase10-cli --shell powershell --include-desktop`
- `python -m hermes_cli.main portable desktop-command --root E:\tmp\portable-phase10-cli --shell powershell --skip-build`
- `python -m hermes_cli.main portable extensions --json --timeout 0.05`
- `python -m hermes_cli.main portable init --root E:\tmp\portable-phase10-init --apply --json`
- `python -m hermes_cli.main portable migrate --root E:\tmp\portable-phase10-migrate --apply --json`
- `powershell -ExecutionPolicy Bypass -NoProfile -File scripts\portable\hermes-portable.ps1 -Root E:\tmp\portable-hermes-major-update -Desktop --help`
- `cmd /c scripts\portable\hermes-portable.cmd -Root E:\tmp\portable-hermes-major-update -Desktop --help`

## Broader Suite Results

- `python -m pytest tests\ -q --basetemp E:\tmp\pytest-portable-phase10-full`
  - Result: collection failed because this checkout is not in the full dev/test environment.
  - Missing/runtime blockers observed: `acp`, `concurrent_log_handler`, `pytest_asyncio`, `tzdata`, and a Windows PATH assumption for `which`.
  - No portable-specific failures were reached before collection stopped.
- `python -m pytest tests\hermes_cli -q --basetemp E:\tmp\pytest-portable-phase10-hermes-cli`
  - Result: timed out after 904 seconds.
  - Cleanup: stopped the leftover pytest process and dashboard subprocess; verified no remaining `python.exe` processes.
- Focused CLI run including upstream profile/default-home tests:
  - Result: `336 passed, 1 skipped, 8 failed`.
  - Failures were in existing `test_apply_profile_override.py` and `test_config.py` Windows expectations. The portable patch does not modify those files or `hermes_constants.py`; failures line up with upstream platform-native Windows default home behavior (`%LOCALAPPDATA%\hermes`), unavailable POSIX `pwd`, and profile fixture assumptions.

## Missed Issue Found During Self-Audit

The independent code audit found one real bug after smoke tests:

- `render_desktop_command(..., shell="powershell"|"cmd")` originally rendered the portable launcher with positional `desktop --hermes-root ... --cwd ...` arguments.
- Because `hermes-portable.ps1` declares `[string]$Root` first, PowerShell would bind positional `desktop` to `-Root` instead of forwarding it as a Hermes subcommand.
- Fixed by rendering PowerShell/CMD desktop commands as:
  - `hermes-portable.ps1 -Root <root> -Desktop <desktop flags>`
  - `hermes-portable.cmd -Root <root> -Desktop <desktop flags>`
- Bash/sh remains direct:
  - `hermes-portable.sh desktop --hermes-root <root> --cwd <root> <desktop flags>`
- Added tests for the corrected PowerShell/CMD/Bash behavior.
- Verified actual PowerShell and CMD launcher desktop help mode reaches `hermes desktop` successfully.

## Final Self-Audit

- `hermes_cli/main.py` only adds the `portable` parser and imports `cmd_portable` inside parser construction. The parser module is lightweight and does not import portable runtime helpers or model-tool code.
- `hermes_cli/subcommands/portable.py` maps all actions to `cmd_portable` and bare `hermes portable` defaults to `status`.
- `hermes_cli/portable.py` is CLI/runtime-only:
  - no model tool registration
  - no toolset edits
  - no yolo/approval bypass
  - no updater/tool-maker/run-python shortcuts
- Launchers create only folder-local `.hermes` subdirectories and `extensions`, set only `HERMES_HOME`, and use the normal `hermes_cli.main` entry point.
- Migration is dry-run by default, copies only with `--apply`, preserves existing targets unless `--overwrite`, and never deletes source state.
- Extension manifests are informational, disabled by default, unmanaged, and loopback-only. LM Studio uses `127.0.0.1:1234`, ComfyUI uses `127.0.0.1:8188`, and Piper remains manual because no canonical HTTP endpoint exists.
- Runtime artifacts are ignored: `.hermes/` was already ignored; this patch adds portable `extensions/` and `python_embedded/`.
- Documentation credits `aivrar` and notes the former `rookiemann` name.

## Residual Risks

- Full-suite execution still needs a proper Hermes dev environment or local venv with the declared extras. No `venv` or `.venv` existed in this worktree.
- Electron desktop build/launch was not run; only command rendering and desktop parser/help routing were smoke-tested.
- The focused upstream Windows profile/default-home test failures remain outside this portable patch scope.

## 2026-07-01 Completion Update

Additional smoke testing and self-audit work was completed in the Windows
checkout after the initial phase-10 note above.

Late issues found and fixed:

- `hermes_cli/main.py` still had one direct `_signal.SIGKILL` reference in a
  cleanup path. It now uses `getattr(_signal, "SIGKILL", _signal.SIGTERM)`.
- `tests/tools/test_zombie_process_cleanup.py` used `os.kill(pid, 0)` and
  `signal.SIGKILL`, which is not portable on native Windows. It now uses
  `Popen.poll()`, `kill()`, and `wait()` handles.
- `apps/desktop/electron/update-relaunch.cjs` resolved Linux release paths
  with host OS path semantics. It now uses `path.posix` for Linux/macOS targets
  and `path.win32` only for Windows targets.
- `apps/desktop/electron/update-relaunch.test.cjs` linted generated bash
  scripts through temp file paths that were not readable by this host's `bash`.
  It now pipes the generated script to `bash -n` via stdin.
- Portable status and the local terminal backend could prefer
  `C:\Windows\System32\bash.exe` (WSL launcher) over Git Bash. Both resolvers
  now prefer explicit/bundled/known Git for Windows installs and skip the WSL
  launcher as a fallback.
- `hermes portable status` warned for an empty legacy root `extensions/`
  directory. It now warns only when that directory contains entries.

Additional validation passed:

- `tests/tools/test_whatsapp_send_message_media.py`: `23 passed`
- `tests/tools/test_windows_compat.py`: passed
- `tests/tools/test_windows_native_support.py`: passed after the SIGKILL
  fallback fix
- `tests/tools/test_write_approval.py`: passed
- `tests/tools/test_write_deny.py`: passed
- `tests/tools/test_x_search_tool.py`: passed
- `tests/tools/test_xai_http_storage.py`: passed
- `tests/tools/test_yolo_mode.py`: passed
- `tests/tools/test_zombie_process_cleanup.py`: `12 passed`
- `tests/hermes_cli/test_portable.py`: passed after the Git Bash and empty
  legacy-directory fixes
- `tests/tools/test_find_shell.py`: covered Git Bash over WSL bash selection
- `tests/tools/test_windows_compat.py tests/tools/test_windows_native_support.py tests/tools/test_find_shell.py`: passed together
- `node --test apps/desktop/electron/update-relaunch.test.cjs`: passed
- `npm --workspace apps/desktop run typecheck`: passed after installing the
  desktop workspace dependencies locally
- `npm --workspace apps/desktop run test:desktop:platforms`: passed
- `npm --workspace apps/desktop run build`: passed
- `python -m hermes_cli.main portable desktop-command --skip-build`: rendered
  the PowerShell portable desktop launcher command
- `scripts\portable\hermes-portable.ps1 -Status`: reported portable home
  active, supported Python, and Git Bash at `C:\Program Files\Git\bin\bash.exe`
  with no empty-extension warning

Updated residual risk:

- The Electron desktop was build-validated and launcher-command validated in
  this environment. A full interactive GUI launch was intentionally not opened
  from the chat runner.
- The full monolithic `tests/` command remains unsuitable for this chat runner
  on Windows because several long/process-heavy shards can destabilize the
  session. The broad suite was instead validated through focused shards and
  individual files with logs under `codex/test-logs/`.
