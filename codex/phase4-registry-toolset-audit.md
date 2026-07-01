# Phase 4 - Tool Architecture And Registry

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`

## Objective

Validate that the portable update fits current upstream's registry, toolset, and plugin architecture instead of reviving stale fork-era manual tool plumbing.

## Implemented

Added `tests/tools/test_portable_registry_boundary.py`:

- Imports `model_tools` so builtin tool discovery runs.
- Asserts no registered tool is named `portable` or starts with `portable_`.
- Asserts no static toolset resolves to `portable` or `portable_*`.
- Asserts the portable source files do not use `registry.register` or `skip_checks`.

## Upstream Registry Baseline

Direct code review confirmed current upstream already includes the architecture this phase wanted:

- Builtin tool auto-discovery via `tools.registry.discover_builtin_tools()`.
- Thread-safe registry mutation and snapshot reads with `RLock`.
- Registry generation counter used by `model_tools.get_tool_definitions(...)` cache keys.
- Dynamic schema overrides at registry definition time.
- Plugin override policy enforced by `PluginContext.register_tool(...)` and `registry.register(..., override=True)`.
- `check_fn` TTL caching plus last-good grace for transient optional-service failures.
- Tool Search bridge scoping so restricted sessions cannot call out-of-scope deferred tools.

## Smoke Tests

Environment note: no local `venv` exists in the worktree or main checkout; tests used the available `Python 3.13.11`.

- `python -m py_compile tests\tools\test_portable_registry_boundary.py`
  - Passed.
- `python -m pytest tests\tools\test_portable_registry_boundary.py tests\tools\test_registry.py tests\tools\test_tool_search.py -q --basetemp E:\tmp\pytest-registry-phase4`
  - Passed: `75 passed in 12.46s`.
- Direct schema timing:
  - `model_tools.get_tool_definitions(enabled_toolsets=['hermes-cli'], quiet_mode=True)`
  - Cold in-process call: `28 tools in 2250.8 ms`.
  - Warm cached call: `28 tools in 0.2 ms`.
  - Portable tool present: `False`.
- Direct registry query:
  - `registry.get_entry('portable')` returned `None`.
  - Portable-prefixed registry names returned `[]`.
- `git diff --check`
  - Passed with only Git's existing line-ending warning for `hermes_cli/main.py`.

## Independent Self-Audit

Direct code review after smoke tests found:

- The portable command is wired only through `argparse` and `cmd_portable`; it does not participate in `model_tools`.
- `toolsets.py` was not modified.
- `tools/registry.py` was not modified.
- No optional local-service probe was added by the portable update.
- No new plugin/tool override path was added.
- Cold schema generation still pays for upstream optional checks when unavailable credentials/services are probed; warm memoized generation is effectively instant. This is inherited upstream behavior, not introduced by the portable layer.

## Phase 4 Acceptance

Phase 4 is complete:

- The portable update does not add model-visible tools.
- The portable update does not bypass registry availability checks.
- Registry/tool-search regression tests pass.
- Tool schema generation baseline is recorded and the portable layer is proven not to contribute to optional-service probe cost.
