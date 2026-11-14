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
        "portable_hermes/manifests/python-runtime.txt",
        "portable_hermes/recovery.py",
        "portable_hermes/runtime.py",
        "portable_hermes/launch/cli.cmd",
        "portable_hermes/launch/env.cmd",
        "portable_hermes/launch/gui.cmd",
        "portable_hermes/launch/gui-exit.cmd",
        "portable_hermes/launch/prepare.cmd",
        "portable_hermes/launch/runtime.cmd",
        "portable_hermes/launch/session.cmd",
        "portable_hermes/launch/start.cmd",
        "portable_hermes/launch/update.cmd",
        "portable_hermes/launch/update-finish.cmd",
        "LICENSE",
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
        ["build_release.py", "--version", "v9.8.7", "--output-dir", str(tmp_path),
         "--no-git-check"],
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
                                     "--output-dir", str(output), "--no-git-check"])
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
    # The licence ships at the root of every release, and no updater manages it.
    assert "LICENSE" in build_release.REQUIRED_RELEASE_FILES and "LICENSE" in candidates
    assert ownership.is_release_only("LICENSE") and not ownership.is_wrapper("LICENSE")
    # Otherwise the release is wrapper-owned files only: no core file ships.
    assert all(ownership.classify(p) == "wrapper" for p in candidates
               if not ownership.is_release_only(p))
    assert "run_agent.py" not in candidates and "toolsets.py" not in candidates
    assert not any(p.startswith(("hermes_cli/", "agent/", "website/")) for p in candidates)
    # Wrapper files inside upstream directories must stay in the release minimum.
    assert ownership.WRAPPER_CORE_TREE_FILES <= build_release.REQUIRED_RELEASE_FILES


def test_built_release_is_wrapper_only_with_payload_and_manifest(tmp_path, monkeypatch):
    import hashlib
    import json

    # The real tree, which may hold uncommitted work while tests run: the
    # git-archive check has its own tests below (on a scratch repository).
    monkeypatch.setattr(sys, "argv", ["build_release.py", "--version", "v0.0.1-test",
                                      "--output-dir", str(tmp_path), "--no-git-check"])
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
    assert manifest["git_archive_check"] == "skipped (--no-git-check)"
    assert manifest["source_commit"] is None
    assert set(manifest["files"]) == rels - {ownership.RELEASE_MANIFEST}
    assert "run_agent.py" not in rels and "hermes_cli/main.py" not in rels
    assert "tools/lm_studio_tools.py" in rels
    assert "LICENSE" in rels and "LICENSE" in manifest["files"]
    assert ownership.PAYLOAD_DIR + "/LICENSE" not in rels
    assert ownership.PAYLOAD_DIR + "/tools/lm_studio_tools.py" in rels
    assert ownership.PAYLOAD_DIR + "/README.md" in rels
    assert ownership.PAYLOAD_DIR + "/gui/app.py" not in rels      # wrapper-only tree
    assert ownership.PAYLOAD_DIR + "/START.bat" not in rels       # wrapper-only name
    shipped = {r for r in rels if not r.startswith("portable_hermes/")}
    assert set(manifest["payload"]) == {r for r in shipped if ownership.is_payload_path(r)}


# --------------------------------------------------------------------------
# a release is byte-identical to `git archive` of its commit
# --------------------------------------------------------------------------

SOURCE_FILES = {
    "README.md": b"# Portable Hermes Agent\nreadme\n",
    "START_HERE.txt": b"Start here\nline two\n",
    "LICENSE": b"MIT License\n",
}


def _git(cwd, *args):
    """git in a scratch repository, independent of the machine's git settings."""
    return subprocess.run(
        ["git", "-c", "user.name=Release Test", "-c", "user.email=release-test@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def release_source(tmp_path, monkeypatch):
    """A committed scratch checkout (LF files, core.autocrlf=false) to build from."""
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "core.autocrlf", "false")
    for rel, data in SOURCE_FILES.items():
        (source / rel).write_bytes(data)
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "release source")
    output = tmp_path / "dist"
    monkeypatch.setattr(build_release, "PROJECT_ROOT", str(source))
    monkeypatch.setattr(build_release, "REQUIRED_RELEASE_FILES", set(SOURCE_FILES))
    monkeypatch.setattr(sys, "argv", ["build_release.py", "--version", "v9.9.9",
                                      "--output-dir", str(output)])
    return source, output


