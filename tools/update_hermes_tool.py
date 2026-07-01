#!/usr/bin/env python3
"""
Portable Hermes update tools.

These tools intentionally update from the user's configured ``origin`` remote.
For portable-hermes-agent, ``origin`` should be
``https://github.com/aivrar/portable-hermes-agent.git``.  Do not merge the
upstream Hermes repository directly from a model-visible tool: upstream changes
are incorporated by maintainers, tested with the portable extensions, and then
shipped through this portable repo.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.registry import registry


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PORTABLE_REPO = "aivrar/portable-hermes-agent"


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


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


def _current_branch() -> str:
    rc, out, _ = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    if rc == 0 and out and out != "HEAD":
        return out
    return "main"


def _origin_url() -> str | None:
    rc, out, _ = _run_git("remote", "get-url", "origin")
    return out if rc == 0 and out else None


def _recent_origin_commits(branch: str, limit: int = 10) -> list[str]:
    rc, out, _ = _run_git("log", "--oneline", f"HEAD..origin/{branch}", f"-{limit}")
    if rc != 0 or not out:
        return []
    return out.splitlines()


def _run_update_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _tail(text: str | None, limit: int = 4000) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[-limit:]


def check_updates_handler(args: dict, **kwargs) -> str:
    """Check for portable repo updates without applying them."""
    branch = str(args.get("branch") or _current_branch() or "main").strip() or "main"

    if not _is_git_checkout():
        return _json(
            {
                "needs_update": None,
                "can_update": True,
                "update_source": _PORTABLE_REPO,
                "branch": branch,
                "reason": (
                    "This install has no .git directory. The safe update command "
                    "will use the portable ZIP fallback."
                ),
                "recommended_command": "hermes update --backup --yes",
            }
        )

    origin = _origin_url()
    if not origin:
        return _json(
            {
                "needs_update": None,
                "can_update": False,
                "branch": branch,
                "error": "No origin remote is configured for this checkout.",
            }
        )

    rc, _, err = _run_git("fetch", "origin", branch, "--quiet", timeout=60)
    if rc != 0:
        return _json(
            {
                "needs_update": None,
                "can_update": False,
                "update_source": origin,
                "branch": branch,
                "error": f"git fetch origin {branch} failed: {err}",
            }
        )

    rc, out, err = _run_git("rev-list", "--count", f"HEAD..origin/{branch}")
    if rc != 0:
        return _json(
            {
                "needs_update": None,
                "can_update": False,
                "update_source": origin,
                "branch": branch,
                "error": f"Could not compare HEAD to origin/{branch}: {err}",
            }
        )

    try:
        commits_behind = int(out or "0")
    except ValueError:
        commits_behind = 0

    rc, local, _ = _run_git("log", "--oneline", "-1")
    return _json(
        {
            "needs_update": commits_behind > 0,
            "can_update": True,
            "commits_behind": commits_behind,
            "current_commit": local if rc == 0 else "",
            "recent_origin": _recent_origin_commits(branch),
            "update_source": origin,
            "branch": branch,
            "recommended_command": "hermes update --backup --yes",
        }
    )


def update_hermes_handler(args: dict, **kwargs) -> str:
    """Run the normal Hermes updater against this portable repo's origin."""
    branch = str(args.get("branch") or "").strip()
    backup = bool(args.get("backup", True))
    assume_yes = bool(args.get("yes", True))
    timeout = int(args.get("timeout", 1800) or 1800)
    timeout = max(60, min(timeout, 7200))

    command = [sys.executable, "-m", "hermes_cli.main", "update"]
    if backup:
        command.append("--backup")
    else:
        command.append("--no-backup")
    if assume_yes:
        command.append("--yes")
    if branch:
        command.extend(["--branch", branch])

    try:
        result = _run_update_command(command, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return _json(
            {
                "success": False,
                "timed_out": True,
                "timeout_seconds": timeout,
                "command": command,
                "stdout": _tail(exc.stdout if isinstance(exc.stdout, str) else ""),
                "stderr": _tail(exc.stderr if isinstance(exc.stderr, str) else ""),
            }
        )
    except Exception as exc:
        return _json(
            {
                "success": False,
                "command": command,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    return _json(
        {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "command": command,
            "update_source": _origin_url() or _PORTABLE_REPO,
            "preserved_runtime_paths": [
                ".hermes/",
                ".hermes/custom_tools/",
                ".hermes/extensions/",
                "extensions/",
                "python_embedded/",
            ],
            "stdout": _tail(result.stdout),
            "stderr": _tail(result.stderr),
        }
    )


UPDATE_SCHEMA = {
    "name": "update_hermes",
    "description": (
        "Safely update Portable Hermes Agent from this installation's origin "
        "remote. Runs the normal 'hermes update --backup --yes' path so "
        "portable runtime folders and custom tools are preserved."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "backup": {
                "type": "boolean",
                "description": "Create pre-update backups first. Defaults to true.",
            },
            "yes": {
                "type": "boolean",
                "description": "Assume yes for updater prompts. Defaults to true.",
            },
            "branch": {
                "type": "string",
                "description": "Optional origin branch to update from. Defaults to main/current branch.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum update runtime in seconds, 60-7200. Defaults to 1800.",
            },
        },
    },
}

CHECK_UPDATES_SCHEMA = {
    "name": "check_hermes_updates",
    "description": (
        "Check whether Portable Hermes Agent has updates available from this "
        "installation's origin remote without applying them."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Optional origin branch to check. Defaults to main/current branch.",
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
