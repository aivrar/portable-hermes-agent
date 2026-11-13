import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import build_release
from portable_hermes import ownership

BOOT = "from portable_hermes.__main__ import main"


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
        "portable_hermes/__main__.py",
        "portable_hermes/bridge.py",
        "portable_hermes/core.py",
        "portable_hermes/ownership.py",
        "portable_hermes/wrapper.py",
        "portable_hermes/manifests/last-known-good.json",
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
    tracked = set(build_release.iter_release_files())
    candidates = {p for p in tracked if not build_release.should_exclude(p)}
    assert build_release.REQUIRED_RELEASE_FILES <= candidates
    # The release is wrapper-owned files only: no core file ships.
    assert all(ownership.classify(p) == "wrapper" for p in candidates)
    assert "run_agent.py" not in candidates and "toolsets.py" not in candidates
    assert not any(p.startswith(("hermes_cli/", "agent/", "website/")) for p in candidates)
    # Wrapper files inside upstream directories must stay in the release minimum.
    assert ownership.WRAPPER_CORE_TREE_FILES <= build_release.REQUIRED_RELEASE_FILES


def test_built_release_is_wrapper_only_with_payload_and_manifest(tmp_path, monkeypatch):
    import hashlib
    import json

    monkeypatch.setattr(sys, "argv", ["build_release.py", "--version", "v0.0.1-test",
                                      "--output-dir", str(tmp_path)])
    build_release.main()
    archive = tmp_path / "portable-hermes-agent-v0.0.1-test.zip"
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert all(n.startswith("portable-hermes-agent/") for n in names)
        rels = {n.split("/", 1)[1] for n in names}
        manifest = json.loads(zf.read("portable-hermes-agent/" + ownership.RELEASE_MANIFEST))
        for rel, digest in manifest["files"].items():
            data = zf.read("portable-hermes-agent/" + rel)
            assert hashlib.sha256(data).hexdigest() == digest, rel
    assert manifest["version"] == "v0.0.1-test"
    assert set(manifest["files"]) == rels - {ownership.RELEASE_MANIFEST}
    assert "run_agent.py" not in rels and "hermes_cli/main.py" not in rels
    assert "tools/lm_studio_tools.py" in rels
    assert ownership.PAYLOAD_DIR + "/tools/lm_studio_tools.py" in rels
    assert ownership.PAYLOAD_DIR + "/README.md" in rels
    assert ownership.PAYLOAD_DIR + "/gui/app.py" not in rels      # wrapper-only tree
    assert ownership.PAYLOAD_DIR + "/START.bat" not in rels       # wrapper-only name
    shipped = {r for r in rels if not r.startswith("portable_hermes/")}
    assert set(manifest["payload"]) == {r for r in shipped if ownership.is_payload_path(r)}


def test_root_readmes_keep_portable_identity_and_consistent_language_links():
    root = Path(build_release.PROJECT_ROOT)
    readme_names = {path.name for path in root.glob("README*.md")}
    assert "README.md" in readme_names
    language_badges = None

    for readme_name in readme_names:
        content = (root / readme_name).read_text(encoding="utf-8")
        assert "Portable Hermes Agent" in content
        assert "https://github.com/aivrar/portable-hermes-agent/releases/latest" in content
        assert "NousResearch/hermes-agent/releases" not in content
        assert "hermes-agent.nousresearch.com/docs" not in content
        assert "discord.gg/NousResearch" not in content
        assert "UPDATE.bat" in content
        badges = tuple(
            line.strip() for line in content.splitlines()
            if "img.shields.io/badge/Language-" in line
        )
        assert badges and all(line.isascii() for line in badges)
        links = {
            match.group(1) for line in badges
            if (match := re.search(r'href="(README[^"]*\.md)"', line))
        }
        assert links == readme_names
        if language_badges is None:
            language_badges = badges
        else:
            assert badges == language_badges

    spanish_readme = (root / "README.es.md").read_text(encoding="utf-8")
    assert "hermes_gui.bat" in spanish_readme
    assert "hermes-agent.nousresearch.com/install" not in spanish_readme


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


