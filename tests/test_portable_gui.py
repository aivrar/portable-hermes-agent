import importlib
import queue
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

# Most GUI modules import the Hermes core (dotenv, hermes_constants, run_agent);
# the branding check runs without it.


def _bridge_shell(agent_bridge, tmp_path):
    bridge = object.__new__(agent_bridge.AgentBridge)
    bridge.config = {
        "model": {"default": "provider/current-model"},
        "agent": {"max_turns": 12},
        "provider_routing": {},
    }
    bridge._active_provider = "cloud"
    bridge._lm_studio_base_url = None
    bridge._selected_model = "provider/current-model"
    bridge._session_db = None
    bridge.python_dir = tmp_path / "python_embedded"
    return bridge


@pytest.mark.needs_core
def test_portable_gui_modules_import():
    modules = (
        "gui.agent_bridge",
        "gui.api_setup_wizard",
        "gui.app",
        "gui.extensions",
        "gui.lm_studio",
        "gui.permissions",
        "gui.permissions_panel",
        "gui.theme",
    )

    assert all(importlib.import_module(module) for module in modules)


@pytest.mark.needs_core
def test_gui_startup_never_probes_lm_studio_on_tk_thread(monkeypatch):
    """Network discovery starts later in Sidebar.refresh_models' worker thread."""
    from gui import app

    class FakeRoot:
        def withdraw(self):
            pass

        def title(self, _value):
            pass

        def geometry(self, _value):
            pass

        def minsize(self, *_args):
            pass

        def deiconify(self):
            pass

        def after(self, *_args):
            pass

        def bind(self, *_args):
            pass

        def protocol(self, *_args):
            pass

    class FakeBridge:
        _startup_fallback = False

        def __init__(self, *_args, **_kwargs):
            pass

        def _validate_startup_model(self):
            raise AssertionError("startup must not perform the LM Studio network probe")

        def get_model(self):
            return "provider/model"

        def _is_local_model(self, _model):
            return False

        def _is_model_configured(self):
            return True

    monkeypatch.setattr(app.tk, "Tk", FakeRoot)
    monkeypatch.setattr(app, "AgentBridge", FakeBridge)
    monkeypatch.setattr(app, "init_dpi_scaling", lambda _root: None)
    monkeypatch.setattr(app, "apply_theme", lambda _root: None)
    monkeypatch.setattr(app, "center_window", lambda *_args: None)
    monkeypatch.setattr(app, "get_missing_keys", lambda: [])
    monkeypatch.setattr(app.HermesGUI, "_build_menu", lambda _self: None)

    def fake_layout(gui):
        gui.status_bar = SimpleNamespace(set_model=lambda _model: None)
        gui.sidebar = SimpleNamespace(set_model=lambda _model: None)

    monkeypatch.setattr(app.HermesGUI, "_build_layout", fake_layout)
    monkeypatch.setattr(app.HermesGUI, "_add_msg", lambda *_args: None)

    app.HermesGUI()


def test_gui_keeps_portable_branding_and_has_no_stale_version_label():
    source = (Path(__file__).resolve().parents[1] / "gui" / "app.py").read_text(
        encoding="utf-8"
    )

    from gui.i18n import TRANSLATIONS

    assert TRANSLATIONS["en"]["app.title"] == "Portable Hermes Agent"
    assert 'self.root.title(t("app.title"))' in source
    assert "github.com/aivrar/portable-hermes-agent" in source
    assert "Hermes Agent v0.2.0" not in source


@pytest.mark.needs_core
def test_gui_bridge_uses_current_runtime_provider(monkeypatch, tmp_path):
    from gui import agent_bridge
    import run_agent
    from hermes_cli import runtime_provider

    bridge = _bridge_shell(agent_bridge, tmp_path)
    captured = {}

    def fake_resolve_runtime_provider(**kwargs):
        assert kwargs == {"target_model": "provider/current-model"}
        return {
            "provider": "current-provider",
            "api_mode": "current-api-mode",
            "base_url": "https://current.example/v1",
            "api_key": "current-key",
            "credential_pool": "current-pool",
        }

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )

    bridge._create_agent()

    assert captured["provider"] == "current-provider"
    assert captured["api_mode"] == "current-api-mode"
    assert captured["base_url"] == "https://current.example/v1"
    assert captured["api_key"] == "current-key"
    assert captured["credential_pool"] == "current-pool"
    assert captured["platform"] == "gui"


