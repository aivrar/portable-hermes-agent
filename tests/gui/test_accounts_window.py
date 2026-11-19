"""View > Accounts: the window and the sign-in dialog (Tk; the adapter is faked)."""
from __future__ import annotations

import time

import pytest

from gui import accounts_core as core

SECRET = "tok-SECRET-123"


@pytest.fixture
def tk_root(monkeypatch):
    import tkinter as tk
    from gui import i18n
    monkeypatch.setattr(i18n, "_current_language", "en")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    yield root
    root.destroy()


def pump(root, cond, seconds=5.0):
    end = time.monotonic() + seconds
    while not cond():
        assert time.monotonic() < end, "timed out"
        root.update()
        time.sleep(0.01)


def texts(widget):
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except Exception:
            pass
        found += texts(child)
    return found


class FakeCore:
    def __init__(self, monkeypatch, start=None, states=None):
        from gui import accounts_window
        self.calls, self.states, self.opened = [], list(states or []), []
        self.start_result = start or {"session": "s1", "url": "https://x.ai/device",
                                      "user_code": "ABCD-1234", "expires_in": 600}
        for name in ("status", "start_sign_in", "poll", "cancel", "disconnect", "models", "default_model"):
            monkeypatch.setattr(core, name, getattr(self, name))
        monkeypatch.setattr(accounts_window.webbrowser, "open", self.opened.append)

    def status(self, p):
        return p == "openai-codex"

    gate = None

    def start_sign_in(self, p):
        if self.gate is not None:
            self.gate.wait(5)
        self.calls.append(("start", p))
        return self.start_result

    def poll(self, s):
        self.calls.append(("poll", s))
        return self.states.pop(0) if self.states else ("pending", "")

    def cancel(self, s):
        self.calls.append(("cancel", s))

    def disconnect(self, p):
        self.calls.append(("disconnect", p))
        return True

    def models(self, p):
        return ["grok-4.6", "grok-4.7"]

    def default_model(self, p, ids):
        return "grok-4.6"


class Now:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


def _dialog(root, **kw):
    from gui.accounts_window import SignInDialog
    used, now = [], Now()
    dialog = SignInDialog(root, "xai-oauth", "xAI Grok", lambda p, m: used.append((p, m)), now=now, **kw)
    return dialog, used, now


def test_window_rows_follow_the_status(tk_root, monkeypatch):
    from gui.accounts_window import AccountsWindow
    fake_core = FakeCore(monkeypatch)
    window = AccountsWindow(tk_root, on_use=lambda p, m: None, active_account=lambda: "openai-codex")
    assert "Checking..." in texts(window)
    pump(tk_root, lambda: window.connected)
    shown = texts(window)
    assert shown.count("Connected") == 1 and shown.count("Not connected") == 1
    assert {"Connect", "Use", "Disconnect"} <= set(shown)

    window._disconnect("openai-codex")                  # in use for chat: refused
    assert ("disconnect", "openai-codex") not in fake_core.calls
    assert "in use for chat" in window.note.cget("text")
    window._disconnect("xai-oauth")                      # on the worker, not the Tk thread
    pump(tk_root, lambda: "disconnected" in window.note.cget("text"))
    assert ("disconnect", "xai-oauth") in fake_core.calls
    window.destroy()
    assert not window._worker.busy


def test_sign_in_shows_the_code_and_then_offers_the_model(tk_root, monkeypatch):
    fake_core = FakeCore(monkeypatch, states=[("pending", ""), ("approved", "")])
    dialog, used, now = _dialog(tk_root)
    assert dialog.state == "starting"
    pump(tk_root, lambda: dialog.state == "waiting")
    assert fake_core.opened == ["https://x.ai/device"]             # the GUI opens the browser
    assert {"https://x.ai/device", "ABCD-1234"} <= set(texts(dialog))
    assert dialog.waiting.cget("text") == "Waiting for approval... 10:00"
    assert dialog._tick_id is not None

    dialog._stop_tick()
    now.value += 65
    dialog._tick()                                                 # second poll: approved
    assert dialog._tick_id is None and dialog.session is None
    pump(tk_root, lambda: hasattr(dialog, "model_var"))
    assert dialog.model_var.get() == "grok-4.6"
    assert "Use Grok for chat with:" in texts(dialog)
    dialog.model_var.set("grok-4.7")
    dialog._use()
    assert used == [("xai-oauth", "grok-4.7")] and not dialog.winfo_exists()
    assert ("cancel", "s1") not in fake_core.calls                 # a finished sign-in is not cancelled


