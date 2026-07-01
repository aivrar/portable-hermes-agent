import importlib
import json
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _fresh_tool_maker():
    module = importlib.import_module("tools.tool_maker")
    return importlib.reload(module)


def test_create_tool_writes_to_hermes_home_custom_tools():
    tool_maker = _fresh_tool_maker()
    home = Path(os.environ["HERMES_HOME"])
    name = "unit_runtime_echo"

    tool_maker.registry._tools.pop(name, None)
    result = json.loads(
        tool_maker.create_tool_handler(
            {
                "name": name,
                "description": "Echo a test value",
                "mode": "code",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
                "code": "result = {'value': args.get('value')}",
            }
        )
    )

    try:
        assert result["created"] is True
        tool_path = Path(result["file"])
        assert tool_path.parent == home / "custom_tools"
        assert tool_path.is_file()
        assert (home / "custom_tools" / "manifest.json").is_file()
        assert not (REPO_ROOT / "tools" / "custom" / f"{name}.py").exists()

        listed = json.loads(tool_maker.list_custom_tools_handler({}))
        assert listed["runtime_dir"].endswith("/custom_tools") or listed[
            "runtime_dir"
        ].endswith("\\custom_tools")
        assert any(tool["name"] == name for tool in listed["tools"])

        response = json.loads(tool_maker.registry._tools[name].handler({"value": "ok"}))
        assert response == {"value": "ok"}
    finally:
        tool_maker.delete_tool_handler({"name": name})


def test_legacy_source_tree_custom_tools_migrate_to_runtime(tmp_path, monkeypatch):
    tool_maker = _fresh_tool_maker()
    runtime_dir = tmp_path / "runtime_custom"
    legacy_dir = tmp_path / "legacy_custom"
    legacy_dir.mkdir()
    legacy_source = "LEGACY_MARKER = True\n"
    (legacy_dir / "legacy_echo.py").write_text(legacy_source, encoding="utf-8")
    (legacy_dir / "manifest.json").write_text(
        json.dumps(
            {
                "tools": {
                    "legacy_echo": {
                        "mode": "code",
                        "file": "legacy_echo.py",
                        "description": "old custom tool",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(tool_maker, "_CUSTOM_DIR", runtime_dir)
    monkeypatch.setattr(tool_maker, "_MANIFEST_PATH", runtime_dir / "manifest.json")
    monkeypatch.setattr(tool_maker, "_LEGACY_CUSTOM_DIR", legacy_dir)
    monkeypatch.setattr(
        tool_maker, "_LEGACY_MANIFEST_PATH", legacy_dir / "manifest.json"
    )

    manifest = tool_maker._load_manifest()

    assert manifest["tools"]["legacy_echo"]["file"] == "legacy_echo.py"
    assert manifest["migrated_from"] == "tools/custom"
    assert (runtime_dir / "legacy_echo.py").read_text(encoding="utf-8") == legacy_source
    assert (legacy_dir / "legacy_echo.py").is_file()


def test_corrupt_runtime_manifest_does_not_break_tool_maker(tmp_path, monkeypatch):
    tool_maker = _fresh_tool_maker()
    runtime_dir = tmp_path / "runtime_custom"
    runtime_dir.mkdir()
    manifest_path = runtime_dir / "manifest.json"
    manifest_path.write_text("{not json", encoding="utf-8")

    monkeypatch.setattr(tool_maker, "_CUSTOM_DIR", runtime_dir)
    monkeypatch.setattr(tool_maker, "_MANIFEST_PATH", manifest_path)

    manifest = tool_maker._load_manifest()

    assert manifest["tools"] == {}
    assert "manifest_error" in manifest
