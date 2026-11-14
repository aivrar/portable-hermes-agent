"""The journaled swap, standalone recovery, and what a journal may touch.

Fault injection kills the swap (a BaseException, like the process dying) at
every rename/link it performs; the recovery then runs as the launchers run
it: ``.portable/recover.py`` in a fresh interpreter that cannot import
``portable_hermes``. The result must be byte-identical to the tree before the
update, or, once the journal says "committed", to the tree after it.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from portable_hermes import common, ownership, recovery

REPO_ROOT = Path(__file__).resolve().parents[2]


class Killed(BaseException):
    """The process dying: not an OSError, so the swap's own undo never runs."""


def write(root: Path, files: dict) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def tree(root: Path) -> dict:
    """Every file outside .portable, plus the channel state files, by content."""
    out = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".portable/") and rel not in recovery.STATE_RELS:
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def all_files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def dirs(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_dir() and not p.relative_to(root).as_posix().startswith(".portable")}


def run_recover_script(root: Path, *, extra_env=None) -> subprocess.CompletedProcess:
    """The launchers' recovery: isolated, no site (no .pth, so no editable
    install of this repo), with nothing from portable_hermes importable."""
    env = dict(os.environ, **(extra_env or {}))
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, "-I", "-S", str(root / ".portable" / "recover.py"),
                           str(root)], capture_output=True, text=True, env=env, timeout=120)


BEFORE = {
    "keep.txt": b"untouched",
    "a.txt": b"old a",                       # replaced
    "b.txt": b"old b",                       # removed
    "d.txt": b"user edit of d",              # replaced, user edit kept
    "e.txt": b"user edit of e",              # removed, user edit kept
    "pkg/old.py": b"old module",             # removed
    ".portable/core-state.json": b'{"commit": "old"}',
}
STAGED = {
    "a.txt": b"new a",
    "c/deep/new.txt": b"new c",              # added in new folders
    "d.txt": b"new d",
    "st/core-state.json": b'{"commit": "new"}',
}


def plan(root: Path) -> common.Transaction:
    write(root, BEFORE)
    staged = common.staging_dir(root) / "c"
    write(staged, STAGED)
    txn = common.Transaction(root, "core")
    txn.put("a.txt", staged / "a.txt")
    txn.put("c/deep/new.txt", staged / "c/deep/new.txt")
    txn.put("d.txt", staged / "d.txt", preserve=True)
    txn.remove("b.txt")
    txn.remove("e.txt", preserve=True)
    txn.remove("pkg/old.py")
    txn.put(".portable/core-state.json", staged / "st/core-state.json")
    return txn


AFTER = {
    "keep.txt": b"untouched", "a.txt": b"new a", "c/deep/new.txt": b"new c",
    "d.txt": b"new d", ".portable/core-state.json": b'{"commit": "new"}',
}


class Faults:
    """Patch os.replace/os.link; die at call number *index* (0: never)."""

    def __init__(self, monkeypatch, index: int, *, links: bool):
        self.calls, self.index, self.links = 0, index, links
        self.real_replace, self.real_link = os.replace, os.link
        self.monkeypatch = monkeypatch
        monkeypatch.setattr(os, "replace", self.replace)
        monkeypatch.setattr(os, "link", self.link)

    def _tick(self):
        self.calls += 1
        if self.calls == self.index:
            raise Killed()

    def replace(self, *a, **k):
        self._tick()
        return self.real_replace(*a, **k)

    def link(self, *a, **k):
        if not self.links:
            raise OSError("hard links are not supported on this drive")
        self._tick()
        return self.real_link(*a, **k)

    def undo(self):
        self.monkeypatch.setattr(os, "replace", self.real_replace)
        self.monkeypatch.setattr(os, "link", self.real_link)


def fault_points(tmp_path, monkeypatch, links: bool) -> int:
    """How many renames/links one complete apply + commit performs."""
    txn = plan(tmp_path / f"count-{links}")
    faults = Faults(monkeypatch, 0, links=links)
    try:
        txn.apply()
        txn.commit()
    finally:
        faults.undo()
    return faults.calls


AFTER_NO_PORTABLE = {k: v for k, v in AFTER.items() if not k.startswith(".portable/")}


def all_files_without_portable(root: Path) -> dict:
    return {k: v for k, v in all_files(root).items() if not k.startswith(".portable/")}


