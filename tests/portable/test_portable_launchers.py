"""The Windows launchers, run for real with cmd.exe.

``python_embedded`` is a venv made from the interpreter running the tests (a
real Python, no download) whose launcher is copied to
``python_embedded/python.exe``; ``hermes_cli`` is a stub that prints what it
received. ``install.bat`` is never the real one: tests that need setup or a
Python upgrade put a small stand-in at the install root.

The legacy tests take the v1.4.18 launchers from git, exactly as released
(CRLF), and replace the line that ran Python with a same-length command that
copies the new launcher over the running file, which is what the v1.4.18
updater effectively did. cmd.exe then continues at the old byte offset in the
new file.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import venv
import zipfile
from pathlib import Path

import pytest

from portable_hermes import common, ownership, runtime
from tests import IN_CI

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows launchers")

REPO_ROOT = Path(__file__).resolve().parents[2]
TRAMPOLINES = ("hermes.bat", "hermes_gui.bat", "START.bat", "UPDATE.bat")
AWKWARD = "Portable Hermes & (test) 'q' [1] ,;="

STUB_CLI = (
    "import json, os, sys\n"
    "print('STUB_ARGS=' + json.dumps(sys.argv[1:]))\n"
    "print('STUB_HOME=' + os.environ.get('HERMES_HOME', ''))\n"
    "print('STUB_OPENAI=' + os.environ.get('OPENAI_API_KEY', '<unset>'))\n"
    "print('STUB_UNATTENDED=' + os.environ.get('HERMES_PORTABLE_NONINTERACTIVE', '<unset>'))\n"
    "sys.exit(int(os.environ.get('STUB_EXIT', '0')))\n"
)

STUB_GUI = (
    "import json, os, sys\n"
    "def main():\n"
    "    print('GUI_ARGS=' + json.dumps(sys.argv[1:]))\n"
    "    sys.exit(int(os.environ.get('STUB_EXIT', '0')))\n"
)


def make_runtime(folder: Path) -> None:
    """A real interpreter at folder/python.exe (venv redirector + pyvenv.cfg).

    Built under a plain name and moved into place: venv refuses paths with ;
    and the venv does not record its own location."""
    build = folder.parent.parent / f"venv-build-{os.getpid()}-{id(folder)}"
    venv.create(build, with_pip=False)
    shutil.copy2(build / "Scripts" / "python.exe", build / "python.exe")
    os.rename(build, folder)


def make_install(base: Path, name: str = AWKWARD, *, runtime: bool = True,
                 gui: bool = False, core: bool = True, release: bool = True) -> Path:
    """A stand-in install: the real launchers and portable_hermes, a stub core
    (``run_agent.py`` and a ``hermes_cli`` that prints its arguments) and, like
    every release, ``portable_hermes/release.json``."""
    root = base / name
    root.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "portable_hermes", root / "portable_hermes",
                    ignore=shutil.ignore_patterns("__pycache__", "release.json", "payload"))
    for bat in TRAMPOLINES:
        shutil.copy2(REPO_ROOT / bat, root / bat)
    if release:
        (root / "portable_hermes" / "release.json").write_text(json.dumps(
            {"schema": 1, "version": "v0.0.0", "files": {}, "payload": {}}))
    (root / "hermes_cli").mkdir()
    (root / "hermes_cli" / "__init__.py").write_text("")
    (root / "hermes_cli" / "main.py").write_text(STUB_CLI)
    if core:
        (root / "run_agent.py").write_text("# stub core\n")
    if gui:
        (root / "gui").mkdir()
        (root / "gui" / "__init__.py").write_text("")
        (root / "gui" / "app.py").write_text(STUB_GUI)
    if runtime:
        make_runtime(root / "python_embedded")
    return root


def base_env(tmp_path: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
                                "HERMES_PORTABLE_HIDDEN", "PORTABLE_HERMES_ROOT")}
    env.update(HERMES_HOME=str(tmp_path / "home"), HERMES_PORTABLE_NONINTERACTIVE="1")
    env.update(extra)
    return {k: v for k, v in env.items() if v is not None}


def run(root: Path, bat: str, args: str = "", *, env: dict, stdin: str = "\n\n\n",
        timeout: int = 300) -> subprocess.CompletedProcess:
    line = f'cmd.exe /d /s /c ""{root / bat}"{" " + args if args else ""}"'
    return subprocess.run(line, cwd=str(root.parent), env=env, input=stdin,
                          capture_output=True, text=True, timeout=timeout)


def out(proc) -> str:
    return proc.stdout + proc.stderr


NOT_RECOGNIZED = "is not recognized as an internal or external command"


# --------------------------------------------------------------------------
# the trampolines and real scripts
# --------------------------------------------------------------------------

def test_launcher_files_are_one_line_trampolines_in_crlf_ascii():
    for bat in TRAMPOLINES:
        data = (REPO_ROOT / bat).read_bytes()
        data.decode("ascii")
        first = data.split(b"\r\n", 1)[0]
        assert first.startswith(b"@setlocal & set \"PORTABLE_HERMES_ROOT=%~dp0.\"")
        # Chained without CALL, so the arguments are parsed exactly once.
        assert first.endswith(b".cmd %*") and b"call" not in first.lower()
        assert b"\n" not in data.replace(b"\r\n", b"")          # CRLF only
        if bat != "UPDATE.bat":
            assert data.count(b"\r\n") == 1
            # Shorter than every byte offset a v1.4.18 launcher resumes at.
            assert len(data) < 1136
    # UPDATE.bat: blank lines from the end of line 1 to offset 6000, then the
    # message for a v1.4.18-or-older updater that replaced it mid-run.
    update = (REPO_ROOT / "UPDATE.bat").read_bytes()
    first_end = update.index(b"\r\n") + 2
    tail = update.index(b"@echo.")
    assert tail >= 6000
    assert set(update[first_end:tail]) <= set(b" \r\n")
    assert update[tail:].index(b"@pause") < update[tail:].index(b"@exit /b 0")
    for script in (REPO_ROOT / "portable_hermes" / "launch").glob("*.cmd"):
        raw = script.read_bytes()
        raw.decode("ascii")
        assert b"\n" not in raw.replace(b"\r\n", b""), script.name


def test_cli_passes_awkward_arguments_and_exit_codes_through(tmp_path):
    root = make_install(tmp_path)
    env = base_env(tmp_path, OPENAI_API_KEY="from-the-shell")
    proc = run(root, "hermes.bat", 'chat -q "hi! (x) & y = z, done;"', env=env)
    assert proc.returncode == 0, out(proc)
    assert 'STUB_ARGS=["chat", "-q", "hi! (x) & y = z, done;"]' in proc.stdout
    assert f"STUB_HOME={tmp_path / 'home'}" in proc.stdout
    assert "STUB_OPENAI=<unset>" in proc.stdout              # stray shell keys cleared
    proc = run(root, "hermes.bat", "chat", env=dict(env, STUB_EXIT="7"))
    assert proc.returncode == 7, out(proc)
    assert NOT_RECOGNIZED not in out(proc)


def test_cli_exit_code_reaches_a_calling_batch_file(tmp_path):
    root = make_install(tmp_path)
    caller = tmp_path / "caller.cmd"
    caller.write_bytes(f'@echo off\r\ncall "{root / "hermes.bat"}" chat\r\n'
                       'echo CALLER_SAW=%errorlevel%\r\n'.encode("ascii"))
    proc = subprocess.run(f'cmd.exe /d /s /c ""{caller}""', cwd=str(tmp_path),
                          env=base_env(tmp_path, STUB_EXIT="5"), capture_output=True,
                          text=True, timeout=300)
    assert "CALLER_SAW=5" in proc.stdout, out(proc)


def test_update_failure_is_reported_with_its_exit_code(tmp_path):
    root = make_install(tmp_path)
    proc = run(root, "UPDATE.bat", "--yes --no-core --zip missing.zip", env=base_env(tmp_path))
    assert proc.returncode == 1, out(proc)
    assert "wrapper archive not found" in proc.stdout
    assert "Update finished with problems (exit code 1)" in proc.stdout
    assert NOT_RECOGNIZED not in out(proc)


# --------------------------------------------------------------------------
# the user's arguments, compared with what the v1.4.18 hermes.bat delivered
# --------------------------------------------------------------------------

ARGUMENT_CASES = [
    ('"100% sure"', ["100% sure"]),
    ('"2^10"', ["2^10"]),
    ('"wow!"', ["wow!"]),
    ("photo(1).png", ["photo(1).png"]),
    ('"a & b"', ["a & b"]),
    ('"what is *.py?"', ["what is *.py?"]),
    ("--yes", ["--yes"]),
]
ALL_ARGUMENTS = " ".join(typed for typed, _ in ARGUMENT_CASES)
ALL_EXPECTED = [value for _, expected in ARGUMENT_CASES for value in expected]


@pytest.fixture(scope="module")
def args_install(tmp_path_factory):
    root = make_install(tmp_path_factory.mktemp("args"), gui=True)
    (root / "legacy-hermes.bat").write_bytes(legacy_bytes("hermes.bat"))
    return root


def printed_args(proc, prefix: str = "STUB_ARGS=") -> list:
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(prefix)]
    assert len(lines) == 1, out(proc)
    return json.loads(lines[0][len(prefix):])


@pytest.mark.parametrize("typed, expected", ARGUMENT_CASES)
def test_arguments_reach_hermes_like_the_v1_4_18_launcher(args_install, typed, expected):
    root = args_install
    env = base_env(root.parent, HERMES_PORTABLE_NONINTERACTIVE=None)
    ours = run(root, "hermes.bat", typed, env=env)
    legacy = run(root, "legacy-hermes.bat", typed, env=env)
    assert ours.returncode == 0, out(ours)
    assert printed_args(ours) == expected
    if "(" in typed and '"' not in typed:
        # v1.4.18 had %* inside a parenthesised block: an unquoted ")" ended
        # the block and the launcher stopped before Hermes started.
        assert legacy.returncode != 0 and "STUB_ARGS" not in legacy.stdout
        assert "was unexpected at this time" in out(legacy)
        return
    assert legacy.returncode == 0, out(legacy)
    if "!" in typed:
        # v1.4.18 ran with delayed expansion on and dropped every "!".
        assert printed_args(legacy) == [v.replace("!", "") for v in expected]
    else:
        assert printed_args(legacy) == expected
    # --yes belongs to Hermes here: it does not make the launcher unattended.
    assert "STUB_UNATTENDED=<unset>" in ours.stdout


def test_gui_and_start_pass_the_same_arguments(args_install):
    root = args_install
    env = base_env(root.parent)
    for bat in ("hermes_gui.bat", "START.bat"):
        proc = run(root, bat, ALL_ARGUMENTS, env=env)
        assert proc.returncode == 0, out(proc)
        assert printed_args(proc, "GUI_ARGS=") == ALL_EXPECTED, bat
    proc = run(root, "hermes.bat", ALL_ARGUMENTS, env=env)
    assert printed_args(proc) == ALL_EXPECTED
    proc = run(root, "hermes_gui.bat", ALL_ARGUMENTS, env=dict(env, STUB_EXIT="6"))
    assert proc.returncode == 6 and "GUI exited with an error" in proc.stdout, out(proc)


def test_update_reads_yes_after_a_path_with_parentheses(tmp_path):
    root = make_install(tmp_path)
    env = base_env(tmp_path, HERMES_PORTABLE_NONINTERACTIVE=None)
    proc = run(root, "UPDATE.bat", r"--no-core --zip C:\x\file(1).zip --yes", env=env, stdin="")
    assert proc.returncode == 1, out(proc)
    assert "wrapper archive not found: C:\\x\\file(1).zip" in proc.stdout
    assert "Update finished with problems (exit code 1)" in proc.stdout
    assert "Press any key" not in out(proc)                 # --yes: unattended
    assert "syntax of the command is incorrect" not in out(proc)


def test_hermes_update_reads_yes_after_a_path_with_parentheses(tmp_path):
    """hermes.bat runs in a throwaway install under tmp_path whose hermes_cli is
    a stub that only prints its arguments, and the portable updater stops at
    the missing ZIP before any download."""
    root = make_install(tmp_path)
    env = base_env(tmp_path, HERMES_PORTABLE_NONINTERACTIVE=None)
    proc = run(root, "hermes.bat", r"update --no-core --zip C:\x\file(1).zip -y", env=env,
               stdin="")
    assert proc.returncode == 1, out(proc)
    assert "wrapper archive not found: C:\\x\\file(1).zip" in proc.stdout
    assert "STUB_ARGS" not in proc.stdout                   # never upstream's updater
    assert "Press any key" not in out(proc)


@pytest.mark.parametrize("name, char", [("bang!folder", "!"), ("pct%folder", "%"),
                                        ("caret^folder", "^")])
def test_folders_batch_files_cannot_handle_are_refused_up_front(tmp_path, name, char):
    root = make_install(tmp_path, name, runtime=False)
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 1, out(proc)
    assert "cannot run from this folder" in proc.stdout
    assert "Nothing was changed" in proc.stdout
    assert "STUB_ARGS" not in proc.stdout
    assert not (tmp_path / "home").exists()


def test_hermes_home_with_bang_is_refused(tmp_path):
    root = make_install(tmp_path)
    proc = run(root, "hermes.bat", "chat",
               env=base_env(tmp_path, HERMES_HOME=str(tmp_path / "home!x")))
    assert proc.returncode == 1 and "Hermes home folder" in proc.stdout, out(proc)


# --------------------------------------------------------------------------
# prepare.cmd: interrupted updates, setup, package changes
# --------------------------------------------------------------------------

def interrupted_update(root: Path) -> None:
    (root / "tools").mkdir(exist_ok=True)
    (root / "tools" / "a.py").write_bytes(b"old")
    staged = common.staging_dir(root)
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "a.py").write_bytes(b"new")
    txn = common.Transaction(root, "core")
    txn.put("tools/a.py", staged / "a.py")
    txn.apply()                       # never committed: the updater "died" here


def test_launcher_settles_an_interrupted_update_before_starting_hermes(tmp_path):
    root = make_install(tmp_path)
    interrupted_update(root)
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 0, out(proc)
    text = proc.stdout
    assert "rolled back an interrupted core update" in text
    assert text.index("rolled back") < text.index("STUB_ARGS")
    assert (root / "tools" / "a.py").read_bytes() == b"old"
    assert not (root / ".portable" / "journal.json").exists()


def test_damaged_journal_stops_the_launch_and_changes_nothing(tmp_path):
    root = make_install(tmp_path)
    interrupted_update(root)
    journal = root / ".portable" / "journal.json"
    journal.write_text('{"schema": 2, "id": "zz"}', encoding="utf-8")
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 1, out(proc)
    assert "damaged" in proc.stdout and "journal.damaged.json" in proc.stdout
    assert "Hermes was not started" in proc.stdout
    assert "STUB_ARGS" not in proc.stdout
    assert journal.read_text(encoding="utf-8") == '{"schema": 2, "id": "zz"}'
    assert (root / "tools" / "a.py").read_bytes() == b"new"   # left exactly as found


def test_missing_recovery_script_stops_the_launch(tmp_path):
    root = make_install(tmp_path)
    interrupted_update(root)
    os.rename(root / ".portable" / "recover.py", root / ".portable" / "recover.moved")
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 1 and "recover.py" in proc.stdout, out(proc)
    assert "STUB_ARGS" not in proc.stdout


def test_pending_package_change_is_announced(tmp_path):
    root = make_install(tmp_path)
    (root / ".portable").mkdir()
    (root / ".portable" / "deps-pending.json").write_text("{}", encoding="utf-8")
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 0, out(proc)
    assert "interrupted while it was changing Python" in proc.stdout
    assert "UPDATE.bat" in proc.stdout and "STUB_ARGS" in proc.stdout


STAND_IN_INSTALL = (
    "@echo off\r\n"
    "echo STAND-IN install.bat %*\r\n"
    "if defined STANDIN_FAIL exit /b 1\r\n"
    "if not exist \"%~dp0python_embedded\\python.exe\" xcopy /e /i /q "
    "\"%~dp0..\\spare-runtime\" \"%~dp0python_embedded\" >nul\r\n"
    "if not exist \"%~dp0run_agent.py\" echo # stub core> \"%~dp0run_agent.py\"\r\n"
    "if exist \"%~dp0.portable\\installing\" del \"%~dp0.portable\\installing\"\r\n"
    "exit /b 0\r\n"
)


def test_first_start_runs_setup_then_hermes(tmp_path):
    root = make_install(tmp_path, runtime=False)
    make_runtime(tmp_path / "spare-runtime")
    (root / "install.bat").write_bytes(STAND_IN_INSTALL.encode("ascii"))
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 0, out(proc)
    assert proc.stdout.index("STAND-IN install.bat") < proc.stdout.index("STUB_ARGS")


def test_unfinished_setup_runs_again_and_failure_stops_the_launch(tmp_path):
    root = make_install(tmp_path)
    (root / "install.bat").write_bytes(STAND_IN_INSTALL.encode("ascii"))
    (root / ".portable").mkdir()
    (root / ".portable" / "installing").write_text("started", encoding="ascii")
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path, STANDIN_FAIL="1"))
    assert proc.returncode == 1, out(proc)
    assert "did not finish" in proc.stdout and "STUB_ARGS" not in proc.stdout
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 0, out(proc)
    assert "STAND-IN install.bat" in proc.stdout and "STUB_ARGS" in proc.stdout
    assert not (root / ".portable" / "installing").exists()
    # A legacy install (no marker) just starts.
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert "STAND-IN" not in proc.stdout and "STUB_ARGS" in proc.stdout


def test_a_folder_with_python_but_no_core_runs_setup_first(tmp_path):
    """A git clone has no core (the repository holds only the wrapper): with a
    Python already in place, the next start installs the core first."""
    root = make_install(tmp_path, core=False)
    (root / "install.bat").write_bytes(STAND_IN_INSTALL.encode("ascii"))
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 0, out(proc)
    text = proc.stdout
    assert "This folder has no Hermes core yet. Running setup to install it now." in text
    assert "did not finish" not in text
    assert text.index("no Hermes core yet") < text.index("STAND-IN install.bat")
    assert text.index("STAND-IN install.bat") < text.index("STUB_ARGS")
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert "STAND-IN" not in proc.stdout and "STUB_ARGS" in proc.stdout


HANDOVER_NOTE = "NOTE: the update is not finished. Run UPDATE.bat once more."


def test_v1_4_18_hand_over_state_says_to_run_update_once_more(tmp_path):
    """After the first UPDATE.bat of a v1.4.18 install: the new launchers came
    from the repository's main ZIP (no release.json) and the old core, with its
    complete tools folder, is still there. Hermes starts, with a note."""
    root = make_install(tmp_path, release=False)
    (root / "tools").mkdir()
    (root / "tools" / "registry.py").write_text("registry = None\n")
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path))
    assert proc.returncode == 0, out(proc)
    assert HANDOVER_NOTE in proc.stdout
    assert proc.stdout.index(HANDOVER_NOTE) < proc.stdout.index("STUB_ARGS")
    assert "Hermes was not started" not in proc.stdout
    # UPDATE.bat itself is the way out: no note there.
    proc = run(root, "UPDATE.bat", "--yes --no-core --zip missing.zip", env=base_env(tmp_path))
    assert "wrapper archive not found" in proc.stdout, out(proc)
    assert HANDOVER_NOTE not in proc.stdout
    # A release (release.json) or a git clone (.git) is never in that state.
    for marker in ("release", "git"):
        other = make_install(tmp_path / marker, release=marker == "release")
        if marker == "git":
            (other / ".git").mkdir()
        proc = run(other, "hermes.bat", "chat", env=base_env(tmp_path))
        assert proc.returncode == 0 and "STUB_ARGS" in proc.stdout, out(proc)
        assert HANDOVER_NOTE not in proc.stdout, marker


def test_hand_over_state_with_an_incomplete_core_does_not_start_hermes(tmp_path):
    """If the old updater replaced the whole tools folder (GitHub ignoring
    export-ignore), the old core cannot start: say so instead of a traceback."""
    root = make_install(tmp_path, release=False)
    env = base_env(tmp_path, HERMES_PORTABLE_NONINTERACTIVE=None)
    proc = run(root, "hermes.bat", "chat", env=env, stdin="\n")
    assert proc.returncode == 1, out(proc)
    text = " ".join(proc.stdout.split())
    assert HANDOVER_NOTE in text
    assert ("Hermes was not started: its core is incomplete until UPDATE.bat has run once "
            "more. Your settings and data are kept.") in text
    assert "Press any key" in text
    assert "STUB_ARGS" not in proc.stdout


# --------------------------------------------------------------------------
# GitHub's source download (no portable tools): a plain message, nothing done
# --------------------------------------------------------------------------

SOURCE_DOWNLOAD_LINES = (
    "This folder is GitHub's source download of Portable Hermes. It lacks the portable "
    "tools, so it cannot be installed.",
    "Download portable-hermes-agent-vX.Y.Z.zip from the Assets list on "
    "https://github.com/aivrar/portable-hermes-agent/releases/latest (not \"Source code\"), "
    "then extract it into a new folder and run START.bat there.",
    "Nothing was installed or changed.",
)


def source_download(base: Path) -> Path:
    """The launchers and the real install.bat as GitHub's source ZIP has them:
    no tools/, no release.json, no .git, no Python. python-runtime.txt is left
    out as a tripwire: if the check let setup go on, install.bat would stop at
    its missing-pin error, before any download."""
    root = base / AWKWARD
    root.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "portable_hermes", root / "portable_hermes",
                    ignore=shutil.ignore_patterns("__pycache__", "release.json", "payload",
                                                  "python-runtime.txt"))
    for bat in TRAMPOLINES + ("install.bat",):
        shutil.copy2(REPO_ROOT / bat, root / bat)
    return root


def tree(root: Path) -> list:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


@pytest.mark.parametrize("bat, expected_rc", [
    ("START.bat", 12), ("install.bat", 12), ("hermes.bat", 1), ("hermes_gui.bat", 1)])
def test_source_download_explains_itself_and_changes_nothing(tmp_path, bat, expected_rc):
    root = source_download(tmp_path)
    before = tree(root)
    env = base_env(tmp_path, HERMES_PORTABLE_NONINTERACTIVE=None)      # a double-click
    proc = run(root, bat, env=env, stdin="\n")
    text = " ".join(proc.stdout.split())
    assert proc.returncode == expected_rc, out(proc)
    for line in SOURCE_DOWNLOAD_LINES:
        assert line in text, out(proc)
    assert "Press any key" in text                       # the window stays open
    assert text.count("Press any key") == 1
    assert "python-runtime.txt is missing" not in text   # stopped before setup
    for later in ("First Time Setup", "Starting Hermes", "Setup did not finish",
                  "GUI exited with an error", "Installer"):
        assert later not in text, (later, out(proc))
    assert NOT_RECOGNIZED not in out(proc)
    assert tree(root) == before
    assert not (tmp_path / "home").exists()


def test_source_download_check_never_pauses_unattended(tmp_path):
    root = source_download(tmp_path)
    env = base_env(tmp_path, HERMES_PORTABLE_NONINTERACTIVE=None)
    proc = run(root, "install.bat", "--yes", env=env, stdin="")
    assert proc.returncode == 12, out(proc)
    assert "Nothing was installed or changed." in proc.stdout
    assert "Press any key" not in out(proc)


def test_source_download_check_is_the_same_in_install_bat_and_start_cmd():
    """START.bat hands over to install.bat on exactly the test install.bat
    makes, so the message comes before the welcome text. The file it looks for
    is part of every release; release.json is written into every release."""
    condition = ('if not exist "%PH_ROOT%\\tools\\update_hermes_tool.py" if not exist '
                 '"%PH_ROOT%\\portable_hermes\\release.json" if not exist "%PH_ROOT%\\.git" ')
    install = (REPO_ROOT / "install.bat").read_text(encoding="ascii")
    start = (REPO_ROOT / "portable_hermes" / "launch" / "start.cmd").read_text(encoding="ascii")
    assert install.count(condition + "(") == 1
    assert start.count(condition + ".\\install.bat\n") == 1
    assert start.index(condition) < start.index("First Time Setup")
    # Before anything that writes or downloads.
    assert install.index(condition) < install.index("journal.json")
    assert install.index(condition) < install.index(":: Step 1:")
    assert "tools/update_hermes_tool.py" in ownership.REQUIRED_RELEASE_FILES
    assert ownership.RELEASE_MANIFEST == "portable_hermes/release.json"


# --------------------------------------------------------------------------
# runtime.cmd: the in-place Python upgrade (install.bat is a stand-in)
# --------------------------------------------------------------------------

DRIVER = (
    "@echo off\r\n"
    "setlocal disabledelayedexpansion\r\n"
    "for %%I in (\"%~dp0.\") do set \"PH_ROOT=%%~fI\"\r\n"
    "pushd \"%~dp0\"\r\n"
    "call .\\portable_hermes\\launch\\env.cmd\r\n"
    "call .\\portable_hermes\\launch\\runtime.cmd\r\n"
    "call exit /b %%errorlevel%%\r\n"
)

UPGRADE_INSTALL = (
    "@echo off\r\n"
    "echo STAND-IN install.bat %*\r\n"
    "if exist \"%~dp0python_embedded\" echo STALE-RUNTIME-PRESENT\r\n"
    "xcopy /e /i /q \"%~dp0..\\spare-runtime\" \"%~dp0python_embedded\" >nul\r\n"
    "echo new> \"%~dp0python_embedded\\which.txt\"\r\n"
    "if defined STANDIN_DEPS echo changed by the new core> \"%~dp0.portable\\deps-pending.json\"\r\n"
    "exit /b %STANDIN_EXIT%\r\n"
)


def upgrade_setup(tmp_path):
    root = make_install(tmp_path)
    make_runtime(tmp_path / "spare-runtime")
    (root / "python_embedded" / "which.txt").write_text("old\n", encoding="ascii")
    (root / "install.bat").write_bytes(UPGRADE_INSTALL.encode("ascii"))
    (root / "upgrade.cmd").write_bytes(DRIVER.encode("ascii"))
    return root


def python_tag_of(root: Path, folder: str) -> str:
    return subprocess.run([str(root / folder / "python.exe"), "-c",
                           "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
                          capture_output=True, text=True).stdout.strip()


def test_runtime_upgrade_success_keeps_the_previous_python(tmp_path):
    root = upgrade_setup(tmp_path)
    tag = python_tag_of(root, "python_embedded")
    proc = run(root, "upgrade.cmd", "--yes", env=base_env(tmp_path, STANDIN_EXIT="0"))
    assert proc.returncode == 0, out(proc)
    old = f"python_embedded.old-{tag}"
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "new"
    assert (root / old / "which.txt").read_text().strip() == "old"
    text = proc.stdout
    assert "STAND-IN install.bat --runtime-upgrade" in text
    assert "STALE-RUNTIME-PRESENT" not in text
    assert f"The previous Python is kept in the folder {old}" in text
    assert f"You may delete the folder {old}" in text
    assert "Upgrade the portable Python" not in text                # unattended: no question


def test_runtime_upgrade_failure_before_the_core_commits_puts_everything_back(tmp_path):
    root = upgrade_setup(tmp_path)
    (root / ".portable").mkdir()
    (root / ".portable" / "core-state.json").write_text('{"commit": "x"}', encoding="ascii")
    pin = (REPO_ROOT / "portable_hermes/manifests/python-runtime.txt").read_text().strip()
    proc = run(root, "upgrade.cmd", "--yes", env=base_env(tmp_path, STANDIN_EXIT="1"))
    assert proc.returncode == 1, out(proc)
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "old"
    failed = root / f"python_embedded.failed-{pin}"
    assert (failed / "which.txt").read_text().strip() == "new"
    assert "upgrade did not complete, so it was undone" in proc.stdout
    assert not list(root.glob("python_embedded.old-*"))
    assert not (root / ".portable" / "installing").exists()
    assert (root / ".portable" / "core-state.json").read_text() == '{"commit": "x"}'


def test_runtime_upgrade_after_the_core_committed_keeps_the_new_python(tmp_path):
    root = upgrade_setup(tmp_path)
    proc = run(root, "upgrade.cmd", "--yes", env=base_env(tmp_path, STANDIN_EXIT="11"))
    assert proc.returncode == 3, out(proc)
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "new"
    assert "Run install.bat again to finish" in proc.stdout


def test_runtime_upgrade_changes_nothing_while_python_is_in_use(tmp_path):
    root = upgrade_setup(tmp_path)
    holder = open(root / "python_embedded" / "which.txt", "rb")     # like a running Hermes
    try:
        proc = run(root, "upgrade.cmd", "--yes", env=base_env(tmp_path, STANDIN_EXIT="0"))
    finally:
        holder.close()
    assert proc.returncode == 1, out(proc)
    assert "Close Hermes (GUI, CLI, gateway) and run UPDATE.bat again" in proc.stdout
    assert "Nothing was changed" in proc.stdout
    assert "STAND-IN" not in proc.stdout
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "old"
    assert not list(root.glob("python_embedded.*"))


def test_runtime_upgrade_asks_and_no_changes_nothing(tmp_path):
    root = upgrade_setup(tmp_path)
    env = base_env(tmp_path, STANDIN_EXIT="0", HERMES_PORTABLE_NONINTERACTIVE=None)
    proc = run(root, "upgrade.cmd", "", env=env, stdin="n\n")
    assert proc.returncode == 5, out(proc)
    assert "Upgrade the portable Python to" in proc.stdout
    assert "Nothing was changed" in proc.stdout and "STAND-IN" not in proc.stdout
    assert not list(root.glob("python_embedded.*"))
    assert not (root / ".portable" / "runtime-plan.cmd").exists()


@pytest.mark.parametrize("had_note", [True, False])
def test_failed_upgrade_puts_the_pending_package_note_back_byte_for_byte(tmp_path, had_note):
    """The stand-in changes .portable\\deps-pending.json the way the new core's
    package step would, then fails before the core commits."""
    root = upgrade_setup(tmp_path)
    note = root / ".portable" / "deps-pending.json"
    before = b'{"packages": ["requests==2.31.0"]}\r\n'
    if had_note:
        note.parent.mkdir()
        note.write_bytes(before)
    env = base_env(tmp_path, STANDIN_EXIT="1", STANDIN_DEPS="1")
    proc = run(root, "upgrade.cmd", "--yes", env=env)
    assert proc.returncode == 1, out(proc)
    assert "upgrade did not complete, so it was undone" in proc.stdout
    if had_note:
        assert note.read_bytes() == before
    else:
        assert not note.exists()
    assert not (root / ".portable" / "deps-pending.before-runtime-upgrade.json").exists()
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "old"


def test_upgrade_changes_nothing_when_the_pending_package_note_cannot_be_backed_up(tmp_path):
    root = upgrade_setup(tmp_path)
    state = root / ".portable"
    state.mkdir()
    note = state / "deps-pending.json"
    note.write_bytes(b'{"packages": []}\r\n')
    stale = state / "deps-pending.before-runtime-upgrade.json"
    stale.write_bytes(b"stale\r\n")
    os.chmod(stale, stat.S_IREAD)           # copy /y onto it fails: Access is denied
    try:
        proc = run(root, "upgrade.cmd", "--yes", env=base_env(tmp_path, STANDIN_EXIT="0"))
    finally:
        os.chmod(stale, stat.S_IREAD | stat.S_IWRITE)
    assert proc.returncode == 1, out(proc)
    assert "could not be backed up. Nothing was changed." in proc.stdout
    assert "STAND-IN" not in proc.stdout
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "old"
    assert not list(root.glob("python_embedded.*"))
    assert not (state / "runtime-plan.cmd").exists()
    assert note.read_bytes() == b'{"packages": []}\r\n'
    assert stale.read_bytes() == b"stale\r\n"


# --------------------------------------------------------------------------
# an interrupted Python upgrade is finished or undone at the next start
# --------------------------------------------------------------------------

#: Ends cmd.exe itself ("exit" without /b), like closing the window or a
#: power cut in the middle of install.bat --runtime-upgrade.
INTERRUPT_INSTALL = (
    "@echo off\r\n"
    "echo STAND-IN install.bat %*\r\n"
    "if not defined STANDIN_PARTIAL goto :die\r\n"
    "mkdir \"%~dp0python_embedded\\Lib\"\r\n"
    "echo half> \"%~dp0python_embedded\\Lib\\half.txt\"\r\n"
    ":die\r\n"
    "exit 9\r\n"
)
PIN = (REPO_ROOT / "portable_hermes/manifests/python-runtime.txt").read_text().strip()
PLAN = Path(".portable") / "runtime-plan.cmd"
RESUME = Path(".portable") / "runtime-resume.cmd"


def interrupted_upgrade(tmp_path, partial: bool = False):
    root = upgrade_setup(tmp_path)
    (root / "install.bat").write_bytes(INTERRUPT_INSTALL.encode("ascii"))
    env = base_env(tmp_path, STANDIN_PARTIAL="1" if partial else None)
    proc = run(root, "upgrade.cmd", "", env=env)
    assert proc.returncode == 9, out(proc)
    assert (root / PLAN).is_file()
    old = list(root.glob("python_embedded.old-*"))
    assert len(old) == 1 and (old[0] / "which.txt").read_text().strip() == "old"
    assert (root / "python_embedded").exists() is partial
    assert not (root / "python_embedded" / "python.exe").exists()
    (root / "install.bat").write_bytes(UPGRADE_INSTALL.encode("ascii"))
    return root, old[0].name


@pytest.mark.parametrize("partial", [False, True])
def test_interrupted_runtime_upgrade_is_finished_at_the_next_start(tmp_path, partial):
    root, old = interrupted_upgrade(tmp_path, partial)
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path, STANDIN_EXIT="0"))
    assert proc.returncode == 0, out(proc)
    text = proc.stdout
    assert "An upgrade of the portable Python was interrupted" in text
    assert "installed again from the beginning" in text
    assert "Upgrade the portable Python to" not in text            # never asked again
    assert "STALE-RUNTIME-PRESENT" not in text                     # built from nothing
    assert text.index("STAND-IN install.bat --runtime-upgrade") < text.index("STUB_ARGS")
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "new"
    assert (root / old / "which.txt").read_text().strip() == "old"
    assert not (root / PLAN).exists() and not (root / RESUME).exists()
    aside = root / f"python_embedded.failed-{PIN}"
    assert (aside / "Lib" / "half.txt").is_file() is partial       # set aside, not deleted


@pytest.mark.parametrize("partial", [False, True])
def test_interrupted_runtime_upgrade_that_fails_again_puts_the_previous_python_back(
        tmp_path, partial):
    root, old = interrupted_upgrade(tmp_path, partial)
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path, STANDIN_EXIT="1"))
    assert proc.returncode == 0, out(proc)               # Hermes starts on the previous Python
    text = proc.stdout
    assert "upgrade did not complete, so it was undone" in text
    assert text.index("so it was undone") < text.index("STUB_ARGS")
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "old"
    assert not (root / old).exists()
    failed = root / f"python_embedded.failed-{PIN}"
    if partial:
        assert (failed / "Lib" / "half.txt").is_file()
        failed = root / f"python_embedded.failed-{PIN}-2"
    assert (failed / "which.txt").read_text().strip() == "new"
    assert not (root / PLAN).exists() and not (root / RESUME).exists()


def test_interrupted_undo_is_finished(tmp_path):
    root, old = interrupted_upgrade(tmp_path)
    shutil.copytree(tmp_path / "spare-runtime", root / "python_embedded")
    (root / "python_embedded" / "which.txt").write_text("new\n", encoding="ascii")
    with open(root / PLAN, "ab") as plan:
        plan.write(b'set "PH_UNDOING=1"\r\n')
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path, STANDIN_EXIT="0"))
    assert proc.returncode == 0, out(proc)
    assert "The upgrade was being undone" in proc.stdout
    assert "STAND-IN" not in proc.stdout                           # no new attempt
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "old"
    assert (root / f"python_embedded.failed-{PIN}" / "which.txt").read_text().strip() == "new"
    assert not (root / PLAN).exists()


@pytest.mark.parametrize("standin_exit, expected_rc", [("0", 0), ("1", 1)])
def test_interrupted_upgrade_after_the_core_committed_only_goes_forward(
        tmp_path, standin_exit, expected_rc):
    root, old = interrupted_upgrade(tmp_path)
    shutil.copytree(tmp_path / "spare-runtime", root / "python_embedded")
    (root / "python_embedded" / "which.txt").write_text("new\n", encoding="ascii")
    (root / ".portable" / "core-state.json").write_text(
        json.dumps({"commit": "x", "python": PIN}), encoding="utf-8")
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path, STANDIN_EXIT=standin_exit))
    assert proc.returncode == expected_rc, out(proc)
    text = proc.stdout
    assert f"already installed with Python {PIN}" in text
    assert "STALE-RUNTIME-PRESENT" in text                         # kept, not set aside
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "new"
    assert (root / old / "which.txt").read_text().strip() == "old"
    assert not list(root.glob("python_embedded.failed-*"))         # never undone
    assert not (root / PLAN).exists()
    if expected_rc:
        assert "Run install.bat again to finish" in text
        assert "Hermes was not started" in text and "STUB_ARGS" not in text
    else:
        assert "STUB_ARGS" in text


def test_upgrade_interrupted_before_anything_moved_changes_nothing(tmp_path):
    root = upgrade_setup(tmp_path)
    runtime.write_plan_file(root, runtime.plan(root, "3.13.12", PIN))
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path, STANDIN_EXIT="0"))
    assert proc.returncode == 0, out(proc)
    assert "stopped before anything was moved" in proc.stdout
    assert "STAND-IN" not in proc.stdout and "STUB_ARGS" in proc.stdout
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "old"
    assert not list(root.glob("python_embedded.*")) and not (root / PLAN).exists()


def test_unreadable_note_of_an_upgrade_that_never_started_is_set_aside(tmp_path):
    """An empty or cut-off note while python_embedded is in place and no
    python_embedded.old-* exists: nothing was renamed, so Hermes starts."""
    root = upgrade_setup(tmp_path)
    (root / ".portable").mkdir()
    notes = [(b"", "runtime-plan.unreadable.cmd"),
             (b'@rem written by portable_hermes runtime plan\r\nset "PH_OLD',
              "runtime-plan.unreadable-2.cmd")]
    for content, aside in notes:
        (root / PLAN).write_bytes(content)
        proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path, STANDIN_EXIT="0"))
        assert proc.returncode == 0, out(proc)
        assert ("An unreadable note of a Python upgrade that had not started was set aside "
                f"(.portable\\{aside}). Nothing was changed.") in proc.stdout
        assert "STAND-IN" not in proc.stdout and "STUB_ARGS" in proc.stdout
        assert not (root / PLAN).exists()
        assert (root / ".portable" / aside).read_bytes() == content     # renamed, not deleted
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "old"
    assert not list(root.glob("python_embedded.*"))


@pytest.mark.parametrize("situation", ["previous python aside", "no python"])
def test_unreadable_note_still_stops_the_launch_when_something_may_have_moved(
        tmp_path, situation):
    if situation == "no python":
        root = make_install(tmp_path, runtime=False)
    else:
        root = upgrade_setup(tmp_path)
        (root / "python_embedded.old-3.13.12").mkdir()
    (root / ".portable").mkdir()
    (root / PLAN).write_bytes(b"")
    proc = run(root, "hermes.bat", "chat", env=base_env(tmp_path, STANDIN_EXIT="0"))
    assert proc.returncode == 1, out(proc)
    assert "cannot be read. Hermes was not started." in " ".join(proc.stdout.split())
    assert "STUB_ARGS" not in proc.stdout and "set aside" not in proc.stdout
    assert (root / PLAN).read_bytes() == b""                       # kept for the next start
    assert not list((root / ".portable").glob("runtime-plan.unreadable*"))


def test_hidden_gui_start_opens_a_window_to_finish_an_interrupted_upgrade(tmp_path):
    """hermes_gui.vbs starts the GUI without a window: the resume must not run
    there. prepare.cmd opens START.bat in a new console window instead, where
    the upgrade is finished and its messages can be read."""
    root, old = interrupted_upgrade(tmp_path)
    env = base_env(tmp_path, STANDIN_EXIT="0", HERMES_PORTABLE_HIDDEN="1")
    proc = run(root, "hermes_gui.bat", "", env=env)
    assert proc.returncode == 1, out(proc)
    assert "STAND-IN" not in out(proc) and "interrupted" not in out(proc)
    deadline = time.monotonic() + 240
    while (root / PLAN).exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not (root / PLAN).exists(), "the visible window did not finish the upgrade"
    assert (root / "python_embedded" / "which.txt").read_text().strip() == "new"
    assert (root / old / "which.txt").read_text().strip() == "old"


# --------------------------------------------------------------------------
# install.bat blocks, run for real (never the whole installer)
# --------------------------------------------------------------------------

def installer_block(start: str, end: str) -> str:
    text = (REPO_ROOT / "install.bat").read_text(encoding="ascii")
    return text[text.index(start):text.index(end)]


def run_driver(tmp_path: Path, name: str, text: str, env: dict) -> subprocess.CompletedProcess:
    bat = tmp_path / name
    bat.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))
    return subprocess.run(f'cmd.exe /d /s /c ""{bat}""', cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=120)


def test_install_step_6b_writes_run_py_sh_with_unix_line_endings(tmp_path):
    """The real step-6b lines of install.bat, with delayed expansion on as in
    install.bat, a real Python, and an install folder with awkward characters."""
    step = installer_block("echo [STEP 6b]", ":: Step 7:")
    folder = tmp_path / AWKWARD
    folder.mkdir()
    head = ("@echo off\nsetlocal enabledelayedexpansion\n"
            f'set "PYTHON_EXE={sys.executable}"\n')
    proc = run_driver(tmp_path, "step6b.cmd",
                      head + f'set "PH_ROOT={folder}"\n' + step + "exit /b 0\n",
                      base_env(tmp_path))
    assert "[OK] run_py.sh created." in proc.stdout, out(proc)
    data = (folder / "run_py.sh").read_bytes()
    assert data.split(b"\n")[0] == b"#!/bin/bash"
    assert data == b'#!/bin/bash\n"$(dirname "$0")/python_embedded/python.exe" "$@"\n'
    assert b"\r" not in data
    # A step that fails says so, and never prints [OK].
    proc = run_driver(tmp_path, "step6b-fail.cmd",
                      head + f'set "PH_ROOT={tmp_path / "missing folder"}"\n' + step
                      + "exit /b 0\n", base_env(tmp_path))
    assert "[WARN] run_py.sh could not be written" in proc.stdout, out(proc)
    assert "[OK]" not in proc.stdout


def step1_driver(root: Path, archive: Path | str) -> str:
    """The real step-1 and step-2 lines of install.bat (move leftovers aside,
    download, extract, configure, rename) and its download subroutine,
    downloading from a local file:// URL (or a local test server's URL) so no
    network is used."""
    block = installer_block(":: A python_embedded folder without python.exe",
                            ":: Step 3: Bootstrap pip")
    url = archive if isinstance(archive, str) else archive.as_uri()
    head = ("@echo off\nsetlocal enabledelayedexpansion\n"
            f'set "PH_ROOT={root}"\n'
            f'set "PYTHON_DIR={root / "python_embedded"}"\n'
            f'set "PYTHON_EXE={root / "python_embedded" / "python.exe"}"\n'
            f'set "PYTHON_STAGE={root / "python_embedded.extracting"}"\n'
            f'set "PYTHON_ZIP={root / "python_embedded.zip"}"\n'
            f'set "PYTHON_URL={url}"\n'
            'set "PYTHON_VERSION=3.14.9"\nset "PYTHON_MINOR=314"\n')
    return (head + block + "echo REACHED-END\nexit /b 0\n" + DOWNLOAD_SUBROUTINE
            + ":fail\necho REACHED-FAIL\nexit /b 1\n")


#: install.bat's download subroutine, from its header comment up to ":fail".
DOWNLOAD_SUBROUTINE = installer_block(":: call :download - fetch", "\n:fail") + "\n"


def embed_zip(path: Path) -> Path:
    """A stand-in for the embeddable Python ZIP (what steps 1 and 2 need)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("python.exe", b"stand-in for the embeddable python.exe")
        zf.writestr("python314._pth", "python314.zip\n.\n")
        zf.writestr("python314.zip", b"stand-in standard library")
    return path


