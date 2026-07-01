import json
import subprocess
import sys
from pathlib import Path

from tools import update_hermes_tool


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_update_hermes_runs_portable_updater_with_backup(monkeypatch):
    captured = {}

    def fake_run_update(command, timeout):
        captured["command"] = command
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(command, 0, stdout="updated", stderr="")

    monkeypatch.setattr(update_hermes_tool, "_run_update_command", fake_run_update)
    monkeypatch.setattr(
        update_hermes_tool,
        "_origin_url",
        lambda: "https://github.com/aivrar/portable-hermes-agent.git",
    )

    result = json.loads(
        update_hermes_tool.update_hermes_handler(
            {"branch": "main", "timeout": 30}
        )
    )

    assert result["success"] is True
    assert captured["timeout"] == 60
    assert result["command"] == [
        sys.executable,
        "-m",
        "hermes_cli.main",
        "update",
        "--backup",
        "--yes",
        "--branch",
        "main",
    ]
    assert result["update_source"] == "https://github.com/aivrar/portable-hermes-agent.git"
    assert ".hermes/custom_tools/" in result["preserved_runtime_paths"]
    assert "NousResearch" not in " ".join(result["command"])


def test_check_updates_without_git_uses_portable_zip_fallback(monkeypatch):
    monkeypatch.setattr(update_hermes_tool, "_is_git_checkout", lambda: False)
    monkeypatch.setattr(update_hermes_tool, "_current_branch", lambda: "main")

    result = json.loads(update_hermes_tool.check_updates_handler({}))

    assert result["needs_update"] is None
    assert result["can_update"] is True
    assert result["update_source"] == "aivrar/portable-hermes-agent"
    assert result["recommended_command"] == "hermes update --backup --yes"
    assert "portable ZIP fallback" in result["reason"]
    assert "NousResearch" not in json.dumps(result)


def test_update_tool_does_not_embed_upstream_update_urls():
    source = (REPO_ROOT / "tools" / "update_hermes_tool.py").read_text(
        encoding="utf-8"
    )

    assert "github.com/NousResearch" not in source
    assert "NousResearch/hermes-agent/archive" not in source


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
