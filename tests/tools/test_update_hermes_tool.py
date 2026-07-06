import json
from pathlib import Path

from tools import update_hermes_tool


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_check_updates_without_git_uses_upstream_zip_overlay(monkeypatch):
    def fake_run_git(*args, timeout=120):
        raise AssertionError(f"no-.git update checks must not require git: {args}")

    monkeypatch.setattr(update_hermes_tool, "_is_git_checkout", lambda: False)
    monkeypatch.setattr(update_hermes_tool, "_run_git", fake_run_git)

    result = json.loads(update_hermes_tool.check_updates_handler({}))

    assert result["upstream"] == "NousResearch/hermes-agent"
    assert result["can_update"] is True
    assert result["needs_update"] is None
    assert result["update_mode"] == "upstream_zip_overlay"
    assert "without requiring Git" in result["reason"]
    assert result["recommended_tool"] == "update_hermes"


def test_update_hermes_git_merge_preserves_portable_surface(monkeypatch):
    calls = []
    snapshot = {"tools/update_hermes_tool.py": b"portable updater"}
    repaired = {
        "restored_portable_sources": [],
        "custom_core_tools": "all custom core tools present",
        "custom_toolsets": "all custom toolsets present",
        "preserved_runtime_paths": [".hermes", "python_embedded"],
    }

    def fake_run_git(*args, timeout=120):
        calls.append(args)
        if args == ("fetch", "hermes-upstream", "main", "--quiet"):
            return 0, "", ""
        if args == ("merge", "--ff-only", "hermes-upstream/main"):
            return 0, "Fast-forward", ""
        if args == ("log", "--oneline", "-1"):
            return 0, "abc123 portable update", ""
        return 0, "", ""

    seen = {}
    monkeypatch.setattr(update_hermes_tool, "_is_git_checkout", lambda: True)
    monkeypatch.setattr(
        update_hermes_tool,
        "_ensure_upstream_remote",
        lambda reset_wrong_remote=False: (True, "hermes-upstream", "exists"),
    )
    monkeypatch.setattr(update_hermes_tool, "_create_backup_branch", lambda: "before-sync")
    monkeypatch.setattr(
        update_hermes_tool,
        "_stash_local_changes_if_needed",
        lambda: (True, None, "clean"),
    )
    monkeypatch.setattr(update_hermes_tool, "_restore_stash", lambda ref: (True, "not needed"))
    monkeypatch.setattr(update_hermes_tool, "_snapshot_portable_sources", lambda: snapshot)
    monkeypatch.setattr(update_hermes_tool, "_run_git", fake_run_git)

    def fake_repair(captured_snapshot):
        seen["snapshot"] = captured_snapshot
        return repaired

    monkeypatch.setattr(update_hermes_tool, "_repair_portable_surface", fake_repair)

    result = json.loads(update_hermes_tool.update_hermes_handler({"branch": "main"}))

    assert result["success"] is True
    assert result["mode"] == "git_merge"
    assert result["upstream"] == "NousResearch/hermes-agent"
    assert result["portable_repair"] == repaired
    assert result["current_commit"] == "abc123 portable update"
    assert seen["snapshot"] == snapshot
    assert ("fetch", "hermes-upstream", "main", "--quiet") in calls
    assert ("merge", "--ff-only", "hermes-upstream/main") in calls


