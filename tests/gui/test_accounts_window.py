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

    def start_sign_in(self, p):
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
    window._disconnect("xai-oauth")
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
        "menu.accounts", "chat.account_in_use", "chat.account_rejected", "wizard.accounts_hint"}
    assert len(keys) == 31
    for lang, table in TRANSLATIONS.items():
        for key in keys:
            fields = [f for f in ("{name}", "{model}", "{time}", "{error}", "{command}", "{menu}")
                      if f in TRANSLATIONS["en"][key]]
            assert all(f in table[key] for f in fields), (lang, key)
