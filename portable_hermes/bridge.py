"""Offer the portable tools in upstream's default tool selection, in memory.

The wrapper never edits an upstream file. The portable tool modules
(``tools/lm_studio_tools.py`` and friends) register themselves with upstream's
tool registry like any built-in tool, which is enough for the GUI: it builds
its agent with ``enabled_toolsets=None`` (every toolset). The CLI is different
on every core this wrapper has run on: it selects toolsets through
``hermes_cli.tools_config._get_platform_tools(config, "cli")``, which only
recovers *static* entries of ``toolsets.TOOLSETS`` whose tools are listed in
the ``hermes-cli`` composite. Registry-only toolsets are never selected there,
and on the in-repo core that selection runs before tool discovery.

Today's upstream also hides every tool that is not in
``toolsets._HERMES_CORE_TOOLS`` behind its ``tool_search`` bridge ("plugin
tools are deferred"), so the model only sees the portable tools if it searches.

So after upstream's ``toolsets`` module has executed, :func:`augment` adds the
portable tool names to ``_HERMES_CORE_TOOLS`` (where the fork's old text patch
put them), adds the portable toolsets to ``TOOLSETS`` and appends the portable
tool names to the ``hermes-*`` composites built from the core tool list. It
runs from a meta-path
hook installed at interpreter start by a ``.pth`` line in the product
interpreter's site-packages (see :func:`ensure_pth`), so it also covers child
processes such as upstream's gateway daemon. Every step fails soft and logs.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("portable_hermes.bridge")

#: The install root this copy of the wrapper belongs to.
ROOT = Path(__file__).resolve().parent.parent

PTH_NAME = "portable_hermes_hook.pth"
NO_HOOK_ENV = "PORTABLE_HERMES_NO_HOOK"

PORTABLE_TOOLSETS: dict[str, dict] = {
    "run_python": {
        "description": "Execute Python code through the portable Python runtime",
        "tools": ["run_python"],
    },
    "gpu": {
        "description": "NVIDIA GPU status: memory, temperature, and utilization",
        "tools": ["gpu_info"],
    },
    "model_switcher": {
        "description": "Switch the active model/provider configuration",
        "tools": ["switch_model"],
    },
    "lm_studio": {
        "description": "LM Studio local model control and model library tools",
        "tools": [
            "lm_studio_status", "lm_studio_models", "lm_studio_load",
            "lm_studio_unload", "lm_studio_search", "lm_studio_download",
            "lm_studio_model_info", "lm_studio_tokenize",
            "lm_studio_embed", "lm_studio_chat",
        ],
    },
    "music": {
        "description": "Portable music generation server tools",
        "tools": [
            "music_status", "music_generate", "music_models",
            "music_model_load", "music_model_unload", "music_outputs",
            "music_install",
        ],
    },
    "extension_tts": {
        "description": "Portable TTS server tools for local voice models",
        "tools": [
            "tts_server_status", "tts_server_generate", "tts_server_models",
            "tts_server_model_load", "tts_server_model_unload",
            "tts_server_voices", "tts_server_jobs",
        ],
    },
    "comfyui": {
        "description": "Portable ComfyUI image generation and instance tools",
        "tools": [
            "comfyui_status", "comfyui_instances", "comfyui_instance_start",
            "comfyui_instance_stop", "comfyui_generate", "comfyui_models",
            "comfyui_nodes",
        ],
    },
    "hermes_update": {
        "description": "Check for and install upstream Hermes core updates for Portable Hermes",
        "tools": ["update_hermes", "check_hermes_updates"],
    },
    "tool_maker": {
        "description": "Create, delete, and list runtime custom tools",
        "tools": ["create_tool", "delete_tool", "list_custom_tools"],
    },
    "workflows": {
        "description": "Create, run, schedule, and manage multi-step workflows",
        "tools": [
            "workflow_create", "workflow_run", "workflow_list",
            "workflow_delete", "workflow_show", "workflow_schedule",
        ],
    },
    "serper": {
        "description": "Google-quality search through Serper.dev",
        "tools": ["serper_search"],
    },
    "guide": {
        "description": "Search the built-in Portable Hermes Agent guide",
        "tools": ["search_guide"],
    },
}

PORTABLE_TOOLS: tuple[str, ...] = tuple(
    tool for spec in PORTABLE_TOOLSETS.values() for tool in spec["tools"]
)

_APPLIED_FLAG = "_portable_hermes_augmented"


def augment(module) -> list[str]:
    """Add the portable toolsets to a loaded ``toolsets`` module.

    Idempotent and never raises. Returns a short list of what changed.
    Toolset names upstream already defines are left untouched.
    """
    changes: list[str] = []
    try:
        toolsets = getattr(module, "TOOLSETS", None)
        if not isinstance(toolsets, dict):
            logger.warning("portable toolsets not added: toolsets.TOOLSETS is %s",
                           type(toolsets).__name__)
            return changes
        seen: set[int] = set()
        # Core tool list: upstream reads it lazily to decide which tools are
        # "core" (never deferred behind the tool_search bridge, kept by the
        # memory manager). The portable tools were core tools in the fork.
        core = getattr(module, "_HERMES_CORE_TOOLS", None)
        missing_core = [t for t in PORTABLE_TOOLS if core is not None and t not in core]
        if isinstance(core, list):
            seen.add(id(core))
            if missing_core:
                core.extend(missing_core)
                changes.append("core-tools")
        elif isinstance(core, (tuple, set, frozenset)) and missing_core:
            merged = list(core) + missing_core
            setattr(module, "_HERMES_CORE_TOOLS", type(core)(merged))
            changes.append("core-tools")
        elif core is None:
            logger.warning("portable tools not marked core: toolsets._HERMES_CORE_TOOLS missing")
        for name, spec in PORTABLE_TOOLSETS.items():
            if name in toolsets:
                continue
            toolsets[name] = {
                "description": spec["description"],
                "tools": list(spec["tools"]),
                "includes": [],
            }
            changes.append(f"toolset:{name}")
        for name, spec in list(toolsets.items()):
            if not name.startswith("hermes-") or not isinstance(spec, dict):
                continue
            tools = spec.get("tools")
            if not isinstance(tools, list) or "terminal" not in tools or id(tools) in seen:
                continue
            seen.add(id(tools))
            missing = [tool for tool in PORTABLE_TOOLS if tool not in tools]
            if missing:
                tools.extend(missing)
                changes.append(f"composite:{name}")
        memo = getattr(module, "_resolve_toolset_memo", None)
        if isinstance(memo, dict):
            memo.clear()
        setattr(module, _APPLIED_FLAG, True)
        logger.debug("portable toolsets applied: %s", ", ".join(changes) or "nothing to do")
    except Exception as exc:  # fail soft: the agent still runs without them
        logger.warning("portable toolsets not added: %s: %s", type(exc).__name__, exc)
    return changes


class _AugmentingLoader(importlib.abc.Loader):
    def __init__(self, inner):
        self._inner = inner

    def create_module(self, spec):
        create = getattr(self._inner, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module):
        self._inner.exec_module(module)
        augment(module)

    def __getattr__(self, name):  # get_source, get_code, get_filename, ...
        return getattr(self._inner, name)


class _ToolsetsFinder(importlib.abc.MetaPathFinder):
    """Wraps the loader of *this install's* ``toolsets`` module."""

    portable_hermes_bridge = True

    def find_spec(self, fullname, path, target=None):
        if fullname != "toolsets":
            return None
        try:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None or not spec.origin or spec.loader is None:
                return None
            if Path(spec.origin).resolve().parent != ROOT:
                return None
            spec.loader = _AugmentingLoader(spec.loader)
            return spec
        except Exception as exc:
            logger.warning("portable toolsets hook skipped: %s", exc)
            return None


