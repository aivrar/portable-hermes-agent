"""The toolsets bridge: portable tools offered by default without editing upstream.

The proof on real tool definitions runs in fresh processes so this test
process's imported modules stay untouched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from portable_hermes import bridge, common

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_toolsets(shared_core: bool):
    core = ["terminal", "read_file"]
    module = types.ModuleType("toolsets")
    module._HERMES_CORE_TOOLS = core
    module._resolve_toolset_memo = {("x",): ["stale"]}
    module.TOOLSETS = {
        "hermes-cli": {"tools": core if shared_core else list(core), "includes": []},
        "hermes-telegram": {"tools": list(core) + ["send_message"], "includes": []},
        "hermes-gateway": {"tools": [], "includes": ["hermes-telegram"]},
        "coding": {"tools": ["terminal"], "includes": [], "posture": True},
        "guide": {"description": "upstream already has a guide toolset", "tools": ["x"]},
    }
    return module


@pytest.mark.parametrize("shared_core", [True, False])
def test_augment_adds_portable_tools_to_core_list_toolsets_and_composites(shared_core):
    module = _fake_toolsets(shared_core)
    changes = bridge.augment(module)
    assert changes
    core = module._HERMES_CORE_TOOLS
    assert set(bridge.PORTABLE_TOOLS) <= set(core)
    assert len(core) == len(set(core))
    for name in ("hermes-cli", "hermes-telegram"):
        tools = module.TOOLSETS[name]["tools"]
        assert set(bridge.PORTABLE_TOOLS) <= set(tools) and len(tools) == len(set(tools))
    assert module.TOOLSETS["lm_studio"]["tools"][0] == "lm_studio_status"
    assert module.TOOLSETS["guide"]["tools"] == ["x"]          # upstream's name wins
    assert module.TOOLSETS["coding"]["tools"] == ["terminal"]  # not a hermes-* composite
    assert module._resolve_toolset_memo == {}
    assert bridge.augment(module) == []                        # idempotent


def test_augment_handles_tuple_core_lists_and_never_raises():
    module = _fake_toolsets(False)
    module._HERMES_CORE_TOOLS = ("terminal",)
    bridge.augment(module)
    assert isinstance(module._HERMES_CORE_TOOLS, tuple)
    assert "run_python" in module._HERMES_CORE_TOOLS
    broken = types.ModuleType("toolsets")
    broken.TOOLSETS = None
    assert bridge.augment(broken) == []


def _run(code: str, *, env_extra=None, timeout=600) -> dict:
    env = common.clean_python_env({"HERMES_HOME": os.environ["HERMES_HOME"]})
    env.update(env_extra or {})
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(REPO_ROOT)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=str(REPO_ROOT), env=env)
    assert proc.returncode == 0, proc.stderr[-3000:]
    line = [l for l in proc.stdout.splitlines() if l.startswith("RESULT ")][-1]
    return json.loads(line[len("RESULT "):])


SELECTION_PROBE = r"""
import contextlib, io, json, sys
sys.path.insert(0, sys.argv[1])
from portable_hermes import bridge
{setup}
with contextlib.redirect_stdout(io.StringIO()):
    import toolsets
    from hermes_cli.config import load_config
    from hermes_cli.tools_config import _get_platform_tools
    selected = _get_platform_tools(load_config(), "cli")
    names = set().union(*(toolsets.resolve_toolset(t) for t in selected))
