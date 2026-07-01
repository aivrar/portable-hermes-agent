"""Tests for the ``hermes hooks`` CLI subcommand."""

from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import subprocess
from functools import lru_cache
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent import shell_hooks
from hermes_cli import hooks as hooks_cli


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("HERMES_ACCEPT_HOOKS", raising=False)
    shell_hooks.reset_for_tests()
    yield
    shell_hooks.reset_for_tests()


def _hook_script(tmp_path: Path, body: str, name: str = "hook.sh") -> Path:
    p = tmp_path / name
    p.write_text(body, newline="\n")
    p.chmod(0o755)
    return p


@lru_cache(maxsize=1)
def _bash_uses_wsl_mounts() -> bool:
    if os.name != "nt":
        return False
    bash_path = (shutil.which("bash") or "").replace("\\", "/").lower()
    if "/windows/system32/bash" in bash_path or "/windowsapps/" in bash_path:
        return True
    try:
        result = subprocess.run(
            ["bash", "-lc", "case \"$PWD\" in /mnt/*) echo wsl;; *) echo other;; esac"],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return result.stdout.strip() == "wsl"


def _bash_path(path: Path) -> str:
    raw = str(path)
    if os.name == "nt":
        drive, tail = os.path.splitdrive(raw)
        if drive:
            tail = tail.replace("\\", "/")
            drive_letter = drive[:1].lower()
            if _bash_uses_wsl_mounts():
                return f"/mnt/{drive_letter}{tail}"
            return f"/{drive_letter}{tail}"
    return raw


def _hook_command(script: Path) -> str:
    if os.name == "nt":
        return f"bash {shlex.quote(_bash_path(script))}"
    return str(script)


def _run(sub_args: SimpleNamespace) -> str:
    """Capture stdout for a hooks_command invocation."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        hooks_cli.hooks_command(sub_args)
    return buf.getvalue()


# ── list ──────────────────────────────────────────────────────────────────


class TestHooksList:
    def test_empty_config(self, tmp_path):
        with patch("hermes_cli.config.load_config", return_value={}):
            out = _run(SimpleNamespace(hooks_action="list"))
        assert "No shell hooks configured" in out

    def test_shows_configured_and_consent_status(self, tmp_path):
        script = _hook_script(
            tmp_path, "#!/usr/bin/env bash\nprintf '{}\\n'\n",
        )
        cfg = {
            "hooks": {
                "pre_tool_call": [
                    {"matcher": "terminal", "command": str(script), "timeout": 30},
                ],
                "on_session_start": [
                    {"command": str(script)},
                ],
            }
        }

        # Approve one of the two so we can see both states in the output
        shell_hooks._record_approval("pre_tool_call", str(script))

        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(hooks_action="list"))

        assert "[pre_tool_call]" in out
        assert "[on_session_start]" in out
        assert "✓ allowed" in out
        assert "✗ not allowlisted" in out
        assert str(script) in out


# ── test ──────────────────────────────────────────────────────────────────


class TestHooksTest:
    def test_synthetic_payload_matches_production_shape(self, tmp_path):
        """`hermes hooks test` must feed the script stdin in the same
        shape invoke_hook() would at runtime.  Prior to this fix,
        run_once bypassed _serialize_payload and the two paths diverged —
        scripts tested with `hermes hooks test` saw different top-level
        keys than at runtime, silently breaking in production."""
        capture = tmp_path / "captured.json"
        script = _hook_script(
            tmp_path,
            f"#!/usr/bin/env bash\ncat - > {_bash_path(capture)}\nprintf '{{}}\\n'\n",
        )
        cfg = {"hooks": {"subagent_stop": [{"command": _hook_command(script)}]}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            _run(SimpleNamespace(
                hooks_action="test", event="subagent_stop",
                for_tool=None, payload_file=None,
            ))

        seen = json.loads(capture.read_text())
        # Same top-level keys _serialize_payload produces at runtime
        assert set(seen.keys()) == {
            "hook_event_name", "tool_name", "tool_input",
            "session_id", "cwd", "extra",
        }
        # parent_session_id was routed to top-level session_id (matches runtime)
        assert seen["session_id"] == "parent-sess"
        assert "parent_session_id" not in seen["extra"]
        # subagent_stop has no tool, so tool_name / tool_input are null
        assert seen["tool_name"] is None
        assert seen["tool_input"] is None

    def test_fires_real_subprocess_and_parses_block(self, tmp_path):
        block_script = _hook_script(
            tmp_path,
            "#!/usr/bin/env bash\n"
            'printf \'{"decision": "block", "reason": "nope"}\\n\'\n',
            name="block.sh",
        )
        cfg = {
            "hooks": {
                "pre_tool_call": [
                    {"matcher": "terminal", "command": _hook_command(block_script)},
                ],
            },
        }
        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(
                hooks_action="test", event="pre_tool_call",
                for_tool="terminal", payload_file=None,
            ))

        # Parsed block appears in output
        assert '"action": "block"' in out
        assert '"message": "nope"' in out

    def test_for_tool_matcher_filters(self, tmp_path):
        script = _hook_script(tmp_path, "#!/usr/bin/env bash\nprintf '{}\\n'\n")
        cfg = {
            "hooks": {
                "pre_tool_call": [
                    {"matcher": "terminal", "command": _hook_command(script)},
                ],
            }
        }
        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(
                hooks_action="test", event="pre_tool_call",
                for_tool="web_search", payload_file=None,
            ))
        assert "No shell hooks" in out

    def test_unknown_event(self):
        with patch("hermes_cli.config.load_config", return_value={}):
            out = _run(SimpleNamespace(
                hooks_action="test", event="bogus_event",
                for_tool=None, payload_file=None,
            ))
        assert "Unknown event" in out


# ── revoke ────────────────────────────────────────────────────────────────


class TestHooksRevoke:
    def test_revoke_removes_entry(self, tmp_path):
        script = _hook_script(tmp_path, "#!/usr/bin/env bash\n")
        shell_hooks._record_approval("on_session_start", str(script))

        out = _run(SimpleNamespace(hooks_action="revoke", command=str(script)))
        assert "Removed 1" in out
        assert shell_hooks.allowlist_entry_for(
            "on_session_start", str(script),
        ) is None

    def test_revoke_unknown(self, tmp_path):
        out = _run(SimpleNamespace(
            hooks_action="revoke", command=str(tmp_path / "never.sh"),
        ))
        assert "No allowlist entry" in out


# ── doctor ────────────────────────────────────────────────────────────────


class TestHooksDoctor:
    def test_flags_missing_exec_bit(self, tmp_path):
        script = tmp_path / "hook.sh"
        script.write_text("#!/usr/bin/env bash\nprintf '{}\\n'\n")
        # No chmod — intentionally not executable
        cfg = {"hooks": {"on_session_start": [{"command": str(script)}]}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(hooks_action="doctor"))
        assert "not executable" in out.lower()

    def test_flags_unallowlisted(self, tmp_path):
        script = _hook_script(tmp_path, "#!/usr/bin/env bash\nprintf '{}\\n'\n")
        cfg = {"hooks": {"on_session_start": [{"command": str(script)}]}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(hooks_action="doctor"))
        assert "not allowlisted" in out.lower()

    def test_flags_invalid_json(self, tmp_path):
        script = _hook_script(
            tmp_path,
            "#!/usr/bin/env bash\necho 'not json!'\n",
        )
        command = _hook_command(script)
        shell_hooks._record_approval("on_session_start", command)
        cfg = {"hooks": {"on_session_start": [{"command": command}]}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(hooks_action="doctor"))
        assert "not valid JSON" in out

    def test_flags_mtime_drift(self, tmp_path, monkeypatch):
        """Allowlist with older mtime than current -> drift warning."""
        script = _hook_script(tmp_path, "#!/usr/bin/env bash\nprintf '{}\\n'\n")

        # Manually stash an allowlist entry with an old mtime
        from agent.shell_hooks import allowlist_path
        allowlist_path().parent.mkdir(parents=True, exist_ok=True)
        allowlist_path().write_text(json.dumps({
            "approvals": [
                {
                    "event": "on_session_start",
                    "command": _hook_command(script),
                    "approved_at": "2000-01-01T00:00:00Z",
                    "script_mtime_at_approval": "2000-01-01T00:00:00Z",
                }
            ]
        }))

        cfg = {"hooks": {"on_session_start": [{"command": _hook_command(script)}]}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(hooks_action="doctor"))
        assert "modified since approval" in out

    def test_clean_script_runs(self, tmp_path):
        script = _hook_script(tmp_path, "#!/usr/bin/env bash\nprintf '{}\\n'\n")
        command = _hook_command(script)
        shell_hooks._record_approval("on_session_start", command)
        cfg = {"hooks": {"on_session_start": [{"command": command}]}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(hooks_action="doctor"))
        assert "All shell hooks look healthy" in out

    def test_unallowlisted_script_is_not_executed(self, tmp_path):
        """Regression for M4: `hermes hooks doctor` used to run every
        listed script against a synthetic payload as part of its JSON
        smoke test, which contradicted the documented workflow of
        "spot newly-added hooks *before they register*".  An un-allowlisted
        script must not be executed during `doctor`."""
        sentinel = tmp_path / "executed"
        # Script would touch the sentinel if executed; we assert it wasn't.
        script = _hook_script(
            tmp_path,
            f"#!/usr/bin/env bash\ntouch {_bash_path(sentinel)}\nprintf '{{}}\\n'\n",
        )
        cfg = {"hooks": {"on_session_start": [{"command": _hook_command(script)}]}}
        with patch("hermes_cli.config.load_config", return_value=cfg):
            out = _run(SimpleNamespace(hooks_action="doctor"))

        assert not sentinel.exists(), (
            "doctor executed an un-allowlisted script — "
            "M4 gate regressed"
        )
        assert "not allowlisted" in out.lower()
        assert "skipped JSON smoke test" in out
