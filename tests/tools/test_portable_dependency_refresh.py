"""The upstream updater must install new requirements, not just source files."""
import json
import subprocess

import pytest

from tools import update_hermes_tool as updater


@pytest.mark.parametrize("exit_code", [0, 1])
def test_refresh_uses_embedded_runtime_and_propagates_failure(tmp_path, monkeypatch, exit_code):
    embedded = tmp_path / "python_embedded" / "python.exe"
    embedded.parent.mkdir()
    embedded.touch()
    monkeypatch.setattr(updater, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("PIP_PREFIX", "unrelated-location")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert command[0] == str(embedded)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["PIP_TARGET"] == str(embedded.parent / "Lib" / "site-packages")
        assert "PIP_PREFIX" not in kwargs["env"]
        return subprocess.CompletedProcess(command, exit_code, "", "test install failure" if exit_code else "")
    monkeypatch.setattr(updater.subprocess, "run", run)
    result = updater._refresh_portable_dependencies(60)
    assert result["success"] is (exit_code == 0)
    assert calls[0][1:] == ["-m", "pip", "install", "--upgrade", "-e", str(tmp_path)]
    assert len(calls) == (2 if exit_code == 0 else 1)


def test_zip_update_is_not_successful_when_dependencies_fail(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_checkout", lambda: False)
    monkeypatch.setattr(updater, "_snapshot_portable_sources", lambda: {})
    monkeypatch.setattr(updater, "_overlay_upstream_zip", lambda *a, **k: {"success": True})
    monkeypatch.setattr(updater, "_repair_portable_surface", lambda *a: {})
    monkeypatch.setattr(updater, "_portable_surface_is_ready", lambda: (True, "verified"))
    monkeypatch.setattr(updater, "_refresh_portable_dependencies",
                        lambda timeout: {"success": False, "error": "missing runtime requirement"})
    result = json.loads(updater.update_hermes_handler({}))
    assert result["success"] is False
    assert result["error"] == "missing runtime requirement"
