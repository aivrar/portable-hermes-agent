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


def _store():
    """The session store of the test's Hermes home, the way the GUI opens it."""
    from portable_hermes.session_store import open_store
    return open_store()


def _row(store, session_id):
    """A session's row as a dict, or None (test-side read, both core shapes)."""
    if store.legacy:
        return store.handle.get_session(session_id)
    record = store.handle.sessions.get(session_id)
    return None if record is None else record.as_session_row()


@pytest.mark.needs_core
def test_gui_sidebar_hides_sessions_without_messages():
    """Empty sessions (failed first turn, gateway resets) cannot be resumed."""
    from gui import app

    with _store() as store:
        store.create("empty_session", "gui", model="m")
        store.create("chat_session", "gui", model="m")
        store.append("chat_session", "user", "hello")

    sidebar = _sidebar_shell(app)
    sidebar._load_sessions()

    assert [s["id"] for s in sidebar._sessions_data] == ["chat_session"]


def _installed_core_is_legacy():
    """True on cores without persistence_assembly (the last-known-good core
    the required CI runs against); False on current cores."""
    import importlib.util
    return importlib.util.find_spec("persistence_assembly") is None


@pytest.mark.needs_core
def test_gui_opens_the_installed_core_store_the_way_its_agent_takes_it():
    import inspect
    from run_agent import AIAgent

    legacy = _installed_core_is_legacy()
    print("installed core shape:", "SessionDB" if legacy else "storage interface")
    with _store() as store:
        assert store.legacy is legacy
        keyword, = store.agent_kwargs()
        assert keyword == ("session_db" if legacy else "persistence")
        assert keyword in inspect.signature(AIAgent.__init__).parameters


def _legacy_core(monkeypatch, session_db_class):
    """Make the core look like one without persistence_assembly whose
    hermes_state.SessionDB is *session_db_class*."""
    import sys
    monkeypatch.setitem(sys.modules, "persistence_assembly", None)   # import fails
    monkeypatch.setitem(sys.modules, "hermes_state", SimpleNamespace(SessionDB=session_db_class))


def _fake_session_db(rows, calls, supports_filter):
    """A SessionDB stand-in whose rows are newest first, honouring ``limit``."""

    class FakeSessionDB:
        def close(self):
            pass

        if supports_filter:
            def list_sessions_rich(self, source=None, limit=20, min_message_count=0):
                calls.append({"limit": limit, "min_message_count": min_message_count})
                raise TypeError("bug inside a core that supports the filter")
        else:
            def list_sessions_rich(self, source=None, limit=20):
                calls.append({"limit": limit})
                return rows[:limit]

    return FakeSessionDB


@pytest.mark.needs_core
def test_gui_sidebar_old_core_fallback_survives_20_newer_empty_sessions(monkeypatch):
    from gui import app

    rows = ([{"id": f"empty{i}", "message_count": 0} for i in range(20)]
            + [{"id": f"chat{i}", "message_count": 2} for i in range(25)])
    calls = []
    _legacy_core(monkeypatch, _fake_session_db(rows, calls, supports_filter=False))

    sidebar = _sidebar_shell(app)
    sidebar._load_sessions()

    assert [s["id"] for s in sidebar._sessions_data] == [f"chat{i}" for i in range(20)]
    assert calls == [{"limit": 200}]


@pytest.mark.needs_core
def test_gui_sidebar_does_not_retry_when_supporting_core_raises_type_error(monkeypatch):
    from gui import app

    calls = []
    _legacy_core(monkeypatch, _fake_session_db([], calls, supports_filter=True))

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


def _tagged(body, tag):
    ranges = body.tag_ranges(tag)
    return [body.get(ranges[i], ranges[i + 1]) for i in range(0, len(ranges), 2)]


# Replies whose markers stream in awkward places (25a/25b review corpus).
MARKDOWN_CORPUS = [
    "Search **/*.py and **/*.txt", "2*3*4", "2**10 = 1024 and 3**2 = 9",
    "C:\\Users\\*\\*.txt", "a ** b ** c", "**", "****", "***x***", "**bold**",
    "**bold** and **more**", "`code with ** inside`", "an unmatched ` backtick",
    "`a` and `b`", "**RTX 3060** (GPU 0)", "Run:\n```python\nx = 2**3  # **no**\n```\nDone **ok**.",
    "***\n*x**", "Your **RTX 3060** has `12288` MiB and **bold",
    "line one **a\nb** two `c\nd` three",
]


