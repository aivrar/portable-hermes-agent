"""
Hermes Agent - API Key Setup Wizard
Walks non-technical users through getting free API keys.
Opens signup pages in their real browser, they handle CAPTCHAs,
paste the key back, and we save it automatically.
"""
import os
import re
import tkinter as tk
from tkinter import ttk
import webbrowser
from pathlib import Path

from gui.theme import C, FONTS, set_dark_title_bar, Tooltip, SF

PROJECT_ROOT = Path(__file__).parent.parent

# ============================================================================
# API Key definitions — each service the user can sign up for
# ============================================================================

API_SERVICES = [
    {
        "key": "OPENROUTER_API_KEY",
        "name": "OpenRouter",
        "icon": "LLM",
        "what": "Powers all AI conversations — this is the brain.",
        "unlocks": "Chat, vision analysis, multi-model reasoning",
        "signup_url": "https://openrouter.ai/keys",
        "steps": [
            "1. Click 'Get Key' below — it opens OpenRouter in your browser",
            "2. Sign up with Google or email (free, no credit card)",
            "3. Click 'Create Key' on their dashboard",
            "4. Copy the key (starts with sk-or-...)",
            "5. Paste it below and click Save",
        ],
        "free_tier": "Free tier available — many models are free",
        "required": True,
        "prefix": "sk-or-",
    },
    {
        "key": "FIRECRAWL_API_KEY",
        "name": "Firecrawl",
        "icon": "WEB",
        "what": "Web search and webpage reading — lets Hermes find info online.",
        "unlocks": "web_search, web_extract tools",
        "signup_url": "https://www.firecrawl.dev/app/api-keys",
        "steps": [
            "1. Click 'Get Key' below — it opens Firecrawl in your browser",
            "2. Sign up with Google or GitHub (free)",
            "3. Go to API Keys in their dashboard",
            "4. Copy your API key",
            "5. Paste it below and click Save",
        ],
        "free_tier": "Free: 500 credits/month (plenty for personal use)",
        "required": False,
        "prefix": "fc-",
    },
    {
        "key": "FAL_KEY",
        "name": "FAL.ai",
        "icon": "IMG",
        "what": "Image generation — Hermes can create images from descriptions.",
        "unlocks": "image_generate tool (FLUX model)",
        "signup_url": "https://fal.ai/dashboard/keys",
        "steps": [
            "1. Click 'Get Key' below — it opens FAL.ai in your browser",
            "2. Sign up with GitHub or Google (free)",
            "3. Go to Keys in their dashboard",
            "4. Create and copy your API key",
            "5. Paste it below and click Save",
        ],
        "free_tier": "Free: $10 in credits to start",
        "required": False,
        "prefix": "",
    },
    {
        "key": "SERPER_API_KEY",
        "name": "Serper (Google Search)",
        "icon": "SRC",
        "what": "Google-quality search results — structured, fast, with knowledge graphs.",
        "unlocks": "serper_search tool (better than DuckDuckGo for factual queries)",
        "signup_url": "https://serper.dev/api-key",
        "steps": [
            "1. Click 'Get Key' below — it opens Serper.dev in your browser",
            "2. Sign up with Google or email (free)",
            "3. Copy your API key from the dashboard",
            "4. Paste it below and click Save",
        ],
        "free_tier": "Free: 2,500 searches/month",
        "required": False,
        "prefix": "",
    },
    {
        "key": "BROWSERBASE_API_KEY",
        "name": "Browserbase",
        "icon": "WWW",
        "what": "Cloud browser — faster web browsing with anti-bot protection.",
        "unlocks": "Upgrades browser from local to cloud (optional)",
        "signup_url": "https://www.browserbase.com/sign-up",
        "steps": [
            "1. Click 'Get Key' below — it opens Browserbase in your browser",
            "2. Sign up (free tier available)",
            "3. Copy your API Key AND Project ID from the dashboard",
            "4. Paste the API key below",
            "5. (You'll also need to set BROWSERBASE_PROJECT_ID in Settings)",
        ],
        "free_tier": "Free tier: 1000 browser sessions/month",
        "required": False,
        "prefix": "",
    },
]


def _save_key_to_env(key: str, value: str):
    """Save an API key to .env file and set it in the current environment."""
    os.environ[key] = value
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = f"^{key}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content += f"\n{replacement}\n"

    with open(env_path, "w", encoding="utf-8") as f:
        f.write(content)


def get_missing_keys():
    """Return list of API services that don't have keys set."""
    missing = []
    for svc in API_SERVICES:
        if not os.getenv(svc["key"]):
            missing.append(svc)
    return missing


def get_key_status():
    """Return dict of key -> bool for all services."""
    return {svc["key"]: bool(os.getenv(svc["key"])) for svc in API_SERVICES}


