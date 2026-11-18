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

    import threading

    bridge = object.__new__(AgentBridge)
    bridge.agent = None
    bridge.is_running = False
    bridge._shutdown_once = threading.Lock()
    db = bridge._session_db = FakeDB()

    bridge.close()
    bridge.close()                     # a second close is harmless

    assert bridge._session_db is None and db.closed


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
def test_gui_wrapped_session_title_is_left_aligned():
    import tkinter as tk
    from gui import app

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    try:
        sidebar = object.__new__(app.Sidebar)
        sidebar.session_frame = tk.Frame(root)
        sidebar._add_session_entry({"id": "s1", "title": "Output sequence of numbers 1 to 60",
                                    "message_count": 4, "model": "gemma-4-e4b-it"})
        entry = sidebar._session_widgets["s1"]
        title = entry.winfo_children()[0].winfo_children()[0]
        assert title.cget("text").startswith("Output sequence")
        assert str(title.cget("justify")) == "left" and str(title.cget("anchor")) == "w"
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


@pytest.mark.needs_core
def test_gui_sidebar_auto_load_uses_the_selected_gpu_placement(monkeypatch):
    import logging
    from unittest.mock import Mock
    from gui import app
    from gui import lm_studio as lm

    calls = []

    class FakeClient:
        last_loaded_identifier = "deepseek"

        def __init__(self, base_url):
            pass

        def connect_sdk(self):
            return True

        def load_model(self, model_id, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(lm, "LMStudioClient", FakeClient)
    monkeypatch.setattr(lm.LMStudioPanel, "_resolve_base_url",
                        staticmethod(lambda: "http://127.0.0.1:9/v1"))
    settings = {"gpu_placement": "split", "gpu_index": None,
                "context_length": 65536, "flash_attention": True}

    assert app._auto_load_local_model("deepseek", settings, logging.getLogger("t"))[0]

    assert calls[0]["gpu_placement"] == "split" and calls[0]["gpu_index"] is None


@pytest.mark.needs_core
def test_gui_sidebar_gpu_choices_keep_the_selection_and_translate(monkeypatch):
    from unittest.mock import MagicMock
    from gui import app
    from gui import i18n
    from portable_hermes import lmstudio_gpu as gpu_place

    gpus = [gpu_place.NvidiaGpu(0, "RTX 3060", 12288), gpu_place.NvidiaGpu(1, "RTX 3090", 24576)]

    class Var:
        value = ""

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    sidebar = object.__new__(app.Sidebar)
    sidebar.__dict__.update(_gpu_var=Var(), _gpus=[], _gpu_label_to_placement={},
                            _gpu_combo=MagicMock(), _save_local_settings=lambda: None)

    sidebar._populate_gpus(gpus)
    assert sidebar._get_gpu_placement() == "gpu:0"          # default: first GPU
    label_of = {p: label for label, p in sidebar._gpu_label_to_placement.items()}
    sidebar._gpu_var.set(label_of["split"])                  # user picks "All GPUs"
    assert sidebar._get_gpu_placement() == "split"
    assert sidebar._get_gpu_index() is None

    old = i18n.get_language()
    try:
        i18n.set_language("es", persist=False)
        sidebar._show_gpu_choices(sidebar._get_gpu_placement())   # language switch
        assert sidebar._gpu_var.get() == i18n.TRANSLATIONS["es"]["lmstudio.gpu_split"]
        assert sidebar._get_gpu_placement() == "split"
    finally:
        i18n.set_language(old, persist=False)

    sidebar._populate_gpus(gpus[:1])                        # split no longer offered
    assert sidebar._get_gpu_placement() == "gpu:0" and sidebar._get_gpu_index() == 0


@pytest.mark.needs_core
@pytest.mark.parametrize("choice", ["cpu", "auto"])
def test_gui_sidebar_keeps_a_gpu_choice_made_during_detection(choice):
    from unittest.mock import MagicMock
    from gui import app
    from portable_hermes import lmstudio_gpu as gpu_place

    class Var:
        value = ""

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    saved = []
    sidebar = object.__new__(app.Sidebar)
    sidebar.__dict__.update(_gpu_var=Var(), _gpus=[], _gpu_label_to_placement={},
                            _gpu_combo=MagicMock(), _gpu_user_choice=None,
                            _save_local_settings=lambda: saved.append(1))
    sidebar._show_gpu_choices()                         # before detection: auto, cpu
    label_of = {p: label for label, p in sidebar._gpu_label_to_placement.items()}
    sidebar._gpu_var.set(label_of[choice])
    sidebar._on_gpu_chosen()                            # the user's pick
    assert saved == [1]

    sidebar._populate_gpus([gpu_place.NvidiaGpu(0, "RTX 3060", 12288),
                            gpu_place.NvidiaGpu(1, "RTX 3090", 24576)])

    assert sidebar._get_gpu_placement() == choice      # not reset to GPU 0


@pytest.mark.needs_core
def test_gui_sidebar_auto_load_reports_an_estimated_gpu(monkeypatch):
    import logging
    from unittest.mock import Mock
    from gui import app
    from gui import lm_studio as lm
    from portable_hermes import lmstudio_gpu as gpu_place

    nvidia = [gpu_place.NvidiaGpu(0, "RTX 3060", 12288), gpu_place.NvidiaGpu(1, "RTX 3090", 24576)]
    plans = {"estimated": gpu_place.plan("gpu:1", nvidia, None),
             "confirmed": gpu_place.plan(
                 "gpu:1", nvidia, [gpu_place.LmStudioGpu(0, "RTX 3090", 24575),
                                   gpu_place.LmStudioGpu(1, "RTX 3060", 12287)])}
    current = {}

    class FakeClient:
        last_loaded_identifier = "deepseek"

        def __init__(self, base_url):
            self.last_gpu_plan = plans[current["kind"]]

        def connect_sdk(self):
            return True

        def load_model(self, model_id, **kwargs):
            pass

    monkeypatch.setattr(lm, "LMStudioClient", FakeClient)
    monkeypatch.setattr(lm.LMStudioPanel, "_resolve_base_url",
                        staticmethod(lambda: "http://127.0.0.1:9/v1"))
    settings = {"gpu_placement": "gpu:1", "gpu_index": 1,
                "context_length": 65536, "flash_attention": True}

    current["kind"] = "confirmed"
    assert app._auto_load_local_model("deepseek", settings, logging.getLogger("t")) == (
        True, "", "deepseek")
    current["kind"] = "estimated"
    ok, note, _loaded = app._auto_load_local_model("deepseek", settings, logging.getLogger("t"))
    assert ok and "nvidia-smi" in note and "GPU 1" in note

    sidebar = _auto_load_sidebar(app, ["deepseek"])
    sidebar._on_auto_load_complete("deepseek", True, note, "deepseek")
    assert sidebar._show_load_status.call_args_list[0].args[0] == \
        "sidebar.model_loaded_gpu_unconfirmed"

    gui = SimpleNamespace(_add_msg=Mock())
    app.HermesGUI._on_auto_load_status(gui, "deepseek", True, note)
    assert [c.args for c in gui._add_msg.call_args_list][1] == (note, "system")


@pytest.mark.needs_core
@pytest.mark.parametrize("outcome", ["cpu_ok", "failed"])
def test_gui_sidebar_auto_load_result_lines(outcome):
    from gui import app

    sidebar = _auto_load_sidebar(app, ["deepseek"])
    sidebar._loading_placement = "cpu"
    if outcome == "cpu_ok":
        sidebar._on_auto_load_complete("deepseek", True, "", "deepseek")
        assert sidebar._show_load_status.call_args_list[0].args[0] == "sidebar.model_loaded_cpu"
    else:
        sidebar._on_auto_load_complete("deepseek", False, "unknown model architecture", None)
    # The load unloads existing instances first: the list is refreshed either way.
    assert (500, sidebar.refresh_models) in [c.args for c in sidebar.after.call_args_list]


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


@pytest.mark.needs_core
def test_gui_new_chat_ends_the_previous_session_in_the_database():
    from gui.agent_bridge import AgentBridge
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        db.create_session(session_id="gui_old", source="gui", model="m")
        bridge = object.__new__(AgentBridge)
        bridge.agent = None
        bridge.conversation_history = [{"role": "user", "content": "hi"}]
        bridge.session_id = "gui_old"
        bridge._session_db = db

        bridge.new_session()

        row = db.get_session("gui_old")
        assert row["end_reason"] == "new_chat"
        assert row["ended_at"]
        assert bridge.session_id is None
    finally:
        db.close()


def _new_chat_bridge(agent, history):
    from gui.agent_bridge import AgentBridge

    import threading

    bridge = object.__new__(AgentBridge)
    bridge.__dict__.update(agent=agent, conversation_history=list(history),
                           session_id="gui_old", _session_db=None, is_running=False,
                           _resume_session_id=None, _shutdown_once=threading.Lock(),
                           _clarify_queue=queue.Queue(), _approval_queue=queue.Queue())
    return bridge


HISTORY = [{"role": "user", "content": "remember: I like tea"},
           {"role": "assistant", "content": "Noted."}]


@pytest.mark.needs_core
def test_gui_new_chat_commits_the_conversation_to_memory():
    """The old _memory_store.flush() call did not exist, so nothing was committed."""
    committed = []
    agent = SimpleNamespace(commit_memory_session=committed.append)
    bridge = _new_chat_bridge(agent, HISTORY)

    bridge.new_session()

    assert committed == [HISTORY]
    assert bridge.agent is None and bridge.conversation_history == []


@pytest.mark.needs_core
def test_gui_new_chat_memory_commit_never_raises_into_the_gui():
    def broken(_messages):
        raise RuntimeError("provider offline")

    for agent in (SimpleNamespace(commit_memory_session=broken),   # failing provider
                  SimpleNamespace(),                               # core without the method
                  None):                                           # no agent yet
        bridge = _new_chat_bridge(agent, HISTORY)
        bridge.new_session()
        assert bridge.agent is None and bridge.conversation_history == []


class _ReleasableAgent:
    """Records what the bridge does with a dropped agent."""

    def __init__(self):
        self.calls = []

    def close(self):
        self.calls.append("close")

    def release_clients(self):
        self.calls.append("release_clients")

    def commit_memory_session(self, messages):
        self.calls.append("commit_memory_session")


@pytest.mark.needs_core
def test_gui_new_chat_closes_the_agent_and_commits_memory_once():
    """close() already commits memory (shutdown_memory_provider): no second commit."""
    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)

    bridge.new_session()

    assert agent.calls == ["close"]
    assert bridge.agent is None