def test_every_installer_download_goes_through_the_retrying_subroutine():
    text = (REPO_ROOT / "install.bat").read_text(encoding="ascii")
    assert text.count("DownloadFile(") == 1 and ".DownloadFile($env:PH_URL, $part)" in text
    assert text.count("call :download\n") == 3
    for url_var in ("%PYTHON_URL%", "https://bootstrap.pypa.io/get-pip.py", "%TCLTK_URL%"):
        step = text[text.index(f'set "PH_URL={url_var}"'):]
        assert step.index("call :download") < step.index("goto :fail"), url_var
    # The subroutine sits between the end of the install and :fail, so the
    # installer still ends with its single failure exit.
    assert text.index("exit /b 0\n\n:: ===") < text.index("\n:download\n") < text.index("\n:fail\n")


def test_installer_retries_a_dropped_download(tmp_path, scripted_server):
    """A reset connection, a cut-off body and a 503, then the real file: the
    download is retried with growing pauses and only the complete file is used.

    .NET itself sends a GET once more after a connection reset before any
    answer, so the reset may not reach the retry loop; the cut-off body does:
    WebClient reports it as a success, and the size check catches it."""
    data = embed_zip(tmp_path / "src" / "python-3.14.9-embed-amd64.zip").read_bytes()
    server = scripted_server(data, ["reset", "truncate", 503])
    root = tmp_path / "inst"
    root.mkdir()
    started = time.monotonic()
    proc = run_driver(tmp_path, "step1-retry.cmd", step1_driver(root, server.url),
                      base_env(tmp_path))
    elapsed = time.monotonic() - started
    assert proc.returncode == 0 and "REACHED-END" in proc.stdout, out(proc)
    lines = [line.strip() for line in proc.stdout.splitlines()]
    retries = [line for line in lines if line.startswith("download failed (")]
    assert len(retries) in (2, 3), out(proc)
    assert [line.rsplit("; ", 1)[1] for line in retries] == [
        f"trying again ({n} of 4) ..." for n in range(2, 2 + len(retries))]
    assert any(f"the connection closed after {len(data) // 2} of {len(data)} bytes" in line
               for line in retries)
    assert "(503) Server Unavailable" in retries[-1]
    assert "[OK] Embedded Python 3.14.9 ready." in proc.stdout
    assert server.hits == 4 and elapsed >= sum((2, 5, 10)[:len(retries)])
    assert sorted(p.name for p in root.iterdir()) == ["python_embedded"]


