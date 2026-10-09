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
        gui.sidebar._show_load_status("sidebar.loading_model")
        for language in ("zh-hant", "zh", "en", "es"):
            gui._switch_language(language)
            gui.root.update()
            assert gui.send_btn.cget("text") == t("chat.send")
            assert gui.attach_btn.cget("text") == t("chat.attach")
            assert gui.stop_btn.cget("text") == t("chat.stop")
            assert gui.status_bar._state_kind == "tool"
            assert gui.status_bar.status_lbl.cget("text") == t("status.tool_calling", tool="read_file")
            assert gui.sidebar._local_header.cget("text") == t("sidebar.local_settings")
            assert gui.sidebar._auto_load_cb.cget("text") == t("sidebar.auto_load")
            assert gui.sidebar.model_combo["values"][0] == gui.sidebar._display_name(gui.sidebar.MODELS[0])
            assert gui.chat_title.cget("text") == t("chat.new_chat_title")
            assert gui.sidebar.session_frame.winfo_children()[0].cget("text") == t("sidebar.no_sessions")
            assert gui.sidebar._load_status_var.get() == t("sidebar.loading_model")
            gui.sidebar._sessions_data = [{"id": "test", "title": "", "preview": "", "model": "", "message_count": 2}]
            gui.sidebar._render_sessions()
            info = gui.sidebar.session_frame.winfo_children()[0].winfo_children()[1]
            assert info.cget("text") == t("sidebar.session_messages", count=2)
            gui.sidebar._sessions_data = []
            gui.sidebar._render_sessions()
            gui.status_bar.set_iter(3)
            assert gui.status_bar.iter_lbl.cget("text") == t("status.step", count=3)
            gui.status_bar.set_tokens(1234)
            assert gui.status_bar.iter_lbl.cget("text") == t("chat.token_count", count="1,234")
        dlg = app.SettingsDialog(gui.root, bridge)
        dlg.withdraw()
        dlg.lang_var.set(dict(app.SUPPORTED_LANGUAGES)["es"])
        dlg._save()
        gui.root.update()
        assert gui.send_btn.cget("text") == t("chat.send")
        assert gui.root.title() == t("app.title")
        assert not errors
    finally:
        gui._on_close()
    assert gui._on_language_changed not in _listeners


@pytest.mark.skipif(not _has_display(), reason="requires a Tk display")
def test_open_secondary_panels_retranslate_without_losing_model_selection(monkeypatch):
    import os
    import tkinter as tk
    from gui import lm_studio as lm, extensions as ext
    from gui.app import SkillsBrowser
    from gui.i18n import get_language, set_language, t, _listeners

    old_lang, old_env = get_language(), os.environ.get("HERMES_LANGUAGE")
    monkeypatch.setattr(lm.LMStudioPanel, "_resolve_base_url", staticmethod(lambda: "http://localhost:1234/v1"))
    monkeypatch.setattr(lm.LMStudioPanel, "_resolve_api_key", staticmethod(lambda: ""))
    monkeypatch.setattr(lm.LMStudioPanel, "_connect", lambda self: None)
    monkeypatch.setattr(lm, "get_available_gpus", lambda: ["CPU"])
    monkeypatch.setattr(ext, "get_extension_status", lambda: {})
    monkeypatch.setattr(SkillsBrowser, "_load", lambda self: None)
    warning = Mock()
    confirm = Mock(return_value=False)
    monkeypatch.setattr(lm.messagebox, "showwarning", warning)
    monkeypatch.setattr(ext.messagebox, "askyesno", confirm)
    root = tk.Tk()
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    set_language("en", persist=False)
    panel = manager = skills = None
    try:
        panel = lm.LMStudioPanel(root)
        panel.withdraw()
        panel._display_models([{"id": "sample/model", "state": "loaded", "context_length": 4096}])
        panel.model_list.selection_set(0)
        panel._set_status("lmstudio.loading_model", model="sample/model")
        manager = ext.ExtensionsManager(root)
        manager.withdraw()
        manager._show_progress("extensions.cloning", "music-server")
        skills = SkillsBrowser(root)
        skills.withdraw()
        skills._set(t("skills.no_dir"), key="skills.no_dir")
        for language in ("es", "zh", "zh-hant", "en"):
            set_language(language, persist=False)
            root.update()
            assert panel.title() == t("lmstudio.title")
            assert panel.status_lbl.cget("text") == t("lmstudio.loading_model", model="sample/model")
            assert panel.model_list.curselection() == (0,)
            assert panel.model_list.get(0).startswith(t("lmstudio.loaded_tag"))
            panel._load_model()
            assert warning.call_args.args == (
                t("lmstudio.context_too_small_title"),
                t("lmstudio.context_too_small_msg", supported="4,096",
                  required=f"{lm.MINIMUM_CONTEXT_LENGTH:,}"),
            )
            assert manager.title() == t("extensions.title")
            assert manager._subtitle.cget("text") == t("extensions.subtitle")
            assert manager._progress_label.cget("text") == t("extensions.cloning", name=t("extensions.music-server.name"))
            manager._install("music-server")
            assert confirm.call_args.args[0] == t("extensions.confirm_title")
            assert skills.title() == t("skills.title")
            assert skills._heading.cget("text") == t("skills.heading")
            assert skills.text.get("1.0", "end-1c") == t("skills.no_dir")
        assert not errors
    finally:
        if panel is not None:
            panel.destroy()
        if manager is not None:
            manager.destroy()
        if skills is not None:
            skills.destroy()
        root.destroy()
        set_language(old_lang, persist=False)
        if old_env is None:
            os.environ.pop("HERMES_LANGUAGE", None)
        else:
            os.environ["HERMES_LANGUAGE"] = old_env
    assert panel.update_ui_language not in _listeners
    assert manager.update_ui_language not in _listeners
    assert skills.update_ui_language not in _listeners


def test_lmstudio_connect_action_starts_one_connection(monkeypatch):
    import gui.lm_studio as lm
    monkeypatch.setattr(lm, "LMStudioClient", Mock())
    monkeypatch.setattr(lm, "_write_lmstudio_config", Mock(return_value=True))
    panel = types.SimpleNamespace(
        _ep_var=Mock(get=lambda: "http://localhost:1234"),
        _key_var=Mock(get=lambda: ""),
        status_dot=Mock(), status_lbl=Mock(), _connect=Mock(), _set_status=Mock(),
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
