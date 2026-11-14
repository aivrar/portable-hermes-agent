"""update_hermes / check_hermes_updates: thin callers of the portable lifecycle.

The update logic itself is covered offline in tests/portable/. These tests pin
the model-visible contract: names, toolset, schema compatibility, how results
are reported (restart notice, kept core, git clones) and that no upstream
file is patched any more.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests import HAS_CORE, NO_CORE_REASON

if not HAS_CORE:          # the tool imports the core's tools.registry
    pytest.skip(NO_CORE_REASON, allow_module_level=True)

import tools.update_hermes_tool as tool  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _completed(result: dict, rc: int = 0):
    return subprocess.CompletedProcess(
        args=[], returncode=rc,
        stdout="progress line\nPORTABLE_RESULT " + json.dumps(result) + "\n", stderr="")


@pytest.fixture()
def calls(monkeypatch):
    seen = []
    replies = {}

    def fake_run(cmd, **kwargs):
        seen.append({"cmd": cmd, **kwargs})
        key = tuple(a for a in cmd if a in ("core", "wrapper", "update", "check"))
        return replies.get(key, _completed({"ok": False, "reason": "no reply"}, 1))

    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    return seen, replies


def test_tools_keep_their_names_toolset_and_parameters():
    from tools.registry import registry

    assert registry.get_toolset_for_tool("update_hermes") == "hermes_update"
    assert registry.get_toolset_for_tool("check_hermes_updates") == "hermes_update"
    assert set(tool.UPDATE_SCHEMA["parameters"]["properties"]) == {
        "branch", "timeout", "allow_merge_commit", "backup_branch", "reset_upstream"}
    assert set(tool.CHECK_UPDATES_SCHEMA["parameters"]["properties"]) == {
        "branch", "timeout", "reset_upstream"}
    assert "NousResearch/hermes-agent" in tool.UPDATE_SCHEMA["description"]


def test_update_success_reports_commit_and_restart(calls):
    seen, replies = calls
    replies[("core", "update")] = _completed({
        "ok": True, "changed": True, "commit": "a" * 40, "repository": "NousResearch/hermes-agent",
        "message": "core installed at aaaaaaaaaaaa", "dependencies": {"strategy": "uv.lock"},
        "files_written": 10, "files_removed": 2})
    out = json.loads(tool.update_hermes_handler({"timeout": 5}))
    assert out["success"] and out["updated"] and out["restart_required"]
    assert "Restart Hermes" in out["next_step"]
    assert out["commit"] == "a" * 40
    cmd = seen[0]["cmd"]
    assert cmd[-3:] == ["core", "update", "--json"]
    assert seen[0]["timeout"] == 60                       # clamped to the minimum
    # Credentials never reach the updater process.
    assert not any(k.endswith("_API_KEY") for k in seen[0]["env"])


def test_update_passes_branch_and_reports_up_to_date(calls):
    seen, replies = calls
    replies[("core", "update")] = _completed({"ok": True, "changed": False,
                                              "commit": "b" * 40, "message": "core already at b"})
    out = json.loads(tool.update_hermes_handler({"branch": "release-x"}))
    assert out["success"] and not out["updated"] and "restart_required" not in out
    assert "--ref" in seen[0]["cmd"] and "release-x" in seen[0]["cmd"]


def test_update_failure_says_the_core_was_kept(calls):
    _, replies = calls
    replies[("core", "update")] = _completed({
        "ok": False, "code": "verify_failed", "kept_existing_core": True,
        "reason": "verification of cccccccccccc failed: cli_selection: lm_studio_status"}, 3)
    out = json.loads(tool.update_hermes_handler({}))
    assert not out["success"] and out["code"] == "verify_failed"
    assert "kept unchanged" in out["note"]


def test_check_in_a_git_clone_points_the_wrapper_at_git_pull(calls):
    # A clone gets its core from the portable updater like a ZIP install;
    # only the wrapper channel belongs to git.
    _, replies = calls
    replies[("core", "check")] = _completed({"ok": True, "install_type": "zip",
                                             "commit": "a" * 40, "update_available": False})
    replies[("wrapper", "check")] = _completed({"ok": True, "install_type": "git",
                                                "installed_version": "unknown",
                                                "latest_version": "v2.1.0",
                                                "update_available": True})
    out = json.loads(tool.check_updates_handler({}))
    assert "Core: up to date." in out["summary"]
    assert "Portable wrapper: git checkout, update it with git pull." in out["summary"]
    assert "UPDATE.bat" not in out["summary"]
    assert "git checkout" not in tool.UPDATE_SCHEMA["description"]


def test_timeout_is_reported_with_the_recovery_path(monkeypatch):
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(tool.subprocess, "run", slow)
    out = json.loads(tool.update_hermes_handler({"timeout": 60}))
    assert not out["success"] and out["code"] == "timeout"
    assert "rolled back the next time Hermes starts" in out["error"]


def test_check_reports_both_channels_separately(calls):
    seen, replies = calls
    replies[("core", "check")] = _completed({"ok": True, "install_type": "zip",
                                             "commit": "a" * 40, "behind_by": 57,
                                             "update_available": True})
    replies[("wrapper", "check")] = _completed({"ok": True, "installed_version": "v2.0.0",
                                                "latest_version": "v2.1.0",
                                                "update_available": True})
    out = json.loads(tool.check_updates_handler({"branch": "main"}))
    assert out["success"]
    assert "57 upstream commits behind" in out["summary"]
    assert "v2.1.0 is available" in out["summary"] and "UPDATE.bat" in out["summary"]
    assert any("--ref" in c["cmd"] for c in seen)


def test_check_degrades_gracefully_offline(calls):
    _, replies = calls
    replies[("core", "check")] = _completed({"ok": True, "install_type": "zip",
                                             "update_available": None,
                                             "network_error": "network error fetching x"})
    replies[("wrapper", "check")] = _completed({"ok": True, "update_available": None,
                                                "network_error": "HTTP 403"})
    out = json.loads(tool.check_updates_handler({}))
    assert "could not check" in out["summary"]


def test_no_upstream_file_is_patched_any_more():
    source = (REPO_ROOT / "tools" / "update_hermes_tool.py").read_text(encoding="utf-8")
    assert "toolsets.py" not in source.replace("``toolsets``", "")
    assert "_HERMES_CORE_TOOLS" not in source
    assert "git merge" not in source and "read-tree" not in source


def test_portable_tool_modules_match_builtin_discovery_contract():
    from tools.registry import _module_registers_tools

    portable_modules = {
        "extension_tools.py",
        "gpu_tool.py",
        "guide_tool.py",
        "lm_studio_tools.py",
        "model_switcher_tool.py",
        "run_python_tool.py",
        "serper_search_tool.py",
        "tool_maker.py",
        "update_hermes_tool.py",
        "workflow_tool.py",
    }

    assert all(
        _module_registers_tools(REPO_ROOT / "tools" / module)
        for module in portable_modules
    )


def test_bridge_lists_exactly_the_tools_the_portable_modules_register():
    from portable_hermes import bridge
    from tools.registry import registry

    import model_tools  # noqa: F401  (runs discovery)

    registered = {name for name in registry.get_all_tool_names()
                  if registry.get_toolset_for_tool(name) in bridge.PORTABLE_TOOLSETS}
    assert registered == set(bridge.PORTABLE_TOOLS)