def test_installer_gives_up_after_four_failed_downloads(tmp_path, scripted_server):
    server = scripted_server(b"never sent", [503] * 4)
    root = tmp_path / "inst"
    root.mkdir()
    proc = run_driver(tmp_path, "step1-down.cmd", step1_driver(root, server.url),
                      base_env(tmp_path))
    assert proc.returncode == 1 and "REACHED-FAIL" in proc.stdout, out(proc)
    assert proc.stdout.count("trying again (") == 3
    assert "gave up after 4 attempts." in proc.stdout
    assert "ERROR: Failed to download Python. Check your internet connection." in proc.stdout
    assert "Extracting" not in proc.stdout
    assert server.hits == 4
    assert list(root.iterdir()) == []                       # no partial download left


def test_installer_does_not_retry_a_missing_file(tmp_path, scripted_server):
    server = scripted_server(b"never sent", [404])
    root = tmp_path / "inst"
    root.mkdir()
    proc = run_driver(tmp_path, "step1-404.cmd", step1_driver(root, server.url),
                      base_env(tmp_path))
    assert proc.returncode == 1 and "REACHED-FAIL" in proc.stdout, out(proc)
    assert "trying again" not in proc.stdout and "not retried." in proc.stdout
    assert "ERROR: Failed to download Python. Check your internet connection." in proc.stdout
    assert server.hits == 1 and list(root.iterdir()) == []


