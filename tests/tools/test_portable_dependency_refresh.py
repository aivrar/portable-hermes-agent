"""A core update must install the new core's requirements, not just its files.

The dependency step now lives in the wrapper-owned core lifecycle
(``portable_hermes.core``). These tests pin how it runs pip: with the product
interpreter, without pip redirection or credentials in the environment, from
the core's lockfile (hash-checked, no resolver), and with failures propagated
and rolled back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portable_hermes import core
from portable_hermes.core import CoreLifecycle

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("exit_code", [0, 1])
def test_pip_runs_on_the_product_interpreter_without_redirection(tmp_path, monkeypatch, exit_code):
    embedded = tmp_path / "python_embedded" / "python.exe"
    embedded.parent.mkdir()
    embedded.touch()
    monkeypatch.setenv("PIP_PREFIX", "unrelated-location")
    monkeypatch.setenv("PIP_TARGET", "unrelated-target")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[0] == str(embedded)
        assert kwargs["cwd"] == str(tmp_path.resolve())
        env = kwargs["env"]
        assert "PIP_PREFIX" not in env and "PIP_TARGET" not in env
        assert "OPENROUTER_API_KEY" not in env
        return subprocess.CompletedProcess(command, exit_code, "out", "ERROR: boom" if exit_code else "")

    monkeypatch.setattr(core.subprocess, "run", run)
    life = CoreLifecycle(tmp_path, python=str(embedded), quiet=True)
    rc, output = life._run_pip(["install", "-r", "reqs.txt"])
    assert rc == exit_code
    assert calls[0][1:3] == ["-m", "pip"]


def test_lockfile_dependencies_install_hash_checked_without_resolver(tmp_path):
    calls = []

    def pip(args, timeout=3600):
        calls.append(list(args))
        if args[0] == "list":
            return 0, "[]"
        return 0, "ok"

    life = CoreLifecycle(tmp_path, quiet=True, run_pip=pip)
    plan = core.dependency_plan(REPO_ROOT)
    report = life._install_dependencies(plan, tmp_path)
    install = next(c for c in calls if c[0] == "install" and "-r" in c)
    assert "--no-deps" in install and "--require-hashes" in install
    wrapper = next(c for c in calls if c[0] == "install" and "lmstudio" in c)
    assert "-c" in wrapper          # wrapper packages may not move the core's pins
    assert report["strategy"] == "uv.lock"


def test_dependency_failure_propagates_and_restores_previous_packages(tmp_path):
    state = {"requests": "1.0", "pip": "25.0"}
    calls = []

    def pip(args, timeout=3600):
        calls.append(list(args))
        if args[0] == "list":
            import json
            return 0, json.dumps([{"name": n, "version": v} for n, v in state.items()])
        if args[0] == "install" and "-r" in args:
            state["requests"] = "9.9"      # partially applied before failing
            state["newpkg"] = "1.0"
            return 1, "ERROR: missing runtime requirement"
        if args[0] == "install":
            for tok in args:
                if "==" in tok:
                    name, version = tok.split("==")
                    state[name] = version
            return 0, ""
        if args[0] == "uninstall":
            for name in args[2:]:
                state.pop(name, None)
            return 0, ""
        return 1, ""

    life = CoreLifecycle(tmp_path, quiet=True, run_pip=pip)
    plan = {"strategy": "pyproject", "requirements": ["requests==9.9"], "extras": [],
            "missing_extras": [], "wrapper_requirements": []}
    with pytest.raises(core.UpdateError) as info:
        life._install_dependencies(plan, tmp_path)
    assert info.value.code == "dependencies_failed"
    assert "missing runtime requirement" in info.value.reason
    assert state == {"requests": "1.0", "pip": "25.0"}
