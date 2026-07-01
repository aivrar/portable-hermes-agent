"""Tests for portable launcher scripts."""

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = REPO_ROOT / "scripts" / "portable"


def test_portable_launcher_scripts_exist():
    assert (LAUNCHER_DIR / "hermes-portable.ps1").is_file()
    assert (LAUNCHER_DIR / "hermes-portable.cmd").is_file()
    assert (LAUNCHER_DIR / "hermes-portable.sh").is_file()


def test_launchers_pin_existing_hermes_home_only():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            LAUNCHER_DIR / "hermes-portable.ps1",
            LAUNCHER_DIR / "hermes-portable.cmd",
            LAUNCHER_DIR / "hermes-portable.sh",
        )
    )

    assert "HERMES_HOME" in combined
    assert "HERMES_YOLO_MODE" not in combined
    assert "HERMES_PORTABLE" not in combined
    assert "HermesHome \"extensions\"" in combined or "HERMES_HOME/extensions" in combined


def test_gitignore_excludes_portable_runtime_artifacts():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".hermes/" in gitignore
    assert "extensions/" in gitignore
    assert "python_embedded/" in gitignore


def test_git_update_autostash_leaves_portable_runtime_artifacts_in_place(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not available")

    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / ".gitignore").write_text((REPO_ROOT / ".gitignore").read_text(encoding="utf-8"))
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")

    portable_files = [
        tmp_path / ".hermes" / "config.yaml",
        tmp_path / "extensions" / "local-service" / "README.md",
        tmp_path / "python_embedded" / "python.exe",
    ]
    for path in portable_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("local\n", encoding="utf-8")

    git("stash", "push", "--include-untracked", "-m", "hermes-update-autostash")

    for path in portable_files:
        assert path.exists()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ".hermes" not in status
    assert "extensions" not in status
    assert "python_embedded" not in status


def test_portable_docs_credit_current_name_and_link_commands():
    docs = (REPO_ROOT / "docs" / "portable-mode.md").read_text(encoding="utf-8")

    assert "aivrar" in docs
    assert "hermes portable status" in docs
    assert "portable backup" in docs
    assert "updates.non_interactive_local_changes: discard" in docs
    assert "HERMES_YOLO_MODE" in docs


def test_sdist_manifest_includes_portable_launchers():
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "recursive-include scripts/portable *" in manifest