def _built_manifest(output):
    import json
    with zipfile.ZipFile(output / "portable-hermes-agent-v9.9.9.zip") as zf:
        for rel, data in SOURCE_FILES.items():
            assert zf.read("portable-hermes-agent/" + rel) == data, rel
        return json.loads(zf.read("portable-hermes-agent/" + ownership.RELEASE_MANIFEST))


def test_release_from_a_clean_checkout_passes_and_records_its_commit(release_source):
    source, output = release_source
    build_release.main()
    manifest = _built_manifest(output)
    head = _git(source, "rev-parse", "HEAD").stdout.decode().strip()
    assert manifest["source_commit"] == head
    assert manifest["git_archive_check"] == "passed"


def test_a_crlf_copy_of_an_archived_lf_file_stops_the_build_and_is_named(
        release_source, monkeypatch):
    """An ordinary Windows clone (core.autocrlf=true) of files without a
    line-ending rule: git sees no change, but the bytes differ from the archive.
    A rule (text eol=lf) makes the same clone build."""
    source, output = release_source
    clone = source.parent / "windows-clone"
    _git(source.parent, "clone", "-q", "-c", "core.autocrlf=true", str(source), str(clone))
    monkeypatch.setattr(build_release, "PROJECT_ROOT", str(clone))
    assert (clone / "START_HERE.txt").read_bytes() == b"Start here\r\nline two\r\n"
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                            cwd=clone, capture_output=True, check=True)
    assert status.stdout == b""                 # nothing uncommitted as far as git knows
    with pytest.raises(build_release.SourceCheckError) as info:
        build_release.main()
    message = str(info.value)
    assert "  START_HERE.txt: line endings (CRLF here, LF in the archive)\n" in message
    assert "  README.md: line endings (CRLF here, LF in the archive)\n" in message
    assert "git add --renormalize" in message and "core.autocrlf=false" in message
    assert not output.exists() or list(output.iterdir()) == []
    # The fix: line-ending rules, committed; a fresh clone then builds.
    (source / ".gitattributes").write_bytes(
        b"*.md text eol=lf\n/LICENSE text eol=lf\n/START_HERE.txt text eol=lf\n")
    _git(source, "add", ".gitattributes")
    _git(source, "commit", "-q", "-m", "line-ending rules")
    fixed = source.parent / "windows-clone-2"
    _git(source.parent, "clone", "-q", "-c", "core.autocrlf=true", str(source), str(fixed))
    monkeypatch.setattr(build_release, "PROJECT_ROOT", str(fixed))
    assert (fixed / "START_HERE.txt").read_bytes() == SOURCE_FILES["START_HERE.txt"]
    build_release.main()
    assert _built_manifest(output)["git_archive_check"] == "passed"


def test_an_uncommitted_change_stops_the_build_and_is_named(release_source):
    source, output = release_source
    (source / "README.md").write_bytes(b"# Portable Hermes Agent\nnot committed\n")
    with pytest.raises(build_release.SourceCheckError) as info:
        build_release.main()
    message = str(info.value)
    assert "not committed:\n  README.md\n" in message
    assert "START_HERE.txt" not in message
    assert not output.exists() or list(output.iterdir()) == []
    # Staged but not committed counts too.
    _git(source, "add", "README.md")
    with pytest.raises(build_release.SourceCheckError):
        build_release.main()


#: Shipped, but not in REQUIRED_RELEASE_FILES, so only the source check can
#: notice when it is gone.
OPTIONAL_FILE = "docs/hermes-guide.md"


@pytest.mark.parametrize("how", ["deleted", "git rm"])
def test_a_deleted_shipped_file_stops_the_build_and_is_named(release_source, capsys, how):
    source, output = release_source
    (source / "docs").mkdir()
    (source / OPTIONAL_FILE).write_bytes(b"# Guide\n")
    _git(source, "add", OPTIONAL_FILE)
    _git(source, "commit", "-q", "-m", "a guide")
    assert not build_release.should_exclude(OPTIONAL_FILE)
    assert OPTIONAL_FILE not in build_release.REQUIRED_RELEASE_FILES
    if how == "git rm":
        _git(source, "rm", "-q", OPTIONAL_FILE)          # staged: git ls-files drops it
    else:
        (source / OPTIONAL_FILE).unlink()                # unstaged: still in the index
    assert build_release.cli() == 1
    message = capsys.readouterr().err
    assert f"In the commit but missing here:\n    {OPTIONAL_FILE}\n" in message
    assert "README.md" not in message and "not in the commit:" not in message
    assert not output.exists() or list(output.iterdir()) == []


