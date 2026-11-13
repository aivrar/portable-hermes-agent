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

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from portable_hermes import common

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows launchers")

REPO_ROOT = Path(__file__).resolve().parents[2]
TRAMPOLINES = ("hermes.bat", "hermes_gui.bat", "START.bat", "UPDATE.bat")
AWKWARD = "Portable Hermes & (test) 'q' [1] ,;="

STUB_CLI = (
    "import json, os, sys\n"
    "print('STUB_ARGS=' + json.dumps(sys.argv[1:]))\n"
    "print('STUB_HOME=' + os.environ.get('HERMES_HOME', ''))\n"
    "print('STUB_OPENAI=' + os.environ.get('OPENAI_API_KEY', '<unset>'))\n"
    "sys.exit(int(os.environ.get('STUB_EXIT', '0')))\n"
)


def make_runtime(folder: Path) -> None:
    """A real interpreter at folder/python.exe (venv redirector + pyvenv.cfg).

    Built under a plain name and moved into place: venv refuses paths with ;
    and the venv does not record its own location."""
    build = folder.parent.parent / f"venv-build-{os.getpid()}-{id(folder)}"
    venv.create(build, with_pip=False)
    shutil.copy2(build / "Scripts" / "python.exe", build / "python.exe")
    os.rename(build, folder)


def make_install(base: Path, name: str = AWKWARD, *, runtime: bool = True) -> Path:
    root = base / name
    root.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "portable_hermes", root / "portable_hermes",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for bat in TRAMPOLINES:
        shutil.copy2(REPO_ROOT / bat, root / bat)
    (root / "hermes_cli").mkdir()
    (root / "hermes_cli" / "__init__.py").write_text("")
    (root / "hermes_cli" / "main.py").write_text(STUB_CLI)
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
        assert first.endswith(b"& call exit /b %%errorlevel%%")
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


# --------------------------------------------------------------------------
# runtime.cmd: the in-place Python upgrade (install.bat is a stand-in)
# --------------------------------------------------------------------------

DRIVER = (
    "@echo off\r\n"
    "setlocal disabledelayedexpansion\r\n"
    "for %%I in (\"%~dp0.\") do set \"PH_ROOT=%%~fI\"\r\n"
    "pushd \"%~dp0\"\r\n"
    "call .\\portable_hermes\\launch\\env.cmd %*\r\n"
    "call .\\portable_hermes\\launch\\runtime.cmd\r\n"
    "call exit /b %%errorlevel%%\r\n"
)

UPGRADE_INSTALL = (
    "@echo off\r\n"
    "echo STAND-IN install.bat %*\r\n"
    "if exist \"%~dp0python_embedded\" echo STALE-RUNTIME-PRESENT\r\n"
    "xcopy /e /i /q \"%~dp0..\\spare-runtime\" \"%~dp0python_embedded\" >nul\r\n"
    "echo new> \"%~dp0python_embedded\\which.txt\"\r\n"
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


# --------------------------------------------------------------------------
# v1.4.18 launchers replaced while they run
# --------------------------------------------------------------------------

def legacy_bytes(rel: str) -> bytes:
    try:
        raw = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"v1.4.18:{rel}"],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("the v1.4.18 tag is not available in this checkout")
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