def test_the_countdown_is_live(tk_root, monkeypatch):
    FakeCore(monkeypatch)
    dialog, _, now = _dialog(tk_root)
    pump(tk_root, lambda: dialog.state == "waiting")
    dialog._stop_tick()
    now.value += 65
    dialog._tick()
    assert dialog.waiting.cget("text") == "Waiting for approval... 8:55"
    assert dialog._tick_id is not None                             # still waiting: next tick set
    dialog.destroy()


@pytest.mark.parametrize("state, message, shown", [
    ("denied", "", "Sign-in was declined in the browser."),
    ("expired", "Device code expired before approval", "The code expired before it was approved."),
    ("error", "network down", "Sign-in failed: network down"),
])
def test_a_failed_sign_in_says_why_and_can_try_again(tk_root, monkeypatch, state, message, shown):
    fake_core = FakeCore(monkeypatch, states=[(state, message)])
    dialog, used, _ = _dialog(tk_root)
    pump(tk_root, lambda: dialog.state == "failed")
    assert shown in texts(dialog) and "Try again" in texts(dialog)
    assert dialog._tick_id is None and used == []
    dialog.start()                                                 # Try again
    pump(tk_root, lambda: dialog.state == "waiting")
    assert [c for c in fake_core.calls if c[0] == "start"] == [("start", "xai-oauth")] * 2
    dialog.destroy()


def test_closing_the_dialog_cancels_the_sign_in_and_its_timers(tk_root, monkeypatch):
    fake_core = FakeCore(monkeypatch)
    dialog, used, _ = _dialog(tk_root)
    pump(tk_root, lambda: dialog.state == "waiting")
    assert dialog._tick_id is not None
    dialog.destroy()                                               # the window's X does the same
    assert ("cancel", "s1") in fake_core.calls and used == []
    assert dialog._tick_id is None and not dialog._worker.busy


def test_closing_while_starting_stops_the_worker_timer(tk_root, monkeypatch):
    FakeCore(monkeypatch)
    dialog, _, _ = _dialog(tk_root)
    assert dialog._worker.busy
    dialog.destroy()
    assert not dialog._worker.busy


def test_the_code_running_out_ends_the_wait(tk_root, monkeypatch):
    fake_core = FakeCore(monkeypatch)
    dialog, _, now = _dialog(tk_root)
    pump(tk_root, lambda: dialog.state == "waiting")
    dialog._stop_tick()
    now.value += 601
    dialog._tick()
    assert ("cancel", "s1") in fake_core.calls
    assert "The code expired before it was approved." in texts(dialog)
    dialog.destroy()


def test_an_old_core_gets_the_terminal_command(tk_root, monkeypatch):
    FakeCore(monkeypatch, start={"unavailable": True, "command": "hermes auth add xai-oauth"})
    dialog, _, _ = _dialog(tk_root)
    pump(tk_root, lambda: dialog.state == "failed")
    shown = " ".join(texts(dialog))
    assert "hermes auth add xai-oauth" in shown and "Try again" not in shown
    dialog.destroy()


def test_a_connected_account_goes_straight_to_the_model(tk_root, monkeypatch):
    fake_core = FakeCore(monkeypatch)
    dialog, _, _ = _dialog(tk_root, connected=True)
    pump(tk_root, lambda: hasattr(dialog, "model_var"))
    assert not [c for c in fake_core.calls if c[0] == "start"]
    assert SECRET not in " ".join(texts(dialog))
    dialog.destroy()