def _styled_chars(body):
    """[(char, tags)] the bubble shows."""
    from gui.inline_markdown import BOLD, CODE
    text = body.get("1.0", "end-1c")
    return [(ch, tuple(t for t in (BOLD, CODE) if t in body.tag_names(f"1.0+{i}c")))
            for i, ch in enumerate(text)]


def _expected_chars(text):
    from gui.inline_markdown import spans
    return [(ch, tags) for piece, tags in spans(text) for ch in piece]


@pytest.mark.needs_core
def test_gui_streamed_reply_shows_exactly_the_whole_reply_styling_for_any_split():
    import random
    import tkinter as tk
    from gui import app

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    rng = random.Random(25)
    try:
        for text in MARKDOWN_CORPUS:
            splits = [[text], list(text)]
            splits += [[text[:c], text[c:]] for c in range(len(text) + 1)]
            for _ in range(20):
                cuts = sorted(rng.sample(range(len(text) + 1), min(len(text) + 1, rng.randint(1, 6))))
                splits.append([text[a:b] for a, b in zip([0] + cuts, cuts + [len(text)])])
            for chunks in splits:
                bubble = app.StreamingBubble(root)
                for chunk in chunks:
                    bubble.append_text(chunk)
                bubble.finalize()
                assert _styled_chars(bubble._body) == _expected_chars(text), (text, chunks)
                assert bubble.get_text() == text
                bubble.destroy()
    finally:
        root.destroy()


@pytest.mark.needs_core
def test_gui_long_streams_cost_about_linear_time():
    import time
    import tkinter as tk
    from gui import app
    from gui.reply_activity import ReplyActivity

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    # Mapped (off-screen) at a real size: a withdrawn window's text widgets
    # are 1 pixel wide, and Tk then wraps every word onto its own line.
    root.geometry("900x700+-3000+-3000")
    root.update()

    def stream(n, newline_every):
        bubble = app.StreamingBubble(root, ReplyActivity(), True)
        bubble.pack(fill="x")
        root.update()
        started = time.perf_counter()
        for i in range(n):
            bubble.add_thinking("think " if i % 15 else "think\n")
            if i % 100 == 0:
                bubble.refresh_activity()        # what the 100 ms batching does
        for i in range(n):
            bubble.append_text("word\n" if i % newline_every == newline_every - 1 else "word ")
        bubble.finalize()
        seconds = time.perf_counter() - started
        assert len(bubble.get_text()) == 5 * n
        assert bubble._activity_view._text.get("1.0", "end-1c") == "".join(
            "think " if i % 15 else "think\n" for i in range(n))
        bubble.destroy()
        return seconds

    try:
        for newline_every in (20, 10 ** 9):      # short lines; one ever-growing line
            small, large = stream(5000, newline_every), stream(20000, newline_every)
            assert large < 20, newline_every     # about 1.5 s here
            # 4x the chunks: linear work takes ~4x, quadratic ~16x.
            assert large < 10 * max(small, 0.05), (newline_every, small, large)
    finally:
        root.destroy()


@pytest.mark.needs_core
@pytest.mark.parametrize("keep_thinking", [True, False])
def test_gui_destroying_a_bubble_cancels_its_pending_redraws(keep_thinking):
    import time
    import tkinter as tk
    from gui import app
    from gui.reply_activity import ReplyActivity

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(exc)
    try:
        def pending():
            return set(root.tk.splitlist(root.tk.call("after", "info")))

        bubble = app.StreamingBubble(root, ReplyActivity(keep_thinking=keep_thinking))
        bubble.add_thinking("Let me check")             # waiting -> thinking: one redraw
        owned = {bubble._refresh_id, bubble._blink_id}
        assert None not in owned and owned <= pending()

        bubble.refresh_activity()
        bubble.add_thinking(" the cards")
        # Off: nothing new to show (the clock moves the line); on: the text.
        assert (bubble._refresh_id is not None) is keep_thinking

        bubble.destroy()                                  # e.g. Stop within 100 ms
        assert not (owned | {bubble._refresh_id}) & pending()
        time.sleep(0.6)
        root.update()
        assert errors == []
        bubble.refresh_activity()                         # a late call on a dead bubble
        assert errors == []
    finally:
        root.destroy()