def test_a_shipped_file_that_is_only_staged_stops_the_build_and_is_named(release_source,
                                                                         capsys):
    source, output = release_source
    (source / "docs").mkdir()
    (source / OPTIONAL_FILE).write_bytes(b"# Guide\n")
    _git(source, "add", OPTIONAL_FILE)
    assert build_release.cli() == 1
    message = capsys.readouterr().err
    assert f"To be shipped here but not in the commit:\n    {OPTIONAL_FILE}\n" in message
    assert not output.exists() or list(output.iterdir()) == []


def test_a_git_worktree_of_a_clean_commit_passes(release_source, monkeypatch):
    """Also: the files the builder adds itself (payload copies, release.json)
    are not compared with the commit's file list."""
    source, output = release_source
    worktree = source.parent / "worktree"
    _git(source, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    monkeypatch.setattr(build_release, "PROJECT_ROOT", str(worktree))
    assert build_release.cli() == 0
    manifest = _built_manifest(output)
    assert manifest["git_archive_check"] == "passed"
    assert "README.md" in manifest["payload"]
    assert f"{ownership.PAYLOAD_DIR}/README.md" in manifest["files"]


def test_a_source_that_is_not_a_git_checkout_needs_no_git_check(tmp_path, monkeypatch):
    source = tmp_path / "extracted"
    source.mkdir()
    for rel, data in SOURCE_FILES.items():
        (source / rel).write_bytes(data)
    output = tmp_path / "dist"
    monkeypatch.setattr(build_release, "PROJECT_ROOT", str(source))
    monkeypatch.setattr(build_release, "REQUIRED_RELEASE_FILES", set(SOURCE_FILES))
    monkeypatch.setattr(build_release, "iter_release_files", lambda: iter(SOURCE_FILES))
    argv = ["build_release.py", "--version", "v9.9.9", "--output-dir", str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(build_release.SourceCheckError) as info:
        build_release.main()
    assert "is not a git checkout" in str(info.value) and "--no-git-check" in str(info.value)
    assert not output.exists() or list(output.iterdir()) == []
    monkeypatch.setattr(sys, "argv", argv + ["--no-git-check"])
    build_release.main()
    manifest = _built_manifest(output)
    assert manifest["source_commit"] is None
    assert manifest["git_archive_check"] == "skipped (--no-git-check)"


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


LAUNCH = Path(build_release.PROJECT_ROOT) / "portable_hermes" / "launch"


def _launch(name: str) -> str:
    return (LAUNCH / name).read_text(encoding="utf-8")


def test_windows_launchers_keep_runtime_state_in_active_hermes_home():
    root = Path(build_release.PROJECT_ROOT)
    install = (root / "install.bat").read_text(encoding="utf-8")
    env = _launch("env.cmd")

    # One place decides the Hermes home; every launcher and install.bat call it,
    # without the user's arguments (those belong to Hermes or the updater).
    assert 'if not defined HERMES_HOME set "HERMES_HOME=%USERPROFILE%\\.hermes"' in env
    assert "call .\\portable_hermes\\launch\\env.cmd\n" in install
    for name in ("cli.cmd", "gui.cmd", "start.cmd", "update.cmd"):
        assert "call .\\portable_hermes\\launch\\env.cmd\n" in _launch(name), name
    for name, text in [("install.bat", install)] + [
            (p.name, p.read_text(encoding="utf-8")) for p in LAUNCH.glob("*.cmd")]:
        assert "env.cmd %" not in text, name
    assert "%*" not in env and "%1" not in env and "%~1" not in env
    assert "INTERFACE BETWEEN WRAPPER VERSIONS" in env

    assert "%HERMES_HOME%\\.env" in install
    assert "%HERMES_HOME%\\config.yaml" in install
    assert "%HERMES_HOME%\\permissions.json" in install
    assert '"%HERMES_HOME%\\skills"' in install
    assert "%USERPROFILE%\\.hermes\\permissions.json" not in install
    start = _launch("start.cmd")
    assert '\nif exist "%PH_ROOT%\\gui\\app.py" .\\portable_hermes\\launch\\gui.cmd %*\n' in start
    assert "\n.\\portable_hermes\\launch\\cli.cmd %*\n" in start

    for name in ("cli.cmd", "gui.cmd", "start.cmd", "update.cmd", "env.cmd", "session.cmd"):
        assert 'set "PIP_PREFIX=' not in _launch(name)


def test_launchers_route_updates_and_repair_through_the_portable_wrapper():
    root = Path(build_release.PROJECT_ROOT)
    cli = _launch("cli.cmd")
    gui = _launch("gui.cmd")
    update = _launch("update.cmd")
    env = _launch("env.cmd")
    vbs = (root / "hermes_gui.vbs").read_text(encoding="utf-8")
    assert BOOT in env

    session = _launch("session.cmd")
    finish = _launch("update-finish.cmd")

    # Setup, interrupted-upgrade/update recovery and launch-time repair all run
    # before Hermes starts, on one pre-parsed line (prepare.cmd, then
    # session.cmd, then Python). START.bat and hermes_gui.vbs go through gui.cmd.
    for launcher, start_marker, after in (
            (cli, '"%PYTHON_EXE%" -m hermes_cli.main %*', " & call exit /b %%ERRORLEVEL%%"),
            (gui, '"%PYTHON_EXE%" -c "from gui.app import main; main()" %*',
             " & call .\\portable_hermes\\launch\\gui-exit.cmd & call exit /b %%ERRORLEVEL%%"),
            (update, '"%PYTHON_EXE%" -c "%PH_UPDATE_BOOT%" "%PH_ROOT%\\." %*',
             " & call .\\portable_hermes\\launch\\update-finish.cmd"
             " & call exit /b %%ERRORLEVEL%%")):
        line = next(ln for ln in launcher.splitlines() if start_marker in ln)
        assert line.startswith("call .\\portable_hermes\\launch\\prepare.cmd "), line
        assert line.index("prepare.cmd") < line.index("session.cmd") < line.index(start_marker)
        assert line.endswith(start_marker + after), line
    assert session.count('"%PH_BOOT%" "%PH_ROOT%\\." repair --quiet') == 2      # cli and gui
    prepare = _launch("prepare.cmd")
    assert prepare.index("runtime-plan.cmd") < prepare.index("install.bat") \
        < prepare.index("recover.py")
    assert "call .\\portable_hermes\\launch\\runtime.cmd resume" in prepare
    assert '-I -X utf8 "%PH_STATE%\\recover.py"' in prepare
    assert "hermes_gui.bat" in vbs and "HERMES_PORTABLE_HIDDEN" in vbs

    # "hermes update" goes to the portable updater, never upstream's own one.
    intercept = 'if /i "%~1"=="update" .\\portable_hermes\\launch\\update.cmd %*'
    assert intercept in cli
    assert cli.index(intercept) < cli.index("-m hermes_cli.main %*")
    assert "hermes_cli.main update" not in update
    # Exit code 4: the newest core needs a newer portable Python.
    assert finish.index('"!PH_RC!"=="4"') < finish.index(
        "call .\\portable_hermes\\launch\\runtime.cmd")


def _paren_depths(text: str):
    """(line, depth of open parenthesised blocks before it) for a batch file."""
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        yield line, depth
        if stripped.lower().startswith(("::", "rem ", "@rem ")):
            continue
        code = stripped.replace("^(", "").replace("^)", "")
        code = "".join(part for i, part in enumerate(code.split('"')) if i % 2 == 0)
        depth += code.count("(") - code.count(")")
        assert depth >= 0, line


def test_user_arguments_are_never_parsed_twice():
    """%* never goes through CALL (which doubles carets and expands % again)
    and never sits inside a parenthesised block (a ")" in an argument would
    end it). The root launchers chain into the real scripts without CALL."""
    root = Path(build_release.PROJECT_ROOT)
    files = {name: (root / name).read_text(encoding="utf-8")
             for name in ("hermes.bat", "hermes_gui.bat", "START.bat", "install.bat")}
    files["UPDATE.bat"] = (root / "UPDATE.bat").read_text(encoding="utf-8").split("\n", 1)[0]
    files.update({p.name: p.read_text(encoding="utf-8") for p in LAUNCH.glob("*.cmd")})
    for name, text in files.items():
        for line, depth in _paren_depths(text):
            if "%*" not in line or line.strip().startswith("::"):
                continue
            assert depth == 0, (name, line)
            assert "call " not in line.lower().split("%*")[0].rsplit("&", 1)[-1], (name, line)
            assert "for " not in line.lower(), (name, line)


def test_installer_reads_its_options_with_a_shift_loop_and_resumes_upgrades():
    installer = (Path(build_release.PROJECT_ROOT) / "install.bat").read_text(encoding="utf-8")
    assert "%*" not in installer
    assert '\n:args\nif [%1]==[] goto :args_done\n' in installer
    assert 'if /i "%~1"=="--runtime-upgrade" set "PH_UPGRADE=1"' in installer
    assert "\nshift\ngoto :args\n" in installer
    update = _launch("update.cmd")
    assert '\n:yes_loop\nif [%1]==[] goto :yes_done\n' in update
    # An interrupted Python upgrade is settled before an ordinary install runs.
    resume = installer.index('if not defined PH_UPGRADE if exist "%PH_STATE%\\runtime-plan.cmd" (')
    assert resume < installer.index("call .\\portable_hermes\\launch\\runtime.cmd resume") \
        < installer.index("[STEP 1/10]")
    # The runtime is unpacked and configured under a temporary name, then renamed.
    assert 'set "PYTHON_STAGE=%PH_ROOT%\\python_embedded.extracting"' in installer
    assert installer.index('set "PH_DEST=%PYTHON_STAGE%"') < installer.index(
        'set "PH_PYDIR=%PYTHON_STAGE%"') < installer.index(
        'ren "%PYTHON_STAGE%" "python_embedded"')
    assert "python_embedded.incomplete" in installer
    # The marker holds fixed text (no %DATE% / %TIME%: locale-dependent and
    # they may contain characters the batch parser treats specially).
    assert "%DATE%" not in installer and "%TIME%" not in installer
    assert '> "%PH_STATE%\\installing" echo install.bat has not finished yet' in installer


def _delayed_lines(text: str):
    on = False
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("setlocal") and "enabledelayedexpansion" in low:
            on = True
        elif low.startswith("setlocal") and "disabledelayedexpansion" in low:
            on = False
        if on and not low.startswith(("::", "rem ", "@rem ")):
            yield line


def test_no_literal_exclamation_mark_runs_with_delayed_expansion():
    """With delayed expansion on, cmd.exe reads ! as the start of a variable
    and drops it (install.bat's run_py.sh shebang was lost this way)."""
    files = {"install.bat": (Path(build_release.PROJECT_ROOT) / "install.bat")}
    files.update({p.name: p for p in LAUNCH.glob("*.cmd")})
    checked = 0
    for name, path in files.items():
        for line in _delayed_lines(path.read_text(encoding="utf-8")):
            checked += 1
            rest = re.sub(r"![A-Za-z_][A-Za-z0-9_]*!", "", line)
            assert "!" not in rest, (name, line)
    assert checked > 100
    installer = files["install.bat"].read_text(encoding="utf-8")
    assert "'#' + chr(33) + '/bin/bash'" in installer


def test_installer_never_prints_ok_for_a_step_it_did_not_check():
    lines = (Path(build_release.PROJECT_ROOT) / "install.bat").read_text(
        encoding="utf-8").splitlines()
    for number, line in enumerate(lines):
        if "[OK]" not in line:
            continue
        before = "\n".join(lines[max(0, number - 8):number]).lower()
        # Every [OK] sits behind a check: an if on the line, or an enclosing
        # if/else block a few lines up.
        assert line.strip().lower().startswith("if ") or "if " in before or \
            ") else (" in before, line
    text = "\n".join(lines)
    step = text[text.index("[STEP 6b]"):text.index("Step 7:")]
    assert step.index("if errorlevel 1 (") < step.index("[OK] run_py.sh created.")
    assert 'if not exist "%PH_ROOT%\\run_py.sh"' in step


def test_root_launchers_are_trampolines_into_the_launch_folder():
    root = Path(build_release.PROJECT_ROOT)
    for name, script in (("hermes.bat", "cli.cmd"), ("hermes_gui.bat", "gui.cmd"),
                         ("START.bat", "start.cmd"), ("UPDATE.bat", "update.cmd")):
        first = (root / name).read_bytes().split(b"\r\n", 1)[0].decode("ascii")
        # Chained, not CALLed: CALL would parse the arguments a second time.
        assert first == ('@setlocal & set "PORTABLE_HERMES_ROOT=%~dp0." & pushd "%~dp0" && '
                         f".\\portable_hermes\\launch\\{script} %*"), name


def _batch_files():
    root = Path(build_release.PROJECT_ROOT)
    files = {name: root / name for name in
             ("install.bat", "START.bat", "UPDATE.bat", "hermes.bat", "hermes_gui.bat")}
    files.update({f"launch/{p.name}": p for p in sorted(LAUNCH.glob("*.cmd"))})
    return files


def test_batch_files_are_ascii_crlf_and_never_block_unattended_runs():
    files = _batch_files()
    assert {"launch/env.cmd", "launch/prepare.cmd", "launch/runtime.cmd", "launch/session.cmd",
            "launch/gui-exit.cmd", "launch/update-finish.cmd"} <= set(files)
    for name, path in files.items():
        raw = path.read_bytes()
        assert raw.isascii(), name
        assert raw.count(b"\n") == raw.count(b"\r\n"), name
    assert "HERMES_PORTABLE_NONINTERACTIVE" in _launch("env.cmd")
    for name, path in files.items():
        lines = [line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines()]
        for number, line in enumerate(lines):
            if "pause" not in line.split() and not line.startswith(("set /p", "@pause")):
                continue
            if line.startswith(("::", "rem", "@rem")):
                continue
            if name == "UPDATE.bat":
                continue        # the legacy tail: only an old updater reaches it
            # The pause or prompt itself is conditional, or sits in a block
            # opened by "if defined PH_PAUSE (".
            guarded = "ph_pause" in line or any(
                "if defined ph_pause (" in prev for prev in lines[max(0, number - 3):number])
            assert guarded, (name, line)


def test_windows_installer_fails_closed_instead_of_finishing_partial_setup():
    installer = (Path(build_release.PROJECT_ROOT) / "install.bat").read_text(
        encoding="utf-8"
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
    # a fresh process afterwards. "Kept existing core" (exit 3) is a warning,
    # except while upgrading the Python runtime; exit 4 starts that upgrade.
    core_step = installer.index('"%PH_BOOT%" "%PH_ROOT%\\." core install')
    assert installer.index("[STEP 5/10] Installing Tkinter") < core_step
    assert installer.index('"%PH_BOOT%" "%PH_ROOT%\\." verify') > core_step
    assert 'if "%CORE_EXIT%"=="3" if not defined PH_UPGRADE (' in installer
    assert 'if "%CORE_EXIT%"=="4" if not defined PH_UPGRADE (' in installer
    assert "call .\\portable_hermes\\launch\\runtime.cmd" in installer
    assert 'pip install -e "%SCRIPT_DIR%.' not in installer
    # npm cannot install a pnpm workspace core; that case is skipped, not fatal.
    assert installer.index("pnpm-workspace.yaml") < installer.index('call "%NPM_CMD%" install --quiet')
    # Every failure after the setup checks goes through one label that pauses
    # only when attended; 11 tells runtime.cmd the core was already installed.
    assert installer.rstrip().endswith(
        ":fail\nif defined PH_PAUSE pause\nif defined PH_CORE_DONE exit /b 11\nexit /b 1")
    # The installing marker is removed only after verification succeeded.
    assert installer.rindex('del "%PH_STATE%\\installing"') > installer.index(
        "Installation verification failed")
    # Paths reach PowerShell and Python as environment variables or arguments.
    assert "Invoke-WebRequest" not in installer
    assert "r'%" not in installer and "'%PYTHON" not in installer
    assert "$env:PH_URL" in installer and "-LiteralPath $env:PH_ZIP" in installer
    # The skills fallback never overwrites a skill that is already there.
    assert "xcopy /E /Y /Q \"%SCRIPT_DIR%skills" not in installer
    assert "/XC /XN /XO" in installer


@pytest.mark.needs_core  # the upstream comfyui skill comes with the core
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