def test_installer_never_extracts_into_a_leftover_staging_folder(tmp_path):
    """A python_embedded.extracting left by an earlier attempt at another
    Python version is moved aside, never mixed into the new runtime."""
    archive = embed_zip(tmp_path / "src" / "python-3.14.9-embed-amd64.zip")
    root = tmp_path / "inst"
    (root / "python_embedded").mkdir(parents=True)          # incomplete: no python.exe
    (root / "python_embedded" / "half.txt").write_text("half\n", encoding="ascii")
    stage = root / "python_embedded.extracting"
    stage.mkdir()
    (stage / "python313._pth").write_text("stale\n", encoding="ascii")
    (stage / "python313.zip").write_bytes(b"stale")
    proc = run_driver(tmp_path, "step1.cmd", step1_driver(root, archive), base_env(tmp_path))
    assert proc.returncode == 0 and "REACHED-END" in proc.stdout, out(proc)
    assert ("[INFO] An incomplete python_embedded folder was moved to "
            "python_embedded.incomplete.") in proc.stdout
    assert ("[INFO] An unfinished python_embedded.extracting folder was moved to "
            "python_embedded.incomplete-2.") in proc.stdout
    assert "[OK] Embedded Python 3.14.9 ready." in proc.stdout
    assert (root / "python_embedded.incomplete" / "half.txt").is_file()
    assert (root / "python_embedded.incomplete-2" / "python313._pth").read_text() == "stale\n"
    runtime_dir = root / "python_embedded"
    assert sorted(p.name for p in runtime_dir.iterdir()) == [
        "DLLs", "Lib", "python.exe", "python314._pth", "python314.zip"]
    assert (runtime_dir / "python314._pth").read_text(encoding="ascii").splitlines() == [
        "python314.zip", ".", "Lib", "Lib\\site-packages", "DLLs", "", "import site"]
    assert not stage.exists()
    # Moved-aside runtimes are user data for every updater (never removed).
    assert ownership.is_user("python_embedded.incomplete-2/python313._pth")
    assert ownership.is_user("python_embedded.extracting/python313._pth")
    # A staging folder that cannot be moved (a program holds a file in it)
    # stops setup before anything is downloaded or extracted.
    root2 = tmp_path / "inst2"
    (root2 / "python_embedded.extracting").mkdir(parents=True)
    held = root2 / "python_embedded.extracting" / "python313._pth"
    held.write_text("stale\n", encoding="ascii")
    with open(held, "rb"):
        proc = run_driver(tmp_path, "step1-held.cmd", step1_driver(root2, archive),
                          base_env(tmp_path))
    assert proc.returncode == 1 and "REACHED-FAIL" in proc.stdout, out(proc)
    assert ("python_embedded.extracting could not be moved aside."
            in " ".join(proc.stdout.split()))
    assert "[STEP 1/10]" not in proc.stdout
    assert sorted(p.name for p in root2.iterdir()) == ["python_embedded.extracting"]