def test_launchers_route_updates_and_repair_through_the_portable_wrapper():
    root = Path(build_release.PROJECT_ROOT)
    cli_launcher = (root / "hermes.bat").read_text(encoding="utf-8")
    gui_launcher = (root / "hermes_gui.bat").read_text(encoding="utf-8")
    updater = (root / "UPDATE.bat").read_text(encoding="utf-8")
    vbs = (root / "hermes_gui.vbs").read_text(encoding="utf-8")

    # Launch-time repair runs before Hermes starts in both launchers. START.bat
    # and hermes_gui.vbs both go through hermes_gui.bat.
    for launcher, start_marker in ((cli_launcher, "-m hermes_cli.main %*"),
                                   (gui_launcher, "gui")):
        assert BOOT in launcher
        repair = launcher.index("main(['repair', '--quiet'])")
        assert repair < launcher.rindex(start_marker)
    assert "hermes_gui.bat" in vbs

    # "hermes update" goes to the portable updater, never upstream's own one.
    intercept = 'if /i "%~1"=="update" goto :portable_update'
    assert intercept in cli_launcher
    assert cli_launcher.index(intercept) < cli_launcher.index("-m hermes_cli.main %*")
    assert "hermes_cli.main update" not in updater
    assert '"%SCRIPT_DIR%." update %*' in updater and BOOT in updater


def test_batch_files_are_ascii_crlf_and_never_block_unattended_runs():
    root = Path(build_release.PROJECT_ROOT)
    for name in ("install.bat", "START.bat", "UPDATE.bat", "hermes.bat", "hermes_gui.bat"):
        raw = (root / name).read_bytes()
        assert raw.isascii(), name
        assert raw.count(b"\n") == raw.count(b"\r\n"), name
    for name in ("install.bat", "UPDATE.bat", "START.bat"):
        text = (root / name).read_text(encoding="utf-8")
        assert "HERMES_PORTABLE_NONINTERACTIVE" in text, name
        lines = [line.strip().lower() for line in text.splitlines()]
        for number, line in enumerate(lines):
            if "pause" not in line.split():
                continue
            # Either the pause itself is conditional, or an earlier line
            # jumps over it in unattended mode.
            guarded = "ph_pause" in line or "hermes_portable_noninteractive" in line or any(
                "hermes_portable_noninteractive" in prev and "goto" in prev
                for prev in lines[max(0, number - 3):number])
            assert guarded, (name, line)


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

    # The core comes from upstream through the wrapper's lifecycle module,
    # after the embedded runtime exists, and the whole install is verified in
    # a fresh process afterwards. "Kept existing core" (exit 3) is a warning.
    core_step = installer.index('"%SCRIPT_DIR%." core install')
    assert installer.index('if not exist "%PYTHON_DIR%\\Lib\\tkinter" (') < core_step
    assert installer.index('"%SCRIPT_DIR%." verify') > core_step
    assert 'if "%CORE_EXIT%"=="3"' in installer
    assert 'pip install -e "%SCRIPT_DIR%.' not in installer
    # npm cannot install a pnpm workspace core; that case is skipped, not fatal.
    assert installer.index("pnpm-workspace.yaml") < installer.index('call "%NPM_CMD%" install --quiet')
    # Every failure path goes through one label that pauses only when attended.
    assert installer.count("exit /b 1") == 1
    assert installer.rstrip().endswith(":fail\nif defined PH_PAUSE pause\nexit /b 1")


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
    """The wrapper release ships no core file at all. The generated-docs rule
    moved to the core installer, which applies it to the upstream archive and
    still installs runtime assets such as the model catalog."""
    flagged_doc = (
        "website/docs/user-guide/skills/optional/autonomous-ai-agents/"
        "autonomous-ai-agents-blackbox.md"
    )
    assert build_release.should_exclude(flagged_doc) is True
    assert build_release.should_exclude(flagged_doc.replace("/", "\\")) is True
    assert not ownership.is_core_installable(flagged_doc)
    assert not ownership.is_core_installable(flagged_doc.replace("/", "\\"))

    localized_doc = (
        "website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/"
        "user-guide/skills/optional/autonomous-ai-agents/"
        "autonomous-ai-agents-blackbox.md"
    )
    assert not ownership.is_core_installable(localized_doc)
    assert not ownership.is_core_installable(localized_doc.replace("/", "\\"))
    assert not ownership.is_core_installable(
        "website/i18n/es/docusaurus-plugin-content-docs-version-v2/intro.md")
    assert ownership.is_core_installable(
        "website/i18n/zh-Hans/docusaurus-theme-classic/navbar.json")
    assert ownership.is_core_installable("website/static/api/model-catalog.json")
    assert ownership.is_core_installable(
        "optional-skills/autonomous-ai-agents/blackbox/SKILL.md")
    for core_path in (localized_doc, "website/static/api/model-catalog.json",
                      "optional-skills/autonomous-ai-agents/blackbox/SKILL.md"):
        assert build_release.should_exclude(core_path) is True


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
