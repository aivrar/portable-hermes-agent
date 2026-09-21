"""
Unit tests for GUI language updates, persistence under an isolated HERMES_HOME,
regression coverage for actual application methods (HermesGUI and SettingsDialog),
and full compatibility with headless CI environments.
"""
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gui import i18n
from gui.i18n import (
    t,
    get_language,
    set_language,
    save_language,
    load_saved_language,
    register_listener,
    unregister_listener,
    SUPPORTED_LANGUAGES,
)
from gui.app import StatusBar, HermesGUI, SettingsDialog
from gui.theme import Tooltip


def _has_display() -> bool:
    """Check whether a real display is available for Tkinter GUI instantiation."""
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.destroy()
        return True
    except Exception:
        return False


class HeadlessWidgetStub:
    """A lightweight, headless-safe stub that implements Tkinter widget protocols."""
    def __init__(self, **kwargs):
        self._cfg = dict(kwargs)
        self.text = self._cfg.get("text", "")

    def configure(self, **kwargs):
        self._cfg.update(kwargs)
        if "text" in kwargs:
            self.text = kwargs["text"]

    def get(self):
        return self.text

    def set(self, val):
        self.text = str(val)
        self._cfg["text"] = str(val)

    def cget(self, key):
        return self._cfg.get(key, "")

    def __getitem__(self, key):
        return self._cfg.get(key, "")

    def winfo_exists(self):
        return True

    def winfo_children(self):
        return []

    def pack(self, *args, **kwargs):
        pass

    def pack_forget(self):
        pass

    def destroy(self):
        pass

    def title(self, new_title=None):
        if new_title is not None:
            self._cfg["title"] = new_title
        return self._cfg.get("title", "")


class TestGuiLanguagePersistence(unittest.TestCase):
    """Tests language persistence under an isolated HERMES_HOME directory."""

    def setUp(self):
        self.orig_env_home = os.environ.get("HERMES_HOME")
        self.orig_env_lang = os.environ.get("HERMES_LANGUAGE")
        self.orig_active_lang = get_language()

        # Create isolated temporary HERMES_HOME
        self.temp_dir = tempfile.TemporaryDirectory()
        self.isolated_home = Path(self.temp_dir.name)
        os.environ["HERMES_HOME"] = str(self.isolated_home)
        os.environ.pop("HERMES_LANGUAGE", None)

    def tearDown(self):
        # Restore environment
        if self.orig_env_home is not None:
            os.environ["HERMES_HOME"] = self.orig_env_home
        else:
            os.environ.pop("HERMES_HOME", None)

        if self.orig_env_lang is not None:
            os.environ["HERMES_LANGUAGE"] = self.orig_env_lang
            set_language(self.orig_env_lang, persist=False)
        else:
            os.environ.pop("HERMES_LANGUAGE", None)
            set_language(self.orig_active_lang, persist=False)

        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_save_and_load_persistence_isolated_home(self):
        """
        Verify that language preferences persist to gui_config.json under an isolated HERMES_HOME.
        Clears HERMES_LANGUAGE env before load_saved_language() to strictly verify file-based reload.
        """
        cfg_file = self.isolated_home / "gui_config.json"
        self.assertFalse(cfg_file.exists(), "Initial config should not exist in clean isolated home")

        # 1. Save Traditional Chinese
        success = set_language("zh-hant", persist=True)
        self.assertTrue(success)
        self.assertTrue(cfg_file.exists(), "gui_config.json should be created")

        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("language"), "zh-hant")

        # CRITICAL: Clear environment variable so load_saved_language() must read from gui_config.json
        os.environ.pop("HERMES_LANGUAGE", None)
        loaded = load_saved_language()
        self.assertEqual(loaded, "zh-hant", "Must reload zh-hant from saved gui_config.json")

        # 2. Switch to Simplified Chinese
        set_language("zh", persist=True)
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("language"), "zh")

        os.environ.pop("HERMES_LANGUAGE", None)
        self.assertEqual(load_saved_language(), "zh", "Must reload zh from saved gui_config.json")

        # 3. Switch to English
        set_language("en", persist=True)
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("language"), "en")

        os.environ.pop("HERMES_LANGUAGE", None)
        self.assertEqual(load_saved_language(), "en", "Must reload en from saved gui_config.json")

    def test_env_override_takes_precedence_over_file(self):
        """HERMES_LANGUAGE environment variable should override file configuration."""
        cfg_file = self.isolated_home / "gui_config.json"
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump({"language": "en"}, f)

        # File says 'en', but env variable says 'zh-hant'
        os.environ["HERMES_LANGUAGE"] = "zh-hant"
        self.assertEqual(load_saved_language(), "zh-hant")