@pytest.mark.parametrize("links", [True, False], ids=["hardlink", "copy-fallback"])
def test_a_kill_at_any_rename_is_undone_or_finished_by_the_standalone_script(
        tmp_path, monkeypatch, links):
    total = fault_points(tmp_path, monkeypatch, links)
    assert total >= 12
    outcomes = {"rolled back": 0, "finished": 0, "nothing to do": 0}
    for index in range(1, total + 1):
        root = tmp_path / f"r{index}"
        txn = plan(root)
        before, before_dirs = tree(root), dirs(root)
        faults = Faults(monkeypatch, index, links=links)
        with pytest.raises(Killed):
            txn.apply()
            txn.commit()
        faults.undo()
        journal = recovery.journal_path(root)
        committed = journal.exists() and json.loads(journal.read_text())["state"] == "committed"
        if journal.exists():
            proc = run_recover_script(root)
            assert proc.returncode == 0, (index, proc.stdout, proc.stderr)
            outcomes["finished" if committed else "rolled back"] += 1
        else:
            outcomes["nothing to do"] += 1
        assert not journal.exists(), index
        assert not (root / txn.backup_rel).exists(), index
        if committed:
            assert all_files_without_portable(root) == AFTER_NO_PORTABLE, index
            assert (root / ".portable/core-state.json").read_bytes() == \
                AFTER[".portable/core-state.json"]
            kept = root / txn.keep_rel
            assert (kept / "d.txt").read_bytes() == b"user edit of d", index
            assert (kept / "e.txt").read_bytes() == b"user edit of e", index
        else:
            assert tree(root) == before, index
            assert dirs(root) == before_dirs, index      # created folders removed again
    # Every phase was really hit: before the journal, mid-swap, mid-finish.
    assert all(outcomes.values()), outcomes


def test_completed_swap_commits_with_kept_user_edits(tmp_path):
    root = tmp_path / "r"
    txn = plan(root)
    txn.apply()
    done = txn.commit()
    assert all_files_without_portable(root) == AFTER_NO_PORTABLE
    assert done["kept"] == 2 and done["keep"] == txn.keep_rel
    assert txn.keep_rel.startswith(".portable/kept/") and txn.keep_rel.endswith("-core")
    assert sorted(p.name for p in (root / txn.keep_rel).rglob("*") if p.is_file()) == \
        ["d.txt", "e.txt"]
    assert not recovery.journal_path(root).exists()


def test_recovery_script_works_without_and_despite_the_portable_package(tmp_path, monkeypatch):
    root = tmp_path / "r"
    txn = plan(root)
    before = tree(root)
    faults = Faults(monkeypatch, 6, links=True)      # mid-swap
    with pytest.raises(Killed):
        txn.apply()
    faults.undo()
    # A "portable_hermes" from another version (or half replaced) sits in the
    # root and would explode on import; the script never imports it.
    explode = b"raise SystemExit('a portable_hermes module was imported')\n"
    write(root, {"portable_hermes/__init__.py": explode, "portable_hermes/common.py": explode})
    isolated = subprocess.run([sys.executable, "-I", "-S", "-c", "import portable_hermes"],
                              capture_output=True, text=True, cwd=str(tmp_path))
    assert isolated.returncode != 0          # really not importable in the recovery run
    proc = run_recover_script(root)
    assert proc.returncode == 0 and "rolled back" in proc.stdout, proc.stdout + proc.stderr
    current = tree(root)
    del current["portable_hermes/__init__.py"], current["portable_hermes/common.py"]
    assert current == before
    # Not isolated, with the exploding package first on the path: still fine.
    root2 = tmp_path / "r2"
    plan(root2).apply()
    write(root2, {"portable_hermes/__init__.py": explode})
    env = dict(os.environ, PYTHONPATH=str(root2))
    proc = subprocess.run([sys.executable, str(root2 / ".portable/recover.py"), str(root2)],
                          capture_output=True, text=True, env=env, cwd=str(root2))
    assert proc.returncode == 0 and "rolled back" in proc.stdout, proc.stdout + proc.stderr


def test_recovery_module_imports_only_the_standard_library():
    source = (REPO_ROOT / "portable_hermes" / "recovery.py").read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in recovery.py"
            names.add((node.module or "").split(".")[0])
    assert names <= set(sys.stdlib_module_names) | {"__future__"}, names


def test_the_copy_written_before_the_swap_is_the_running_code(tmp_path):
    root = tmp_path / "r"
    txn = plan(root)
    txn.apply()
    assert (root / ".portable/recover.py").read_bytes() == \
        (REPO_ROOT / "portable_hermes/recovery.py").read_bytes()
    txn.commit()


def test_recovery_reports_another_running_update(tmp_path):
    root = tmp_path / "r"
    txn = plan(root)
    txn.apply()
    with common.InstallLock(root):
        proc = run_recover_script(root)
    assert proc.returncode == 3 and "another update" in proc.stdout
    assert recovery.journal_path(root).exists()
    assert run_recover_script(root).returncode == 0


# --------------------------------------------------------------------------
# malformed journals: refused as a whole, nothing touched
# --------------------------------------------------------------------------

def _good(root: Path) -> dict:
    return {"schema": 2, "id": "abc123", "kind": "core", "state": "applying",
            "backup": ".portable/b/abc123", "ops": [], "created_dirs": []}


