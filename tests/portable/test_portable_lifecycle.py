"""Offline tests for the portable core/wrapper lifecycle (synthetic archives).

No network, no real pip, no real verification: the lifecycle's pip runner and
verifier are replaced with recording fakes, and the "upstream" and "release"
archives are small ZIPs built here. What is real: the ownership model, safe
extraction, the journaled swap, rollback, stale-file accounting, adoption,
the wrapper updater's fresh-process ownership read and compile check, and
launch-time repair.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from portable_hermes import common, core, ownership, wrapper
from portable_hermes.core import CoreLifecycle
from portable_hermes.wrapper import WrapperUpdater

REPO_ROOT = Path(__file__).resolve().parents[2]
SHA1 = "1" * 40
SHA2 = "2" * 40
SHA_LKG = "9" * 40

PYPROJECT = b"""[project]
name = "hermes-agent"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = ["requests==2.0"]

[project.optional-dependencies]
messaging = ["slack-sdk==1.0"]
"""


def lock_for(requests: str = "2.0") -> bytes:
    """A minimal hash-pinned uv.lock matching PYPROJECT with *requests*."""
    return f"""version = 1
requires-python = ">=3.11"

[[package]]
name = "hermes-agent"
version = "0.0.0"
source = {{ editable = "." }}
dependencies = [{{ name = "requests" }}]

[package.optional-dependencies]
messaging = [{{ name = "slack-sdk" }}]

[[package]]
name = "requests"
version = "{requests}"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {{ url = "https://example.invalid/requests.tar.gz", hash = "sha256:{'a' * 64}" }}

