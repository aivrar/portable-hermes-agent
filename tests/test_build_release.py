import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import build_release


def test_release_zip_includes_user_launchers_and_docs():
    assert build_release.should_exclude("START.bat") is False
    assert build_release.should_exclude("hermes_gui.bat") is False
    assert build_release.should_exclude("UPDATE.bat") is False
    assert build_release.should_exclude("START_HERE.txt") is False
    assert build_release.should_exclude("README.md") is False


def test_tracked_release_inventory_contains_complete_portable_surface():
    release_files = set(build_release.iter_release_files())

    assert {
        "README.md",
        "START.bat",
        "START_HERE.txt",
        "UPDATE.bat",
        "hermes.bat",
        "hermes_gui.bat",
        "hermes_gui.vbs",
        "install.bat",
        "assets/SOUL.md",
        "gui/__init__.py",
        "gui/app.py",
        "gui/agent_bridge.py",
        "gui/api_setup_wizard.py",
        "gui/extensions.py",
        "gui/lm_studio.py",
        "gui/permissions.py",
        "gui/permissions_panel.py",
        "gui/theme.py",
        "skills/extensions/portable-comfyui/SKILL.md",
        "skills/extensions/music-server/SKILL.md",
        "skills/extensions/tts-server/SKILL.md",
        "skills/getting-started/SKILL.md",
        "skills/lm-studio/SKILL.md",
        "tools/extension_tools.py",
        "tools/gpu_tool.py",
        "tools/guide_tool.py",
        "tools/lm_studio_tools.py",
        "tools/model_switcher_tool.py",
        "tools/run_python_tool.py",
        "tools/serper_search_tool.py",
        "tools/tool_maker.py",
        "tools/update_hermes_tool.py",
        "tools/workflow_tool.py",
    } <= release_files


def test_release_tag_produces_the_expected_asset_name(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_release.py", "--version", "v9.8.7", "--output-dir", str(tmp_path)],
    )
    monkeypatch.setattr(build_release, "iter_release_files", lambda: iter(()))
    monkeypatch.setattr(build_release, "REQUIRED_RELEASE_FILES", set())

    build_release.main()

    assert (tmp_path / "portable-hermes-agent-v9.8.7.zip").is_file()


@pytest.mark.parametrize("failure", ["inventory", "missing_source", "write", "corrupt"])
def test_incomplete_build_never_replaces_previous_archive(tmp_path, monkeypatch, failure):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_bytes(b"portable readme")
    output = tmp_path / "release"
    output.mkdir()
    published = output / "portable-hermes-agent-vtest.zip"
    published.write_bytes(b"previous verified release")
    monkeypatch.setattr(sys, "argv", ["build_release.py", "--version", "test",
                                     "--output-dir", str(output)])
    monkeypatch.setattr(build_release, "PROJECT_ROOT", str(source))
    monkeypatch.setattr(build_release, "REQUIRED_RELEASE_FILES", {"README.md"})
    candidates = [] if failure == "inventory" else ["README.md"]
    if failure == "missing_source":
        candidates.append("gui/app.py")
    monkeypatch.setattr(build_release, "iter_release_files", lambda: iter(candidates))
    if failure == "write":
        def fail_write(*args, **kwargs):
            raise PermissionError("source became unreadable")
        monkeypatch.setattr(zipfile.ZipFile, "write", fail_write)
    elif failure == "corrupt":
        def corrupt_write(zf, filename, arcname):
            zf.writestr(arcname, b"wrong bytes")
        monkeypatch.setattr(zipfile.ZipFile, "write", corrupt_write)

    with pytest.raises((RuntimeError, OSError)):
        build_release.main()
    assert published.read_bytes() == b"previous verified release"
    assert list(output.iterdir()) == [published]


def test_release_required_surface_is_tracked_and_not_excluded():
    from tools.update_hermes_tool import _PORTABLE_SOURCE_PATHS, _PORTABLE_REQUIRED_TREE_FILES

    candidates = {p for p in build_release.iter_release_files()
                  if not build_release.should_exclude(p)}
    assert build_release.REQUIRED_RELEASE_FILES <= candidates
    # Adding a portable-owned source must also add it to the release minimum.
    assert (_PORTABLE_SOURCE_PATHS | _PORTABLE_REQUIRED_TREE_FILES) <= build_release.REQUIRED_RELEASE_FILES


def test_readme_download_links_target_the_portable_release_page():
    content = (Path(build_release.PROJECT_ROOT) / "README.md").read_text(
        encoding="utf-8"
    )

    assert "https://github.com/aivrar/portable-hermes-agent/releases/latest" in content
    assert "NousResearch/hermes-agent/releases" not in content