@pytest.mark.needs_core
def test_gui_approval_bridge_returns_current_approval_choices():
    from gui.agent_bridge import AgentBridge

    seen = []

    class ImmediateRoot:
        @staticmethod
        def after(_delay, callback):
            callback()

    bridge = object.__new__(AgentBridge)
    bridge.root = ImmediateRoot()
    bridge.on_approval = lambda command, description: seen.append(
        (command, description)
    )
    bridge._approval_queue = queue.Queue()
    bridge._approval_queue.put(True)

    assert bridge._approval_callback("dangerous command", "changes files") == "once"
    assert seen == [("dangerous command", "changes files")]

    bridge._approval_queue.put(False)
    assert bridge._approval_callback("dangerous command", "changes files") == "deny"


@pytest.mark.needs_core
def test_local_chat_receives_saved_lmstudio_key(monkeypatch, tmp_path):
    from gui import agent_bridge, lm_studio
    import run_agent
    monkeypatch.setattr(lm_studio, "LMSTUDIO_CONFIG_PATH", tmp_path / "lm-config")
    assert lm_studio._write_lmstudio_config(base_url="http://localhost:1234", api_key="test-only")
    bridge = _bridge_shell(agent_bridge, tmp_path)
    monkeypatch.setenv("TERMINAL_CWD", str(agent_bridge.PROJECT_ROOT))
    bridge.config["terminal"] = {"cwd": "."}
    bridge.set_local_mode("http://localhost:1234", "local-model")
    captured = {}
    monkeypatch.setattr(run_agent, "AIAgent", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", ""))
    bridge._create_agent()
    assert captured["api_key"] == "test-only"
    assert captured["base_url"] == "http://localhost:1234/v1"
    assert captured["skip_context_files"] is True
    assert captured["load_soul_identity"] is True
    bridge.config["terminal"] = {"cwd": str(tmp_path)}
    bridge._create_agent()
    assert captured["skip_context_files"] is False


@pytest.mark.needs_core
def test_real_local_gui_agent_constructs_without_install_tree_instructions(monkeypatch, tmp_path):
    from gui import agent_bridge
    from agent.system_prompt import build_system_prompt
    monkeypatch.setenv("TERMINAL_CWD", str(agent_bridge.PROJECT_ROOT))
    bridge = _bridge_shell(agent_bridge, tmp_path)
    bridge.config["terminal"] = {"cwd": "."}
    bridge.set_local_mode("http://127.0.0.1:1234", "local-test")
    # Real AIAgent initialization, including Windows logging dependencies.
    bridge._create_agent()
    try:
        assert bridge.agent.skip_context_files is True
        assert bridge.agent.load_soul_identity is True
        prompt = build_system_prompt(bridge.agent)
        assert "Hermes Agent - Development Guide" not in prompt
    finally:
        bridge.agent = None


@pytest.mark.needs_core
def test_gui_bridge_close_releases_owned_session_database():
    from gui.agent_bridge import AgentBridge

    class FakeDB:
        closed = False

        def close(self):
            self.closed = True

    bridge = object.__new__(AgentBridge)
    bridge.agent = None
    bridge.is_running = False
    bridge._session_db = FakeDB()

    bridge.close()

    assert bridge._session_db is None


@pytest.mark.needs_core
def test_gui_skill_browser_discovers_current_nested_skill_layout(tmp_path):
    from gui.app import _discover_installed_skills

    skill = tmp_path / "extensions" / "lm-studio" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "name: lm-studio\n"
        "description: Control local models.\n"
        "metadata:\n"
        "  hermes:\n"
        "    category: extensions\n"
        "---\n\n# LM Studio\n",
        encoding="utf-8",
    )

    assert _discover_installed_skills(tmp_path) == {
        "extensions": [("lm-studio", "Control local models.")]
    }


@pytest.mark.needs_core
def test_gui_api_key_wizard_persists_to_active_hermes_home(monkeypatch, tmp_path):
    from gui import api_setup_wizard

    monkeypatch.setattr(api_setup_wizard, "get_hermes_home", lambda: tmp_path)
    monkeypatch.delenv("PORTABLE_TEST_API_KEY", raising=False)

    api_setup_wizard._save_key_to_env("PORTABLE_TEST_API_KEY", "secret-value")

    assert (tmp_path / ".env").read_text(encoding="utf-8") == (
        "\nPORTABLE_TEST_API_KEY=secret-value\n"
    )


def _sidebar_shell(app):
    sidebar = object.__new__(app.Sidebar)
    sidebar._render_sessions = lambda: None
    return sidebar


