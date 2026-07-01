#!/usr/bin/env python3
"""
Update Hermes Tool — Pull latest from NousResearch/hermes-agent upstream.

Handles the merge carefully:
1. Stashes local uncommitted changes
2. Pulls origin/main
3. Pops stash and reports conflicts if any
4. Re-injects custom tool imports into model_tools.py if upstream overwrote them
5. Re-injects custom tool entries into toolsets.py _HERMES_CORE_TOOLS if needed

Custom tools (local-only, not in upstream):
- tools/lm_studio_tools.py   (lm_studio toolset)
- tools/extension_tools.py   (music, extension_tts, comfyui toolsets)
- tools/gpu_tool.py           (gpu toolset)
- tools/model_switcher_tool.py (model_switcher toolset)
- tools/run_python_tool.py    (run_python toolset)
"""

import json
import logging
import subprocess
import re
from pathlib import Path

from tools.registry import registry

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Custom tool modules that we need to ensure are imported in model_tools.py
_CUSTOM_MODULES = [
    "tools.run_python_tool",
    "tools.lm_studio_tools",
    "tools.gpu_tool",
    "tools.model_switcher_tool",
    "tools.extension_tools",
    "tools.update_hermes_tool",
    "tools.tool_maker",
    "tools.workflow_tool",
    "tools.serper_search_tool",
]

# Custom tool names that must be in _HERMES_CORE_TOOLS in toolsets.py
_CUSTOM_CORE_TOOLS = [
    # Python execution
    "run_python",
    # GPU info
    "gpu_info",
    # Model switching
    "switch_model",
    # LM Studio
    "lm_studio_status", "lm_studio_models", "lm_studio_load", "lm_studio_unload",
    "lm_studio_search", "lm_studio_download", "lm_studio_model_info", "lm_studio_tokenize",
    "lm_studio_embed", "lm_studio_chat",
    # Music
    "music_status", "music_generate",
    "music_models", "music_model_load", "music_model_unload", "music_outputs", "music_install",
    # TTS
    "tts_server_status", "tts_server_generate",
    "tts_server_models", "tts_server_model_load", "tts_server_model_unload",
    "tts_server_voices", "tts_server_jobs",
    # ComfyUI
    "comfyui_status",
    "comfyui_instances", "comfyui_instance_start", "comfyui_instance_stop",
    "comfyui_generate", "comfyui_models", "comfyui_nodes",
    # Hermes update
    "update_hermes", "check_hermes_updates",
    # Tool maker
    "create_tool", "delete_tool", "list_custom_tools",
    # Workflows
    "workflow_create", "workflow_run", "workflow_list", "workflow_delete", "workflow_show",
    "workflow_schedule",
    # Serper
    "serper_search",
]

# Toolset definitions to inject if missing
_CUSTOM_TOOLSETS = {
    "run_python": {
        "description": "Execute Python code directly via stdin pipe (no shell escaping issues)",
        "tools": ["run_python"],
        "includes": [],
    },
    "gpu": {
        "description": "NVIDIA GPU status: memory, temperature, utilization",
        "tools": ["gpu_info"],
        "includes": [],
    },
    "model_switcher": {
        "description": "Switch the active LLM model by updating .env",
        "tools": ["switch_model"],
        "includes": [],
    },
    "lm_studio": {
        "description": "LM Studio control: status, search, download, load/unload, model info, tokenization",
        "tools": [
            "lm_studio_status", "lm_studio_models", "lm_studio_load", "lm_studio_unload",
            "lm_studio_search", "lm_studio_download", "lm_studio_model_info", "lm_studio_tokenize",
        ],
        "includes": [],
    },
    "music": {
        "description": "Music generation: status, models, load/unload, generate, install, output library",
        "tools": [
            "music_status", "music_generate",
            "music_models", "music_model_load", "music_model_unload",
            "music_outputs", "music_install",
        ],
        "includes": [],
    },
    "extension_tts": {
        "description": "Local TTS server: models, load/unload, voices, generate, jobs",
        "tools": [
            "tts_server_status", "tts_server_generate",
            "tts_server_models", "tts_server_model_load", "tts_server_model_unload",
            "tts_server_voices", "tts_server_jobs",
        ],
        "includes": [],
    },
    "comfyui": {
        "description": "ComfyUI: instances, models, nodes, image generation",
        "tools": [
            "comfyui_status",
            "comfyui_instances", "comfyui_instance_start", "comfyui_instance_stop",
            "comfyui_generate", "comfyui_models", "comfyui_nodes",
        ],
        "includes": [],
    },
}


