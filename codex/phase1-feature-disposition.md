# Phase 1 Feature Disposition

Date: 2026-06-30
Integration branch: `major-update/upstream-2026-06-30`
Base commit for integration: upstream `f99ba56df4bb6a1caf490e99c542507e3c3926cb`
Fork overlay range: `86ac23c8da4564de93168071c6edff1ee87ac371..main`

## Decision Summary

The old portable fork changed 85 tracked paths and added roughly 17k lines over its March 2026 base. Current upstream has since added native Windows install support, an Electron desktop app, plugin infrastructure, a stronger registry, a richer approval system, and much more active desktop/dashboard work.

Execution decision:

- Use upstream `main` as the code base.
- Port portable value as isolated distribution/plugin/app work.
- Do not replay old edits into `run_agent.py`, `model_tools.py`, `toolsets.py`, or `tools/registry.py` unless a current-upstream hook is missing and proven necessary.
- Treat arbitrary Python execution, tool creation, self-update, and extension installation as explicitly gated operations.

## Feature Groups

| Group | Old fork files | Disposition |
| --- | --- | --- |
| Tkinter GUI | `gui/*`, `hermes_gui.bat`, `hermes_gui.vbs` | Do not port wholesale. Upstream desktop is now primary. Preserve UX ideas through desktop/provider/settings/extensions work. Keep classic Tk only if it becomes a thin launcher later. |
| Portable Windows install | `install.bat`, `START.bat`, `hermes.bat`, `run_py.*`, `build_release.py` | Redesign around upstream installer/runtime. Add portable-mode launcher/packaging only after state home and dependency policy are explicit. |
| LM Studio UX | `gui/lm_studio.py`, `tools/lm_studio_tools.py`, `skills/lm-studio/*` | Port as local provider UX plus service-gated/plugin capability. Do not default all LM Studio tools into core. |
| Local extensions | `gui/extensions.py`, `tools/extension_tools.py`, `skills/extensions/*` | Port as versioned extension catalog/plugin layer. Require explicit install/start approval. Fix ComfyUI port story. |
| Arbitrary code/tool creation | `tools/run_python_tool.py`, `tools/tool_maker.py` | Keep only as developer opt-in plugin or disabled toolset. Never expose by default. |
| Updater tool | `tools/update_hermes_tool.py` | Drop as model tool. Use upstream installer/update UX or explicit CLI/desktop command outside the model tool surface. |
| Workflow engine | `tools/workflow_tool.py` | Evaluate against upstream cron/delegation/skills. Port only if distinct; likely plugin or CLI surface. |
| Guide/manual | `docs/*`, `tools/guide_tool.py`, `build_manual_pdf.py` | Regenerate later from current product. Guide search should become a skill/docs feature, not a default core tool unless justified. |
| Windows test adaptations | `.github/workflows/tests.yml`, `tests/conftest.py`, `tests/windows_skip.txt` | Reconcile with upstream current tests. Keep only proven Windows fixes. Remove informational CI posture if possible. |
| Direct core edits | `run_agent.py`, `model_tools.py`, `toolsets.py`, `tools/registry.py`, `hermes_constants.py`, `hermes_cli/config.py` | Do not replay blindly. Upstream has newer implementations. Port only narrow missing behavior with tests. |

## Per-Path Disposition