@pytest.mark.needs_core
def test_gui_sidebar_hides_sessions_without_messages():
    """Empty sessions (failed first turn, gateway resets) cannot be resumed."""
    from gui import app
    from hermes_state import SessionDB

    with SessionDB() as db:
        db.create_session(session_id="empty_session", source="gui", model="m")
        db.create_session(session_id="chat_session", source="gui", model="m")
        db.append_message("chat_session", "user", "hello")

    sidebar = _sidebar_shell(app)
    sidebar._load_sessions()

    assert [s["id"] for s in sidebar._sessions_data] == ["chat_session"]


@pytest.mark.needs_core
def test_gui_sidebar_detects_current_core_session_filter():
    import inspect
    from hermes_state import SessionDB

    with SessionDB() as db:
        params = inspect.signature(db.list_sessions_rich).parameters

    assert "min_message_count" in params


def _fake_session_db(rows, calls, supports_filter):
    """A SessionDB stand-in whose rows are newest first, honouring ``limit``."""

    class FakeSessionDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        if supports_filter:
            def list_sessions_rich(self, source=None, limit=20, min_message_count=0):
                calls.append({"limit": limit, "min_message_count": min_message_count})
                raise TypeError("bug inside a core that supports the filter")
        else:
            def list_sessions_rich(self, source=None, limit=20):
                calls.append({"limit": limit})
                return rows[:limit]

    return SimpleNamespace(SessionDB=FakeSessionDB)


@pytest.mark.needs_core
def test_gui_sidebar_old_core_fallback_survives_20_newer_empty_sessions(monkeypatch):
    import sys
    from gui import app

    rows = ([{"id": f"empty{i}", "message_count": 0} for i in range(20)]
            + [{"id": f"chat{i}", "message_count": 2} for i in range(25)])
    calls = []
    monkeypatch.setitem(sys.modules, "hermes_state",
                        _fake_session_db(rows, calls, supports_filter=False))

    sidebar = _sidebar_shell(app)
    sidebar._load_sessions()

    assert [s["id"] for s in sidebar._sessions_data] == [f"chat{i}" for i in range(20)]
    assert calls == [{"limit": 200}]


@pytest.mark.needs_core
def test_gui_sidebar_does_not_retry_when_supporting_core_raises_type_error(monkeypatch):
    import sys
    from gui import app

    calls = []
    monkeypatch.setitem(sys.modules, "hermes_state",
                        _fake_session_db([], calls, supports_filter=True))

    sidebar = _sidebar_shell(app)
    sidebar._load_sessions()

    assert calls == [{"limit": 20, "min_message_count": 1}]
    assert sidebar._sessions_data == []


def _tool_progress_bridge():
    from gui.agent_bridge import AgentBridge

    bridge = object.__new__(AgentBridge)
    bridge.on_tool_call = object()
    posted = []
    bridge._post = lambda callback, *args: posted.append((callback, args))
    return bridge, posted


@pytest.mark.needs_core
def test_gui_tool_bubble_uses_tool_name_from_current_core_events():
    bridge, posted = _tool_progress_bridge()

    bridge._on_tool_progress("tool.started", "gpu_info", None, {})
    bridge._on_tool_progress("tool.started", "terminal", "nvidia-smi", {"command": "nvidia-smi"})
    bridge._on_tool_progress("tool.started", "read_file", None, {"path": "a.txt"})

    assert [args for _, args in posted] == [
        ("gpu_info", None), ("terminal", "nvidia-smi"), ("read_file", {"path": "a.txt"})]
    assert all(callback is bridge.on_tool_call for callback, _ in posted)


@pytest.mark.needs_core
def test_gui_tool_bubble_ignores_non_start_progress_events():
    bridge, posted = _tool_progress_bridge()

    bridge._on_tool_progress("tool.completed", "gpu_info", None, None,
                             duration=0.1, is_error=False, result="{}")
    bridge._on_tool_progress("tool.progress", "terminal", "50%", None, tool_call_id="c1")
    bridge._on_tool_progress("tool.output_risk", "web", None, None, risk_metadata={})
    bridge._on_tool_progress("reasoning.available", "_thinking", "hmm", None)
    bridge._on_tool_progress("_thinking", "first line")
    bridge._on_tool_progress("moa.progress", refs_done=1, refs_total=2, label="x")

    assert posted == []


@pytest.mark.needs_core
def test_gui_tool_bubble_still_accepts_legacy_name_preview_calls():
    bridge, posted = _tool_progress_bridge()

    bridge._on_tool_progress("gpu_info", "query GPUs")

    assert [args for _, args in posted] == [("gpu_info", "query GPUs")]


