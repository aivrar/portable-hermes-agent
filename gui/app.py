"""
Hermes Agent - Windows Desktop GUI
Styled to match ImageBuddy/ImageDownloader visual design.
Pure tkinter + ttk, dark theme, flat design.
"""
import os
import sys
import re
import io
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image, ImageTk
    import httpx
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gui.theme import C, FONTS, apply_theme, set_dark_title_bar, Tooltip, center_window
from gui.agent_bridge import AgentBridge
from gui.api_setup_wizard import APISetupWizard, get_missing_keys
from gui.extensions import ExtensionsManager
from gui.lm_studio import LMStudioPanel
from gui.permissions_panel import PermissionsPanel
from gui.permissions import load_permissions, get_permissions_summary


# ============================================================================
# Chat Message Widgets
# ============================================================================

class MessageBubble(tk.Frame):
    """A single chat message."""

    def __init__(self, parent, text, msg_type="user", tool_name=None):
        super().__init__(parent, bg=C["bg_main"])

        if msg_type == "user":
            bg, border, label, label_fg = C["msg_user"], C["msg_user_border"], "You", C["accent"]
        elif msg_type == "ai":
            bg, border, label, label_fg = C["msg_ai"], C["msg_ai_border"], "Hermes", C["success"]
        elif msg_type == "tool":
            bg, border = C["msg_tool"], C["msg_tool_border"]
            label, label_fg = f"Tool: {tool_name or '?'}", C["warning_dark"]
        elif msg_type == "error":
            bg, border, label, label_fg = C["msg_error"], C["msg_error_border"], "Error", C["danger"]
        else:  # system
            bg, border, label, label_fg = C["msg_system"], C["msg_system_border"], "System", C["text_hint"]

        # Outer padding
        pad = tk.Frame(self, bg=C["bg_main"])
        pad.pack(fill="x", padx=16, pady=3)

        # Card
        card = tk.Frame(pad, bg=bg, highlightbackground=border,
                       highlightthickness=1, padx=12, pady=8)
        if msg_type == "user":
            card.pack(side="right", anchor="e")
        else:
            card.pack(side="left", anchor="w", fill="x", expand=True)

        # Header row
        hdr = tk.Frame(card, bg=bg)
        hdr.pack(fill="x")

        tk.Label(hdr, text=label, font=FONTS["small"] + ("bold",),
                fg=label_fg, bg=bg).pack(side="left")

        ts = datetime.now().strftime("%H:%M")
        tk.Label(hdr, text=ts, font=("Segoe UI", 8),
                fg=C["text_disabled"], bg=bg).pack(side="right")

        # Check for markdown images: ![alt](url)
        self._images = []  # Keep references so GC doesn't kill them
        image_pattern = r'!\[([^\]]*)\]\((https?://[^\)]+)\)'
        image_matches = list(re.finditer(image_pattern, text))

        # Strip image markdown from text for display
        display_text = re.sub(image_pattern, '', text).strip()

        # Message body (text part)
        if display_text:
            body = tk.Text(card, wrap="word", bg=bg, fg=C["text_primary"],
                          font=FONTS["body"], relief="flat", borderwidth=0,
                          padx=0, pady=2, cursor="arrow",
                          selectbackground=C["accent"], selectforeground="white",
                          highlightthickness=0)
            body.insert("1.0", display_text)
            body.configure(state="disabled")

            lines = max(1, display_text.count('\n') + 1)
            for line in display_text.split('\n'):
                lines += max(0, len(line) // 70)
            body.configure(height=min(lines, 25))
            body.pack(fill="x")

            body.bind("<Button-3>", lambda e: self._ctx_menu(e, body))

        # Render images inline
        if HAS_PIL and image_matches:
            for match in image_matches:
                alt_text = match.group(1)
                url = match.group(2)
                img_frame = tk.Frame(card, bg=bg)
                img_frame.pack(fill="x", pady=(6, 2))

                # Loading label (replaced by image when downloaded)
                loading = tk.Label(img_frame, text=f"Loading image...",
                                  font=FONTS["small"], fg=C["text_hint"], bg=bg)
                loading.pack()

                # Download and display in background
                threading.Thread(target=self._load_image,
                               args=(img_frame, loading, url, alt_text, bg),
                               daemon=True).start()
        elif image_matches and not HAS_PIL:
            # Fallback: show clickable link
            for match in image_matches:
                url = match.group(2)
                link = tk.Label(card, text=f"[Image: {url}]",
                               font=FONTS["small"], fg=C["accent"], bg=bg,
                               cursor="hand2")
                link.pack(fill="x", pady=(4, 0))
                link.bind("<Button-1>", lambda e, u=url: __import__('webbrowser').open(u))

    def _ctx_menu(self, event, tw):
        menu = tk.Menu(self, tearoff=0,
                      bg=C["bg_card"], fg=C["text_primary"],
                      activebackground=C["accent"], activeforeground="white")
        menu.add_command(label="Copy All", command=lambda: self._copy(tw))
        menu.add_command(label="Select All", command=lambda: self._select_all(tw))
        menu.post(event.x_root, event.y_root)

    def _copy(self, tw):
        tw.configure(state="normal")
        txt = tw.get("1.0", "end-1c")
        tw.configure(state="disabled")
        self.clipboard_clear()
        self.clipboard_append(txt)

    def _select_all(self, tw):
        tw.configure(state="normal")
        tw.tag_add("sel", "1.0", "end-1c")
        tw.configure(state="disabled")

    def _load_image(self, frame, loading_label, url, alt_text, bg):
        """Download image from URL and display it inline."""
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            img_data = resp.content

            img = Image.open(io.BytesIO(img_data))

            # Resize to fit chat area (max 400px wide, maintain aspect ratio)
            max_w = 400
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

            # Convert to tkinter-compatible image
            tk_img = ImageTk.PhotoImage(img)

            # Must update GUI from main thread
            def _show():
                try:
                    loading_label.destroy()
                    img_label = tk.Label(frame, image=tk_img, bg=bg, cursor="hand2")
                    img_label.pack()
                    # Keep reference so GC doesn't destroy it
                    self._images.append(tk_img)
                    # Click to open full size in browser
                    img_label.bind("<Button-1>",
                                  lambda e: __import__('webbrowser').open(url))
                    # Tooltip
                    from gui.theme import Tooltip
                    Tooltip(img_label, f"Click to open full size\n{alt_text}")
                except tk.TclError:
                    pass

            frame.after(0, _show)

        except Exception as e:
            def _show_error():
                try:
                    loading_label.configure(text=f"Could not load image: {e}",
                                           fg=C["danger"])
                except tk.TclError:
                    pass
            frame.after(0, _show_error)


class ToolCallWidget(tk.Frame):
    """Compact tool-call indicator."""

    def __init__(self, parent, tool_name, args_preview):
        super().__init__(parent, bg=C["bg_main"])

        pad = tk.Frame(self, bg=C["bg_main"])
        pad.pack(fill="x", padx=16, pady=1)

        card = tk.Frame(pad, bg=C["msg_tool"], highlightbackground=C["msg_tool_border"],
                       highlightthickness=1, padx=8, pady=4)
        card.pack(side="left", fill="x", expand=True)

        row = tk.Frame(card, bg=C["msg_tool"])
        row.pack(fill="x")

        tk.Label(row, text="\u25B6", font=("Segoe UI", 8),
                fg=C["warning_dark"], bg=C["msg_tool"]).pack(side="left", padx=(0, 6))
        tk.Label(row, text=tool_name, font=FONTS["mono_small"] + ("bold",),
                fg=C["accent"], bg=C["msg_tool"]).pack(side="left")

        if args_preview:
            preview = str(args_preview)[:100]
            if len(str(args_preview)) > 100:
                preview += "..."
            tk.Label(card, text=preview, font=FONTS["mono_small"],
                    fg=C["text_hint"], bg=C["msg_tool"],
                    wraplength=500, justify="left", anchor="w").pack(fill="x")


class ThinkingIndicator(tk.Frame):
    """Animated thinking dots."""

    def __init__(self, parent):
        super().__init__(parent, bg=C["bg_main"])
        self._alive = False
        self._dots = 0

        pad = tk.Frame(self, bg=C["bg_main"])
        pad.pack(fill="x", padx=16, pady=4)

        card = tk.Frame(pad, bg=C["bg_card"], highlightbackground=C["info"],
                       highlightthickness=1, padx=12, pady=6)
        card.pack(side="left")

        self._label = tk.Label(card, text="Hermes is thinking",
                              font=FONTS["small"] + ("italic",),
                              fg=C["info"], bg=C["bg_card"])
        self._label.pack(side="left")

        self._dots_label = tk.Label(card, text="", width=4,
                                   font=FONTS["body"],
                                   fg=C["info"], bg=C["bg_card"])
        self._dots_label.pack(side="left")

    def start(self):
        self._alive = True
        self._tick()

    def stop(self):
        self._alive = False

    def _tick(self):
        if not self._alive:
            return
        try:
            self._dots = (self._dots + 1) % 4
            self._dots_label.configure(text="." * self._dots)
            self.after(400, self._tick)
        except tk.TclError:
            pass  # Widget was destroyed


# ============================================================================
# Sidebar
# ============================================================================

class Sidebar(tk.Frame):
    """Left sidebar with branding, new-chat, session history, and model switcher."""

    MODELS = [
        ("google/gemini-2.5-flash", "Gemini Flash", "Fast & cheap"),
        ("google/gemini-2.5-pro", "Gemini Pro", "Smart & affordable"),
        ("anthropic/claude-sonnet-4", "Claude Sonnet", "Great all-rounder"),
        ("anthropic/claude-opus-4.6", "Claude Opus", "Most capable"),
        ("openai/gpt-4o", "GPT-4o", "OpenAI flagship"),
        ("openai/gpt-4o-mini", "GPT-4o Mini", "Fast & cheap"),
        ("deepseek/deepseek-chat-v3", "DeepSeek V3", "Strong & cheap"),
        ("meta-llama/llama-4-maverick", "Llama Maverick", "Open source"),
    ]

    def __init__(self, parent, on_new=None, on_model_change=None,
                 on_session_select=None, **kw):
        super().__init__(parent, bg=C["bg_sidebar"], width=260, **kw)
        self.pack_propagate(False)
        self.on_new = on_new
        self.on_model_change = on_model_change
        self.on_session_select = on_session_select
        self._confirm_delete = True  # Show confirmation dialog

        # -- Logo --
        logo_fr = tk.Frame(self, bg=C["bg_sidebar"], pady=16, padx=16)
        logo_fr.pack(fill="x")
        tk.Label(logo_fr, text="HERMES", font=FONTS["logo"],
                fg=C["accent"], bg=C["bg_sidebar"]).pack(side="left")
        tk.Label(logo_fr, text="AGENT", font=FONTS["logo_sub"],
                fg=C["text_secondary"], bg=C["bg_sidebar"]).pack(side="left", padx=(6, 0))

        # -- New Chat button --
        btn_fr = tk.Frame(self, bg=C["bg_sidebar"], padx=16)
        btn_fr.pack(fill="x")
        self.new_btn = ttk.Button(btn_fr, text="+ New Chat", style="Primary.TButton",
                                  command=self._on_new)
        self.new_btn.pack(fill="x", pady=(0, 8))

        # -- Model Switcher --
        model_fr = tk.Frame(self, bg=C["bg_sidebar"], padx=16)
        model_fr.pack(fill="x")

        tk.Label(model_fr, text="Model:", font=FONTS["small"],
                fg=C["text_hint"], bg=C["bg_sidebar"]).pack(anchor="w")

        self.model_var = tk.StringVar(value=os.getenv("LLM_MODEL", "google/gemini-2.5-flash"))
        display_values = [f"{name}  ({note})" for _, name, note in self.MODELS]
        self.model_combo = ttk.Combobox(model_fr, textvariable=tk.StringVar(),
                                        values=display_values,
                                        font=FONTS["small"], state="readonly")
        # Set current selection
        current_model = self.model_var.get()
        for i, (model_id, _, _) in enumerate(self.MODELS):
            if model_id == current_model:
                self.model_combo.current(i)
                break
        else:
            # Custom model not in list — show raw ID
            self.model_combo.set(current_model)

        self.model_combo.pack(fill="x", pady=(2, 8))
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_selected)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # -- Sessions header --
        tk.Label(self, text="Recent Sessions", font=FONTS["small"],
                fg=C["text_hint"], bg=C["bg_sidebar"], padx=16, pady=8,
                anchor="w").pack(fill="x")

        # -- Session list (scrollable) --
        self.session_canvas = tk.Canvas(self, bg=C["bg_sidebar"],
                                        highlightthickness=0, borderwidth=0)
        self.session_canvas.pack(fill="both", expand=True, padx=4)

        self.session_frame = tk.Frame(self.session_canvas, bg=C["bg_sidebar"])
        self.session_canvas.create_window((0, 0), window=self.session_frame, anchor="nw",
                                          tags="inner")
        self.session_frame.bind("<Configure>", lambda e: self.session_canvas.configure(
            scrollregion=self.session_canvas.bbox("all")))
        self.session_canvas.bind("<Configure>", lambda e: self.session_canvas.itemconfig(
            "inner", width=e.width))

        # Mouse wheel on session list
        def _sw(event):
            self.session_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.session_canvas.bind("<MouseWheel>", _sw)
        self.session_frame.bind("<MouseWheel>", _sw)

        # Load sessions on startup
        self.after(500, self._load_sessions)

    def set_model(self, name):
        self.model_var.set(name)
        for i, (model_id, _, _) in enumerate(self.MODELS):
            if model_id == name:
                self.model_combo.current(i)
                return
        self.model_combo.set(name)

    def _on_new(self):
        if self.on_new:
            self.on_new()

    def _on_model_selected(self, event):
        idx = self.model_combo.current()
        if 0 <= idx < len(self.MODELS):
            model_id = self.MODELS[idx][0]
            self.model_var.set(model_id)
            if self.on_model_change:
                self.on_model_change(model_id)

    def _load_sessions(self):
        """Load recent sessions from SessionDB."""
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            sessions = db.list_sessions_rich(source=None, limit=20)
            for widget in self.session_frame.winfo_children():
                widget.destroy()
            if not sessions:
                tk.Label(self.session_frame, text="No past sessions yet",
                        font=FONTS["small"], fg=C["text_disabled"],
                        bg=C["bg_sidebar"], padx=12).pack(anchor="w", pady=4)
                return
            for sess in sessions:
                self._add_session_entry(sess)
        except Exception:
            tk.Label(self.session_frame, text="No sessions found",
                    font=FONTS["small"], fg=C["text_disabled"],
                    bg=C["bg_sidebar"], padx=12).pack(anchor="w", pady=4)

    def _add_session_entry(self, sess):
        sid = sess.get("id", "")
        title = sess.get("title") or sess.get("preview", "Untitled")
        if len(title) > 35:
            title = title[:32] + "..."
        model = sess.get("model", "")
        msg_count = sess.get("message_count", 0)

        entry = tk.Frame(self.session_frame, bg=C["bg_sidebar"], padx=12, pady=4,
                        cursor="hand2")
        entry.pack(fill="x", pady=1)

        # Top row: title + delete button
        top_row = tk.Frame(entry, bg=C["bg_sidebar"])
        top_row.pack(fill="x")

        tk.Label(top_row, text=title, font=FONTS["small"],
                fg=C["text_primary"], bg=C["bg_sidebar"],
                anchor="w", wraplength=190).pack(side="left", fill="x", expand=True)

        # Delete button (only visible on hover)
        del_btn = tk.Label(top_row, text="\u2715", font=("Segoe UI", 9),
                          fg=C["bg_sidebar"], bg=C["bg_sidebar"],
                          cursor="hand2", padx=4)
        del_btn.pack(side="right")
        del_btn.bind("<Button-1>", lambda e, s=sid: self._delete_session(s))

        info_text = f"{msg_count} msgs"
        if model:
            short_model = model.split("/")[-1][:15]
            info_text += f" | {short_model}"

        tk.Label(entry, text=info_text, font=("Segoe UI", 8),
                fg=C["text_disabled"], bg=C["bg_sidebar"],
                anchor="w").pack(fill="x")

        # Hover effect — show delete button on hover
        def _enter(e, f=entry, d=del_btn):
            f.configure(bg=C["bg_hover"])
            for c in f.winfo_children():
                c.configure(bg=C["bg_hover"])
                for gc in c.winfo_children():
                    gc.configure(bg=C["bg_hover"])
            d.configure(fg=C["danger"])  # Show the X

        def _leave(e, f=entry, d=del_btn):
            f.configure(bg=C["bg_sidebar"])
            for c in f.winfo_children():
                c.configure(bg=C["bg_sidebar"])
                for gc in c.winfo_children():
                    gc.configure(bg=C["bg_sidebar"])
            d.configure(fg=C["bg_sidebar"])  # Hide the X

        entry.bind("<Enter>", _enter)
        entry.bind("<Leave>", _leave)
        for child in entry.winfo_children():
            child.bind("<Enter>", _enter)
            child.bind("<Leave>", _leave)
            for gc in child.winfo_children():
                gc.bind("<Enter>", _enter)
                gc.bind("<Leave>", _leave)
                if gc != del_btn:
                    gc.bind("<Button-1>", lambda e, s=sid: self._select_session(s))
        entry.bind("<Button-1>", lambda e, s=sid: self._select_session(s))
        entry.bind("<MouseWheel>", lambda e: self.session_canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"))

    def _select_session(self, session_id):
        if self.on_session_select:
            self.on_session_select(session_id)

    def _delete_session(self, session_id):
        """Delete a session with optional confirmation dialog."""
        if self._confirm_delete:
            # Custom dialog with "don't show again" checkbox
            dlg = tk.Toplevel(self)
            dlg.title("Delete Session")
            dlg.geometry("380x180")
            dlg.configure(bg=C["bg_main"])
            dlg.transient(self.winfo_toplevel())
            dlg.grab_set()
            set_dark_title_bar(dlg)
            center_window(dlg, 380, 180, self.winfo_toplevel())

            tk.Label(dlg, text="Delete this session?",
                    font=FONTS["subheading"], fg=C["text_primary"],
                    bg=C["bg_main"]).pack(pady=(20, 4))
            tk.Label(dlg, text="This will permanently remove the conversation\n"
                    "and all its messages. This cannot be undone.",
                    font=FONTS["small"], fg=C["text_hint"],
                    bg=C["bg_main"], justify="center").pack(pady=(0, 12))

            # Don't show again checkbox
            dont_ask = tk.BooleanVar(value=False)
            tk.Checkbutton(dlg, text="Don't ask me again",
                          variable=dont_ask, font=FONTS["small"],
                          fg=C["text_secondary"], bg=C["bg_main"],
                          selectcolor=C["bg_input"],
                          activebackground=C["bg_main"],
                          activeforeground=C["text_primary"]).pack()

            btn_frame = tk.Frame(dlg, bg=C["bg_main"])
            btn_frame.pack(pady=12)

            def _do_delete():
                if dont_ask.get():
                    self._confirm_delete = False
                dlg.destroy()
                self._perform_delete(session_id)

            ttk.Button(btn_frame, text="Delete", style="Danger.TButton",
                       command=_do_delete).pack(side="left", padx=4)
            ttk.Button(btn_frame, text="Cancel", style="TButton",
                       command=dlg.destroy).pack(side="left", padx=4)
        else:
            self._perform_delete(session_id)

    def _perform_delete(self, session_id):
        """Actually delete the session from the database."""
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            db.delete_session(session_id)
        except Exception:
            try:
                # Fallback: try direct SQL if method doesn't exist
                import sqlite3
                from hermes_state import DEFAULT_DB_PATH
                conn = sqlite3.connect(str(DEFAULT_DB_PATH))
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                conn.commit()
                conn.close()
            except Exception:
                pass
        self._load_sessions()

    def refresh_sessions(self):
        self._load_sessions()


# ============================================================================
# Settings Dialog
# ============================================================================

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, bridge):
        super().__init__(parent)
        self.bridge = bridge
        self.title("Settings")
        self.geometry("550x480")
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        self.grab_set()
        set_dark_title_bar(self)
        center_window(self, 550, 480, parent)

        tk.Label(self, text="Settings", font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(pady=(20, 8))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=16, pady=8)

        # -- API Keys tab --
        api_fr = tk.Frame(nb, bg=C["bg_main"], padx=16, pady=16)
        nb.add(api_fr, text="  API Keys  ")
        self._build_api(api_fr)

        # -- Model tab --
        mdl_fr = tk.Frame(nb, bg=C["bg_main"], padx=16, pady=16)
        nb.add(mdl_fr, text="  Model  ")
        self._build_model(mdl_fr)

        ttk.Button(self, text="Save & Close", style="Primary.TButton",
                   command=self._save).pack(pady=(4, 16))

    def _build_api(self, parent):
        keys = [
            ("OPENROUTER_API_KEY", "OpenRouter (main LLM provider)"),
            ("FIRECRAWL_API_KEY", "Firecrawl (web search)"),
            ("FAL_KEY", "FAL.ai (image generation)"),
            ("SERPER_API_KEY", "Serper.dev (Google search)"),
            ("VOICE_TOOLS_OPENAI_KEY", "OpenAI (voice/transcription)"),
            ("GITHUB_TOKEN", "GitHub (Skills Hub rate limits)"),
        ]
        self.key_entries = {}
        for key, label in keys:
            tk.Label(parent, text=label, font=FONTS["small"],
                    fg=C["text_secondary"], bg=C["bg_main"]).pack(anchor="w", pady=(6, 0))
            ent = tk.Entry(parent, font=FONTS["mono_small"],
                          bg=C["bg_input"], fg=C["text_primary"],
                          insertbackground=C["text_primary"],
                          relief="flat", show="*")
            ent.pack(fill="x", ipady=4)
            cur = os.getenv(key, "")
            if cur:
                ent.insert(0, cur)
            self.key_entries[key] = ent

    def _build_model(self, parent):
        tk.Label(parent, text="Default Model", font=FONTS["small"],
                fg=C["text_secondary"], bg=C["bg_main"]).pack(anchor="w")

        models = [
            "google/gemini-2.5-flash",
            "google/gemini-2.5-pro",
            "anthropic/claude-sonnet-4",
            "anthropic/claude-opus-4.6",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "openai/o3-mini",
            "meta-llama/llama-4-maverick",
            "deepseek/deepseek-chat-v3",
            "qwen/qwen3-235b-a22b",
        ]
        self.model_var = tk.StringVar(value=os.getenv("LLM_MODEL", "google/gemini-2.5-flash"))
        self.model_combo = ttk.Combobox(parent, textvariable=self.model_var,
                                        values=models, font=FONTS["mono_small"])
        self.model_combo.pack(fill="x", pady=(4, 12))
        tk.Label(parent, text="You can type any OpenRouter model ID",
                font=("Segoe UI", 8), fg=C["text_disabled"], bg=C["bg_main"]).pack(anchor="w")

    def _save(self):
        env_path = PROJECT_ROOT / ".env"
        if not env_path.exists():
            self.destroy()
            return
        import re
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()
        for key, ent in self.key_entries.items():
            val = ent.get().strip()
            if val:
                os.environ[key] = val
                pat = f"^{key}=.*$"
                repl = f"{key}={val}"
                if re.search(pat, content, re.MULTILINE):
                    content = re.sub(pat, repl, content, flags=re.MULTILINE)
                else:
                    content += f"\n{key}={val}\n"
        model = self.model_var.get().strip()
        if model:
            os.environ["LLM_MODEL"] = model
            content = re.sub(r"^LLM_MODEL=.*$", f"LLM_MODEL={model}", content, flags=re.MULTILINE)
            self.bridge.set_model(model)
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
        self.destroy()


