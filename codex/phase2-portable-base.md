# Phase 2 - Current-Upstream Portable Base

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`
Branch: `major-update/upstream-2026-06-30`
Base: upstream `main` at `f99ba56df4bb6a1caf490e99c542507e3c3926cb`

## Objective

Establish a current-upstream implementation base and reapply the portable value as a small, isolated runtime surface instead of replaying the old fork over stale core files.

## Implemented

- Added `hermes_cli/portable.py`.
  - Computes a folder-local portable state path: `<portable-root>/.hermes`.
  - Reports required directories and runtime executables.
  - Emits shell-specific `HERMES_HOME` activation commands.
  - Creates the portable directory layout only when `init --apply` is used.
  - Does not register model tools, alter the agent loop, mutate tool discovery, or add a new persistent config key.
- Added `hermes_cli/subcommands/portable.py`.
  - Adds `hermes portable status`.
  - Adds `hermes portable env`.
  - Adds `hermes portable init`.
  - Defaults bare `hermes portable` to `status`.
- Wired the parser into `hermes_cli/main.py`.
- Added `tests/hermes_cli/test_portable.py`.

## Connection Map

`hermes_cli/main.py`
-> `build_portable_parser(...)`
-> `cmd_portable(args)`
-> `collect_status(...)`, `render_env(...)`, `initialize_portable_root(...)`
-> existing Hermes `HERMES_HOME` behavior.

The portable layer stays outside:

- `run_agent.py`
- `model_tools.py`
- `toolsets.py`
- `tools/registry.py`
- provider selection
- prompt construction
- MCP/plugin discovery

## Smoke Tests

Environment note: no `venv\Scripts\Activate.ps1` exists in either the integration worktree or the main checkout, so these checks used the available interpreter:

- `python --version`
  - Passed: `Python 3.13.11`
- `python -m py_compile hermes_cli\portable.py hermes_cli\subcommands\portable.py tests\hermes_cli\test_portable.py`
  - Passed.
- `python -m pytest tests\hermes_cli\test_portable.py -q --basetemp E:\tmp\pytest-portable-phase2`
  - Passed: `7 passed in 1.24s`.
- `python -m hermes_cli.main portable env --shell cmd`
  - Passed and printed only `HERMES_HOME`.
- `python -m hermes_cli.main portable init --root E:\tmp\portable-phase2-smoke --json`
  - Passed dry-run without creating directories.
- `python -m hermes_cli.main portable init --root E:\tmp\portable-phase2-smoke --apply --json`
  - Passed and created missing portable directories.
- Sequential after `init --apply`:
  - `$env:HERMES_HOME='E:\tmp\portable-phase2-smoke\.hermes'`
  - `python -m hermes_cli.main portable status --root E:\tmp\portable-phase2-smoke --json`
  - Passed with `"ready": true`.
- `git diff --check`
  - Passed with only Git's existing line-ending warning for `hermes_cli/main.py`.
- `rg -n "HERMES_PORTABLE|registry\.register|run_python|tool_maker|update_hermes" hermes_cli\portable.py hermes_cli\subcommands\portable.py hermes_cli\main.py tests\hermes_cli\test_portable.py`
  - Only expected test assertion for `HERMES_PORTABLE` was found.

## Independent Self-Audit

Findings from direct code review after smoke tests:

- The new command is a CLI/runtime helper only. It introduces no model-visible tools and no registry side effects.
- The only environment variable emitted by the activation command is the existing `HERMES_HOME`; no new `HERMES_PORTABLE` switch was introduced.
- The initial implementation reported already-existing directories as `Created` during `init --apply`. This was corrected so actions distinguish `Created`, `Exists`, and `Would create`.
- A regression test now verifies that existing directories are not marked as newly created.
- A parallel smoke run initially made `status` observe a root before `init --apply` finished. The dependent check was rerun sequentially and passed; the race was in the test harness, not in product code.
- `status` intentionally returns exit code `1` when the portable root is not ready. `env` and `init` return `0` when they complete their own operation.
- The implementation is profile-compatible because it uses the established `HERMES_HOME` mechanism rather than inventing separate profile state.

## Phase 2 Acceptance

Phase 2 is complete:

- Current upstream is the implementation base.
- Old stale fork edits were not replayed into core agent/tool files.
- Portable behavior is restored as a minimal, test-covered runtime surface.
- Smoke tests passed.
- Independent code audit passed after one bug fix.