@pytest.mark.needs_core
def test_gui_reply_bubbles_show_bold_and_code_with_tags():
    import tkinter as tk
    from gui import app
    from gui.inline_markdown import BOLD, CODE

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    try:
        stream = app.StreamingBubble(root)
        for chunk in ("Your *", "*RTX 3060*", "* has `", "12288` MiB", " and **bold"):
            stream.append_text(chunk)
        # while streaming, the line is styled as far as it is known
        assert _tagged(stream._body, BOLD) == ["RTX 3060"]
        stream.finalize()                         # never closed: shown as typed
        assert stream._body.get("1.0", "end-1c") == "Your RTX 3060 has 12288 MiB and **bold"
        assert _tagged(stream._body, BOLD) == ["RTX 3060"]
        assert _tagged(stream._body, CODE) == ["12288"]
        assert stream.get_text().startswith("Your **RTX 3060**")      # the raw reply is kept

        ai = app.MessageBubble(root, "Use **Split** or `gpu:1`.", "ai")
        body = next(w for w in ai.winfo_children()[0].winfo_children()[0].winfo_children()
                    if isinstance(w, tk.Text))
        assert body.get("1.0", "end-1c") == "Use Split or gpu:1."
        assert _tagged(body, BOLD) == ["Split"] and _tagged(body, CODE) == ["gpu:1"]

        user = app.MessageBubble(root, "I typed **this**", "user")
        body = next(w for w in user.winfo_children()[0].winfo_children()[0].winfo_children()
                    if isinstance(w, tk.Text))
        assert body.get("1.0", "end-1c") == "I typed **this**"       # only replies are styled
    finally:
        root.destroy()


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

    db = _store()
    try:
        db.create("gui_old", "gui", model="m")
        bridge = object.__new__(AgentBridge)
        bridge.agent = None
        bridge.conversation_history = [{"role": "user", "content": "hi"}]
        bridge.session_id = "gui_old"
        bridge._session_db = db

        bridge.new_session()

        row = _row(db, "gui_old")
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

    db = _store()
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

        # The agent gets the id and the store (persistence= on current cores,
        # session_db= on older ones), and creates the row on its first turn.
        assert captured["session_id"] == bridge.session_id
        keyword, other = (("session_db", "persistence") if _installed_core_is_legacy()
                          else ("persistence", "session_db"))
        assert captured[keyword] is db.handle and other not in captured
        assert captured["platform"] == "gui"
        assert _row(db, bridge.session_id) is None
    finally:
        db.close()


@pytest.mark.needs_core
def test_gui_resumed_session_continues_under_its_own_id(monkeypatch, tmp_path):
    from gui import agent_bridge
    import run_agent
    from hermes_cli import runtime_provider

    db = _store()
    try:
        db.create("stored", "gui", model="m")
        db.append("stored", "user", "hello")
        db.end("stored", "new_chat")
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

        history = db.conversation("stored")
        assert [m["content"] for m in history] == ["hello"]
        bridge.resume_session("stored", history)

        assert bridge.agent is None
        assert bridge.conversation_history == history
        assert _row(db, "stored")["ended_at"] is None  # reopened, like the CLI
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
    from gui import app
    from gui.i18n import t

    class RefusingDB:
        def reopen(self, session_id):
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
            return SimpleNamespace(conversation=lambda sid: [{"role": "user", "content": "old"}])

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(app, "open_store", StoredDB)
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
def _bundled_skill(root, name):
    skill = root / "demo" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A test skill.\n---\nDo it.\n", encoding="utf-8")


def _skill_names(home):
    return sorted(p.parent.name for p in (home / "skills").rglob("SKILL.md"))


@pytest.mark.needs_core
def test_gui_skills_sync_completes_a_partly_seeded_home(monkeypatch, tmp_path):
    """The core's sync runs whatever the home holds: a home with one of the
    bundled skills (an earlier sync stopped half way) gets the rest."""
    from gui import agent_bridge, app

    bundled = tmp_path / "bundled"
    _bundled_skill(bundled, "first-skill")
    home = tmp_path / "home"
    _bundled_skill(home / "skills", "first-skill")
    _bundled_skill(bundled, "second-skill")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_SKILLS", str(bundled))
    monkeypatch.setattr(agent_bridge, "_skills_synced", False)

    assert agent_bridge.sync_bundled_skills_once() is True
    assert _skill_names(home) == ["first-skill", "second-skill"]
    names = [n for skills in app._discover_installed_skills(home / "skills").values()
             for n, _d in skills]
    assert "second-skill" in names                      # the Skills browser lists it


