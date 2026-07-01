# Phase 3 - Safety And Permissions First

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`

## Objective

Ensure the portable update does not reintroduce the old fork's unsafe behavior, especially silent YOLO activation and model-visible execution/update tools.

## Implemented

Added focused portable safety regressions in `tests/hermes_cli/test_portable.py`:

- `cmd_portable` must not mutate `HERMES_YOLO_MODE`.
- `hermes portable` may expose only non-execution actions: `status`, `env`, and `init`.
- Portable source files must not call `registry.register`.
- Portable source files must not reference old model-callable execution/update surfaces:
  - `run_python`
  - `tool_maker`
  - `update_hermes`

No production approval logic was weakened or bypassed.

## Upstream Safety Baseline

Current upstream already covers the old fork's missing safety pieces:

- `tools/approval.py` freezes process-level `HERMES_YOLO_MODE` at import time so in-process code cannot flip it mid-session.
- `check_all_command_guards(...)` runs hardline catastrophic-command and sudo-stdin guards before YOLO or `approvals.mode=off`.
- Gateway approval uses `register_gateway_notify(...)`, blocks the agent thread in `_await_gateway_decision(...)`, and resolves through `/approve` or `/deny`.
- Desktop receives gateway `approval.request` events, stores them per session, marks the session as needing input, and surfaces approve/reject native actions.
- ACP routes approvals through a callback bridge instead of falling through to terminal input.

The current upstream desktop has an explicit YOLO UI, but it uses gateway config/session state. A source scan found no `HERMES_YOLO_MODE` writes under `apps/desktop`, `hermes_cli/subcommands/gui.py`, or the new portable files.

## Smoke Tests

Environment note: no local `venv` exists in the worktree or main checkout; tests used the available `Python 3.13.11`.

- `python -m pytest tests\hermes_cli\test_portable.py -q --basetemp E:\tmp\pytest-portable-phase3`
  - Passed: `10 passed`.
- `python -m pytest tests\cli\test_cli_yolo_toggle.py tests\tools\test_command_guards.py -q --basetemp E:\tmp\pytest-safety-phase3`
  - Passed: `44 passed`.
- Final combined safety smoke:
  - `python -m pytest tests\hermes_cli\test_portable.py tests\cli\test_cli_yolo_toggle.py tests\tools\test_command_guards.py -q --basetemp E:\tmp\pytest-safety-phase3-final`
  - Passed: `54 passed in 3.91s`.
- `python -m py_compile tests\hermes_cli\test_portable.py`
  - Passed.
- `rg -n "HERMES_YOLO_MODE" apps\desktop hermes_cli\subcommands\gui.py hermes_cli\portable.py hermes_cli\subcommands\portable.py`
  - No matches.
- `git diff --check`
  - Passed with only Git's existing line-ending warning for `hermes_cli/main.py`.

Desktop Vitest was not run because neither root `node_modules` nor `apps/desktop/node_modules` exists in this worktree. I did not install Node dependencies during this phase because the safety change is Python test coverage plus source audit.

## Independent Self-Audit

Direct code review after smoke tests found:

- The new portable implementation does not import `subprocess`, does not call `os.system`, and does not create model-callable tools.
- The parser exposes only inspection, environment-printing, and directory-initialization commands.
- `init --apply` creates directories only inside the selected portable root and does not execute external installers.
- The explicit upstream YOLO controls remain visible user actions (`--yolo`, `/yolo`, desktop status control) rather than hidden portable defaults.
- The old fork's GUI behavior of setting `HERMES_YOLO_MODE=1` on launch is not present in this update.

## Phase 3 Acceptance

Phase 3 is complete:

- No portable path silently enables YOLO.
- No portable path adds arbitrary code execution, update, tool-maker, or registry surfaces.
- Existing upstream approval/yolo regression tests pass.
- GUI/gateway approval bridge was mapped in code and found connected.