# ============================================================================
# Setup Wizard GUI
# ============================================================================

class APISetupWizard(tk.Toplevel):
    """
    Step-by-step wizard that walks users through getting API keys.
    Opens signup pages in their real browser, they paste keys back.
    """

    def __init__(self, parent, on_complete=None, auto_mode=False, single_service=None):
        super().__init__(parent)
        self.on_complete = on_complete
        self.auto_mode = auto_mode  # True = only show missing keys
        self.title("Hermes Agent - API Setup")
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        set_dark_title_bar(self)

        from gui.theme import center_window
        center_window(self, 600, 580, parent)

        self.current_step = -1
        self.key_entries = {}
        self.saved_keys = {}

        # Single service mode — jump directly to that service
        if single_service:
            svc = next((s for s in API_SERVICES if s["key"] == single_service), None)
            if svc:
                self.services = [svc]
                self.current_step = 0
                self._show_service(svc)
                return

        # Determine which keys to show
        if auto_mode:
            self.services = get_missing_keys()
        else:
            self.services = list(API_SERVICES)

        self._show_welcome()

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _show_welcome(self):
        self._clear()

        # Header
        hdr = tk.Frame(self, bg=C["bg_main"])
        hdr.pack(fill="x", padx=40, pady=(30, 0))

        tk.Label(hdr, text="API Key Setup", font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(anchor="w")
        tk.Label(hdr, text="Let's unlock Hermes' full power",
                font=FONTS["body"], fg=C["text_secondary"],
                bg=C["bg_main"]).pack(anchor="w", pady=(4, 0))

        # Status overview
        status_frame = tk.Frame(self, bg=C["bg_main"])
        status_frame.pack(fill="x", padx=40, pady=(20, 0))

        tk.Label(status_frame, text="Service Status:",
                font=FONTS["subheading"], fg=C["text_primary"],
                bg=C["bg_main"]).pack(anchor="w", pady=(0, 8))

        for svc in API_SERVICES:
            has_key = bool(os.getenv(svc["key"]))
            dot_color = C["success"] if has_key else (C["danger"] if svc["required"] else C["warning_dark"])
            status_text = "Ready" if has_key else ("Required" if svc["required"] else "Not set")
            hover_bg = C["bg_hover"]

            row = tk.Frame(status_frame, bg=C["bg_main"], cursor="hand2",
                          padx=4, pady=3)
            row.pack(fill="x", pady=1)

            tk.Label(row, text="\u25CF", font=SF("Segoe UI", 10),
                    fg=dot_color, bg=C["bg_main"]).pack(side="left", padx=(0, 8))
            tk.Label(row, text=f"[{svc['icon']}]", font=FONTS["mono_small"],
                    fg=C["text_disabled"], bg=C["bg_main"]).pack(side="left", padx=(0, 6))
            tk.Label(row, text=svc["name"], font=FONTS["body"],
                    fg=C["text_primary"], bg=C["bg_main"]).pack(side="left")
            tk.Label(row, text=status_text, font=FONTS["small"],
                    fg=dot_color, bg=C["bg_main"]).pack(side="right")
            tk.Label(row, text="  Set up", font=SF("Segoe UI", 8, "underline"),
                    fg=C["accent"], bg=C["bg_main"], cursor="hand2").pack(side="right")

            # Click row to set up just that service
            def _on_click(event, s=svc):
                self.services = [s]
                self.current_step = 0
                self._show_service(s)

            row.bind("<Button-1>", _on_click)
            for child in row.winfo_children():
                child.bind("<Button-1>", _on_click)

        # Info
        if not self.services:
            tk.Label(self, text="All API keys are set! You're good to go.",
                    font=FONTS["body"], fg=C["success"],
                    bg=C["bg_main"]).pack(pady=20)
            ttk.Button(self, text="Close", style="Primary.TButton",
                       command=self._finish).pack(pady=10)
        else:
            missing_count = len(self.services)
            tk.Label(self, text=f"\n{missing_count} key{'s' if missing_count > 1 else ''} to set up. "
                    "Each takes about 1 minute.\n"
                    "I'll open the signup page — you handle any CAPTCHAs,\n"
                    "then paste the key back here.",
                    font=FONTS["body"], fg=C["text_secondary"],
                    bg=C["bg_main"], justify="center").pack(pady=(15, 0))

            # Buttons
            btn_frame = tk.Frame(self, bg=C["bg_main"])
            btn_frame.pack(pady=20)

            ttk.Button(btn_frame, text="Let's Go!", style="Primary.TButton",
                       command=self._next_step).pack(side="left", padx=4)
            ttk.Button(btn_frame, text="Skip All", style="TButton",
                       command=self._finish).pack(side="left", padx=4)

    def _next_step(self):
        self.current_step += 1
        if self.current_step >= len(self.services):
            self._show_done()
            return
        self._show_service(self.services[self.current_step])

    def _show_service(self, svc):
        self._clear()

        key_name = svc["key"]
        step_num = self.current_step + 1
        total = len(self.services)

        # Progress bar
        prog_frame = tk.Frame(self, bg=C["bg_sidebar"], height=4)
        prog_frame.pack(fill="x")
        prog_frame.pack_propagate(False)
        pct = step_num / total
        prog_fill = tk.Frame(prog_frame, bg=C["accent"], width=int(600 * pct))
        prog_fill.pack(side="left", fill="y")

        # Header
        hdr = tk.Frame(self, bg=C["bg_main"])
        hdr.pack(fill="x", padx=40, pady=(20, 0))

        tk.Label(hdr, text=f"Step {step_num} of {total}",
                font=FONTS["small"], fg=C["text_hint"],
                bg=C["bg_main"]).pack(anchor="w")
        tk.Label(hdr, text=f"[{svc['icon']}] {svc['name']}",
                font=FONTS["heading"], fg=C["accent"],
                bg=C["bg_main"]).pack(anchor="w", pady=(4, 0))
        tk.Label(hdr, text=svc["what"], font=FONTS["body"],
                fg=C["text_primary"], bg=C["bg_main"]).pack(anchor="w", pady=(4, 0))

        # Unlocks
        tk.Label(hdr, text=f"Unlocks: {svc['unlocks']}",
                font=FONTS["small"], fg=C["success"],
                bg=C["bg_main"]).pack(anchor="w", pady=(2, 0))
        tk.Label(hdr, text=svc["free_tier"],
                font=FONTS["small"], fg=C["warning_dark"],
                bg=C["bg_main"]).pack(anchor="w")

        # Steps
        steps_frame = tk.Frame(self, bg=C["bg_card"], padx=16, pady=12,
                              highlightbackground=C["border"], highlightthickness=1)
        steps_frame.pack(fill="x", padx=40, pady=(16, 0))

        for step_text in svc["steps"]:
            tk.Label(steps_frame, text=step_text, font=FONTS["body"],
                    fg=C["text_primary"], bg=C["bg_card"],
                    anchor="w", justify="left").pack(fill="x", pady=1)

        # Open browser button
        btn_frame = tk.Frame(self, bg=C["bg_main"])
        btn_frame.pack(fill="x", padx=40, pady=(16, 0))

        open_btn = ttk.Button(btn_frame, text=f"Get Key  (opens {svc['name']} in your browser)",
                             style="Primary.TButton",
                             command=lambda: webbrowser.open(svc["signup_url"]))
        open_btn.pack(fill="x")
        Tooltip(open_btn, f"Opens {svc['signup_url']} in your default browser")

        # Key entry
        entry_frame = tk.Frame(self, bg=C["bg_main"])
        entry_frame.pack(fill="x", padx=40, pady=(16, 0))

        tk.Label(entry_frame, text="Paste your key here:",
                font=FONTS["small"], fg=C["text_secondary"],
                bg=C["bg_main"]).pack(anchor="w")

        key_entry = tk.Entry(entry_frame, font=FONTS["mono"],
                            bg=C["bg_input"], fg=C["text_primary"],
                            insertbackground=C["text_primary"],
                            relief="flat")
        key_entry.pack(fill="x", ipady=8, pady=(4, 0))

        # Pre-fill if already set
        current = os.getenv(key_name, "")
        if current:
            key_entry.insert(0, current)

        self.key_entries[key_name] = key_entry

        # Auto-detect from clipboard button
        clip_frame = tk.Frame(entry_frame, bg=C["bg_main"])
        clip_frame.pack(fill="x", pady=(6, 0))

        ttk.Button(clip_frame, text="Paste from Clipboard",
                   style="Small.TButton",
                   command=lambda: self._paste_from_clipboard(key_entry)).pack(side="left")

        tk.Label(clip_frame, text="  Copy the key on the website, then click this",
                font=SF("Segoe UI", 8), fg=C["text_hint"],
                bg=C["bg_main"]).pack(side="left")

        # Status label
        self.status_label = tk.Label(entry_frame, text="", font=FONTS["small"],
                                    bg=C["bg_main"])
        self.status_label.pack(anchor="w", pady=(4, 0))

        # Snapshot current clipboard so we only auto-fill on NEW copies
        try:
            self._clip_snapshot = self.clipboard_get().strip()
        except tk.TclError:
            self._clip_snapshot = ""

        # Auto-poll clipboard for key changes
        self._poll_clipboard(key_entry, svc)

        # Bottom buttons
        bottom = tk.Frame(self, bg=C["bg_main"])
        bottom.pack(fill="x", padx=40, pady=(20, 0))

        ttk.Button(bottom, text="Save & Next", style="Primary.TButton",
                   command=lambda: self._save_current(svc)).pack(side="right")
        ttk.Button(bottom, text="Skip", style="TButton",
                   command=self._next_step).pack(side="right", padx=(0, 8))

        # Focus the entry
        key_entry.focus_set()

        # Bind Enter to save
        key_entry.bind("<Return>", lambda e: self._save_current(svc))

    def _paste_from_clipboard(self, entry):
        """Paste clipboard contents into the entry field."""
        try:
            clip = self.clipboard_get().strip()
            if clip:
                entry.delete(0, "end")
                entry.insert(0, clip)
        except tk.TclError:
            pass  # Clipboard empty or not text

    def _poll_clipboard(self, entry, svc):
        """Auto-detect NEW API key appearing in clipboard after user copies it."""
        if not self.winfo_exists():
            return
        try:
            clip = self.clipboard_get().strip()
        except tk.TclError:
            clip = ""

        # Only act if clipboard CHANGED since we opened this step
        # (prevents stale key from previous service auto-filling)
        if clip and clip != self._clip_snapshot:
            current = entry.get().strip()
            prefix = svc.get("prefix", "")
            is_key = False

            if prefix and clip.startswith(prefix) and len(clip) > 20:
                is_key = True
            elif not prefix and len(clip) > 20 and " " not in clip and "\n" not in clip:
                is_key = True

            if is_key and clip != current:
                entry.delete(0, "end")
                entry.insert(0, clip)
                self._clip_snapshot = clip  # Don't re-trigger
                self.status_label.configure(
                    text="Key detected from clipboard!",
                    fg=C["success"])

        # Poll every 2 seconds
        try:
            self.after(2000, lambda: self._poll_clipboard(entry, svc))
        except tk.TclError:
            pass

    def _save_current(self, svc):
        key_name = svc["key"]
        entry = self.key_entries.get(key_name)
        if not entry:
            self._next_step()
            return

        value = entry.get().strip()
        if not value:
            self.status_label.configure(text="No key entered — skipping.",
                                       fg=C["warning_dark"])
            self.after(1000, self._next_step)
            return

        # Basic validation
        if svc.get("prefix") and not value.startswith(svc["prefix"]):
            self.status_label.configure(
                text=f"Key usually starts with '{svc['prefix']}' — saving anyway.",
                fg=C["warning_dark"])

        # Save it
        _save_key_to_env(key_name, value)
        self.saved_keys[key_name] = True
        self.status_label.configure(text="Saved!", fg=C["success"])
        self.after(500, self._next_step)

    def _show_done(self):
        self._clear()

        # Progress complete
        prog_frame = tk.Frame(self, bg=C["accent"], height=4)
        prog_frame.pack(fill="x")

        tk.Label(self, text="Setup Complete!", font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(pady=(40, 8))

        saved_count = len(self.saved_keys)
        if saved_count > 0:
            tk.Label(self, text=f"{saved_count} API key{'s' if saved_count > 1 else ''} saved successfully.",
                    font=FONTS["body"], fg=C["success"],
                    bg=C["bg_main"]).pack()
        else:
            tk.Label(self, text="No new keys were added.",
                    font=FONTS["body"], fg=C["text_hint"],
                    bg=C["bg_main"]).pack()

        # Final status
        status_frame = tk.Frame(self, bg=C["bg_main"])
        status_frame.pack(fill="x", padx=40, pady=(20, 0))

        for svc in API_SERVICES:
            row = tk.Frame(status_frame, bg=C["bg_main"])
            row.pack(fill="x", pady=2)

            has_key = bool(os.getenv(svc["key"]))
            dot_color = C["success"] if has_key else C["text_disabled"]

            tk.Label(row, text="\u25CF", font=SF("Segoe UI", 10),
                    fg=dot_color, bg=C["bg_main"]).pack(side="left", padx=(0, 8))
            tk.Label(row, text=svc["name"], font=FONTS["body"],
                    fg=C["text_primary"], bg=C["bg_main"]).pack(side="left")
            tk.Label(row, text="Ready" if has_key else "Not set",
                    font=FONTS["small"], fg=dot_color,
                    bg=C["bg_main"]).pack(side="right")

        tk.Label(self, text="\nYou can always add more keys later from\n"
                "File > API Key Setup or Settings.",
                font=FONTS["small"], fg=C["text_hint"],
                bg=C["bg_main"], justify="center").pack(pady=(20, 0))

        ttk.Button(self, text="Start Chatting!", style="Primary.TButton",
                   command=self._finish).pack(pady=20)

    def _finish(self):
        if self.on_complete:
            self.on_complete(self.saved_keys)
        self.destroy()
