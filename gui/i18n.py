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
        "wizard.status_required": "Required",
        "wizard.keys_to_setup": "\n{count} key(s) to set up. Each takes about 1 minute.\nI'll open the signup page — you handle any CAPTCHAs,\nthen paste the key back here.",
        "wizard.unlocks": "Unlocks: {unlocks}",
        "wizard.open_url_tooltip": "Opens {url} in your default browser",
        "wizard.paste_from_clip": "Paste from Clipboard",
        "wizard.copy_hint": "Copy the key on the website, then click this",
        "wizard.service.openrouter_api_key.what": "Powers all AI conversations — this is the brain.",
        "wizard.service.openrouter_api_key.unlocks": "Chat, vision analysis, multi-model reasoning",
        "wizard.service.openrouter_api_key.free_tier": "Free tier available — many models are free",
        "wizard.service.openrouter_api_key.step_1": "1. Click 'Get Key' below — it opens OpenRouter in your browser",
        "wizard.service.openrouter_api_key.step_2": "2. Sign up with Google or email (free, no credit card)",
        "wizard.service.openrouter_api_key.step_3": "3. Click 'Create Key' on their dashboard",
        "wizard.service.openrouter_api_key.step_4": "4. Copy the key (starts with sk-or-...)",
        "wizard.service.openrouter_api_key.step_5": "5. Paste it below and click Save",
        "wizard.service.firecrawl_api_key.what": "Web search and webpage reading — lets Hermes find info online.",
        "wizard.service.firecrawl_api_key.unlocks": "web_search, web_extract tools",
        "wizard.service.firecrawl_api_key.free_tier": "Free: 500 credits/month (plenty for personal use)",
        "wizard.service.firecrawl_api_key.step_1": "1. Click 'Get Key' below — it opens Firecrawl in your browser",
        "wizard.service.firecrawl_api_key.step_2": "2. Sign up with Google or GitHub (free)",
        "wizard.service.firecrawl_api_key.step_3": "3. Go to API Keys in their dashboard",
        "wizard.service.firecrawl_api_key.step_4": "4. Copy your API key",
        "wizard.service.firecrawl_api_key.step_5": "5. Paste it below and click Save",
        "wizard.service.fal_key.what": "Image generation — Hermes can create images from descriptions.",
        "wizard.service.fal_key.unlocks": "image_generate tool (FLUX model)",
        "wizard.service.fal_key.free_tier": "Free: $10 in credits to start",
        "wizard.service.fal_key.step_1": "1. Click 'Get Key' below — it opens FAL.ai in your browser",
        "wizard.service.fal_key.step_2": "2. Sign up with GitHub or Google (free)",
        "wizard.service.fal_key.step_3": "3. Go to Keys in their dashboard",
        "wizard.service.fal_key.step_4": "4. Create and copy your API key",
        "wizard.service.fal_key.step_5": "5. Paste it below and click Save",
        "wizard.service.serper_api_key.what": "Google-quality search results — structured, fast, with knowledge graphs.",
        "wizard.service.serper_api_key.unlocks": "serper_search tool (better than DuckDuckGo for factual queries)",
        "wizard.service.serper_api_key.free_tier": "Free: 2,500 searches/month",
        "wizard.service.serper_api_key.step_1": "1. Click 'Get Key' below — it opens Serper.dev in your browser",
        "wizard.service.serper_api_key.step_2": "2. Sign up with Google or email (free)",
        "wizard.service.serper_api_key.step_3": "3. Copy your API key from the dashboard",
        "wizard.service.serper_api_key.step_4": "4. Paste it below and click Save",
        "wizard.service.browserbase_api_key.what": "Cloud browser — faster web browsing with anti-bot protection.",
        "wizard.service.browserbase_api_key.unlocks": "Upgrades browser from local to cloud (optional)",
        "wizard.service.browserbase_api_key.free_tier": "Free tier: 1000 browser sessions/month",
        "wizard.service.browserbase_api_key.step_1": "1. Click 'Get Key' below — it opens Browserbase in your browser",
        "wizard.service.browserbase_api_key.step_2": "2. Sign up (free tier available)",
        "wizard.service.browserbase_api_key.step_3": "3. Copy your API Key AND Project ID from the dashboard",
        "wizard.service.browserbase_api_key.step_4": "4. Paste the API key below",
        "wizard.service.browserbase_api_key.step_5": "5. (You'll also need to set BROWSERBASE_PROJECT_ID in Settings)",
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

        # Chat extra keys
        "chat.resumed_session": "Resumed Session",
        "chat.session_started": "New session started.",
        "chat.session_resumed": "Session resumed. You can continue the conversation.",
        "chat.generation_stopped": "Generation stopped.",
        "chat.welcome_configured": "Welcome to Portable Hermes Agent!\nType a message below and press Enter to chat.\nShift+Enter for newlines. Escape to interrupt.",
        "chat.welcome_unconfigured": "Welcome to Portable Hermes Agent!\n\nNo AI model is connected yet, but that's OK!\nI'm running in guided mode — ask me anything and I'll search the built-in guide for answers.\n\nTry typing:\n  • How do I get started?\n  • What is OpenRouter?\n  • How do I use local models?\n  • What can Hermes do?\n\nOr go to File > API Key Setup to connect an AI model.",

        # Settings extra keys
        "settings.api_openrouter": "OpenRouter (main LLM provider)",
        "settings.api_firecrawl": "Firecrawl (web search)",
        "settings.api_fal": "FAL.ai (image generation)",
        "settings.api_serper": "Serper.dev (Google search)",
        "settings.api_openai": "OpenAI (voice/transcription)",
        "settings.api_github": "GitHub (Skills Hub rate limits)",
        "settings.model_hint": "You can type any OpenRouter model ID",

        # Permissions extra keys
        "permissions.reset_defaults": "Reset to Defaults",
        "permissions.read.name": "File Reading",
        "permissions.read.level_0.name": "Disabled",
        "permissions.read.level_0.desc": "Agent cannot read any files",
        "permissions.read.level_1.name": "App Only",
        "permissions.read.level_1.desc": "Can read files inside the Hermes app folder only",
        "permissions.read.level_2.name": "App + Home",
        "permissions.read.level_2.desc": "Can read files in app folder and your user folder",
        "permissions.read.level_3.name": "Anywhere",
        "permissions.read.level_3.desc": "Can read any file on your computer",
        "permissions.read.level_4.name": "Anywhere + System",
        "permissions.read.level_4.desc": "Can read system files, configs, registry",

        "permissions.write.name": "File Writing",
        "permissions.write.level_0.name": "Disabled",
        "permissions.write.level_0.desc": "Agent cannot write any files",
        "permissions.write.level_1.name": "App Only",
        "permissions.write.level_1.desc": "Can only write inside the Hermes app folder",
        "permissions.write.level_2.name": "App + Home",
        "permissions.write.level_2.desc": "Can write in app folder and your user folder",
        "permissions.write.level_3.name": "Anywhere",
        "permissions.write.level_3.desc": "Can write files anywhere on your computer",
        "permissions.write.level_4.name": "Anywhere + System",
        "permissions.write.level_4.desc": "Can modify system files and configs",

        "permissions.install.name": "Package Installation",
        "permissions.install.level_0.name": "Disabled",
        "permissions.install.level_0.desc": "Cannot install any packages",
        "permissions.install.level_1.name": "App Only",
        "permissions.install.level_1.desc": "Installs into the portable Python only",
        "permissions.install.level_2.name": "App + User",
        "permissions.install.level_2.desc": "Can install to portable Python and user packages",
        "permissions.install.level_3.name": "System-wide",
        "permissions.install.level_3.desc": "Can install packages system-wide (pip install --global)",
        "permissions.install.level_4.name": "System + Admin",
        "permissions.install.level_4.desc": "Can install system services, drivers, global tools",

        "permissions.execute.name": "Command Execution",
        "permissions.execute.level_0.name": "Disabled",
        "permissions.execute.level_0.desc": "Cannot run any commands",
        "permissions.execute.level_1.name": "App Only",
        "permissions.execute.level_1.desc": "Can only run commands inside the app folder",
        "permissions.execute.level_2.name": "App + Safe",
        "permissions.execute.level_2.desc": "Can run commands anywhere but no admin/system changes",
        "permissions.execute.level_3.name": "Unrestricted",
        "permissions.execute.level_3.desc": "Can run any command on your computer",
        "permissions.execute.level_4.name": "Admin",
        "permissions.execute.level_4.desc": "Can run elevated/admin commands (use with caution)",

        "permissions.remove.name": "File Deletion",
        "permissions.remove.level_0.name": "Disabled",
        "permissions.remove.level_0.desc": "Cannot delete any files",
        "permissions.remove.level_1.name": "App Only",
        "permissions.remove.level_1.desc": "Can only delete files inside the Hermes app folder",
        "permissions.remove.level_2.name": "App + Home",
        "permissions.remove.level_2.desc": "Can delete in app folder and your user folder",
        "permissions.remove.level_3.name": "Anywhere",
        "permissions.remove.level_3.desc": "Can delete any file on your computer",
        "permissions.remove.level_4.name": "Anywhere + System",
        "permissions.remove.level_4.desc": "Can delete system files (dangerous!)",

        "permissions.network.name": "Network Access",
        "permissions.network.level_0.name": "Offline",
        "permissions.network.level_0.desc": "No network access at all",
        "permissions.network.level_1.name": "Local Only",
        "permissions.network.level_1.desc": "Can only access localhost services (LM Studio, extensions)",
        "permissions.network.level_2.name": "Web + APIs",
        "permissions.network.level_2.desc": "Can browse web, call APIs, search (normal usage)",
        "permissions.network.level_3.name": "Full Network",
        "permissions.network.level_3.desc": "Can access any network resource, SSH, etc.",
        "permissions.network.level_4.name": "Full + Listen",
        "permissions.network.level_4.desc": "Can open ports, start servers, accept connections",

        # Extensions extra keys
        "extensions.subtitle": "Add powerful AI capabilities to Hermes",
        "extensions.status_running": "Running",
        "extensions.status_stopped": "Installed (stopped)",
        "extensions.port": "Port",
        "extensions.size": "Size",
        "extensions.gpu_recommended": "GPU recommended",
        "extensions.start_btn": "Start",
        "extensions.stop_btn": "Stop",
        "extensions.open_folder": "Open Folder",
        "extensions.confirm_title": "Install Extension",
        "extensions.confirm_msg": "Install {name}?\n\nSize: {size}\nThis will download and set up everything automatically.\nThe install window will open — follow any prompts there.",
        "extensions.music-server.name": "Music Generation Server",
        "extensions.music-server.desc": "Generate music, songs, and sound effects from text prompts.\n8 AI models, multi-GPU, production mastering pipeline.",
        "extensions.music-server.size": "~5 GB (models downloaded separately)",
        "extensions.tts-server.name": "Text-to-Speech Server",
        "extensions.tts-server.desc": "Convert text to broadcast-quality speech with voice cloning.\n10 TTS models, emotions, multilingual, post-processing.",
        "extensions.tts-server.size": "~5 GB (models downloaded separately)",
        "extensions.comfyui.name": "ComfyUI Image Generator",
        "extensions.comfyui.desc": "Full ComfyUI installation for AI image generation.\n100+ models, workflows, multi-GPU, custom nodes.",
        "extensions.comfyui.size": "~10 GB (with base model)",

        # Skills Browser extra keys
        "skills.title": "Skills Browser",
        "skills.heading": "Installed Skills",
        "skills.no_dir": "No skills directory found.",
        "skills.no_skills": "No skills found.",

        # LM Studio extra keys
        "lmstudio.heading": "LM Studio",
        "lmstudio.endpoint": "Endpoint:",
        "lmstudio.available_models": "Available Models",
        "lmstudio.gpu": "GPU:",
        "lmstudio.context": "Context:",
        "lmstudio.unload": "Unload",
        "lmstudio.use_chat": "Use for Chat",
        "lmstudio.status_connecting": "Connecting...",
        "lmstudio.status_connected": "Connected",
        "lmstudio.status_not_running": "Not running — start LM Studio first",
        "lmstudio.api_key": "API Key:",
        "lmstudio.save_key": "Save",
        "lmstudio.api_key_saved": "API key saved",
        "lmstudio.api_key_cleared": "API key cleared",
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
        "wizard.status_required": "必填",
        "wizard.keys_to_setup": "\n需設定 {count} 項金鑰，每項約需 1 分鐘。\n精靈將為您開啟註冊頁面 — 完成驗證碼後，\n將金鑰貼回此處即可。",
        "wizard.unlocks": "解鎖功能：{unlocks}",
        "wizard.open_url_tooltip": "在預設瀏覽器中開啟 {url}",
        "wizard.paste_from_clip": "從剪貼簿貼上",
        "wizard.copy_hint": "在網站上複製金鑰後點擊此處",
        "wizard.service.openrouter_api_key.what": "驅動所有 AI 對話 — 這是核心大腦。",
        "wizard.service.openrouter_api_key.unlocks": "對話、圖像視覺分析、多模型推理",
        "wizard.service.openrouter_api_key.free_tier": "提供免費額度 — 多款模型可免費使用",
        "wizard.service.openrouter_api_key.step_1": "1. 點擊下方的「取得金鑰」— 將在瀏覽器中開啟 OpenRouter",
        "wizard.service.openrouter_api_key.step_2": "2. 使用 Google 或電子郵件註冊（免費、無需信用卡）",
        "wizard.service.openrouter_api_key.step_3": "3. 在控制台中點擊「Create Key」建立金鑰",
        "wizard.service.openrouter_api_key.step_4": "4. 複製金鑰（以 sk-or- 開頭）",
        "wizard.service.openrouter_api_key.step_5": "5. 將金鑰貼在下方並點擊儲存",
        "wizard.service.firecrawl_api_key.what": "網路搜尋與網頁閱讀 — 讓 Hermes 能連網檢索資訊。",
        "wizard.service.firecrawl_api_key.unlocks": "web_search、web_extract 工具",
        "wizard.service.firecrawl_api_key.free_tier": "免費：每月 500 點額度（個人使用充裕）",
        "wizard.service.firecrawl_api_key.step_1": "1. 點擊下方的「取得金鑰」— 將在瀏覽器中開啟 Firecrawl",
        "wizard.service.firecrawl_api_key.step_2": "2. 使用 Google 或 GitHub 註冊（免費）",
        "wizard.service.firecrawl_api_key.step_3": "3. 前往控制台的 API Keys 頁面",
        "wizard.service.firecrawl_api_key.step_4": "4. 複製您的 API 金鑰",
        "wizard.service.firecrawl_api_key.step_5": "5. 將金鑰貼在下方並點擊儲存",
        "wizard.service.fal_key.what": "圖像生成 — Hermes 可根據描述生成圖片。",
        "wizard.service.fal_key.unlocks": "image_generate 工具 (FLUX 模型)",
        "wizard.service.fal_key.free_tier": "免費：初始贈送 $10 額度",
        "wizard.service.fal_key.step_1": "1. 點擊下方的「取得金鑰」— 將在瀏覽器中開啟 FAL.ai",
        "wizard.service.fal_key.step_2": "2. 使用 GitHub 或 Google 註冊（免費）",
        "wizard.service.fal_key.step_3": "3. 前往控制台的 Keys 頁面",
        "wizard.service.fal_key.step_4": "4. 建立並複製您的 API 金鑰",
        "wizard.service.fal_key.step_5": "5. 將金鑰貼在下方並點擊儲存",
        "wizard.service.serper_api_key.what": "Google 級搜尋結果 — 結構化、快速且具備知識圖譜。",
        "wizard.service.serper_api_key.unlocks": "serper_search 工具（針對事實查詢優於 DuckDuckGo）",
        "wizard.service.serper_api_key.free_tier": "免費：每月 2,500 次搜尋",
        "wizard.service.serper_api_key.step_1": "1. 點擊下方的「取得金鑰」— 將在瀏覽器中開啟 Serper.dev",
        "wizard.service.serper_api_key.step_2": "2. 使用 Google 或電子郵件註冊（免費）",
        "wizard.service.serper_api_key.step_3": "3. 從控制台複製您的 API 金鑰",
        "wizard.service.serper_api_key.step_4": "4. 將金鑰貼在下方並點擊儲存",
        "wizard.service.browserbase_api_key.what": "雲端瀏覽器 — 更快且具備防機器人偵測機制的網頁瀏覽。",
        "wizard.service.browserbase_api_key.unlocks": "將瀏覽器從本地升級至雲端（選填）",
        "wizard.service.browserbase_api_key.free_tier": "免費額度：每月 1000 次瀏覽器工作階段",
        "wizard.service.browserbase_api_key.step_1": "1. 點擊下方的「取得金鑰」— 將在瀏覽器中開啟 Browserbase",
        "wizard.service.browserbase_api_key.step_2": "2. 註冊帳號（提供免費額度）",
        "wizard.service.browserbase_api_key.step_3": "3. 從控制台複製您的 API Key 與 Project ID",
        "wizard.service.browserbase_api_key.step_4": "4. 將 API 金鑰貼在下方",
        "wizard.service.browserbase_api_key.step_5": "5. （您還需要在「設定」中填寫 BROWSERBASE_PROJECT_ID）",
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

        # Chat extra keys
        "chat.resumed_session": "恢復對話",
        "chat.session_started": "已開啟新對話。",
        "chat.session_resumed": "對話已載入，您可以繼續對話。",
        "chat.generation_stopped": "已停止生成。",
        "chat.welcome_configured": "歡迎使用便攜版 Hermes Agent！\n請在下方輸入訊息並按 Enter 即可開始對話。\nShift+Enter 換行，Escape 可中斷生成。",
        "chat.welcome_unconfigured": "歡迎使用便攜版 Hermes Agent！\n\n目前尚未連接 AI 模型，但這沒關係！\n我目前處於引導模式 — 您可以問我任何問題，我會搜尋內建指南為您解答。\n\n例如輸入：\n  • 如何開始使用？\n  • 什麼是 OpenRouter？\n  • 如何使用本地模型？\n  • Hermes 可以做什麼？\n\n或前往「檔案 > API 金鑰設定」連線 AI 模型。",

        # Settings extra keys
        "settings.api_openrouter": "OpenRouter (主要 LLM 提供商)",
        "settings.api_firecrawl": "Firecrawl (網路搜尋)",
        "settings.api_fal": "FAL.ai (圖像生成)",
        "settings.api_serper": "Serper.dev (Google 搜尋)",
        "settings.api_openai": "OpenAI (語音/逐字稿轉錄)",
        "settings.api_github": "GitHub (Skills Hub 速率上限金鑰)",
        "settings.model_hint": "可輸入任意 OpenRouter 模型識別碼",

        # Permissions extra keys
        "permissions.reset_defaults": "重設為預設值",
        "permissions.read.name": "檔案讀取",
        "permissions.read.level_0.name": "已停用",
        "permissions.read.level_0.desc": "Agent 無法讀取任何檔案",
        "permissions.read.level_1.name": "僅限應用目錄",
        "permissions.read.level_1.desc": "僅能讀取 Hermes 應用程式資料夾內的檔案",
        "permissions.read.level_2.name": "應用 + 家目錄",
        "permissions.read.level_2.desc": "可讀取應用程式目錄與您的使用者家目錄",
        "permissions.read.level_3.name": "電腦任意位置",
        "permissions.read.level_3.desc": "可讀取您電腦上的任何檔案",
        "permissions.read.level_4.name": "任意位置 + 系統",
        "permissions.read.level_4.desc": "可讀取系統檔案、設定檔與登錄檔",

        "permissions.write.name": "檔案寫入",
        "permissions.write.level_0.name": "已停用",
        "permissions.write.level_0.desc": "Agent 無法建立或修改任何檔案",
        "permissions.write.level_1.name": "僅限應用目錄",
        "permissions.write.level_1.desc": "僅能在 Hermes 應用程式資料夾內寫入",
        "permissions.write.level_2.name": "應用 + 家目錄",
        "permissions.write.level_2.desc": "可在應用程式目錄與使用者家目錄寫入",
        "permissions.write.level_3.name": "電腦任意位置",
        "permissions.write.level_3.desc": "可在電腦任意位置寫入檔案",
        "permissions.write.level_4.name": "任意位置 + 系統",
        "permissions.write.level_4.desc": "可修改系統檔案與設定檔",

        "permissions.install.name": "套件安裝",
        "permissions.install.level_0.name": "已停用",
        "permissions.install.level_0.desc": "無法安裝任何套件",
        "permissions.install.level_1.name": "僅限應用目錄",
        "permissions.install.level_1.desc": "僅安裝至便攜版 Python 環境中",
        "permissions.install.level_2.name": "應用 + 使用者",
        "permissions.install.level_2.desc": "可安裝至便攜版 Python 與使用者套件目錄",
        "permissions.install.level_3.name": "全系統範圍",
        "permissions.install.level_3.desc": "可在全系統範圍安裝套件 (pip install --global)",
        "permissions.install.level_4.name": "系統 + 管理員",
        "permissions.install.level_4.desc": "可安裝系統服務、驅動程式與全域工具",

        "permissions.execute.name": "命令執行",
        "permissions.execute.level_0.name": "已停用",
        "permissions.execute.level_0.desc": "無法執行任何命令",
        "permissions.execute.level_1.name": "僅限應用目錄",
        "permissions.execute.level_1.desc": "僅能在應用程式目錄內執行命令",
        "permissions.execute.level_2.name": "應用 + 安全模式",
        "permissions.execute.level_2.desc": "可在任意處執行命令，但禁止管理員/系統級變更",
        "permissions.execute.level_3.name": "無限制",
        "permissions.execute.level_3.desc": "可在電腦上執行任意命令",
        "permissions.execute.level_4.name": "管理員權限",
        "permissions.execute.level_4.desc": "可執行提升/管理員命令（請謹慎使用）",

        "permissions.remove.name": "檔案刪除",
        "permissions.remove.level_0.name": "已停用",
        "permissions.remove.level_0.desc": "無法刪除任何檔案",
        "permissions.remove.level_1.name": "僅限應用目錄",
        "permissions.remove.level_1.desc": "僅能刪除 Hermes 應用程式資料夾內的檔案",
        "permissions.remove.level_2.name": "應用 + 家目錄",
        "permissions.remove.level_2.desc": "可刪除應用程式目錄與使用者家目錄的檔案",
        "permissions.remove.level_3.name": "電腦任意位置",
        "permissions.remove.level_3.desc": "可刪除電腦上的任意檔案",
        "permissions.remove.level_4.name": "任意位置 + 系統",
        "permissions.remove.level_4.desc": "可刪除系統檔案（極度危險！）",

        "permissions.network.name": "網路存取",
        "permissions.network.level_0.name": "離線模式",
        "permissions.network.level_0.desc": "完全不進行任何網路存取",
        "permissions.network.level_1.name": "僅本機",
        "permissions.network.level_1.desc": "僅能存取 localhost 本機服務（LM Studio、擴充套件）",
        "permissions.network.level_2.name": "網路 + API",
        "permissions.network.level_2.desc": "可瀏覽網頁、呼叫 API、連網搜尋（一般用途）",
        "permissions.network.level_3.name": "完整網路",
        "permissions.network.level_3.desc": "可存取任何網路資源、SSH 等",
        "permissions.network.level_4.name": "完整 + 監聽服務",
        "permissions.network.level_4.desc": "可開啟通訊埠、啟動伺服器並接收連線",

        # Extensions extra keys
        "extensions.subtitle": "為 Hermes 增添強大的 AI 擴充能力",
        "extensions.status_running": "運行中",
        "extensions.status_stopped": "已安裝 (未運行)",
        "extensions.port": "通訊埠",
        "extensions.size": "容量大小",
        "extensions.gpu_recommended": "建議使用 GPU",
        "extensions.start_btn": "啟動",
        "extensions.stop_btn": "停止",
        "extensions.open_folder": "開啟資料夾",
        "extensions.confirm_title": "安裝擴充套件",
        "extensions.confirm_msg": "確定要安裝 {name} 嗎？\n\n預估容量：{size}\n這將自動下載並設定所有相依環境。\n將開啟安裝視窗 — 請遵循視窗中的提示操作。",
        "extensions.music-server.name": "音樂生成伺服器",
        "extensions.music-server.desc": "從文字提示詞生成音樂、歌曲與音效。\n內建 8 種 AI 模型、支援多 GPU 與生產級母帶後製管線。",
        "extensions.music-server.size": "~5 GB (模型將另行下載)",
        "extensions.tts-server.name": "文字轉語音 (TTS) 伺服器",
        "extensions.tts-server.desc": "具備聲音複製能力的廣播級語音生成。\n內建 10 種 TTS 模型、支援豐富情緒、多國語言與後製處理。",
        "extensions.tts-server.size": "~5 GB (模型將另行下載)",
        "extensions.comfyui.name": "ComfyUI 圖像生成器",
        "extensions.comfyui.desc": "完整的 ComfyUI AI 繪圖生成環境。\n支援 100+ 模型、工作流、多 GPU 與自訂節點擴充。",
        "extensions.comfyui.size": "~10 GB (含基礎模型)",

        # Skills Browser extra keys
        "skills.title": "技能瀏覽器",
        "skills.heading": "已安裝技能",
        "skills.no_dir": "未找到技能目錄。",
        "skills.no_skills": "尚未安裝任何技能。",

        # LM Studio extra keys
        "lmstudio.heading": "LM Studio",
        "lmstudio.endpoint": "端點網址：",
        "lmstudio.available_models": "可用模型清單",
        "lmstudio.gpu": "GPU 裝置：",
        "lmstudio.context": "上下文：",
        "lmstudio.unload": "卸載模型",
        "lmstudio.use_chat": "用於對話",
        "lmstudio.status_connecting": "正在連線...",
        "lmstudio.status_connected": "已連線",
        "lmstudio.status_not_running": "未運行 — 請先啟動 LM Studio",
        "lmstudio.api_key": "API 金鑰：",
        "lmstudio.save_key": "儲存",
        "lmstudio.api_key_saved": "API 金鑰已儲存",
        "lmstudio.api_key_cleared": "API 金鑰已清除",
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
        "wizard.status_required": "必填",
        "wizard.keys_to_setup": "\n需设置 {count} 项密钥，每项约需 1 分钟。\n向导将为您打开注册页面 — 完成验证码后，\n将密钥粘贴回此处即可。",
        "wizard.unlocks": "解锁功能：{unlocks}",
        "wizard.open_url_tooltip": "在默认浏览器中打开 {url}",
        "wizard.paste_from_clip": "从剪贴板粘贴",
        "wizard.copy_hint": "在网站上复制密钥后点击此处",
        "wizard.service.openrouter_api_key.what": "驱动所有 AI 对话 — 这是核心大脑。",
        "wizard.service.openrouter_api_key.unlocks": "对话、图像视觉分析、多模型推理",
        "wizard.service.openrouter_api_key.free_tier": "提供免费额度 — 多款模型可免费使用",
        "wizard.service.openrouter_api_key.step_1": "1. 点击下方的“获取密钥” — 将在浏览器中打开 OpenRouter",
        "wizard.service.openrouter_api_key.step_2": "2. 使用 Google 或电子邮件注册（免费、无需信用卡）",
        "wizard.service.openrouter_api_key.step_3": "3. 在控制台中点击“Create Key”创建密钥",
        "wizard.service.openrouter_api_key.step_4": "4. 复制密钥（以 sk-or- 开头）",
        "wizard.service.openrouter_api_key.step_5": "5. 将密钥粘贴在下方并点击保存",
        "wizard.service.firecrawl_api_key.what": "网络搜索与网页阅读 — 让 Hermes 能联网检索信息。",
        "wizard.service.firecrawl_api_key.unlocks": "web_search、web_extract 工具",
        "wizard.service.firecrawl_api_key.free_tier": "免费：每月 500 点额度（个人使用充裕）",
        "wizard.service.firecrawl_api_key.step_1": "1. 点击下方的“获取密钥” — 将在浏览器中打开 Firecrawl",
        "wizard.service.firecrawl_api_key.step_2": "2. 使用 Google 或 GitHub 注册（免费）",
        "wizard.service.firecrawl_api_key.step_3": "3. 前往控制台的 API Keys 页面",
        "wizard.service.firecrawl_api_key.step_4": "4. 复制您的 API 密钥",
        "wizard.service.firecrawl_api_key.step_5": "5. 将密钥粘贴在下方并点击保存",
        "wizard.service.fal_key.what": "图像生成 — Hermes 可根据描述生成图片。",
        "wizard.service.fal_key.unlocks": "image_generate 工具 (FLUX 模型)",
        "wizard.service.fal_key.free_tier": "免费：初始赠送 $10 额度",
        "wizard.service.fal_key.step_1": "1. 点击下方的“获取密钥” — 将在浏览器中打开 FAL.ai",
        "wizard.service.fal_key.step_2": "2. 使用 GitHub 或 Google 注册（免费）",
        "wizard.service.fal_key.step_3": "3. 前往控制台的 Keys 页面",
        "wizard.service.fal_key.step_4": "4. 创建并复制您的 API 密钥",
        "wizard.service.fal_key.step_5": "5. 将密钥粘贴在下方并点击保存",
        "wizard.service.serper_api_key.what": "Google 级搜索结果 — 结构化、快速且具备知识图谱。",
        "wizard.service.serper_api_key.unlocks": "serper_search 工具（针对事实查询优于 DuckDuckGo）",
        "wizard.service.serper_api_key.free_tier": "免费：每月 2,500 次搜索",
        "wizard.service.serper_api_key.step_1": "1. 点击下方的“获取密钥” — 将在浏览器中打开 Serper.dev",
        "wizard.service.serper_api_key.step_2": "2. 使用 Google 或电子邮件注册（免费）",
        "wizard.service.serper_api_key.step_3": "3. 从控制台复制您的 API 密钥",
        "wizard.service.serper_api_key.step_4": "4. 将密钥粘贴在下方并点击保存",
        "wizard.service.browserbase_api_key.what": "云端浏览器 — 更快且具备防机器人检测机制的网页浏览。",
        "wizard.service.browserbase_api_key.unlocks": "将浏览器从本地升级至云端（选填）",
        "wizard.service.browserbase_api_key.free_tier": "免费额度：每月 1000 次浏览器会话",
        "wizard.service.browserbase_api_key.step_1": "1. 点击下方的“获取密钥” — 将在浏览器中打开 Browserbase",
        "wizard.service.browserbase_api_key.step_2": "2. 注册账号（提供免费额度）",
        "wizard.service.browserbase_api_key.step_3": "3. 从控制台复制您的 API Key 与 Project ID",
        "wizard.service.browserbase_api_key.step_4": "4. 将 API 密钥粘贴在下方",
        "wizard.service.browserbase_api_key.step_5": "5. （您还需要在“设置”中填写 BROWSERBASE_PROJECT_ID）",
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
                "about.license": "授权协议：MIT",

        # Chat extra keys
        "chat.resumed_session": "恢复对话",
        "chat.session_started": "已开始新对话。",
        "chat.session_resumed": "对话已加载，您可以继续对话。",
        "chat.generation_stopped": "已停止生成。",
        "chat.welcome_configured": "欢迎使用便携版 Hermes Agent！\n请在下方输入消息并按 Enter 即可开始对话。\nShift+Enter 换行，Escape 可中断生成。",
        "chat.welcome_unconfigured": "欢迎使用便携版 Hermes Agent！\n\n当前尚未连接 AI 模型，但这没关系！\n我目前处于引导模式 — 您可以问我任何问题，我将搜索内置指南为您解答。\n\n例如输入：\n  • 如何开始使用？\n  • 什么是 OpenRouter？\n  • 如何使用本地模型？\n  • Hermes 可以做什么？\n\n或前往“文件 > API 密钥设置”连接 AI 模型。",

        # Settings extra keys
        "settings.api_openrouter": "OpenRouter (主要 LLM 提供商)",
        "settings.api_firecrawl": "Firecrawl (网络搜索)",
        "settings.api_fal": "FAL.ai (图像生成)",
        "settings.api_serper": "Serper.dev (Google 搜索)",
        "settings.api_openai": "OpenAI (语音/转录)",
        "settings.api_github": "GitHub (Skills Hub 速率限制密钥)",
        "settings.model_hint": "可输入任意 OpenRouter 模型标识符",

        # Permissions extra keys
        "permissions.reset_defaults": "重置为默认值",
        "permissions.read.name": "文件读取",
        "permissions.read.level_0.name": "已禁用",
        "permissions.read.level_0.desc": "Agent 无法读取任何文件",
        "permissions.read.level_1.name": "仅限应用目录",
        "permissions.read.level_1.desc": "仅能读取 Hermes 应用程序文件夹内的文件",
        "permissions.read.level_2.name": "应用 + 用户主目录",
        "permissions.read.level_2.desc": "可读取应用程序目录与您的用户主目录",
        "permissions.read.level_3.name": "计算机任意位置",
        "permissions.read.level_3.desc": "可读取计算机上的任意文件",
        "permissions.read.level_4.name": "任意位置 + 系统",
        "permissions.read.level_4.desc": "可读取系统文件、配置文件与注册表",

        "permissions.write.name": "文件写入",
        "permissions.write.level_0.name": "已禁用",
        "permissions.write.level_0.desc": "Agent 无法创建或修改任何文件",
        "permissions.write.level_1.name": "仅限应用目录",
        "permissions.write.level_1.desc": "仅能在 Hermes 应用程序文件夹内写入",
        "permissions.write.level_2.name": "应用 + 用户主目录",
        "permissions.write.level_2.desc": "可在应用程序目录与用户主目录写入",
        "permissions.write.level_3.name": "计算机任意位置",
        "permissions.write.level_3.desc": "可在计算机任意位置写入文件",
        "permissions.write.level_4.name": "任意位置 + 系统",
        "permissions.write.level_4.desc": "可修改系统文件与配置文件",

        "permissions.install.name": "包安装",
        "permissions.install.level_0.name": "已禁用",
        "permissions.install.level_0.desc": "无法安装任何包",
        "permissions.install.level_1.name": "仅限应用目录",
        "permissions.install.level_1.desc": "仅安装至便携版 Python 环境中",
        "permissions.install.level_2.name": "应用 + 用户",
        "permissions.install.level_2.desc": "可安装至便携版 Python 与用户包目录",
        "permissions.install.level_3.name": "全系统范围",
        "permissions.install.level_3.desc": "可在全系统范围安装包 (pip install --global)",
        "permissions.install.level_4.name": "系统 + 管理员",
        "permissions.install.level_4.desc": "可安装系统服务、驱动程序与全局工具",

        "permissions.execute.name": "命令执行",
        "permissions.execute.level_0.name": "已禁用",
        "permissions.execute.level_0.desc": "无法运行任何命令",
        "permissions.execute.level_1.name": "仅限应用目录",
        "permissions.execute.level_1.desc": "仅能在应用程序目录内运行命令",
        "permissions.execute.level_2.name": "应用 + 安全模式",
        "permissions.execute.level_2.desc": "可在任意位置运行命令，但禁止管理员/系统级变更",
        "permissions.execute.level_3.name": "无限制",
        "permissions.execute.level_3.desc": "可在计算机上运行任意命令",
        "permissions.execute.level_4.name": "管理员权限",
        "permissions.execute.level_4.desc": "可运行提权/管理员命令（请谨慎使用）",

        "permissions.remove.name": "文件删除",
        "permissions.remove.level_0.name": "已禁用",
        "permissions.remove.level_0.desc": "无法删除任何文件",
        "permissions.remove.level_1.name": "仅限应用目录",
        "permissions.remove.level_1.desc": "仅能删除 Hermes 应用程序文件夹内的文件",
        "permissions.remove.level_2.name": "应用 + 用户主目录",
        "permissions.remove.level_2.desc": "可删除应用程序目录与用户主目录的文件",
        "permissions.remove.level_3.name": "计算机任意位置",
        "permissions.remove.level_3.desc": "可删除计算机上的任意文件",
        "permissions.remove.level_4.name": "任意位置 + 系统",
        "permissions.remove.level_4.desc": "可删除系统文件（极度危险！）",

        "permissions.network.name": "网络访问",
        "permissions.network.level_0.name": "离线模式",
        "permissions.network.level_0.desc": "完全不进行任何网络访问",
        "permissions.network.level_1.name": "仅本地",
        "permissions.network.level_1.desc": "仅能访问 localhost 本地服务（LM Studio、扩展插件）",
        "permissions.network.level_2.name": "网络 + API",
        "permissions.network.level_2.desc": "可浏览网页、调用 API、网络搜索（一般用途）",
        "permissions.network.level_3.name": "完整网络",
        "permissions.network.level_3.desc": "可访问任何网络资源、SSH 等",
        "permissions.network.level_4.name": "完整 + 监听服务",
        "permissions.network.level_4.desc": "可打开端口、启动服务器并接收连接",

        # Extensions extra keys
        "extensions.subtitle": "为 Hermes 增添强大的 AI 扩展能力",
        "extensions.status_running": "运行中",
        "extensions.status_stopped": "已安装 (未运行)",
        "extensions.port": "端口",
        "extensions.size": "大小",
        "extensions.gpu_recommended": "建议使用 GPU",
        "extensions.start_btn": "启动",
        "extensions.stop_btn": "停止",
        "extensions.open_folder": "打开文件夹",
        "extensions.confirm_title": "安装扩展",
        "extensions.confirm_msg": "确定要安装 {name} 吗？\n\n预估大小：{size}\n这将自动下载并设置所有依赖环境。\n将打开安装窗口 — 请遵循窗口中的提示操作。",
        "extensions.music-server.name": "音乐生成服务器",
        "extensions.music-server.desc": "根据文本提示生成音乐、歌曲与音效。\n内置 8 种 AI 模型、支持多 GPU 与生产级母带处理管线。",
        "extensions.music-server.size": "~5 GB (模型将单独下载)",
        "extensions.tts-server.name": "文本转语音 (TTS) 服务器",
        "extensions.tts-server.desc": "具备声音克隆能力的广播级语音转换。\n内置 10 种 TTS 模型、支持丰富情绪、多国语言与后处理。",
        "extensions.tts-server.size": "~5 GB (模型将单独下载)",
        "extensions.comfyui.name": "ComfyUI 图像生成器",
        "extensions.comfyui.desc": "完整的 ComfyUI AI 绘图生成环境。\n支持 100+ 模型、工作流、多 GPU 与自定义节点扩展。",
        "extensions.comfyui.size": "~10 GB (含基础模型)",

        # Skills Browser extra keys
        "skills.title": "技能浏览器",
        "skills.heading": "已安装技能",
        "skills.no_dir": "未找到技能目录。",
        "skills.no_skills": "尚未安装任何技能。",

        # LM Studio extra keys
        "lmstudio.heading": "LM Studio",
        "lmstudio.endpoint": "端点：",
        "lmstudio.available_models": "可用模型",
        "lmstudio.gpu": "GPU：",
        "lmstudio.context": "上下文：",
        "lmstudio.unload": "卸载模型",
        "lmstudio.use_chat": "用于对话",
        "lmstudio.status_connecting": "正在连接...",
        "lmstudio.status_connected": "已连接",
        "lmstudio.status_not_running": "未运行 — 请先启动 LM Studio",
        "lmstudio.api_key": "API 密钥：",
        "lmstudio.save_key": "保存",
        "lmstudio.api_key_saved": "API 密钥已保存",
        "lmstudio.api_key_cleared": "API 密钥已清除",
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