def test_accounts_strings_exist_in_every_language():
    from gui.i18n import TRANSLATIONS
    keys = {k for k in TRANSLATIONS["en"] if k.startswith("accounts.")} | {
        "menu.accounts", "chat.account_in_use", "chat.account_rejected", "wizard.accounts_hint",
        "chat.model_save_failed"}
    assert len(keys) == 34
    for lang, table in TRANSLATIONS.items():
        for key in keys:
            fields = [f for f in ("{name}", "{model}", "{time}", "{error}", "{command}", "{menu}")
                      if f in TRANSLATIONS["en"][key]]
            assert all(f in table[key] for f in fields), (lang, key)


def test_the_key_wizard_points_subscribers_to_accounts(tk_root):
    from gui.api_setup_wizard import APISetupWizard
    wizard = APISetupWizard(tk_root)
    try:
        assert ("Have a ChatGPT or Grok subscription? Use View > Accounts (ChatGPT, Grok) "
                "instead of a key.") in texts(wizard)
    finally:
        wizard.destroy()


def test_closing_before_the_session_exists_still_cancels_it(tk_root, monkeypatch):
    import threading
    fake_core = FakeCore(monkeypatch)
    fake_core.gate = threading.Event()
    dialog, used, _ = _dialog(tk_root)
    shown_before = []
    monkeypatch.setattr(dialog, "_started", shown_before.append)   # must never run
    dialog.destroy()                                   # the core has not answered yet
    assert fake_core.calls == []
    fake_core.gate.set()                               # now the core returns session s1
    deadline = time.monotonic() + 5
    while ("cancel", "s1") not in fake_core.calls:
        assert time.monotonic() < deadline, fake_core.calls
        time.sleep(0.01)
    tk_root.update()
    assert fake_core.calls == [("start", "xai-oauth"), ("cancel", "s1")]
    assert shown_before == [] and used == [] and fake_core.opened == []


def test_disconnect_is_refused_while_a_reply_or_model_work_runs(tk_root, monkeypatch):
    from gui.accounts_window import AccountsWindow
    fake_core = FakeCore(monkeypatch)
    window = AccountsWindow(tk_root, on_use=lambda p, m: None, can_change=lambda: False)
    window._disconnect("xai-oauth")
    assert ("disconnect", "xai-oauth") not in fake_core.calls
    assert window.note.cget("text") == "Wait until the reply or the model change has finished."
    window.destroy()


def _boom(*_args):
    raise RuntimeError("core changed its mind")


def test_a_failing_step_ends_the_wait_with_a_plain_message(tk_root, monkeypatch):
    fake_core = FakeCore(monkeypatch, states=[("approved", "")])
    monkeypatch.setattr(core, "default_model", _boom)              # after sign-in, models step fails
    dialog, used, _ = _dialog(tk_root)
    pump(tk_root, lambda: "Try again" in texts(dialog) and dialog.state == "models")
    shown = " ".join(texts(dialog))
    assert "Could not load the model list" in shown and "Traceback" not in shown
    assert not dialog._worker.busy and dialog._tick_id is None and used == []
    dialog.destroy()

    monkeypatch.setattr(core, "start_sign_in", _boom)              # the start itself fails
    dialog, _, _ = _dialog(tk_root)
    pump(tk_root, lambda: dialog.state == "failed")
    assert "Sign-in failed: core changed its mind" in texts(dialog) and not dialog._worker.busy
    dialog.destroy()


def test_a_failing_poll_cancels_and_stops_polling(tk_root, monkeypatch):
    fake_core = FakeCore(monkeypatch)
    dialog, _, _ = _dialog(tk_root)
    pump(tk_root, lambda: dialog.state == "waiting")
    monkeypatch.setattr(core, "poll", _boom)
    dialog._stop_tick()
    dialog._tick()
    assert dialog.state == "failed" and dialog._tick_id is None
    assert ("cancel", "s1") in fake_core.calls
    assert "Sign-in failed: core changed its mind" in texts(dialog)
    dialog.destroy()


def test_a_failing_disconnect_says_so(tk_root, monkeypatch):
    from gui.accounts_window import AccountsWindow
    FakeCore(monkeypatch)
    monkeypatch.setattr(core, "disconnect", _boom)
    window = AccountsWindow(tk_root, on_use=lambda p, m: None)
    pump(tk_root, lambda: window.connected)
    window._disconnect("openai-codex")
    pump(tk_root, lambda: window.note.cget("text"))
    assert window.note.cget("text") == "Something went wrong: core changed its mind"
    assert not window._worker.busy
    window.destroy()


