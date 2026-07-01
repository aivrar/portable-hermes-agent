# Phase 7 - Local AI Extensions

Date: 2026-06-30
Worktree: `E:\tmp\portable-hermes-major-update`

## Objective

Convert local AI extension ideas into explicit optional manifests with readiness checks, without auto-installing or auto-running third-party code and without exposing model tools by default.

## Research Sources

- LM Studio local server docs: https://lmstudio.ai/docs/developer/core/server
- LM Studio REST/OpenAI-compatible API docs: https://lmstudio.ai/docs/app/api/endpoints/rest
- ComfyUI server routes docs: https://docs.comfy.org/development/comfyui-server/comms_routes
- Piper upstream project: https://github.com/rhasspy/piper

## Implemented

- Added portable extension manifest support in `hermes_cli/portable.py`.
- Added `hermes portable extensions`.
  - Text output for humans.
  - `--json` output for automation.
  - `--timeout` for localhost readiness probes.
- Added disabled-by-default manifests:
  - `lm-studio`
    - Category: `local-llm`
    - Default endpoint: `http://127.0.0.1:1234/v1/models`
    - Managed: no
  - `comfyui`
    - Category: `image-video-workflows`
    - Default endpoint: `http://127.0.0.1:8188/system_stats`
    - Managed: no
    - No port 5000 assumption.
  - `piper-tts-http`
    - Category: `local-tts`
    - Manual adapter only.
    - No invented default HTTP port.
- Added loopback-only health probing.
- Added short TCP connect preflight before HTTP, so missing local services return quickly.
- Added tests for disabled defaults, loopback-only defaults, and status collection without live services.

## Smoke Tests

Environment note: no local `venv` exists in the worktree or main checkout; tests used the available `Python 3.13.11`.

- `python -m py_compile hermes_cli\portable.py hermes_cli\subcommands\portable.py tests\hermes_cli\test_portable.py`
  - Passed.
- `python -m pytest tests\hermes_cli\test_portable.py -q --basetemp E:\tmp\pytest-portable-phase7-final`
  - Passed: `17 passed`.
- `python -m hermes_cli.main portable extensions --json --timeout 0.05`
  - Passed and returned all manifests with LM Studio/ComfyUI offline and Piper manual.
- `python -m hermes_cli.main portable extensions --timeout 0.05`
  - Passed human-readable output.
- Direct probe timing:
  - `collect_extension_status(timeout=0.05)`
  - Returned in `121.4 ms` with services absent.
- Source scan:
  - No `5000` port assumption.
  - No `registry.register`.
  - No `HERMES_YOLO_MODE`.
  - No `run_python`, `tool_maker`, or `update_hermes`.

## Independent Self-Audit

Direct code review after smoke tests found:

- Extensions are informational and disabled by default.
- Status checks only probe loopback HTTP URLs.
- Status checks do not install, start, stop, update, or delete extension code.
- Missing services do not fail the portable command; they report `offline` or `manual`.
- Piper is not assigned a fake default port because the upstream project does not define one canonical HTTP service.
- ComfyUI uses port `8188` and no longer repeats the old fork's ambiguous `5000` management-port story.
- No model-visible extension tools were added. Future integrations should be plugins/MCP/toolsets with explicit opt-in.

## Phase 7 Acceptance

Phase 7 is complete:

- Extension definitions are explicit, inspectable, and reversible.
- Local services are disabled by default.
- Readiness checks are fast and loopback-only.
- Third-party code is never auto-run as a model-tool side effect.
