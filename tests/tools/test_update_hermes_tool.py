import io
import json
import subprocess
import zipfile
from pathlib import Path

from tools import update_hermes_tool


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


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


def test_update_hermes_fast_forward_repairs_portable_surface(monkeypatch):
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
        if args == ("rev-parse", "HEAD"):
            return 0, "abc123", ""
        if args == ("merge", "--ff-only", "hermes-upstream/main"):
            return 0, "Fast-forward", ""
        if args == ("log", "--oneline", "-1"):
            return 0, "def456 portable update", ""
        return 0, "", ""

    seen = {}
    monkeypatch.setattr(update_hermes_tool, "_is_git_checkout", lambda: True)
    monkeypatch.setattr(
        update_hermes_tool,
        "_ensure_upstream_remote",
        lambda reset_wrong_remote=False: (True, "hermes-upstream", "exists"),
    )
    monkeypatch.setattr(
        update_hermes_tool, "_create_backup_branch", lambda: "before-sync"
    )
    monkeypatch.setattr(
        update_hermes_tool,
        "_stash_local_changes_if_needed",
        lambda: (True, None, "clean"),
    )
    monkeypatch.setattr(
        update_hermes_tool, "_restore_stash", lambda ref: (True, "not needed")
    )
    monkeypatch.setattr(
        update_hermes_tool, "_snapshot_portable_sources", lambda: snapshot
    )
    monkeypatch.setattr(update_hermes_tool, "_run_git", fake_run_git)

    def fake_repair(captured_snapshot):
        seen["snapshot"] = captured_snapshot
        return repaired

    monkeypatch.setattr(update_hermes_tool, "_repair_portable_surface", fake_repair)

    result = json.loads(update_hermes_tool.update_hermes_handler({"branch": "main"}))

    assert result["success"] is True
    assert result["mode"] == "git_merge"
    assert result["portable_repair"] == repaired
    assert result["current_commit"] == "def456 portable update"
    assert seen["snapshot"] == snapshot
    assert ("fetch", "hermes-upstream", "main", "--quiet") in calls
    assert ("merge", "--ff-only", "hermes-upstream/main") in calls