def _run_git(*args, timeout=60):
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True,
        cwd=str(_PROJECT_ROOT),
        timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _ensure_custom_imports():
    """Ensure model_tools.py imports our custom tool modules."""
    mt_path = _PROJECT_ROOT / "model_tools.py"
    if not mt_path.exists():
        return "model_tools.py not found"

    content = mt_path.read_text(encoding="utf-8")
    added = []

    for mod in _CUSTOM_MODULES:
        if f'"{mod}"' not in content:
            # Insert before the closing bracket of the _modules list
            content = content.replace(
                '    ]\n    import importlib',
                f'        "{mod}",\n    ]\n    import importlib',
            )
            added.append(mod)

    if added:
        mt_path.write_text(content, encoding="utf-8")
        return f"Added imports: {', '.join(added)}"
    return "All custom imports present"


def _ensure_core_tools():
    """Ensure toolsets.py _HERMES_CORE_TOOLS has our custom tool names."""
    ts_path = _PROJECT_ROOT / "toolsets.py"
    if not ts_path.exists():
        return "toolsets.py not found"

    content = ts_path.read_text(encoding="utf-8")
    missing = [t for t in _CUSTOM_CORE_TOOLS if f'"{t}"' not in content]

    if missing:
        # Find the end of _HERMES_CORE_TOOLS list and inject before the closing ]
        # Build injection block
        lines = []
        lines.append("    # Custom local tools (LM Studio, extensions, GPU, etc.)")
        for t in missing:
            lines.append(f'    "{t}",')
        injection = "\n".join(lines) + "\n"

        # Insert before the closing ] of _HERMES_CORE_TOOLS
        content = re.sub(
            r'(\n]\s*\n\n# Core toolset definitions)',
            f'\n{injection}]\n\n# Core toolset definitions',
            content,
            count=1,
        )
        ts_path.write_text(content, encoding="utf-8")
        return f"Added {len(missing)} tool names to _HERMES_CORE_TOOLS"
    return "All custom tools present in _HERMES_CORE_TOOLS"


def _ensure_upstream_remote():
    """Ensure the 'upstream' remote exists pointing to NousResearch."""
    rc, out, _ = _run_git("remote", "get-url", "upstream")
    if rc != 0:
        # No upstream remote — add it
        _run_git("remote", "add", "upstream",
                 "https://github.com/NousResearch/hermes-agent.git")
        return "added"
    return "exists"


def _ensure_git_repo():
    """Ensure we're in a git repo (fresh zip installs won't have one)."""
    rc, _, _ = _run_git("status")
    if rc != 0:
        # Initialize a git repo
        _run_git("init")
        _run_git("add", "-A")
        _run_git("commit", "-m", "Initial portable install")
        return "initialized"
    return "exists"