print("RESULT " + json.dumps({
    "origin": toolsets.__file__,
    "augmented": getattr(toolsets, "_portable_hermes_augmented", False),
    "selected": sorted(set(bridge.PORTABLE_TOOLS) & names),
    "core": sorted(set(bridge.PORTABLE_TOOLS) & set(toolsets._HERMES_CORE_TOOLS)),
}))
"""


@pytest.mark.needs_core
def test_repo_core_does_not_offer_portable_tools_without_the_bridge():
    """Documents why the bridge exists: upstream files stay unpatched.

    The interpreter may carry the bridge's .pth hook (the core installer puts
    it into python_embedded, which CI runs the tests with): it is switched
    off here."""
    result = _run(SELECTION_PROBE.replace("{setup}", ""), env_extra={bridge.NO_HOOK_ENV: "1"})
    assert result["augmented"] is False
    assert result["selected"] == [] and result["core"] == []


@pytest.mark.needs_core
def test_hook_augments_this_installs_toolsets_on_import():
    result = _run(SELECTION_PROBE.replace("{setup}", "bridge.install_hook()"))
    assert Path(result["origin"]).resolve().parent == REPO_ROOT
    assert result["augmented"] is True
    assert result["selected"] == sorted(bridge.PORTABLE_TOOLS)
    assert result["core"] == sorted(bridge.PORTABLE_TOOLS)


@pytest.mark.needs_core
def test_pth_line_installs_the_hook_and_honours_the_opt_out(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    assert bridge.ensure_pth(site_dir) == "written"
    assert bridge.ensure_pth(site_dir) == "ok"
    code = (
        "import json, site, sys; sys.path.insert(0, sys.argv[1]); site.addsitedir(sys.argv[2]);"
        "import toolsets;"
        "print('RESULT ' + json.dumps({'augmented': getattr(toolsets, '_portable_hermes_augmented', False)}))"
    )
    env = common.clean_python_env({"HERMES_HOME": os.environ["HERMES_HOME"]})
    for opt_out, expected in ((None, True), ("1", False)):
        run_env = dict(env)
        if opt_out:
            run_env[bridge.NO_HOOK_ENV] = opt_out
        proc = subprocess.run([sys.executable, "-c", code, str(REPO_ROOT), str(site_dir)],
                              capture_output=True, text=True, timeout=300, env=run_env,
                              cwd=str(tmp_path))
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert json.loads(proc.stdout.split("RESULT ", 1)[1])["augmented"] is expected


def test_hook_ignores_a_toolsets_module_from_another_tree(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "toolsets.py").write_text("TOOLSETS = {'hermes-cli': {'tools': ['terminal']}}\n")
    code = (
        "import json, sys; root, other = sys.argv[1], sys.argv[2];"
        "sys.path.insert(0, root); from portable_hermes import bridge; bridge.install_hook();"
        "sys.path.insert(0, other); import toolsets;"
        "print('RESULT ' + json.dumps({'origin': toolsets.__file__, 'tools': toolsets.TOOLSETS['hermes-cli']['tools']}))"
    )
    proc = subprocess.run([sys.executable, "-c", code, str(REPO_ROOT), str(other)],
                          capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.split("RESULT ", 1)[1])
    assert Path(result["origin"]).parent == other and result["tools"] == ["terminal"]


def test_project_pth_follows_a_moved_folder(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    assert bridge.ensure_project_pth(site_dir) == "absent"
    (site_dir / bridge.PROJECT_PTH_NAME).write_text("C:\\old\\place\\\n", encoding="utf-8")
    assert bridge.ensure_project_pth(site_dir) == "written"
    assert Path((site_dir / bridge.PROJECT_PTH_NAME).read_text().strip()) == bridge.ROOT
    assert bridge.ensure_project_pth(site_dir) == "ok"


@pytest.mark.needs_core
def test_repo_core_real_tool_definitions_offer_portable_tools_to_cli_and_gui():
    """Fresh-process verification of this repo's core: tool discovery, the
    default CLI selection and definitions, and a real AIAgent(platform='gui')."""
    from portable_hermes.core import CoreLifecycle

    result = CoreLifecycle(REPO_ROOT, quiet=True)._default_verify(REPO_ROOT, gui=False)
    checks = {c["name"]: c for c in result.get("checks", [])}
    assert result["ok"], result.get("reason")
    for name in ("core_imports", "portable_tools_registered", "cli_selection", "gui_selection"):
        assert checks[name]["ok"], checks[name]
    assert "47 selected" in checks["cli_selection"]["detail"]
