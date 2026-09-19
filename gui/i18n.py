"""
Hermes Agent - GUI Internationalization (i18n)
Supports Traditional Chinese (zh-hant), Simplified Chinese (zh), and English (en).
Provides runtime language switching with automatic persistence under HERMES_HOME.
"""
from __future__ import annotations

import os
import locale
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES: List[Tuple[str, str]] = [
    ("zh-hant", "繁體中文"),
    ("zh", "简体中文"),
    ("en", "English"),
]

LANGUAGE_CODES = [code for code, _ in SUPPORTED_LANGUAGES]
DEFAULT_LANGUAGE = "en"

# Translation dictionary
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # App & Window
        "app.title": "Portable Hermes Agent",
        "app.exit_confirm": "Agent is still running. Exit anyway?",

        # Menu bar
        "menu.file": "File",
        "menu.view": "View",
        "menu.language": "Language",
        "menu.help": "Help",
        "menu.new_chat": "New Chat",
        "menu.api_setup": "API Key Setup",
        "menu.permissions": "Permissions",
        "menu.settings": "Settings",
        "menu.exit": "Exit",
        "menu.lm_studio": "LM Studio (Local Models)",
        "menu.skills": "Skills Browser",
        "menu.extensions": "Extensions",
        "menu.toggle_sidebar": "Toggle Sidebar",
        "menu.about": "About",

        # Sidebar
        "sidebar.new_chat": "+ New Chat",
        "sidebar.model": "Model:",
        "sidebar.recent_sessions": "Recent Sessions",
        "sidebar.no_sessions": "No recent sessions",
        "sidebar.delete_title": "Delete Session",
        "sidebar.delete_confirm": "Are you sure you want to delete session '{session_id}'?\n\nThis cannot be undone.",
        "sidebar.local_settings": "Local Model Settings",
        "sidebar.gpu_offload": "GPU Offload:",
        "sidebar.context_len": "Context Length:",
        "sidebar.threads": "CPU Threads:",
        "sidebar.temp": "Temperature:",
        "sidebar.loading_model": "Loading model...",
        "sidebar.model_loaded": "Model loaded",
        "sidebar.load_failed": "Failed to load: {error}",

        # Chat Area
        "chat.new_chat_title": "New Chat",
        "chat.attach": "📎 Attach",
        "chat.attach_tooltip": "Attach image (Ctrl+Shift+I)",
        "chat.send": "Send",
        "chat.send_tooltip": "Send message (Enter)",
        "chat.stop": "Stop",
        "chat.stop_tooltip": "Stop generation (Escape)",
        "chat.placeholder": "Type a message... (Enter to send, Shift+Enter for newline)",
        "chat.empty_warning": "Please enter a message first.",
        "chat.running_warning": "Agent is already running. Wait or press Stop.",
        "chat.file_drag_drop": "Drag & drop files here or click Attach",

        # Message Roles & Tool widgets
        "chat.role_user": "You",
        "chat.role_ai": "Hermes",
        "chat.role_tool": "Tool",
        "chat.role_error": "Error",
        "chat.role_system": "System",
        "chat.tool": "Tool: {name}",

        # Status bar
        "status.ready": "Ready",
        "status.running": "Running...",
        "status.thinking": "Thinking...",
        "status.tool_calling": "Calling: {tool}",
        "status.error": "Error: {error}",
        "status.local_connected": "LM Studio Connected",
        "status.local_disconnected": "LM Studio Disconnected",

        # Settings dialog
        "settings.title": "Settings",
        "settings.tab_api": "API Keys",
        "settings.tab_model": "Model",
        "settings.tab_general": "General",
        "settings.language": "Interface Language",
        "settings.save": "Save",
        "settings.cancel": "Cancel",
        "settings.saved_success": "Settings saved successfully.",
        "settings.saved_title": "Settings Saved",
        "settings.restart_hint": "Some changes may require restarting the app.",
        "settings.openrouter_key": "OpenRouter API Key:",
        "settings.default_model": "Default Model:",
        "settings.max_turns": "Max Turns per Conversation:",
        "settings.temperature": "Temperature:",

        # API Key Setup Wizard
        "wizard.title": "API Key Setup Wizard",
        "wizard.welcome_title": "Welcome to Hermes Agent!",
        "wizard.welcome_desc": "Let's set up your API keys so Hermes can think, search the web, and help you get things done.",
        "wizard.welcome_note": "You only need ONE key to get started (OpenRouter is recommended).",
        "wizard.step_of": "Step {current} of {total}",
        "wizard.get_key": "Get Key",
        "wizard.paste_label": "Paste your API key here:",
        "wizard.paste_placeholder": "Paste key here...",
        "wizard.clip_detected": "Key detected from clipboard!",
        "wizard.save_continue": "Save & Continue",
        "wizard.skip": "Skip for now",
        "wizard.back": "Back",
        "wizard.finish": "Finish",
        "wizard.no_key": "No key entered — skipping.",
        "wizard.prefix_hint": "Key usually starts with '{prefix}' — saving anyway.",
        "wizard.saved": "Saved!",
        "wizard.done_title": "Setup Complete!",
        "wizard.done_saved": "{count} API key(s) saved successfully.",
        "wizard.done_none": "No new keys were added.",
        "wizard.status_ready": "Ready",
        "wizard.status_not_set": "Not set",
        "wizard.done_hint": "\nYou can always add more keys later from\nFile > API Key Setup or Settings.",
        "wizard.start_chatting": "Start Chatting!",

        # Permissions Panel
        "permissions.title": "Permissions",
        "permissions.desc": "Control what Hermes Agent is allowed to do on your computer.",
        "permissions.save": "Save Permissions",
        "permissions.cancel": "Cancel",
        "permissions.saved": "Permissions saved successfully.",
        "permissions.level_0": "Disabled",
        "permissions.level_1": "App Only",
        "permissions.level_2": "App + Home",
        "permissions.level_3": "Anywhere",
        "permissions.level_4": "System / Admin",

        # Extensions Dialog
        "extensions.title": "Extensions Manager",
        "extensions.installed_tab": "Installed",
        "extensions.available_tab": "Available",
        "extensions.install_btn": "Install",
        "extensions.uninstall_btn": "Uninstall",
        "extensions.status_installed": "Installed",
        "extensions.status_not_installed": "Not Installed",

        # LM Studio Panel
        "lmstudio.title": "LM Studio Local Models",
        "lmstudio.connect": "Connect",
        "lmstudio.disconnect": "Disconnect",
        "lmstudio.status_running": "Running",
        "lmstudio.status_stopped": "Not Running",
        "lmstudio.refresh": "Refresh Models",
        "lmstudio.load": "Load Model",
        "lmstudio.eject": "Eject Model",

        # About Dialog
        "about.title": "About Portable Hermes Agent",
        "about.version": "Version: {version}",
        "about.description": "Portable, battery-included desktop AI agent for Windows.",
        "about.license": "License: MIT",
    },

    "zh-hant": {
        # App & Window
        "app.title": "便攜版 Hermes Agent",
        "app.exit_confirm": "Agent 仍在執行中。確定要結束嗎？",

        # Menu bar
        "menu.file": "檔案",
        "menu.view": "檢視",
        "menu.language": "語言",
        "menu.help": "說明",
        "menu.new_chat": "新對話",
        "menu.api_setup": "API 金鑰設定",
        "menu.permissions": "權限管理",
        "menu.settings": "設定",
        "menu.exit": "結束",
        "menu.lm_studio": "LM Studio (本地模型)",
        "menu.skills": "技能瀏覽器",
        "menu.extensions": "擴充套件",
        "menu.toggle_sidebar": "切換側邊欄",
        "menu.about": "關於",

        # Sidebar
        "sidebar.new_chat": "+ 新對話",
        "sidebar.model": "模型：",
        "sidebar.recent_sessions": "最近對話",
        "sidebar.no_sessions": "尚無最近對話紀錄",
        "sidebar.delete_title": "刪除對話",
        "sidebar.delete_confirm": "確定要刪除對話「{session_id}」嗎？\n\n此操作無法復原。",
        "sidebar.local_settings": "本地模型設定",
        "sidebar.gpu_offload": "GPU 卸載：",
        "sidebar.context_len": "上下文長度：",
        "sidebar.threads": "CPU 線程數：",
        "sidebar.temp": "溫度值：",
        "sidebar.loading_model": "正在載入模型...",
        "sidebar.model_loaded": "模型載入完成",
        "sidebar.load_failed": "載入失敗：{error}",

        # Chat Area
        "chat.new_chat_title": "新對話",
        "chat.attach": "📎 附件",
        "chat.attach_tooltip": "附加圖片 (Ctrl+Shift+I)",
        "chat.send": "發送",
        "chat.send_tooltip": "發送訊息 (Enter)",
        "chat.stop": "停止",
        "chat.stop_tooltip": "停止生成 (Escape)",
        "chat.placeholder": "輸入訊息...（Enter 發送，Shift+Enter 換行）",
        "chat.empty_warning": "請先輸入訊息。",
        "chat.running_warning": "Agent 正在運作中。請稍候或按停止。",
        "chat.file_drag_drop": "拖放檔案至此處或點擊附件",

        # Message Roles & Tool widgets
        "chat.role_user": "您",
        "chat.role_ai": "Hermes",
        "chat.role_tool": "工具",
        "chat.role_error": "錯誤",
        "chat.role_system": "系統",
        "chat.tool": "工具: {name}",

        # Status bar
        "status.ready": "就緒",
        "status.running": "執行中...",
        "status.thinking": "思考中...",
        "status.tool_calling": "正在呼叫：{tool}",
        "status.error": "錯誤：{error}",
        "status.local_connected": "LM Studio 已連線",
        "status.local_disconnected": "LM Studio 未連線",

        # Settings dialog
        "settings.title": "設定",
        "settings.tab_api": "API 金鑰",
        "settings.tab_model": "模型",
        "settings.tab_general": "一般",
        "settings.language": "介面語言",
        "settings.save": "儲存",
        "settings.cancel": "取消",
        "settings.saved_success": "設定已成功儲存。",
        "settings.saved_title": "設定已儲存",
        "settings.restart_hint": "部分變更可能需要重新啟動應用程式生效。",
        "settings.openrouter_key": "OpenRouter API 金鑰：",
        "settings.default_model": "預設模型：",
        "settings.max_turns": "每輪對話最大輪數：",
        "settings.temperature": "溫度值：",

        # API Key Setup Wizard
        "wizard.title": "API 金鑰設定精靈",
        "wizard.welcome_title": "歡迎使用 Hermes Agent！",
        "wizard.welcome_desc": "讓我們設定您的 API 金鑰，讓 Hermes 可以進行推理思考、搜尋網路並為您工作。",
        "wizard.welcome_note": "您只需設定一組金鑰即可開始（推薦使用 OpenRouter）。",
        "wizard.step_of": "步驟 {current} / {total}",
        "wizard.get_key": "取得金鑰",
        "wizard.paste_label": "請在此貼上您的 API 金鑰：",
        "wizard.paste_placeholder": "在此貼上金鑰...",
        "wizard.clip_detected": "已從剪貼簿偵測到金鑰！",
        "wizard.save_continue": "儲存並繼續",
        "wizard.skip": "暫時略過",
        "wizard.back": "返回",
        "wizard.finish": "完成",
        "wizard.no_key": "未輸入金鑰 — 已略過。",
        "wizard.prefix_hint": "金鑰通常以「{prefix}」開頭 — 仍為您儲存。",
        "wizard.saved": "已儲存！",
        "wizard.done_title": "設定完成！",
        "wizard.done_saved": "已成功儲存 {count} 項 API 金鑰。",
        "wizard.done_none": "本次未新增任何金鑰。",
        "wizard.status_ready": "已就緒",
        "wizard.status_not_set": "未設定",
        "wizard.done_hint": "\n您可以隨時在「檔案 > API 金鑰設定」\n或「設定」中新增或修改金鑰。",
        "wizard.start_chatting": "開始對話！",

        # Permissions Panel
        "permissions.title": "權限設定",
        "permissions.desc": "控制 Hermes Agent 在您電腦上的操作存取權限。",
        "permissions.save": "儲存權限",
        "permissions.cancel": "取消",
        "permissions.saved": "權限設定已成功儲存。",
        "permissions.level_0": "已停用",
        "permissions.level_1": "僅限應用程式目錄",
        "permissions.level_2": "應用程式 + 家目錄",
        "permissions.level_3": "電腦任意位置",
        "permissions.level_4": "系統 / 管理員權限",

        # Extensions Dialog
        "extensions.title": "擴充套件管理",
        "extensions.installed_tab": "已安裝",
        "extensions.available_tab": "可安裝",
        "extensions.install_btn": "安裝",
        "extensions.uninstall_btn": "解除安裝",
        "extensions.status_installed": "已安裝",
        "extensions.status_not_installed": "未安裝",

        # LM Studio Panel
        "lmstudio.title": "LM Studio 本地模型",
        "lmstudio.connect": "連線",
        "lmstudio.disconnect": "中斷連線",
        "lmstudio.status_running": "運行中",
        "lmstudio.status_stopped": "未運行",
        "lmstudio.refresh": "重新整理模型",
        "lmstudio.load": "載入模型",
        "lmstudio.eject": "退出模型",

        # About Dialog
        "about.title": "關於便攜版 Hermes Agent",
        "about.version": "版本：{version}",
        "about.description": "專為 Windows 設計的開箱即用便攜版 AI Agent。",
        "about.license": "授權協議：MIT",
    },

    "zh": {
        # App & Window
        "app.title": "便携版 Hermes Agent",
        "app.exit_confirm": "Agent 仍在运行中。确定要退出吗？",

        # Menu bar
        "menu.file": "文件",
        "menu.view": "视图",
        "menu.language": "语言",
        "menu.help": "帮助",
        "menu.new_chat": "新建对话",
        "menu.api_setup": "API 密钥设置",
        "menu.permissions": "权限管理",
        "menu.settings": "设置",
        "menu.exit": "退出",
        "menu.lm_studio": "LM Studio (本地模型)",
        "menu.skills": "技能浏览器",
        "menu.extensions": "扩展插件",
        "menu.toggle_sidebar": "切换侧边栏",
        "menu.about": "关于",

        # Sidebar
        "sidebar.new_chat": "+ 新建对话",
        "sidebar.model": "模型：",
        "sidebar.recent_sessions": "最近对话",
        "sidebar.no_sessions": "暂无最近对话记录",
        "sidebar.delete_title": "删除对话",
        "sidebar.delete_confirm": "确定要删除对话“{session_id}”吗？\n\n此操作无法撤销。",
        "sidebar.local_settings": "本地模型设置",
        "sidebar.gpu_offload": "GPU 卸载：",
        "sidebar.context_len": "上下文长度：",
        "sidebar.threads": "CPU 线程数：",
        "sidebar.temp": "温度值：",
        "sidebar.loading_model": "正在加载模型...",
        "sidebar.model_loaded": "模型加载完成",
        "sidebar.load_failed": "加载失败：{error}",

        # Chat Area
        "chat.new_chat_title": "新建对话",
        "chat.attach": "📎 附件",
        "chat.attach_tooltip": "附加图片 (Ctrl+Shift+I)",
        "chat.send": "发送",
        "chat.send_tooltip": "发送消息 (Enter)",
        "chat.stop": "停止",
        "chat.stop_tooltip": "停止生成 (Escape)",
        "chat.placeholder": "输入消息...（Enter 发送，Shift+Enter 换行）",
        "chat.empty_warning": "请先输入消息。",
        "chat.running_warning": "Agent 正在运行中。请稍候或按停止。",
        "chat.file_drag_drop": "拖放文件到此处或点击附件",

        # Message Roles & Tool widgets
        "chat.role_user": "您",
        "chat.role_ai": "Hermes",
        "chat.role_tool": "工具",
        "chat.role_error": "错误",
        "chat.role_system": "系统",
        "chat.tool": "工具: {name}",

        # Status bar
        "status.ready": "就绪",
        "status.running": "运行中...",
        "status.thinking": "思考中...",
        "status.tool_calling": "正在调用：{tool}",
        "status.error": "错误：{error}",
        "status.local_connected": "LM Studio 已连接",
        "status.local_disconnected": "LM Studio 未连接",

        # Settings dialog
        "settings.title": "设置",
        "settings.tab_api": "API 密钥",
        "settings.tab_model": "模型",
        "settings.tab_general": "常规",
        "settings.language": "界面语言",
        "settings.save": "保存",
        "settings.cancel": "取消",
        "settings.saved_success": "设置已成功保存。",
        "settings.saved_title": "设置已保存",
        "settings.restart_hint": "部分更改可能需要重启应用生效。",
        "settings.openrouter_key": "OpenRouter API 密钥：",
        "settings.default_model": "默认模型：",
        "settings.max_turns": "每轮对话最大轮数：",
        "settings.temperature": "温度值：",

        # API Key Setup Wizard
        "wizard.title": "API 密钥设置向导",
        "wizard.welcome_title": "欢迎使用 Hermes Agent！",
        "wizard.welcome_desc": "让我们设置您的 API 密钥，以便 Hermes 进行推理思考、网络搜索并协助您的工作。",
        "wizard.welcome_note": "您只需配置一组密钥即可开始使用（推荐 OpenRouter）。",
        "wizard.step_of": "步骤 {current} / {total}",
        "wizard.get_key": "获取密钥",
        "wizard.paste_label": "请在此粘贴您的 API 密钥：",
        "wizard.paste_placeholder": "在此粘贴密钥...",
        "wizard.clip_detected": "已从剪贴板检测到密钥！",
        "wizard.save_continue": "保存并继续",
        "wizard.skip": "暂时跳过",
        "wizard.back": "返回",
        "wizard.finish": "完成",
        "wizard.no_key": "未输入密钥 — 已跳过。",
        "wizard.prefix_hint": "密钥通常以“{prefix}”开头 — 仍为您保存。",
        "wizard.saved": "已保存！",
        "wizard.done_title": "设置完成！",
        "wizard.done_saved": "已成功保存 {count} 项 API 密钥。",
        "wizard.done_none": "本次未添加任何密钥。",
        "wizard.status_ready": "已就绪",
        "wizard.status_not_set": "未设置",
        "wizard.done_hint": "\n您可以随时在“文件 > API 密钥设置”\n或“设置”中添加或修改密钥。",
        "wizard.start_chatting": "开始对话！",

        # Permissions Panel
        "permissions.title": "权限设置",
        "permissions.desc": "控制 Hermes Agent 在您计算机上的操作权限。",
        "permissions.save": "保存权限",
        "permissions.cancel": "取消",
        "permissions.saved": "权限设置已成功保存。",
        "permissions.level_0": "已禁用",
        "permissions.level_1": "仅限应用目录",
        "permissions.level_2": "应用 + 用户主目录",
        "permissions.level_3": "计算机任意位置",
        "permissions.level_4": "系统 / 管理员权限",

        # Extensions Dialog
        "extensions.title": "扩展管理器",
        "extensions.installed_tab": "已安装",
        "extensions.available_tab": "可安装",
        "extensions.install_btn": "安装",
        "extensions.uninstall_btn": "卸载",
        "extensions.status_installed": "已安装",
        "extensions.status_not_installed": "未安装",

        # LM Studio Panel
        "lmstudio.title": "LM Studio 本地模型",
        "lmstudio.connect": "连接",
        "lmstudio.disconnect": "断开连接",
        "lmstudio.status_running": "运行中",
        "lmstudio.status_stopped": "未运行",
        "lmstudio.refresh": "刷新模型",
        "lmstudio.load": "加载模型",
        "lmstudio.eject": "弹出模型",

        # About Dialog
        "about.title": "关于便携版 Hermes Agent",
        "about.version": "版本：{version}",
        "about.description": "专为 Windows 打造的即开即用便携版 AI Agent。",
        "about.license": "开源协议：MIT",
    },
}