def test_divergent_merge_uses_upstream_tree_and_restores_portable_surface(
    tmp_path, monkeypatch
):
    repo = tmp_path / "portable"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Portable Test")
    _git(repo, "config", "user.email", "portable@example.invalid")
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text(
        exclude.read_text(encoding="utf-8")
        + "\n.env\n.hermes/\n.venv/\nextensions/\nnode_modules/\n"
        "python_embedded/\nvenv/\n",
        encoding="utf-8",
    )

    (repo / "seed.txt").write_text("shared\n", encoding="utf-8")
    (repo / "removed-upstream.txt").write_text("remove me\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "shared base")
    _git(repo, "branch", "upstream-main")

    _git(repo, "switch", "upstream-main")
    (repo / "README.md").write_text("upstream readme\n", encoding="utf-8")
    (repo / "toolsets.py").write_text(
        '_HERMES_CORE_TOOLS = [\n    "terminal",\n]\n\n'
        "# Core toolset definitions\nTOOLSETS = {\n"
        '    "terminal": {"description": "Terminal", "tools": ["terminal"], "includes": []},\n'
        "}\n",
        encoding="utf-8",
    )
    (repo / "upstream-only.txt").write_text("new upstream code\n", encoding="utf-8")
    (repo / "removed-upstream.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "upstream changes")

    _git(repo, "switch", "main")
    portable_source_contents = {}
    for rel_path in update_hermes_tool._PORTABLE_SOURCE_PATHS:
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            b"# Portable Hermes Agent\nportable instructions\n"
            if rel_path == "README.md"
            else f"portable:{rel_path}\n".encode()
        )
        path.write_bytes(content)
        portable_source_contents[rel_path] = content
    portable_tree_contents = {}
    for rel_path in update_hermes_tool._PORTABLE_REQUIRED_TREE_FILES:
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"portable-tree:{rel_path}\n".encode()
        path.write_bytes(content)
        portable_tree_contents[rel_path] = content
    (repo / "toolsets.py").write_text(
        '_HERMES_CORE_TOOLS = [\n    "terminal",\n]\n\n'
        "# Core toolset definitions\nTOOLSETS = {\n"
        '    "terminal": {"description": "Terminal", "tools": ["terminal"], "includes": []},\n'
        "}\n",
        encoding="utf-8",
    )
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "portable.yml").write_text(
        "name: portable\n", encoding="utf-8"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "portable-policy.txt").write_text(
        "portable tests\n", encoding="utf-8"
    )
    (repo / "build_release.py").write_text(
        "# portable release builder\n", encoding="utf-8"
    )
    runtime_markers = {
        ".env": "PORTABLE_SECRET=kept\n",
        ".hermes/config.yaml": "portable: true\n",
        ".hermes/gui_config.json": '{"language": "zh-hant"}\n',
        ".hermes/custom_tools/user_tool.py": "# user tool\n",
        ".hermes/extensions/user-extension/state.json": "{}\n",
        ".venv/pyvenv.cfg": "home = portable\n",
        "extensions/comfyui/user-model.txt": "keep me\n",
        "node_modules/.portable-marker": "keep me\n",
        "python_embedded/python.exe": "portable python\n",
        "venv/pyvenv.cfg": "home = portable\n",
    }
    for rel_path, content in runtime_markers.items():
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "portable surface")
    pre_merge_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    merge = _git(repo, "merge", "--no-edit", "upstream-main", check=False)
    assert merge.returncode != 0
    assert (_git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")).returncode == 0

    monkeypatch.setattr(update_hermes_tool, "_PROJECT_ROOT", repo)
    success, details = update_hermes_tool._finish_divergent_upstream_merge(
        "upstream-main", pre_merge_head, timeout=120
    )

    assert success is True, details
    assert details["portable_verification"] == "portable surface verified"
    assert _git(repo, "status", "--porcelain").stdout == ""
    assert len(_git(repo, "show", "-s", "--format=%P", "HEAD").stdout.split()) == 2
    assert (repo / "upstream-only.txt").read_text(
        encoding="utf-8"
    ) == "new upstream code\n"
    assert not (repo / "removed-upstream.txt").exists()
    assert (repo / "README.md").read_text(encoding="utf-8") == (
        portable_source_contents["README.md"].decode()
    )
    assert (repo / ".github" / "workflows" / "portable.yml").is_file()
    assert (repo / "tests" / "portable-policy.txt").is_file()
    assert (repo / "build_release.py").is_file()
    for rel_path, content in runtime_markers.items():
        assert (repo / rel_path).read_text(encoding="utf-8") == content

    for rel_path in update_hermes_tool._PORTABLE_SOURCE_PATHS:
        assert (repo / rel_path).read_text(encoding="utf-8") == (
            portable_source_contents[rel_path].decode()
        )
    for rel_path, content in portable_tree_contents.items():
        assert (repo / rel_path).read_text(encoding="utf-8") == content.decode()

    toolsets = (repo / "toolsets.py").read_text(encoding="utf-8")
    assert all(
        f'"{name}"' in toolsets for name in update_hermes_tool._CUSTOM_CORE_TOOLS
    )
    assert all(
        f'    "{name}": {{' in toolsets for name in update_hermes_tool._CUSTOM_TOOLSETS
    )


def test_portable_surface_repair_reinjects_tools_and_toolsets(tmp_path, monkeypatch):
    toolsets = tmp_path / "toolsets.py"
    toolsets.write_text(
        '_HERMES_CORE_TOOLS = [\n    "terminal",\n]\n\n'
        "# Core toolset definitions\nTOOLSETS = {\n"
        '    "terminal": {"description": "Terminal", "tools": ["terminal"], "includes": []},\n'
        "}\n",
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


def test_zip_overlay_preserves_portable_runtime_and_source_paths():
    assert update_hermes_tool._is_preserved_overlay_path(".hermes/custom_tools/demo.py")
    assert update_hermes_tool._is_preserved_overlay_path("extensions/demo")
    assert update_hermes_tool._is_preserved_overlay_path("python_embedded/python.exe")
    assert update_hermes_tool._is_preserved_overlay_path("tools/update_hermes_tool.py")
    assert update_hermes_tool._is_preserved_overlay_path("gui/future_panel.py")
    assert update_hermes_tool._is_preserved_overlay_path(
        "skills/extensions/portable-comfyui/SKILL.md"
    )
    assert update_hermes_tool._is_preserved_overlay_path("tests/portable-policy.py")
    assert not update_hermes_tool._is_preserved_overlay_path("run_agent.py")


def test_upstream_zip_update_preserves_runtime_readme_and_portable_tools(
    tmp_path, monkeypatch
):
    project = tmp_path / "portable"
    project.mkdir()
    portable_files = {
        "README.md": "# Portable Hermes Agent\nportable instructions\n",
        "README.zh-TW.md": "portable translated instructions\n",
        ".gitattributes": "*.bat text eol=crlf\n",
        "gui/i18n.py": "# portable translations\n",
        "gui/future_panel.py": "# preserve whole GUI tree\n",
        "tools/update_hermes_tool.py": "# portable upstream updater\n",
        ".github/workflows/portable.yml": "name: portable\n",
        ".hermes/config.yaml": "portable: true\n",
        ".hermes/gui_config.json": '{"language": "zh-hant"}\n',
        ".hermes/custom_tools/user_tool.py": "# user tool\n",
        ".hermes/extensions/user-extension/state.json": "{}\n",
        "extensions/comfyui/user-model.txt": "keep me\n",
        "python_embedded/python.exe": "portable python\n",
    }
    for rel_path, content in portable_files.items():
        path = project / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    upstream_toolsets = (
        '_HERMES_CORE_TOOLS = [\n    "terminal",\n]\n\n'
        "# Core toolset definitions\nTOOLSETS = {\n"
        '    "terminal": {"description": "Terminal", "tools": ["terminal"], "includes": []},\n'
        "}\n"
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        root = "hermes-agent-main/"
        zf.writestr(root + "README.md", "# Hermes Agent\nupstream readme\n")
        for name in ("README.zh-TW.md", ".gitattributes", "gui/i18n.py",
                     "gui/future_panel.py", ".hermes/gui_config.json"):
            zf.writestr(root + name, "upstream replacement\n")
        zf.writestr(root + "tools/update_hermes_tool.py", "# upstream file\n")
        zf.writestr(root + ".github/workflows/upstream.yml", "name: upstream\n")
        zf.writestr(root + ".hermes/config.yaml", "portable: false\n")
        zf.writestr(root + "extensions/comfyui/user-model.txt", "overwrite\n")
        zf.writestr(root + "python_embedded/python.exe", "overwrite\n")
        zf.writestr(root + "run_agent.py", "# current upstream core\n")
        zf.writestr(root + "toolsets.py", upstream_toolsets)
    payload = archive.getvalue()

    monkeypatch.setattr(update_hermes_tool, "_PROJECT_ROOT", project)
    monkeypatch.setattr(update_hermes_tool, "_is_git_checkout", lambda: False)
    monkeypatch.setattr(
        update_hermes_tool,
        "_PORTABLE_SOURCE_PATHS",
        {"README.md", "README.zh-TW.md", ".gitattributes", "tools/update_hermes_tool.py"},
    )
    monkeypatch.setattr(update_hermes_tool, "_PORTABLE_SOURCE_DIRS", {"gui"})
    monkeypatch.setattr(update_hermes_tool, "_PORTABLE_REQUIRED_TREE_FILES", {"gui/i18n.py"})
    monkeypatch.setattr(
        update_hermes_tool, "urlopen", lambda *args, **kwargs: io.BytesIO(payload)
    )

    result = json.loads(update_hermes_tool.update_hermes_handler({"branch": "main"}))

    assert result["success"] is True, result
    assert result["portable_verification"] == "portable surface verified"
    assert (project / "run_agent.py").read_text(encoding="utf-8") == (
        "# current upstream core\n"
    )
    for rel_path, content in portable_files.items():
        assert (project / rel_path).read_text(encoding="utf-8") == content
    assert not (project / ".github" / "workflows" / "upstream.yml").exists()

    toolsets = (project / "toolsets.py").read_text(encoding="utf-8")
    assert all(
        f'"{name}"' in toolsets for name in update_hermes_tool._CUSTOM_CORE_TOOLS
    )
    assert all(
        f'    "{name}": {{' in toolsets for name in update_hermes_tool._CUSTOM_TOOLSETS
    )


def test_portable_surface_rejects_upstream_readme(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text(
        "# Hermes Agent\nupstream instructions\n", encoding="utf-8"
    )
    monkeypatch.setattr(update_hermes_tool, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(update_hermes_tool, "_PORTABLE_SOURCE_PATHS", {"README.md"})
    monkeypatch.setattr(update_hermes_tool, "_PORTABLE_SOURCE_DIRS", set())
    monkeypatch.setattr(update_hermes_tool, "_PORTABLE_REQUIRED_TREE_FILES", set())
    monkeypatch.setattr(update_hermes_tool, "_CUSTOM_CORE_TOOLS", [])
    monkeypatch.setattr(update_hermes_tool, "_CUSTOM_TOOLSETS", {})

    ready, status = update_hermes_tool._portable_surface_is_ready()

    assert ready is False
    assert status == "README.md is not the Portable Hermes Agent README"


def test_portable_source_directories_are_snapshotted_and_restored(tmp_path, monkeypatch):
    gui_file = tmp_path / "gui" / "future_panel.py"
    skill_file = tmp_path / "skills" / "lm-studio" / "references" / "usage.md"
    gui_file.parent.mkdir(parents=True)
    skill_file.parent.mkdir(parents=True)
    gui_file.write_bytes(b"portable gui\n")
    skill_file.write_bytes(b"portable skill support\n")

    monkeypatch.setattr(update_hermes_tool, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(update_hermes_tool, "_PORTABLE_SOURCE_PATHS", set())
    monkeypatch.setattr(
        update_hermes_tool,
        "_PORTABLE_SOURCE_DIRS",
        {"gui", "skills/lm-studio"},
    )

    snapshot = update_hermes_tool._snapshot_portable_sources()
    gui_file.unlink()
    skill_file.write_bytes(b"upstream replacement\n")

    restored = update_hermes_tool._restore_portable_sources(snapshot)

    assert set(restored) == {
        "gui/future_panel.py",
        "skills/lm-studio/references/usage.md",
    }
    assert gui_file.read_bytes() == b"portable gui\n"
    assert skill_file.read_bytes() == b"portable skill support\n"


def test_update_tool_explicitly_targets_both_repositories():
    source = (REPO_ROOT / "tools" / "update_hermes_tool.py").read_text(encoding="utf-8")

    assert "github.com/NousResearch/hermes-agent.git" in source
    assert "NousResearch/hermes-agent/archive" in source
    assert "aivrar/portable-hermes-agent" in source


def test_default_cli_tool_definitions_include_portable_tools():
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
        "delete_tool",
        "list_custom_tools",
        "run_python",
        "workflow_create",
        "workflow_list",
    }.issubset(names)


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
