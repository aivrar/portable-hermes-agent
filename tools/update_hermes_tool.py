#!/usr/bin/env python3
"""Model-visible update tools for Portable Hermes Agent.

``update_hermes`` and ``check_hermes_updates`` are thin callers of the
wrapper-owned core lifecycle (``python -m portable_hermes core ...``). The
lifecycle fetches NousResearch/hermes-agent as a source archive, installs its
dependencies, verifies it in a fresh process, swaps files with rollback and
records what it installed. The portable tools are never patched into upstream
files; ``portable_hermes.bridge`` offers them to the agent at runtime.

The portable wrapper itself (launchers, GUI, these tools) is updated from the
aivrar/portable-hermes-agent releases by ``UPDATE.bat``, a separate channel
(in a git clone of that repository: ``git pull``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.registry import registry

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RESTART = "Restart Hermes (close and reopen the GUI or CLI) to load the new core."


def _interpreter() -> str:
    embedded = _PROJECT_ROOT / "python_embedded" / "python.exe"
    return str(embedded) if embedded.is_file() else sys.executable


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _run_portable(args: list[str], timeout: int) -> dict[str, Any]:
    """Run ``python -m portable_hermes <args> --json`` and parse its result."""
    from portable_hermes.common import clean_python_env, module_command
    try:
        completed = subprocess.run(
            module_command(_interpreter(), _PROJECT_ROOT, *args, "--json"),
            cwd=str(_PROJECT_ROOT), env=clean_python_env(), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "timeout",
                "reason": f"stopped after {timeout}s; any unfinished file swap is rolled "
                          "back the next time Hermes starts"}
    except OSError as exc:
        return {"ok": False, "code": "spawn_failed", "reason": str(exc)}
    for line in reversed((completed.stdout or "").splitlines()):
        if line.startswith("PORTABLE_RESULT "):
            try:
                return json.loads(line.split(" ", 1)[1])
            except ValueError:
                break
    tail = ((completed.stderr or "") + (completed.stdout or "")).strip()[-1500:]
    return {"ok": False, "code": "no_result",
            "reason": f"portable updater exited {completed.returncode}: {tail}"}


def update_hermes_handler(args: dict, **kwargs) -> str:
    args = args or {}
    timeout = _clamp(args.get("timeout"), 60, 7200, 1800)
    branch = str(args.get("branch") or "").strip()
    command = ["core", "update"]
    if branch and branch != "main":
        command += ["--ref", branch]
    result = _run_portable(command, timeout)
    if result.get("ok"):
        changed = result.get("changed", True)
        payload = {
            "success": True,
            "updated": bool(changed),
            "kept_edits": result.get("kept_edits"),
            "warnings": result.get("warnings") or None,
            "repository": result.get("repository", "NousResearch/hermes-agent"),
            "commit": result.get("commit"),
            "message": result.get("message"),
            "dependencies": result.get("dependencies"),
            "files_written": result.get("files_written"),
            "files_removed": result.get("files_removed"),
        }
        if result.get("fallback"):
            payload["fallback"] = result["fallback"]
        if result.get("kept_edits_count"):
            from portable_hermes.common import kept_sentence
            payload["kept_note"] = kept_sentence(result)
        if changed:
            payload["restart_required"] = True
            payload["next_step"] = _RESTART
        return json.dumps(payload, default=str)
    payload = {"success": False, "error": result.get("reason"), "code": result.get("code")}
    if result.get("code") == "runtime_too_old":
        # The portable Python cannot be swapped by a process running from it.
        from portable_hermes.core import runtime_too_old_sentence
        needed = runtime_too_old_sentence(result.get("current_python"),
                                          result.get("target_python"),
                                          result.get("requires_python"))
        payload["next_step"] = (
            f"{needed} Close Hermes and "
            "run UPDATE.bat --core: it upgrades the portable Python in place (keeping "
            "everything in this folder) and then installs the core. This cannot be done "
            "from inside a running Hermes.")
        payload["note"] = "Nothing was changed."
    elif result.get("dependencies_restored") is False:
        payload["note"] = ("The previous core's files were kept, but its Python packages could "
                           "not all be put back. Run UPDATE.bat to finish.")
    elif result.get("kept_existing_core"):
        payload["note"] = "The existing core was kept unchanged."
    return json.dumps(payload, default=str)


def check_updates_handler(args: dict, **kwargs) -> str:
    args = args or {}
    timeout = _clamp(args.get("timeout"), 30, 600, 120)
    branch = str(args.get("branch") or "").strip()
    core = _run_portable(["core", "check"] + (["--ref", branch] if branch else []), timeout)
    wrapper = _run_portable(["wrapper", "check"], timeout)
    lines = []
    if core.get("update_available") is False:
        lines.append("Core: up to date.")
    elif core.get("update_available"):
        behind = core.get("behind_by")
        lines.append(f"Core: {behind} upstream commits behind." if isinstance(behind, int)
                     else "Core: an upstream update is available.")
    else:
        lines.append(f"Core: could not check ({core.get('network_error') or core.get('reason')}).")
    if wrapper.get("install_type") == "git":
        lines.append("Portable wrapper: git checkout, update it with git pull.")
    elif wrapper.get("update_available"):
        lines.append(f"Portable wrapper: {wrapper.get('latest_version')} is available "
                     f"(installed {wrapper.get('installed_version') or 'unknown'}); run UPDATE.bat.")
    elif wrapper.get("update_available") is False:
        lines.append("Portable wrapper: " + (wrapper.get("message") or "up to date") + ".")
    else:
        lines.append("Portable wrapper: could not check "
                     f"({wrapper.get('network_error') or wrapper.get('reason')}).")
    return json.dumps({
        "success": bool(core.get("ok", False)),
        "summary": " ".join(lines),
        "core": core,
        "wrapper": wrapper,
    }, default=str)


_COMPAT = "Ignored; accepted for compatibility with older callers."

UPDATE_SCHEMA = {
    "name": "update_hermes",
    "description": (
        "Update the upstream Hermes Agent core (NousResearch/hermes-agent) inside this "
        "Portable Hermes install: download it, install its dependencies, verify it in a "
        "fresh process, then swap it in with automatic rollback on failure. Portable tools, "
        "the GUI and user data are kept. Hermes must be restarted afterwards."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Upstream branch, tag or commit to install. Defaults to main.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum update runtime in seconds, 60-7200. Defaults to 1800.",
            },
            "allow_merge_commit": {"type": "boolean", "description": _COMPAT},
            "backup_branch": {"type": "boolean", "description": _COMPAT},
            "reset_upstream": {"type": "boolean", "description": _COMPAT},
        },
    },
}

CHECK_UPDATES_SCHEMA = {
    "name": "check_hermes_updates",
    "description": (
        "Check, without changing anything, how far the installed upstream Hermes core is "
        "behind NousResearch/hermes-agent main, and whether a newer Portable Hermes release "
        "is published."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Upstream branch to compare against. Defaults to main.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum check runtime in seconds, 30-600. Defaults to 120.",
            },
            "reset_upstream": {"type": "boolean", "description": _COMPAT},
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
