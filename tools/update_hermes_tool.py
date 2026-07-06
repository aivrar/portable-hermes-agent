#!/usr/bin/env python3
"""Hermes update tools for Portable Hermes Agent.

``update_hermes`` intentionally restores the original Portable Hermes behavior:
pull upstream Hermes code from ``NousResearch/hermes-agent`` and then repair the
portable tool surface so this repo's LM Studio, extension, workflow, guide, and
runtime tools remain available.

The normal CLI command ``hermes update`` still updates the portable
distribution from ``aivrar/portable-hermes-agent``. This model-visible tool is
for updating the embedded upstream Hermes agent code.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from tools.registry import registry


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PORTABLE_REPO = "aivrar/portable-hermes-agent"
_UPSTREAM_REPO = "NousResearch/hermes-agent"
_UPSTREAM_REPO_URL = "https://github.com/NousResearch/hermes-agent.git"
_UPSTREAM_ZIP_URL = "https://github.com/NousResearch/hermes-agent/archive/refs/heads/{branch}.zip"
_UPSTREAM_REMOTE_CANDIDATES = ("hermes-upstream", "upstream")

_TAIL_LIMIT = 4000

_PORTABLE_RUNTIME_DIRS = {
    ".git",
    ".github",
    ".hermes",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "extensions",
    "node_modules",
    "python_embedded",
    "tests",
    "venv",
}

_PORTABLE_RUNTIME_PATHS = {
    ".env",
    "build_release.py",
}

_PORTABLE_SOURCE_PATHS = {
    "README.md",
    "START.bat",
    "START_HERE.txt",
    "UPDATE.bat",
    "hermes.bat",
    "install.bat",
    "scripts/install.cmd",
    "scripts/install.ps1",
    "scripts/install.sh",
    "docs/hermes-guide.md",
    "docs/Portable-Hermes-Agent-Manual.pdf",
    "tools/update_hermes_tool.py",
    "tools/run_python_tool.py",
    "tools/lm_studio_tools.py",
    "tools/gpu_tool.py",
    "tools/model_switcher_tool.py",
    "tools/extension_tools.py",
    "tools/tool_maker.py",
    "tools/workflow_tool.py",
    "tools/serper_search_tool.py",
    "tools/guide_tool.py",
}

_CUSTOM_CORE_TOOLS = [
    "run_python",
    "gpu_info",
    "switch_model",
    "lm_studio_status", "lm_studio_models", "lm_studio_load", "lm_studio_unload",
    "lm_studio_search", "lm_studio_download", "lm_studio_model_info",
    "lm_studio_tokenize", "lm_studio_embed", "lm_studio_chat",
    "music_status", "music_generate",
    "music_models", "music_model_load", "music_model_unload", "music_outputs",
    "music_install",
    "tts_server_status", "tts_server_generate",
    "tts_server_models", "tts_server_model_load", "tts_server_model_unload",
    "tts_server_voices", "tts_server_jobs",
    "comfyui_status", "comfyui_instances", "comfyui_instance_start",
    "comfyui_instance_stop", "comfyui_generate", "comfyui_models",
    "comfyui_nodes",
    "update_hermes", "check_hermes_updates",
    "create_tool", "delete_tool", "list_custom_tools",
    "workflow_create", "workflow_run", "workflow_list", "workflow_delete",
    "workflow_show", "workflow_schedule",
    "serper_search", "search_guide",
]

_CUSTOM_TOOLSETS: dict[str, dict[str, Any]] = {
    "run_python": {
        "description": "Execute Python code through the portable Python runtime",
        "tools": ["run_python"],
        "includes": [],
    },
    "gpu": {
        "description": "NVIDIA GPU status: memory, temperature, and utilization",
        "tools": ["gpu_info"],
        "includes": [],
    },
    "model_switcher": {
        "description": "Switch the active model/provider configuration",
        "tools": ["switch_model"],
        "includes": [],
    },
    "lm_studio": {
        "description": "LM Studio local model control and model library tools",
        "tools": [
            "lm_studio_status", "lm_studio_models", "lm_studio_load",
            "lm_studio_unload", "lm_studio_search", "lm_studio_download",
            "lm_studio_model_info", "lm_studio_tokenize",
            "lm_studio_embed", "lm_studio_chat",
        ],
        "includes": [],
    },
    "music": {
        "description": "Portable music generation server tools",
        "tools": [
            "music_status", "music_generate", "music_models",
            "music_model_load", "music_model_unload", "music_outputs",
            "music_install",
        ],
        "includes": [],
    },
    "extension_tts": {
        "description": "Portable TTS server tools for local voice models",
        "tools": [
            "tts_server_status", "tts_server_generate", "tts_server_models",
            "tts_server_model_load", "tts_server_model_unload",
            "tts_server_voices", "tts_server_jobs",
        ],
        "includes": [],
    },
    "comfyui": {
        "description": "Portable ComfyUI image generation and instance tools",
        "tools": [
            "comfyui_status", "comfyui_instances", "comfyui_instance_start",
            "comfyui_instance_stop", "comfyui_generate", "comfyui_models",
            "comfyui_nodes",
        ],
        "includes": [],
    },
    "hermes_update": {
        "description": "Update upstream Hermes from NousResearch and preserve Portable Hermes tools",
        "tools": ["update_hermes", "check_hermes_updates"],
        "includes": [],
    },
    "tool_maker": {
        "description": "Create, delete, and list runtime custom tools",
        "tools": ["create_tool", "delete_tool", "list_custom_tools"],
        "includes": [],
    },
    "workflows": {
        "description": "Create, run, schedule, and manage multi-step workflows",
        "tools": [
            "workflow_create", "workflow_run", "workflow_list",
            "workflow_delete", "workflow_show", "workflow_schedule",
        ],
        "includes": [],
    },
    "serper": {
        "description": "Google-quality search through Serper.dev",
        "tools": ["serper_search"],
        "includes": [],
    },
    "guide": {
        "description": "Search the built-in Portable Hermes Agent guide",
        "tools": ["search_guide"],
        "includes": [],
    },
}


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _tail(text: str | None, limit: int = _TAIL_LIMIT) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[-limit:]


def _run_git(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def _is_git_checkout() -> bool:
    return (_PROJECT_ROOT / ".git").exists()


def _current_commit() -> str:
    rc, out, _ = _run_git("log", "--oneline", "-1")
    return out if rc == 0 else ""


def _normalize_repo_url(url: str | None) -> str:
    if not url:
        return ""
    normalized = url.strip().rstrip("/").lower()
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized[len("git@github.com:") :]
    elif normalized.startswith("ssh://git@github.com/"):
        normalized = "https://github.com/" + normalized[len("ssh://git@github.com/") :]
    return normalized


def _is_upstream_url(url: str | None) -> bool:
    return _normalize_repo_url(url) == _normalize_repo_url(_UPSTREAM_REPO_URL)


def _remote_url(name: str) -> str | None:
    rc, out, _ = _run_git("remote", "get-url", name)
    return out if rc == 0 and out else None


def _ensure_upstream_remote(reset_wrong_remote: bool = False) -> tuple[bool, str, str]:
    """Return ``(ok, remote_name, status)`` for the NousResearch remote."""
    first_missing = _UPSTREAM_REMOTE_CANDIDATES[0]
    wrong: list[str] = []

    for remote in _UPSTREAM_REMOTE_CANDIDATES:
        url = _remote_url(remote)
        if not url:
            continue
        if _is_upstream_url(url):
            return True, remote, "exists"
        wrong.append(f"{remote}={url}")

    if wrong and not reset_wrong_remote:
        return (
            False,
            "",
            "Existing upstream remote does not point to "
            f"{_UPSTREAM_REPO}: {', '.join(wrong)}",
        )

    if wrong and reset_wrong_remote:
        remote = wrong[0].split("=", 1)[0]
        rc, _, err = _run_git("remote", "set-url", remote, _UPSTREAM_REPO_URL)
        if rc != 0:
            return False, "", f"Could not reset {remote}: {err}"
        return True, remote, "reset"

    rc, _, err = _run_git("remote", "add", first_missing, _UPSTREAM_REPO_URL)
    if rc != 0:
        return False, "", f"Could not add {first_missing}: {err}"
    return True, first_missing, "added"


def _working_tree_dirty() -> bool:
    rc, out, _ = _run_git("status", "--porcelain")
    return rc == 0 and bool(out)


def _stash_local_changes_if_needed() -> tuple[bool, str | None, str]:
    if not _working_tree_dirty():
        return True, None, "clean"
    rc, out, err = _run_git(
        "stash",
        "push",
        "--include-untracked",
        "-m",
        "portable-hermes-upstream-sync-autostash",
        timeout=120,
    )
    if rc != 0:
        return False, None, err
    stash_ref = "stash@{0}" if out else None
    return True, stash_ref, out or "stashed"


def _restore_stash(stash_ref: str | None) -> tuple[bool, str]:
    if not stash_ref:
        return True, "not needed"
    rc, out, err = _run_git("stash", "pop", stash_ref, timeout=120)
    if rc != 0:
        return False, err or out
    return True, out or "restored"


def _create_backup_branch() -> str | None:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"portable-hermes-before-upstream-{suffix}"
    rc, _, _ = _run_git("branch", name)
    return name if rc == 0 else None


def _snapshot_portable_sources() -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for rel_path in sorted(_PORTABLE_SOURCE_PATHS):
        path = _PROJECT_ROOT / rel_path
        if path.is_file():
            snapshot[rel_path] = path.read_bytes()
    return snapshot


def _restore_portable_sources(snapshot: dict[str, bytes]) -> list[str]:
    restored: list[str] = []
    for rel_path, content in snapshot.items():
        path = _PROJECT_ROOT / rel_path
        if path.exists() and path.read_bytes() == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        restored.append(rel_path)
    return restored


def _ensure_custom_core_tools() -> str:
    path = _PROJECT_ROOT / "toolsets.py"
    if not path.exists():
        return "toolsets.py not found"

    content = path.read_text(encoding="utf-8")
    missing = [name for name in _CUSTOM_CORE_TOOLS if f'"{name}"' not in content]
    if not missing:
        return "all custom core tools present"

    injection = "\n".join(f'    "{name}",' for name in missing) + "\n"
    updated = re.sub(
        r"(\n]\s*\n\n# Core toolset definitions)",
        f"\n    # Portable Hermes custom tools\n{injection}]\n\n# Core toolset definitions",
        content,
        count=1,
    )
    if updated == content:
        return f"could not inject {len(missing)} custom core tools"
    path.write_text(updated, encoding="utf-8")
    return f"added {len(missing)} custom core tools"


def _format_toolset(name: str, spec: dict[str, Any]) -> str:
    tools = ", ".join(f'"{tool}"' for tool in spec["tools"])
    includes = ", ".join(f'"{item}"' for item in spec.get("includes", []))
    return (
        f'    "{name}": {{\n'
        f'        "description": "{spec["description"]}",\n'
        f'        "tools": [{tools}],\n'
        f'        "includes": [{includes}],\n'
        f"    }},\n\n"
    )


def _ensure_custom_toolsets() -> str:
    path = _PROJECT_ROOT / "toolsets.py"
    if not path.exists():
        return "toolsets.py not found"

    content = path.read_text(encoding="utf-8")
    missing = [name for name in _CUSTOM_TOOLSETS if f'    "{name}": {{' not in content]
    if not missing:
        return "all custom toolsets present"

    marker = '    "terminal": {'
    insert_at = content.find(marker)
    if insert_at < 0:
        return f"could not inject {len(missing)} custom toolsets"

    block = "".join(_format_toolset(name, _CUSTOM_TOOLSETS[name]) for name in missing)
    content = content[:insert_at] + block + content[insert_at:]
    path.write_text(content, encoding="utf-8")
    return f"added {len(missing)} custom toolsets"


def _repair_portable_surface(snapshot: dict[str, bytes] | None = None) -> dict[str, Any]:
    snapshot = snapshot or {}
    restored = _restore_portable_sources(snapshot)
    return {
        "restored_portable_sources": restored,
        "custom_core_tools": _ensure_custom_core_tools(),
        "custom_toolsets": _ensure_custom_toolsets(),
        "preserved_runtime_paths": sorted(_PORTABLE_RUNTIME_DIRS | _PORTABLE_RUNTIME_PATHS),
    }


def _is_preserved_overlay_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    if norm in _PORTABLE_RUNTIME_PATHS or norm in _PORTABLE_SOURCE_PATHS:
        return True
    first = norm.split("/", 1)[0]
    return first in _PORTABLE_RUNTIME_DIRS


def _safe_extract_zip(zf: zipfile.ZipFile, tmp_dir: str) -> None:
    tmp_real = os.path.realpath(tmp_dir)
    for member in zf.infolist():
        member_path = os.path.realpath(os.path.join(tmp_dir, member.filename))
        if not member_path.startswith(tmp_real + os.sep) and member_path != tmp_real:
            raise ValueError(f"Zip-slip detected: {member.filename}")
        mode = (member.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"ZIP contains unsupported symlink member: {member.filename}")
    zf.extractall(tmp_dir)


def _overlay_upstream_zip(branch: str, timeout: int = 600) -> dict[str, Any]:
    tmp_dir = tempfile.mkdtemp(prefix="hermes-upstream-")
    try:
        zip_url = _UPSTREAM_ZIP_URL.format(branch=branch)
        zip_path = os.path.join(tmp_dir, f"hermes-agent-{branch}.zip")
        with urlopen(zip_url, timeout=timeout) as response, open(zip_path, "wb") as fh:
            shutil.copyfileobj(response, fh)

        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract_zip(zf, tmp_dir)

        extracted = None
        for child in Path(tmp_dir).iterdir():
            if child.is_dir() and child.name != "__MACOSX":
                extracted = child
                break
        if extracted is None:
            return {"success": False, "error": "Could not find extracted upstream tree"}

        copied = 0
        skipped = 0
        for src in sorted(path for path in extracted.rglob("*") if path.is_file()):
            rel = src.relative_to(extracted).as_posix()
            if _is_preserved_overlay_path(rel):
                skipped += 1
                continue
            dst = _PROJECT_ROOT / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1

        return {
            "success": True,
            "source": zip_url,
            "copied_files": copied,
            "skipped_preserved_files": skipped,
        }
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def check_updates_handler(args: dict, **kwargs) -> str:
    """Check for upstream Hermes updates without applying them."""
    branch = str(args.get("branch") or "main").strip() or "main"
    timeout = int(args.get("timeout", 120) or 120)
    timeout = max(30, min(timeout, 600))

    if not _is_git_checkout():
        return _json(
            {
                "upstream": _UPSTREAM_REPO,
                "branch": branch,
                "can_update": True,
                "needs_update": None,
                "update_mode": "upstream_zip_overlay",
                "reason": (
                    "This install has no .git directory, so update_hermes will "
                    "download and overlay the upstream branch ZIP without "
                    "requiring Git."
                ),
                "recommended_tool": "update_hermes",
            }
        )

    ok, remote, status = _ensure_upstream_remote(
        reset_wrong_remote=bool(args.get("reset_upstream", False))
    )
    if not ok:
        return _json(
            {
                "upstream": _UPSTREAM_REPO,
                "branch": branch,
                "can_update": False,
                "needs_update": None,
                "error": status,
            }
        )

    rc, _, err = _run_git("fetch", remote, branch, "--quiet", timeout=timeout)
    if rc != 0:
        return _json(
            {
                "upstream": _UPSTREAM_REPO,
                "branch": branch,
                "can_update": False,
                "needs_update": None,
                "remote": remote,
                "error": err,
            }
        )

    compare_ref = f"{remote}/{branch}"
    rc, out, err = _run_git("rev-list", "--count", f"HEAD..{compare_ref}")
    if rc != 0:
        return _json(
            {
                "upstream": _UPSTREAM_REPO,
                "branch": branch,
                "can_update": False,
                "needs_update": None,
                "remote": remote,
                "error": err,
            }
        )

    try:
        commits_behind = int(out or "0")
    except ValueError:
        commits_behind = 0

    rc, recent, _ = _run_git("log", "--oneline", f"HEAD..{compare_ref}", "-10")
    return _json(
        {
            "upstream": _UPSTREAM_REPO,
            "branch": branch,
            "remote": remote,
            "remote_status": status,
            "can_update": True,
            "needs_update": commits_behind > 0,
            "commits_behind": commits_behind,
            "current_commit": _current_commit(),
            "recent_upstream": recent.splitlines() if rc == 0 and recent else [],
            "recommended_tool": "update_hermes",
        }
    )


def update_hermes_handler(args: dict, **kwargs) -> str:
    """Update upstream Hermes and preserve Portable Hermes custom tools."""
    branch = str(args.get("branch") or "main").strip() or "main"
    timeout = int(args.get("timeout", 1800) or 1800)
    timeout = max(60, min(timeout, 7200))
    allow_merge_commit = bool(args.get("allow_merge_commit", True))
    reset_upstream = bool(args.get("reset_upstream", False))
    backup_branch = bool(args.get("backup_branch", True))

    snapshot = _snapshot_portable_sources()
    result: dict[str, Any] = {
        "upstream": _UPSTREAM_REPO,
        "branch": branch,
        "mode": "git_merge" if _is_git_checkout() else "upstream_zip_overlay",
        "steps": [],
    }

    if not _is_git_checkout():
        overlay = _overlay_upstream_zip(branch, timeout=timeout)
        result["steps"].append({"upstream_zip_overlay": overlay})
        result["portable_repair"] = _repair_portable_surface(snapshot)
        result["success"] = bool(overlay.get("success"))
        result["current_commit"] = ""
        return _json(result)

    ok, remote, remote_status = _ensure_upstream_remote(reset_wrong_remote=reset_upstream)
    result["steps"].append({"upstream_remote": remote_status, "remote": remote})
    if not ok:
        result["success"] = False
        result["error"] = remote_status
        return _json(result)

    if backup_branch:
        backup = _create_backup_branch()
        result["steps"].append({"backup_branch": backup or "failed"})

    stash_ok, stash_ref, stash_status = _stash_local_changes_if_needed()
    result["steps"].append({"stash": stash_status})
    if not stash_ok:
        result["success"] = False
        result["error"] = stash_status
        return _json(result)

    try:
        rc, _, err = _run_git("fetch", remote, branch, "--quiet", timeout=timeout)
        result["steps"].append({"fetch": "success" if rc == 0 else _tail(err)})
        if rc != 0:
            result["success"] = False
            result["error"] = err
            return _json(result)

        merge_ref = f"{remote}/{branch}"
        rc, out, err = _run_git("merge", "--ff-only", merge_ref, timeout=timeout)
        if rc == 0:
            result["steps"].append({"merge": "fast-forward", "output": _tail(out)})
        elif allow_merge_commit:
            rc2, out2, err2 = _run_git("merge", "--no-edit", merge_ref, timeout=timeout)
            if rc2 == 0:
                result["steps"].append({"merge": "merge-commit", "output": _tail(out2)})
            else:
                _run_git("merge", "--abort", timeout=120)
                result["steps"].append({"merge": "failed", "error": _tail(err2 or err)})
                result["success"] = False
                result["error"] = err2 or err
                return _json(result)
        else:
            result["steps"].append({"merge": "failed", "error": _tail(err)})
            result["success"] = False
            result["error"] = err
            return _json(result)
    finally:
        restore_ok, restore_status = _restore_stash(stash_ref)
        result["steps"].append({"stash_restore": restore_status})
        if not restore_ok:
            result["stash_restore_failed"] = True

    result["portable_repair"] = _repair_portable_surface(snapshot)
    result["current_commit"] = _current_commit()
    result["success"] = not result.get("stash_restore_failed", False)
    return _json(result)


UPDATE_SCHEMA = {
    "name": "update_hermes",
    "description": (
        "Update THE upstream Hermes Agent code from NousResearch/hermes-agent "
        "inside this Portable Hermes install, then preserve/reinstall this "
        "repo's custom tools, toolsets, extensions, guide, and portable launchers."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Upstream NousResearch branch to merge or overlay. Defaults to main.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum update runtime in seconds, 60-7200. Defaults to 1800.",
            },
            "allow_merge_commit": {
                "type": "boolean",
                "description": "Allow a non-fast-forward merge commit when needed. Defaults to true.",
            },
            "backup_branch": {
                "type": "boolean",
                "description": "Create a backup branch before merging upstream. Defaults to true.",
            },
            "reset_upstream": {
                "type": "boolean",
                "description": "Reset an existing wrong upstream remote to NousResearch. Defaults to false.",
            },
        },
    },
}

CHECK_UPDATES_SCHEMA = {
    "name": "check_hermes_updates",
    "description": (
        "Check whether THE upstream Hermes Agent has updates available from "
        "NousResearch/hermes-agent without applying them."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Upstream NousResearch branch to check. Defaults to main.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum check runtime in seconds, 30-600. Defaults to 120.",
            },
            "reset_upstream": {
                "type": "boolean",
                "description": "Reset an existing wrong upstream remote to NousResearch. Defaults to false.",
            },
        },
    },
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
