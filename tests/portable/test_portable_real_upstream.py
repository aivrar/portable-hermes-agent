"""Opt-in: install the real upstream core into a scratch portable root.

Skipped unless ``PORTABLE_REAL_UPSTREAM=1``. It needs network access to PyPI
(and to GitHub unless an archive is given) and takes several minutes.

    PORTABLE_REAL_UPSTREAM=1
    PORTABLE_REAL_PYTHON=<python.exe whose version upstream supports>   (default: this one)
    PORTABLE_REAL_UPSTREAM_ZIP=<upstream archive>   (default: download main)

The scratch root is laid out like a portable install: the wrapper files of
this checkout plus a virtual environment in ``python_embedded`` standing in for
the embedded interpreter. The flow is the one install.bat runs: write
``hermes_project.pth``, run ``core install`` (real download or archive, real
hash-pinned dependency install from upstream's uv.lock, real staged and live
verification including a real ``AIAgent(platform="gui")``), then start
upstream's own CLI and check that the portable toolsets are offered.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from portable_hermes import bridge, common, ownership

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("PORTABLE_REAL_UPSTREAM") != "1",
                       reason="set PORTABLE_REAL_UPSTREAM=1 to install the real upstream core"),
]

PORTABLE_TOOLSET_NAMES = ("lm_studio", "extension_tts", "tool_maker", "hermes_update")


def _run(cmd, *, env, cwd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(cwd), timeout=timeout)


def _result(proc) -> dict:
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("PORTABLE_RESULT "):
            return json.loads(line.split(" ", 1)[1])
    raise AssertionError(f"no result (exit {proc.returncode}):\n"
                         f"{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_upstream_core_installs_verifies_and_offers_portable_tools(tmp_path):
    real_python = os.environ.get("PORTABLE_REAL_PYTHON") or sys.executable
    archive = os.environ.get("PORTABLE_REAL_UPSTREAM_ZIP")
    root = tmp_path / "Portable Hermes"          # a space, like many real folders
    home = tmp_path / "home"
    home.mkdir()

    wrapper = {}
    for rel in ownership.iter_wrapper_files(REPO_ROOT):
        if rel in ownership.WRAPPER_DEV_ONLY:
            continue
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, root / rel)
        wrapper[rel] = _digest(root / rel)

    venv = root / "python_embedded"
    subprocess.run([real_python, "-m", "venv", str(venv)], check=True, timeout=600)
    python = str(venv / "Scripts" / "python.exe")
    site = bridge.site_packages(venv)
    assert site is not None
    (site / bridge.PROJECT_PTH_NAME).write_text(str(root) + "\n", encoding="utf-8")

    env = common.clean_python_env({"HERMES_HOME": str(home)})
    args = ["core", "install", "--json", "--no-fallback"]
    if archive:
        args += ["--zip", str(Path(archive).resolve())]
    proc = _run(common.module_command(python, root, *args), env=env, cwd=root, timeout=5400)
    result = _result(proc)
    assert proc.returncode == 0 and result["ok"], json.dumps(result, indent=1)[-6000:]
    assert result["changed"] is True
    assert result["dependencies"]["strategy"] == "uv.lock"
    assert {"core_imports", "portable_tools_registered", "cli_selection",
            "gui_selection", "gui_modules"} <= set(result["verification"])
    assert result["hook"] in ("written", "ok")

    state = json.loads((root / ".portable" / "core-state.json").read_text(encoding="utf-8"))
    assert state["repository"] == "NousResearch/hermes-agent"
    assert len(state["files"]) > 1000
    assert "run_agent.py" in state["files"]
    assert not any(rel.startswith((".github/", "tests/", "website/docs/"))
                   for rel in state["files"])
    assert all(ownership.classify(rel) == "core" for rel in state["files"])
    # The wrapper's own files are untouched by the core install.
    for rel, digest in wrapper.items():
        assert _digest(root / rel) == digest, rel

    # Same source again: reported as current, nothing reinstalled.
    if archive:
        again = _result(_run(common.module_command(python, root, *args), env=env, cwd=root,
                             timeout=600))
        assert again["ok"] and again["changed"] is False

    # Upstream's own CLI, started the way hermes.bat starts it, offers the
    # portable toolsets; with the bridge switched off it does not.
    cli = [python, "-X", "utf8", "-m", "hermes_cli.main", "tools", "--summary"]
    with_hook = _run(cli, env=env, cwd=root, timeout=600)
    assert with_hook.returncode == 0, with_hook.stderr[-3000:]
    without_hook = _run(cli, env=dict(env, **{bridge.NO_HOOK_ENV: "1"}), cwd=root, timeout=600)
    assert without_hook.returncode == 0, without_hook.stderr[-3000:]
    for name in PORTABLE_TOOLSET_NAMES:
        assert name in with_hook.stdout, (name, with_hook.stdout[-3000:])
        assert name not in without_hook.stdout, name

    # The standalone verification command used by install.bat agrees.
    verify = _run(common.module_command(python, root, "verify", "--no-gui"), env=env,
                  cwd=root, timeout=900)
    assert verify.returncode == 0, verify.stdout[-3000:] + verify.stderr[-3000:]