def install_hook() -> bool:
    """Make the next import of ``toolsets`` apply :func:`augment`.

    If ``toolsets`` is already imported from this install, augment it now.
    """
    try:
        loaded = sys.modules.get("toolsets")
        if loaded is not None:
            origin = getattr(loaded, "__file__", None)
            if origin and Path(origin).resolve().parent == ROOT:
                augment(loaded)
            return True
        if not any(getattr(f, "portable_hermes_bridge", False) for f in sys.meta_path):
            sys.meta_path.insert(0, _ToolsetsFinder())
        return True
    except Exception as exc:
        logger.warning("portable toolsets hook not installed: %s", exc)
        return False


def remove_hooks() -> None:
    """Drop every bridge finder (used when verifying a different tree)."""
    sys.meta_path[:] = [f for f in sys.meta_path
                        if not getattr(f, "portable_hermes_bridge", False)]


def pth_line() -> str:
    """The single ``.pth`` line that installs the hook at interpreter start."""
    return (
        "import os, sys; exec(\"try:\\n"
        f" if not os.environ.get('{NO_HOOK_ENV}'):\\n"
        "  import portable_hermes.bridge as _phb; _phb.install_hook()\\n"
        "except Exception:\\n pass\")\n"
    )


def site_packages(python_dir: Path | None = None) -> Path | None:
    """The product interpreter's site-packages (``python_embedded``)."""
    base = Path(python_dir) if python_dir else ROOT / "python_embedded"
    candidate = base / "Lib" / "site-packages"
    return candidate if candidate.is_dir() else None


def ensure_pth(target_dir: Path | None = None) -> str:
    """Write the hook ``.pth`` into *target_dir* (default: python_embedded).

    Returns ``"ok"``, ``"written"`` or a reason string when nothing was done.
    """
    target = Path(target_dir) if target_dir else site_packages()
    if target is None:
        return "no python_embedded site-packages"
    path = target / PTH_NAME
    line = pth_line()
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == line:
            return "ok"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(line, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        return "written"
    except OSError as exc:
        return f"could not write {path}: {exc}"


PROJECT_PTH_NAME = "hermes_project.pth"


def ensure_project_pth(target_dir: Path | None = None) -> str:
    """Point ``hermes_project.pth`` at this install root.

    install.bat writes it once with an absolute path, so a portable folder
    that was moved or renamed would import from the old location. Only an
    existing file is rewritten, and only when it names a different folder.
    """
    target = Path(target_dir) if target_dir else site_packages()
    if target is None:
        return "no python_embedded site-packages"
    path = target / PROJECT_PTH_NAME
    try:
        if not path.is_file():
            return "absent"
        current = path.read_text(encoding="utf-8", errors="replace").strip()
        try:
            same = bool(current) and Path(current).resolve() == ROOT
        except OSError:
            same = False
        if same:
            return "ok"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(str(ROOT) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return "written"
    except OSError as exc:
        return f"could not write {path}: {exc}"