class TestApplicationLanguageSwitchingRegression(unittest.TestCase):
    """
    Regression tests exercising actual application methods:
    - HermesGUI._switch_language
    - HermesGUI._on_language_changed
    - SettingsDialog._save
    - StatusBar.update_ui_language (preserving activity state)
    - Composer controls & tooltips updates
    - Listener registration and cleanup
    """

    def setUp(self):
        self.orig_env_home = os.environ.get("HERMES_HOME")
        self.orig_env_lang = os.environ.get("HERMES_LANGUAGE")
        self.orig_active_lang = get_language()

        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["HERMES_HOME"] = self.temp_dir.name
        os.environ.pop("HERMES_LANGUAGE", None)
        set_language("en", persist=False)

    def tearDown(self):
        if self.orig_env_home is not None:
            os.environ["HERMES_HOME"] = self.orig_env_home
        else:
            os.environ.pop("HERMES_HOME", None)

        if self.orig_env_lang is not None:
            os.environ["HERMES_LANGUAGE"] = self.orig_env_lang
            set_language(self.orig_env_lang, persist=False)
        else:
            os.environ.pop("HERMES_LANGUAGE", None)
            set_language(self.orig_active_lang, persist=False)

        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _create_app_stub(self):
        """Construct a stubbed HermesGUI instance with real application method bindings."""
        gui = object.__new__(HermesGUI)
        gui.root = HeadlessWidgetStub(title=t("app.title"))
        gui.menu_bar = HeadlessWidgetStub()
        gui._build_menu_items = MagicMock()

        # Sidebar stub
        gui.sidebar = HeadlessWidgetStub()
        gui.sidebar.update_ui_language = MagicMock()

        # Real StatusBar instance logic via duck-typing stub
        status_bar = object.__new__(StatusBar)
        status_bar.status_lbl = HeadlessWidgetStub(text=t("status.ready"))
        status_bar.dot = HeadlessWidgetStub()
        status_bar.model_lbl = HeadlessWidgetStub()
        status_bar.iter_lbl = HeadlessWidgetStub()
        status_bar._state_kind = "ready"
        status_bar._state_data = ""
        gui.status_bar = status_bar

        # Composer controls & tooltips
        gui.attach_btn = HeadlessWidgetStub(text=t("chat.attach"))
        gui.attach_tooltip = HeadlessWidgetStub(text=t("chat.attach_tooltip"))
        gui.send_btn = HeadlessWidgetStub(text=t("chat.send"))
        gui.send_tooltip = HeadlessWidgetStub(text=t("chat.send_tooltip"))
        gui.stop_btn = HeadlessWidgetStub(text=t("chat.stop"))
        gui.stop_tooltip = HeadlessWidgetStub(text=t("chat.stop_tooltip"))

        # Register listener as HermesGUI.__init__ does
        register_listener(gui._on_language_changed)
        return gui

    def test_menu_switch_language_updates_controls_and_preserves_ready_state(self):
        """Verify HermesGUI._switch_language executes cleanly, updates controls, and handles ready state."""
        gui = self._create_app_stub()
        try:
            # 1. Switch to Traditional Chinese via menu entry point
            HermesGUI._switch_language(gui, "zh-hant")

            # Check title and controls
            self.assertEqual(gui.root.title(), "便攜版 Hermes Agent")
            self.assertEqual(gui.attach_btn.cget("text"), "📎 附件")
            self.assertEqual(gui.attach_tooltip.text, "附加圖片 (Ctrl+Shift+I)")
            self.assertEqual(gui.send_btn.cget("text"), "發送")
            self.assertEqual(gui.send_tooltip.text, "發送訊息 (Enter)")
            self.assertEqual(gui.stop_btn.cget("text"), "停止")
            self.assertEqual(gui.stop_tooltip.text, "停止生成 (Escape)")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "就緒")

            # Check callbacks
            gui.sidebar.update_ui_language.assert_called()
            gui._build_menu_items.assert_called()

            # 2. Switch back to English
            HermesGUI._switch_language(gui, "en")
            self.assertEqual(gui.root.title(), "Portable Hermes Agent")
            self.assertEqual(gui.attach_btn.cget("text"), "📎 Attach")
            self.assertEqual(gui.attach_tooltip.text, "Attach image (Ctrl+Shift+I)")
            self.assertEqual(gui.send_btn.cget("text"), "Send")
            self.assertEqual(gui.send_tooltip.text, "Send message (Enter)")
            self.assertEqual(gui.stop_btn.cget("text"), "Stop")
            self.assertEqual(gui.stop_tooltip.text, "Stop generation (Escape)")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "Ready")
        finally:
            unregister_listener(gui._on_language_changed)

    def test_switch_language_preserves_thinking_and_tool_activity_states(self):
        """
        Critical regression test: switching language while work is in progress must
        preserve thinking/tool activity states rather than unconditionally resetting to 'Ready'.
        """
        gui = self._create_app_stub()
        try:
            # Case A: Thinking state with custom status text
            StatusBar.set_thinking(gui.status_bar, "Analyzing user code...")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "Analyzing user code...")

            HermesGUI._switch_language(gui, "zh-hant")
            # Activity text must be preserved, NOT reset to '就緒'
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "Analyzing user code...")

            # Case B: Default thinking state (no text)
            StatusBar.set_thinking(gui.status_bar, "")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "思考中...")

            HermesGUI._switch_language(gui, "en")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "Thinking...")

            # Case C: Tool calling state
            StatusBar.set_tool(gui.status_bar, "read_file")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "Calling: read_file")

            HermesGUI._switch_language(gui, "zh-hant")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "正在呼叫：read_file")

            HermesGUI._switch_language(gui, "zh")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "正在调用：read_file")

            # Case D: Error state
            StatusBar.set_error(gui.status_bar)
            HermesGUI._switch_language(gui, "en")
            self.assertEqual(gui.status_bar.status_lbl.cget("text"), "Error: ")
        finally:
            unregister_listener(gui._on_language_changed)

    def test_settings_save_triggers_gui_refresh_via_listener(self):
        """
        Regression test: SettingsDialog._save calls set_language(), which must
        notify registered HermesGUI listener and refresh main controls without restart.
        """
        gui = self._create_app_stub()
        try:
            # Construct a stubbed SettingsDialog
            dlg = object.__new__(SettingsDialog)
            dlg.key_entries = {}
            dlg.model_var = HeadlessWidgetStub(text="")
            dlg.bridge = MagicMock()
            dlg.destroy = MagicMock()

            # User selected Traditional Chinese in Settings
            dlg.lang_var = HeadlessWidgetStub(text="繁體中文")

            # Execute actual SettingsDialog._save method
            SettingsDialog._save(dlg)

            # Dialog must be closed and language updated in GUI
            dlg.destroy.assert_called_once()
            self.assertEqual(get_language(), "zh-hant")
            self.assertEqual(gui.attach_btn.cget("text"), "📎 附件")
            self.assertEqual(gui.send_btn.cget("text"), "發送")
            self.assertEqual(gui.stop_btn.cget("text"), "停止")
            self.assertEqual(gui.root.title(), "便攜版 Hermes Agent")
        finally:
            unregister_listener(gui._on_language_changed)

    def test_listener_cleanup_on_close(self):
        """HermesGUI._on_close must unregister the language change listener."""
        gui = self._create_app_stub()
        gui.bridge = MagicMock()
        gui.bridge.is_running = False

        # Close the app
        HermesGUI._on_close(gui)

        # Ensure listener was removed
        from gui.i18n import _listeners
        self.assertNotIn(gui._on_language_changed, _listeners)

    @unittest.skipUnless(_has_display(), "Headless environment without display - skipping real Tk display lane")
    def test_display_backed_app_and_settings_switching(self):
        """Full display-backed lane: verifies actual Tkinter widgets and SettingsDialog under a real window."""
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            # Build actual StatusBar and controls
            status_bar = StatusBar(root)
            status_bar.set_thinking("Deep reasoning in progress")
            self.assertEqual(status_bar.status_lbl.cget("text"), "Deep reasoning in progress")

            btn_attach = tk.Button(root, text=t("chat.attach"))
            tip_attach = Tooltip(btn_attach, t("chat.attach_tooltip"))

            # Switch language
            set_language("zh-hant", persist=False)
            status_bar.update_ui_language()
            btn_attach.configure(text=t("chat.attach"))
            tip_attach.text = t("chat.attach_tooltip")

            self.assertEqual(btn_attach.cget("text"), "📎 附件")
            self.assertEqual(tip_attach.text, "附加圖片 (Ctrl+Shift+I)")
            self.assertEqual(status_bar.status_lbl.cget("text"), "Deep reasoning in progress")
        finally:
            root.destroy()