def test_installer_settles_an_interrupted_upgrade_before_installing(tmp_path):
    """The real resume block of install.bat with a stand-in runtime.cmd."""
    block = installer_block("if not defined PH_UPGRADE if exist", "if not defined PH_PYTHON_PIN")
    launch = tmp_path / "portable_hermes" / "launch"
    launch.mkdir(parents=True)
    (launch / "runtime.cmd").write_bytes(
        b"@echo off\r\necho STAND-IN runtime.cmd %*\r\nexit /b 3\r\n")
    (tmp_path / ".portable").mkdir()
    head = ("@echo off\nsetlocal enabledelayedexpansion\n"
            f'set "PH_STATE={tmp_path / ".portable"}"\nset "PH_UPGRADE=%~1"\n')
    driver = head + block + "echo FELL-THROUGH\nexit /b 0\n"
    env = base_env(tmp_path)
    proc = run_driver(tmp_path, "resume.cmd", driver, env)
    assert proc.returncode == 0 and "FELL-THROUGH" in proc.stdout, out(proc)
    (tmp_path / PLAN).write_bytes(b'set "PH_OLD_NAME=python_embedded.old-3.13.12"\r\n')
    proc = run_driver(tmp_path, "resume.cmd", driver, env)
    assert proc.returncode == 3, out(proc)
    assert "STAND-IN runtime.cmd resume" in proc.stdout
    assert "FELL-THROUGH" not in proc.stdout