@pytest.mark.needs_core
def test_gui_skills_sync_runs_once_per_process_and_never_raises(monkeypatch):
    import tools.skills_sync as skills_sync
    from gui import agent_bridge

    calls = []

    def broken(**kw):
        calls.append(kw)
        raise OSError("disk full")
    monkeypatch.setattr(skills_sync, "sync_skills", broken)
    monkeypatch.setattr(agent_bridge, "_skills_synced", False)

    assert agent_bridge.sync_bundled_skills_once() is False   # failed: logged, not raised
    assert agent_bridge.sync_bundled_skills_once() is False   # not again in this process
    assert calls == [{"quiet": True}]


@pytest.mark.needs_core
@pytest.mark.parametrize("may_sync", [True, False])
def test_gui_skills_browser_syncs_only_when_no_reply_runs(monkeypatch, tmp_path, may_sync):
    from unittest.mock import Mock
    from gui import app

    import queue
    import threading

    sync = Mock()
    monkeypatch.setattr(app, "sync_bundled_skills_once", sync)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _bundled_skill(tmp_path / "skills", "listed-skill")
    browser = object.__new__(app.SkillsBrowser)
    shown, tk_calls = [], []
    browser.__dict__.update(_may_sync=may_sync, _result=queue.SimpleQueue(),
                            after=lambda _ms, fn: tk_calls.append(threading.current_thread()),
                            _set=lambda text, **_kw: shown.append(text))

    worker = threading.Thread(target=browser._load)
    worker.start()
    worker.join(30)
    assert tk_calls == [] and shown == []               # the worker never touches Tk
    browser._poll_result()                              # Tk thread shows the result

    assert sync.call_count == (1 if may_sync else 0)
    assert "listed-skill" in shown[-1]                  # during a reply: what is there


@pytest.mark.needs_core
def test_gui_skills_browser_shows_the_list_in_a_real_window(monkeypatch, tmp_path):
    import time
    import tkinter as tk
    from gui import app

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _bundled_skill(tmp_path / "skills", "windowed-skill")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    try:
        browser = app.SkillsBrowser(root, may_sync=False)
        deadline = time.time() + 10
        while "windowed-skill" not in browser.text.get("1.0", "end") and time.time() < deadline:
            root.update()
            time.sleep(0.02)
        assert "windowed-skill" in browser.text.get("1.0", "end")
        assert browser._poll_id is None                 # polling stopped once shown
        browser.destroy()
    finally:
        root.destroy()


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

    gui._on_complete({})                                   # no title yet
    gui.chat_title.configure.assert_called_with(text=t("chat.new_chat_title"))

    sessions[1]["title"] = "General assistance capabilities"
    gui._on_complete({})
    gui.chat_title.configure.assert_called_with(text="General assistance capabilities")

    # A model or settings change rebuilds the agent with a new session id;
    # until that session has a title, the header says New Chat again.
    bridge.session_id = "s2"
    sessions.insert(0, {"id": "s2", "title": None, "preview": "next"})
    gui._on_complete({})
    gui.chat_title.configure.assert_called_with(text=t("chat.new_chat_title"))
    assert gui._chat_title_text is None

    gui._new_chat()
    gui.chat_title.configure.assert_called_with(text=t("chat.new_chat_title"))

    gui._show_session_title("s0", "resumed")               # resuming a stored session
    gui.chat_title.configure.assert_called_with(text="Other chat")
    gui._show_session_title("s2", "resumed")               # one without a title
    gui.chat_title.configure.assert_called_with(text=t("chat.resumed_session"))
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


def _chat_keeping_bubbles(gui, app):
    """_add_msg adds a (Tk-free) MessageBubble that the chat then lists."""
    bubbles = []

    def add(text, msg_type, tool_name=None):
        bubble = object.__new__(app.MessageBubble)
        bubble.__dict__.update(_text=text, _msg_type=msg_type, _tool_name=tool_name)
        bubbles.append(bubble)

    gui._add_msg = add
    gui.msg_frame.winfo_children.side_effect = lambda: list(bubbles)
    return bubbles