@pytest.mark.needs_core
@pytest.mark.parametrize("action", ["set_cloud_mode", "set_local_mode", "rebuild_agent"])
def test_gui_rebuilding_the_agent_releases_the_old_one_softly(action):
    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)
    args = {"set_cloud_mode": ("cloud/model",),
            "set_local_mode": ("http://127.0.0.1:1234", "local-model"),
            "rebuild_agent": ()}[action]

    getattr(bridge, action)(*args)

    assert agent.calls == ["release_clients"]     # chat goes on: no memory commit
    assert bridge.agent is None and bridge.conversation_history == HISTORY


@pytest.mark.needs_core
def test_gui_resume_and_bridge_close_close_the_previous_agent():
    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)
    bridge.resume_session("gui_other", [])
    assert agent.calls == ["close"]

    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)
    bridge.close()
    assert agent.calls == ["close"] and bridge.agent is None


@pytest.mark.needs_core
@pytest.mark.parametrize("switch", ["set_cloud_mode", "set_local_mode", "set_model"])
def test_gui_bridge_refuses_a_model_switch_during_a_turn(switch):
    from gui.agent_bridge import TurnInProgress

    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)
    bridge.__dict__.update(_active_provider="cloud", _selected_model="old/model",
                           _lm_studio_base_url=None, is_running=True)
    args = ("http://127.0.0.1:1234", "local") if switch == "set_local_mode" else ("new/m",)

    with pytest.raises(TurnInProgress):
        getattr(bridge, switch)(*args)

    assert (bridge._active_provider, bridge._selected_model, bridge._lm_studio_base_url) == (
        "cloud", "old/model", None)
    assert bridge.agent is agent and agent.calls == []


