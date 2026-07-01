# Portable Mode

Portable mode is a source-checkout layout for running Hermes with state beside
the folder:

```text
<portable-root>/
  .hermes/            # config, keys, sessions, skills, logs
    extensions/       # optional local AI services, disabled by default
  scripts/portable/   # launchers
```

Hermes Agent remains based on the upstream Nous Research project. This portable
distribution ships through `aivrar/portable-hermes-agent`, which merges upstream
Hermes changes after validating the portable Windows launchers, runtime state,
and extension tooling.

## Quick Start

From a checkout:

```powershell
python -m hermes_cli.main portable status
python -m hermes_cli.main portable init --apply
python -m hermes_cli.main portable env --shell powershell
```

After the package entry point is installed, the same commands are available as
`hermes portable status`, `hermes portable init`, and `hermes portable env`.

Or use the launcher:

```powershell
scripts\portable\hermes-portable.ps1 -Status
scripts\portable\hermes-portable.ps1
```

The launcher sets only `HERMES_HOME=<portable-root>\.hermes`, validates Python
`>=3.11,<3.14`, creates the folder-local state directories, and then delegates
to `hermes_cli.main`.

## Install And Repair

Portable mode does not duplicate the installer. To bootstrap or repair a
portable checkout, print the exact installer command for the current folder:

```powershell
python -m hermes_cli.main portable install-command --shell powershell
```

Add `--include-desktop` if you want the Electron desktop build included.

## Desktop

The supported GUI path is upstream Electron desktop, not the old Tkinter shell:

```powershell
python -m hermes_cli.main portable desktop-command --shell powershell
```

That command pins `--hermes-root` and `--cwd` to the portable root so the desktop
uses the same checkout and folder-local `.hermes` state.

## Local AI Extensions

Local extensions are disabled by default and never installed, started, or
exposed as model tools by portable commands:

```powershell
python -m hermes_cli.main portable extensions
python -m hermes_cli.main portable extensions --json
```

Current manifests:

| ID | Purpose | Default Check |
| --- | --- | --- |
| `lm-studio` | Local OpenAI-compatible LLM server | `http://127.0.0.1:1234/v1/models` |
| `comfyui` | Image/video workflow service | `http://127.0.0.1:8188/system_stats` |
| `piper-tts-http` | Manual Piper HTTP adapter | No canonical default port |

## Migration

Dry-run first:

```powershell
python -m hermes_cli.main portable migrate --json
```

Copy detected legacy state into `.hermes` without deleting the old files:

```powershell
python -m hermes_cli.main portable migrate --apply
```

For old user-home state, pass the path explicitly:

```powershell
python -m hermes_cli.main portable migrate --legacy-home "$env:USERPROFILE\.hermes" --json
```

Targets are preserved unless `--overwrite` is explicit.

## Updating Safely

Portable runtime state is intentionally kept out of tracked upstream source:

- `.hermes/` holds config, keys, sessions, skills, plugins, logs, backups, and extension payloads
- `.hermes/custom_tools/` holds Tool Maker output created by users or the agent
- `.hermes/extensions/` holds optional local extension payloads and service notes
- root-level `extensions/` is treated as a legacy portable path and is included in backups/migration if present
- `python_embedded/` may hold an optional folder-local Python runtime

For a release-zip install, double-click:

```batch
UPDATE.bat
```

For one-command update safety, run the update through the portable launcher
with `--backup`:

```powershell
scripts\portable\hermes-portable.ps1 -Root . update --backup
```

When portable mode is active, `update --backup` creates the normal
pre-update `HERMES_HOME` backup and an additional focused
`portable-runtime-*.zip` archive for folder-local portable payloads.

You can also create the portable runtime archive manually before any risky
operation:

```powershell
scripts\portable\hermes-portable.ps1 -Root . portable backup
```

`portable backup` writes `portable-runtime-*.zip` under `.hermes/backups/` and
includes `.hermes/` plus a legacy root-level `extensions/` folder if present.
Add `--include-python` if the embedded Python folder is not easily
reinstallable.

`hermes update` stashes uncommitted source edits and untracked
non-ignored source files, then restores them after the pull unless the user has
explicitly configured `updates.non_interactive_local_changes: discard`. Runtime
folders are ignored and preserved in place; the Windows ZIP fallback also treats
`.hermes/`, `extensions/`, and `python_embedded/` as preserve-only directories.
The portable ZIP fallback downloads from `aivrar/portable-hermes-agent`, not
directly from `NousResearch/hermes-agent`.

## Safety

Portable mode does not:

- set `HERMES_YOLO_MODE`
- register model-visible tools
- bypass upstream command approvals
- alter `run_agent.py`, `model_tools.py`, `toolsets.py`, or `tools/registry.py`
- auto-run cloned extension code

All agent semantics, approval bridges, prompt caching, sessions, skills, MCP,
gateway, and desktop behavior remain upstream Hermes behavior.
