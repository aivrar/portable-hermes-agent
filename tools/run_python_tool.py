#!/usr/bin/env python3
"""
Run Python Tool — Execute Python code directly via stdin pipe.

Bypasses shell escaping and the Windows 8191-char command-line limit by
piping code to python.exe via stdin.  Uses the project's embedded Python
(python_embedded/python.exe) when available, falling back to system python.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from tools.registry import registry

logger = logging.getLogger(__name__)

# Max output size to return (bytes)
_MAX_OUTPUT = 50 * 1024  # 50 KB

# Locate the best python executable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_EMBEDDED_PYTHON = _PROJECT_ROOT / "python_embedded" / "python.exe"


def _get_python_exe() -> str:
    """Return the path to the python executable to use."""
    if _EMBEDDED_PYTHON.exists():
        return str(_EMBEDDED_PYTHON)
    return sys.executable


def _check_python() -> bool:
    """Check that a usable python.exe exists."""
    exe = _get_python_exe()
    return os.path.isfile(exe)


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n... (truncated, {len(text)} bytes total)"
    return text


def run_python_handler(args: dict, **kwargs) -> str:
    """Execute Python code via stdin pipe and return stdout/stderr."""
    code = args.get("code", "")
    if not code.strip():
        return json.dumps({"error": "No code provided"})

    timeout = min(int(args.get("timeout", 60)), 300)  # cap at 5 min
    exe = _get_python_exe()

    try:
        result = subprocess.run(
            [exe, "-u", "-"],
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_PROJECT_ROOT),
        )
        return json.dumps({
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
            "returncode": result.returncode,
        }, ensure_ascii=False)

    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Execution timed out after {timeout}s"})
    except Exception as e:
        return json.dumps({"error": f"Failed to run python: {e}"})


# ---------------------------------------------------------------------------
# Schema & Registration
# ---------------------------------------------------------------------------
RUN_PYTHON_SCHEMA = {
    "name": "run_python",
    "description": (
        "Execute Python code directly. Code is piped to the Python interpreter via stdin — "
        "no shell involved, no escaping issues. Use this instead of terminal for Python scripts. "
        "Returns stdout, stderr, and return code."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max execution time in seconds (default 60, max 300).",
            },
        },
        "required": ["code"],
    },
}

registry.register(
    name="run_python",
    toolset="run_python",
    schema=RUN_PYTHON_SCHEMA,
    handler=run_python_handler,
    check_fn=_check_python,
)
