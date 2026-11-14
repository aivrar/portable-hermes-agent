"""The repository holds only the portable wrapper (issue #176).

START.bat (in CI: ``python -m portable_hermes core install``) installs the
Hermes core into a checkout, next to the wrapper files. So:

- every tracked file ships in a release or is a known development file, and
  nothing else gets tracked by accident;
- ``.gitignore`` ignores the core and user data, and never a wrapper file;
- ``git archive`` (GitHub's source ZIP, which the v1.4.18 updater downloads)
  leaves out ``tools/`` and ``skills/`` and keeps everything else
  (``.gitattributes`` says why).
"""

from __future__ import annotations

import fnmatch
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

import build_release
from portable_hermes import ownership
from tests import IN_CI

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Tracked files that are not part of a release. Anything else that is tracked
#: must ship (``build_release.should_exclude`` is False for it).
DEVELOPMENT_FILES = (
    ".gitattributes",
    ".gitignore",
    "build_release.py",
    "pytest.ini",
    ".github/FUNDING.yml",
    ".github/SECURITY.md",
    ".github/dependabot.yml",
    ".github/workflows/*.yml",
    "tests/*.py",
    "tests/requirements.txt",
)

#: Left out of `git archive` by .gitattributes.
EXPORT_IGNORED = ("tools", "skills")


def git(*args: str, data: bytes | None = None) -> bytes:
    """git in this checkout; outside a git checkout the tests skip (in CI: fail)."""
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), *args], input=data,
                          capture_output=True)
    # check-ignore exits with 1 when no path is ignored.
    if proc.returncode not in ((0, 1) if "check-ignore" in args else (0,)):
        message = (f"git {' '.join(args[:3])} failed in this checkout: "
                   f"{proc.stderr.decode(errors='replace').strip()}")
        (pytest.fail if IN_CI else pytest.skip)(message)
    return proc.stdout


def split(out: bytes) -> list[str]:
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def tracked() -> list[str]:
    return split(git("ls-files", "-z"))


def ignored(paths) -> set[str]:
    """The paths among *paths* that .gitignore ignores, whether tracked or not."""
    data = "".join(f"{p}\0" for p in paths).encode("utf-8", "surrogateescape")
    return set(split(git("check-ignore", "--no-index", "--stdin", "-z", data=data)))


def is_development_file(rel: str) -> bool:
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in DEVELOPMENT_FILES)


def test_every_tracked_file_ships_or_is_a_known_development_file():
    files = tracked()
    stray = [p for p in files if build_release.should_exclude(p) and not is_development_file(p)]
    assert stray == [], ("tracked files that are neither shipped nor development files "
                         "(a stray file, or a new wrapper path missing from "
                         "portable_hermes/ownership.py?)")
    unused = [pat for pat in DEVELOPMENT_FILES
              if not any(fnmatch.fnmatchcase(p, pat) for p in files)]
    assert unused == []
    # What ships is wrapper-owned (or the licence): no core file is tracked.
    assert all(ownership.classify(p) == "wrapper" or ownership.is_release_only(p)
               for p in files if not build_release.should_exclude(p))
    assert not any(ownership.is_core_installable(p) and not ownership.is_release_only(p)
                   for p in files)


def test_gitignore_hides_the_core_and_user_data_but_no_wrapper_file():
    files = tracked()
    assert ignored(files) == set(), "tracked files that .gitignore ignores"

    # Every path the ownership model gives the wrapper stays visible to git,
    # including new files in wrapper folders.
    wrapper_paths = (
        set(ownership.WRAPPER_ROOT_FILES) | set(ownership.WRAPPER_DEV_ONLY)
        | set(ownership.WRAPPER_CORE_TREE_FILES) | set(ownership.RELEASE_ONLY_FILES)
        | {f"{tree}/new_file.py" for tree in ownership.WRAPPER_ROOT_TREES}
        | {f"{tree}/new-skill/SKILL.md" for tree in ownership.WRAPPER_CORE_TREE_DIRS}
        | {"README.fr.md", ".github/workflows/new.yml", "tests/portable/test_new.py"})
    assert {p for p in wrapper_paths if not ownership.is_user(p)} == wrapper_paths
    assert ignored(wrapper_paths) == set()

    # Every file the core installer may write (the core of every release up to
    # v1.4.18, plus files of today's upstream core) is ignored.
    legacy = (REPO_ROOT / "portable_hermes/manifests/legacy-core-files.txt").read_text(
        encoding="utf-8").splitlines()
    core_paths = {p for p in legacy if p and not p.startswith("#")} | {
        "run_agent.py", "pyproject.toml", "uv.lock", "AGENTS.md", ".env.example",
        "cli-config.yaml.example", "hermes_cli/main.py", "agent/memory_manager.py",
        "tools/__init__.py", "tools/registry.py", "skills/creative/comfyui/SKILL.md",
        "docs/upstream-page.md", "assets/banner.png"}
    core_paths = {p for p in core_paths
                  if ownership.is_core_installable(p) and not ownership.is_release_only(p)}
    assert len(core_paths) > 5000
    assert sorted(core_paths - ignored(core_paths)) == []

    # User data and runtime state, at the top level and inside wrapper folders.
    user_paths = (
        {f"{name}/x" for name in ownership.USER_TOP_LEVEL if name != ".git"}
        | {name for name in ownership.USER_TOP_LEVEL if name != ".git"}
        | {f"{tree}/mine.py" for tree in ownership.USER_NESTED}
        | {"python_embedded.old-3.13.12/python.exe", ".portable/core-state.json",
           ".portable/kept/20261114-101500-wrapper/tools/update_hermes_tool.py",
           "gui/__pycache__/app.cpython-314.pyc", "portable_hermes/core.pyc",
           "tests/portable/__pycache__/x.cpython-314.pyc"})
    assert sorted(user_paths - ignored(user_paths)) == []

    # What the release builder adds to a release is never committed.
    generated = {ownership.RELEASE_MANIFEST, f"{ownership.PAYLOAD_DIR}/tools/gpu_tool.py"}
    assert ignored(generated) == generated


def test_git_archive_leaves_out_tools_and_skills_and_keeps_everything_else():
    archive = git("-c", "core.autocrlf=false", "archive", "--format=tar", "HEAD")
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = tar.getmembers()
    names = {m.name.rstrip("/") for m in members}
    # Not even an empty folder: v1.4.18's updater would swap it in for the old one.
    assert not [n for n in names if n.split("/")[0] in EXPORT_IGNORED]
    at_head = set(split(git("ls-tree", "-r", "--name-only", "-z", "HEAD")))
    files = {m.name for m in members if m.isfile()}
    assert files == {p for p in at_head if p.split("/")[0] not in EXPORT_IGNORED}
    # The portable tools are tracked (and shipped by build_release.py) ...
    assert {"tools/update_hermes_tool.py", "skills/lm-studio/SKILL.md"} <= at_head
    # ... and the file the "GitHub's source download" check in install.bat and
    # start.cmd looks for is one of those left out.
    for launcher in ("install.bat", "portable_hermes/launch/start.cmd"):
        text = (REPO_ROOT / launcher).read_text(encoding="ascii")
        assert 'if not exist "%PH_ROOT%\\tools\\update_hermes_tool.py"' in text, launcher
    out = git("check-attr", "--source=HEAD", "export-ignore", "--", *EXPORT_IGNORED)
    assert out.decode().splitlines() == [f"{name}: export-ignore: set" for name in EXPORT_IGNORED]
