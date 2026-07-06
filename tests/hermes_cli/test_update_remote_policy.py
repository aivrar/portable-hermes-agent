import subprocess
from pathlib import Path
from unittest.mock import patch

from hermes_cli import main as hm


def test_official_repo_url_policy_accepts_portable_forms():
    assert hm._is_official_repo_url(
        "https://github.com/aivrar/portable-hermes-agent.git"
    )
    assert hm._is_official_repo_url(
        "git@github.com:aivrar/portable-hermes-agent.git"
    )
    assert hm._is_fork("https://github.com/NousResearch/hermes-agent.git")


def test_sync_with_upstream_skips_nonportable_existing_upstream(capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["git", "remote", "get-url", "upstream"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="https://github.com/NousResearch/hermes-agent.git\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd!r}")

    with patch.object(hm.subprocess, "run", side_effect=fake_run):
        hm._sync_with_upstream_if_needed(["git"], Path("unused"))

    out = capsys.readouterr().out
    assert "not Portable Hermes Agent" in out
    assert "https://github.com/NousResearch/hermes-agent.git" in out
    assert not any(cmd[:3] == ["git", "fetch", "upstream"] for cmd in calls)


def test_sync_with_upstream_fetches_official_portable_upstream(capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["git", "remote", "get-url", "upstream"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="https://github.com/aivrar/portable-hermes-agent.git\n",
                stderr="",
            )
        if cmd == ["git", "fetch", "upstream", "main", "--quiet"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd == ["git", "rev-list", "--count", "upstream/main..origin/main"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
        if cmd == ["git", "rev-list", "--count", "origin/main..upstream/main"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd!r}")

    with patch.object(hm.subprocess, "run", side_effect=fake_run):
        hm._sync_with_upstream_if_needed(["git"], Path("unused"))

    out = capsys.readouterr().out
    assert "Fork is up to date with upstream" in out
    assert ["git", "fetch", "upstream", "main", "--quiet"] in calls
