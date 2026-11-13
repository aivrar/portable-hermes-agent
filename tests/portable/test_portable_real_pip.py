"""Real pip, real .pyd: changing packages while another process has them loaded.

Hermes can run the core update from inside the GUI (the update_hermes tool),
so pip changes packages whose compiled extensions (.pyd) the GUI process has
loaded. Windows does not let a loaded DLL be deleted. This test does exactly
that with a small package that ships a .pyd (MarkupSafe), in a throw-away
venv, and checks what the lifecycle reports and restores.

Opt-in, because it downloads two MarkupSafe wheels from PyPI:

    set HERMES_PORTABLE_REAL_PIP=1
    python -m pytest tests/portable/test_portable_real_pip.py -s

``-s`` prints every pip command and its full output.
"""

from __future__ import annotations

import json
import os
import subprocess
import venv
from pathlib import Path

import pytest

from portable_hermes import common
from portable_hermes.core import CoreLifecycle

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows file locking"),
    pytest.mark.skipif(not os.environ.get("HERMES_PORTABLE_REAL_PIP"),
                       reason="downloads from PyPI; set HERMES_PORTABLE_REAL_PIP=1"),
]

OLD, NEW = "3.0.1", "3.0.2"


def test_package_change_while_its_pyd_is_loaded(tmp_path):
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True)             # pip from the bundled wheel
    python = env_dir / "Scripts" / "python.exe"
    root = tmp_path / "root"
    (root / ".portable").mkdir(parents=True)
    life = CoreLifecycle(root, python=str(python), quiet=False)
    log: list[tuple[list[str], int, str]] = []
    real_pip = life._run_pip

    def recording_pip(args, timeout=3600):
        rc, out = real_pip(args, timeout)
        log.append((list(args), rc, out))
        print(f"\n$ pip {' '.join(args)}\n(exit {rc})\n{out.strip()}")
        return rc, out

    life._run_pip = recording_pip
    rc, out = recording_pip(["install", "--no-input", f"markupsafe=={OLD}"])
    assert rc == 0, out

    holder = subprocess.Popen(
        [str(python), "-c", "import markupsafe._speedups as s, sys, time; "
                            "print(s.__file__, flush=True); time.sleep(600)"],
        stdout=subprocess.PIPE, text=True, env=common.clean_python_env())
    try:
        pyd = Path(holder.stdout.readline().strip())
        assert pyd.suffix == ".pyd" and pyd.is_file()
        print(f"\nloaded by process {holder.pid}: {pyd}")

        plan = {"strategy": "pyproject", "requirements": [f"markupsafe=={NEW}"],
                "wrapper_requirements": [], "extras": [], "missing_extras": []}
        work = tmp_path / "work"
        work.mkdir()
        ctx: dict = {}
        try:
            report = life._install_dependencies(plan, work, "fingerprint-new", ctx)
            installed = True
        except common.UpdateError as exc:
            report, installed = ctx["deps"], False
            print(f"\ninstall failed: {exc.reason}")
        assert report["before"]["markupsafe"] == OLD
        assert life.deps_marker_path.is_file()            # journaled until settled
        marker = json.loads(life.deps_marker_path.read_text(encoding="utf-8"))
        assert marker["before"]["markupsafe"] == OLD
        after_install = life._pip_list().get("markupsafe")
        print(f"\nafter the install attempt: markupsafe {after_install} "
              f"(install {'succeeded' if installed else 'failed'})")

        # Undo, as a failed verification would: restore the previous set.
        restored = life._restore_dependencies(report)
        final = life._pip_list().get("markupsafe")
        print(f"\nrestore: {report.get('restore')}; restored={restored}; "
              f"markupsafe now {final}; not restored: {report.get('not_restored')}")
        leftovers = sorted(p.name for p in pyd.parent.parent.glob("~*"))
        print(f"pip leftovers in site-packages: {leftovers}")
        # The invariant that matters: the report is true.
        if restored:
            assert final == OLD
            assert not life.deps_marker_path.exists()
        else:
            assert final != OLD or report.get("not_restored")
            assert life.deps_marker_path.is_file()
    finally:
        holder.kill()
        holder.wait()
    # With the holder gone, a retry always settles it.
    if life.deps_marker_path.exists():
        assert life._restore_dependencies(dict(report)) is True
    assert life._pip_list().get("markupsafe") == OLD
