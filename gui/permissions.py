"""
Hermes Agent - Permissions System
Controls where the agent can read, write, install, execute, and access network.

Levels:
    0 = Disabled (nowhere)
    1 = App directory only (app folder and extensions)
    2 = App + User home directory (~/)
    3 = System-wide (anywhere on this computer)
    4 = System-wide + Admin (can modify system files, services, registry)

Default: read=2, write=1, install=1, execute=1, network=2
"""
import os
import json
from pathlib import Path
from typing import Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
_hermes_home = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
PERMISSIONS_FILE = _hermes_home / "permissions.json"

# ============================================================================
# Permission Definitions
# ============================================================================

PERMISSION_DEFS = {
    "read": {
        "name": "File Reading",
        "description": "Where the agent can read files from",
        "levels": {
            0: ("Disabled", "Agent cannot read any files"),
            1: ("App Only", "Can read files inside the Hermes app folder only"),
            2: ("App + Home", "Can read files in app folder and your user folder"),
            3: ("Anywhere", "Can read any file on your computer"),
            4: ("Anywhere + System", "Can read system files, configs, registry"),
        },
        "default": 2,
    },
    "write": {
        "name": "File Writing",
        "description": "Where the agent can create or modify files",
        "levels": {
            0: ("Disabled", "Agent cannot write any files"),
            1: ("App Only", "Can only write inside the Hermes app folder"),
            2: ("App + Home", "Can write in app folder and your user folder"),
            3: ("Anywhere", "Can write files anywhere on your computer"),
            4: ("Anywhere + System", "Can modify system files and configs"),
        },
        "default": 1,
    },
    "install": {
        "name": "Package Installation",
        "description": "Where pip/npm installs go",
        "levels": {
            0: ("Disabled", "Cannot install any packages"),
            1: ("App Only", "Installs into the portable Python only"),
            2: ("App + User", "Can install to portable Python and user packages"),
            3: ("System-wide", "Can install packages system-wide (pip install --global)"),
            4: ("System + Admin", "Can install system services, drivers, global tools"),
        },
        "default": 1,
    },
    "execute": {
        "name": "Command Execution",
        "description": "What commands the agent can run",
        "levels": {
            0: ("Disabled", "Cannot run any commands"),
            1: ("App Only", "Can only run commands inside the app folder"),
            2: ("App + Safe", "Can run commands anywhere but no admin/system changes"),
            3: ("Unrestricted", "Can run any command on your computer"),
            4: ("Admin", "Can run elevated/admin commands (use with caution)"),
        },
        "default": 2,
    },
    "remove": {
        "name": "File Deletion",
        "description": "Where the agent can delete files",
        "levels": {
            0: ("Disabled", "Cannot delete any files"),
            1: ("App Only", "Can only delete files inside the Hermes app folder"),
            2: ("App + Home", "Can delete in app folder and your user folder"),
            3: ("Anywhere", "Can delete any file on your computer"),
            4: ("Anywhere + System", "Can delete system files (dangerous!)"),
        },
        "default": 1,
    },
    "network": {
        "name": "Network Access",
        "description": "What the agent can access on the network",
        "levels": {
            0: ("Offline", "No network access at all"),
            1: ("Local Only", "Can only access localhost services (LM Studio, extensions)"),
            2: ("Web + APIs", "Can browse web, call APIs, search (normal usage)"),
            3: ("Full Network", "Can access any network resource, SSH, etc."),
            4: ("Full + Listen", "Can open ports, start servers, accept connections"),
        },
        "default": 2,
    },
}

# Allowed paths per level
def _get_allowed_paths(level: int) -> list:
    """Return list of allowed base paths for a given level."""
    paths = []
    if level >= 1:
        paths.append(str(PROJECT_ROOT))
        paths.append(str(_hermes_home))
        paths.append(str(PROJECT_ROOT / "extensions"))
    if level >= 2:
        paths.append(str(Path.home()))
    if level >= 3:
        paths.append("")  # Empty = anywhere
    return paths


def _is_path_allowed(filepath: str, level: int) -> bool:
    """Check if a file path is allowed under the given permission level."""
    if level <= 0:
        return False
    if level >= 3:
        return True

    filepath = str(Path(filepath).resolve())
    allowed = _get_allowed_paths(level)
    return any(filepath.startswith(p) for p in allowed if p)


# ============================================================================
# Load / Save
# ============================================================================

def load_permissions() -> Dict[str, int]:
    """Load permissions from file, or return defaults."""
    defaults = {k: v["default"] for k, v in PERMISSION_DEFS.items()}

    if PERMISSIONS_FILE.exists():
        try:
            with open(PERMISSIONS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # Merge with defaults (in case new permissions are added)
            for k in defaults:
                if k in saved:
                    defaults[k] = int(saved[k])
            return defaults
        except Exception:
            pass

    return defaults


def save_permissions(perms: Dict[str, int]):
    """Save permissions to file."""
    PERMISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PERMISSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(perms, f, indent=2)


def get_permission(name: str) -> int:
    """Get a single permission level."""
    perms = load_permissions()
    return perms.get(name, PERMISSION_DEFS.get(name, {}).get("default", 1))


def get_level_name(perm_name: str, level: int) -> str:
    """Get human-readable name for a permission level."""
    defn = PERMISSION_DEFS.get(perm_name, {})
    levels = defn.get("levels", {})
    return levels.get(level, ("Unknown", ""))[0]


def get_level_description(perm_name: str, level: int) -> str:
    """Get description for a permission level."""
    defn = PERMISSION_DEFS.get(perm_name, {})
    levels = defn.get("levels", {})
    return levels.get(level, ("", "Unknown"))[1]


# ============================================================================
# Enforcement
# ============================================================================

def check_read_allowed(filepath: str) -> bool:
    return _is_path_allowed(filepath, get_permission("read"))


def check_write_allowed(filepath: str) -> bool:
    return _is_path_allowed(filepath, get_permission("write"))


def check_remove_allowed(filepath: str) -> bool:
    return _is_path_allowed(filepath, get_permission("remove"))


def check_execute_allowed(cwd: str = "") -> bool:
    level = get_permission("execute")
    if level <= 0:
        return False
    if level >= 2:
        return True
    # Level 1: only in app directory
    if cwd:
        return _is_path_allowed(cwd, 1)
    return True


def check_network_allowed(host: str = "") -> bool:
    level = get_permission("network")
    if level <= 0:
        return False
    if level == 1:
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "")
    return True


def check_install_allowed() -> int:
    """Return install permission level."""
    return get_permission("install")


def get_permissions_summary() -> str:
    """Human-readable permissions summary for the agent's system prompt."""
    perms = load_permissions()
    lines = ["## Your Permissions (what you're allowed to do)\n"]
    for key, defn in PERMISSION_DEFS.items():
        level = perms.get(key, defn["default"])
        name = defn["name"]
        level_name, level_desc = defn["levels"].get(level, ("?", "?"))
        lines.append(f"- **{name}**: {level_name} (level {level}) — {level_desc}")
    lines.append("")
    lines.append("If a user asks you to do something outside your permissions, "
                "explain what you can't do and suggest they adjust permissions "
                "in File > Permissions.")
    return "\n".join(lines)
