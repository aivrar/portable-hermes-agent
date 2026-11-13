"""Verify a Portable Hermes tree in a fresh process.

Run with the product interpreter::

    python -m portable_hermes.verify --root <tree> [--json] [--no-gui]

The caller (the core/wrapper updaters) runs this with a scrubbed environment
(no API keys), a throw-away ``HERMES_HOME`` and ``PORTABLE_HERMES_NO_HOOK=1``
so the tree under test, not the live install, provides every module.

Each check reports a precise reason. Exit status 0 means every check passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path


def _isolate(root: Path) -> None:
    """Put *root* first on sys.path and drop other Hermes trees from it."""
    root_s = str(root)
    cleaned = []
    for entry in sys.path:
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            cleaned.append(entry)
            continue
        if resolved == root:
            continue
        # Another Hermes tree (for example the live install while a staged
        # copy is verified) must not satisfy imports for the tree under test.
        if (resolved / "run_agent.py").is_file() or (resolved / "portable_hermes").is_dir():
            continue
        cleaned.append(entry)
    sys.path[:] = [root_s] + cleaned
    for name in [n for n in sys.modules if n == "portable_hermes" or n.startswith("portable_hermes.")]:
        if name != __name__:
            del sys.modules[name]


class Checks:
    def __init__(self):
        self.results: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append({"name": name, "ok": bool(ok), "detail": detail})
        return ok

    def run(self, name: str, fn) -> bool:
        try:
            ok, detail = fn()
        except BaseException as exc:  # noqa: BLE001 - report, never crash
            if isinstance(exc, KeyboardInterrupt):
                raise
            tb = traceback.extract_tb(exc.__traceback__)
            where = f" at {Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
            return self.add(name, False, f"{type(exc).__name__}: {exc}{where}")
        return self.add(name, ok, detail)

    @property
    def ok(self) -> bool:
        return all(r["ok"] for r in self.results)

    def first_failure(self) -> str:
        for r in self.results:
            if not r["ok"]:
                return f"{r['name']}: {r['detail']}"
        return ""


def verify(root: Path, *, gui: bool = True) -> dict:
    root = Path(root).resolve()
    if not os.environ.get("HERMES_HOME"):
        os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="portable-verify-home-")
    _isolate(root)
    checks = Checks()

    from portable_hermes import bridge, core as core_mod

    def python_requires():
        pyproject = root / "pyproject.toml"
        if not pyproject.is_file():
            return False, "pyproject.toml missing"
        spec = core_mod.read_project(pyproject).get("requires-python", "")
        ok = core_mod.specifier_matches(spec, core_mod.marker_environment()["python_full_version"])
        return ok, f"requires-python {spec!r} vs Python {sys.version.split()[0]}"

    checks.run("python_requires", python_requires)

    bridge.remove_hooks()
    bridge.install_hook()

    def core_imports():
        import importlib
        for name in ("hermes_constants", "hermes_cli.config", "hermes_state",
                     "tools.registry", "toolsets", "model_tools"):
            importlib.import_module(name)
        from run_agent import AIAgent  # noqa: F401
        import run_agent
        origin = Path(run_agent.__file__).resolve()
        if root not in origin.parents:
            return False, f"run_agent imported from {origin}, not from the tree under test"
        return True, "run_agent.AIAgent, model_tools, toolsets, hermes_cli.config, hermes_state"

    if not checks.run("core_imports", core_imports):
        return _result(root, checks)

    expected = set(bridge.PORTABLE_TOOLS)

    def portable_tools_registered():
        from tools.registry import registry
        names = set(registry.get_all_tool_names())
        missing = sorted(expected - names)
        if missing:
            return False, "not registered by tool discovery: " + ", ".join(missing)
        return True, f"{len(expected)} portable tools registered"

    if not checks.run("portable_tools_registered", portable_tools_registered):
        return _result(root, checks)

    def available_portable():
        from tools.registry import registry
        return {d["function"]["name"] for d in registry.get_definitions(expected, quiet=True)}

    def cli_selection():
        import toolsets
        from hermes_cli.config import load_config
        from hermes_cli.tools_config import _get_platform_tools
        if not getattr(toolsets, "_portable_hermes_augmented", False):
            return False, "portable toolsets bridge did not run for toolsets.py"
        selected = _get_platform_tools(load_config(), "cli")
        names = set()
        for ts in selected:
            names.update(toolsets.resolve_toolset(ts))
        missing = sorted(expected - names)
        if missing:
            return False, "not in the default CLI selection: " + ", ".join(missing)
        from model_tools import get_tool_definitions
        defs = {d["function"]["name"] for d in
                get_tool_definitions(enabled_toolsets=sorted(selected), quiet_mode=True)}
        offered = available_portable()
        lost = sorted(offered - defs)
        if lost:
            return False, "selected but missing from CLI tool definitions: " + ", ".join(lost)
        return True, f"{len(expected)} selected; {len(offered & defs)} offered (others need their service)"

    checks.run("cli_selection", cli_selection)

    def gui_selection():
        # Build the agent the way gui/agent_bridge.py does, with a dummy local
        # endpoint (nothing is contacted while constructing it).
        from run_agent import AIAgent
        agent = AIAgent(model="portable-verify", provider="custom",
                        base_url="http://127.0.0.1:9/v1", api_key="portable-verify",
                        quiet_mode=True, platform="gui", skip_context_files=True,
                        disabled_toolsets=["code_execution"], max_iterations=1)
        defs = {t["function"]["name"] for t in (getattr(agent, "tools", None) or [])}
        offered = available_portable()
        lost = sorted(offered - defs)
        if lost:
            return False, "missing from the GUI agent's tools: " + ", ".join(lost)
        if not offered:
            return False, "no portable tool is available to the GUI"
        return True, f"{len(offered)} portable tools offered to AIAgent(platform='gui')"

    checks.run("gui_selection", gui_selection)

    if gui:
        def gui_modules():
            import importlib
            import tkinter  # noqa: F401
            for name in ("gui.i18n", "gui.theme", "gui.agent_bridge", "gui.app"):
                importlib.import_module(name)
            return True, "tkinter, gui.app, gui.agent_bridge"

        checks.run("gui_modules", gui_modules)

    return _result(root, checks)


def _result(root: Path, checks: Checks) -> dict:
    return {
        "ok": checks.ok,
        "root": str(root),
        "python": sys.version.split()[0],
        "reason": checks.first_failure(),
        "checks": checks.results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m portable_hermes.verify")
    parser.add_argument("--root", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args(argv)
    # Tool modules print to stdout while importing; keep the JSON channel clean.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        result = verify(Path(args.root), gui=not args.no_gui)
    finally:
        sys.stdout = real_stdout
    if args.json:
        print("PORTABLE_VERIFY_RESULT " + json.dumps(result))
    else:
        for check in result["checks"]:
            mark = "ok  " if check["ok"] else "FAIL"
            print(f"[{mark}] {check['name']}: {check['detail']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