# ============================================================================
# Skills Browser
# ============================================================================

class SkillsBrowser(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Skills Browser")
        self.geometry("650x500")
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        set_dark_title_bar(self)
        center_window(self, 650, 500, parent)

        tk.Label(self, text="Installed Skills", font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(pady=(20, 8))

        self.text = tk.Text(self, wrap="word", bg=C["bg_card"], fg=C["text_primary"],
                           font=FONTS["mono_small"], relief="flat", padx=16, pady=12,
                           highlightthickness=0)
        sb = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 16), pady=(0, 16))
        self.text.pack(fill="both", expand=True, padx=(16, 0), pady=(0, 16))

        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            skills_dir = Path.home() / ".hermes" / "skills"
            if not skills_dir.exists():
                self.after(0, lambda: self._set("No skills directory found."))
                return
            cats = {}
            for d in sorted(skills_dir.iterdir()):
                if d.is_dir() and not d.name.startswith('.'):
                    cat = "uncategorized"
                    desc = ""
                    meta = d / "metadata.yaml"
                    if meta.exists():
                        try:
                            import yaml
                            with open(meta, "r", encoding="utf-8") as f:
                                m = yaml.safe_load(f) or {}
                            cat = m.get("category", cat)
                            desc = m.get("description", "")
                        except Exception:
                            pass
                    cats.setdefault(cat, []).append((d.name, desc))
            lines = []
            for cat in sorted(cats):
                lines.append(f"\n  {cat.upper()}")
                lines.append("  " + "-" * 40)
                for n, d in cats[cat]:
                    lines.append(f"    {n:30s} {d[:50]}" if d else f"    {n}")
            self.after(0, lambda: self._set("\n".join(lines) or "No skills found."))
        except Exception as e:
            self.after(0, lambda: self._set(f"Error: {e}"))

    def _set(self, txt):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", txt)
        self.text.configure(state="disabled")


