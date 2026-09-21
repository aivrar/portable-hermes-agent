"""Exercise real localization controls and the LM Studio connect boundary."""
import types
from unittest.mock import Mock
try:
    import pytest
except ImportError:
    import unittest
    raise unittest.SkipTest("pytest is not installed in current python environment")

def _has_display():
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_display(), reason="requires a Tk display")
def test_real_app_menu_and_settings_language_switch(monkeypatch):
    import tkinter as tk
    import gui.app as app
    from gui.i18n import set_language, t, _listeners

    # Keep real widgets and application methods; isolate model/network boundaries.
    monkeypatch.setattr(tk.Tk, "deiconify", lambda self: None)
    monkeypatch.setattr(app.Sidebar, "refresh_models", lambda self: None)
    monkeypatch.setattr(app.Sidebar, "_load_sessions", lambda self: None)
    monkeypatch.setattr(app, "get_missing_keys", lambda: [])
    bridge = Mock()
    bridge.get_model.return_value = "google/gemini-2.5-flash"
    bridge._is_local_model.return_value = False
    bridge._is_model_configured.return_value = False
    bridge._startup_fallback = False
    bridge.is_running = False
    monkeypatch.setattr(app, "AgentBridge", lambda *a, **kw: bridge)
    set_language("en", persist=False)
    gui = app.HermesGUI()
    gui.root.withdraw()
    errors = []
    gui.root.report_callback_exception = lambda *args: errors.append(args)
    try:
        gui.status_bar.set_tool("read_file")
        for language in ("zh-hant", "zh", "en"):
            gui._switch_language(language)
            gui.root.update()
            assert gui.send_btn.cget("text") == t("chat.send")
            assert gui.attach_btn.cget("text") == t("chat.attach")
            assert gui.stop_btn.cget("text") == t("chat.stop")
            assert gui.status_bar._state_kind == "tool"
            assert gui.status_bar.status_lbl.cget("text") == t("status.tool_calling", tool="read_file")
        dlg = app.SettingsDialog(gui.root, bridge)
        dlg.withdraw()
        dlg.lang_var.set(dict(app.SUPPORTED_LANGUAGES)["zh-hant"])
        dlg._save()
        gui.root.update()
        assert gui.send_btn.cget("text") == t("chat.send")
        assert gui.root.title() == t("app.title")
        assert not errors
    finally:
        gui._on_close()
    assert gui._on_language_changed not in _listeners


def test_lmstudio_connect_action_starts_one_connection(monkeypatch):
    import gui.lm_studio as lm
    monkeypatch.setattr(lm, "LMStudioClient", Mock())
    monkeypatch.setattr(lm, "_write_lmstudio_config", Mock(return_value=True))
    panel = types.SimpleNamespace(
        _ep_var=Mock(get=lambda: "http://localhost:1234"),
        _key_var=Mock(get=lambda: ""),
        status_dot=Mock(), status_lbl=Mock(), _connect=Mock(),
    )
    lm.LMStudioPanel._apply_endpoint(panel)
    assert panel._connect.call_count == 1


@pytest.mark.skipif(not _has_display(), reason="requires a Tk display")
def test_lmstudio_panel_keeps_event_loop_responsive(monkeypatch):
    import time
    import tkinter as tk
    from gui import lm_studio as lm
    root = tk.Tk()
    root.withdraw()
    errors, heartbeats = [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr(lm, "get_available_gpus", lambda: ["CPU"])
    monkeypatch.setattr(lm, "HAS_SDK", False)
    def slow_probe(self):
        time.sleep(0.4)
        return True
    monkeypatch.setattr(lm.LMStudioClient, "is_running", slow_probe)
    monkeypatch.setattr(lm.LMStudioClient, "list_models_api", lambda self: [
        {"id": "test/model", "context_length": 4096, "state": "loaded"}])
    panel = lm.LMStudioPanel(root)
    panel.withdraw()
    root.after(200, lambda: heartbeats.append(panel.model_list.size()))
    root.after(1000, root.quit)
    try:
        root.mainloop()
        assert heartbeats == [0], "Tk must respond while the network probe is pending"
        assert panel.model_list.size() == 1
        assert not errors
    finally:
        root.destroy()
