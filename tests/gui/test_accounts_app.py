"""Chatting through a signed-in account: the bridge, the model box and the
status bar (the adapter is faked; no network, no sign-in)."""
from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gui import accounts_core

pytestmark = pytest.mark.needs_core


@pytest.fixture(autouse=True)
def english(monkeypatch):
    from gui import i18n
    monkeypatch.setattr(i18n, "_current_language", "en")
    yield


def _bridge(**fields):
    from gui.agent_bridge import AgentBridge
    bridge = object.__new__(AgentBridge)
    bridge.__dict__.update(agent=None, conversation_history=[], session_id="s", _session_db=None,
                           is_running=False, _resume_session_id=None, _shutdown_once=threading.Lock(),
                           _clarify_queue=queue.Queue(), _approval_queue=queue.Queue(),
                           _active_provider="cloud", _selected_model="google/gemini-2.5-flash",
                           _lm_studio_base_url=None, _known_local_models={"local/m"}, config={},
                           _account_provider=None)
    bridge.__dict__.update(fields)
    return bridge


def test_account_mode_reloads_the_config_and_starts_a_new_session(monkeypatch):
    from gui import agent_bridge
    monkeypatch.setattr(agent_bridge, "_load_cli_config",
                        lambda: {"model": {"provider": "xai-oauth", "default": "grok-4.6"}})
    bridge = _bridge(_resume_session_id="stored", _active_provider="local",
                     _lm_studio_base_url="http://127.0.0.1:1234")
    assert bridge.set_account_mode("xai-oauth", "grok-4.6") is True     # pending resume dropped
    assert (bridge._account_provider, bridge.get_model(), bridge._active_provider,
            bridge._lm_studio_base_url) == ("xai-oauth", "grok-4.6", "cloud", None)
    assert bridge.config["model"]["provider"] == "xai-oauth"


def test_account_mode_is_refused_during_a_reply():
    from gui.agent_bridge import TurnInProgress
    bridge = _bridge(is_running=True)
    with pytest.raises(TurnInProgress):
        bridge.set_account_mode("openai-codex", "gpt-6-sol")
    assert (bridge._account_provider, bridge._selected_model) == (None, "google/gemini-2.5-flash")


def test_an_openrouter_pick_names_its_provider_and_lm_studio_writes_nothing(monkeypatch):
    from gui import agent_bridge
    written = []
    monkeypatch.setattr(accounts_core, "use_openrouter", written.append)
    monkeypatch.setattr(agent_bridge, "_load_cli_config", lambda: {"model": {"provider": "openrouter"}})
    bridge = _bridge(_account_provider="openai-codex")
    bridge.set_cloud_mode("google/gemini-2.5-pro")
    assert written == ["google/gemini-2.5-pro"] and bridge._account_provider is None
    bridge.set_local_mode("http://127.0.0.1:1234", "local/m")
    bridge.set_cloud_mode("local/m")             # LM Studio not running: as before, no write
    assert written == ["google/gemini-2.5-pro"]


class FakeRoot:
    def __init__(self):
        self.pending = []

    def after(self, _ms, fn):
        self.pending.append(fn)

    def drain(self, until, seconds=5.0):
        end = time.monotonic() + seconds
        while not until():
            assert time.monotonic() < end, "timed out"
            pending, self.pending = self.pending, []
            for fn in pending:
                fn()
            time.sleep(0.01)


def _gui(bridge):
    from gui import app
    gui = object.__new__(app.HermesGUI)
    gui.__dict__.update(bridge=bridge, root=FakeRoot(), _add_msg=Mock(), msg_frame=Mock(),
                        sidebar=Mock(_loading_model=False), status_bar=Mock(), _model_work=[],
                        _lm_panels=[])
    gui.msg_frame.winfo_children.return_value = []
    return gui


def _account_bridge(calls):
    bridge = Mock(is_running=False, _account_provider=None, _active_provider="cloud")
    bridge.get_model.return_value = "google/gemini-2.5-flash"

    def set_account_mode(provider, model):
        calls.append(("bridge", provider, model))
        bridge._account_provider = provider
        return False
    bridge.set_account_mode.side_effect = set_account_mode
    return bridge


def test_using_an_account_validates_on_a_worker_then_switches(monkeypatch):
    calls, release = [], threading.Event()

    def use(provider, model):
        release.wait(5)
        calls.append(("use", provider, model))
        return model
    monkeypatch.setattr(accounts_core, "use", use)
    monkeypatch.setattr(accounts_core, "models", lambda p: ["gpt-6-sol", "gpt-6-luna"])
    gui = _gui(_account_bridge(calls))

    gui._use_account("openai-codex", "gpt-6-sol")
    assert gui._model_work_running()            # sending waits for the switch
    release.set()
    gui.root.drain(lambda: gui.sidebar.set_account_models.called)
    assert calls == [("use", "openai-codex", "gpt-6-sol"), ("bridge", "openai-codex", "gpt-6-sol")]
    assert not gui._model_work_running()
    gui.status_bar.set_model.assert_called_with("ChatGPT: gpt-6-sol")
    gui.sidebar.set_account_models.assert_called_with("openai-codex", "ChatGPT", ["gpt-6-sol", "gpt-6-luna"])
    assert "Now chatting through ChatGPT: gpt-6-sol." in str(gui._add_msg.call_args_list)


