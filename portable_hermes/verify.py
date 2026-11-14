"""Verify a Portable Hermes tree in a fresh process.

Run with the product interpreter::

    python -m portable_hermes.verify --root <tree> [--json] [--no-gui]

The caller (the core/wrapper updaters) runs this with a scrubbed environment
(no API keys), a throw-away ``HERMES_HOME`` and ``PORTABLE_HERMES_NO_HOOK=1``
so the tree under test, not the live install, provides every module.

Each check reports a precise reason. Exit status 0 means every check passed.
A check can also pass with a visible warning (for example when a private
upstream API the CLI probe relies on is gone).

The wrapper's needs are derived, not hand-listed: every import of a core
module in the wrapper's own Python files (``gui/`` and the portable tool
modules), including imports inside functions, is checked against the tree
under test, and every keyword ``gui/agent_bridge.py`` passes to ``AIAgent`` is
checked against its signature. Imports inside a ``try`` that handles
``ImportError``/``Exception`` are optional by design and skipped.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
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

    def add(self, name: str, ok: bool, detail: str = "", warning: bool = False) -> bool:
        entry = {"name": name, "ok": bool(ok), "detail": detail}
        if warning:
            entry["warning"] = True
        self.results.append(entry)
        return ok

    def run(self, name: str, fn) -> bool:
        try:
            outcome = fn()
        except BaseException as exc:  # noqa: BLE001 - report, never crash
            if isinstance(exc, KeyboardInterrupt):
                raise
            tb = traceback.extract_tb(exc.__traceback__)
            where = f" at {Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
            return self.add(name, False, f"{type(exc).__name__}: {exc}{where}")
        ok, detail = outcome[0], outcome[1]
        return self.add(name, ok, detail, warning=len(outcome) > 2 and bool(outcome[2]))

    @property
    def warnings(self) -> list[str]:
        return [f"{r['name']}: {r['detail']}" for r in self.results if r.get("warning")]

    @property
    def ok(self) -> bool:
        return all(r["ok"] for r in self.results)

    def first_failure(self) -> str:
        for r in self.results:
            if not r["ok"]:
                return f"{r['name']}: {r['detail']}"
        return ""


# --------------------------------------------------------------------------
# the wrapper's contract with the core, derived from its own source
# --------------------------------------------------------------------------

_GUARDS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _handles_import_errors(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    for node in nodes:
        name = node.id if isinstance(node, ast.Name) else \
            node.attr if isinstance(node, ast.Attribute) else None
        if name in _GUARDS:
            return True
    return False


def required_imports(tree: ast.AST) -> list[tuple[int, str, list[str] | None]]:
    """Absolute imports that are not optional: ``(line, module, names or None)``.

    Function-level imports count. Imports in the body of a ``try`` with an
    ``ImportError``/``Exception``/bare handler are optional and skipped.
    """
    found: list[tuple[int, str, list[str] | None]] = []
    try_types = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)

    def visit(node, guarded: bool) -> None:
        if isinstance(node, try_types):
            body_guarded = guarded or any(_handles_import_errors(h) for h in node.handlers)
            for child in node.body:
                visit(child, body_guarded)
            for handler in node.handlers:
                for child in handler.body:
                    visit(child, guarded)
            for child in list(node.orelse) + list(node.finalbody):
                visit(child, guarded)
            return
        if isinstance(node, ast.Import) and not guarded:
            for alias in node.names:
                found.append((node.lineno, alias.name, None))
        elif isinstance(node, ast.ImportFrom) and not guarded and node.level == 0 \
                and node.module:
            found.append((node.lineno, node.module, [a.name for a in node.names]))
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(tree, False)
    return found


def wrapper_python_files(root: Path) -> list[Path]:
    """The wrapper's own Python files that run inside Hermes."""
    from portable_hermes import ownership
    root = Path(root)
    files = sorted((root / "gui").rglob("*.py")) if (root / "gui").is_dir() else []
    for rel in sorted(ownership.WRAPPER_CORE_TREE_FILES):
        if rel.startswith("tools/") and rel.endswith(".py") and (root / rel).is_file():
            files.append(root / rel)
    return files


def _module_file(root: Path, module: str) -> Path | None:
    rel = module.replace(".", "/")
    for cand in (f"{rel}.py", f"{rel}/__init__.py"):
        if (root / cand).is_file():
            return root / cand
    return None