# Active language state
_current_language: str = DEFAULT_LANGUAGE
_listeners: List[Callable[[str], None]] = []


def _get_config_path() -> Path:
    """Get the path to gui_config.json under HERMES_HOME."""
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home() / "gui_config.json"
    except Exception:
        env_home = os.environ.get("HERMES_HOME")
        if env_home:
            return Path(env_home) / "gui_config.json"
        return Path.home() / ".hermes" / "gui_config.json"


def load_saved_language() -> str:
    """Determine the effective language from environment, saved config, or system locale."""
    # 1. Environment variable override
    env_lang = os.environ.get("HERMES_LANGUAGE", "").strip().lower()
    if env_lang in LANGUAGE_CODES:
        return env_lang
    if env_lang in ("zh-tw", "zh-hk", "zh-mo", "traditional-chinese"):
        return "zh-hant"
    if env_lang in ("zh-cn", "zh-sg", "simplified-chinese"):
        return "zh"

    # 2. Saved configuration file under HERMES_HOME
    try:
        cfg_path = _get_config_path()
        if cfg_path.exists():
            import json
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved = data.get("language", "").strip().lower()
            if saved in LANGUAGE_CODES:
                return saved
            if saved in ("zh-tw", "zh-hk", "zh-mo"):
                return "zh-hant"
            if saved in ("zh-cn", "zh-sg"):
                return "zh"
    except Exception as e:
        logger.debug("Failed to read language preference from config: %s", e)

    # 3. System locale detection fallback
    try:
        loc, _ = locale.getdefaultlocale()
        if loc:
            loc = loc.lower()
            if any(loc.startswith(p) for p in ("zh_tw", "zh_hk", "zh_mo")):
                return "zh-hant"
            if loc.startswith("zh"):
                return "zh"
    except Exception:
        pass

    return DEFAULT_LANGUAGE