@pytest.mark.needs_core
def test_gui_rebuild_agent_discards_directly_when_idle_and_refuses_mid_turn():
    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)
    bridge.is_running = True

    assert bridge.rebuild_agent() is False                 # refused (logged)
    assert bridge.agent is agent and agent.calls == []     # nothing under the turn

    bridge.is_running = False
    bridge.rebuild_agent()                                 # idle: discarded at once
    assert agent.calls == ["release_clients"] and bridge.agent is None


@pytest.mark.needs_core
def test_gui_failing_release_never_raises_into_the_gui():
    class Broken(_ReleasableAgent):
        def close(self):
            raise RuntimeError("close failed")

        def release_clients(self):
            raise RuntimeError("release failed")

    for action in ("new_session", "rebuild_agent", "close"):
        bridge = _new_chat_bridge(Broken(), HISTORY)
        getattr(bridge, action)()
        assert bridge.agent is None


@pytest.mark.needs_core
def test_gui_permissions_and_api_keys_rebuild_through_the_bridge():
    from unittest.mock import Mock

    gui = _gui_with_bridge(Mock(is_running=False))
    gui._on_permissions_saved({})
    gui.bridge.rebuild_agent.assert_called_once_with()


@pytest.mark.needs_core
def test_gui_bridge_release_methods_exist_in_the_core():
    from run_agent import AIAgent

    assert callable(AIAgent.close) and callable(AIAgent.release_clients)


@pytest.mark.needs_core
def test_gui_new_chat_commit_matches_the_core_signature():
    import inspect
    from run_agent import AIAgent

    params = inspect.signature(AIAgent.commit_memory_session).parameters
    assert list(params)[:2] == ["self", "messages"]


@pytest.mark.needs_core
def test_gui_bridge_leaves_session_row_creation_to_the_core(monkeypatch, tmp_path):
    """No row before the first turn: a failing agent build must not leave an empty session."""
    from gui import agent_bridge
    import run_agent
    from hermes_cli import runtime_provider
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        bridge = _bridge_shell(agent_bridge, tmp_path)
        bridge._session_db = db
        captured = {}

        class FailingAgent:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                raise RuntimeError("agent build failed")

        monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", lambda **kw: {
            "provider": "custom", "api_mode": "chat_completions",
            "base_url": "http://127.0.0.1:9/v1", "api_key": "k"})
        monkeypatch.setattr(run_agent, "AIAgent", FailingAgent)
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, "", ""))

        with pytest.raises(RuntimeError):
            bridge._create_agent()

        # The agent gets the id and the database, and creates the row on its first turn.
        assert captured["session_id"] == bridge.session_id
        assert captured["session_db"] is db
        assert captured["platform"] == "gui"
        assert db.get_session(bridge.session_id) is None
    finally:
        db.close()


@pytest.mark.needs_core
def test_gui_resumed_session_continues_under_its_own_id(monkeypatch, tmp_path):
    from gui import agent_bridge
    import run_agent
    from hermes_cli import runtime_provider
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        db.create_session(session_id="stored", source="gui", model="m")
        db.append_message("stored", "user", "hello")
        db.end_session("stored", "new_chat")
        bridge = _bridge_shell(agent_bridge, tmp_path)
        bridge._session_db = db
        bridge.agent = object()
        built = []

        class FakeAgent:
            def __init__(self, **kwargs):
                built.append(kwargs["session_id"])

        monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", lambda **kw: {
            "provider": "custom", "api_mode": "chat_completions",
            "base_url": "http://127.0.0.1:9/v1", "api_key": "k"})
        monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, "", ""))

        history = db.get_messages_as_conversation("stored")
        bridge.resume_session("stored", history)

        assert bridge.agent is None
        assert bridge.conversation_history == history
        assert db.get_session("stored")["ended_at"] is None  # reopened, like the CLI
        bridge._create_agent()
        assert built == ["stored"]

        # Only the resume keeps the id; a later rebuild or New Chat starts fresh.
        bridge._create_agent()
        bridge.new_session()
        bridge._create_agent()
        assert built[1] != "stored" and built[2] not in ("stored", built[1])
    finally:
        db.close()


# --- session changes vs a running turn, pending resumes (item 11) -----------

def _fake_agent_build(monkeypatch, agent_class):
    import run_agent
    from hermes_cli import runtime_provider

    monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", lambda **kw: {
        "provider": "custom", "api_mode": "chat_completions",
        "base_url": "http://127.0.0.1:9/v1", "api_key": "k"})
    monkeypatch.setattr(run_agent, "AIAgent", agent_class)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, "", ""))


@pytest.mark.needs_core
def test_gui_bridge_refuses_session_changes_during_a_turn():
    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)
    bridge.is_running = True

    assert bridge.new_session() is False
    assert bridge.resume_session("gui_other", []) is False
    assert bridge.agent is agent and bridge.conversation_history == HISTORY
    assert bridge.session_id == "gui_old" and agent.calls == []