def _is_core_module(root: Path, module: str) -> bool:
    from portable_hermes import ownership
    found = _module_file(root, module)
    if found is not None:
        return ownership.classify(found.relative_to(root).as_posix()) == "core"
    top = module.split(".")[0]
    top_file = _module_file(root, top)
    if top_file is not None:
        return ownership.classify(top_file.relative_to(root).as_posix()) == "core"
    return (root / top).is_dir() and ownership.classify(f"{top}/__init__.py") == "core"


def _top_level_names(path: Path) -> set[str]:
    """Names a module defines at module level (static; no import)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()

    def targets(node):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                targets(elt)

    def scan(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    targets(target)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets(node.target)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.If):
                scan(node.body)
                scan(node.orelse)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                scan(node.body)
            elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
                scan(node.body)
                for handler in node.handlers:
                    scan(handler.body)
                scan(node.orelse)
                scan(node.finalbody)
    scan(tree.body)
    return names


def check_import_contract(root: Path) -> tuple[bool, str]:
    """Every name the wrapper imports from the core exists in the tree."""
    root = Path(root)
    problems, checked = [], 0
    defined: dict[str, set[str]] = {}
    for path in wrapper_python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{rel} does not parse: {exc}")
            continue
        for line, module, names in required_imports(tree):
            if not _is_core_module(root, module):
                continue
            checked += 1
            source = _module_file(root, module)
            if source is None:
                problems.append(f"{rel}:{line} imports {module}, which this core does not have")
                continue
            for name in names or []:
                if name == "*" or _module_file(root, f"{module}.{name}") is not None:
                    continue
                if module not in defined:
                    try:
                        defined[module] = _top_level_names(source)
                    except (OSError, SyntaxError, ValueError):
                        defined[module] = set()
                if name in defined[module]:
                    continue
                try:   # dynamic definitions: import the module and look
                    if hasattr(importlib.import_module(module), name):
                        continue
                except Exception as exc:  # noqa: BLE001 - report the precise reason
                    problems.append(f"{rel}:{line} needs {module}.{name}; importing {module} "
                                    f"failed: {type(exc).__name__}: {exc}")
                    continue
                problems.append(f"{rel}:{line} needs {module}.{name}, which this core does "
                                "not define")
    if problems:
        return False, "; ".join(problems[:10]) + (
            f" (+{len(problems) - 10} more)" if len(problems) > 10 else "")
    return True, f"{checked} core imports in the wrapper's own files resolve"


def gui_agent_keywords(root: Path) -> list[str]:
    """Keyword names ``gui/agent_bridge.py`` passes to ``AIAgent(...)``."""
    path = Path(root) / "gui" / "agent_bridge.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else \
                func.attr if isinstance(func, ast.Attribute) else None
            if called == "AIAgent":
                names.update(k.arg for k in node.keywords if k.arg)
    return sorted(names)


def check_agent_keywords(root: Path, agent_class) -> tuple:
    passed = gui_agent_keywords(root)
    if not passed:
        return False, "gui/agent_bridge.py has no AIAgent(...) call to check"
    params = inspect.signature(agent_class.__init__).parameters
    accepted = {n for n, p in params.items()
                if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    unknown = [n for n in passed if n not in accepted]
    if not unknown:
        return True, f"all {len(passed)} keywords the GUI passes are in AIAgent.__init__"
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return True, ("AIAgent takes **kwargs, so these GUI keywords may be ignored: "
                      + ", ".join(unknown)), True
    return False, "AIAgent.__init__ does not accept: " + ", ".join(unknown)


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

    checks.run("wrapper_imports", lambda: check_import_contract(root))

    def gui_agent_arguments():
        from run_agent import AIAgent
        return check_agent_keywords(root, AIAgent)

    if (root / "gui" / "agent_bridge.py").is_file():
        checks.run("gui_agent_arguments", gui_agent_arguments)

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
        if not getattr(toolsets, "_portable_hermes_augmented", False):
            return False, "portable toolsets bridge did not run for toolsets.py"
        try:   # a private upstream API: without it the probe cannot run
            from hermes_cli.tools_config import _get_platform_tools
        except (ImportError, AttributeError) as exc:
            return True, ("WARNING: the CLI tool-selection probe was skipped because "
                          f"hermes_cli.tools_config._get_platform_tools is gone ({exc}); "
                          "check the portable tools in the CLI by hand"), True
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
        "warnings": checks.warnings,
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
            mark = ("warn" if check.get("warning") else "ok  ") if check["ok"] else "FAIL"
            print(f"[{mark}] {check['name']}: {check['detail']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