[[package]]
name = "slack-sdk"
version = "1.0"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {{ url = "https://example.invalid/slack.tar.gz", hash = "sha256:{'b' * 64}" }}
""".encode()


def with_requests(files: dict, version: str) -> dict:
    """*files* with a different pinned requests version (a dependency change)."""
    return dict(files, **{
        "pyproject.toml": PYPROJECT.replace(b"requests==2.0", f"requests=={version}".encode()),
        "uv.lock": lock_for(version)})


CORE_V1 = {
    "run_agent.py": b"class AIAgent: pass\n",
    "pyproject.toml": PYPROJECT,
    "uv.lock": lock_for(),
    "toolsets.py": b"TOOLSETS = {}\n",
    "tools/registry.py": b"registry = None\n",
    "tools/web_tools.py": b"# web v1\n",
    "hermes_cli/__init__.py": b"",
    "hermes_cli/main.py": b"def main(): pass\n",
    "skills/core-skill/SKILL.md": b"core skill\n",
    # Never installed by the core lifecycle:
    "README.md": b"upstream readme\n",
    "tests/test_x.py": b"def test(): pass\n",
    "website/docs/page.md": b"generated\n",
    ".github/workflows/ci.yml": b"on: push\n",
    "tools/custom/evil.py": b"user path\n",
    "gui/app.py": b"upstream must not own this\n",
    "tools/lm_studio_tools.py": b"upstream must not own this\n",
}

CORE_V2 = dict(CORE_V1)
CORE_V2.update({"run_agent.py": b"class AIAgent: version = 2\n",
                "tools/new_tool.py": b"# new in v2\n"})
del CORE_V2["tools/web_tools.py"]

WRAPPER_FILES = {
    "START.bat": b"@echo off\r\n",
    "README.md": b"# Portable Hermes Agent\n",
    "gui/app.py": b"# portable gui\n",
    "tools/lm_studio_tools.py": b"# portable lm studio tools\n",
    "assets/SOUL.md": b"portable soul\n",
    "skills/lm-studio/SKILL.md": b"portable skill\n",
}

USER_FILES = {
    ".env": b"OPENROUTER_API_KEY=x\n",
    "cli-config.yaml": b"model: x\n",
    ".hermes/config.yaml": b"a: 1\n",
    ".hermes/gui_config.json": b'{"language": "zh-hant"}\n',
    ".hermes/custom_tools/personal.py": b"# personal tool\n",
    ".lmstudio_config": b'{"base_url": "http://localhost:1234"}\n',
    "python_embedded/Lib/site-packages/somepkg.py": b"x = 1\n",
    "extensions/tts-server/server.py": b"print('tts')\n",
    "workflows/mine.json": b"{}\n",
    "tools/custom/my_tool.py": b"# custom tool\n",
    "apps/desktop/release/Hermes.exe": b"MZ\n",
    "node_modules/pkg/index.js": b"1\n",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def write_files(root: Path, files: dict) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def make_zip(path: Path, files: dict, *, top: str | None, comment: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for rel, data in files.items():
            zf.writestr(f"{top}/{rel}" if top else rel, data)
        if comment:
            zf.comment = comment.encode()
    return path


def core_zip(tmp_path: Path, files: dict, sha: str, name: str) -> Path:
    return make_zip(tmp_path / name, files, top=f"hermes-agent-{sha}", comment=sha)


def snapshot(root: Path, rels) -> dict:
    return {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
            for rel in rels if (root / rel).is_file()}


class FakePip:
    def __init__(self):
        self.packages = {"pip": "25.0"}
        self.calls: list[list[str]] = []
        self.fail_requirements = False

    def __call__(self, args, timeout=3600):
        args = list(args)
        self.calls.append(args)
        if args[0] == "list":
            return 0, json.dumps([{"name": n, "version": v} for n, v in self.packages.items()])
        if args[0] == "uninstall":
            for name in args[2:]:
                self.packages.pop(core.canonical(name), None)
            return 0, ""
        if args[0] == "install":
            tokens, skip = [], False
            for i, tok in enumerate(args[1:], 1):
                if skip:
                    skip = False
                    continue
                if tok == "-r":
                    if self.fail_requirements:
                        return 1, "ERROR: Could not find a version that satisfies requests==2.0"
                    tokens += Path(args[i + 1]).read_text(encoding="utf-8").split()
                    skip = True
                elif tok == "-c":
                    skip = True
                elif not tok.startswith("-"):
                    tokens.append(tok)
            for tok in tokens:
                if tok.startswith("--"):
                    continue
                name, _, version = tok.partition("==")
                self.packages[core.canonical(name.split(";")[0].strip())] = version or "1.0"
            return 0, "Successfully installed"
        return 1, "unexpected"


class FakeVerify:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.calls: list[Path] = []
        self.fail_staged = False
        self.fail_live = False
        self.fail_when_file: str | None = None

    def __call__(self, tree, gui=True):
        tree = Path(tree).resolve()
        self.calls.append(tree)
        if self.fail_when_file and (tree / self.fail_when_file).exists():
            return {"ok": False, "reason": f"core_imports: {self.fail_when_file} is broken"}
        if tree == self.root and self.fail_live:
            return {"ok": False, "reason": "cli_selection: lm_studio_status not selected"}
        if tree != self.root and self.fail_staged:
            return {"ok": False, "reason": "portable_tools_registered: missing run_python"}
        return {"ok": True, "checks": [{"name": "core_imports", "ok": True, "detail": ""}]}


@pytest.fixture()
def root(tmp_path):
    r = tmp_path / "install"
    write_files(r, WRAPPER_FILES)
    write_files(r, USER_FILES)
    return r


def lifecycle(root, pip=None, verify=None):
    pip = pip or FakePip()
    verify = verify or FakeVerify(root)
    return CoreLifecycle(root, quiet=True, run_pip=pip, run_verify=verify), pip, verify


def protected(root):
    return snapshot(root, list(WRAPPER_FILES) + list(USER_FILES))


# --------------------------------------------------------------------------
# ownership
# --------------------------------------------------------------------------

def test_ownership_categories():
    assert ownership.classify("gui/app.py") == "wrapper"
    assert ownership.classify("portable_hermes/core.py") == "wrapper"
    assert ownership.classify("tools/lm_studio_tools.py") == "wrapper"
    assert ownership.classify("skills/extensions/tts-server/SKILL.md") == "wrapper"
    assert ownership.classify("README.zh-CN.md") == "wrapper"
    assert ownership.classify("docs/hermes-guide.md") == "wrapper"
    assert ownership.classify("tools/custom/x.py") == "user"
    assert ownership.classify("apps/desktop/release/x.exe") == "user"
    assert ownership.classify("python_embedded/python.exe") == "user"
    assert ownership.classify(".hermes/config.yaml") == "user"
    assert ownership.classify("tools/__pycache__/x.cpython-314.pyc") == "user"
    assert ownership.classify("tools/web_tools.py") == "core"
    assert ownership.classify("skills/creative/comfyui/SKILL.md") == "core"
    assert ownership.classify("docs/README.md") == "core"
    assert ownership.classify("apps/desktop/src/main.ts") == "core"


def test_core_install_filter_mirrors_release_exclusions():
    assert ownership.is_core_installable("run_agent.py")
    assert ownership.is_core_installable("website/static/api/model-catalog.json")
    assert ownership.is_core_installable("website/i18n/zh-Hans/docusaurus-theme-classic/navbar.json")
    assert ownership.is_core_installable("optional-skills/autonomous-ai-agents/blackbox/SKILL.md")
    assert not ownership.is_core_installable("website/docs/user-guide/a.md")
    assert not ownership.is_core_installable(
        "website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/a.md")
    assert not ownership.is_core_installable(
        "website/i18n/es/docusaurus-plugin-content-docs-version-v2/intro.md")
    assert not ownership.is_core_installable("tests/test_x.py")
    assert not ownership.is_core_installable(".github/workflows/x.yml")
    assert not ownership.is_core_installable("README.md")          # wrapper wins
    assert not ownership.is_core_installable("gui/app.py")
    assert not ownership.is_core_installable("tools/custom/a.py")  # user path


def test_payload_covers_wrapper_files_exposed_to_upstream_swaps():
    assert ownership.is_payload_path("tools/lm_studio_tools.py")
    assert ownership.is_payload_path("skills/getting-started/SKILL.md")
    assert ownership.is_payload_path("README.md")
    assert ownership.is_payload_path("assets/SOUL.md")
    assert not ownership.is_payload_path("gui/app.py")
    assert not ownership.is_payload_path("START.bat")
    assert not ownership.is_payload_path("run_agent.py")


def test_legacy_manifest_accounts_only_for_core_paths():
    lines = [line for line in (REPO_ROOT / "portable_hermes/manifests/legacy-core-files.txt")
             .read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert "run_agent.py" in lines and "toolsets.py" in lines
    assert all(ownership.classify(line) == "core" for line in lines)
    assert lines == sorted(lines)


# --------------------------------------------------------------------------
# archives and the journal
# --------------------------------------------------------------------------

@pytest.mark.parametrize("member", ["../evil.py", "/abs.py", "C:/x.py", "a/../../b.py", "a/b:c"])
def test_safe_extract_rejects_unsafe_members(tmp_path, member):
    archive = make_zip(tmp_path / "bad.zip", {member: b"x"}, top=None)
    with pytest.raises(common.UpdateError) as info:
        common.safe_extract(archive, tmp_path / "out")
    assert info.value.code == "unsafe_archive"
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*"))


def test_safe_extract_rejects_symlinks(tmp_path):
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("top/link")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(common.UpdateError, match="symbolic link"):
        common.safe_extract(archive, tmp_path / "out")


def test_safe_extract_strips_the_single_top_folder(tmp_path):
    archive = make_zip(tmp_path / "top.zip", {"run_agent.py": b"1", "tools/x.py": b"2"},
                       top="hermes-agent-" + SHA1)
    names = common.safe_extract(archive, tmp_path / "out", strip_top=True)
    assert sorted(names) == ["run_agent.py", "tools/x.py"]
    assert (tmp_path / "out" / "tools" / "x.py").read_bytes() == b"2"


def test_too_long_install_path_is_refused_up_front_with_the_limit(root, tmp_path, monkeypatch):
    """Without Windows long paths, staging upstream's deepest files from a deep
    folder would fail halfway; the update refuses first and says what to do."""
    monkeypatch.setattr(common, "long_paths_enabled", lambda: False)
    deep = dict(CORE_V1)
    deep["plugins/" + "d" * 200 + ".json"] = b"{}"
    life, pip, verify = lifecycle(root)
    before = protected(root)
    result = life.install(zip_path=str(core_zip(tmp_path, deep, SHA1, "deep.zip")))
    assert not result["ok"] and result["code"] == "path_too_long"
    assert "at most" in result["reason"] and "C:\\PortableHermes" in result["reason"]
    assert not (root / "run_agent.py").exists() and protected(root) == before
    assert pip.calls == [] and verify.calls == []
    monkeypatch.setattr(common, "long_paths_enabled", lambda: True)
    common.check_path_lengths(root, ["x" * 300], overhead=20, what="t")   # no error


def test_archive_commit_comes_from_zip_comment(tmp_path):
    archive = core_zip(tmp_path, {"a": b"1"}, SHA1, "c.zip")
    assert common.archive_commit(archive) == SHA1
    assert common.archive_commit(make_zip(tmp_path / "n.zip", {"a": b"1"}, top=None)) is None


class Killed(BaseException):
    """Stands in for the process dying (not an OSError, so nothing catches it)."""


def test_swap_killed_halfway_is_rolled_back_by_recover(tmp_path, monkeypatch):
    root = tmp_path / "r"
    write_files(root, {"a.txt": b"old a", "b.txt": b"old b", "d.txt": b"old d"})
    staged = common.staging_dir(root)
    write_files(staged, {"a.txt": b"new a", "c.txt": b"new c", "d.txt": b"new d"})
    txn = common.Transaction(root, "core")
    txn.put("a.txt", staged / "a.txt")
    txn.put("c.txt", staged / "c.txt")
    txn.remove("b.txt")
    txn.put("d.txt", staged / "d.txt")
    real_replace, calls = os.replace, {"n": 0}

    def dies_on_third_staged_rename(src, dst):
        # Counts renames out of the staging folder (not the journal's writes).
        if str(staged) in str(src):
            calls["n"] += 1
            if calls["n"] == 3:
                raise Killed()
        return real_replace(src, dst)

    monkeypatch.setattr(common.os, "replace", dies_on_third_staged_rename)
    with pytest.raises(Killed):
        txn.apply()
    monkeypatch.setattr(common.os, "replace", real_replace)
    # a and c swapped, b moved to the backup, d untouched: a real half state.
    assert (root / "a.txt").read_bytes() == b"new a" and not (root / "b.txt").exists()
    assert "rolled back" in common.recover(root)
    assert (root / "a.txt").read_bytes() == b"old a"
    assert (root / "b.txt").read_bytes() == b"old b"
    assert (root / "d.txt").read_bytes() == b"old d"
    assert not (root / "c.txt").exists()
    assert not (root / ".portable" / "journal.json").exists()


def test_failed_rename_rolls_back_every_applied_step(tmp_path, monkeypatch):
    root = tmp_path / "r"
    write_files(root, {"a.txt": b"old a", "b.txt": b"old b"})
    staged = common.staging_dir(root)
    write_files(staged, {"a.txt": b"new a", "b.txt": b"new b"})
    txn = common.Transaction(root, "core")
    txn.put("a.txt", staged / "a.txt")
    txn.put("b.txt", staged / "b.txt")
    real_replace = os.replace

    def flaky(src, dst):
        if str(src) == str(staged / "b.txt"):
            raise PermissionError("file in use")
        return real_replace(src, dst)

    monkeypatch.setattr(common.os, "replace", flaky)
    with pytest.raises(common.UpdateError, match="rolled back"):
        txn.apply()
    monkeypatch.setattr(common.os, "replace", real_replace)
    assert (root / "a.txt").read_bytes() == b"old a"
    assert (root / "b.txt").read_bytes() == b"old b"
    assert not (root / ".portable" / "journal.json").exists()


def test_staged_files_must_live_in_the_staging_folder(tmp_path):
    root = tmp_path / "r"
    write_files(root, {"a.txt": b"old", "elsewhere/a.txt": b"new"})
    txn = common.Transaction(root, "core")
    with pytest.raises(common.UpdateError, match="not under"):
        txn.put("a.txt", root / "elsewhere" / "a.txt")


# --------------------------------------------------------------------------
# dependency plans
# --------------------------------------------------------------------------

def test_marker_evaluator_matches_pip_packaging_on_real_lock_markers():
    import tomllib
    from pip._vendor.packaging.markers import Marker

    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    markers = {dep["marker"] for pkg in lock["package"]
               for dep in pkg.get("dependencies", []) if "marker" in dep}
    markers |= {dep["marker"] for pkg in lock["package"]
                for deps in pkg.get("optional-dependencies", {}).values()
                for dep in deps if "marker" in dep}
    markers |= {m for pkg in lock["package"] for m in pkg.get("resolution-markers", [])}
    markers |= {"python_version >= '3.14'", "'android' not in platform_release",
                "platform_machine in 'x86_64 aarch64 i686'", "python_full_version == '3.12.*'"}
    env = core.marker_environment()
    assert len(markers) > 15
    for marker in markers:
        assert core.evaluate_marker(marker, env) == Marker(marker).evaluate(env), marker


def test_specifier_matching():
    assert core.specifier_matches(">=3.11,<3.15", "3.14.9")
    assert not core.specifier_matches(">=3.11,<3.14", "3.14.0")
    assert core.specifier_matches("==3.12.*", "3.12.4")
    assert core.specifier_matches("~=3.13.1", "3.13.9")
    assert not core.specifier_matches("~=3.13.1", "3.14.0")


def test_lock_plan_is_hash_pinned_and_resolver_free():
    plan = core.dependency_plan(REPO_ROOT)
    assert plan["strategy"] == "uv.lock"
    names = {line.split("==")[0] for line in plan["requirements"]}
    assert {"openai", "requests", "pydantic"} <= names
    assert all("--hash=sha256:" in line for line in plan["requirements"])


def test_core_needing_newer_python_fails_precisely(tmp_path):
    tree = tmp_path / "core"
    write_files(tree, {"pyproject.toml": b"""[project]