def save_language(lang_code: str) -> bool:
    """Persist language preference to gui_config.json under HERMES_HOME."""
    if lang_code not in LANGUAGE_CODES:
        return False
    try:
        cfg_path = _get_config_path()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        data = {}
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["language"] = lang_code
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning("Failed to save language preference: %s", e)
        return False


def init_language() -> str:
    """Initialize active language on app startup."""
    global _current_language
    _current_language = load_saved_language()
    return _current_language


def get_language() -> str:
    """Return currently active language code ('en', 'zh-hant', or 'zh')."""
    return _current_language


def set_language(lang_code: str, persist: bool = True) -> bool:
    """Switch language at runtime and notify all registered listeners."""
    global _current_language
    if lang_code not in LANGUAGE_CODES:
        logger.warning("Unsupported language code: %s", lang_code)
        return False

    _current_language = lang_code
    os.environ["HERMES_LANGUAGE"] = lang_code

    if persist:
        save_language(lang_code)

    # Notify listeners
    for listener in list(_listeners):
        try:
            listener(lang_code)
        except Exception as e:
            logger.error("Error in language listener callback: %s", e)

    return True


def register_listener(callback: Callable[[str], None]) -> None:
    """Register a callback invoked when the language changes: callback(new_lang_code)."""
    if callback not in _listeners:
        _listeners.append(callback)


def unregister_listener(callback: Callable[[str], None]) -> None:
    """Remove a previously registered language change callback."""
    if callback in _listeners:
        _listeners.remove(callback)


def t(key: str, default: Optional[str] = None, **kwargs: Any) -> str:
    """
    Look up translation string for the active language.
    Falls back to English if missing, then to default (or key itself).
    Supports keyword formatting: t("wizard.step_of", current=1, total=5)
    """
    lang_dict = TRANSLATIONS.get(_current_language, {})
    template = lang_dict.get(key)

    if template is None and _current_language != DEFAULT_LANGUAGE:
        # Fallback to English
        template = TRANSLATIONS.get(DEFAULT_LANGUAGE, {}).get(key)

    if template is None:
        template = default if default is not None else key

    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    return template


# Run initialization on import
init_language()