def test_runtime_upgrade_install_ends_without_the_first_install_text(tmp_path):
    """The real end of install.bat. Seen in a real upgrade: "Installation
    complete ... First time?" right before runtime.cmd's upgrade summary."""
    block = installer_block(":: A Python upgrade ends with the summary", "\n:fail")
    assert "First time?" in block and "goto :install_finished" in block
    head = ('@echo off\nsetlocal enabledelayedexpansion\nset "PH_PAUSE="\n'
            'set "PYTHON_VERSION=3.14.9"\n')
    for upgrade, first_install in (("", True), ("1", False)):
        proc = run_driver(tmp_path, f"end-{upgrade or 'first'}.cmd",
                          head + f'set "PH_UPGRADE={upgrade}"\n' + block, base_env(tmp_path))
        assert proc.returncode == 0, out(proc)
        assert ("Installation complete." in proc.stdout) is first_install, out(proc)
        assert ("First time?" in proc.stdout) is first_install, out(proc)


# --------------------------------------------------------------------------
# v1.4.18 launchers replaced while they run
# --------------------------------------------------------------------------

def legacy_bytes(rel: str) -> bytes:
    try:
        raw = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"v1.4.18:{rel}"],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        # In CI the tag is fetched on purpose: never skip these tests there.
        (pytest.fail if IN_CI else pytest.skip)(
            "the v1.4.18 tag is not available in this checkout "
            "(git fetch origin tag v1.4.18 --no-tags)")
    return raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def swap_line(old: bytes, marker: bytes, command: str) -> bytes:
    """Replace the line containing *marker* by *command* padded to the same length."""
    start = old.index(marker)
    start = old.rindex(b"\r\n", 0, start) + 2
    end = old.index(b"\r\n", start)
    width = end - start
    cmd = command.encode("ascii")
    assert len(cmd) <= width, (command, width)
    return old[:start] + cmd + b" " * (width - len(cmd)) + old[end:]