# ============================================================================
# Status Bar
# ============================================================================

class StatusBar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C["bg_sidebar"], height=28)
        self.pack_propagate(False)

        self.dot = tk.Label(self, text="\u25CF", font=("Segoe UI", 10),
                           fg=C["success"], bg=C["bg_sidebar"])
        self.dot.pack(side="left", padx=(12, 4))

        self.status_lbl = tk.Label(self, text="Ready", font=FONTS["small"],
                                  fg=C["text_hint"], bg=C["bg_sidebar"])
        self.status_lbl.pack(side="left")

        self.model_lbl = tk.Label(self, text="", font=FONTS["mono_small"],
                                 fg=C["text_disabled"], bg=C["bg_sidebar"])
        self.model_lbl.pack(side="right", padx=12)

        self.iter_lbl = tk.Label(self, text="", font=FONTS["mono_small"],
                                fg=C["text_disabled"], bg=C["bg_sidebar"])
        self.iter_lbl.pack(side="right", padx=8)

    def set_ready(self):
        self.dot.configure(fg=C["success"])
        self.status_lbl.configure(text="Ready")

    def set_thinking(self, text=""):
        self.dot.configure(fg=C["info"])
        if text:
            # Truncate to fit status bar width
            display = text[:120] if len(text) > 120 else text
            self.status_lbl.configure(text=display)
        else:
            self.status_lbl.configure(text="Thinking...")

    def set_tool(self, name):
        self.dot.configure(fg=C["warning_dark"])
        self.status_lbl.configure(text=f"Running: {name}")

    def set_error(self):
        self.dot.configure(fg=C["danger"])
        self.status_lbl.configure(text="Error")

    def set_model(self, m):
        self.model_lbl.configure(text=m)

    def set_iter(self, n):
        self.iter_lbl.configure(text=f"Step {n}")


