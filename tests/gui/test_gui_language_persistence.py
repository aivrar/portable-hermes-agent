"""
Unit tests for GUI language updates, persistence under an isolated HERMES_HOME,
and compatibility with headless CI environments.
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
)


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
        """Verify that language preferences persist to gui_config.json under an isolated HERMES_HOME."""
        cfg_file = self.isolated_home / "gui_config.json"
        self.assertFalse(cfg_file.exists(), "Initial config should not exist in clean isolated home")

        # 1. Save Traditional Chinese
        success = set_language("zh-hant", persist=True)
        self.assertTrue(success)
        self.assertTrue(cfg_file.exists(), "gui_config.json should be created")

        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("language"), "zh-hant")

        # Clear active state and verify reload from isolated file
        loaded = load_saved_language()
        self.assertEqual(loaded, "zh-hant")

        # 2. Switch to Simplified Chinese
        set_language("zh", persist=True)
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("language"), "zh")
        self.assertEqual(load_saved_language(), "zh")

        # 3. Switch to English
        set_language("en", persist=True)
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("language"), "en")
        self.assertEqual(load_saved_language(), "en")

    def test_env_override_takes_precedence_over_file(self):
        """HERMES_LANGUAGE environment variable should override file configuration."""
        cfg_file = self.isolated_home / "gui_config.json"
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump({"language": "en"}, f)

        # File says 'en', but env variable says 'zh-hant'
        os.environ["HERMES_LANGUAGE"] = "zh-hant"
        self.assertEqual(load_saved_language(), "zh-hant")

    def test_gui_listener_updates_without_display(self):
        """
        Headless-compatible test: verifies that simulated GUI widgets correctly
        receive language change events and update their text without requiring a real display.
        """
        mock_sidebar_btn = MagicMock()
        mock_status_lbl = MagicMock()

        def on_language_change(lang_code):
            mock_sidebar_btn.configure(text=t("sidebar.new_chat"))
            mock_status_lbl.configure(text=t("status.ready"))

        register_listener(on_language_change)
        try:
            # Switch to Traditional Chinese
            set_language("zh-hant", persist=False)
            mock_sidebar_btn.configure.assert_called_with(text="+ 新對話")
            mock_status_lbl.configure.assert_called_with(text="就緒")

            # Switch to English
            set_language("en", persist=False)
            mock_sidebar_btn.configure.assert_called_with(text="+ New Chat")
            mock_status_lbl.configure.assert_called_with(text="Ready")
        finally:
            unregister_listener(on_language_change)

    @unittest.skipUnless(_has_display(), "Headless environment without display - skipping real Tk widget test")
    def test_real_tk_widgets_on_display_available(self):
        """Test real Tkinter widget updates when an actual display is present."""
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            btn = tk.Button(root, text=t("chat.send"))
            self.assertEqual(btn["text"], t("chat.send"))

            set_language("zh-hant", persist=False)
            btn.configure(text=t("chat.send"))
            self.assertEqual(btn["text"], "發送")

            set_language("en", persist=False)
            btn.configure(text=t("chat.send"))
            self.assertEqual(btn["text"], "Send")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