def _app(root):
    """The app's account parts on a real Tk root (bridge and widgets faked)."""
    from unittest.mock import Mock
    from gui import app
    gui = object.__new__(app.HermesGUI)
    bridge = Mock(is_running=False, _account_provider=None, _active_provider="cloud")
    bridge.get_model.return_value = "google/gemini-2.5-flash"
    gui.__dict__.update(bridge=bridge, root=root, _add_msg=Mock(), msg_frame=Mock(),
                        sidebar=Mock(_loading_model=False), status_bar=Mock(), _model_work=[],
                        _lm_panels=[])
    gui.msg_frame.winfo_children.return_value = []
    return gui


def _accounts_windows(root):
    from gui.accounts_window import AccountsWindow
    return [w for w in root.winfo_children() if isinstance(w, AccountsWindow)]


def test_view_accounts_opens_one_window_and_brings_it_forward(tk_root, monkeypatch):
    FakeCore(monkeypatch)
    gui = _app(tk_root)
    gui._open_accounts()
    first = gui._accounts_window
    raised = []
    for name in ("deiconify", "lift", "focus_force"):
        setattr(first, name, lambda n=name: raised.append(n))
    gui._open_accounts()
    assert gui._accounts_window is first and _accounts_windows(tk_root) == [first]
    assert raised == ["deiconify", "lift", "focus_force"]    # brought forward
    first.destroy()
    gui._open_accounts()                                # closed: a new one opens
    assert gui._accounts_window is not first and len(_accounts_windows(tk_root)) == 1
    gui._accounts_window.destroy()


def test_disconnect_holds_the_busy_state_until_it_ends(tk_root, monkeypatch):
    import threading
    from gui.i18n import t
    fake_core = FakeCore(monkeypatch)
    gate, used = threading.Event(), []

    def slow_disconnect(p):
        gate.wait(5)
        fake_core.calls.append(("disconnect", p))
        return True
    monkeypatch.setattr(core, "disconnect", slow_disconnect)
    monkeypatch.setattr(core, "use", lambda p, m: used.append(m))
    gui = _app(tk_root)
    gui._open_accounts()
    window = gui._accounts_window
    pump(tk_root, lambda: window.connected)

    window._disconnect("openai-codex")
    assert gui._model_work_running() and gui._refuse_model_change() is True    # Send waits too
    gui._use_account("xai-oauth", "grok-4.6")            # a switch cannot start mid-disconnect
    window._disconnect("openai-codex")                   # nor a second disconnect (also a notice)
    assert window.note.cget("text") == t("accounts.busy")
    assert [c[0][0] for c in gui._add_msg.call_args_list] == [t("chat.model_loading_wait")] * 3
    gate.set()
    pump(tk_root, lambda: "disconnected" in window.note.cget("text"))
    assert fake_core.calls.count(("disconnect", "openai-codex")) == 1 and used == []
    assert not gui._model_work_running() and gui._refuse_model_change() is False
    window.destroy()


def test_a_failing_or_orphaned_disconnect_still_ends_the_busy_state(tk_root, monkeypatch):
    import threading
    FakeCore(monkeypatch)
    monkeypatch.setattr(core, "disconnect", _boom)
    gui = _app(tk_root)
    gui._open_accounts()
    window = gui._accounts_window
    pump(tk_root, lambda: window.connected)
    window._disconnect("openai-codex")
    pump(tk_root, lambda: not gui._model_work_running())
    assert window.note.cget("text") == "Something went wrong: core changed its mind"

    gate = threading.Event()                             # closed while it runs
    monkeypatch.setattr(core, "disconnect", lambda p: gate.wait(5))
    window._disconnect("openai-codex")
    window.destroy()
    assert gui._model_work_running()
    gate.set()
    pump(tk_root, lambda: not gui._model_work_running())   # no error from the closed window