class _FakeRoot:
    """Tk's after/after_cancel, run by hand."""

    def __init__(self):
        self.pending, self.next_id = {}, 0

    def after(self, ms, fn):
        self.next_id += 1
        self.pending[self.next_id] = (ms, fn)
        return self.next_id

    def after_cancel(self, after_id):
        self.pending.pop(after_id, None)

    def clock_ticks(self):
        return [i for i, (ms, fn) in self.pending.items() if ms == 1000]

    def run(self, after_id):
        self.pending.pop(after_id)[1]()

    def destroy(self):
        pass


class _FakeReplyBubble:
    """StreamingBubble without Tk: the activity is real."""

    made = []

    def __init__(self, parent, activity=None, thinking_open=False, on_thinking_toggle=None):
        self.activity, self.thinking_open = activity, thinking_open
        self.on_thinking_toggle = on_thinking_toggle
        self.refreshes, self.finalized, self.destroyed, self.text = 0, False, False, ""
        _FakeReplyBubble.made.append(self)

    def pack(self, **kw):
        pass

    def refresh_activity(self):
        self.refreshes += 1

    def add_thinking(self, text):
        self.activity.add_thinking(text)

    def append_text(self, text):
        self.text += text
        self.activity.answer_started()

    def get_text(self):
        return self.text

    def has_content(self):
        return bool(self.text.strip()) or self.activity.expandable

    def finalize(self):
        self.activity.finish()
        self.finalized = True

    def destroy(self):
        self.destroyed = True


def _replying_gui(monkeypatch, *, local=True, history=()):
    """A HermesGUI that has just sent "hi" (fake Tk root and bubbles)."""
    from unittest.mock import Mock
    from gui import app

    _FakeReplyBubble.made = []
    monkeypatch.setattr(app, "StreamingBubble", _FakeReplyBubble)
    monkeypatch.setattr(app, "ToolCallWidget", Mock())
    bridge = Mock(is_running=False, conversation_history=list(history))
    bridge.get_token_usage.return_value = {}
    bridge._is_local_model.return_value = local
    gui = _gui_with_bridge(bridge)
    gui.__dict__.update(root=_FakeRoot(), _stream_bubble=None, _has_streamed=False,
                        _turn_clock_id=None, _show_thinking=True, _thinking_open=False,
                        _attached_images=[], _update_attach_preview=Mock(),
                        msg_canvas=Mock())
    gui.input_text.get.return_value = "hi"
    gui._send()
    bridge.is_running = True
    return gui


@pytest.mark.needs_core
@pytest.mark.parametrize("exit_path", ["reply done", "error", "Stop", "New Chat", "window close"])
def test_gui_reply_clock_ticks_and_stops_on_every_exit_path(monkeypatch, exit_path):
    gui = _replying_gui(monkeypatch)
    bubble, = _FakeReplyBubble.made
    tick, = gui.root.clock_ticks()
    gui.root.run(tick)                                 # one second later
    assert bubble.refreshes == 1 and len(gui.root.clock_ticks()) == 1

    if exit_path == "reply done":
        gui.bridge.is_running = False
        gui._on_complete({})
    elif exit_path == "error":
        gui._on_error("boom")
    elif exit_path == "Stop":
        gui._interrupt()
    elif exit_path == "New Chat":
        gui.bridge.is_running = False
        gui.bridge.new_session.return_value = True
        gui._new_chat()
    else:
        gui.bridge.is_running = False
        from gui import app
        monkeypatch.setattr(app, "unregister_listener", lambda fn: None)
        gui._on_close()

    assert gui.root.clock_ticks() == [] and gui._turn_clock_id is None


@pytest.mark.needs_core
@pytest.mark.parametrize("exit_path", ["reply done", "error", "Stop"])
def test_gui_status_bar_clock_runs_with_the_reply(monkeypatch, exit_path):
    from types import SimpleNamespace
    from gui import app

    now = [500.0]
    monkeypatch.setattr(app, "time", SimpleNamespace(monotonic=lambda: now[0]))
    gui = _replying_gui(monkeypatch)
    gui.status_bar.set_elapsed.assert_called_once_with(0)

    now[0] += 65.4
    gui.root.run(gui.root.clock_ticks()[0])
    assert abs(gui.status_bar.set_elapsed.call_args.args[0] - 65.4) < 1e-6

    {"reply done": lambda: gui._on_complete({}), "error": lambda: gui._on_error("boom"),
     "Stop": gui._interrupt}[exit_path]()
    assert gui.status_bar.set_elapsed.call_args.args == (None,)