def _gui_with_bridge(bridge):
    from unittest.mock import Mock
    from gui import app

    gui = object.__new__(app.HermesGUI)
    gui.__dict__.update(bridge=bridge, _add_msg=Mock(), msg_frame=Mock(),
                        sidebar=Mock(), status_bar=Mock(), chat_title=Mock(),
                        input_text=Mock())
    gui.msg_frame.winfo_children.return_value = []
    return gui


@pytest.mark.needs_core
def test_gui_new_chat_select_and_delete_ask_to_stop_first(monkeypatch):
    from unittest.mock import Mock
    from gui import app
    from gui.i18n import t

    bridge = _new_chat_bridge(_ReleasableAgent(), HISTORY)
    bridge.is_running = True
    bridge.new_session = Mock()
    bridge.resume_session = Mock()
    gui = _gui_with_bridge(bridge)
    busy = t("chat.busy_stop_first", stop=t("chat.stop"))

    gui._new_chat()
    gui._on_session_select("gui_other")
    assert gui._can_delete_session("gui_old") is False       # the active session
    assert gui._can_delete_session("gui_other") is True      # any other session

    bridge.new_session.assert_not_called()
    bridge.resume_session.assert_not_called()
    assert [c.args for c in gui._add_msg.call_args_list] == [(busy, "system")] * 3

    sidebar = object.__new__(app.Sidebar)
    sidebar.__dict__.update(can_delete_session=lambda sid: False, _confirm_delete=False,
                            _perform_delete=Mock())
    sidebar._delete_session("gui_old")
    sidebar._perform_delete.assert_not_called()


@pytest.mark.needs_core
def test_gui_turn_survives_an_agent_build_that_yields_nothing(monkeypatch):
    from gui import agent_bridge
    import tools.terminal_tool as terminal_tool

    errors = []
    bridge = _new_chat_bridge(None, HISTORY)
    bridge.__dict__.update(root=SimpleNamespace(after=lambda _ms, fn: fn()),
                           on_error=errors.append, _interrupted=False,
                           _is_model_configured=lambda: True,
                           _create_agent=lambda: None,        # agent gone again
                           get_model=lambda: "m", _active_provider="cloud")
    monkeypatch.setattr(terminal_tool, "set_approval_callback", lambda cb: None)
    bridge.is_running = True

    agent_bridge.AgentBridge._run_agent(bridge, "hi")

    assert errors and "no agent could be prepared" in errors[0]
    assert "NoneType" not in errors[0]
    assert bridge.is_running is False and bridge.conversation_history == HISTORY


def _core_context_refusal():
    """The core's own error for a 32K LM Studio window (agent construction)."""
    from agent import agent_init
    agent = SimpleNamespace(
        model="gemma-4-e4b-it", provider="custom", base_url="http://127.0.0.1:1234/v1",
        context_compressor=SimpleNamespace(context_length=32768),
        _ollama_num_ctx=None, _config_context_length=None)
    try:
        agent_init._enforce_minimum_context(agent)
    except ValueError as e:
        return e
    raise AssertionError("the core accepted a 32K window")


@pytest.mark.needs_core
@pytest.mark.parametrize("provider, hint", [("local", True), ("cloud", False)])
def test_gui_error_bubble_shows_the_message_and_logs_the_traceback(monkeypatch, provider, hint):
    import logging
    from gui import agent_bridge
    from gui.i18n import t
    from gui.lm_studio import MINIMUM_CONTEXT_LENGTH
    import tools.terminal_tool as terminal_tool

    refusal = _core_context_refusal()

    def build():
        raise refusal

    errors, records = [], []
    bridge = _new_chat_bridge(None, HISTORY)
    bridge.__dict__.update(root=SimpleNamespace(after=lambda _ms, fn: fn()),
                           on_error=errors.append, _interrupted=False,
                           _is_model_configured=lambda: True, _create_agent=build,
                           get_model=lambda: "gemma-4-e4b-it", _active_provider=provider)
    monkeypatch.setattr(terminal_tool, "set_approval_callback", lambda cb: None)
    capture = logging.Handler()
    capture.emit = records.append
    logging.getLogger("hermes.bridge").addHandler(capture)
    try:
        bridge.is_running = True
        agent_bridge.AgentBridge._run_agent(bridge, "hi")
    finally:
        logging.getLogger("hermes.bridge").removeHandler(capture)

    bubble = errors[0]
    assert bubble.startswith(f"Error: {refusal}")
    assert "Traceback" not in bubble and "File \"" not in bubble
    log_path = str(agent_bridge.get_hermes_home() / "logs" / "bridge.log")
    assert bubble.endswith(t("chat.error_details_in_log", path=log_path))
    reload_hint = t("chat.error_reload_with_context", tokens=f"{MINIMUM_CONTEXT_LENGTH:,}")
    assert (reload_hint in bubble) is hint
    logged = [r for r in records if r.exc_info]
    assert logged and logged[0].exc_info[1] is refusal       # the traceback is in bridge.log
    assert bridge.is_running is False


@pytest.mark.needs_core
def test_gui_error_bubble_keeps_the_traceback_when_it_cannot_be_logged():
    from gui import agent_bridge
    from gui.i18n import t

    def broken_log():
        raise OSError("logs folder is read-only")

    try:
        raise RuntimeError("model server went away")
    except RuntimeError as e:
        failure = e
    bridge = _new_chat_bridge(None, HISTORY)
    bridge.__dict__.update(_bridge_log=broken_log, _active_provider="cloud")

    bubble = agent_bridge.AgentBridge._error_text(bridge, failure)

    assert bubble.startswith("Error: model server went away")
    assert "Traceback (most recent call last)" in bubble
    assert "test_gui_error_bubble_keeps_the_traceback" in bubble   # the frame is there
    assert t("chat.error_details_in_log", path="X").split("X")[0] not in bubble