def _with_op(**op):
    def make(root):
        data = _good(root)
        data["ops"] = [dict({"rel": "a.txt", "action": "remove"}, **op)]
        return data
    return make


MALFORMED = {
    "not json": lambda root: "{not json",
    "not an object": lambda root: [],
    "missing id": lambda root: {k: v for k, v in _good(root).items() if k != "id"},
    "missing ops": lambda root: {k: v for k, v in _good(root).items() if k != "ops"},
    "missing backup": lambda root: {k: v for k, v in _good(root).items() if k != "backup"},
    "old schema": lambda root: dict(_good(root), schema=1),
    "unknown state": lambda root: dict(_good(root), state="weird"),
    "backup outside .portable": lambda root: dict(_good(root), backup="../b/abc123"),
    "backup absolute": lambda root: dict(_good(root), backup=str(root / ".portable/b/abc123")),
    "backup other id": lambda root: dict(_good(root), backup=".portable/b/ffffff"),
    "keep outside kept": lambda root: dict(_good(root), keep=".portable/b/x"),
    "keep with dotdot": lambda root: dict(_good(root), keep=".portable/kept/../../x"),
    "keep nested": lambda root: dict(_good(root), keep=".portable/kept/a/b"),
    "absolute rel": _with_op(rel="C:/Windows/x.txt"),
    "rooted rel": _with_op(rel="/x.txt"),
    "backslash rel": _with_op(rel="tools\\x.py"),
    "dotdot rel": _with_op(rel="tools/../../x.txt"),
    "user data rel": _with_op(rel=".env"),
    "runtime rel": _with_op(rel="python_embedded/python.exe"),
    "set-aside runtime rel": _with_op(rel="python_embedded.old-3.13.12/python.exe"),
    "hermes home rel": _with_op(rel=".hermes/config.yaml"),
    "user data rel other case": _with_op(rel="Extensions/x.py"),
    "portable internals rel": _with_op(rel=".portable/lock"),
    "unknown action": _with_op(action="chmod"),
    "remove with src": _with_op(src=".portable/s/a.txt"),
    "replace src outside staging": _with_op(action="replace", src=".portable/b/abc123/a.txt"),
    "replace src outside root": _with_op(action="replace", src="../evil.txt"),
    "preserve without keep": _with_op(preserve=True),
    "duplicate path": lambda root: dict(_good(root), ops=[
        {"rel": "a.txt", "action": "remove"}, {"rel": "A.TXT", "action": "remove"}]),
    "created dir inside .portable": lambda root: dict(_good(root), created_dirs=[".portable/x"]),
    "created dir dotdot": lambda root: dict(_good(root), created_dirs=["../x"]),
    # Windows drops a trailing dot or space: these would land in protected
    # folders while passing the protected-name comparison.
    "hermes home with trailing dot": _with_op(rel=".hermes./config.yaml"),
    "user data with trailing space": _with_op(rel=".env "),
    "runtime with trailing dot": _with_op(rel="python_embedded./python.exe"),
    "trailing dot deeper": _with_op(rel="tools./x.py"),
    "device name": _with_op(rel="tools/NUL"),
    "device name with extension": _with_op(rel="tools/com1.txt"),
    "device name as folder": _with_op(rel="aux/x.py"),
    "forbidden character": _with_op(rel="tools/a?.py"),
    "staged src with trailing dot": _with_op(action="replace", src=".portable/s./a.txt"),
    "created dir with trailing space": lambda root: dict(_good(root), created_dirs=["tools "]),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_journal_is_refused_and_nothing_is_touched(tmp_path, case):
    root = tmp_path / "r"
    # Canaries a hostile journal would like to move or delete.
    write(root, {"a.txt": b"live", ".env": b"KEY=1", "python_embedded/python.exe": b"MZ",
                 ".portable/b/abc123/a.txt": b"backup", ".portable/b/ffffff/x": b"x",
                 ".portable/s/a.txt": b"staged", "tools/x.py": b"x",
                 ".portable/kept/a/b/k.txt": b"k"})
    (tmp_path / "evil.txt").write_bytes(b"outside")
    data = MALFORMED[case](root)
    text = data if isinstance(data, str) else json.dumps(data)
    recovery.journal_path(root).write_text(text, encoding="utf-8")
    common.state_dir(root).joinpath("recover.py").write_bytes(
        (REPO_ROOT / "portable_hermes/recovery.py").read_bytes())
    before = all_files(root)
    with pytest.raises(common.UpdateError) as info:
        common.recover(root)
    assert info.value.code == "journal_damaged"
    assert "journal.damaged.json" in info.value.reason
    proc = run_recover_script(root)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "damaged" in proc.stdout and "Nothing was changed" in proc.stdout
    after = all_files(root)
    assert after.pop(".portable/lock", b"") == b""      # the (empty) lock file may appear
    assert after == before
    assert (tmp_path / "evil.txt").read_bytes() == b"outside"


def test_journal_protected_names_mirror_the_ownership_model():
    assert recovery.PROTECTED_TOP_LEVEL == {n.lower() for n in ownership.USER_TOP_LEVEL}
    assert (recovery.PROTECTED_PREFIX,) == ownership.USER_TOP_LEVEL_PREFIXES
    assert recovery.STATE_DIR == common.STATE_DIR


def test_a_transaction_refuses_paths_differing_only_by_case(tmp_path):
    root = tmp_path / "r"
    write(root, {"a.txt": b"1"})
    write(common.staging_dir(root), {"a.txt": b"2", "b.txt": b"3"})
    txn = common.Transaction(root, "core")
    txn.put("a.txt", common.staging_dir(root) / "a.txt")
    with pytest.raises(common.UpdateError, match="planned twice"):
        txn.put("A.TXT", common.staging_dir(root) / "b.txt")


def test_a_transaction_refuses_to_plan_user_data(tmp_path):
    root = tmp_path / "r"
    write(root, {".env": b"KEY=1"})
    write(common.staging_dir(root), {"x": b"2"})
    txn = common.Transaction(root, "core")
    txn.put(".env", common.staging_dir(root) / "x")
    with pytest.raises(common.UpdateError, match="unsafe file plan"):
        txn.apply()
    assert (root / ".env").read_bytes() == b"KEY=1"
    assert not recovery.journal_path(root).exists()


# --------------------------------------------------------------------------
# archives
# --------------------------------------------------------------------------

@pytest.mark.parametrize("names", [
    ["top/a/b."], ["top/a/b "], ["top/a./b.py"],
    ["top/CON"], ["top/nul.txt"], ["top/a/COM1.py"], ["top/lpt9"], ["top/AUX.tar.gz"],
    ["top/Prn"], ["top/a/con .txt"],
    ["top/a<b"], ["top/a|b"], ["top/a?b"], ["top/a*b"], ['top/a"b'], ["top/a\x01b"],
    ["top/a/X.py", "top/a/x.py"], ["top/Readme.md", "top/README.md"],
    ["top/a/b", "top/a/B/c"],
], ids=lambda names: repr(names))
def test_safe_extract_rejects_names_windows_cannot_hold_faithfully(tmp_path, names):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("top/ok.txt", b"ok")
        for name in names:
            zf.writestr(name, b"x")
    out = tmp_path / "out"
    with pytest.raises(common.UpdateError) as info:
        common.safe_extract(archive, out, strip_top=True)
    assert info.value.code == "unsafe_archive"
    assert not out.exists() or not any(out.rglob("*"))


def test_safe_extract_accepts_ordinary_names_that_look_close(tmp_path):
    archive = tmp_path / "ok.zip"
    good = ["top/console.py", "top/nul_device.md", "top/com10.txt", "top/a.b/c.d",
            "top/skills/autonomous-ai-agents/codex/SKILL.md", "top/plugins/x/tests/t.py"]
    with zipfile.ZipFile(archive, "w") as zf:
        for name in good:
            zf.writestr(name, b"x")
    names = common.safe_extract(archive, tmp_path / "out", strip_top=True)
    assert sorted(names) == sorted(n.split("/", 1)[1] for n in good)


def test_core_exclusions_apply_only_at_the_top_level():
    for rel in ("skills/autonomous-ai-agents/codex/SKILL.md", "plugins/x/tests/test_y.py",
                "skills/a/tests/fixture.json", "optional-skills/plans/SKILL.md"):
        assert ownership.is_core_installable(rel), rel
    for rel in ("tests/test_x.py", "Tests/test_x.py", ".github/workflows/x.yml",
                "codex/x.md", "plans/p.md", "tests-js/a.js", "website/docs/a.md"):
        assert not ownership.is_core_installable(rel), rel


def test_ownership_is_case_insensitive():
    assert ownership.classify("GUI/App.py") == "wrapper"
    assert ownership.classify("Tools/LM_Studio_Tools.py") == "wrapper"
    assert ownership.classify("PYTHON_EMBEDDED/python.exe") == "user"
    assert ownership.classify("python_embedded.old-3.13.12/python.exe") == "user"
    assert ownership.classify("Python_Embedded.failed-3.14.9/Lib/x.py") == "user"
    assert ownership.classify(".ENV") == "user"
    assert ownership.classify("Extensions/tts/x.py") == "user"
    assert ownership.classify("Portable_Hermes/core.py") == "wrapper"
    assert ownership.key("Tools\\Web_Tools.py") == ownership.key("tools/web_tools.py")
    assert not ownership.is_core_installable("README.MD")
    assert not ownership.is_core_installable("GUI/app.py")