def test_status_bar_clock_text():
    from types import SimpleNamespace
    from gui import app

    shown = {}
    bar = SimpleNamespace(clock_lbl=SimpleNamespace(configure=lambda **kw: shown.update(kw)))
    app.StatusBar.set_elapsed(bar, 65.4)
    assert shown["text"] == "1:05"
    app.StatusBar.set_elapsed(bar, None)
    assert shown["text"] == ""


@pytest.mark.needs_core
def test_gui_reply_bubble_follows_waiting_thinking_tool_and_answer(monkeypatch):
    from gui import i18n
    monkeypatch.setattr(i18n, "_current_language", "en")
    gui = _replying_gui(monkeypatch, local=True, history=())
    first, = _FakeReplyBubble.made
    assert first.activity.first_local_turn and first.activity.state == "waiting"

    gui._on_reasoning("Need the GPU list.")
    assert first.activity.state == "thinking"
    assert "Need the GPU list." in first.activity.header()

    gui._on_tool_call("gpu_info", "{}")               # thinking kept, a new segment runs the tool
    assert first.finalized and not first.destroyed
    second = _FakeReplyBubble.made[-1]
    assert second.activity.header().startswith("Running gpu_info...")
    gui._on_step(2, ["gpu_info"])                      # the model is called again
    assert second.activity.state == "waiting" and not second.activity.first_local_turn
    gui._on_stream_delta("Your RTX 3060")
    assert second.activity.state == "done"


@pytest.mark.needs_core
def test_gui_later_turns_and_cloud_models_get_no_first_turn_note(monkeypatch):
    gui = _replying_gui(monkeypatch, local=True, history=[{"role": "user", "content": "x"}])
    assert not _FakeReplyBubble.made[-1].activity.first_local_turn
    gui = _replying_gui(monkeypatch, local=False, history=())
    assert not _FakeReplyBubble.made[-1].activity.first_local_turn


@pytest.mark.needs_core
def test_gui_thinking_choices_are_remembered(monkeypatch):
    saved = {}
    from gui import app
    monkeypatch.setattr(app, "save_gui_setting", lambda k, v: saved.__setitem__(k, v))
    gui = _replying_gui(monkeypatch)
    gui._build_menu_items = lambda: None

    _FakeReplyBubble.made[-1].on_thinking_toggle(True)   # the user opens the tab
    assert saved == {"thinking_open": True} and gui._thinking_open is True
    gui._toggle_show_thinking()
    assert saved["show_thinking"] is False

    gui.bridge.is_running = False
    gui._on_complete({})
    gui._send()                                          # the next reply uses both
    bubble = _FakeReplyBubble.made[-1]
    assert bubble.thinking_open is True and bubble.activity.keep_thinking is False


@pytest.mark.needs_core
def test_gui_reply_bubble_activity_line_in_real_tk(monkeypatch):
    import tkinter as tk
    from gui import app, i18n
    from gui.reply_activity import ReplyActivity

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    monkeypatch.setattr(i18n, "_current_language", "en")
    try:
        toggles = []
        bubble = app.StreamingBubble(root, ReplyActivity(), False, toggles.append)
        bubble.pack()
        view = bubble._activity_view
        assert view._label.cget("text").startswith("Waiting for the model... 0:0")
        for word in ["Let me ", "check ", "the ", "cards."] * 50:   # many tokens, one refresh
            bubble.add_thinking(word)
        assert bubble._refresh_id is not None
        bubble.refresh_activity()
        assert view._label.cget("text").startswith("▸ Thinking... 0:0")
        assert view._text is None                         # closed: no thinking pane
        view.toggle()
        assert toggles == [True] and view._text.get("1.0", "end-1c").endswith("the cards.")
        bubble.add_thinking(" More.")
        bubble.refresh_activity()
        assert view._text.get("1.0", "end-1c").endswith("cards. More.")
        bubble.append_text("Answer")
        assert view._label.cget("text").startswith("▾ Thought for ")
        bubble.finalize()
        assert bubble._body.get("1.0", "end-1c") == "Answer"
    finally:
        root.destroy()