@pytest.mark.parametrize("bat, marker, expected_offset", [
    ("UPDATE.bat", b"-m hermes_cli.main update", 1200),
    ("hermes.bat", b'"%PYTHON_EXE%" -m hermes_cli.main %*', 3650),
    ("hermes_gui.bat", b"from gui.app import main", 1136),
])
def test_v1_4_18_launcher_replaced_while_running_ends_cleanly(tmp_path, bat, marker,
                                                             expected_offset):
    root = tmp_path / "inst"
    (root / "python_embedded").mkdir(parents=True)
    # A real, harmless program as python.exe: the old scripts only check it exists.
    shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "hostname.exe",
                 root / "python_embedded" / "python.exe")
    (root / "new").mkdir()
    shutil.copy2(REPO_ROOT / bat, root / "new" / bat)
    old = legacy_bytes(bat)
    patched = swap_line(old, marker, f"copy/y new\\{bat} {bat}>nul")
    assert len(patched) == len(old)
    resume = patched.index(b"\r\n", patched.index(f"copy/y new\\{bat}".encode())) + 2
    assert resume == expected_offset
    (root / bat).write_bytes(patched)
    proc = subprocess.run(f'cmd.exe /d /s /c ""{root / bat}""', cwd=str(root),
                          env=base_env(tmp_path), input="\n\n\n", capture_output=True,
                          text=True, timeout=120)
    text = out(proc)
    assert (root / bat).read_bytes() == (REPO_ROOT / bat).read_bytes()
    assert NOT_RECOGNIZED not in text, text
    assert "Update finished with problems" not in text
    assert "The syntax of the command is incorrect" not in text
    if bat == "UPDATE.bat":
        assert "Run UPDATE.bat once more" in text, text
        assert proc.returncode == 0


def test_the_round_one_launchers_would_have_failed_this_way(tmp_path):
    """Control: the same swap onto a long launcher reproduces the reported
    breakage, so the test above would notice a regression."""
    root = tmp_path / "inst"
    (root / "python_embedded").mkdir(parents=True)
    shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "hostname.exe",
                 root / "python_embedded" / "python.exe")
    (root / "new").mkdir()
    long_launcher = (b"@echo off\r\n" + b"rem " + b"x" * 1300 + b"\r\n"
                     + b"MES_ROOT=%~dp0\r\necho finished-badly\r\n")
    (root / "new" / "UPDATE.bat").write_bytes(long_launcher)
    old = legacy_bytes("UPDATE.bat")
    (root / "UPDATE.bat").write_bytes(
        swap_line(old, b"-m hermes_cli.main update", "copy/y new\\UPDATE.bat UPDATE.bat>nul"))
    proc = subprocess.run(f'cmd.exe /d /s /c ""{root / "UPDATE.bat"}""', cwd=str(root),
                          env=base_env(tmp_path), input="\n\n\n", capture_output=True,
                          text=True, timeout=120)
    assert NOT_RECOGNIZED in out(proc) or "finished-badly" in out(proc)