name = "hermes-agent"
requires-python = ">=3.11,<3.15"
dependencies = ["openai==2.0; python_version >= '3.99'", "rich==1; python_version >= '3.99'"]
"""})
    with pytest.raises(common.UpdateError) as info:
        core.dependency_plan(tree)
    assert info.value.code == "python_incompatible"
    assert "python_version >= '3.99'" in info.value.reason


def test_requires_python_mismatch_fails_precisely(tmp_path):
    tree = tmp_path / "core"
    write_files(tree, {"pyproject.toml": b'[project]\nname="hermes-agent"\nrequires-python=">=3.99"\n'})
    with pytest.raises(common.UpdateError, match="requires Python >=3.99"):
        core.dependency_plan(tree)


# --------------------------------------------------------------------------
# core lifecycle
# --------------------------------------------------------------------------

def test_fresh_install_records_core_and_leaves_wrapper_and_user_data(root, tmp_path):
    before = protected(root)
    life, pip, verify = lifecycle(root)
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))
    assert result["ok"], result
    assert result["commit"] == SHA1
    assert (root / "run_agent.py").read_bytes() == CORE_V1["run_agent.py"]
    assert (root / "tools/web_tools.py").is_file()
    for never in ("tests/test_x.py", "website/docs/page.md", ".github/workflows/ci.yml",
                  "tools/custom/evil.py"):
        assert not (root / never).exists(), never
    assert protected(root) == before
    state = json.loads((root / ".portable/core-state.json").read_text())
    assert state["commit"] == SHA1 and state["repository"] == "NousResearch/hermes-agent"
    assert "run_agent.py" in state["files"] and "README.md" not in state["files"]
    assert state["dependencies_strategy"] == "uv.lock"
    # Staged tree verified first (with the wrapper overlaid), then the live tree.
    assert len(verify.calls) == 2 and verify.calls[-1] == root.resolve()
    assert pip.packages["requests"] == "2.0" and pip.packages["slack-sdk"] == "1.0"
    assert {"ddgs", "lmstudio", "pillow"} <= set(pip.packages)
    assert not (root / ".portable/s").exists()
    assert not (root / ".portable/b").exists() or not any((root / ".portable/b").iterdir())


def test_update_replaces_changed_files_and_removes_only_unchanged_recorded_ones(root, tmp_path):
    life, pip, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    write_files(root, {"tools/unknown_local.py": b"# not recorded anywhere\n"})
    (root / "hermes_cli/main.py").write_bytes(b"# edited by hand\n")   # recorded, still shipped
    before = protected(root)
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V2, SHA2, "v2.zip")))
    assert result["ok"], result
    assert (root / "run_agent.py").read_bytes() == CORE_V2["run_agent.py"]
    assert (root / "tools/new_tool.py").is_file()
    assert not (root / "tools/web_tools.py").exists()          # recorded, unchanged, dropped
    assert (root / "tools/unknown_local.py").is_file()         # unknown: never deleted
    assert (root / "hermes_cli/main.py").read_bytes() == CORE_V1["hermes_cli/main.py"]
    assert protected(root) == before
    assert json.loads((root / ".portable/core-state.json").read_text())["commit"] == SHA2
    # Same dependency set: pip install is not run again.
    assert result["dependencies"]["skipped"] and "unchanged" in result["dependencies"]["reason"]


def test_recorded_file_modified_after_install_is_kept_when_upstream_drops_it(root, tmp_path):
    life, _, _ = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    (root / "tools/web_tools.py").write_bytes(b"# local edit\n")
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V2, SHA2, "v2.zip")))
    assert result["ok"]
    assert (root / "tools/web_tools.py").read_bytes() == b"# local edit\n"
    assert result["kept_modified"] == ["tools/web_tools.py"]


def test_same_commit_is_reported_current_without_changes(root, tmp_path):
    life, _, verify = lifecycle(root)
    archive = core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")
    assert life.install(zip_path=str(archive))["ok"]
    calls = len(verify.calls)
    result = life.install(zip_path=str(archive))
    assert result["ok"] and result["changed"] is False
    assert len(verify.calls) == calls


def test_staged_verification_failure_changes_nothing_and_restores_dependencies(root, tmp_path):
    life, pip, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    live_before = snapshot(root, list(CORE_V1) + list(WRAPPER_FILES) + list(USER_FILES))
    packages_before = dict(pip.packages)
    v2 = with_requests(CORE_V2, "3.0")
    verify.fail_staged = True
    result = life.install(zip_path=str(core_zip(tmp_path, v2, SHA2, "v2.zip")))
    assert not result["ok"] and result["code"] == "verify_failed"
    assert "portable_tools_registered" in result["reason"]
    assert result["exit"] == core.EXIT_KEPT and result["kept_existing_core"]
    assert snapshot(root, list(CORE_V1) + list(WRAPPER_FILES) + list(USER_FILES)) == live_before
    assert not (root / "tools/new_tool.py").exists()
    assert pip.packages == packages_before
    assert json.loads((root / ".portable/core-state.json").read_text())["commit"] == SHA1


def test_live_verification_failure_rolls_the_swap_back(root, tmp_path):
    life, pip, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    live_before = snapshot(root, list(CORE_V1) + list(WRAPPER_FILES) + list(USER_FILES))
    verify.fail_live = True
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V2, SHA2, "v2.zip")))
    assert not result["ok"] and "rolled back" in result["reason"]
    assert snapshot(root, list(CORE_V1) + list(WRAPPER_FILES) + list(USER_FILES)) == live_before
    assert (root / "tools/web_tools.py").is_file() and not (root / "tools/new_tool.py").exists()
    assert not (root / ".portable/journal.json").exists()


def test_dependency_failure_rolls_back_and_keeps_core(root, tmp_path):
    life, pip, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    packages_before = dict(pip.packages)
    live_before = snapshot(root, list(CORE_V1))
    pip.fail_requirements = True
    v2 = with_requests(CORE_V2, "3.0")
    result = life.install(zip_path=str(core_zip(tmp_path, v2, SHA2, "v2.zip")))
    assert not result["ok"] and result["code"] == "dependencies_failed"
    assert "Could not find a version" in result["reason"]
    assert snapshot(root, list(CORE_V1)) == live_before
    assert pip.packages == packages_before


def test_adoption_of_legacy_install_removes_only_accounted_files(root, tmp_path, monkeypatch):
    # An old full-tree install: core files from the previous updater, no state.
    write_files(root, {"run_agent.py": b"old", "toolsets.py": b"old",
                       "old_module.py": b"legacy core file", "tests/test_old.py": b"legacy test",
                       "my_notes.txt": b"unknown file"})
    monkeypatch.setattr(CoreLifecycle, "legacy_files", lambda self: {
        "run_agent.py": None, "toolsets.py": None, "old_module.py": None,
        "tests/test_old.py": None})
    before = protected(root)
    life, _, _ = lifecycle(root)
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))
    assert result["ok"] and result["adopted"]
    assert not (root / "old_module.py").exists()
    assert not (root / "tests/test_old.py").exists()
    assert (root / "my_notes.txt").read_bytes() == b"unknown file"
    assert (root / "run_agent.py").read_bytes() == CORE_V1["run_agent.py"]
    assert protected(root) == before
    assert json.loads((root / ".portable/core-state.json").read_text())["adopted_from"]


def test_fresh_install_falls_back_to_last_known_good(root, tmp_path, monkeypatch):
    broken = dict(CORE_V2, **{"BROKEN": b"x"})
    archives = {
        "https://github.com/NousResearch/hermes-agent/archive/main.zip":
            core_zip(tmp_path, broken, SHA2, "main.zip"),
        f"https://github.com/NousResearch/hermes-agent/archive/{SHA_LKG}.zip":
            core_zip(tmp_path, CORE_V1, SHA_LKG, "lkg.zip"),
    }
    monkeypatch.setattr(common, "download",
                        lambda url, dest, **kw: Path(shutil.copy(archives[url], dest)))
    monkeypatch.setattr(CoreLifecycle, "last_known_good",
                        lambda self: {"commit": SHA_LKG, "repository": "NousResearch/hermes-agent"})
    verify = FakeVerify(root)
    verify.fail_when_file = "BROKEN"
    life, _, _ = lifecycle(root, verify=verify)
    result = life.install()
    assert result["ok"], result
    assert result["commit"] == SHA_LKG and result["fallback"]["commit"] == SHA_LKG
    assert "BROKEN" in result["fallback"]["reason"]
    assert not (root / "BROKEN").exists()


@pytest.mark.parametrize("python, expected", [("3.14.2", True), ("3.13.12", False)])
def test_shipped_last_known_good_matches_only_interpreters_it_was_verified_on(
        root, monkeypatch, python, expected):
    data = json.loads((core.DATA_DIR / "last-known-good.json").read_text(encoding="utf-8"))
    assert data["repository"] == "NousResearch/hermes-agent"
    for cand in data["candidates"]:
        assert len(cand["commit"]) == 40 and int(cand["commit"], 16) >= 0
        assert cand["python"] and cand["verified"]
    env = dict(core.marker_environment(), python_full_version=python,
               python_version=python.rsplit(".", 1)[0])
    monkeypatch.setattr(core, "marker_environment", lambda: env)
    found = CoreLifecycle(root, quiet=True).last_known_good()
    assert (found is not None) is expected


def test_update_of_existing_core_never_falls_back(root, tmp_path, monkeypatch):
    life, _, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    archive = core_zip(tmp_path, dict(CORE_V2, BROKEN=b"x"), SHA2, "main.zip")
    monkeypatch.setattr(common, "download", lambda url, dest, **kw: Path(shutil.copy(archive, dest)))
    monkeypatch.setattr(CoreLifecycle, "last_known_good",
                        lambda self: pytest.fail("must not fall back over a working core"))
    verify.fail_when_file = "BROKEN"
    result = life.install()
    assert not result["ok"] and result["kept_existing_core"]


def test_git_checkout_is_never_rewritten(root, tmp_path):
    (root / ".git").mkdir()
    life, _, _ = lifecycle(root)
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))
    assert not result["ok"] and result["code"] == "git_checkout"
    assert not (root / "run_agent.py").exists()
    assert life.check()["install_type"] == "git"
    assert WrapperUpdater(root, run_verify=FakeVerify(root)).update(zip_path="x")["code"] == \
        "git_checkout"


def test_check_reports_how_far_behind_and_degrades_offline(root, tmp_path, monkeypatch):
    life, _, _ = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    monkeypatch.setattr(common, "github_commit_sha", lambda repo, ref, timeout=20: SHA2)
    monkeypatch.setattr(common, "github_compare", lambda repo, base, head, timeout=20:
                        {"status": "ahead", "ahead_by": 42, "behind_by": 0})
    info = life.check()
    assert info["commit"] == SHA1 and info["behind_by"] == 42 and info["update_available"]

    def offline(*a, **k):
        raise common.UpdateError("network error fetching x", code="network")

    monkeypatch.setattr(common, "github_commit_sha", offline)
    info = life.check()
    assert info["ok"] and info["update_available"] is None and "network" in info["network_error"]


# --------------------------------------------------------------------------
# wrapper channel
# --------------------------------------------------------------------------

def release_zip(tmp_path: Path, files: dict, version: str) -> Path:
    """A release archive shaped like build_release.py output."""
    members = {}
    for rel in ownership.iter_wrapper_files(REPO_ROOT):
        if rel.startswith("portable_hermes/") and not rel.startswith(ownership.PAYLOAD_DIR):
            members[rel] = (REPO_ROOT / rel).read_bytes()
    members.update(files)
    payload = {}
    for rel in list(members):
        if ownership.is_payload_path(rel):
            members[f"{ownership.PAYLOAD_DIR}/{rel}"] = members[rel]
            payload[rel] = hashlib.sha256(members[rel]).hexdigest()
    hashes = {rel: hashlib.sha256(data).hexdigest() for rel, data in members.items()}
    manifest = {"schema": 1, "version": version, "files": hashes, "payload": payload}
    members[ownership.RELEASE_MANIFEST] = json.dumps(manifest).encode()
    return make_zip(tmp_path / f"portable-hermes-agent-{version}.zip", members,
                    top="portable-hermes-agent")


NEW_WRAPPER = {
    "START.bat": b"@echo off\r\nrem v2\r\n",
    "README.md": b"# Portable Hermes Agent v2\n",
    "gui/app.py": b"# portable gui v2\n",
    "gui/new_panel.py": b"# new gui module\n",
    "tools/lm_studio_tools.py": b"# portable lm studio tools v2\n",
    "assets/SOUL.md": b"portable soul\n",
    "skills/lm-studio/SKILL.md": b"portable skill v2\n",
}


def test_wrapper_update_replaces_only_wrapper_paths(root, tmp_path):
    life, _, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    core_before = snapshot(root, [r for r in CORE_V1 if ownership.is_core_installable(r)])
    users_before = snapshot(root, USER_FILES)
    archive = release_zip(tmp_path, NEW_WRAPPER, "v9.0.0")
    # Members a release must never be able to write: user data and core files.
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("portable-hermes-agent/.env", b"HIJACK=1\n")
        zf.writestr("portable-hermes-agent/run_agent.py", b"not from the wrapper\n")
    result = WrapperUpdater(root, quiet=True, run_verify=verify).update(zip_path=str(archive))
    assert result["ok"], result
    assert result["version"] == "v9.0.0"
    assert (root / "gui/app.py").read_bytes() == NEW_WRAPPER["gui/app.py"]
    assert (root / "gui/new_panel.py").is_file()
    assert (root / "tools/lm_studio_tools.py").read_bytes() == NEW_WRAPPER["tools/lm_studio_tools.py"]
    assert (root / "portable_hermes/release.json").is_file()
    assert (root / ownership.PAYLOAD_DIR / "tools/lm_studio_tools.py").is_file()
    assert snapshot(root, [r for r in CORE_V1 if ownership.is_core_installable(r)]) == core_before
    assert snapshot(root, USER_FILES) == users_before
    assert any(".env" in s for s in result["skipped"])
    assert any("run_agent.py" in s for s in result["skipped"])
    assert json.loads((root / ".portable/wrapper-state.json").read_text())["version"] == "v9.0.0"
    assert result["changed"] is True
    # Forcing the same release again writes nothing and says so (UPDATE.bat
    # only hands the core step to a new process when wrapper code changed).
    again = WrapperUpdater(root, quiet=True, run_verify=verify).update(
        zip_path=str(archive), force=True)
    assert again["ok"] and again["changed"] is False and again["files_written"] == 0


def test_wrapper_update_refuses_pre_evergreen_releases(root, tmp_path):
    archive = make_zip(tmp_path / "old.zip", {"README.md": b"old", "run_agent.py": b"x"},
                       top="portable-hermes-agent")
    result = WrapperUpdater(root, quiet=True, run_verify=FakeVerify(root)).update(
        zip_path=str(archive))
    assert not result["ok"] and result["code"] == "downgrade"


def test_wrapper_update_refuses_tampered_archives(root, tmp_path):
    archive = release_zip(tmp_path, NEW_WRAPPER, "v9.0.1")
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(tampered, "w") as dst:
        for item in src.infolist():
            data = src.read(item)
            if item.filename.endswith("gui/app.py"):
                data = b"tampered"
            dst.writestr(item, data)
    result = WrapperUpdater(root, quiet=True, run_verify=FakeVerify(root)).update(
        zip_path=str(tampered))
    assert not result["ok"] and "does not match" in result["reason"]
    assert (root / "gui/app.py").read_bytes() == WRAPPER_FILES["gui/app.py"]


def test_wrapper_update_rolls_back_when_verification_fails(root, tmp_path):
    verify = FakeVerify(root)
    life, _, _ = lifecycle(root, verify=verify)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    before = protected(root)
    calls = {"n": 0}

    def flaky(tree, gui=True):
        calls["n"] += 1
        return {"ok": calls["n"] == 1, "reason": "gui_modules: ImportError"}

    result = WrapperUpdater(root, quiet=True, run_verify=flaky).update(
        zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.0.2")))
    assert not result["ok"] and "rolled back" in result["reason"]
    assert protected(root) == before
    assert not (root / "gui/new_panel.py").exists()


def test_second_wrapper_update_drops_files_no_longer_shipped(root, tmp_path):
    verify = FakeVerify(root)
    updater = WrapperUpdater(root, quiet=True, run_verify=verify)
    assert updater.update(zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.1.0")))["ok"]
    smaller = dict(NEW_WRAPPER)
    del smaller["gui/new_panel.py"]
    smaller["gui/app.py"] = b"# v3\n"
    assert updater.update(zip_path=str(release_zip(tmp_path, smaller, "v9.2.0")))["ok"]
    assert not (root / "gui/new_panel.py").exists()
    assert (root / "gui/app.py").read_bytes() == b"# v3\n"


# --------------------------------------------------------------------------
# launch-time repair and back-to-back sequences
# --------------------------------------------------------------------------

def upstream_swap(root: Path, files: dict) -> None:
    """What upstream's own ``hermes update`` does on a ZIP install: replace every
    top-level entry its archive ships, wholesale."""
    tops = {rel.split("/", 1)[0] for rel in files}
    for top in tops:
        path = root / top
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    write_files(root, files)


def test_repair_restores_wrapper_files_after_upstream_swap(root, tmp_path):
    life, _, verify = lifecycle(root)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    assert WrapperUpdater(root, quiet=True, run_verify=verify).update(
        zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.3.0")))["ok"]
    users_before = snapshot(root, USER_FILES)
    upstream_swap(root, {"tools/registry.py": b"upstream", "tools/web_tools.py": b"upstream",
                         "README.md": b"upstream readme", "skills/core-skill/SKILL.md": b"u",
                         "assets/banner.png": b"png"})
    assert not (root / "tools/lm_studio_tools.py").exists()
    report = wrapper.repair(root, quiet=True)
    assert set(report["restored"]) >= {"tools/lm_studio_tools.py", "README.md",
                                       "assets/SOUL.md", "skills/lm-studio/SKILL.md"}
    assert (root / "tools/lm_studio_tools.py").read_bytes() == NEW_WRAPPER["tools/lm_studio_tools.py"]
    assert (root / "README.md").read_bytes() == NEW_WRAPPER["README.md"]
    assert (root / "tools/web_tools.py").read_bytes() == b"upstream"   # core left alone
    # Repair overwrote upstream's README.md, so it kept a copy first.
    kept = root / report["kept_folder"]
    assert (kept / "README.md").read_bytes() == b"upstream readme"
    # Upstream's own swap replaces the whole tools/ folder, so the legacy
    # tools/custom location is lost to it; that is why Tool Maker keeps its
    # tools in HERMES_HOME/custom_tools (moved there on start), which survives.
    # Every other user path is unchanged.
    after = snapshot(root, USER_FILES)
    lost = {rel for rel in users_before if rel not in after}
    assert lost == {"tools/custom/my_tool.py"}
    assert after == {rel: h for rel, h in users_before.items() if rel not in lost}
    assert ".hermes/custom_tools/personal.py" in after
    assert wrapper.repair(root, quiet=True)["restored"] == []          # idempotent
    # The next core update adopts what upstream changed without losing anything.
    result = life.install(zip_path=str(core_zip(tmp_path, CORE_V2, SHA2, "v2.zip")))
    assert result["ok"], result
    assert (root / "tools/lm_studio_tools.py").read_bytes() == NEW_WRAPPER["tools/lm_studio_tools.py"]


def test_repair_is_a_noop_in_a_development_checkout(root):
    report = wrapper.repair(root, quiet=True)
    assert report["restored"] == []
    assert any("development checkout" in note for note in report["notes"])


def test_repair_skips_while_an_update_holds_the_lock(root):
    lock = common.InstallLock(root)
    assert lock.acquire()
    try:
        report = wrapper.repair(root, quiet=True)
    finally:
        lock.release()
    assert any("update is running" in note for note in report["notes"])


def test_repair_settles_an_interrupted_update(root, tmp_path):
    write_files(root, {"a.txt": b"old"})
    staged = common.staging_dir(root)
    write_files(staged, {"a.txt": b"new"})
    txn = common.Transaction(root, "core")
    txn.put("a.txt", staged / "a.txt")
    txn.apply()          # never committed: as if the updater died right here
    report = wrapper.repair(root, quiet=True)
    assert any("rolled back" in note for note in report["notes"])
    assert (root / "a.txt").read_bytes() == b"old"


@pytest.mark.parametrize("order", ["core-then-wrapper", "wrapper-then-core"])
def test_back_to_back_updates_in_either_order(root, tmp_path, order):
    verify = FakeVerify(root)
    life, _, _ = lifecycle(root, verify=verify)
    updater = WrapperUpdater(root, quiet=True, run_verify=verify)
    users_before = snapshot(root, USER_FILES)
    assert life.install(zip_path=str(core_zip(tmp_path, CORE_V1, SHA1, "v1.zip")))["ok"]
    steps = [lambda: life.install(zip_path=str(core_zip(tmp_path, CORE_V2, SHA2, "v2.zip"))),
             lambda: updater.update(zip_path=str(release_zip(tmp_path, NEW_WRAPPER, "v9.4.0")))]
    if order == "wrapper-then-core":
        steps.reverse()
    for step in steps:
        result = step()
        assert result["ok"], result
    assert (root / "run_agent.py").read_bytes() == CORE_V2["run_agent.py"]
    assert (root / "gui/app.py").read_bytes() == NEW_WRAPPER["gui/app.py"]
    assert (root / "tools/lm_studio_tools.py").read_bytes() == NEW_WRAPPER["tools/lm_studio_tools.py"]
    assert (root / "README.md").read_bytes() == NEW_WRAPPER["README.md"]
    assert snapshot(root, USER_FILES) == users_before
    assert wrapper.repair(root, quiet=True)["restored"] == []
    assert json.loads((root / ".portable/core-state.json").read_text())["commit"] == SHA2


# --------------------------------------------------------------------------
# UPDATE.bat entry point
# --------------------------------------------------------------------------

def test_update_command_hands_the_core_step_to_the_newly_installed_wrapper(root, monkeypatch):
    from portable_hermes import __main__ as cli

    calls = []
    monkeypatch.setattr(WrapperUpdater, "update",
                        lambda self, **kw: {"ok": True, "changed": True, "message": "v9"})
    monkeypatch.setattr(CoreLifecycle, "install",
                        lambda self, **kw: pytest.fail("old wrapper code ran the core step"))
    import subprocess
    monkeypatch.setattr(subprocess, "call", lambda cmd: calls.append(cmd) or 0)
    assert cli.main(["--root", str(root), "update", "--core", "--yes"]) == 0
    assert calls[0][-5:] == [str(root), "update", "--core-only", "--core", "--yes"]


def test_update_command_never_prompts_when_unattended(root, monkeypatch, capsys):
    from portable_hermes import __main__ as cli

    monkeypatch.setenv("HERMES_PORTABLE_NONINTERACTIVE", "1")
    monkeypatch.setattr(WrapperUpdater, "update",
                        lambda self, **kw: {"ok": True, "changed": False, "message": "current"})
    monkeypatch.setattr(CoreLifecycle, "check", lambda self, **kw: {
        "ok": True, "install_type": "zip", "commit": SHA1, "behind_by": 12,
        "update_available": True})
    monkeypatch.setattr(CoreLifecycle, "install",
                        lambda self, **kw: pytest.fail("core updated without consent"))
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("prompted"))
    assert cli.main(["--root", str(root), "update"]) == 0
    out = capsys.readouterr().out
    assert "12 upstream commits behind" in out and "UPDATE.bat --core" in out