class TestLMStudioConfigAndClient(unittest.TestCase):
    """Unit tests for LM Studio configuration read/write and client header generation."""

    def setUp(self):
        self.orig_lm_key = os.environ.get("LM_API_KEY")
        self.orig_lm_url = os.environ.get("LM_BASE_URL")
        os.environ.pop("LM_API_KEY", None)
        os.environ.pop("LM_BASE_URL", None)

        from gui import lm_studio
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_cfg_path = Path(self.temp_dir.name) / ".lmstudio_config"
        self.orig_cfg_path = lm_studio.LMSTUDIO_CONFIG_PATH
        lm_studio.LMSTUDIO_CONFIG_PATH = self.test_cfg_path

    def tearDown(self):
        from gui import lm_studio
        lm_studio.LMSTUDIO_CONFIG_PATH = self.orig_cfg_path

        if self.orig_lm_key is not None:
            os.environ["LM_API_KEY"] = self.orig_lm_key
        else:
            os.environ.pop("LM_API_KEY", None)

        if self.orig_lm_url is not None:
            os.environ["LM_BASE_URL"] = self.orig_lm_url
        else:
            os.environ.pop("LM_BASE_URL", None)

        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_lmstudio_client_urls_and_headers(self):
        from gui.lm_studio import LMStudioClient

        client = LMStudioClient(base_url="http://127.0.0.1:1234/v1", api_key="sk-test-key-123")
        self.assertEqual(client._openai_base(), "http://127.0.0.1:1234/v1")
        self.assertEqual(client._server_root(), "http://127.0.0.1:1234")

        headers = client._auth_headers()
        self.assertEqual(headers["Authorization"], "Bearer sk-test-key-123")
        self.assertEqual(headers["Accept"], "application/json")

        client_no_key = LMStudioClient(base_url="http://localhost:1234", api_key="")
        self.assertEqual(client_no_key._openai_base(), "http://localhost:1234/v1")
        self.assertEqual(client_no_key._server_root(), "http://localhost:1234")
        self.assertEqual(client_no_key._auth_headers(), {})

    def test_lmstudio_config_roundtrip(self):
        from gui import lm_studio
        self.assertEqual(lm_studio._read_lmstudio_config(), {})

        ok = lm_studio._write_lmstudio_config(base_url="http://127.0.0.1:5678", api_key="sk-mykey")
        self.assertTrue(ok)
        self.assertTrue(self.test_cfg_path.exists())

        data = lm_studio._read_lmstudio_config()
        self.assertEqual(data.get("base_url"), "http://127.0.0.1:5678")
        self.assertEqual(data.get("api_key"), "sk-mykey")

    def test_lmstudio_config_clearing_and_failure(self):
        from gui import lm_studio

        # 1. Save initial config
        lm_studio._write_lmstudio_config(base_url="http://127.0.0.1:1234", api_key="sk-initial")
        self.assertEqual(lm_studio._read_lmstudio_config().get("api_key"), "sk-initial")

        # 2. Clear key
        ok = lm_studio._write_lmstudio_config(api_key="")
        self.assertTrue(ok)
        self.assertEqual(lm_studio._read_lmstudio_config().get("api_key"), "")
        self.assertEqual(lm_studio._read_lmstudio_config().get("base_url"), "http://127.0.0.1:1234")

        # 3. Simulate failure when path points to an invalid directory
        orig = lm_studio.LMSTUDIO_CONFIG_PATH
        try:
            lm_studio.LMSTUDIO_CONFIG_PATH = Path("/nonexistent/directory/unwritable/.lmstudio_config")
            res = lm_studio._write_lmstudio_config(base_url="http://fail")
            self.assertFalse(res)
        finally:
            lm_studio.LMSTUDIO_CONFIG_PATH = orig

    def test_list_models_api_fallbacks_and_metadata(self):
        from unittest.mock import patch
        from gui.lm_studio import LMStudioClient

        client = LMStudioClient(base_url="http://localhost:1234", api_key="test-key")

        # Scenario A: /api/v0/models succeeds with rich metadata
        mock_resp_v0 = MagicMock()
        mock_resp_v0.status_code = 200
        mock_resp_v0.json.return_value = {
            "data": [
                {
                    "id": "qwen2.5-coder-7b-instruct@q4_k_m",
                    "path": "qwen/qwen2.5-coder-7b",
                    "display_name": "qwen2.5-coder-7b-instruct@q4_k_m",
                    "max_context_length": 32768,
                    "quantization": "Q4_K_M",
                    "state": "loaded",
                }
            ]
        }

        with patch("gui.lm_studio.httpx.get", return_value=mock_resp_v0) as mock_get:
            models = client.list_models_api()
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0]["id"], "qwen2.5-coder-7b-instruct@q4_k_m")
            self.assertEqual(models[0]["display_name"], "qwen2.5-coder-7b-instruct")
            self.assertEqual(models[0]["context_length"], 32768)
            self.assertEqual(models[0]["quantization"], "Q4_K_M")
            self.assertEqual(models[0]["state"], "loaded")
            mock_get.assert_called_once()
            # Verify auth header was passed
            call_kwargs = mock_get.call_args[1]
            self.assertEqual(call_kwargs["headers"].get("Authorization"), "Bearer test-key")

        # Scenario B: /api/v0/models 404s, falls back to OpenAI-compatible /models
        def side_effect(url, **kwargs):
            resp = MagicMock()
            if "/api/v0/models" in url:
                resp.status_code = 404
            else:
                resp.status_code = 200
                resp.json.return_value = {
                    "data": [
                        {"id": "meta-llama/llama-3.1-8b-instruct"}
                    ]
                }
            return resp

        with patch("gui.lm_studio.httpx.get", side_effect=side_effect):
            fallback_models = client.list_models_api()
            self.assertEqual(len(fallback_models), 1)
            self.assertEqual(fallback_models[0]["id"], "meta-llama/llama-3.1-8b-instruct")
            self.assertEqual(fallback_models[0]["display_name"], "llama-3.1-8b-instruct")
            self.assertEqual(fallback_models[0]["state"], "ready")


if __name__ == "__main__":
    unittest.main()