def update_hermes_handler(args: dict, **kwargs) -> str:
    """Pull latest from NousResearch upstream and re-inject custom tools."""
    results = {"steps": []}

    # 0. Ensure git repo and upstream remote exist
    repo_status = _ensure_git_repo()
    results["steps"].append({"git_repo": repo_status})

    upstream_status = _ensure_upstream_remote()
    results["steps"].append({"upstream_remote": upstream_status})

    # 1. Check for uncommitted changes
    rc, out, err = _run_git("status", "--porcelain")
    has_changes = bool(out.strip())
    results["steps"].append({"check_status": "has changes" if has_changes else "clean"})

    # 2. Stash if needed
    stashed = False
    if has_changes:
        rc, out, err = _run_git("stash", "push", "-m", "hermes-update-tool-autostash")
        if rc == 0:
            stashed = True
            results["steps"].append({"stash": "saved"})
        else:
            results["steps"].append({"stash": f"failed: {err}"})
            return json.dumps(results, ensure_ascii=False)

    # 3. Fetch upstream
    rc, out, err = _run_git("fetch", "upstream", timeout=60)
    if rc != 0:
        results["steps"].append({"fetch": f"failed: {err}"})
        if stashed:
            _run_git("stash", "pop")
        return json.dumps(results, ensure_ascii=False)
    results["steps"].append({"fetch": "success"})

    # 4. Merge upstream/main
    rc, out, err = _run_git("merge", "upstream/main", "--ff-only", timeout=120)
    if rc == 0:
        results["steps"].append({"merge": "success", "output": out[:500]})
    else:
        # Try merge without ff-only (will create merge commit)
        rc2, out2, err2 = _run_git("merge", "upstream/main",
                                    "--no-edit", timeout=120)
        if rc2 == 0:
            results["steps"].append({"merge": "success (merge commit)", "output": out2[:500]})
        else:
            _run_git("merge", "--abort")
            if "unrelated histories" in err2.lower():
                results["steps"].append({
                    "merge": "skipped",
                    "reason": "Unrelated histories — this fork was built from a snapshot, not a git fork. "
                              "Use 'git cherry-pick <commit>' to pull specific upstream fixes, or "
                              "compare upstream changes at https://github.com/NousResearch/hermes-agent/commits/main"
                })
            else:
                results["steps"].append({"merge": f"failed: {err2[:500]}"})
            if stashed:
                _run_git("stash", "pop")
            return json.dumps(results, ensure_ascii=False)

    # 4. Pop stash
    if stashed:
        rc, out, err = _run_git("stash", "pop")
        if rc == 0:
            results["steps"].append({"stash_pop": "clean"})
        else:
            results["steps"].append({"stash_pop": f"conflicts: {err[:500]}"})

    # 5. Re-inject custom tool imports
    imports_result = _ensure_custom_imports()
    results["steps"].append({"custom_imports": imports_result})

    # 6. Re-inject custom core tools
    core_result = _ensure_core_tools()
    results["steps"].append({"custom_core_tools": core_result})

    # 7. Final status
    rc, out, err = _run_git("log", "--oneline", "-1")
    results["current_commit"] = out
    results["success"] = True

    return json.dumps(results, indent=2, ensure_ascii=False)


def check_updates_handler(args: dict, **kwargs) -> str:
    """Check how many commits behind NousResearch upstream without pulling."""
    # Ensure git repo and remote exist
    repo_status = _ensure_git_repo()
    remote_status = _ensure_upstream_remote()

    rc, out, err = _run_git("fetch", "upstream", timeout=30)
    if rc != 0:
        return json.dumps({"error": f"Fetch upstream failed: {err}"})

    rc, out, err = _run_git("log", "--oneline", "HEAD..upstream/main")
    commits = out.strip().splitlines() if out.strip() else []

    rc2, local_out, _ = _run_git("log", "--oneline", "-1")

    return json.dumps({
        "commits_behind": len(commits),
        "current_commit": local_out,
        "recent_upstream": [c for c in commits[:10]],
        "needs_update": len(commits) > 0,
        "upstream": "NousResearch/hermes-agent",
    }, indent=2, ensure_ascii=False)


# ===========================================================================
# Schemas & Registration
# ===========================================================================

UPDATE_SCHEMA = {
    "name": "update_hermes",
    "description": (
        "Update Hermes to the latest version from NousResearch/hermes-agent. "
        "Stashes local changes, pulls upstream, pops stash, and re-injects "
        "custom tool imports (LM Studio, extensions, GPU, etc.)."
    ),
    "parameters": {"type": "object", "properties": {}},
}

CHECK_UPDATES_SCHEMA = {
    "name": "check_hermes_updates",
    "description": (
        "Check if there are upstream updates available for Hermes without pulling. "
        "Shows how many commits behind and recent changes."
    ),
    "parameters": {"type": "object", "properties": {}},
}

registry.register(
    name="update_hermes",
    toolset="hermes_update",
    schema=UPDATE_SCHEMA,
    handler=update_hermes_handler,
)

registry.register(
    name="check_hermes_updates",
    toolset="hermes_update",
    schema=CHECK_UPDATES_SCHEMA,
    handler=check_updates_handler,
)