def _streamed(chunks):
    """(shown text, height, raw text) of a StreamingBubble fed *chunks*, finalized."""
    import tkinter as tk
    from gui import app

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    try:
        bubble = app.StreamingBubble(root)
        for delta in chunks:
            bubble.append_text(delta)
        bubble.finalize()
        return (bubble._body.get("1.0", "end-1c"), int(bubble._body.cget("height")),
                bubble.get_text())
    finally:
        root.destroy()


@pytest.mark.needs_core
def test_gui_streamed_reply_has_no_leading_or_trailing_blank_lines():
    chunks = ("\n", "\n", "Hello", " world\n", "line two", "\n\n", " \n")
    shown, height, raw = _streamed(chunks)

    assert shown == "Hello world\nline two"
    assert height == 2
    # The raw stream stays available to the caller unchanged.
    assert raw == "".join(chunks)


@pytest.mark.needs_core
def test_gui_streamed_reply_keeps_first_line_indentation():
    assert _streamed(("\n\n", "    print(1)\n", "done"))[0] == "    print(1)\ndone"
    # Indentation split over chunks, after whitespace-only chunks.
    assert _streamed((" \n", "\n  ", "  print(1)"))[0] == "    print(1)"
    assert _streamed(("  ", "x"))[0] == "  x"


@pytest.mark.needs_core
def test_gui_sidebar_auto_load_calls_load_model_and_reports_instance_id(monkeypatch):
    import logging
    from unittest.mock import Mock
    from gui import app
    from gui import lm_studio as lm

    if not lm.HAS_SDK:
        pytest.skip("lmstudio SDK not installed")
    target = Mock(model_key="deepseek@q4_k_m", path="p/deepseek", display_name="DeepSeek")
    target.load_new_instance.return_value = SimpleNamespace(identifier="deepseek")
    llm = Mock()
    llm.list_loaded.return_value = []
    llm.list_downloaded.return_value = [target]

    def connect(client):
        client._sdk_client = SimpleNamespace(llm=llm)
        return True

    monkeypatch.setattr(lm.LMStudioPanel, "_resolve_base_url",
                        staticmethod(lambda: "http://127.0.0.1:9/v1"))
    monkeypatch.setattr(lm.LMStudioClient, "connect_sdk", connect)
    settings = {"gpu_index": None, "context_length": 65536, "flash_attention": True}

    result = app._auto_load_local_model("deepseek@q4_k_m", settings, logging.getLogger("t"))

    assert result == (True, "", "deepseek")
    target.load_new_instance.assert_called_once()


def _auto_load_sidebar(app, local_ids):
    from unittest.mock import Mock

    sidebar = object.__new__(app.Sidebar)
    rows = [(mid, mid, "LM Studio") for mid in local_ids]
    sidebar.__dict__.update(
        _loading_model=True, model_combo=Mock(), _show_load_status=Mock(),
        _model_states={}, after=Mock(), model_var=Mock(),
        _lm_studio_models=list(rows), _all_models=list(rows),
        on_local_models=Mock(), on_auto_load=Mock(), on_model_change=Mock())
    return sidebar


@pytest.mark.needs_core
def test_gui_sidebar_auto_load_switches_chat_to_the_loaded_instance():
    from gui import app

    sidebar = _auto_load_sidebar(app, ["deepseek@q4_k_m"])

    sidebar._on_auto_load_complete("deepseek@q4_k_m", True, "", "deepseek")

    sidebar.on_local_models.assert_called_once_with(["deepseek@q4_k_m", "deepseek"])
    sidebar.on_model_change.assert_called_once_with("deepseek")
    sidebar.model_var.set.assert_called_once_with("deepseek")
    assert sidebar._model_states == {"deepseek": "loaded"}


@pytest.mark.needs_core
def test_gui_sidebar_auto_load_keeps_model_id_when_instance_matches_or_load_fails():
    from gui import app

    same = _auto_load_sidebar(app, ["gemma"])
    same._on_auto_load_complete("gemma", True, "", "gemma")
    same.on_model_change.assert_called_once_with("gemma")
    same.on_local_models.assert_not_called()

    failed = _auto_load_sidebar(app, ["gemma"])
    failed._on_auto_load_complete("gemma", False, "boom", None)
    failed.on_model_change.assert_called_once_with("gemma")
    failed.on_auto_load.assert_called_once_with("gemma", False, "boom")
