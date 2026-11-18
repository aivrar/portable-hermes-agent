"""View > Accounts: sign in with a ChatGPT/Codex or Grok subscription.

Every core call goes through gui.accounts_core; anything that can block runs
on a worker thread whose result the Tk thread picks up with ``after`` (the
Skills browser pattern). Every timer is cancelled when a window closes, and
closing the sign-in dialog cancels the sign-in.
"""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

from gui import accounts_core as core
from gui.i18n import t
from gui.reply_activity import clock
from gui.theme import C, FONTS, S, SF, center_window, set_dark_title_bar


class _Worker:
    """Runs fn on a thread; the Tk thread gets on_done(result) via after().
    stop() cancels the pending timer (the result is then dropped)."""

    def __init__(self, widget):
        self._widget = widget
        self._after_id = None

    def run(self, fn, on_done):
        self.stop()
        results = queue.SimpleQueue()
        threading.Thread(target=lambda: results.put(fn()), daemon=True).start()

        def check():
            try:
                result = results.get_nowait()
            except queue.Empty:
                self._after_id = self._widget.after(100, check)
                return
            self._after_id = None
            on_done(result)
        self._after_id = self._widget.after(100, check)

    @property
    def busy(self):
        return self._after_id is not None

    def stop(self):
        if self._after_id is not None:
            self._widget.after_cancel(self._after_id)
            self._after_id = None


def _toplevel(window, parent, title, width, height):
    window.title(title)
    window.configure(bg=C["bg_main"])
    window.transient(parent)
    set_dark_title_bar(window)
    center_window(window, width, height, parent)


class AccountsWindow(tk.Toplevel):
    """Two rows: name, status, [Connect] or [Use] [Disconnect].

    *on_use(provider, model)*: the app switches the chat to the account.
    *active_account()*: the account the chat uses now, or None."""

    def __init__(self, parent, on_use, active_account=lambda: None):
        super().__init__(parent)
        self.on_use, self.active_account = on_use, active_account
        _toplevel(self, parent, t("accounts.title"), 560, 300)
        tk.Label(self, text=t("accounts.title"), font=FONTS["title"], fg=C["accent"],
                 bg=C["bg_main"]).pack(pady=(16, 2))
        tk.Label(self, text=t("accounts.subtitle"), font=FONTS["small"], fg=C["text_hint"],
                 bg=C["bg_main"], wraplength=S(500)).pack(padx=20)
        self.note = tk.Label(self, text="", font=FONTS["small"], fg=C["warning"],
                             bg=C["bg_main"], wraplength=S(500))
        self.note.pack(side="bottom", pady=(0, 12))
        self.rows_frame = tk.Frame(self, bg=C["bg_main"])
        self.rows_frame.pack(fill="both", expand=True, padx=20, pady=12)
        self.names = dict(core.rows())
        self.connected = {}
        self.dialog = None
        self._worker = _Worker(self)
        self.refresh()

    def destroy(self):
        self._worker.stop()
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.destroy()
        super().destroy()

    def refresh(self):
        self._draw()
        self._worker.run(lambda: {p: core.status(p) for p in self.names}, self._statuses)

    def _statuses(self, connected):
        self.connected = connected
        self._draw()

    def _draw(self):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        for provider, name in self.names.items():
            row = tk.Frame(self.rows_frame, bg=C["bg_card"], padx=12, pady=8)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=name, font=FONTS["body"], fg=C["text_primary"],
                     bg=C["bg_card"]).pack(side="left")
            state = self.connected.get(provider)
            if state is None:
                tk.Label(row, text=t("accounts.checking"), font=FONTS["small"],
                         fg=C["text_hint"], bg=C["bg_card"]).pack(side="right")
                continue
            buttons = ([(t("accounts.disconnect"), self._disconnect), (t("accounts.use"), self._open)]
                       if state else [(t("accounts.connect"), self._open)])
            for label, action in buttons:
                ttk.Button(row, text=label, command=lambda a=action, p=provider: a(p)).pack(
                    side="right", padx=(6, 0))
            tk.Label(row, text=t("accounts.connected" if state else "accounts.not_connected"),
                     font=FONTS["small"], fg=C["success"] if state else C["text_hint"],
                     bg=C["bg_card"]).pack(side="right", padx=8)

    def _open(self, provider):
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.destroy()
        self.dialog = SignInDialog(self, provider, self.names[provider], self._used,
                                   connected=bool(self.connected.get(provider)),
                                   on_signed_in=self.refresh)

    def _used(self, provider, model):
        self.on_use(provider, model)

    def _disconnect(self, provider):
        name = self.names[provider]
        if self.active_account() == provider:
            self.note.configure(text=t("accounts.disconnect_in_use", name=name))
            return
        core.disconnect(provider)
        self.note.configure(text=t("accounts.disconnected", name=name))
        self.refresh()