| Path | Old action | Exists on current upstream | Disposition |
| --- | --- | --- | --- |
| `.env.example` | Modified | Yes | Reconcile only portable-specific env examples after final config design. |
| `.github/workflows/deploy-site.yml` | Deleted | Yes | Keep upstream. Portable fork should not delete upstream docs/deploy workflow unless this branch becomes a fork-only release branch. |
| `.github/workflows/docker-publish.yml` | Deleted | No | No action. |
| `.github/workflows/docs-site-checks.yml` | Deleted | Yes | Keep upstream. |
| `.github/workflows/tests.yml` | Modified | Yes | Reconcile after test strategy. Do not preserve "informational CI" as final posture. |
| `CLAUDE.md` | Added | No | Drop or convert into `AGENTS.md`/docs if still useful. Do not add duplicate assistant instructions. |
| `DIAGNOSTIC_LOG.md` | Added | No | Drop from release branch; use issue/changelog if needed. |
| `README.md` | Modified | Yes | Rewrite after implementation; do not port stale claims. |
| `START.bat` | Added | No | Replace with upstream-compatible portable launcher if portable mode remains. |
| `acp_adapter/server.py` | Modified | Yes | Review upstream ACP changes first; cherry-pick only missing bug fixes with tests. |
| `acp_adapter/session.py` | Modified | Yes | Review upstream ACP changes first; cherry-pick only missing title/session fixes if absent. |
| `assets/SOUL.md` | Added | No | Drop from core. Could be optional persona/skill asset later. |
| `build_manual_pdf.py` | Added | No | Drop until docs are regenerated. |
| `build_release.py` | Added | No | Rebuild release packaging around upstream desktop/installer. |
| `cli.py` | Modified | Yes | Do not replay; upstream CLI architecture changed. |
| `docs/Portable-Hermes-Agent-Manual.html` | Added | No | Regenerate later; old manual is stale. |
| `docs/Portable-Hermes-Agent-Manual.pdf` | Added | No | Regenerate later; do not port binary. |
| `docs/gen_pdf.py` | Added | No | Drop until docs pipeline decision. |
| `docs/hermes-guide.md` | Added | No | Salvage content into skill/docs later after accuracy pass. |
| `docs/windows-portable-install-diagnosis.md` | Added | No | Salvage lessons into installer docs if still applicable. |
| `gui/__init__.py` | Added | No | Do not port wholesale. |
| `gui/agent_bridge.py` | Added | No | Do not port. Contains unsafe YOLO bypass; GUI must use upstream approval/session APIs. |
| `gui/api_setup_wizard.py` | Added | No | Salvage UX concepts into upstream desktop onboarding/settings. |
| `gui/app.py` | Added | No | Do not port wholesale. Upstream desktop is primary. |
| `gui/extensions.py` | Added | No | Salvage manifest data into extension catalog with approvals. |
| `gui/lm_studio.py` | Added | No | Salvage LM Studio UX into desktop/provider/local-model settings. |
| `gui/permissions.py` | Added | No | Salvage concepts only; enforcement must happen at tool dispatch/policy layer. |
| `gui/permissions_panel.py` | Added | No | Salvage concepts only. |
| `gui/theme.py` | Added | No | Drop with Tkinter GUI unless classic mode is revived later. |
| `hermes.bat` | Added | No | Replace with portable launcher if needed. |
| `hermes_cli/config.py` | Modified | Yes | Reconcile only if old UTF-8/env fixes are absent; upstream is much newer. |
| `hermes_constants.py` | Modified | Yes | Keep upstream profile-safe behavior; do not regress. |
| `hermes_gui.bat` | Added | No | Replace only if classic/portable launcher remains. |
| `hermes_gui.vbs` | Added | No | Drop unless classic launcher remains. |
| `hermes_state.py` | Modified | Yes | Reconcile title/limit/session fixes only if upstream lacks them. |
| `install.bat` | Added | No | Replace with redesigned portable installer using upstream install lessons. |
| `model_tools.py` | Modified | Yes | Do not inject custom imports into core. Use registry/plugin discovery. |
| `plans/checkpoint-rollback.md` | Added | No | Drop or move to docs if still relevant. |
| `pyproject.toml` | Modified | Yes | Keep upstream exact-pin posture. Add portable extras only if necessary. |
| `run_agent.py` | Modified | Yes | Do not replay; upstream agent loop split/refactored. |
| `run_py.bat` | Added | No | Replace with portable runtime launcher if needed. |
| `run_py.sh` | Added | No | Replace with portable runtime launcher if needed. |
| `skills/creative/ascii-video/references/design-patterns.md` | Added | No | Optional skill pack; do not make core requirement. |
| `skills/creative/ascii-video/references/examples.md` | Added | No | Optional skill pack. |
| `skills/extensions/comfyui/metadata.yaml` | Added | No | Salvage into extension skill/plugin after port. |
| `skills/extensions/comfyui/skill.md` | Added | No | Salvage after port and port fix. |
| `skills/extensions/music-server/metadata.yaml` | Added | No | Salvage into extension skill/plugin after port. |
| `skills/extensions/music-server/skill.md` | Added | No | Salvage after port. |
| `skills/extensions/tts-server/metadata.yaml` | Added | No | Salvage into extension skill/plugin after port. |
| `skills/extensions/tts-server/skill.md` | Added | No | Salvage after port. |
| `skills/getting-started/metadata.yaml` | Added | No | Salvage into onboarding docs only if accurate. |
| `skills/getting-started/skill.md` | Added | No | Salvage after docs rewrite. |
| `skills/lm-studio/metadata.yaml` | Added | No | Salvage into LM Studio skill/plugin. |
| `skills/lm-studio/skill.md` | Added | No | Salvage after LM Studio port. |
| `smoke_test_all_tools.py` | Added | No | Replace with focused tests; old all-tools smoke can hide safety problems. |
| `test_all_tools.py` | Added | No | Replace with focused tests. |
| `tests/conftest.py` | Modified | Yes | Reconcile Windows isolation fixes after upstream test review. |
| `tests/gateway/test_image_enrichment.py` | Added | No | Check if upstream has equivalent; port if missing and still relevant. |
| `tests/hermes_cli/test_gateway.py` | Modified | Yes | Reconcile only if old fixes absent. |
| `tests/hermes_cli/test_gateway_linger.py` | Modified | Yes | Reconcile only if old fixes absent. |
| `tests/hermes_cli/test_gateway_service.py` | Modified | Yes | Reconcile only if old fixes absent. |
| `tests/hermes_cli/test_session_browse.py` | Modified | Yes | Reconcile only if old fixes absent. |
| `tests/test_auxiliary_config_bridge.py` | Modified | No | Drop unless current upstream has same test module. |
| `tests/test_percentage_clamp.py` | Modified | No | Drop unless current upstream has same test module. |
| `tests/windows_skip.txt` | Added | No | Avoid broad skip list as final solution. Use targeted fixes/skips only. |
| `tools/browse_tools_tool.py` | Added | No | Drop or redesign as UI/help surface; not core model tool by default. |
| `tools/code_execution_tool.py` | Modified | Yes | Review upstream current implementation; port only missing Windows fix with test. |
| `tools/custom/__init__.py` | Added | No | Drop with old tool maker design. |
| `tools/custom/manifest.json` | Added | No | Drop with old tool maker design. |
| `tools/environments/local.py` | Modified | Yes | Review upstream Windows runtime and Git Bash handling first. |
| `tools/extension_tools.py` | Added | No | Port as extension plugin/service-gated toolset after safety design. |
| `tools/gpu_tool.py` | Added | No | Port as service-gated optional tool/plugin if useful. |
| `tools/guide_tool.py` | Added | No | Prefer skill/docs search; avoid default core tool. |
| `tools/lm_studio_tools.py` | Added | No | Port as optional service-gated/plugin capability. |
| `tools/memory_tool.py` | Modified | Yes | Review upstream memory provider architecture; do not replay blindly. |
| `tools/mixture_of_agents_tool.py` | Modified | No | Likely upstream refactored; drop unless specific bug still exists. |
| `tools/model_switcher_tool.py` | Added | No | Drop; upstream has model switching UX/commands. |
| `tools/registry.py` | Modified | Yes | Keep upstream registry; it already solves much more than old fork. |
| `tools/run_python_tool.py` | Added | No | Disabled/dev-only plugin at most. |
| `tools/serper_search_tool.py` | Added | No | Prefer upstream web provider/plugin architecture. |
| `tools/terminal_tool.py` | Modified | Yes | Review upstream; do not replay. |
| `tools/todo_tool.py` | Modified | Yes | Review upstream; do not replay. |
| `tools/tool_maker.py` | Added | No | Disabled/dev-only plugin at most. |
| `tools/update_hermes_tool.py` | Added | No | Drop as model tool. |
| `tools/workflow_tool.py` | Added | No | Evaluate as plugin/CLI after comparing upstream cron/skills/delegation. |

## Phase 1 Smoke Test

Required checks:

- `git diff --name-status 86ac23c8da4564de93168071c6edff1ee87ac371..main`
- `git diff --stat 86ac23c8da4564de93168071c6edff1ee87ac371..main`
- current upstream worktree status clean before writing this file
- this file covers all 85 changed paths from the fork overlay

Actual result:

- Fork changed paths counted: 85.
- Missing paths from this disposition table: 0.
- Integration worktree status after this artifact: only `codex/` is untracked.
- Upstream base verified: `f99ba56df4bb6a1caf490e99c542507e3c3926cb`.

## Phase 1 Self-Audit Notes

Audit questions for the next phase:

- Does every old portable feature have an explicit disposition? Yes, by path and group.
- Are unsafe defaults identified before code porting starts? Yes: GUI YOLO, `run_python`, `tool_maker`, and `update_hermes`.
- Are upstream-owned surfaces protected from blind replay? Yes: core agent, registry, config, terminal, and model tools are marked "do not replay blindly."
- Is the next phase allowed to modify code? Yes, but only by applying the disposition table and keeping portable work isolated.

Self-audit result: pass. The table is comprehensive against the fork overlay and prevents the two main failure modes: replaying stale core edits and keeping unsafe model-visible tools as defaults.