def test_update_hermes_without_git_overlays_upstream_and_repairs(monkeypatch):
    snapshot = {"README.md": b"portable readme"}
    repaired = {
        "restored_portable_sources": ["README.md"],
        "custom_core_tools": "added 2 custom core tools",
        "custom_toolsets": "added 1 custom toolsets",
        "preserved_runtime_paths": [".hermes"],
    }

    monkeypatch.setattr(update_hermes_tool, "_is_git_checkout", lambda: False)
    monkeypatch.setattr(update_hermes_tool, "_snapshot_portable_sources", lambda: snapshot)

    def fake_overlay(branch, timeout=600):
        assert branch == "main"
        assert timeout == 120
        return {
            "success": True,
            "source": "https://github.com/NousResearch/hermes-agent/archive/refs/heads/main.zip",
            "copied_files": 42,
            "skipped_preserved_files": 7,
        }

    seen = {}

    def fake_repair(captured_snapshot):
        seen["snapshot"] = captured_snapshot
        return repaired

    monkeypatch.setattr(update_hermes_tool, "_overlay_upstream_zip", fake_overlay)
    monkeypatch.setattr(update_hermes_tool, "_repair_portable_surface", fake_repair)

    result = json.loads(
        update_hermes_tool.update_hermes_handler({"branch": "main", "timeout": 120})
    )

    assert result["success"] is True
    assert result["mode"] == "upstream_zip_overlay"
    assert result["steps"][0]["upstream_zip_overlay"]["copied_files"] == 42
    assert result["portable_repair"] == repaired
    assert seen["snapshot"] == snapshot


def test_portable_surface_repair_reinjects_tools_and_toolsets(tmp_path, monkeypatch):
    toolsets = tmp_path / "toolsets.py"
    toolsets.write_text(
        """_HERMES_CORE_TOOLS = [
    "terminal",
]

# Core toolset definitions
TOOLSETS = {
    "terminal": {
        "description": "Terminal tools",
        "tools": ["terminal"],
        "includes": [],
    },
}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(update_hermes_tool, "_PROJECT_ROOT", tmp_path)

    core_status = update_hermes_tool._ensure_custom_core_tools()
    toolset_status = update_hermes_tool._ensure_custom_toolsets()
    repaired = toolsets.read_text(encoding="utf-8")

    assert core_status.startswith("added ")
    assert toolset_status.startswith("added ")
    assert '"update_hermes",' in repaired
    assert '"check_hermes_updates",' in repaired
    assert '    "hermes_update": {' in repaired
    assert "Update upstream Hermes from NousResearch" in repaired


def test_portable_surface_repair_restores_changed_portable_sources(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text("upstream readme\n", encoding="utf-8")
    toolsets = tmp_path / "toolsets.py"
    toolsets.write_text(
        """_HERMES_CORE_TOOLS = [
    "terminal",
]

# Core toolset definitions
TOOLSETS = {
    "terminal": {
        "description": "Terminal tools",
        "tools": ["terminal"],
        "includes": [],
    },
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(update_hermes_tool, "_PROJECT_ROOT", tmp_path)

    repaired = update_hermes_tool._repair_portable_surface(
        {"README.md": b"portable readme\n"}
    )

    assert repaired["restored_portable_sources"] == ["README.md"]
    assert readme.read_text(encoding="utf-8") == "portable readme\n"


def test_zip_overlay_preserves_portable_runtime_and_source_paths():
    assert update_hermes_tool._is_preserved_overlay_path(".hermes/custom_tools/demo.py")
    assert update_hermes_tool._is_preserved_overlay_path(".hermes/extensions/demo")
    assert update_hermes_tool._is_preserved_overlay_path("extensions/demo")
    assert update_hermes_tool._is_preserved_overlay_path("python_embedded/python.exe")
    assert update_hermes_tool._is_preserved_overlay_path("tools/update_hermes_tool.py")
    assert not update_hermes_tool._is_preserved_overlay_path("run_agent.py")


def test_update_tool_explicitly_targets_upstream_hermes():
    source = (REPO_ROOT / "tools" / "update_hermes_tool.py").read_text(
        encoding="utf-8"
    )

    assert "github.com/NousResearch/hermes-agent.git" in source
    assert "NousResearch/hermes-agent/archive" in source
    assert "aivrar/portable-hermes-agent" in source


def test_default_cli_tool_definitions_include_update_and_tool_maker():
    import model_tools

    definitions = model_tools.get_tool_definitions(
        enabled_toolsets=["hermes-cli"],
        quiet_mode=True,
    )
    names = {definition["function"]["name"] for definition in definitions}

    assert {
        "update_hermes",
        "check_hermes_updates",
        "create_tool",
        "list_custom_tools",
    }.issubset(names)