class _Start:
    """One sign-in start. The core starts its poller before it returns the
    session, so a cancel that comes earlier is remembered and applied (on the
    worker thread) the moment the session is known; never touches Tk."""

    def __init__(self, provider):
        self.provider, self.lock = provider, threading.Lock()
        self.cancelled, self.session = False, None

    def run(self):
        result = core.start_sign_in(self.provider)
        with self.lock:
            self.session = result.get("session")
            cancel_now = self.cancelled and self.session
        if cancel_now:
            core.cancel(self.session)
        return result

    def cancel(self):
        with self.lock:
            self.cancelled, session = True, self.session
        if session:
            core.cancel(session)


class SignInDialog(tk.Toplevel):
    """Sign-in (address, code, live countdown, Cancel), then the model to use.
    connected=True skips straight to the model choice."""

    def __init__(self, parent, provider, name, on_use, connected=False, on_signed_in=None,
                 now=time.monotonic):
        super().__init__(parent)
        self.provider, self.name, self.on_use = provider, name, on_use
        self.on_signed_in, self.now = on_signed_in, now
        self.session = None
        self.state = ""
        self._signing_in = None     # the _Start whose sign-in may still be pending
        self._tick_id = None
        self._worker = _Worker(self)
        _toplevel(self, parent, name, 520, 340)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.body = tk.Frame(self, bg=C["bg_main"], padx=24, pady=20)
        self.body.pack(fill="both", expand=True)
        if connected:
            self._show_models(t("accounts.connected"))
        else:
            self.start()

    # -- life cycle -----------------------------------------------------------
    def destroy(self):
        """Every exit path: timers stop and a running sign-in is cancelled."""
        self._stop_tick()
        self._worker.stop()
        if self._signing_in is not None:    # also before the session is known
            self._signing_in.cancel()
            self._signing_in = None
        self.session = None
        super().destroy()

    def _stop_tick(self):
        if self._tick_id is not None:
            self.after_cancel(self._tick_id)
            self._tick_id = None

    def _clear(self):
        for child in self.body.winfo_children():
            child.destroy()

    def _label(self, text, font=None, fg=None, **pack):
        label = tk.Label(self.body, text=text, font=font or FONTS["body"], fg=fg or C["text_primary"],
                         bg=C["bg_main"], wraplength=S(460), justify="left")
        label.pack(anchor="w", **pack)
        return label

    def _buttons(self, *buttons):
        row = tk.Frame(self.body, bg=C["bg_main"])
        row.pack(side="bottom", fill="x")
        for label, command in buttons:
            ttk.Button(row, text=label, command=command).pack(side="right", padx=(6, 0))

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    # -- sign-in --------------------------------------------------------------
    def start(self):
        self.state = "starting"
        self._clear()
        self._label(t("accounts.starting", name=self.name))
        self._buttons((t("accounts.cancel"), self.destroy))
        self._signing_in = _Start(self.provider)
        self._worker.run(self._signing_in.run, self._started)

    def _started(self, result):
        if not result.get("session"):
            self._signing_in = None
        if result.get("unavailable"):
            return self._show_failed(t("accounts.unavailable", command=result["command"]), retry=False)
        if "error" in result:
            return self._show_failed(t("accounts.failed", error=result["error"]))
        self.session, self.state = result["session"], "waiting"
        self.deadline = self.now() + result["expires_in"]
        self._clear()
        self._label(t("accounts.step_open"), pady=(0, 4))
        link_row = tk.Frame(self.body, bg=C["bg_main"])
        link_row.pack(anchor="w", fill="x")
        link = tk.Label(link_row, text=result["url"], font=SF("Segoe UI", 10, "underline"),
                        fg=C["accent"], bg=C["bg_main"], cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e: webbrowser.open(result["url"]))
        ttk.Button(link_row, text=t("accounts.copy"),
                   command=lambda: self._copy(result["url"])).pack(side="left", padx=8)
        self._label(t("accounts.step_code"), pady=(14, 4))
        code_row = tk.Frame(self.body, bg=C["bg_main"])
        code_row.pack(anchor="w", fill="x")
        tk.Label(code_row, text=result["user_code"], font=SF("Consolas", 22, "bold"),
                 fg=C["text_primary"], bg=C["bg_main"]).pack(side="left")
        ttk.Button(code_row, text=t("accounts.copy"),
                   command=lambda: self._copy(result["user_code"])).pack(side="left", padx=12)
        self.waiting = self._label("", font=FONTS["small"], fg=C["text_hint"], pady=(14, 0))
        self._buttons((t("accounts.cancel"), self.destroy))
        webbrowser.open(result["url"])
        self._tick()

    def _tick(self):
        """Once a second: the countdown, then the core's session state."""
        self._tick_id = None
        left = max(0.0, self.deadline - self.now())
        self.waiting.configure(text=t("accounts.waiting", time=clock(left)))
        state, message = core.poll(self.session)
        if state == "pending" and left <= 0:
            core.cancel(self.session)
            state = "expired"
        if state == "pending":
            self._tick_id = self.after(1000, self._tick)
            return
        self.state, self.session, self._signing_in = state, None, None
        if state == "approved":
            if self.on_signed_in:
                self.on_signed_in()
            return self._show_models(t("accounts.approved", name=self.name))
        if state == "cancelled":
            return self.destroy()
        key = {"denied": "accounts.denied", "expired": "accounts.expired"}.get(state)
        self._show_failed(t(key) if key else t("accounts.failed", error=message or state))

    def _show_failed(self, text, retry=True):
        self.state = "failed"
        self._clear()
        self._label(text, fg=C["warning"])
        buttons = [(t("accounts.close"), self.destroy)]
        if retry:
            buttons.append((t("accounts.try_again"), self.start))
        self._buttons(*buttons)

    # -- the model to use -----------------------------------------------------
    def _show_models(self, heading):
        self.state = "models"
        self._clear()
        self._label(heading, fg=C["success"], pady=(0, 12))
        self._label(t("accounts.loading_models"), font=FONTS["small"], fg=C["text_hint"])
        self._buttons((t("accounts.close"), self.destroy))
        self._worker.run(lambda: self._load_models(self.provider), self._models_loaded)

    @staticmethod
    def _load_models(provider):
        ids = core.models(provider)
        return ids, core.default_model(provider, ids)

    def _models_loaded(self, result):
        ids, default = result
        self._clear()
        if not ids:
            self._label(t("accounts.no_models"), fg=C["warning"])
            self._buttons((t("accounts.close"), self.destroy),
                          (t("accounts.try_again"), lambda: self._show_models("")))
            return
        self._label(t("accounts.use_for_chat", name=core.short_name(self.provider)), pady=(0, 6))
        self.model_var = tk.StringVar(value=default or ids[0])
        ttk.Combobox(self.body, textvariable=self.model_var, values=ids, state="readonly",
                     font=FONTS["small"]).pack(anchor="w", fill="x")
        self._buttons((t("accounts.close"), self.destroy), (t("accounts.use_button"), self._use))

    def _use(self):
        provider, model = self.provider, self.model_var.get()
        self.destroy()
        self.on_use(provider, model)