@pytest.mark.needs_core
def test_gui_sidebar_fit_note_follows_model_gpu_and_context(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from gui import app, i18n
    from portable_hermes import lmstudio_gpu as gpu_place

    monkeypatch.setattr(i18n, "_current_language", "en")
    bar = object.__new__(app.Sidebar)
    shown = {}
    label = Mock()
    label.configure.side_effect = lambda **kw: shown.update(kw)
    label.pack.side_effect = lambda **kw: shown.update(packed=True)
    label.pack_forget.side_effect = lambda: shown.update(packed=False)
    ctx = Mock(get=lambda: 65536)
    bar.__dict__.update(
        _fit_hint_lbl=label, _ctx_var=ctx, _gpu_combo=SimpleNamespace(master="gpu row"),
        _gpus=[gpu_place.NvidiaGpu(0, "RTX 3060", 12288), gpu_place.NvidiaGpu(1, "RTX 3090", 24576)],
        _gpu_label_to_placement={"3090": "gpu:1", "split": "split"},
        _gpu_var=Mock(get=lambda: "3090"),
        _model_sizes={"qwen3.8-27b": 16285824272}, model_var=Mock(get=lambda: "qwen3.8-27b"))

    bar._save_local_settings()                       # what every local control calls
    assert shown["packed"] and shown["text"].startswith("This model may not fit")
    label.pack.assert_called_with(fill="x", after="gpu row")

    bar._gpu_var.get = lambda: "split"
    bar._save_local_settings()
    assert shown == {"text": "", "packed": False}

    bar._gpu_var.get = lambda: "3090"
    ctx.get = lambda: "not a number"                 # typed text in the Ctx box
    bar._save_local_settings()
    assert shown["packed"] is False


@pytest.mark.needs_core
def test_gui_a_refusal_in_a_row_is_not_repeated_in_the_chat():
    import threading
    from unittest.mock import Mock
    from gui import app
    from gui.i18n import t

    busy = t("chat.busy_stop_first", stop=t("chat.stop"))
    gui = _gui_with_bridge(Mock(is_running=True))
    bubbles = _chat_keeping_bubbles(gui, app)

    assert gui._refuse_while_running() and gui._refuse_while_running()
    assert [(b._text, b._msg_type) for b in bubbles] == [(busy, "system")]

    gui._add_msg("a reply", "ai")                     # another line in between: say it again
    gui._refuse_while_running()
    gui._add_msg(busy, "ai")                          # same words, but not a System line
    gui._refuse_while_running()
    assert [b._msg_type for b in bubbles] == ["system", "ai", "system", "ai", "system"]

    gui.bridge.is_running = False
    gui.input_text.get.return_value = "hello"
    release = threading.Event()
    loader = threading.Thread(target=release.wait, args=(10,), daemon=True)
    loader.start()
    gui._track_model_work(loader)
    gui._send()
    gui._send()
    assert [b._text for b in bubbles[-2:]] == [busy, t("chat.model_loading_wait")]
    release.set()
    loader.join(10)


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

    with _store() as db:
        for sid in ("del_me", "keep"):
            db.create(sid, "gui", model="m")
            db.append(sid, "user", "hello")
    sidebar = _delete_sidebar(app, monkeypatch)

    sidebar._perform_delete("del_me")

    with _store() as db:
        assert _row(db, "del_me") is None
        assert db.conversation("del_me") == []
        assert _row(db, "keep") is not None
    sidebar.after.assert_not_called()


@pytest.mark.needs_core
def test_gui_sidebar_failed_delete_reloads_the_list_without_raw_sql(monkeypatch):
    import sqlite3
    from gui import app

    class RefusingStore:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def delete(self, session_id):
            raise RuntimeError("session is being written")

    def no_raw_sql(*args, **kwargs):
        raise AssertionError("the GUI must not edit state.db directly")

    monkeypatch.setattr(app, "open_store", RefusingStore)
    monkeypatch.setattr(sqlite3, "connect", no_raw_sql)
    sidebar = _delete_sidebar(app, monkeypatch)

    sidebar._perform_delete("busy")

    sidebar.after.assert_called_once_with(0, sidebar._load_sessions)