@pytest.mark.needs_core
def test_gui_reload_hint_needs_the_core_minimum_not_just_any_value_error():
    from gui import agent_bridge
    bridge = _new_chat_bridge(None, HISTORY)
    bridge._active_provider = "local"
    assert agent_bridge.AgentBridge._context_too_small(bridge, _core_context_refusal())
    assert not agent_bridge.AgentBridge._context_too_small(bridge, ValueError("bad model name"))
    assert not agent_bridge.AgentBridge._context_too_small(
        bridge, RuntimeError(str(_core_context_refusal())))


@pytest.mark.needs_core
@pytest.mark.parametrize("switch", ["set_cloud_mode", "set_local_mode"])
def test_gui_model_switch_drops_a_pending_resume(switch):
    bridge = _new_chat_bridge(None, HISTORY)
    bridge.resume_session("stored", HISTORY)
    assert bridge._resume_session_id == "stored"

    args = ("cloud/m",) if switch == "set_cloud_mode" else ("http://127.0.0.1:1234", "local")
    assert getattr(bridge, switch)(*args) is True            # it was dropped
    assert bridge._resume_session_id is None
    assert bridge.conversation_history == HISTORY            # history kept as context
    assert getattr(bridge, switch)(*args) is False           # nothing pending now


@pytest.mark.needs_core
def test_gui_model_switch_says_the_resumed_session_is_not_continued():
    from unittest.mock import Mock
    from gui.i18n import t

    bridge = Mock(_known_local_models=set(), _active_provider="cloud", is_running=False)
    bridge.set_model.return_value = True
    gui = _gui_with_bridge(bridge)
    gui.sidebar._all_models = []

    gui._on_model_change("cloud/m")

    assert gui._add_msg.call_args_list[-1].args == (t("chat.resume_not_continued"), "system")


@pytest.mark.needs_core
def test_gui_failed_agent_build_keeps_the_pending_resume(monkeypatch, tmp_path):
    from gui import agent_bridge

    built = []

    class FlakyAgent:
        def __init__(self, **kwargs):
            built.append(kwargs["session_id"])
            if len(built) == 1:
                raise RuntimeError("agent build failed")

    _fake_agent_build(monkeypatch, FlakyAgent)
    bridge = _bridge_shell(agent_bridge, tmp_path)
    bridge.__dict__.update(agent=None, conversation_history=[], session_id=None, is_running=False)
    bridge.resume_session("stored", HISTORY)

    with pytest.raises(RuntimeError):
        bridge._create_agent()
    assert bridge._resume_session_id == "stored"             # still pending

    bridge._create_agent()                                   # retry
    assert built == ["stored", "stored"]
    assert bridge._resume_session_id is None


@pytest.mark.needs_core
def test_gui_resume_fails_when_the_core_cannot_reopen_the_session(monkeypatch):
    import hermes_state
    from gui.i18n import t

    class RefusingDB:
        def reopen_session(self, session_id):
            raise RuntimeError("database is locked")

    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)
    bridge._session_db = RefusingDB()

    assert bridge.resume_session("stored", [{"role": "user", "content": "old"}]) is False
    assert bridge.agent is agent and agent.calls == []        # current chat untouched
    assert bridge.session_id == "gui_old" and bridge._resume_session_id is None
    assert bridge.conversation_history == HISTORY

    class StoredDB:  # the GUI's own read of the stored messages works
        def __enter__(self):
            return SimpleNamespace(
                get_messages_as_conversation=lambda sid: [{"role": "user", "content": "old"}])

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(hermes_state, "SessionDB", StoredDB)
    gui = _gui_with_bridge(bridge)
    gui._on_session_select("stored")

    gui._add_msg.assert_called_once_with(t("chat.session_load_failed"), "error")
    gui.msg_frame.winfo_children.assert_not_called()          # chat view not cleared


class _TurnAgent(_ReleasableAgent):
    """An agent whose turn can be held open and interrupted."""

    def __init__(self, model, hold=None):
        super().__init__()
        self.model, self.hold, self.interrupted = model, hold, []
        self.base_url = "http://127.0.0.1:9/v1"

    def run_conversation(self, user_message, conversation_history):
        self.calls.append("run_conversation")
        if self.hold is not None:
            self.hold.wait(10)
        return {"final_response": f"answer from {self.model}",
                "messages": list(conversation_history) + [{"role": "user", "content": user_message}]}

    def interrupt(self, message=""):
        self.interrupted.append(message)
        if self.hold is not None:
            self.hold.set()


def _worker_bridge(monkeypatch, create_agent):
    import tools.terminal_tool as terminal_tool

    events = {"error": [], "response": []}
    bridge = _new_chat_bridge(None, [])
    bridge.__dict__.update(
        root=SimpleNamespace(after=lambda _ms, fn: fn()),
        on_error=events["error"].append, on_response=events["response"].append,
        on_complete=None, _interrupted=False, _is_model_configured=lambda: True,
        get_model=lambda: bridge.__dict__.get("model", "old-model"),
        _active_provider="cloud")
    bridge._create_agent = lambda: create_agent(bridge)
    monkeypatch.setattr(terminal_tool, "set_approval_callback", lambda cb: None)
    return bridge, events


def _wait_for(condition):
    import threading
    for _ in range(250):
        if condition():
            return
        threading.Event().wait(0.02)
    raise AssertionError("condition not reached")


@pytest.mark.needs_core
def test_gui_stop_reaches_the_running_agent_and_nothing_changes_it_mid_turn(monkeypatch):
    import threading
    from gui.agent_bridge import TurnInProgress

    hold = threading.Event()
    running = _TurnAgent("old-model", hold=hold)

    def create(bridge):
        bridge.agent = running

    bridge, events = _worker_bridge(monkeypatch, create)
    bridge.send_message("long task")
    _wait_for(lambda: running.calls)

    with pytest.raises(TurnInProgress):           # model switch refused mid-turn
        bridge.set_cloud_mode("other/model")
    assert bridge.rebuild_agent() is False        # refused too
    assert bridge.agent is running and running.calls == ["run_conversation"]

    bridge.interrupt()                            # Stop
    bridge._agent_thread.join(10)

    assert running.interrupted == [""]
    assert running.calls == ["run_conversation"]  # kept for the next turn
    assert bridge.agent is running and bridge.is_running is False
    assert events["error"] == []