# ============================================================================
# Main Application
# ============================================================================

class HermesGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Hermes Agent")
        self.root.geometry("1100x700")
        self.root.minsize(900, 550)

        # Apply full theme
        apply_theme(self.root)

        # Center main window on screen
        center_window(self.root, 1100, 700)

        # Agent bridge
        self.bridge = AgentBridge(
            self.root,
            on_response=self._on_response,
            on_tool_call=self._on_tool_call,
            on_thinking=self._on_thinking,
            on_error=self._on_error,
            on_step=self._on_step,
            on_clarify=self._on_clarify,
            on_complete=self._on_complete,
            on_approval=self._on_approval,
            on_reasoning=self._on_reasoning,
        )
        self.thinking_widget = None

        self._build_menu()
        self._build_layout()

        # First-run wizard — show if any required keys are missing
        missing = get_missing_keys()
        if any(s["required"] for s in missing):
            self.root.after(500, self._show_api_setup)

        model = self.bridge.get_model()
        self.status_bar.set_model(model)
        self.sidebar.set_model(model)

        # Show context-aware welcome message
        has_key = bool(self.bridge.get_api_key())
        if has_key:
            self._add_msg(
                "Welcome to Hermes Agent!\n"
                "Type a message below and press Enter to chat.\n"
                "Shift+Enter for newlines. Escape to interrupt.",
                "system"
            )
        else:
            self._add_msg(
                "Welcome to Hermes Agent!\n\n"
                "No AI model is connected yet, but that's OK!\n"
                "I'm running in guided mode \u2014 ask me anything and I'll "
                "search the built-in guide for answers.\n\n"
                "Try typing:\n"
                "  \u2022 How do I get started?\n"
                "  \u2022 What is OpenRouter?\n"
                "  \u2022 How do I use local models?\n"
                "  \u2022 What can Hermes do?\n\n"
                "Or go to File > API Key Setup to connect an AI model.",
                "system"
            )

        self.root.bind("<Control-n>", lambda e: self._new_chat())
        self.root.bind("<Control-comma>", lambda e: self._open_settings())
        self.root.bind("<Escape>", lambda e: self._interrupt())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- Menu ----

    def _build_menu(self):
        # Custom dark menu bar (frame-based to avoid Windows white menu strip)
        self.menu_bar = tk.Frame(self.root, bg=C["bg_sidebar"], height=28)
        self.menu_bar.pack(fill="x", side="top")
        self.menu_bar.pack_propagate(False)

        for label, items in [
            ("File", [
                ("New Chat", self._new_chat),
                None,
                ("API Key Setup", self._show_api_setup),
                ("Permissions", self._open_permissions),
                ("Settings", self._open_settings),
                None,
                ("Exit", self._on_close),
            ]),
            ("View", [
                ("LM Studio (Local Models)", self._open_lm_studio),
                ("Skills Browser", self._open_skills),
                ("Extensions", self._open_extensions),
                None,
                ("Toggle Sidebar", self._toggle_sidebar),
            ]),
            ("Help", [
                ("About", self._about),
            ]),
        ]:
            btn = tk.Menubutton(self.menu_bar, text=f"  {label}  ",
                               font=FONTS["small"], fg=C["text_secondary"],
                               bg=C["bg_sidebar"], activebackground=C["bg_hover"],
                               activeforeground=C["text_primary"],
                               relief="flat", padx=4)
            btn.pack(side="left")

            menu = tk.Menu(btn, tearoff=0,
                          bg=C["bg_card"], fg=C["text_primary"],
                          activebackground=C["accent"], activeforeground="white",
                          relief="flat", borderwidth=1)
            for item in items:
                if item is None:
                    menu.add_separator()
                else:
                    menu.add_command(label=item[0], command=item[1])
            btn.configure(menu=menu)

    # ---- Layout ----

    def _build_layout(self):
        main = tk.Frame(self.root, bg=C["bg_main"])
        main.pack(fill="both", expand=True)

        # Sidebar
        self.sidebar = Sidebar(main, on_new=self._new_chat,
                               on_model_change=self._on_model_change,
                               on_session_select=self._on_session_select)
        self.sidebar.pack(side="left", fill="y")

        # Vertical separator
        tk.Frame(main, bg=C["separator"], width=1).pack(side="left", fill="y")

        # Chat area
        chat_area = tk.Frame(main, bg=C["bg_main"])
        chat_area.pack(side="left", fill="both", expand=True)

        # Chat header
        hdr = tk.Frame(chat_area, bg=C["bg_sidebar"], height=40)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self.chat_title = tk.Label(hdr, text="New Chat", font=FONTS["subheading"],
                                  fg=C["text_primary"], bg=C["bg_sidebar"])
        self.chat_title.pack(side="left", padx=16)

        # Stop button is created here but packed in the input area (next to Send)
        # so it doesn't overlap the chat. See btn_frame below.

        # Messages scroll area
        msg_outer = tk.Frame(chat_area, bg=C["bg_main"])
        msg_outer.pack(fill="both", expand=True)

        self.msg_canvas = tk.Canvas(msg_outer, bg=C["bg_main"],
                                    highlightthickness=0, borderwidth=0)
        self.msg_sb = ttk.Scrollbar(msg_outer, orient="vertical", command=self.msg_canvas.yview)
        self.msg_canvas.configure(yscrollcommand=self.msg_sb.set)

        self.msg_sb.pack(side="right", fill="y")
        self.msg_canvas.pack(side="left", fill="both", expand=True)

        self.msg_frame = tk.Frame(self.msg_canvas, bg=C["bg_main"])
        self._msg_win = self.msg_canvas.create_window((0, 0), window=self.msg_frame, anchor="nw")

        self.msg_frame.bind("<Configure>", lambda e: self.msg_canvas.configure(
            scrollregion=self.msg_canvas.bbox("all")))
        self.msg_canvas.bind("<Configure>", lambda e: self.msg_canvas.itemconfig(
            self._msg_win, width=e.width))

        # Mouse wheel
        def _mw(event):
            self.msg_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.msg_canvas.bind_all("<MouseWheel>", _mw, add="+")

        # Input area
        inp_outer = tk.Frame(chat_area, bg=C["bg_sidebar"], padx=16, pady=12)
        inp_outer.pack(fill="x")

        # Image attachment preview (hidden until images attached)
        self._attached_images = []
        self._attach_frame = tk.Frame(inp_outer, bg=C["bg_sidebar"])
        # Not packed initially — shown when images are attached

        inp_card = tk.Frame(inp_outer, bg=C["bg_input"],
                           highlightbackground=C["border"], highlightthickness=1)
        inp_card.pack(fill="x")

        self.input_text = tk.Text(inp_card, wrap="word",
                                 bg=C["bg_input"], fg=C["text_primary"],
                                 font=FONTS["body"], relief="flat", height=3,
                                 padx=12, pady=8, insertbackground=C["text_primary"],
                                 selectbackground=C["accent"], selectforeground="white",
                                 highlightthickness=0)
        self.input_text.pack(fill="both", expand=True)

        # Button row below the text input, separate from the text card
        btn_row = tk.Frame(inp_outer, bg=C["bg_sidebar"])
        btn_row.pack(fill="x", pady=(6, 0))

        attach_btn = ttk.Button(btn_row, text="\U0001f4ce Attach", width=8,
                               command=self._attach_image)
        attach_btn.pack(side="left", padx=(0, 4))
        Tooltip(attach_btn, "Attach image (Ctrl+Shift+I)")

        send_btn = ttk.Button(btn_row, text="Send", style="Primary.TButton",
                             command=self._send)
        send_btn.pack(side="right", padx=(4, 0))
        Tooltip(send_btn, "Send message (Enter)")

        self.stop_btn = ttk.Button(btn_row, text="Stop", style="Danger.TButton",
                                   command=self._interrupt)
        self.stop_btn.pack(side="right", padx=(4, 0))
        Tooltip(self.stop_btn, "Stop generation (Escape)")

        self.root.bind("<Control-Shift-I>", lambda e: self._attach_image())

        self.input_text.bind("<Return>", self._on_enter)
        self.input_text.bind("<Shift-Return>", lambda e: None)
        self.input_text.focus_set()

        # Status bar
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill="x", side="bottom")

    # ---- Actions ----

    def _on_enter(self, event):
        if not (event.state & 0x1):  # no Shift
            self._send()
            return "break"

    def _attach_image(self):
        """Open file dialog to attach an image."""
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Attach Image",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("All files", "*.*"),
            ],
            parent=self.root,
        )
        if not paths:
            return

        for path in paths:
            if path not in self._attached_images:
                self._attached_images.append(path)

        self._update_attach_preview()

    def _remove_image(self, path):
        """Remove an attached image."""
        if path in self._attached_images:
            self._attached_images.remove(path)
        self._update_attach_preview()

    def _make_thumbnail(self, path, size=48):
        """Create a tk PhotoImage thumbnail from an image file."""
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except ImportError:
            return None  # Pillow not installed — fall back to text
        except Exception:
            return None

    def _update_attach_preview(self):
        """Show/hide attached image thumbnails."""
        # Clear existing preview and photo references
        for w in self._attach_frame.winfo_children():
            w.destroy()
        self._thumb_refs = []  # Keep references to prevent GC

        if not self._attached_images:
            self._attach_frame.pack_forget()
            return

        self._attach_frame.pack(fill="x", pady=(0, 6))

        for path in self._attached_images:
            chip = tk.Frame(self._attach_frame, bg=C["bg_card"],
                           highlightbackground=C["border"], highlightthickness=1,
                           padx=4, pady=4)
            chip.pack(side="left", padx=(0, 6))

            # Try to show actual thumbnail
            thumb = self._make_thumbnail(path)
            if thumb:
                self._thumb_refs.append(thumb)
                tk.Label(chip, image=thumb, bg=C["bg_card"]).pack(side="left", padx=(0, 4))

            fname = os.path.basename(path)
            if len(fname) > 18:
                fname = fname[:15] + "..."
            tk.Label(chip, text=fname, font=("Segoe UI", 8),
                    fg=C["text_secondary"], bg=C["bg_card"]).pack(side="left")

            rm_btn = tk.Label(chip, text=" \u2715", font=("Segoe UI", 9, "bold"),
                            fg=C["danger"], bg=C["bg_card"], cursor="hand2")
            rm_btn.pack(side="left")
            rm_btn.bind("<Button-1>", lambda e, p=path: self._remove_image(p))

    def _send(self):
        msg = self.input_text.get("1.0", "end-1c").strip()
        if not msg or self.bridge.is_running:
            return
        self.input_text.delete("1.0", "end")

        # Show attachments in the chat
        display = msg
        if self._attached_images:
            fnames = [os.path.basename(p) for p in self._attached_images]
            display = msg + "\n\U0001f4ce " + ", ".join(fnames)
        self._add_msg(display, "user")

        # Thinking
        self.thinking_widget = ThinkingIndicator(self.msg_frame)
        self.thinking_widget.pack(fill="x")
        self.thinking_widget.start()

        self.status_bar.set_thinking()

        # Send with images
        images = list(self._attached_images) if self._attached_images else None
        self._attached_images.clear()
        self._update_attach_preview()

        self.bridge.send_message(msg, image_paths=images)
        self._scroll_bottom()

    def _add_msg(self, text, msg_type, tool_name=None):
        w = MessageBubble(self.msg_frame, text, msg_type=msg_type, tool_name=tool_name)
        w.pack(fill="x")
        self._scroll_bottom()

    def _scroll_bottom(self):
        self.root.after(50, lambda: self.msg_canvas.yview_moveto(1.0))

    # ---- Callbacks ----

    def _on_response(self, text):
        if self.thinking_widget:
            self.thinking_widget.stop()
            try:
                self.thinking_widget.destroy()
            except tk.TclError:
                pass
            self.thinking_widget = None
        if text:
            self._add_msg(text, "ai")

    def _on_tool_call(self, name, preview):
        w = ToolCallWidget(self.msg_frame, name, preview)
        w.pack(fill="x")
        self.status_bar.set_tool(name)
        self._scroll_bottom()

    def _on_thinking(self, text):
        if text:
            self.status_bar.set_thinking(text)
        else:
            self.status_bar.set_ready()

    def _on_step(self, n, _):
        self.status_bar.set_iter(n)

    def _on_error(self, msg):
        if self.thinking_widget:
            self.thinking_widget.stop()
            try:
                self.thinking_widget.destroy()
            except tk.TclError:
                pass
            self.thinking_widget = None
        self._add_msg(msg, "error")
        self.status_bar.set_error()

    def _on_clarify(self, question, choices=None):
        resp = simpledialog.askstring("Hermes needs input", question, parent=self.root)
        self.bridge.respond_to_clarify(resp or "")

    def _on_approval(self, command, risk_level=None):
        """Dangerous command approval dialog."""
        msg = f"Hermes wants to run this command:\n\n{command}"
        if risk_level:
            msg += f"\n\nRisk level: {risk_level}"
        msg += "\n\nAllow this command?"
        approved = messagebox.askyesno("Command Approval", msg, parent=self.root)
        self.bridge.respond_to_approval(approved)

    def _on_reasoning(self, text):
        """Show model's reasoning/thinking in a subtle way."""
        if text and text.strip():
            # Show as a dim system-style message
            w = MessageBubble(self.msg_frame, f"[Thinking] {text[:300]}...",
                             msg_type="system")
            w.pack(fill="x")
            self._scroll_bottom()

    def _on_complete(self, result):
        self.status_bar.set_ready()
        # Update token display if available
        tokens = self.bridge.get_token_usage()
        if tokens.get("total"):
            total = tokens["total"]
            self.status_bar.iter_lbl.configure(
                text=f"{total:,} tokens"
            )
        # Refresh session list
        try:
            self.sidebar.refresh_sessions()
        except Exception:
            pass

    # ---- Commands ----

    def _new_chat(self):
        self.bridge.new_session()
        for w in self.msg_frame.winfo_children():
            w.destroy()
        self.chat_title.configure(text="New Chat")
        self.status_bar.set_ready()
        self._add_msg("New session started.", "system")
        self.input_text.focus_set()
        self.sidebar.refresh_sessions()

    def _on_model_change(self, model_id):
        """Called when user picks a model from the sidebar dropdown."""
        self.bridge.set_model(model_id)
        self.status_bar.set_model(model_id)
        # Show friendly name
        for mid, name, _ in Sidebar.MODELS:
            if mid == model_id:
                self._add_msg(f"Switched to {name}. Click '+ New Chat' to use it.", "system")
                return
        self._add_msg(f"Switched to {model_id}. Click '+ New Chat' to use it.", "system")

    def _on_session_select(self, session_id):
        """Load a past session into the chat view."""
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            messages = db.get_messages_as_conversation(session_id)
            if not messages:
                self._add_msg("Could not load that session.", "error")
                return

            # Clear current chat
            for w in self.msg_frame.winfo_children():
                w.destroy()

            # Load conversation into bridge
            self.bridge.conversation_history = messages
            self.bridge.agent = None  # Force recreation
            self.chat_title.configure(text="Resumed Session")

            # Display messages
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if not content or role == "system":
                    continue
                if isinstance(content, list):
                    # Multi-part content (images, etc.)
                    content = " ".join(
                        p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                if role == "user":
                    self._add_msg(content, "user")
                elif role == "assistant":
                    if content:
                        self._add_msg(content, "ai")
                elif role == "tool":
                    # Skip tool results in replay
                    pass

            self._add_msg("Session resumed. You can continue the conversation.", "system")
            self.input_text.focus_set()

        except Exception as e:
            self._add_msg(f"Error loading session: {e}", "error")

    def _interrupt(self):
        if self.bridge.is_running:
            self.bridge.interrupt()
            self.status_bar.set_ready()

    def _open_settings(self):
        d = SettingsDialog(self.root, self.bridge)
        self.root.wait_window(d)
        m = self.bridge.get_model()
        self.status_bar.set_model(m)
        self.sidebar.set_model(m)

    def _open_skills(self):
        SkillsBrowser(self.root)

    def _open_permissions(self):
        PermissionsPanel(self.root, on_save=self._on_permissions_saved)

    def _on_permissions_saved(self, perms):
        self.bridge.agent = None  # Force agent recreation with new permissions
        self._add_msg("Permissions updated. Click '+ New Chat' to apply.", "system")

    def _open_extensions(self):
        ExtensionsManager(self.root)

    def _open_lm_studio(self):
        LMStudioPanel(self.root, on_model_ready=self._on_lm_studio_ready)

    def _on_lm_studio_ready(self, base_url, model_id):
        """Switch Hermes to use LM Studio as the LLM provider."""
        # Set environment for the agent
        os.environ["OPENAI_BASE_URL"] = base_url
        if model_id:
            os.environ["LLM_MODEL"] = model_id
            self.bridge.set_model(model_id)
            self.status_bar.set_model(f"LM Studio: {model_id.split('/')[-1]}")
            self.sidebar.set_model(model_id)

        # Force agent recreation with new endpoint
        self.bridge.agent = None

        # Update agent bridge to use custom base URL
        self.bridge._lm_studio_base_url = base_url

        self._add_msg(
            f"Switched to LM Studio (local model).\n"
            f"Model: {model_id or 'default loaded model'}\n"
            f"Click '+ New Chat' to start using it.",
            "system"
        )

    def _show_api_setup(self):
        def on_done(saved_keys):
            if saved_keys:
                names = ", ".join(saved_keys.keys())
                self._add_msg(f"API keys saved: {names}\nNew tools are now available!", "system")
                # Force agent recreation to pick up new tools
                self.bridge.agent = None
            m = self.bridge.get_model()
            self.status_bar.set_model(m)
            self.sidebar.set_model(m)

        w = APISetupWizard(self.root, on_complete=on_done, auto_mode=True)
        self.root.wait_window(w)

    def _toggle_sidebar(self):
        if self.sidebar.winfo_viewable():
            self.sidebar.pack_forget()
        else:
            # Re-pack at left
            children = self.sidebar.master.winfo_children()
            self.sidebar.pack(side="left", fill="y", before=children[1] if len(children) > 1 else None)

    def _about(self):
        messagebox.showinfo("About Hermes Agent",
                           "Hermes Agent v0.2.0\n\n"
                           "The self-improving AI agent\n"
                           "by Nous Research\n\n"
                           "nousresearch.com",
                           parent=self.root)

    def _on_close(self):
        if self.bridge.is_running:
            if not messagebox.askyesno("Hermes Agent",
                                       "Agent is still running. Exit anyway?",
                                       parent=self.root):
                return
            self.bridge.interrupt()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    HermesGUI().run()


if __name__ == "__main__":
    main()
