"""Round-2 guarantees of the core and wrapper lifecycles (offline, synthetic archives).

* never lose a user's edit (core replace, wrapper replace, repair, adoption);
* dependency changes are journaled by a marker until they commit or are
  verifiably restored, and a failed restore is never reported as "kept";
* the newest core needing a newer portable Python is its own result;
* wrapper releases are compared by version; pre-evergreen ones are never
  installed or announced;
* the lock policy for first installs and updates.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from portable_hermes import bridge, common, core, ownership, runtime, wrapper
from portable_hermes.core import CoreLifecycle
from portable_hermes.wrapper import WrapperUpdater

from test_portable_lifecycle import (  # noqa: E402  (sibling helper module)
    CORE_V1, CORE_V2, NEW_WRAPPER, SHA1, SHA2, USER_FILES, WRAPPER_FILES, FakePip, FakeVerify,
    core_zip, lifecycle, protected, release_zip, snapshot, upstream_swap, with_requests,
    write_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def root(tmp_path):
    r = tmp_path / "install"
    write_files(r, WRAPPER_FILES)
    write_files(r, USER_FILES)
    return r


def files_in(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob("*") if p.is_file()}


def kept_files(root: Path, kind: str) -> dict:
    out = {}
    for folder in sorted((root / ".portable" / "kept").glob(f"*-{kind}*")):
        for path in folder.rglob("*"):
            if path.is_file():
                out[path.relative_to(folder).as_posix()] = path.read_bytes()
    return out


# --------------------------------------------------------------------------
# D. never lose a user's edit
# --------------------------------------------------------------------------

def test_core_update_keeps_a_copy_of_an_edited_file_it_replaces(root, tmp_path):
    life, _, _ = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    (root / "hermes_cli/main.py").write_bytes(b"# edited by hand\n")
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V2, SHA2, "v2.zip")))
    assert result["ok"], result
    assert (root / "hermes_cli/main.py").read_bytes() == CORE_V2["hermes_cli/main.py"]
    assert result["kept_edits_count"] == 1
    assert result["kept_edits"].startswith(".portable/kept/")
    assert kept_files(root, "core") == {"hermes_cli/main.py": b"# edited by hand\n"}
    # Unedited files are replaced without copies.
    assert "run_agent.py" not in kept_files(root, "core")


def test_core_update_keeps_an_edited_file_upstream_dropped_in_place(root, tmp_path):
    life, _, _ = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    (root / "tools/web_tools.py").write_bytes(b"# local edit\n")
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V2, SHA2, "v2.zip")))
    assert result["ok"] and result["kept_modified"] == ["tools/web_tools.py"]
    assert (root / "tools/web_tools.py").read_bytes() == b"# local edit\n"


def test_wrapper_update_keeps_a_copy_of_an_edited_wrapper_file(root, tmp_path):
    verify = FakeVerify(root)
    updater = WrapperUpdater(root, quiet=True, run_verify=verify)
    assert updater.update(zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.0.0")))["ok"]
    (root / "gui/app.py").write_bytes(b"# my gui tweak\n")
    newer = dict(NEW_WRAPPER, **{"gui/app.py": b"# portable gui v3\n"})
    result = updater.update(zip_path=str(release_zip(tmp_path, newer, "v9.1.0")))
    assert result["ok"], result
    assert (root / "gui/app.py").read_bytes() == b"# portable gui v3\n"
    assert result["kept_edits_count"] == 1
    assert files_in(root / result["kept_edits"]) == {"gui/app.py": b"# my gui tweak\n"}


def test_repair_keeps_what_it_overwrites(root, tmp_path):
    verify = FakeVerify(root)
    assert WrapperUpdater(root, quiet=True, run_verify=verify).update(
        zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.3.0")))["ok"]
    (root / "README.md").write_bytes(b"my notes in the readme\n")
    report = wrapper.repair(root, quiet=True)
    assert "README.md" in report["restored"] and report["kept"] == 1
    assert report["kept_folder"].startswith(".portable/kept/")
    assert (root / "README.md").read_bytes() == NEW_WRAPPER["README.md"]
    assert kept_files(root, "repair") == {"README.md": b"my notes in the readme\n"}
    # A missing file is restored without a copy.
    (root / "assets/SOUL.md").unlink()
    report = wrapper.repair(root, quiet=True)
    assert report["restored"] == ["assets/SOUL.md"] and report["kept"] == 0


def test_legacy_adoption_keeps_every_file_it_replaces_or_removes(root, tmp_path, monkeypatch):
    write_files(root, {"run_agent.py": b"old", "toolsets.py": b"old",
                       "old_module.py": b"legacy core file"})
    monkeypatch.setattr(CoreLifecycle, "legacy_files", lambda self: {
        "run_agent.py": None, "toolsets.py": None, "old_module.py": None})
    life, _, _ = lifecycle(root)
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))
    assert result["ok"] and result["adopted"]
    assert not (root / "old_module.py").exists()
    assert kept_files(root, "core") == {"run_agent.py": b"old", "toolsets.py": b"old",
                                        "old_module.py": b"legacy core file"}


def test_kept_folders_are_user_data_for_every_updater():
    assert ownership.classify(".portable/kept/20261113-101500-core/run_agent.py") == "user"


# --------------------------------------------------------------------------
# F. dependency changes
# --------------------------------------------------------------------------

class BrokenRestorePip(FakePip):
    """pip that installs the new set but cannot put the old one back."""

    def __init__(self):
        super().__init__()
        self.installs = 0

    def __call__(self, args, timeout=3600):
        args = list(args)
        if args[0] == "install" and "-r" not in args and "-c" not in args and self.installs:
            self.calls.append(args)
            return 1, "ERROR: Could not install packages due to an OSError: [WinError 5]"
        if args[0] == "uninstall":
            self.calls.append(args)
            return 1, "ERROR: Access is denied"
        if args[0] == "install" and "-r" in args:
            self.installs += 1
        return super().__call__(args, timeout)


def marker(root: Path) -> Path:
    return root / ".portable" / core.DEPS_MARKER


def stamp(root: Path) -> Path:
    return root / "python_embedded/Lib/site-packages" / core.DEPS_STAMP


def test_successful_install_clears_the_marker_and_stamps_the_runtime(root, tmp_path):
    life, _, _ = lifecycle(root)
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))
    assert result["ok"]
    assert not marker(root).exists()
    data = json.loads(stamp(root).read_text())
    assert data["fingerprint"] == json.loads(
        (root / ".portable/core-state.json").read_text())["dependencies_fingerprint"]


def test_restored_dependencies_clear_the_marker_and_keep_the_core(root, tmp_path):
    life, pip, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    before = dict(pip.packages)
    verify.fail_staged = True
    result = life.install(zip_path=str(core_zip(tmp_path, with_requests(CORE_V2, "3.0"), SHA2,
                                                "v2.zip")))
    assert not result["ok"] and result["kept_existing_core"] and result["exit"] == core.EXIT_KEPT
    assert result["dependencies_restored"] is True
    assert pip.packages == before
    assert not marker(root).exists()


def test_failed_restore_is_visible_and_never_called_kept(root, tmp_path):
    pip = BrokenRestorePip()
    life, _, verify = lifecycle(root, pip=pip)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    verify.fail_staged = True
    v2 = core_zip(tmp_path, with_requests(CORE_V2, "3.0"), SHA2, "v2.zip")
    result = life.install(zip_path=str(v2))
    assert not result["ok"]
    assert result["dependencies_restored"] is False
    assert result["kept_existing_core"] is False and result["exit"] == core.EXIT_FAILED
    assert "could not all be put back" in result["reason"]
    assert "UPDATE.bat" in result["reason"]
    assert any("requests" in line for line in result["dependencies"]["not_restored"])
    assert marker(root).exists()
    # The core files themselves were not swapped.
    assert json.loads((root / ".portable/core-state.json").read_text())["commit"] == SHA1
    assert life.check()["dependencies_pending"] is True
    # The next update does not take the "already at this commit" shortcut.
    good = FakePip()
    good.packages = dict(pip.packages)
    life2, _, _ = lifecycle(root, pip=good)
    again = life2.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1-again.zip")))
    assert again["ok"] and again.get("changed") is True, again
    assert not again["dependencies"].get("skipped")
    assert not marker(root).exists()


def test_failed_restore_wording_in_the_cli_and_the_agent_tool(monkeypatch, capsys):
    from portable_hermes import __main__ as cli
    failure = {"ok": False, "code": "verify_failed", "reason": "x", "exit": 1,
               "kept_existing_core": False, "dependencies_restored": False}
    cli._emit(failure, False)
    text = capsys.readouterr().out
    assert "could not all be put back" in text and "UPDATE.bat" in text
    tool = pytest.importorskip("tools.update_hermes_tool")
    monkeypatch.setattr(tool, "_run_portable", lambda args, timeout: dict(failure))
    out = json.loads(tool.update_hermes_handler({}))
    assert "could not all be put back" in out["note"] and "kept unchanged" not in out["note"]


def test_an_interrupted_package_change_is_finished_by_the_next_update(root, tmp_path):
    life, pip, _ = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    # The process died while pip was changing packages: the marker stays.
    common.write_json_atomic(marker(root), {"schema": 1, "python": common.python_tag(),
                                            "before": dict(pip.packages), "target": "x"})
    calls = len(pip.calls)
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))
    assert result["ok"] and result.get("changed") is True
    assert any(c[0] == "install" and "-r" in c for c in pip.calls[calls:])
    assert not marker(root).exists()


def test_a_rebuilt_runtime_never_takes_the_unchanged_dependencies_shortcut(root, tmp_path):
    life, pip, _ = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    stamp(root).unlink()                       # a new python_embedded has no stamp
    calls = len(pip.calls)
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))
    assert result["ok"] and result.get("changed") is True
    assert any(c[0] == "install" and "-r" in c for c in pip.calls[calls:])
    assert stamp(root).is_file()


def test_unexpected_exceptions_get_the_same_cleanup(root, tmp_path, monkeypatch):
    life, pip, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    before = dict(pip.packages)
    live_before = protected(root)

    def boom(tree, gui=True):
        if Path(tree).resolve() == root.resolve():
            raise RuntimeError("verifier crashed")
        return {"ok": True, "checks": []}

    life._run_verify = boom
    result = life.install(zip_path=str(core_zip(tmp_path, with_requests(CORE_V2, "3.0"), SHA2,
                                                "v2.zip")))
    assert not result["ok"] and result["code"] == "internal"
    assert "verifier crashed" in result["reason"]
    assert pip.packages == before and protected(root) == live_before
    assert json.loads((root / ".portable/core-state.json").read_text())["commit"] == SHA1
    assert not (root / ".portable/journal.json").exists()
    assert result["kept_existing_core"] is True


# --------------------------------------------------------------------------
# A. the newest core needs a newer portable Python
# --------------------------------------------------------------------------

GATED = b"""[project]
name = "hermes-agent"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = ["requests==2.0; python_version >= '3.99'", "rich==1; python_version >= '3.99'"]
"""


def env_for(version: str) -> dict:
    return core._env_for(core.marker_environment(), version)


def test_runtime_too_old_when_the_pinned_python_would_fit(monkeypatch):
    monkeypatch.setattr(core, "target_python", lambda: "3.99.1")
    project = {"requires-python": ">=3.11",
               "dependencies": ["requests==2.0; python_version >= '3.99'"]}
    with pytest.raises(common.UpdateError) as info:
        core.check_python(project, env_for("3.13.12"))
    assert info.value.code == "runtime_too_old"
    assert info.value.details == {"current_python": "3.13.12", "target_python": "3.99.1",
                                  "requires_python": ">=3.11"}
    assert "UPDATE.bat" in info.value.reason and "in place" in info.value.reason
    core.check_python(project, env_for("3.99.1"))          # fits: no error


@pytest.mark.parametrize("pin", ["3.98.0", None])
def test_python_incompatible_when_the_pin_is_not_enough(monkeypatch, pin):
    monkeypatch.setattr(core, "target_python", lambda: pin)
    project = {"requires-python": ">=3.99"}
    with pytest.raises(common.UpdateError) as info:
        core.check_python(project, env_for("3.13.12"))
    assert info.value.code == "python_incompatible"
    assert "Update the portable wrapper first" in info.value.reason


def test_the_shipped_pin_is_a_full_version_and_newer_than_any_existing_install():
    pin = core.target_python()
    assert pin and wrapper.parse_version(pin) >= (3, 14, 0)
    text = (REPO_ROOT / "portable_hermes/manifests/python-runtime.txt").read_bytes()
    assert text.strip().decode("ascii") == pin


def test_install_returns_exit_4_and_changes_nothing(root, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "target_python", lambda: "3.99.1")
    gated = dict(CORE_V2, **{"pyproject.toml": GATED})
    gated.pop("uv.lock")
    life, pip, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    before, packages = protected(root), dict(pip.packages)
    monkeypatch.setattr(CoreLifecycle, "last_known_good",
                        lambda self: pytest.fail("a runtime problem is not a reason to fall back"))
    result = life.install(zip_path=str(core_zip(tmp_path, gated, SHA2, "gated.zip")))
    assert not result["ok"] and result["code"] == "runtime_too_old"
    assert result["exit"] == core.EXIT_RUNTIME == 4
    assert result["target_python"] == "3.99.1"
    assert protected(root) == before and pip.packages == packages
    assert json.loads((root / ".portable/core-state.json").read_text())["commit"] == SHA1


def test_update_command_passes_exit_4_on_to_update_bat(root, monkeypatch):
    from portable_hermes import __main__ as cli
    monkeypatch.setattr(WrapperUpdater, "update",
                        lambda self, **kw: {"ok": True, "changed": False, "message": "current"})
    monkeypatch.setattr(CoreLifecycle, "install", lambda self, **kw: {
        "ok": False, "code": "runtime_too_old", "exit": 4, "reason": "needs 3.14",
        "current_python": "3.13.12", "requires_python": ">=3.14"})
    assert cli.main(["--root", str(root), "update", "--core", "--yes"]) == 4


def test_agent_tool_never_swaps_the_runtime_and_says_what_to_run(monkeypatch):
    tool = pytest.importorskip("tools.update_hermes_tool")
    monkeypatch.setattr(tool, "_run_portable", lambda args, timeout: {
        "ok": False, "code": "runtime_too_old", "reason": "x", "exit": 4,
        "current_python": "3.13.12", "requires_python": ">=3.14", "target_python": "3.14.9"})
    out = json.loads(tool.update_hermes_handler({}))
    assert not out["success"] and out["code"] == "runtime_too_old"
    assert "UPDATE.bat" in out["next_step"] and "close hermes" in out["next_step"].lower()
    assert out["note"] == "Nothing was changed."


def test_runtime_plan_names_are_unique_and_safe(tmp_path):
    (tmp_path / "python_embedded.old-3.13.12").mkdir()
    info = runtime.plan(tmp_path, "3.13.12", "3.14.9")
    assert info["old_name"] == "python_embedded.old-3.13.12-2"
    assert info["failed_name"] == "python_embedded.failed-3.14.9"
    assert "Close Hermes first" in info["text"] and "MB" in info["text"]
    path = runtime.write_plan_file(tmp_path, info)
    lines = path.read_bytes().decode("ascii").split("\r\n")
    assert 'set "PH_OLD_NAME=python_embedded.old-3.13.12-2"' in lines
    assert 'set "PH_TARGET=3.14.9"' in lines
    with pytest.raises(common.UpdateError):
        runtime.write_plan_file(tmp_path, dict(info, old_name="x & del /q *"))
    with pytest.raises(common.UpdateError):
        runtime.plan(tmp_path, "3.13", "3.14.9")


def test_runtime_messages(tmp_path):
    (tmp_path / "python_embedded.old-3.13.12").mkdir()
    (tmp_path / "python_embedded.old-3.13.12" / "x.bin").write_bytes(b"x" * (3 << 20))
    text = runtime.done_text(tmp_path, "python_embedded.old-3.13.12", None)
    assert "python_embedded.old-3.13.12 (3 MB)" in text and "You may delete" in text
    text = runtime.undone_text(tmp_path, "python_embedded.failed-3.14.9")
    assert "Nothing changed" in text and "UPDATE.bat --core" in text
    assert "install.bat again" in runtime.partial_text("python_embedded.old-3.13.12")


def test_set_aside_runtimes_are_never_touched_by_either_updater(root, tmp_path):
    aside = {"python_embedded.old-3.13.12/python.exe": b"MZ old",
             "python_embedded.failed-3.14.9/Lib/x.py": b"x"}
    write_files(root, aside)
    life, _, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    archive = release_zip(tmp_path, dict(NEW_WRAPPER, **{
        "python_embedded.old-3.13.12/python.exe": b"hijack"}), "v9.0.0")
    result = WrapperUpdater(root, quiet=True, run_verify=verify).update(zip_path=str(archive))
    assert result["ok"]
    assert snapshot(root, aside) == {k: __import__("hashlib").sha256(v).hexdigest()
                                     for k, v in aside.items()}


# --------------------------------------------------------------------------
# B. wrapper versions
# --------------------------------------------------------------------------

def test_version_comparison():
    assert wrapper.is_newer("v1.5.0", None)
    assert wrapper.is_newer("v1.5.0", "unknown")
    assert wrapper.is_newer("v1.10.0", "v1.9.9")
    assert not wrapper.is_newer("v1.5.0", "v1.5.0")
    assert not wrapper.is_newer("v1.5.0", "v1.6.0")
    assert not wrapper.is_newer("v1.4.18", None)         # pre-evergreen: never offered
    assert not wrapper.is_newer("nightly", None)


@pytest.mark.parametrize("latest, installed, available", [
    ("v1.4.18", None, False), ("v1.4.18", "v1.5.0", False), ("v1.5.0", None, True),
    ("v1.5.0", "v1.5.0", False), ("v1.5.1", "v1.5.0", True), ("v1.5.0", "v1.6.0", False),
])
def test_wrapper_check_only_announces_newer_evergreen_releases(root, monkeypatch, latest,
                                                              installed, available):
    if installed:
        common.write_json_atomic(root / ".portable/wrapper-state.json", {"version": installed})
    monkeypatch.setattr(wrapper, "latest_release", lambda timeout=20: {
        "tag": latest, "url": "https://github.com/x", "asset": "a.zip"})
    info = WrapperUpdater(root, quiet=True, run_verify=FakeVerify(root)).check()
    assert info["update_available"] is available
    assert info["installed_version"] == (installed or "unknown")
    if latest == "v1.4.18":
        assert "no newer Portable Hermes release yet" in info["message"]


def test_wrapper_update_with_a_pre_evergreen_latest_is_a_successful_no_op(root, monkeypatch):
    monkeypatch.setattr(wrapper, "latest_release", lambda timeout=20: {
        "tag": "v1.4.18", "url": "https://github.com/x", "asset": "a.zip"})
    monkeypatch.setattr(common, "download", lambda *a, **k: pytest.fail("downloaded"))
    before = protected(root)
    result = WrapperUpdater(root, quiet=True, run_verify=FakeVerify(root)).update()
    assert result["ok"] and result["changed"] is False
    assert "predates this updater" in result["message"]
    assert protected(root) == before


def test_wrapper_update_refuses_old_tags_and_older_zips(root, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "download", lambda *a, **k: pytest.fail("downloaded"))
    updater = WrapperUpdater(root, quiet=True, run_verify=FakeVerify(root))
    result = updater.update(tag="v1.4.18")
    assert not result["ok"] and result["code"] == "downgrade"
    assert updater.update(zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.5.0")))["ok"]
    older = updater.update(zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.4.0")))
    assert not older["ok"] and older["code"] == "downgrade" and "--force" in older["reason"]
    forced = updater.update(zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.4.0")),
                            force=True)
    assert forced["ok"]


def test_wrapper_update_with_unknown_version_accepts_the_newest_release(root, tmp_path,
                                                                       monkeypatch):
    archive = release_zip(tmp_path, NEW_WRAPPER, "v9.6.0")
    monkeypatch.setattr(wrapper, "latest_release", lambda timeout=20: {
        "tag": "v9.6.0", "url": "https://github.com/x/a.zip", "asset": archive.name})
    monkeypatch.setattr(common, "download",
                        lambda url, dest, **kw: Path(__import__("shutil").copy(archive, dest)))
    assert wrapper.installed_version(root) is None
    result = WrapperUpdater(root, quiet=True, run_verify=FakeVerify(root)).update()
    assert result["ok"] and result["version"] == "v9.6.0"


# --------------------------------------------------------------------------
# J. lock policy, honest check output, bridge problems
# --------------------------------------------------------------------------

def test_first_install_never_installs_unpinned_dependencies(root, tmp_path, monkeypatch):
    unlocked = dict(CORE_V1)
    unlocked.pop("uv.lock")
    life, pip, verify = lifecycle(root)
    result = life.install(zip_path=str(core_zip(tmp_path, unlocked, SHA1, "nolock.zip")))
    assert not result["ok"] and result["code"] == "lock_unusable"
    assert "hash-checked" in result["reason"]
    assert pip.calls == [] and not (root / "run_agent.py").exists()


def test_update_without_a_usable_lock_uses_pyproject_and_says_so(root, tmp_path):
    life, pip, _ = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    unlocked = with_requests(CORE_V2, "3.0")
    unlocked.pop("uv.lock")
    result = life.install(zip_path=str(core_zip(tmp_path, unlocked, SHA2, "v2.zip")))
    assert result["ok"], result
    deps = result["dependencies"]
    assert deps["strategy"] == "pyproject"
    assert "without hashes" in deps["lock_note"] and "no uv.lock" in deps["lock_note"]
    assert pip.packages["requests"] == "3.0"


def test_check_counts_missing_recorded_files_honestly(root, tmp_path, monkeypatch):
    life, _, _ = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    (root / "tools/web_tools.py").unlink()
    (root / "run_agent.py").write_bytes(b"edited, not missing")
    monkeypatch.setattr(common, "github_commit_sha", lambda repo, ref, timeout=20: SHA1)
    info = life.check()
    assert info["missing_files"] == 1 and "modified" not in info


def test_bridge_problem_is_recorded_and_shown_by_repair(root, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "ROOT", root.resolve())
    (root / ".portable").mkdir(exist_ok=True)
    monkeypatch.delenv(bridge.NO_HOOK_ENV, raising=False)
    bridge._note_problem("toolsets.TOOLSETS is not a dict in this core")
    assert "not a dict" in bridge.read_problem(root)
    from portable_hermes import __main__ as cli
    assert cli.main(["--root", str(root), "repair", "--quiet"]) == 0
    text = capsys.readouterr().out
    assert "Portable tools problem in the last Hermes session" in text and "not a dict" in text
    bridge._note_problem(None)
    assert bridge.read_problem(root) is None