@pytest.mark.needs_core
def test_gui_close_during_the_agent_build_releases_it_and_publishes_nothing(monkeypatch):
    built = []

    class FakeDB:
        closed = False

        def close(self):
            self.closed = True

    def create(bridge):
        agent = _TurnAgent("old-model")
        built.append(agent)
        bridge.close()                    # the app exits while the agent is built
        bridge.agent = agent

    bridge, events = _worker_bridge(monkeypatch, create)
    db = bridge._session_db = FakeDB()
    posted = []
    bridge.root = SimpleNamespace(after=lambda _ms, fn: posted.append(fn))
    bridge.send_message("hi")
    bridge._agent_thread.join(10)

    assert len(built) == 1                            # no retry
    assert built[0].calls == ["close"]                # closed, never run
    assert bridge.agent is None and bridge._session_db is None and db.closed
    assert posted == [] and events == {"error": [], "response": []}
    assert bridge.is_running is False


@pytest.mark.needs_core
def test_gui_close_during_a_turn_closes_the_agent_once_after_it():
    import threading

    hold = threading.Event()
    running = _TurnAgent("m", hold=hold)
    bridge = _new_chat_bridge(running, HISTORY)
    bridge.__dict__.update(is_running=True, _running_agent=running)

    bridge.close()                                    # Stop + leave it to the worker
    assert running.interrupted == [""] and running.calls == []
    # A worker waiting for an answer is not left waiting for a closed window.
    assert bridge._clarify_queue.get_nowait() == "" and bridge._approval_queue.get_nowait() is False
    bridge._end_turn()                                # the worker's last step
    bridge.close()                                    # and again: still once
    assert running.calls == ["close"] and bridge.agent is None


@pytest.mark.needs_core
def test_gui_interrupt_while_the_turn_finishes_is_harmless():
    class Finished(_ReleasableAgent):
        def interrupt(self, message=""):
            raise RuntimeError("client already closed")

    agent = Finished()
    bridge = _new_chat_bridge(agent, HISTORY)
    bridge.__dict__.update(is_running=True, _running_agent=agent)
    bridge.interrupt()                                # raises inside: swallowed
    bridge._running_agent = None                      # the worker just let go
    bridge.interrupt()
    bridge.is_running = False                         # turn over
    bridge.interrupt()
    assert agent.calls == []                          # interrupt never releases


@pytest.mark.needs_core
@pytest.mark.parametrize("lang", ["en", "zh-hant", "zh", "es"])
def test_gui_use_for_chat_says_the_next_message_uses_the_model(lang):
    """The agent is dropped, so the next message already uses the model: no New Chat."""
    from unittest.mock import Mock
    from gui import i18n

    bridge = Mock(is_running=False)
    bridge.set_local_mode.return_value = False
    gui = _gui_with_bridge(bridge)
    previous = i18n.get_language()
    i18n.set_language(lang, persist=False)
    try:
        gui._on_lm_studio_ready("http://127.0.0.1:1234", "gemma-4-e4b-it")
        new_chat = i18n.t("sidebar.new_chat")
    finally:
        i18n.set_language(previous, persist=False)

    bridge.set_local_mode.assert_called_once_with("http://127.0.0.1:1234", "gemma-4-e4b-it")
    text, kind = gui._add_msg.call_args.args
    assert kind == "system" and "gemma-4-e4b-it" in text
    assert new_chat not in text


@pytest.mark.needs_core
def test_gui_seeds_the_bundled_skills_into_a_home_that_has_none(monkeypatch, tmp_path):
    """A home not made by install.bat: the core's own sync runs, once."""
    import tools.skills_sync as skills_sync
    from gui import agent_bridge, app

    skill = tmp_path / "bundled" / "demo" / "hello-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: hello-skill\ndescription: Says hello.\n---\nSay hello.\n", encoding="utf-8")
    home = tmp_path / "fresh-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_SKILLS", str(tmp_path / "bundled"))

    assert agent_bridge.ensure_bundled_skills() is True
    assert [p.parent.name for p in (home / "skills").rglob("SKILL.md")] == ["hello-skill"]
    names = [n for skills in app._discover_installed_skills(home / "skills").values()
             for n, _d in skills]
    assert "hello-skill" in names                       # the Skills browser lists it

    def must_not_run(**_kw):
        raise AssertionError("synced a home that already has skills")
    monkeypatch.setattr(skills_sync, "sync_skills", must_not_run)
    assert agent_bridge.ensure_bundled_skills() is False


@pytest.mark.needs_core
def test_gui_skills_seeding_never_raises(monkeypatch, tmp_path):
    import tools.skills_sync as skills_sync
    from gui import agent_bridge

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "fresh-home"))

    def broken(**_kw):
        raise OSError("disk full")
    monkeypatch.setattr(skills_sync, "sync_skills", broken)
    assert agent_bridge.ensure_bundled_skills() is False