def test_a_rejected_account_model_says_why_and_keeps_the_model(monkeypatch):
    def use(provider, model):
        raise accounts_core.Rejected("not supported when using Codex")
    monkeypatch.setattr(accounts_core, "use", use)
    calls = []
    gui = _gui(_account_bridge(calls))
    gui._use_account("openai-codex", "google/gemini-2.5-flash")
    gui.root.drain(lambda: gui._add_msg.called)
    text, kind = gui._add_msg.call_args[0]
    assert kind == "error" and "not supported when using Codex" in text
    assert calls == [] and not gui._model_work_running()
    gui.sidebar.set_model.assert_called_with("google/gemini-2.5-flash")


def test_using_an_account_is_refused_while_a_reply_runs_or_a_model_loads(monkeypatch):
    from gui.i18n import t
    used = []
    monkeypatch.setattr(accounts_core, "use", lambda p, m: used.append(m))
    gui = _gui(_account_bridge([]))
    gui.bridge.is_running = True
    gui._use_account("xai-oauth", "grok-4.6")
    gui.bridge.is_running = False
    gui.sidebar._loading_model = True
    gui._use_account("xai-oauth", "grok-4.6")
    shown = [c[0][0] for c in gui._add_msg.call_args_list]
    assert shown == [t("chat.busy_stop_first", stop=t("chat.stop")), t("chat.model_loading_wait")]
    assert used == [] and gui.root.pending == []


def test_the_model_box_lists_account_models_and_routes_them(monkeypatch):
    from gui import app
    sidebar = object.__new__(app.Sidebar)
    sidebar.__dict__.update(_account_models=[], _lm_studio_models=[("local/m", "m", "LM Studio")],
                            _update_combobox_values=Mock())
    sidebar.set_account_models("openai-codex", "ChatGPT", ["gpt-6-sol"])
    assert sidebar._all_models[0] == ("gpt-6-sol", "[ChatGPT] gpt-6-sol", "account:openai-codex")
    assert sidebar._all_models[-1][0] == "local/m" and len(sidebar._all_models) == len(app.Sidebar.MODELS) + 2
    assert app.Sidebar._display_name(sidebar._all_models[0]) == "[ChatGPT] gpt-6-sol"
    assert sidebar.account_for("gpt-6-sol") == "openai-codex"
    assert sidebar.account_for("google/gemini-2.5-flash") is None

    gui = _gui(_account_bridge([]))
    gui.sidebar, gui._use_account = sidebar, Mock()
    gui._on_model_change("gpt-6-sol")
    gui._use_account.assert_called_once_with("openai-codex", "gpt-6-sol")
    gui.bridge._known_local_models = set()
    gui._on_model_change("google/gemini-2.5-flash")             # OpenRouter: as before
    gui.bridge.set_model.assert_called_once_with("google/gemini-2.5-flash")


def test_the_status_bar_names_the_account_unless_on_lm_studio():
    gui = _gui(SimpleNamespace(_account_provider="xai-oauth", _active_provider="cloud"))
    assert gui._model_label("grok-4.6") == "Grok: grok-4.6"
    gui.bridge._active_provider = "local"
    assert gui._model_label("qwen") == "qwen" and gui._active_account() is None
    gui.bridge = Mock()                                          # older test doubles
    assert gui._model_label("m") == "m"


def test_settings_save_keeps_the_model_unless_it_was_changed(monkeypatch):
    from gui import app
    from gui.i18n import SUPPORTED_LANGUAGES
    dialog = object.__new__(app.SettingsDialog)
    dialog.__dict__.update(key_entries={}, bridge=Mock(is_running=False), destroy=Mock(),
                           _shown_model="google/gemini-2.5-flash",
                           model_var=SimpleNamespace(get=lambda: "google/gemini-2.5-flash"),
                           lang_var=SimpleNamespace(get=lambda: dict(SUPPORTED_LANGUAGES)["en"]))
    app.SettingsDialog._save(dialog)
    dialog.bridge.set_model.assert_not_called()                  # the account stays in use
    dialog.model_var = SimpleNamespace(get=lambda: "openai/gpt-4o")
    app.SettingsDialog._save(dialog)
    dialog.bridge.set_model.assert_called_once_with("openai/gpt-4o")