def test_windows_launchers_keep_runtime_state_in_active_hermes_home():
    root = Path(build_release.PROJECT_ROOT)
    start = (root / "START.bat").read_text(encoding="utf-8")
    install = (root / "install.bat").read_text(encoding="utf-8")
    cli_launcher = (root / "hermes.bat").read_text(encoding="utf-8")
    gui_launcher = (root / "hermes_gui.bat").read_text(encoding="utf-8")
    updater = (root / "UPDATE.bat").read_text(encoding="utf-8")

    for launcher in (install, cli_launcher, gui_launcher):
        assert 'if not defined HERMES_HOME set "HERMES_HOME=%USERPROFILE%\\.hermes"' in launcher

    assert "%HERMES_HOME%\\.env" in install
    assert "%HERMES_HOME%\\config.yaml" in install
    assert "%HERMES_HOME%\\permissions.json" in install
    assert "%HERMES_HOME%\\skills\\" in install
    assert "%USERPROFILE%\\.hermes\\permissions.json" not in install
    assert 'call "%SCRIPT_DIR%hermes_gui.bat" %*' in start

    for launcher in (start, cli_launcher, gui_launcher, updater):
        assert 'set "PIP_PREFIX=' not in launcher


def test_windows_installer_fails_closed_instead_of_finishing_partial_setup():
    installer = (Path(build_release.PROJECT_ROOT) / "install.bat").read_text(
        encoding="utf-8"
    )

    # Variables referenced with percent expansion inside a parenthesized block
    # must be assigned before that block is parsed.
    assert installer.index('set "TCLTK_MSI=') < installer.index(
        'if not exist "%PYTHON_DIR%\\Lib\\tkinter" ('
    )

    # npm is a .cmd shim on Windows. Without CALL it terminates install.bat and
    # silently skips profile creation, skill sync, and the success/failure gate.
    assert 'from hermes_constants import bootstrap_hermes_managed_node' in installer
    assert 'call "%NPM_CMD%" install --quiet' in installer
    assert "\n        npm install --quiet" not in installer

    # Success is conditional on the real embedded runtime and portable profile
    # surface, not just on individual download commands returning.
    assert 'import os, tkinter; from pathlib import Path; import gui.app, hermes_cli' in installer
    assert "skills/getting-started/SKILL.md" in installer
    assert "skills/extensions/tts-server/SKILL.md" in installer
    assert "Installation verification failed" in installer


def test_portable_comfyui_skill_does_not_collide_with_upstream_skill():
    root = Path(build_release.PROJECT_ROOT)
    portable = (root / "skills/extensions/portable-comfyui/SKILL.md").read_text(
        encoding="utf-8"
    )
    upstream = (root / "skills/creative/comfyui/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "\nname: portable-comfyui\n" in portable
    assert "\nname: comfyui\n" in upstream


def test_release_zip_excludes_development_only_dirs():
    assert build_release.should_exclude(".github/workflows/tests.yml") is True
    assert build_release.should_exclude("tests/test_toolsets.py") is True
    assert build_release.should_exclude(".pytest_cache/v/cache/nodeids") is True
    assert build_release.should_exclude("test.pdf") is True


def test_release_zip_excludes_generated_docs_but_keeps_runtime_assets():
    flagged_doc = (
        "website/docs/user-guide/skills/optional/autonomous-ai-agents/"
        "autonomous-ai-agents-blackbox.md"
    )
    assert build_release.should_exclude(flagged_doc) is True
    assert build_release.should_exclude(flagged_doc.replace("/", "\\")) is True

    localized_doc = (
        "website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/"
        "user-guide/skills/optional/autonomous-ai-agents/"
        "autonomous-ai-agents-blackbox.md"
    )
    assert build_release.should_exclude(localized_doc) is True
    assert build_release.should_exclude(localized_doc.replace("/", "\\")) is True
    assert (
        build_release.should_exclude(
            "website/i18n/es/docusaurus-plugin-content-docs-version-v2/intro.md"
        )
        is True
    )
    assert (
        build_release.should_exclude(
            "website/i18n/zh-Hans/docusaurus-theme-classic/navbar.json"
        )
        is False
    )
    assert (
        build_release.should_exclude("website/static/api/model-catalog.json") is False
    )
    assert (
        build_release.should_exclude(
            "optional-skills/autonomous-ai-agents/blackbox/SKILL.md"
        )
        is False
    )


def test_release_zip_excludes_portable_runtime_dirs():
    assert build_release.should_exclude(".lmstudio_config") is True
    assert build_release.should_exclude(".hermes/.lmstudio_config") is True
    assert build_release.should_exclude(".hermes/config.yaml") is True
    assert build_release.should_exclude("python_embedded/python.exe") is True
    assert build_release.should_exclude("extensions/comfyui/README.md") is True
    assert build_release.should_exclude("extensions\\music-server\\README.md") is True


def test_release_files_prefer_git_tracked_list(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["git", "ls-files", "-z"]
        return subprocess.CompletedProcess(cmd, 0, stdout=b"README.md\0START.bat\0")

    def fail_worktree_walk():
        raise AssertionError("ignored worktree files should not be walked")

    monkeypatch.setattr(build_release.subprocess, "run", fake_run)
    monkeypatch.setattr(build_release, "iter_worktree_files", fail_worktree_walk)

    assert list(build_release.iter_release_files()) == ["README.md", "START.bat"]


def test_release_files_fall_back_without_git(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd)

    monkeypatch.setattr(build_release.subprocess, "run", fake_run)
    monkeypatch.setattr(
        build_release,
        "iter_worktree_files",
        lambda: iter(["README.md", "START.bat"]),
    )

    assert list(build_release.iter_release_files()) == ["README.md", "START.bat"]