@pytest.mark.needs_core
def test_gui_header_shows_the_session_title_once_it_has_one():
    from unittest.mock import Mock
    from gui.i18n import t

    bridge = Mock(is_running=False, session_id="s1")
    bridge.get_token_usage.return_value = {}
    bridge.new_session.return_value = True
    gui = _gui_with_bridge(bridge)
    gui._cleanup_stream_bubble = Mock()
    sessions = [{"id": "s0", "title": "Other chat"}, {"id": "s1", "title": None, "preview": "hi"}]
    gui.sidebar._sessions_data = sessions

    gui._on_complete({})                                   # no title yet: header unchanged
    gui.chat_title.configure.assert_not_called()

    sessions[1]["title"] = "General assistance capabilities"
    gui._on_complete({})
    gui.chat_title.configure.assert_called_with(text="General assistance capabilities")

    gui._new_chat()
    gui.chat_title.configure.assert_called_with(text=t("chat.new_chat_title"))
    assert gui._chat_title_text is None

    gui._set_chat_title("resumed")                         # resuming a stored session
    gui._show_session_title("s0")
    gui.chat_title.configure.assert_called_with(text="Other chat")
    gui._set_chat_title("resumed", "x" * 80)               # long titles are shortened
    assert gui.chat_title.configure.call_args.kwargs["text"] == "x" * 57 + "..."


@pytest.mark.needs_core
def test_gui_model_switch_is_refused_while_a_reply_runs():
    from unittest.mock import Mock
    from gui import app
    from gui.i18n import t

    bridge = Mock(is_running=True, _known_local_models=set())
    bridge.get_model.return_value = "old/model"
    gui = _gui_with_bridge(bridge)
    busy = (t("chat.busy_stop_first", stop=t("chat.stop")), "system")

    gui._on_model_change("new/model")                 # dropdown or auto-load done
    gui._on_lm_studio_ready("http://127.0.0.1:1234", "local")   # "Use for Chat"

    bridge.set_model.assert_not_called()
    bridge.set_local_mode.assert_not_called()
    gui.sidebar.set_model.assert_called_once_with("old/model")  # dropdown reverts
    assert [c.args for c in gui._add_msg.call_args_list] == [busy, busy]

    sidebar = object.__new__(app.Sidebar)              # refused before any auto-load
    sidebar.__dict__.update(can_change_model=lambda: False, model_combo=Mock(),
                            model_var=Mock(get=lambda: "old/model"),
                            _select_model_in_combo=Mock(), _auto_load_model=Mock(),
                            on_model_change=Mock())
    sidebar._on_model_selected(None)
    sidebar._select_model_in_combo.assert_called_once_with("old/model")
    sidebar._auto_load_model.assert_not_called()
    sidebar.on_model_change.assert_not_called()


@pytest.mark.needs_core
@pytest.mark.parametrize("opener, dialog", [("_open_settings", "SettingsDialog"),
                                            ("_open_permissions", "PermissionsPanel"),
                                            ("_show_api_setup", "APISetupWizard")])
def test_gui_settings_dialogs_are_not_opened_during_a_reply(monkeypatch, opener, dialog):
    from unittest.mock import Mock
    from gui import app
    from gui.i18n import t

    built = Mock()
    monkeypatch.setattr(app, dialog, built)
    bridge = Mock(is_running=True)
    gui = _gui_with_bridge(bridge)
    gui.root = Mock()

    getattr(gui, opener)()                            # menu, Ctrl+comma, first-run timer

    built.assert_not_called()
    bridge.rebuild_agent.assert_not_called()
    assert gui._add_msg.call_args_list == [((t("chat.busy_stop_first", stop=t("chat.stop")),
                                             "system"),)]

    bridge.is_running = False                         # idle: opens as before
    getattr(gui, opener)()
    built.assert_called_once()


@pytest.mark.needs_core
def test_gui_saved_settings_rebuild_the_agent_directly():
    from unittest.mock import Mock

    bridge = Mock(is_running=False)
    bridge.rebuild_agent.return_value = False
    gui = _gui_with_bridge(bridge)
    gui._on_permissions_saved({})
    bridge.rebuild_agent.assert_called_once_with()


@pytest.mark.needs_core
def test_gui_send_is_refused_while_a_model_loads():
    import threading
    from unittest.mock import Mock
    from gui.i18n import t

    gui = _gui_with_bridge(Mock(is_running=False))
    gui.input_text.get.return_value = "hello"
    release = threading.Event()
    loader = threading.Thread(target=release.wait, args=(10,), daemon=True)
    loader.start()
    gui._track_model_work(loader)                     # e.g. the sidebar auto-load

    gui._send()

    gui._add_msg.assert_called_once_with(t("chat.model_loading_wait"), "system")
    gui.input_text.delete.assert_not_called()         # the message stays in the box
    gui.bridge.send_message.assert_not_called()

    release.set()
    loader.join(10)
    assert gui._model_work_running() is False         # busy ends with the thread


@pytest.mark.needs_core
def test_gui_busy_lasts_until_the_tk_side_completion_ran():
    from unittest.mock import Mock

    gui = _gui_with_bridge(Mock(is_running=False))
    gui.sidebar = SimpleNamespace(_loading_model=True)    # thread done, completion queued
    assert gui._model_work_running() is True
    gui.sidebar._loading_model = False                    # _on_auto_load_complete ran
    assert gui._model_work_running() is False

    panel = SimpleNamespace(_closed=False, model_work_pending=lambda: True)
    gui._lm_panels = [panel]                              # Cancel button still shown
    assert gui._model_work_running() is True
    panel._closed = True                                  # closed: completion never runs
    assert gui._model_work_running() is False and gui._lm_panels == []


@pytest.mark.needs_core
def test_gui_first_run_wizard_is_skipped_over_another_modal_dialog():
    from unittest.mock import Mock

    gui = _gui_with_bridge(Mock(is_running=False))
    gui._show_api_setup = Mock()
    gui.root = Mock()
    gui.root.grab_current.return_value = object()         # Settings/Permissions open
    gui._first_run_api_setup()
    gui._show_api_setup.assert_not_called()

    gui.root.grab_current.return_value = None
    gui._first_run_api_setup()
    gui._show_api_setup.assert_called_once_with()


