"""
Unit tests for gui.i18n - multi-language support and headless CI compatibility.
"""
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gui import i18n
from gui.i18n import (
    t,
    get_language,
    set_language,
    register_listener,
    unregister_listener,
    TRANSLATIONS,
    SUPPORTED_LANGUAGES,
)


class TestGuiI18n(unittest.TestCase):

    def setUp(self):
        self.prev_lang = os.environ.get("HERMES_LANGUAGE")

    def tearDown(self):
        if self.prev_lang is not None:
            os.environ["HERMES_LANGUAGE"] = self.prev_lang
            set_language(self.prev_lang, persist=False)
        else:
            os.environ.pop("HERMES_LANGUAGE", None)

    def test_catalog_keys_parity(self):
        """Every supported language must have the exact same set of translation keys as English."""
        en_keys = set(TRANSLATIONS["en"].keys())
        for lang_code, lang_name in SUPPORTED_LANGUAGES:
            if lang_code == "en":
                continue
            lang_keys = set(TRANSLATIONS[lang_code].keys())
            missing = en_keys - lang_keys
            extra = lang_keys - en_keys
            self.assertFalse(missing, f"Language '{lang_code}' is missing keys: {missing}")
            self.assertFalse(extra, f"Language '{lang_code}' has extra keys: {extra}")

    def test_language_switching(self):
        """Test switching between Traditional Chinese, Simplified Chinese, and English."""
        # 1. Traditional Chinese
        set_language("zh-hant", persist=False)
        self.assertEqual(get_language(), "zh-hant")
        self.assertIn("便攜版", t("app.title"))
        self.assertEqual(t("sidebar.new_chat"), "+ 新對話")
        self.assertEqual(t("chat.send"), "發送")
        self.assertEqual(t("status.ready"), "就緒")

        # 2. Simplified Chinese
        set_language("zh", persist=False)
        self.assertEqual(get_language(), "zh")
        self.assertIn("便携版", t("app.title"))
        self.assertEqual(t("sidebar.new_chat"), "+ 新建对话")
        self.assertEqual(t("chat.send"), "发送")
        self.assertEqual(t("status.ready"), "就绪")

        # 3. English
        set_language("en", persist=False)
        self.assertEqual(get_language(), "en")
        self.assertEqual(t("app.title"), "Portable Hermes Agent")
        self.assertEqual(t("sidebar.new_chat"), "+ New Chat")
        self.assertEqual(t("chat.send"), "Send")
        self.assertEqual(t("status.ready"), "Ready")

    def test_formatting(self):
        """Test string formatting interpolation with format_kwargs."""
        set_language("zh-hant", persist=False)
        msg = t("chat.tool", name="read_file")
        self.assertEqual(msg, "工具: read_file")

        set_language("en", persist=False)
        msg_en = t("chat.tool", name="read_file")
        self.assertEqual(msg_en, "Tool: read_file")

    def test_listener_callback(self):
        """Test that registered listeners are called when language changes."""
        changes = []

        def on_change(lang):
            changes.append(lang)

        register_listener(on_change)
        try:
            set_language("zh-hant", persist=False)
            set_language("zh", persist=False)
            set_language("en", persist=False)
            self.assertEqual(changes, ["zh-hant", "zh", "en"])
        finally:
            unregister_listener(on_change)

    def test_fallback_behavior(self):
        """Test fallback when key does not exist."""
        self.assertEqual(t("non_existent_key_12345"), "non_existent_key_12345")
        self.assertEqual(t("non_existent_key_12345", default="Default Val"), "Default Val")

    def test_wizard_translations(self):
        """Verify API key setup wizard translations across all supported languages."""
        set_language("zh-hant", persist=False)
        self.assertEqual(t("wizard.status_required"), "必填")
        self.assertIn("需設定 5 項金鑰", t("wizard.keys_to_setup", count=5))
        self.assertEqual(t("wizard.paste_from_clip"), "從剪貼簿貼上")
        self.assertIn("核心大腦", t("wizard.service.openrouter_api_key.what"))

        set_language("zh", persist=False)
        self.assertEqual(t("wizard.status_required"), "必填")
        self.assertIn("需设置 5 项密钥", t("wizard.keys_to_setup", count=5))
        self.assertEqual(t("wizard.paste_from_clip"), "从剪贴板粘贴")

        set_language("en", persist=False)
        self.assertEqual(t("wizard.status_required"), "Required")
        self.assertIn("5 key(s) to set up", t("wizard.keys_to_setup", count=5))
        self.assertEqual(t("wizard.paste_from_clip"), "Paste from Clipboard")


if __name__ == "__main__":
    unittest.main()