@pytest.mark.needs_core
@pytest.mark.parametrize("dialog", ["settings", "permissions", "wizard_save", "wizard_finish"])
def test_gui_dialog_saves_are_refused_during_a_reply(monkeypatch, tmp_path, dialog):
    """Defensive: even if a dialog is open under a reply, nothing is written."""
    from unittest.mock import Mock
    from gui import app, api_setup_wizard, permissions_panel
    from gui.i18n import t

    busy = t("chat.busy_stop_first", stop=t("chat.stop"))
    info = Mock()
    for module in (app, api_setup_wizard, permissions_panel):
        monkeypatch.setattr(module.messagebox, "showinfo", info)
    written = Mock()

    if dialog == "settings":
        monkeypatch.setattr(app, "get_hermes_home", lambda: tmp_path)
        dlg = object.__new__(app.SettingsDialog)
        dlg.__dict__.update(bridge=Mock(is_running=True), destroy=written)
        dlg._save()
        assert not (tmp_path / ".env").exists()
        dlg.bridge.set_model.assert_not_called()
    elif dialog == "permissions":
        monkeypatch.setattr(permissions_panel, "save_permissions", written)
        dlg = object.__new__(permissions_panel.PermissionsPanel)
        dlg.__dict__.update(can_save=lambda: False, on_save=written, destroy=written,
                            sliders={}, perms={})
        dlg._save()
    else:
        monkeypatch.setattr(api_setup_wizard, "_save_key_to_env", written)
        dlg = object.__new__(api_setup_wizard.APISetupWizard)
        dlg.__dict__.update(can_save=lambda: False, on_complete=written, destroy=written,
                            key_entries={"K": Mock(get=lambda: "sk-key")}, saved_keys={})
        if dialog == "wizard_save":
            dlg._save_current({"key": "K"})
        else:
            dlg._finish()

    written.assert_not_called()                           # nothing saved, dialog stays open
    assert info.call_args.args[1] == busy


@pytest.mark.needs_core
@pytest.mark.parametrize("outcome", ["ok", "error", "crash"])
def test_gui_sidebar_auto_load_is_tracked_and_always_reports(monkeypatch, outcome):
    from unittest.mock import Mock
    from gui import app

    def fake_load(model_id, settings, log):
        if outcome == "crash":
            raise RuntimeError("log dir unwritable")
        return (outcome == "ok", "" if outcome == "ok" else "boom", None)

    monkeypatch.setattr(app, "_auto_load_local_model", fake_load)
    tracked, done = [], []
    sidebar = object.__new__(app.Sidebar)
    sidebar.__dict__.update(
        _loading_model=False, _show_load_status=Mock(), model_combo=Mock(),
        get_local_settings=lambda: {"gpu_placement": "auto", "context_length": 4096},
        track_model_work=tracked.append, after=lambda _ms, fn: fn(),
        _on_auto_load_complete=lambda *a: done.append(a))

    sidebar._auto_load_model("m")
    tracked[0].join(10)

    assert len(tracked) == 1 and not tracked[0].is_alive()
    assert done and done[0][1] is (outcome == "ok")


@pytest.mark.needs_core
@pytest.mark.parametrize("broken", ["log_setup", "model_config", "terminal_tool"])
def test_gui_worker_setup_failure_finishes_the_turn(monkeypatch, broken):
    import sys

    bridge, events = _worker_bridge(monkeypatch, lambda b: None)

    def boom(*a, **k):
        raise OSError(f"{broken} failed")

    if broken == "log_setup":
        bridge._bridge_log = boom
    elif broken == "model_config":
        bridge._is_model_configured = boom
    else:
        monkeypatch.setitem(sys.modules, "tools.terminal_tool", None)   # import fails

    bridge.send_message("hi")
    bridge._agent_thread.join(10)

    assert bridge.is_running is False                 # the session guard is not stuck
    assert len(events["error"]) == 1
    if broken != "terminal_tool":
        assert f"{broken} failed" in events["error"][0]


@pytest.mark.needs_core
def test_gui_reselecting_the_active_session_does_not_end_it():
    agent = _ReleasableAgent()
    bridge = _new_chat_bridge(agent, HISTORY)

    assert bridge.resume_session("gui_old", HISTORY) is True
    assert agent.calls == ["release_clients"]                 # not close(): row stays open


class _InlineThread:
    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        self._target()


def _delete_sidebar(app, monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(app.threading, "Thread", _InlineThread)
    sidebar = object.__new__(app.Sidebar)
    sidebar.__dict__.update(_session_widgets={}, after=Mock())
    return sidebar


@pytest.mark.needs_core
def test_gui_sidebar_delete_removes_the_session_through_the_core(monkeypatch):
    from gui import app
    from hermes_state import SessionDB

    with SessionDB() as db:
        for sid in ("del_me", "keep"):
            db.create_session(session_id=sid, source="gui", model="m")
            db.append_message(sid, "user", "hello")
    sidebar = _delete_sidebar(app, monkeypatch)

    sidebar._perform_delete("del_me")

    with SessionDB() as db:
        assert db.get_session("del_me") is None
        assert db.get_messages_as_conversation("del_me") == []
        assert db.get_session("keep") is not None
    sidebar.after.assert_not_called()


@pytest.mark.needs_core
def test_gui_sidebar_failed_delete_reloads_the_list_without_raw_sql(monkeypatch):
    import sqlite3
    import sys
    from gui import app

    class RefusingSessionDB:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def delete_session(self, session_id):
            raise RuntimeError("session is being written")

    def no_raw_sql(*args, **kwargs):
        raise AssertionError("the GUI must not edit state.db directly")

    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=RefusingSessionDB))
    monkeypatch.setattr(sqlite3, "connect", no_raw_sql)
    sidebar = _delete_sidebar(app, monkeypatch)

    sidebar._perform_delete("busy")

    sidebar.after.assert_called_once_with(0, sidebar._load_sessions)
