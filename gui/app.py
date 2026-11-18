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
import queue
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

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

from gui.theme import C, FONTS, apply_theme, set_dark_title_bar, Tooltip, center_window, init_dpi_scaling, S, SF
from gui.agent_bridge import AgentBridge, ModelSaveFailed, sync_bundled_skills_once
from portable_hermes.session_store import open_store
from gui.api_setup_wizard import APISetupWizard, get_missing_keys
from gui.extensions import ExtensionsManager
from gui import accounts_core
from gui.accounts_window import AccountsWindow
from gui.lm_studio import (LMStudioPanel, DEFAULT_CONTEXT_LENGTH, MINIMUM_CONTEXT_LENGTH,
                           gpu_fit_note)
from gui.permissions_panel import PermissionsPanel
from gui.permissions import load_permissions, get_permissions_summary
from gui.i18n import (
    t,
    get_language,
    set_language,
    register_listener,
    unregister_listener,
    SUPPORTED_LANGUAGES,
    init_language,
    load_gui_setting,
    save_gui_setting,
)
from gui.reply_activity import ReplyActivity, clock
from gui.inline_markdown import BOLD, CODE, line_spans, spans
from hermes_constants import get_hermes_home
from hermes_cli import __version__ as HERMES_CORE_VERSION


# ============================================================================
# Chat Message Widgets
# ============================================================================

def _style_tags(body):
    """Define the **bold** and `code` tags of a reply's text widget (once:
    re-configuring a tag's font makes Tk lay out all of its text again)."""
    body.tag_configure(BOLD, font=FONTS["body"] + ("bold",))
    body.tag_configure(CODE, font=FONTS["mono"], background=C["bg_input"])


def _insert_styled(body, pieces):
    """Insert (text, tags) pieces: **bold** and `code` from the model."""
    for text, tags in pieces:
        body.insert("end", text, tags)


class MessageBubble(tk.Frame):
    """A single chat message."""

    def __init__(self, parent, text, msg_type="user", tool_name=None):
        super().__init__(parent, bg=C["bg_main"])
        self._msg_type = msg_type
        self._tool_name = tool_name
        self._text = text

        if msg_type == "user":
            bg, border, label, label_fg = C["msg_user"], C["msg_user_border"], t("chat.role_user"), C["accent"]
        elif msg_type == "ai":
            bg, border, label, label_fg = C["msg_ai"], C["msg_ai_border"], t("chat.role_ai"), C["success"]
        elif msg_type == "tool":
            bg, border = C["msg_tool"], C["msg_tool_border"]
            label, label_fg = t("chat.tool", name=tool_name or '?'), C["warning_dark"]
        elif msg_type == "error":
            bg, border, label, label_fg = C["msg_error"], C["msg_error_border"], t("chat.role_error"), C["danger"]
        else:  # system
            bg, border, label, label_fg = C["msg_system"], C["msg_system_border"], t("chat.role_system"), C["text_hint"]

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

        self._role_label = tk.Label(hdr, text=label, font=FONTS["small"] + ("bold",),
                                    fg=label_fg, bg=bg)
        self._role_label.pack(side="left")

        ts = datetime.now().strftime("%H:%M")
        tk.Label(hdr, text=ts, font=SF("Segoe UI", 8),
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
            if msg_type == "ai":
                _style_tags(body)
                _insert_styled(body, spans(display_text))
            else:
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
                loading = tk.Label(img_frame, text=t("chat.loading_image"),
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
                link = tk.Label(card, text=t("chat.image_link", url=url),
                               font=FONTS["small"], fg=C["accent"], bg=bg,
                               cursor="hand2")
                link.pack(fill="x", pady=(4, 0))
                link.bind("<Button-1>", lambda e, u=url: __import__('webbrowser').open(u))

    def _ctx_menu(self, event, tw):
        menu = tk.Menu(self, tearoff=0,
                      bg=C["bg_card"], fg=C["text_primary"],
                      activebackground=C["accent"], activeforeground="white")
        menu.add_command(label=t("chat.copy_all"), command=lambda: self._copy(tw))
        menu.add_command(label=t("chat.select_all"), command=lambda: self._select_all(tw))
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
            img.load()                       # decode here, not on the Tk thread

            # Resize to fit chat area (max 400px wide, maintain aspect ratio)
            max_w = 400
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

            # Tk objects (the PhotoImage too) are made on the Tk thread only.
            def _show():
                try:
                    tk_img = ImageTk.PhotoImage(img)
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
                    Tooltip(img_label, t("chat.open_image_tooltip", alt=alt_text))
                except tk.TclError:
                    pass

            frame.after(0, _show)

        except Exception as e:
            def _show_error():
                try:
                    loading_label.configure(text=t("chat.image_load_failed", error=e),
                                           fg=C["danger"])
                except tk.TclError:
                    pass
            frame.after(0, _show_error)

    def update_ui_language(self):
        if self._msg_type == "tool":
            label = t("chat.tool", name=self._tool_name or "?")
        else:
            label = t(f"chat.role_{self._msg_type}")
        self._role_label.configure(text=label)


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

        tk.Label(row, text="\u25B6", font=SF("Segoe UI", 8),
                fg=C["warning_dark"], bg=C["msg_tool"]).pack(side="left", padx=(0, 6))
        tk.Label(row, text=tool_name, font=FONTS["mono_small"] + ("bold",),
                fg=C["accent"], bg=C["msg_tool"]).pack(side="left")

        if args_preview:
            preview = str(args_preview)[:100]
            if len(str(args_preview)) > 100:
                preview += "..."
            tk.Label(card, text=preview, font=FONTS["mono_small"],
                    fg=C["text_hint"], bg=C["msg_tool"],
                    wraplength=S(500), justify="left", anchor="w").pack(fill="x")


class ReplyActivityView(tk.Frame):
    """A reply bubble's activity line ("the tab") and, below it when open,
    the model's thinking text, dimmed. Clicking the line opens or closes it."""

    def __init__(self, parent, bg, activity, opened=False, on_toggle=None):
        super().__init__(parent, bg=bg)
        self.activity = activity
        self.opened = opened
        self._on_toggle = on_toggle
        self._bg = bg
        # The normal body size: the arrow is readable at any DPI.
        self._label = tk.Label(self, font=FONTS["body"], fg=C["text_hint"], bg=bg,
                               anchor="w", justify="left", pady=0)
        self._label.pack(fill="x")
        self._label.bind("<Button-1>", self.toggle)
        self._pane = None    # the thinking pane, made when first opened
        self._text = None
        self._shown = 0      # thinking chunks already in it
        self.refresh()

    def _make_pane(self):
        """Clearly secondary to the answer: dimmer text, indented behind a
        thin bar, and space below it before the answer starts."""
        self._pane = tk.Frame(self, bg=self._bg)
        tk.Frame(self._pane, bg=C["border_dark"], width=S(2)).pack(side="left", fill="y")
        self._text = tk.Text(self._pane, wrap="word", bg=self._bg, fg=C["text_disabled"],
                             font=FONTS["small"], relief="flat", borderwidth=0,
                             highlightthickness=0, padx=S(8), pady=S(2), height=1)
        self._text.pack(side="left", fill="x", expand=True)

    def refresh(self):
        """Show the activity's current line and new thinking text (if open)."""
        header = self.activity.header()
        if header is None:
            self.pack_forget()
            return
        expandable = self.activity.expandable
        arrow = ("▾ " if self.opened else "▸ ") if expandable else ""
        self._label.configure(text=arrow + header, cursor="hand2" if expandable else "")
        if self.opened and expandable:
            if self._pane is None:
                self._make_pane()
            parts = self.activity.thinking_parts
            new = "".join(parts[self._shown:])    # only the chunks since last time
            self._shown = len(parts)
            if new:       # one insert per refresh, however many tokens arrived
                self._text.configure(state="normal")
                self._text.insert("end", new)
                self._text.configure(state="disabled")
                height = min(12, int(self._text.index("end-1c").split(".")[0]))
                if height != int(self._text.cget("height")):   # a resize re-lays out the bubble
                    self._text.configure(height=height)
                self._text.yview_moveto(1.0)
            if not self._pane.winfo_manager():
                self._pane.pack(fill="x", pady=(S(2), S(8)))
        elif self._pane is not None:
            self._pane.pack_forget()

    def toggle(self, _event=None):
        if not self.activity.expandable:
            return
        self.opened = not self.opened
        if self._on_toggle:
            self._on_toggle(self.opened)
        self.refresh()


class StreamingBubble(tk.Frame):
    """A chat bubble that streams text token-by-token, below an activity line
    (waiting / thinking / running a tool) when given a ReplyActivity."""

    _LINE = "md_line"            # Tk mark: where the unfinished line starts
    PREVIEW_LINE_CHARS = 2000    # longer unfinished lines are previewed plain

    def __init__(self, parent, activity=None, thinking_open=False, on_thinking_toggle=None):
        super().__init__(parent, bg=C["bg_main"])
        # Text arrives in many small chunks: kept in lists and joined only
        # when the whole text is needed, never grown per token.
        self._cr = ""         # a chunk's final \r, held: it may be half a CRLF
        self._leading = []    # whitespace chunks held before the first visible character
        self._shown = []      # the chunks given to the body, markers included
        self._line = []       # the chunks of its last, unfinished line
        self._line_len = 0
        self._fenced = None  # the fence open after the finished lines (line_spans)
        self._tall = False    # the body has reached its height limit
        self._bg = C["msg_ai"]
        self._refresh_id = None

        pad = tk.Frame(self, bg=C["bg_main"])
        pad.pack(fill="x", padx=16, pady=3)

        self._card = tk.Frame(pad, bg=self._bg,
                             highlightbackground=C["msg_ai_border"],
                             highlightthickness=1, padx=10, pady=4)
        self._card.pack(side="left", anchor="w", fill="x", expand=True)

        # Header — tight single row
        hdr = tk.Frame(self._card, bg=self._bg)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Hermes", font=FONTS["small"] + ("bold",),
                fg=C["success"], bg=self._bg, pady=0).pack(side="left")
        ts = datetime.now().strftime("%H:%M")
        tk.Label(hdr, text=ts, font=SF("Segoe UI", 8),
                fg=C["text_disabled"], bg=self._bg, pady=0).pack(side="right")

        self.activity = activity
        self._activity_view = None
        if activity is not None:
            self._activity_view = ReplyActivityView(self._card, self._bg, activity,
                                                    thinking_open, on_thinking_toggle)
            if activity.header() is not None:
                self._activity_view.pack(fill="x")

        # Body text widget — stays editable (normal) during streaming
        self._body = tk.Text(self._card, wrap="word", bg=self._bg,
                            fg=C["text_primary"], font=FONTS["body"],
                            relief="flat", borderwidth=0,
                            padx=0, pady=0, cursor="arrow",
                            selectbackground=C["accent"],
                            selectforeground="white",
                            highlightthickness=0, height=1,
                            spacing1=0, spacing2=0, spacing3=0)
        self._body.pack(fill="x")
        _style_tags(self._body)
        self._body.mark_set(self._LINE, "1.0")
        self._body.mark_gravity(self._LINE, "left")   # stays before text added at it

        # Blinking cursor — separate label so it can't corrupt text
        self._cursor_lbl = tk.Label(self._card, text="\u258c",
                                    font=FONTS["body"], fg=C["info"],
                                    bg=self._bg, pady=0)
        self._cursor_lbl.pack(anchor="w")
        self._cursor_on = True
        self._blink()

    def append_text(self, text: str):
        """Append a text delta to the streaming bubble."""
        if text is None:
            return
        # CRLF shows as LF, the same while streaming and once finalized.
        text = self._cr + text
        self._cr = "\r" if text.endswith("\r") else ""
        text = text[:len(text) - len(self._cr)].replace("\r\n", "\n")
        if not text:
            return
        if self._leading is not None:
            # Models often open a reply (or a segment after a tool call) with
            # blank lines: hold whitespace until the first visible character,
            # then drop the blank lines but keep that line's own indentation.
            if text.isspace():
                self._leading.append(text)
                return
            held = "".join(self._leading) + text          # joined once
            content = held.lstrip()
            blank = held[:len(held) - len(content)]
            text = held[blank.rfind("\n") + 1:]
            self._leading = None
            if self.activity is not None:          # the answer starts
                self.activity.answer_started()
                self.refresh_activity()
        self._shown.append(text)
        self._preview(text)
        self._fit_height()

    def _preview(self, text: str):
        """Best-effort styling while streaming: each line is styled on its
        own once finished, the unfinished line again with each token (plain
        once it is very long). finalize() redraws the whole reply."""
        *finished, last = text.split("\n")
        body = self._body
        if finished:
            finished[0] = "".join(self._line) + finished[0]
            self._line, self._line_len = [], 0
            body.delete(self._LINE, "end-1c")
            for line in finished:
                pieces, self._fenced = line_spans(line, self._fenced)
                _insert_styled(body, pieces)
                body.insert("end", "\n")
            body.mark_set(self._LINE, "end-1c")
        self._line.append(last)
        self._line_len += len(last)
        if self._line_len <= self.PREVIEW_LINE_CHARS:   # bounded work per token
            body.delete(self._LINE, "end-1c")
            _insert_styled(body, line_spans("".join(self._line), self._fenced)[0])
        else:
            body.insert("end", last)

    def add_thinking(self, text: str):
        """Thinking text arrives token by token: the view is refreshed at
        most every 100 ms, with all of it in one insert."""
        if self.activity is None:
            return
        state = self.activity.state
        self.activity.add_thinking(text)
        # With Show Thinking off only the change to "Thinking..." needs a
        # redraw; the clock redraws the line every second anyway.
        changed = self.activity.keep_thinking or self.activity.state != state
        if changed and self._refresh_id is None:
            self._refresh_id = self.after(100, self.refresh_activity)

    def _cancel_timers(self, names=("_refresh_id", "_blink_id")):
        """Cancel the Tk after() calls this bubble has pending (all by default)."""
        for name in names:
            after_id = getattr(self, name, None)
            setattr(self, name, None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass

    def destroy(self):
        """Stop, New Chat, an error or a tool call can destroy a bubble with
        a redraw or a cursor blink still pending."""
        self._cursor_on = False
        self._cancel_timers()
        super().destroy()

    def refresh_activity(self):
        """Redraw the activity line (the clock calls this every second)."""
        self._cancel_timers(("_refresh_id",))
        if self._activity_view is None:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            header = self.activity.header()
            if header is None and self.activity.state == "done":
                # A finished segment that keeps no line (a quick answer):
                # drop the view rather than leave it unmapped with a stale text.
                self._activity_view.destroy()
                self._activity_view = None
                return
            if header is not None and not self._activity_view.winfo_manager():
                self._activity_view.pack(fill="x", before=self._body)
            self._activity_view.refresh()
        except tk.TclError:
            pass

    def has_content(self) -> bool:
        """Answer text or thinking text to keep."""
        # _leading is None once a visible character arrived
        return self._leading is None or bool(self.activity and self.activity.expandable)

    def _fit_height(self):
        """Size the body to its content. Once it reaches the 30-line limit
        it is not measured again while streaming (the text only grows)."""
        if self._tall:
            return
        content = self._body.get("1.0", "end-1c")
        lines = max(1, content.count('\n') + 1)
        for line in content.split('\n'):
            lines += max(0, len(line) // 70)
        self._tall = lines >= 30
        self._body.configure(height=min(lines, 30))

    def get_text(self) -> str:
        """The reply as finalize() displays it: CRLF as LF, without the
        leading blank lines and the trailing whitespace; nothing else changed."""
        return "".join(self._shown).rstrip()

    def finalize(self):
        """Stop the cursor blink, show the reply as get_text() returns it
        (only its outer whitespace trimmed), lock the text."""
        if self.activity is not None:
            self.activity.finish()
            self.refresh_activity()
        self._cursor_on = False
        self._cancel_timers()
        try:
            self._cursor_lbl.destroy()
        except tk.TclError:
            pass
        # One redraw of the whole reply: what stays is spans(full text),
        # whatever the preview showed while it streamed.
        self._body.delete("1.0", "end")
        _insert_styled(self._body, spans(self.get_text()))
        self._tall = False
        self._fit_height()                # an estimate until the body is laid out
        if self._leading is not None:
            self._body.pack_forget()      # thinking only: no empty answer line
        self._body.configure(state="disabled")
        self._body.bind("<Configure>", self._fit_display_lines)
        self._fit_display_lines()

    def _fit_display_lines(self, _event=None):
        """Finalized: exactly as tall as the lines the text shows at the
        body's width, measured again whenever that width changes."""
        body = self._body
        try:
            if body.winfo_width() <= 1:   # not laid out yet: <Configure> follows
                return
            lines = body.count("1.0", "end", "update", "displaylines")
            lines = lines[0] if isinstance(lines, tuple) else lines
            if lines and lines != int(body.cget("height")):
                body.configure(height=lines)
        except tk.TclError:
            pass

    def _blink(self):
        self._blink_id = None
        if not self._cursor_on:
            return
        try:
            cur = self._cursor_lbl.cget("fg")
            self._cursor_lbl.configure(
                fg=self._bg if cur != self._bg else C["info"])
            self._blink_id = self.after(500, self._blink)
        except tk.TclError:
            pass


# ============================================================================
# Sidebar
# ============================================================================

def _auto_load_local_model(model_id, settings, log):
    """Load *model_id* in LM Studio for the sidebar; runs on a worker thread.

    Returns (success, message, instance id LM Studio used or None). The
    message is the error on failure; on success it is empty, or the warning
    that the GPU could only be estimated (gui.lm_studio.gpu_unconfirmed_note)."""
    try:
        from gui.lm_studio import LMStudioPanel, LMStudioClient, gpu_choice_label, gpu_unconfirmed_note
        client = LMStudioClient(base_url=LMStudioPanel._resolve_base_url())
        if not client.connect_sdk():
            log.debug("auto-load SDK connect FAILED")
            return False, t("sidebar.sdk_unavailable"), None
        log.debug("auto-load SDK connected, calling load_model...")
        client.load_model(
            model_id,
            gpu_index=settings.get("gpu_index"),
            gpu_placement=settings.get("gpu_placement"),
            context_length=settings["context_length"],
            flash_attention=settings.get("flash_attention", True),
        )
        loaded_id = client.last_loaded_identifier
        log.debug("auto-load SUCCESS instance=%r", loaded_id)
        plan = getattr(client, "last_gpu_plan", None)
        note = None
        if plan is not None and not getattr(plan, "confirmed", True):
            note = gpu_unconfirmed_note(plan, gpu_choice_label(plan.placement))
        return True, note or "", loaded_id
    except Exception as e:
        log.error("auto-load EXCEPTION: %s", e)
        return False, str(e), None


class Sidebar(tk.Frame):
    """Left sidebar with branding, new-chat, session history, and model switcher."""

    MODELS = [
        ("google/gemini-2.5-flash", "Gemini Flash", "sidebar.note.fast_cheap"),
        ("google/gemini-2.5-pro", "Gemini Pro", "sidebar.note.smart_affordable"),
        ("anthropic/claude-sonnet-4", "Claude Sonnet", "sidebar.note.all_rounder"),
        ("anthropic/claude-opus-4.6", "Claude Opus", "sidebar.note.most_capable"),
        ("openai/gpt-4o", "GPT-4o", "sidebar.note.flagship"),
        ("openai/gpt-4o-mini", "GPT-4o Mini", "sidebar.note.fast_cheap"),
        ("deepseek/deepseek-chat-v3", "DeepSeek V3", "sidebar.note.strong_cheap"),
        ("meta-llama/llama-4-maverick", "Llama Maverick", "sidebar.note.open_source"),
    ]

    def __init__(self, parent, on_new=None, on_model_change=None,
                 on_session_select=None, on_local_models=None,
                 on_auto_load=None, can_delete_session=None, can_change_model=None,
                 track_model_work=None, **kw):
        super().__init__(parent, bg=C["bg_sidebar"], width=S(260), **kw)
        self.pack_propagate(False)
        self.on_new = on_new
        # callback() -> bool; False refuses a model pick (it explains why)
        self.can_change_model = can_change_model
        # callback(thread): a thread loading a model (sending waits for it)
        self.track_model_work = track_model_work
        # callback(session_id) -> bool; False refuses the delete (it explains why)
        self.can_delete_session = can_delete_session
        self.on_model_change = on_model_change
        self.on_session_select = on_session_select
        self.on_local_models = on_local_models  # callback(list_of_model_ids)
        self.on_auto_load = on_auto_load  # callback(model_id, gpu, ctx, settings)
        self._confirm_delete = True  # Show confirmation dialog
        self._loading_model = False  # True while auto-loading

        # Unified model list: cloud + local
        self._lm_studio_models: List[tuple] = []  # [(id, name, note), ...]
        self._model_sizes: Dict[str, int] = {}    # LM Studio model id -> file size
        self._account_models: List[tuple] = []  # [(id, "[ChatGPT] id", "account:<provider>")]
        self._all_models: List[tuple] = list(self.MODELS)
        self._model_states: Dict[str, str] = {}  # model_id -> "loaded"/"not-loaded"

        # -- Logo --
        logo_fr = tk.Frame(self, bg=C["bg_sidebar"], pady=12, padx=16)
        logo_fr.pack(fill="x")
        tk.Label(logo_fr, text="HERMES", font=FONTS["logo"],
                fg=C["accent"], bg=C["bg_sidebar"]).pack(anchor="w")
        tk.Label(logo_fr, text="AGENT", font=FONTS["logo_sub"],
                fg=C["text_secondary"], bg=C["bg_sidebar"]).pack(anchor="w")

        # -- New Chat button --
        btn_fr = tk.Frame(self, bg=C["bg_sidebar"], padx=16)
        btn_fr.pack(fill="x")
        self.new_btn = ttk.Button(btn_fr, text=t("sidebar.new_chat"), style="Primary.TButton",
                                  command=self._on_new)
        self.new_btn.pack(fill="x", pady=(0, 8))

        # -- Model Switcher --
        model_fr = tk.Frame(self, bg=C["bg_sidebar"], padx=16)
        model_fr.pack(fill="x")

        self.model_lbl = tk.Label(model_fr, text=t("sidebar.model"), font=FONTS["small"],
                                  fg=C["text_hint"], bg=C["bg_sidebar"])
        self.model_lbl.pack(anchor="w")

        self.model_var = tk.StringVar(value="google/gemini-2.5-flash")
        display_values = [self._display_name(m) for m in self._all_models]
        self.model_combo = ttk.Combobox(model_fr, textvariable=tk.StringVar(),
                                        values=display_values,
                                        font=FONTS["small"], state="readonly")
        current_model = self.model_var.get()
        self._select_model_in_combo(current_model)

        self.model_combo.pack(fill="x", pady=(2, 4))
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_selected)
        self.model_combo.bind("<Button-1>", lambda e: self.refresh_models())

        # -- Loading status indicator (hidden by default) --
        self._load_status_var = tk.StringVar(value="")
        self._load_status_data = None
        self._load_status_lbl = tk.Label(model_fr, textvariable=self._load_status_var,
                                         font=FONTS["small"], fg=C["warning"],
                                         bg=C["bg_sidebar"], anchor="w")
        # Don't pack yet — shown/hidden dynamically

        # -- Local Model Settings (collapsible) --
        self._local_settings_fr = tk.Frame(self, bg=C["bg_sidebar"], padx=16)
        # Don't pack yet — shown when a local model is selected
        self._build_local_settings(self._local_settings_fr)

        # Probe LM Studio models in background after startup
        self.after(1000, self.refresh_models)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # -- Sessions header --
        self.sessions_lbl = tk.Label(self, text=t("sidebar.recent_sessions"), font=FONTS["small"],
                                     fg=C["text_hint"], bg=C["bg_sidebar"], padx=16, pady=8,
                                     anchor="w")
        self.sessions_lbl.pack(fill="x")

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
        self._sessions_data = []
        self.after(500, self._load_sessions)

    @staticmethod
    def _display_name(entry):
        """Build display string for a model tuple (id, name, note)."""
        _, name, note = entry
        if note.startswith("account:"):
            return name
        if note == "LM Studio":
            name = f"{t('sidebar.local_prefix')} {name}"
        elif note.startswith("sidebar.note."):
            note = t(note)
        return f"{name}  ({note})"

    def _select_model_in_combo(self, model_id):
        """Select model_id in the combobox, or show raw ID if not found."""
        for i, (mid, _, _) in enumerate(self._all_models):
            if mid == model_id:
                self.model_combo.current(i)
                return
        self.model_combo.set(model_id)

    def set_model(self, name):
        self.model_var.set(name)
        self._select_model_in_combo(name)

    def _update_combobox_values(self):
        """Rebuild combobox values from _all_models (must be called on main thread)."""
        current = self.model_var.get()
        display_values = [self._display_name(m) for m in self._all_models]
        self.model_combo["values"] = display_values
        self._select_model_in_combo(current)
        self._update_fit_hint()

    def _build_local_settings(self, parent):
        """Build the compact local model settings panel."""
        # Load persisted settings from env
        _hermes_home = get_hermes_home()

        # Header
        self._local_header = tk.Label(parent, text=t("sidebar.local_settings"), font=FONTS["small"],
                                      fg=C["accent"], bg=C["bg_sidebar"])
        self._local_header.pack(anchor="w", pady=(4, 2))

        # GPU selector
        gpu_row = tk.Frame(parent, bg=C["bg_sidebar"])
        gpu_row.pack(fill="x", pady=2)
        self._local_gpu_label = tk.Label(gpu_row, text=t("sidebar.gpu_short"), font=FONTS["small"],
                                         fg=C["text_hint"], bg=C["bg_sidebar"], width=6, anchor="w")
        self._local_gpu_label.pack(side="left")
        self._gpu_var = tk.StringVar(value="")
        self._gpus = []  # NvidiaGpu entries from gui.lm_studio.detect_gpus()
        self._gpu_label_to_placement = {}
        self._gpu_user_choice = None  # placement the user picked, if any
        self._gpu_combo = ttk.Combobox(gpu_row, textvariable=self._gpu_var,
                                        font=FONTS["small"], state="readonly", width=22)
        self._gpu_combo.pack(side="left", fill="x", expand=True)
        self._gpu_combo.bind("<<ComboboxSelected>>", self._on_gpu_chosen)
        # "May not fit on this card" note (shown only when it applies)
        self._fit_hint_lbl = tk.Label(parent, text="", font=FONTS["small"], fg=C["warning"],
                                      bg=C["bg_sidebar"], anchor="w", justify="left",
                                      wraplength=S(220))

        # Detect GPUs in background
        def _detect_gpus():
            try:
                from gui.lm_studio import detect_gpus
                gpus = detect_gpus()
            except Exception:
                gpus = []
            try:
                self.after(0, lambda: self._populate_gpus(gpus))
            except Exception:
                pass
        threading.Thread(target=_detect_gpus, daemon=True).start()

        # Context length
        ctx_row = tk.Frame(parent, bg=C["bg_sidebar"])
        ctx_row.pack(fill="x", pady=2)
        self._local_ctx_label = tk.Label(ctx_row, text=t("sidebar.context_short"), font=FONTS["small"],
                                         fg=C["text_hint"], bg=C["bg_sidebar"], width=6, anchor="w")
        self._local_ctx_label.pack(side="left")
        # Same window as the LM Studio panel: Hermes cannot chat below the minimum.
        self._ctx_var = tk.IntVar(value=DEFAULT_CONTEXT_LENGTH)
        ctx_spin = ttk.Spinbox(ctx_row, from_=MINIMUM_CONTEXT_LENGTH,
                               to=max(131072, DEFAULT_CONTEXT_LENGTH), increment=4096,
                               textvariable=self._ctx_var, font=FONTS["small"], width=8,
                               command=self._save_local_settings)
        ctx_spin.pack(side="left")
        ctx_spin.bind("<FocusOut>", lambda e: self._save_local_settings())
        ctx_spin.bind("<Return>", lambda e: self._save_local_settings())
        self._local_tokens_label = tk.Label(ctx_row, text=t("sidebar.tokens_unit"), font=FONTS["small"],
                                            fg=C["text_disabled"], bg=C["bg_sidebar"])
        self._local_tokens_label.pack(side="left", padx=(4, 0))

        # Temperature
        temp_row = tk.Frame(parent, bg=C["bg_sidebar"])
        temp_row.pack(fill="x", pady=2)
        self._local_temp_label = tk.Label(temp_row, text=t("sidebar.temp_short"), font=FONTS["small"],
                                          fg=C["text_hint"], bg=C["bg_sidebar"], width=6, anchor="w")
        self._local_temp_label.pack(side="left")
        self._temp_var = tk.DoubleVar(value=0.7)
        temp_spin = ttk.Spinbox(temp_row, from_=0.0, to=2.0, increment=0.1,
                                textvariable=self._temp_var, font=FONTS["small"], width=8,
                                format="%.1f")
        temp_spin.pack(side="left")
        temp_spin.bind("<FocusOut>", lambda e: self._save_local_settings())
        temp_spin.bind("<Return>", lambda e: self._save_local_settings())

        # Top-P
        topp_row = tk.Frame(parent, bg=C["bg_sidebar"])
        topp_row.pack(fill="x", pady=2)
        self._local_top_p_label = tk.Label(topp_row, text=t("sidebar.top_p"), font=FONTS["small"],
                                           fg=C["text_hint"], bg=C["bg_sidebar"], width=6, anchor="w")
        self._local_top_p_label.pack(side="left")
        self._topp_var = tk.DoubleVar(value=0.9)
        topp_spin = ttk.Spinbox(topp_row, from_=0.0, to=1.0, increment=0.05,
                                textvariable=self._topp_var, font=FONTS["small"], width=8,
                                format="%.2f")
        topp_spin.pack(side="left")
        topp_spin.bind("<FocusOut>", lambda e: self._save_local_settings())
        topp_spin.bind("<Return>", lambda e: self._save_local_settings())

        # Checkboxes row
        cb_fr = tk.Frame(parent, bg=C["bg_sidebar"])
        cb_fr.pack(fill="x", pady=(4, 4))

        self._auto_load_var = tk.BooleanVar(value=True)
        self._auto_load_cb = tk.Checkbutton(cb_fr, text=t("sidebar.auto_load"),
                                 variable=self._auto_load_var,
                                 font=FONTS["small"], fg=C["text_hint"],
                                 bg=C["bg_sidebar"], selectcolor=C["bg_input"],
                                 activebackground=C["bg_sidebar"],
                                 activeforeground=C["text_primary"],
                                 command=self._save_local_settings)
        self._auto_load_cb.pack(side="left")

        self._flash_attn_var = tk.BooleanVar(value=True)
        self._flash_attn_cb = tk.Checkbutton(cb_fr, text=t("sidebar.flash_attention"),
                                  variable=self._flash_attn_var,
                                  font=FONTS["small"], fg=C["text_hint"],
                                  bg=C["bg_sidebar"], selectcolor=C["bg_input"],
                                  activebackground=C["bg_sidebar"],
                                  activeforeground=C["text_primary"],
                                  command=self._save_local_settings)
        self._flash_attn_cb.pack(side="left", padx=(8, 0))

    def _on_gpu_chosen(self, _event=None):
        """The user picked a GPU entry: remember it by placement (labels are
        translated and the index shifts once GPUs are detected)."""
        self._gpu_user_choice = self._get_gpu_placement()
        self._save_local_settings()

    def _populate_gpus(self, gpus):
        """Populate GPU combobox (called on main thread). Detection can finish
        after the user already picked an entry; keep that choice if offered."""
        self._gpus = list(gpus)
        self._show_gpu_choices(getattr(self, "_gpu_user_choice", None))
        # Persist the selection so bridge can read it
        self._save_local_settings()

    def _show_gpu_choices(self, selected=None):
        """Fill the GPU combobox, keeping *selected* if it is still offered
        (else the first GPU, else Auto)."""
        from gui.lm_studio import gpu_choices
        from portable_hermes import lmstudio_gpu as gpu_place
        choices = gpu_choices(self._gpus)
        self._gpu_label_to_placement = {label: p for p, label in choices}
        placements = [p for p, _label in choices]
        if selected not in placements:
            selected = gpu_place.default_placement(self._gpus)
        self._gpu_combo["values"] = [label for _p, label in choices]
        self._gpu_combo.current(placements.index(selected))
        self._gpu_var.set(choices[placements.index(selected)][1])

    def _save_local_settings(self):
        """Settings are held in UI widgets — nothing to persist; a change may
        change the "may not fit" note."""
        self._update_fit_hint()

    def _update_fit_hint(self):
        """Show or hide the note under the GPU box for the chosen model, GPU
        and context (never blocks a load)."""
        if not hasattr(self, "_fit_hint_lbl"):
            return
        try:
            ctx = int(self._ctx_var.get())
        except (tk.TclError, ValueError):
            ctx = 0
        note = gpu_fit_note(self._get_gpu_placement(), self._gpus,
                            self._model_sizes.get(self.model_var.get()), ctx)
        self._fit_hint_lbl.configure(text=note)
        if note:
            self._fit_hint_lbl.pack(fill="x", after=self._gpu_combo.master)
        else:
            self._fit_hint_lbl.pack_forget()

    def _get_gpu_placement(self) -> str:
        """Placement of the GPU combobox entry: auto, cpu, split or gpu:<n>."""
        return self._gpu_label_to_placement.get(self._gpu_var.get(), "auto")

    def _get_gpu_index(self) -> Optional[int]:
        """nvidia-smi index when a single GPU is selected, else None."""
        placement = self._get_gpu_placement()
        if placement.startswith("gpu:"):
            try:
                return int(placement[4:])
            except ValueError:
                pass
        return None

    def _context_length(self) -> int:
        """The Ctx box value, raised to the minimum Hermes can chat with (the
        box accepts typed values below it); the box then shows what is used."""
        try:
            ctx = int(self._ctx_var.get())
        except (tk.TclError, ValueError):
            ctx = DEFAULT_CONTEXT_LENGTH
            self._ctx_var.set(ctx)
        if ctx < MINIMUM_CONTEXT_LENGTH:
            ctx = MINIMUM_CONTEXT_LENGTH
            self._ctx_var.set(ctx)
        return ctx

    def get_local_settings(self) -> dict:
        """Return current local model settings."""
        return {
            "gpu_placement": self._get_gpu_placement(),
            "gpu_index": self._get_gpu_index(),
            "context_length": self._context_length(),
            "temperature": self._temp_var.get(),
            "top_p": self._topp_var.get(),
            "flash_attention": self._flash_attn_var.get(),
        }

    def _show_local_settings(self, show: bool):
        """Show or hide the local model settings panel."""
        if show:
            # Insert after model combo, before the separator
            try:
                self._local_settings_fr.pack(fill="x", after=self.model_combo.master)
            except Exception:
                self._local_settings_fr.pack(fill="x")
        else:
            self._local_settings_fr.pack_forget()

    def _show_load_status(self, key: str = "", prefix: str = "", **kwargs):
        """Show or hide the loading status label."""
        self._load_status_data = (key, prefix, kwargs) if key else None
        if key:
            self._load_status_var.set(prefix + t(key, **kwargs))
            self._load_status_lbl.pack(fill="x", pady=(0, 2))
        else:
            self._load_status_var.set("")
            self._load_status_lbl.pack_forget()

    def set_account_models(self, provider: str, short: str, model_ids):
        """List a signed-in account's models at the top of the box."""
        self._account_models = [(m, f"[{short}] {m}", f"account:{provider}") for m in model_ids]
        self._all_models = self._account_models + list(self.MODELS) + list(self._lm_studio_models)
        self._update_combobox_values()

    def account_for(self, model_id: str):
        """The account a listed account model belongs to, else None."""
        for mid, _, note in self._account_models:
            if mid == model_id:
                return note.split(":", 1)[1]
        return None

    def _is_local_entry(self, model_id: str) -> bool:
        """Check if a model_id belongs to the local LM Studio models."""
        return any(mid == model_id for mid, _, _ in self._lm_studio_models)

    def refresh_models(self):
        """Probe LM Studio in a background thread and merge local models into the list."""
        def _probe():
            local_models = []
            states = {}
            sizes = {}
            try:
                from gui.lm_studio import LMStudioPanel, LMStudioClient
                url = LMStudioPanel._resolve_base_url()
                client = LMStudioClient(base_url=url)
                if client.is_running():
                    for m in client.list_models_api():
                        mid = m.get("id", "")
                        if mid:
                            state = m.get("state", "unknown")
                            states[mid] = state
                            sizes[mid] = m.get("size_bytes")
                            short = mid.split("/")[-1] if "/" in mid else mid
                            tag = "\u2713 " if state == "loaded" else ""
                            local_models.append((mid, f"{tag}{short}", "LM Studio"))
            except Exception:
                pass
            self._lm_studio_models = local_models
            self._model_states = states
            self._model_sizes = sizes
            self._all_models = self._account_models + list(self.MODELS) + local_models
            # Register local model IDs with the bridge for routing
            if self.on_local_models and local_models:
                local_ids = [mid for mid, _, _ in local_models]
                try:
                    self.after(0, lambda ids=local_ids: self.on_local_models(ids))
                except Exception:
                    pass
            # Update combobox on main thread
            try:
                self.after(0, self._update_combobox_values)
            except Exception:
                pass

        threading.Thread(target=_probe, daemon=True).start()

    def _on_new(self):
        if self.on_new:
            self.on_new()

    def _on_model_selected(self, event):
        idx = self.model_combo.current()
        can_change = getattr(self, "can_change_model", None)
        if can_change and not can_change():
            # Refused before anything happens (an auto-load would unload the
            # model the running reply uses): show the model still in effect.
            self._select_model_in_combo(self.model_var.get())
            return
        if 0 <= idx < len(self._all_models):
            model_id = self._all_models[idx][0]
            self.model_var.set(model_id)
            is_local = self._is_local_entry(model_id)

            # Show/hide local settings panel
            self._show_local_settings(is_local)
            self._update_fit_hint()

            if is_local and self._auto_load_var.get():
                # Always load via SDK to ensure correct GPU placement,
                # even if the model is already loaded (may be on wrong GPU)
                self._auto_load_model(model_id)
                return  # on_model_change called after load completes
            if self.on_model_change:
                self.on_model_change(model_id)

    def _auto_load_model(self, model_id: str):
        """Auto-load a local model in background, then fire on_model_change."""
        if self._loading_model:
            return
        self._loading_model = True
        self._show_load_status("sidebar.loading_model")
        self.model_combo.configure(state="disabled")

        settings = self.get_local_settings()
        self._loading_placement = settings.get("gpu_placement")  # for the result line

        def _load():
            success, error_msg, loaded_id = False, "", None
            try:
                import logging as _log
                _dbg = _log.getLogger("hermes.autoload")
                if not _dbg.handlers:
                    _log_dir = get_hermes_home() / "logs"
                    _log_dir.mkdir(parents=True, exist_ok=True)
                    _fh = _log.FileHandler(str(_log_dir / "bridge.log"), encoding="utf-8")
                    _fh.setFormatter(_log.Formatter("%(asctime)s %(levelname)s %(message)s"))
                    _dbg.addHandler(_fh)
                    _dbg.setLevel(_log.DEBUG)

                _dbg.debug("auto-load START model=%r gpu=%r ctx=%r",
                           model_id, settings.get("gpu_placement"), settings["context_length"])
                success, error_msg, loaded_id = _auto_load_local_model(model_id, settings, _dbg)
            except Exception as exc:  # always report back, so _loading_model ends
                error_msg = str(exc)
            # Back to main thread
            try:
                self.after(0, lambda: self._on_auto_load_complete(
                    model_id, success, error_msg, loaded_id))
            except Exception:
                pass

        worker = threading.Thread(target=_load, daemon=True)
        worker.start()
        track = getattr(self, "track_model_work", None)
        if track:
            track(worker)   # sending waits while it runs

    def _on_auto_load_complete(self, model_id: str, success: bool, error: str,
                               loaded_id: Optional[str] = None):
        """Handle auto-load result on main thread.

        *loaded_id* is the instance id LM Studio gave the load; chat requests
        must use it, so it replaces *model_id* when it differs."""
        self._loading_model = False
        self.model_combo.configure(state="readonly")

        target = loaded_id if success and loaded_id else model_id
        if success:
            in_ram = getattr(self, "_loading_placement", None) == "cpu"
            if error:  # loaded, but the GPU could not be confirmed
                self._show_load_status("sidebar.model_loaded_gpu_unconfirmed", prefix="\u26a0 ")
            elif in_ram:  # layers in RAM; LM Studio may still use some GPU memory
                self._show_load_status("sidebar.model_loaded_cpu", prefix="\u2713 ")
            else:
                self._show_load_status("sidebar.model_loaded", prefix="\u2713 ")
            self._model_states[target] = "loaded"
            if target != model_id:
                # Route the new id to LM Studio before the next refresh lists it.
                self.model_var.set(target)
                if not self._is_local_entry(target):
                    self._lm_studio_models.append((target, target, "LM Studio"))
                    self._all_models.append((target, target, "LM Studio"))
                if self.on_local_models:
                    self.on_local_models([mid for mid, _, _ in self._lm_studio_models])
            self.after(500, self.refresh_models)
            # A note (unconfirmed GPU, CPU only) stays long enough to be read.
            self.after(8000 if error or in_ram else 1500, lambda: self._show_load_status(""))
        else:
            short_err = error[:80] if error else t("sidebar.unknown_error")
            self._show_load_status("sidebar.load_failed", prefix="\u2717 ", error=short_err)
            self.after(5000, lambda: self._show_load_status(""))
            # The load unloads existing instances first: refresh the states.
            self.after(500, self.refresh_models)

        # Notify HermesGUI of load result
        if self.on_auto_load:
            self.on_auto_load(target, success, error)
        # Always switch to the model (user may have loaded it manually)
        if self.on_model_change:
            self.on_model_change(target)

    def _load_sessions(self):
        """Load recent sessions that have messages (empty ones, e.g. a first
        turn that failed, have nothing to resume, so the sidebar hides them)."""
        try:
            with open_store() as store:
                sessions = store.list_with_messages(limit=20)
            self._sessions_data = sessions
            self._render_sessions()
        except Exception:
            self._sessions_data = []
            self._render_sessions()

    def _render_sessions(self):
        for widget in self.session_frame.winfo_children():
            widget.destroy()
        self._session_widgets = {}
        if not self._sessions_data:
            tk.Label(self.session_frame, text=t("sidebar.no_sessions"),
                    font=FONTS["small"], fg=C["text_disabled"],
                    bg=C["bg_sidebar"], padx=12).pack(anchor="w", pady=4)
            return
        for sess in self._sessions_data:
            self._add_session_entry(sess)

    def _add_session_entry(self, sess):
        sid = sess.get("id", "")
        title = sess.get("title") or sess.get("preview") or t("sidebar.untitled")
        if len(title) > 35:
            title = title[:32] + "..."
        model = sess.get("model", "")
        msg_count = sess.get("message_count", 0)

        if not hasattr(self, '_session_widgets'):
            self._session_widgets = {}
        entry = tk.Frame(self.session_frame, bg=C["bg_sidebar"], padx=12, pady=4,
                        cursor="hand2")
        entry.pack(fill="x", pady=1)
        self._session_widgets[sid] = entry

        # Top row: title + delete button
        top_row = tk.Frame(entry, bg=C["bg_sidebar"])
        top_row.pack(fill="x")

        tk.Label(top_row, text=title, font=FONTS["small"],
                fg=C["text_primary"], bg=C["bg_sidebar"],
                anchor="w", justify="left",   # a wrapped second line too
                wraplength=S(190)).pack(side="left", fill="x", expand=True)

        # Delete button (only visible on hover)
        del_btn = tk.Label(top_row, text="\u2715", font=SF("Segoe UI", 9),
                          fg=C["bg_sidebar"], bg=C["bg_sidebar"],
                          cursor="hand2", padx=4)
        del_btn.pack(side="right")
        del_btn.bind("<Button-1>", lambda e, s=sid: self._delete_session(s))

        info_text = t("sidebar.session_messages", count=msg_count)
        if model:
            short_model = model.split("/")[-1][:15]
            info_text += f" | {short_model}"

        tk.Label(entry, text=info_text, font=SF("Segoe UI", 8),
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
        allowed = getattr(self, "can_delete_session", None)
        if allowed is not None and not allowed(session_id):
            return
        if self._confirm_delete:
            # Custom dialog with "don't show again" checkbox
            dlg = tk.Toplevel(self)
            dlg.title(t("sidebar.delete_title"))
            dlg.configure(bg=C["bg_main"])
            dlg.transient(self.winfo_toplevel())
            dlg.grab_set()

            # Content — pack first so we can measure before geometry
            tk.Label(dlg, text=t("sidebar.delete_question"),
                    font=FONTS["subheading"], fg=C["text_primary"],
                    bg=C["bg_main"]).pack(pady=(20, 4))
            tk.Label(dlg, text=t("sidebar.delete_warning"),
                    font=FONTS["small"], fg=C["text_hint"],
                    bg=C["bg_main"], justify="center").pack(pady=(0, 12))

            # Don't show again checkbox
            dont_ask = tk.BooleanVar(value=False)
            tk.Checkbutton(dlg, text=t("sidebar.dont_ask_again"),
                          variable=dont_ask, font=FONTS["small"],
                          fg=C["text_secondary"], bg=C["bg_main"],
                          selectcolor=C["bg_input"],
                          activebackground=C["bg_main"],
                          activeforeground=C["text_primary"]).pack(pady=(0, 8))

            btn_frame = tk.Frame(dlg, bg=C["bg_main"])
            btn_frame.pack(pady=(4, 16))

            def _do_delete():
                if dont_ask.get():
                    self._confirm_delete = False
                dlg.destroy()
                self._perform_delete(session_id)

            ttk.Button(btn_frame, text=f"  {t('sidebar.delete_action')}  ", style="Danger.TButton",
                       command=_do_delete).pack(side="left", padx=8)
            ttk.Button(btn_frame, text=f"  {t('settings.cancel')}  ", style="TButton",
                       command=dlg.destroy).pack(side="left", padx=8)

            set_dark_title_bar(dlg)
            center_window(dlg, 420, 220, self.winfo_toplevel())
        else:
            self._perform_delete(session_id)

    def _perform_delete(self, session_id):
        """Remove widget instantly, delete from DB in background."""
        # Immediate visual removal
        widget = getattr(self, '_session_widgets', {}).pop(session_id, None)
        if widget:
            widget.destroy()

        # DB delete in background, through the core only: it also removes the
        # session's search index, media and related rows. If it fails, reload
        # the list so the session shows again instead of looking deleted.
        def _do():
            deleted = False
            try:
                with open_store() as store:
                    deleted = store.delete(session_id)
            except Exception:
                deleted = False
            if not deleted:
                try:
                    self.after(0, self._load_sessions)
                except Exception:
                    pass
        threading.Thread(target=_do, daemon=True).start()

    def refresh_sessions(self):
        self._load_sessions()

    def update_ui_language(self):
        """Update static sidebar labels when language changes."""
        if hasattr(self, "new_btn"):
            self.new_btn.configure(text=t("sidebar.new_chat"))
        if hasattr(self, "model_lbl"):
            self.model_lbl.configure(text=t("sidebar.model"))
        if hasattr(self, "sessions_lbl"):
            self.sessions_lbl.configure(text=t("sidebar.recent_sessions"))
        if hasattr(self, "_local_header"):
            for widget, key in (
                (self._local_header, "sidebar.local_settings"),
                (self._local_gpu_label, "sidebar.gpu_short"),
                (self._local_ctx_label, "sidebar.context_short"),
                (self._local_tokens_label, "sidebar.tokens_unit"),
                (self._local_temp_label, "sidebar.temp_short"),
                (self._local_top_p_label, "sidebar.top_p"),
                (self._auto_load_cb, "sidebar.auto_load"),
                (self._flash_attn_cb, "sidebar.flash_attention"),
            ):
                widget.configure(text=t(key))
            self._update_combobox_values()
            self._show_gpu_choices(self._get_gpu_placement())
        if hasattr(self, "session_frame"):
            self._render_sessions()
        if self._load_status_data:
            key, prefix, kwargs = self._load_status_data
            self._load_status_var.set(prefix + t(key, **kwargs))


# ============================================================================
# Settings Dialog
# ============================================================================

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, bridge):
        super().__init__(parent)
        self.bridge = bridge
        self.title(t("settings.title"))
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        self.grab_set()
        set_dark_title_bar(self)
        center_window(self, 550, 480, parent)

        tk.Label(self, text=t("settings.title"), font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(pady=(20, 8))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=16, pady=8)

        # -- API Keys tab --
        api_fr = tk.Frame(nb, bg=C["bg_main"], padx=16, pady=16)
        nb.add(api_fr, text=f"  {t('settings.tab_api')}  ")
        self._build_api(api_fr)

        # -- Model tab --
        mdl_fr = tk.Frame(nb, bg=C["bg_main"], padx=16, pady=16)
        nb.add(mdl_fr, text=f"  {t('settings.tab_model')}  ")
        self._build_model(mdl_fr)

        # -- General tab (Language) --
        gen_fr = tk.Frame(nb, bg=C["bg_main"], padx=16, pady=16)
        nb.add(gen_fr, text=f"  {t('settings.tab_general')}  ")
        self._build_general(gen_fr)

        ttk.Button(self, text=t("settings.save"), style="Primary.TButton",
                   command=self._save).pack(pady=(4, 16))

    def _build_api(self, parent):
        keys = [
            ("OPENROUTER_API_KEY", t("settings.api_openrouter", "OpenRouter (main LLM provider)")),
            ("FIRECRAWL_API_KEY", t("settings.api_firecrawl", "Firecrawl (web search)")),
            ("FAL_KEY", t("settings.api_fal", "FAL.ai (image generation)")),
            ("SERPER_API_KEY", t("settings.api_serper", "Serper.dev (Google search)")),
            ("VOICE_TOOLS_OPENAI_KEY", t("settings.api_openai", "OpenAI (voice/transcription)")),
            ("GITHUB_TOKEN", t("settings.api_github", "GitHub (Skills Hub rate limits)")),
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
        tk.Label(parent, text=t("settings.default_model"), font=FONTS["small"],
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
        self.model_var = tk.StringVar(value="google/gemini-2.5-flash")
        self.model_combo = ttk.Combobox(parent, textvariable=self.model_var,
                                        values=models, font=FONTS["mono_small"])
        self._shown_model = self.model_var.get()   # saved only when changed
        self.model_combo.pack(fill="x", pady=(4, 12))
        tk.Label(parent, text=t("settings.model_hint", "You can type any OpenRouter model ID"),
                font=SF("Segoe UI", 8), fg=C["text_disabled"], bg=C["bg_main"]).pack(anchor="w")

    def _build_general(self, parent):
        tk.Label(parent, text=t("settings.language"), font=FONTS["small"],
                fg=C["text_secondary"], bg=C["bg_main"]).pack(anchor="w", pady=(6, 0))
        lang_names = [name for _, name in SUPPORTED_LANGUAGES]
        curr_code = get_language()
        curr_name = dict(SUPPORTED_LANGUAGES).get(curr_code, "English")
        self.lang_var = tk.StringVar(value=curr_name)
        self.lang_combo = ttk.Combobox(parent, textvariable=self.lang_var,
                                       values=lang_names, state="readonly", font=FONTS["small"])
        self.lang_combo.pack(fill="x", pady=(4, 12))

    def _save(self):
        if self.bridge.is_running:
            # Defensive (the dialog is not opened during a reply): never write
            # what a running reply reads; the dialog stays open.
            messagebox.showinfo(t("settings.title"),
                                t("chat.busy_stop_first", stop=t("chat.stop")), parent=self)
            return
        env_path = get_hermes_home() / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        import re
        content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
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
        # Never during a reply (the dialog is modal). Only a changed model is
        # applied: saving other settings keeps the model (or account) in use.
        if model and model != getattr(self, "_shown_model", None):
            try:
                self.bridge.set_model(model)
            except ModelSaveFailed as exc:     # nothing switched: say why
                messagebox.showerror(t("settings.title"),
                                     t("chat.model_save_failed", model=model, error=exc), parent=self)
        env_path.write_text(content, encoding="utf-8")

        # Save language preference
        chosen_name = self.lang_var.get()
        for code, name in SUPPORTED_LANGUAGES:
            if name == chosen_name:
                set_language(code, persist=True)
                break

        self.destroy()


# ============================================================================
# Skills Browser
# ============================================================================

def _discover_installed_skills(skills_dir: Path) -> Dict[str, list]:
    """Return current nested SKILL.md entries grouped for the GUI browser."""
    try:
        import hermes_yaml as yaml      # the core's YAML module; upstream dropped PyYAML
    except ImportError:
        import yaml                     # older cores

    categories: Dict[str, list] = {}
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        relative_dir = skill_md.parent.relative_to(skills_dir)
        if any(part.startswith(".") for part in relative_dir.parts):
            continue

        name = skill_md.parent.name
        description = ""
        category = relative_dir.parts[0] if len(relative_dir.parts) > 1 else "uncategorized"
        try:
            text = skill_md.read_text(encoding="utf-8")
            if text.startswith("---"):
                frontmatter = yaml.safe_load(text.split("---", 2)[1]) or {}
                name = str(frontmatter.get("name") or name)
                description = str(frontmatter.get("description") or "")
                hermes_meta = (frontmatter.get("metadata") or {}).get("hermes") or {}
                category = str(hermes_meta.get("category") or category)
        except Exception:
            pass
        categories.setdefault(category, []).append((name, description))
    return categories

class SkillsBrowser(tk.Toplevel):
    def __init__(self, parent, may_sync=False):
        """*may_sync*: no reply is running, so the list may first run the
        once-per-process skills sync; otherwise it lists what is there."""
        super().__init__(parent)
        self._may_sync = may_sync
        self.title(t("skills.title", "Skills Browser"))
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        set_dark_title_bar(self)
        center_window(self, 650, 500, parent)

        self._heading = tk.Label(self, text=t("skills.heading", "Installed Skills"), font=FONTS["title"],
                                 fg=C["accent"], bg=C["bg_main"])
        self._heading.pack(pady=(20, 8))

        self.text = tk.Text(self, wrap="word", bg=C["bg_card"], fg=C["text_primary"],
                           font=FONTS["mono_small"], relief="flat", padx=16, pady=12,
                           highlightthickness=0)
        sb = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 16), pady=(0, 16))
        self.text.pack(fill="both", expand=True, padx=(16, 0), pady=(0, 16))

        self._content_data = None
        register_listener(self.update_ui_language)
        self._result = queue.SimpleQueue()
        threading.Thread(target=self._load, daemon=True).start()
        self._poll_result()

    def destroy(self):
        unregister_listener(self.update_ui_language)
        if getattr(self, "_poll_id", None):
            self.after_cancel(self._poll_id)
            self._poll_id = None
        super().destroy()

    def update_ui_language(self, _lang_code=None):
        self.title(t("skills.title"))
        self._heading.configure(text=t("skills.heading"))
        if self._content_data:
            key, kwargs = self._content_data
            self._set(t(key, **kwargs), key=key, **kwargs)

    def _load(self):
        """Worker thread: never touches Tk; the result goes through
        self._result to _poll_result on the Tk thread."""
        self._result.put(self._read_skills())

    def _poll_result(self):
        """Tk thread: show the worker's result once it is there."""
        try:
            text, key, kwargs = self._result.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(50, self._poll_result)
            return
        self._poll_id = None
        self._set(text, key=key, **kwargs)

    def _read_skills(self):
        """(text, i18n key or None, key arguments) for the list."""
        try:
            if self._may_sync:
                sync_bundled_skills_once()   # a home not made by install.bat has none yet
            skills_dir = get_hermes_home() / "skills"
            if not skills_dir.exists():
                return t("skills.no_dir"), "skills.no_dir", {}
            cats = _discover_installed_skills(skills_dir)
            lines = []
            for cat in sorted(cats):
                lines.append(f"\n  {cat.upper()}")
                lines.append("  " + "-" * 40)
                for n, d in cats[cat]:
                    lines.append(f"    {n:30s} {d[:50]}" if d else f"    {n}")
            if lines:
                return "\n".join(lines), None, {}
            return t("skills.no_skills"), "skills.no_skills", {}
        except Exception as e:
            error = str(e)
            return t("skills.load_error", error=error), "skills.load_error", {"error": error}

    def _set(self, txt, key=None, **kwargs):
        self._content_data = (key, kwargs) if key else None
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", txt)
        self.text.configure(state="disabled")


# ============================================================================
# Status Bar
# ============================================================================

class StatusBar(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C["bg_sidebar"], height=S(28))
        self.pack_propagate(False)

        self.dot = tk.Label(self, text="\u25CF", font=SF("Segoe UI", 10),
                           fg=C["success"], bg=C["bg_sidebar"])
        self.dot.pack(side="left", padx=(12, 4))

        self.status_lbl = tk.Label(self, text=t("status.ready"), font=FONTS["small"],
                                  fg=C["text_hint"], bg=C["bg_sidebar"])
        self.status_lbl.pack(side="left")

        # How long the running reply has taken (empty when idle).
        self.clock_lbl = tk.Label(self, text="", font=FONTS["mono_small"],
                                  fg=C["text_hint"], bg=C["bg_sidebar"])
        self.clock_lbl.pack(side="left", padx=(8, 0))

        self.model_lbl = tk.Label(self, text="", font=FONTS["mono_small"],
                                 fg=C["text_disabled"], bg=C["bg_sidebar"])
        self.model_lbl.pack(side="right", padx=12)

        self.iter_lbl = tk.Label(self, text="", font=FONTS["mono_small"],
                                fg=C["text_disabled"], bg=C["bg_sidebar"])
        self.iter_lbl.pack(side="right", padx=8)

        self._state_kind = "ready"
        self._state_data = ""
        self._usage_kind = ""
        self._usage_value = 0

    def set_ready(self):
        self._state_kind = "ready"
        self._state_data = ""
        self.dot.configure(fg=C["success"])
        self.status_lbl.configure(text=t("status.ready"))

    def set_thinking(self, text=""):
        self._state_kind = "thinking"
        self._state_data = text
        self.dot.configure(fg=C["info"])
        if text:
            display = text[:120] if len(text) > 120 else text
            self.status_lbl.configure(text=display)
        else:
            self.status_lbl.configure(text=t("status.thinking"))

    def set_thinking_key(self, key, **kwargs):
        """Keep a localized activity message refreshable during language changes."""
        self._state_kind = "thinking_key"
        self._state_data = (key, kwargs)
        self.dot.configure(fg=C["info"])
        self.status_lbl.configure(text=t(key, **kwargs))

    def set_tool(self, name):
        self._state_kind = "tool"
        self._state_data = name
        self.dot.configure(fg=C["warning_dark"])
        self.status_lbl.configure(text=t("status.tool_calling", tool=name))

    def set_error(self):
        self._state_kind = "error"
        self._state_data = ""
        self.dot.configure(fg=C["danger"])
        self.status_lbl.configure(text=t("status.error", error=""))

    def set_activity(self, text, seconds, tool=False):
        """A running reply's state, as its activity line says it (the line's
        own clock next to it)."""
        self._state_kind = "activity"
        self.dot.configure(fg=C["warning_dark"] if tool else C["info"])
        self.status_lbl.configure(text=text)
        self.set_elapsed(seconds)

    def set_elapsed(self, seconds=None):
        """The running reply's clock next to the status text; None clears it."""
        self.clock_lbl.configure(text="" if seconds is None else clock(seconds))

    def set_model(self, m):
        self.model_lbl.configure(text=m)

    def set_iter(self, n):
        self._usage_kind = "step"
        self._usage_value = n
        self.iter_lbl.configure(text=t("status.step", count=n))

    def set_tokens(self, count):
        self._usage_kind = "tokens"
        self._usage_value = count
        self.iter_lbl.configure(text=t("chat.token_count", count=f"{count:,}"))

    def update_ui_language(self):
        """Refresh status label in current language while preserving activity state."""
        if self._state_kind == "ready":
            self.status_lbl.configure(text=t("status.ready"))
        elif self._state_kind == "thinking":
            if self._state_data:
                display = self._state_data[:120] if len(self._state_data) > 120 else self._state_data
                self.status_lbl.configure(text=display)
            else:
                self.status_lbl.configure(text=t("status.thinking"))
        elif self._state_kind == "thinking_key":
            key, kwargs = self._state_data
            self.status_lbl.configure(text=t(key, **kwargs))
        elif self._state_kind == "tool":
            self.status_lbl.configure(text=t("status.tool_calling", tool=self._state_data))
        elif self._state_kind == "error":
            self.status_lbl.configure(text=t("status.error", error=""))
        if self._usage_kind == "step":
            self.iter_lbl.configure(text=t("status.step", count=self._usage_value))
        elif self._usage_kind == "tokens":
            self.iter_lbl.configure(text=t("chat.token_count", count=f"{self._usage_value:,}"))


# ============================================================================
# Main Application
# ============================================================================

class HermesGUI:
    _chat_title_kind = "new"     # "new" or "resumed": the header until a title is known
    _title_session = None        # the session id _show_session_title last showed
    _chat_title_text = None      # the session's title once it has one
    _turn_clock_id = None        # the running reply's per-second clock (Tk after id)
    _follow_reply = True         # keep the chat's bottom in view (the user did not scroll up)
    _scroll_id = None            # the one pending _do_scroll
    _current_turn = None         # the bridge's id of the reply running now

    def _bridge_callbacks(self):
        return dict(
            on_response=self._on_response, on_tool_call=self._on_tool_call,
            on_thinking=self._on_thinking, on_error=self._on_error,
            on_step=self._on_step, on_clarify=self._on_clarify,
            on_complete=self._on_complete, on_approval=self._on_approval,
            on_reasoning=self._on_reasoning, on_stream_delta=self._on_stream_delta,
            on_worker_done=self._on_worker_done, accept_turn=self._is_current_turn)

    def _is_current_turn(self, turn) -> bool:
        """The bridge delivers a turn's callbacks only while that turn is the
        one running: not after Stop, New Chat, a session switch, window close
        or its own end, and never into a later turn."""
        return turn is not None and turn == self._current_turn

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # Hide until fully themed to avoid white flash

        # DPI awareness + scaling — must happen before any geometry calls
        init_dpi_scaling(self.root)

        self.root.title(t("app.title"))
        self.root.geometry(f"{S(1100)}x{S(700)}")
        self.root.minsize(S(900), S(550))

        # Apply full theme (also sets dark title bar)
        apply_theme(self.root)

        # Center and show
        center_window(self.root, 1100, 700)
        self.root.deiconify()

        # Agent bridge
        self.bridge = AgentBridge(self.root, **self._bridge_callbacks())
        self._stream_bubble = None  # Active streaming bubble
        self._has_streamed = False   # True once any stream delta arrived
        # Reply activity: the View > Show Thinking and open-or-closed
        # choices (gui_config.json).
        self._show_thinking = load_gui_setting("show_thinking", True)
        self._thinking_open = load_gui_setting("thinking_open", False)

        self._build_menu()
        self._build_layout()

        # Register GUI language change listener so all entry points (menu, Settings) trigger uniform UI refresh
        register_listener(self._on_language_changed)

        # First-run wizard — show if any required keys are missing
        missing = get_missing_keys()
        if any(s["required"] for s in missing):
            self.root.after(500, self._first_run_api_setup)

        model = self.bridge.get_model()
        self.status_bar.set_model(self._model_label(model))
        self.sidebar.set_model(model)
        if self._active_account():     # config names a signed-in account
            self._load_account_models(self._active_account())

        # Show local settings if current model is local
        if self.bridge._is_local_model(model):
            self.sidebar._show_local_settings(True)

        # Show context-aware welcome message
        has_key = self.bridge._is_model_configured()
        if has_key:
            self._add_msg(t("chat.welcome_configured"), "system")
        else:
            self._add_msg(t("chat.welcome_unconfigured"), "system")

        # Notify user if we fell back from a local model
        if self.bridge._startup_fallback:
            orig = getattr(self.bridge, '_startup_original_model', 'local model')
            self._add_msg(
                f"LM Studio not detected. Local model \"{orig}\" unavailable.\n"
                f"Using {model} instead. Start LM Studio and select your local model from the dropdown to switch back.",
                "system"
            )

        self.root.bind("<Control-n>", lambda e: self._new_chat())
        self.root.bind("<Control-comma>", lambda e: self._open_settings())
        self.root.bind("<Escape>", lambda e: self._interrupt())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- Menu ----

    def _build_menu(self):
        # Custom dark menu bar (frame-based to avoid Windows white menu strip)
        self.menu_bar = tk.Frame(self.root, bg=C["bg_sidebar"], height=S(28))
        self.menu_bar.pack(fill="x", side="top")
        self.menu_bar.pack_propagate(False)
        self._build_menu_items()

    def _build_menu_items(self):
        for widget in self.menu_bar.winfo_children():
            widget.destroy()

        current_lang = get_language()
        for label, items in [
            (t("menu.file"), [
                (t("menu.new_chat"), self._new_chat),
                None,
                (t("menu.api_setup"), self._show_api_setup),
                (t("menu.permissions"), self._open_permissions),
                (t("menu.settings"), self._open_settings),
                None,
                (t("menu.exit"), self._on_close),
            ]),
            (t("menu.view"), [
                (t("menu.lm_studio"), self._open_lm_studio),
                (t("menu.accounts"), self._open_accounts),
                (t("menu.skills"), self._open_skills),
                (t("menu.extensions"), self._open_extensions),
                None,
                (t("menu.toggle_sidebar"), self._toggle_sidebar),
                (f"{'✓ ' if self._show_thinking else '   '}{t('menu.show_thinking')}",
                 self._toggle_show_thinking),
            ]),
            (t("menu.language"), [
                (f"{'✓ ' if current_lang == code else '   '}{name}", lambda c=code: self._switch_language(c))
                for code, name in SUPPORTED_LANGUAGES
            ]),
            (t("menu.help"), [
                (t("menu.about"), self._about),
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

    def _toggle_show_thinking(self):
        """View > Show Thinking: off keeps no thinking text (the waiting
        line and its clock stay). Applies from the next reply."""
        self._show_thinking = not self._show_thinking
        save_gui_setting("show_thinking", self._show_thinking)
        self._build_menu_items()

    def _remember_thinking_open(self, opened):
        """The user's last open/closed choice, for later replies and restarts."""
        self._thinking_open = opened
        save_gui_setting("thinking_open", opened)

    def _switch_language(self, lang_code: str):
        set_language(lang_code, persist=True)

    def _on_language_changed(self, lang_code: str):
        """
        Unified language refresh handler triggered whenever the language changes
        (from the Language menu, SettingsDialog, or external programmatic call).
        Refreshes title, menu, sidebar, status bar (preserving activity state),
        and composer controls/tooltips.
        """
        # 1. Window title
        self.root.title(t("app.title"))

        # 2. Rebuild menu bar items
        self._build_menu_items()

        # 3. Sidebar labels
        if hasattr(self, "sidebar") and hasattr(self.sidebar, "update_ui_language"):
            self.sidebar.update_ui_language()

        # 4. Status bar (preserves current activity state: ready/thinking/tool/error)
        if hasattr(self, "status_bar") and hasattr(self.status_bar, "update_ui_language"):
            self.status_bar.update_ui_language()

        # 5. Composer buttons and tooltips
        if hasattr(self, "attach_btn") and self.attach_btn.winfo_exists():
            self.attach_btn.configure(text=t("chat.attach"))
        if hasattr(self, "attach_tooltip"):
            self.attach_tooltip.text = t("chat.attach_tooltip")

        if hasattr(self, "send_btn") and self.send_btn.winfo_exists():
            self.send_btn.configure(text=t("chat.send"))
        if hasattr(self, "send_tooltip"):
            self.send_tooltip.text = t("chat.send_tooltip")

        if hasattr(self, "stop_btn") and self.stop_btn.winfo_exists():
            self.stop_btn.configure(text=t("chat.stop"))
        if hasattr(self, "stop_tooltip"):
            self.stop_tooltip.text = t("chat.stop_tooltip")

        # 6. Chat title and persistent message headers
        if hasattr(self, "chat_title") and self.chat_title.winfo_exists():
            self._set_chat_title(self._chat_title_kind, self._chat_title_text)
        if hasattr(self, "msg_frame"):
            for child in self.msg_frame.winfo_children():
                if isinstance(child, MessageBubble):
                    child.update_ui_language()

    # ---- Layout ----

    def _build_layout(self):
        main = tk.Frame(self.root, bg=C["bg_main"])
        main.pack(fill="both", expand=True)

        # Sidebar
        self.sidebar = Sidebar(main, on_new=self._new_chat,
                               on_model_change=self._on_model_change,
                               on_session_select=self._on_session_select,
                               on_local_models=self._on_local_models_discovered,
                               on_auto_load=self._on_auto_load_status,
                               can_delete_session=self._can_delete_session,
                               can_change_model=lambda: not self._refuse_while_running(),
                               track_model_work=self._track_model_work)
        self.sidebar.pack(side="left", fill="y")

        # Vertical separator
        tk.Frame(main, bg=C["separator"], width=1).pack(side="left", fill="y")

        # Chat area
        chat_area = tk.Frame(main, bg=C["bg_main"])
        chat_area.pack(side="left", fill="both", expand=True)

        # Chat header
        hdr = tk.Frame(chat_area, bg=C["bg_sidebar"], height=S(40))
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self._chat_title_kind = "new"
        self.chat_title = tk.Label(hdr, text=t("chat.new_chat_title"), font=FONTS["subheading"],
                                  fg=C["text_primary"], bg=C["bg_sidebar"])
        self.chat_title.pack(side="left", padx=16)

        # Stop button is created here but packed in the input area (next to Send)
        # so it doesn't overlap the chat. See btn_frame below.

        # Messages scroll area
        msg_outer = tk.Frame(chat_area, bg=C["bg_main"])
        msg_outer.pack(fill="both", expand=True)

        self.msg_canvas = tk.Canvas(msg_outer, bg=C["bg_main"],
                                    highlightthickness=0, borderwidth=0)
        self.msg_sb = ttk.Scrollbar(msg_outer, orient="vertical", command=self._scrollbar_moved)
        self.msg_canvas.configure(yscrollcommand=self.msg_sb.set)

        self.msg_sb.pack(side="right", fill="y")
        self.msg_canvas.pack(side="left", fill="both", expand=True)

        self.msg_frame = tk.Frame(self.msg_canvas, bg=C["bg_main"])
        self._msg_win = self.msg_canvas.create_window((0, 0), window=self.msg_frame, anchor="nw")

        self.msg_frame.bind("<Configure>", self._on_msg_frame_resized)
        self.msg_canvas.bind("<Configure>", lambda e: self.msg_canvas.itemconfig(
            self._msg_win, width=e.width))

        # Mouse wheel
        def _mw(event):
            self.msg_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            self._note_user_scroll()
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

        self.attach_btn = ttk.Button(btn_row, text=t("chat.attach"), width=8,
                                     command=self._attach_image)
        self.attach_btn.pack(side="left", padx=(0, 4))
        self.attach_tooltip = Tooltip(self.attach_btn, t("chat.attach_tooltip"))

        self.send_btn = ttk.Button(btn_row, text=t("chat.send"), style="Primary.TButton",
                                   command=self._send)
        self.send_btn.pack(side="right", padx=(4, 0))
        self.send_tooltip = Tooltip(self.send_btn, t("chat.send_tooltip"))

        self.stop_btn = ttk.Button(btn_row, text=t("chat.stop"), style="Danger.TButton",
                                   command=self._interrupt)
        self.stop_btn.pack(side="right", padx=(4, 0))
        self.stop_tooltip = Tooltip(self.stop_btn, t("chat.stop_tooltip"))

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
            title=t("chat.attach_image_title"),
            filetypes=[
                (t("chat.image_files"), "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                (t("chat.all_files"), "*.*"),
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
            tk.Label(chip, text=fname, font=SF("Segoe UI", 8),
                    fg=C["text_secondary"], bg=C["bg_card"]).pack(side="left")

            rm_btn = tk.Label(chip, text=" \u2715", font=SF("Segoe UI", 9, "bold"),
                            fg=C["danger"], bg=C["bg_card"], cursor="hand2")
            rm_btn.pack(side="left")
            rm_btn.bind("<Button-1>", lambda e, p=path: self._remove_image(p))

    def _send(self):
        msg = self.input_text.get("1.0", "end-1c").strip()
        if not msg or self.bridge.is_running:
            return
        if self._model_work_running():  # the message stays in the input box
            self._add_notice(t("chat.model_loading_wait"))
            return
        self.input_text.delete("1.0", "end")

        # Show attachments in the chat
        display = msg
        if self._attached_images:
            fnames = [os.path.basename(p) for p in self._attached_images]
            display = msg + "\n\U0001f4ce " + ", ".join(fnames)
        self._add_msg(display, "user")

        # Streaming bubble — shows tokens as they arrive, below its activity line
        # A session's first turn (any provider) sends Hermes's instructions.
        # A previous turn whose end has not been delivered yet keeps what it
        # showed; its late callbacks are dropped (_is_current_turn).
        self._cleanup_stream_bubble()
        self._new_reply_bubble(first_turn=not self.bridge.conversation_history)
        self._follow_reply = True        # the user just sent: show the reply
        self._has_streamed = False

        self._start_turn_clock()

        # Send with images
        images = list(self._attached_images) if self._attached_images else None
        self._attached_images.clear()
        self._update_attach_preview()

        self._current_turn = self.bridge.send_message(msg, image_paths=images)
        self._scroll_bottom()

    def _add_msg(self, text, msg_type, tool_name=None):
        w = MessageBubble(self.msg_frame, text, msg_type=msg_type, tool_name=tool_name)
        w.pack(fill="x")
        # The user's own message always shows; anything else (a refusal
        # notice during a reply...) only if they did not scroll up.
        self._scroll_bottom(force=msg_type == "user")

    def _scrollbar_moved(self, *args):
        self.msg_canvas.yview(*args)
        self._note_user_scroll()

    def _note_user_scroll(self):
        """The user scrolled the chat: follow a running reply again only if
        they left the view at the bottom (never fight a user who scrolled up)."""
        self._follow_reply = self.msg_canvas.yview()[1] >= 0.999

    def _on_msg_frame_resized(self, _event=None):
        """The chat grew or shrank. While a reply runs (thinking pane, answer
        or activity line growing) its bottom stays in view, unless the user
        scrolled up."""
        self.msg_canvas.configure(scrollregion=self.msg_canvas.bbox("all"))
        if self._stream_bubble is not None and self._follow_reply:
            self.msg_canvas.yview_moveto(1.0)

    def _scroll_bottom(self, force=False):
        """Scroll to the bottom shortly, once however often asked, and only
        if the user is still following when it runs (force: follow again)."""
        if force:
            self._follow_reply = True
        if self._scroll_id is None:
            self._scroll_id = self.root.after(10, self._do_scroll)

    def _do_scroll(self):
        self._scroll_id = None
        if not self._follow_reply:       # the user scrolled up meanwhile
            return
        self.msg_canvas.update_idletasks()
        self.msg_canvas.configure(scrollregion=self.msg_canvas.bbox("all"))
        self.msg_canvas.yview_moveto(1.0)

    # ---- Callbacks ----

    def _new_reply_bubble(self, tool=None, first_turn=False):
        """A streaming bubble whose activity line waits for the model (or
        shows *tool* running)."""
        activity = ReplyActivity(keep_thinking=self._show_thinking,
                                 first_turn=first_turn, tool=tool)
        self._stream_bubble = StreamingBubble(self.msg_frame, activity, self._thinking_open,
                                              self._remember_thinking_open)
        self._stream_bubble.pack(fill="x")

    def _start_turn_clock(self):
        self._stop_turn_clock()
        self._turn_started = time.monotonic()
        self._show_activity_status()
        self._turn_clock_id = self.root.after(1000, self._tick_turn_clock)

    def _tick_turn_clock(self):
        """Every second while a reply runs: the activity line's clock and the
        status bar's clock move."""
        self._turn_clock_id = None
        if self._stream_bubble is not None:
            self._stream_bubble.refresh_activity()
        self._show_activity_status()
        self._turn_clock_id = self.root.after(1000, self._tick_turn_clock)

    def _show_activity_status(self):
        """The status bar says what the reply bubble's line says (same state,
        same clock, no thinking tail). While the answer streams it keeps its
        text ("Streaming") and shows the turn's clock."""
        activity = getattr(self._stream_bubble, "activity", None)
        status = activity.status() if activity is not None else None
        if status is None:
            self.status_bar.set_elapsed(time.monotonic() - self._turn_started)
            return
        text, seconds = status
        self.status_bar.set_activity(text, seconds, tool=activity.state == "tool")

    def _stop_turn_clock(self):
        """Every way a turn ends: reply done, error, Stop, New Chat, window
        close. Callbacks the worker still posts for it are dropped."""
        self._current_turn = None
        if self._turn_clock_id is not None:
            try:
                self.root.after_cancel(self._turn_clock_id)
            except tk.TclError:
                pass
            self._turn_clock_id = None
            self.status_bar.set_elapsed(None)

    def _on_response(self, text):
        if self._stream_bubble:
            # Streaming bubble still alive — finalize it
            if self._stream_bubble.has_content():
                self._stream_bubble.finalize()
                if text and not self._has_streamed and not self._stream_bubble.get_text().strip():
                    self._add_msg(text, "ai")       # thinking above, the answer below
            else:
                try:
                    self._stream_bubble.destroy()
                except tk.TclError:
                    pass
                # No streamed content — show full response as regular bubble
                if text and not self._has_streamed:
                    self._add_msg(text, "ai")
            self._stream_bubble = None
        elif text and not self._has_streamed:
            # Only show full response if we never streamed (non-streaming model/fallback)
            self._add_msg(text, "ai")

    def _on_tool_call(self, name, preview):
        # Finalize any in-progress streaming bubble before showing the tool call
        self._cleanup_stream_bubble()
        w = ToolCallWidget(self.msg_frame, name, preview)
        w.pack(fill="x")
        # A new streaming bubble for the next response segment; its line
        # shows the tool running until the model is called again.
        self._new_reply_bubble(tool=name)
        self._show_activity_status()
        if self._follow_reply:
            self._scroll_bottom()

    def _on_stream_delta(self, text):
        """Append a token to the streaming bubble."""
        if text is None:
            # End-of-turn signal — finalize the current bubble
            if self._stream_bubble and self._stream_bubble.has_content():
                self._stream_bubble.finalize()
                self._stream_bubble = None
            return
        if self._stream_bubble:
            self._has_streamed = True
            self._stream_bubble.append_text(text)
            if self._follow_reply:
                self._scroll_bottom()
            self.status_bar.set_thinking_key("status.streaming")

    def _cleanup_stream_bubble(self):
        """Remove or finalize the active streaming bubble (unless its widget
        is already gone, e.g. with a cleared chat)."""
        if self._stream_bubble:
            try:
                alive = bool(self._stream_bubble.winfo_exists())
            except tk.TclError:
                alive = False
            if not alive:
                pass
            elif self._stream_bubble.has_content():
                self._stream_bubble.finalize()
            else:
                try:
                    self._stream_bubble.destroy()
                except tk.TclError:
                    pass
            self._stream_bubble = None

    def _on_thinking(self, text):
        """The core's spinner phrase: not shown, the status bar follows the
        reply bubble's line."""

    def _on_step(self, n, _):
        self.status_bar.set_iter(n)
        if self._stream_bubble is not None and self._stream_bubble.activity is not None:
            self._stream_bubble.activity.model_called()     # a tool ran; waiting again
            self._stream_bubble.refresh_activity()
            self._show_activity_status()

    def _on_error(self, msg):
        self._stop_turn_clock()
        self._cleanup_stream_bubble()
        self._add_msg(msg, "error")
        self.status_bar.set_error()

    def _on_clarify(self, question, choices=None):
        resp = simpledialog.askstring(t("chat.clarify_title"), question, parent=self.root)
        self.bridge.respond_to_clarify(resp or "")

    def _on_approval(self, command, description=None):
        """Dangerous command approval dialog."""
        msg = t("chat.approval_intro", command=command)
        if description:
            msg += t("chat.approval_reason", description=description)
        msg += t("chat.approval_question")
        approved = messagebox.askyesno(t("chat.approval_title"), msg, parent=self.root)
        self.bridge.respond_to_approval(approved)

    def _on_reasoning(self, text):
        """Thinking text: into the reply bubble's activity line (and, when
        open, its thinking pane); the status bar says the model is thinking."""
        if not text:
            return
        if self._stream_bubble is not None:
            self._stream_bubble.add_thinking(text)
            self._show_activity_status()

    def _on_complete(self, result):
        self._stop_turn_clock()
        self._cleanup_stream_bubble()
        self.status_bar.set_ready()

    def _on_worker_done(self):
        """A worker ended, whatever its turn (done, failed or stopped): what
        it saved shows in the token count, session list and header."""
        tokens = self.bridge.get_token_usage()
        if tokens.get("total"):
            total = tokens["total"]
            self.status_bar.set_tokens(total)
        # Refresh session list; the header shows the title once there is one
        try:
            self.sidebar.refresh_sessions()
            self._show_session_title(self.bridge.session_id)
        except Exception:
            pass

    def _set_chat_title(self, kind, title=None):
        """Chat header: the session's title when it has one, else "New Chat"
        or "Resumed Session" (*kind*)."""
        self._chat_title_kind = kind
        self._chat_title_text = title or None
        if title and len(title) > 60:
            title = title[:57] + "..."
        key = "chat.resumed_session" if kind == "resumed" else "chat.new_chat_title"
        self.chat_title.configure(text=title or t(key))

    def _show_session_title(self, session_id, kind=None):
        """Header for *session_id*: its title, as the sidebar's session list
        (just refreshed) has it, else the *kind* label. Without *kind*: the
        header's kind while it shows the same session (a resumed untitled
        session stays "Resumed Session"), else "New Chat" (a rebuilt
        agent's new session has no title yet)."""
        if kind is None:
            kind = self._chat_title_kind if session_id == self._title_session else "new"
        self._title_session = session_id
        title = next((s.get("title") for s in getattr(self.sidebar, "_sessions_data", None) or []
                      if session_id and s.get("id") == session_id), None)
        self._set_chat_title(kind, title)

    # ---- Commands ----

    def _refuse_while_running(self) -> bool:
        """While a reply is running, session changes are refused (the running
        turn would write into the new session); True when refused."""
        if not self.bridge.is_running:
            return False
        self._add_notice(t("chat.busy_stop_first", stop=t("chat.stop")))
        return True

    def _add_notice(self, text):
        """A System line, unless the chat's last line is already this one
        (refusals in a row would repeat it)."""
        children = self.msg_frame.winfo_children()
        last = children[-1] if children else None
        if (isinstance(last, MessageBubble) and last._msg_type == "system"
                and last._text == text):
            return
        self._add_msg(text, "system")

    def _can_delete_session(self, session_id) -> bool:
        """Sidebar delete guard: not the active session while its turn runs."""
        if session_id and session_id == self.bridge.session_id and self._refuse_while_running():
            return False
        return True

    def _note_dropped_resume(self, dropped: bool):
        if dropped:
            self._add_msg(t("chat.resume_not_continued"), "system")

    def _clear_chat(self):
        """Empty the chat area (New Chat, loading a session): no earlier
        turn's callback lands here, no reference to a destroyed bubble stays,
        and the (empty) view follows its end again."""
        self._stop_turn_clock()
        self._stream_bubble = None
        self._has_streamed = False
        for w in self.msg_frame.winfo_children():
            w.destroy()
        self._follow_reply = True

    def _new_chat(self):
        if self._refuse_while_running() or not self.bridge.new_session():
            return
        self._clear_chat()
        self._set_chat_title("new")
        self.status_bar.set_ready()
        self._add_msg(t("chat.session_started", "New session started."), "system")
        self.input_text.focus_set()
        self.sidebar.refresh_sessions()

    def _on_local_models_discovered(self, model_ids):
        """Called when sidebar discovers local models from LM Studio."""
        self.bridge.register_local_models(model_ids)

    def _on_auto_load_status(self, model_id, success, error):
        """Called when a local model auto-load completes."""
        if success:
            self._add_msg(t("chat.auto_load_success", model=model_id), "system")
            if error:  # the GPU could only be estimated: say so and how to check
                self._add_msg(error, "system")
        else:
            self._add_msg(t("chat.auto_load_failed", model=model_id, error=error), "error")

    def _on_model_change(self, model_id):
        """Called when user picks a model from the sidebar dropdown (also after
        a sidebar auto-load). Refused during a reply: the dropdown goes back
        to the model still in effect."""
        if self._refuse_while_running():
            self.sidebar.set_model(self.bridge.get_model())
            return
        account = self.sidebar.account_for(model_id)
        if isinstance(account, str):
            self._use_account(account, model_id)
            return
        # Detect if this is a local model (known from LM Studio discovery)
        try:
            if model_id in self.bridge._known_local_models:
                url = self.bridge._resolve_lm_studio_url()
                if url:
                    dropped = self.bridge.set_local_mode(url, model_id)
                else:
                    dropped = self.bridge.set_model(model_id)
            else:
                dropped = self.bridge.set_model(model_id)
        except ModelSaveFailed as exc:   # leaving an account failed: nothing switched
            self._add_msg(t("chat.model_save_failed", model=model_id, error=exc), "error")
            self.sidebar.set_model(self.bridge.get_model())
            return
        # Show friendly name in status bar
        display = model_id
        for mid, name, note in self.sidebar._all_models:
            if mid == model_id:
                display = name
                break
        is_local = self.bridge._active_provider == "local"
        self.status_bar.set_model(f"LM Studio: {display}" if is_local else display)
        self._add_msg(t("chat.model_switched", model=display), "system")
        self._note_dropped_resume(dropped)

    def _on_session_select(self, session_id):
        """Load a past session into the chat view."""
        if self._refuse_while_running():
            return
        try:
            with open_store() as store:
                messages = store.conversation(session_id)
            # Continue the stored session (same id) with its history; the
            # bridge refuses if the core cannot reopen it.
            if not messages or not self.bridge.resume_session(session_id, messages):
                self._add_msg(t("chat.session_load_failed"), "error")
                return

            # Clear current chat
            self._clear_chat()

            self._show_session_title(session_id, "resumed")

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

            self._add_msg(t("chat.session_resumed", "Session resumed. You can continue the conversation."), "system")
            self.input_text.focus_set()

        except Exception as e:
            self._add_msg(t("chat.session_load_error", error=e), "error")

    def _interrupt(self):
        if self.bridge.is_running:
            self.bridge.interrupt()
            self._stop_turn_clock()
            self._cleanup_stream_bubble()
            self._add_msg(t("chat.generation_stopped", "Generation stopped."), "system")
            self.status_bar.set_ready()

    # Settings, Permissions and the API-key wizard are modal (grab_set): while
    # one is open no message can be sent. They are not opened during a reply,
    # so a save never happens under a running turn (the worker reads these
    # files and env vars while it builds the agent).

    def _open_settings(self):
        if self._refuse_while_running():
            return
        d = SettingsDialog(self.root, self.bridge)
        self.root.wait_window(d)
        m = self.bridge.get_model()
        self.status_bar.set_model(self._model_label(m))
        self.sidebar.set_model(m)

    def _open_skills(self):
        SkillsBrowser(self.root, may_sync=not self.bridge.is_running)

    def _open_permissions(self):
        if self._refuse_while_running():
            return
        PermissionsPanel(self.root, on_save=self._on_permissions_saved,
                         can_save=lambda: not self.bridge.is_running)

    def _on_permissions_saved(self, perms):
        self._add_msg(t("chat.permissions_updated", new_chat=t("sidebar.new_chat")), "system")
        self._note_dropped_resume(self.bridge.rebuild_agent())

    def _open_extensions(self):
        ExtensionsManager(self.root)

    # -- signed-in accounts (View > Accounts) ----------------------------------
    def _open_accounts(self):
        AccountsWindow(self.root, on_use=self._use_account,
                       active_account=self._active_account)

    def _active_account(self):
        """The signed-in account the chat goes through now (not while on LM Studio)."""
        account = getattr(self.bridge, "_account_provider", None)
        local = getattr(self.bridge, "_active_provider", "cloud") == "local"
        return account if isinstance(account, str) and not local else None

    def _model_label(self, model):
        """The status bar's model text: the account in front when one is used."""
        account = self._active_account()
        return f"{accounts_core.short_name(account)}: {model}" if account else model

    def _use_account(self, provider, model):
        """Chat through a signed-in account. The core validates and writes the
        choice on a worker thread; sending waits meanwhile, as for a model load.
        Refused while a reply runs or a model loads."""
        if self._refuse_while_running():
            self.sidebar.set_model(self.bridge.get_model())
            return
        if self._model_work_running():
            self._add_notice(t("chat.model_loading_wait"))
            self.sidebar.set_model(self.bridge.get_model())
            return
        results = queue.SimpleQueue()

        def work():
            try:
                results.put(("ok", accounts_core.use(provider, model)))
            except Exception as exc:   # Rejected: the core's reason; else what failed
                results.put(("failed", str(exc) or type(exc).__name__))

        def check():
            try:
                kind, value = results.get_nowait()
            except queue.Empty:
                self.root.after(100, check)
                return
            self._account_switching = False
            name = accounts_core.short_name(provider)
            if kind != "ok":
                self._add_msg(t("chat.account_rejected", name=name, model=model, error=value), "error")
                self.sidebar.set_model(self.bridge.get_model())
                return
            dropped = self.bridge.set_account_mode(provider, value)
            self.status_bar.set_model(self._model_label(value))
            self.sidebar.set_model(value)
            self._load_account_models(provider)
            self._add_msg(t("chat.account_in_use", name=name, model=value), "system")
            self._note_dropped_resume(dropped)

        thread = threading.Thread(target=work, daemon=True)
        self._account_switching = True
        self._track_model_work(thread)
        thread.start()
        self.root.after(100, check)

    def _load_account_models(self, provider):
        """Fill the model box with the account's models (worker thread)."""
        results = queue.SimpleQueue()
        threading.Thread(target=lambda: results.put(accounts_core.models(provider)),
                         daemon=True).start()

        def check():
            try:
                ids = results.get_nowait()
            except queue.Empty:
                self.root.after(200, check)
                return
            if ids:
                self.sidebar.set_account_models(provider, accounts_core.short_name(provider), ids)
                self.sidebar.set_model(self.bridge.get_model())
        self.root.after(200, check)

    def _open_lm_studio(self):
        panel = LMStudioPanel(self.root, on_model_ready=self._on_lm_studio_ready,
                              can_change_model=lambda: not self.bridge.is_running,
                              track_model_work=self._track_model_work)
        self._lm_panels = [p for p in getattr(self, "_lm_panels", []) if not p._closed] + [panel]

    # -- model loading is "busy" too -------------------------------------------
    # A load or unload in LM Studio (sidebar auto-load, panel load/cancel) runs
    # in a worker thread; while any such thread is alive, sending is refused
    # (the load would unload the model the new turn uses). Tracking the
    # threads themselves means "busy" ends on every exit path, also when the
    # panel is closed mid-load.

    def _track_model_work(self, thread):
        self._model_work = [w for w in getattr(self, "_model_work", []) if w.is_alive()]
        self._model_work.append(thread)

    def _model_work_running(self) -> bool:
        """Busy until the work AND its Tk-side completion are done: a worker
        thread is alive, the sidebar's auto-load has not completed
        (_loading_model, cleared by _on_auto_load_complete), or an open panel
        still awaits its load/cancel completion (model_work_pending)."""
        self._model_work = [w for w in getattr(self, "_model_work", []) if w.is_alive()]
        sidebar = getattr(self, "sidebar", None)
        panels = [p for p in getattr(self, "_lm_panels", []) if not p._closed]
        self._lm_panels = panels
        return (bool(self._model_work)
                or getattr(self, "_account_switching", False) is True
                or getattr(sidebar, "_loading_model", False) is True
                or any(p.model_work_pending() for p in panels))

    def _on_lm_studio_ready(self, base_url, model_id):
        """Switch Hermes to use LM Studio as the LLM provider (refused during
        a reply; the model stays loaded in LM Studio for later)."""
        if self._refuse_while_running():
            return
        dropped = False
        if model_id:
            dropped = self.bridge.set_local_mode(base_url, model_id)
            short = model_id.split("/")[-1] if "/" in model_id else model_id
            self.status_bar.set_model(f"LM Studio: {short}")
            self.sidebar.set_model(model_id)

        # The agent was dropped, so the next message builds one for this model.
        self._add_msg(t("chat.local_model_ready",
                        model=model_id or t("chat.default_loaded_model")), "system")
        self._note_dropped_resume(dropped)

    def _show_api_setup(self):
        # Also reached from the first-run timer: never during a reply.
        if self._refuse_while_running():
            return

        def on_done(saved_keys):
            if saved_keys:
                names = ", ".join(saved_keys.keys())
                self._add_msg(t("chat.api_keys_saved", names=names), "system")
                # Force agent recreation to pick up new tools
                self._note_dropped_resume(self.bridge.rebuild_agent())
            m = self.bridge.get_model()
            self.status_bar.set_model(self._model_label(m))
            self.sidebar.set_model(m)

        w = APISetupWizard(self.root, on_complete=on_done, auto_mode=True,
                           can_save=lambda: not self.bridge.is_running)
        self.root.wait_window(w)

    def _first_run_api_setup(self):
        """First-run timer: skipped when another of our modal dialogs is open
        (its grab would be replaced and not restored); the menu entry stays."""
        if self.root.grab_current() is None:
            self._show_api_setup()

    def _toggle_sidebar(self):
        if self.sidebar.winfo_viewable():
            self.sidebar.pack_forget()
        else:
            # Re-pack at left
            children = self.sidebar.master.winfo_children()
            self.sidebar.pack(side="left", fill="y", before=children[1] if len(children) > 1 else None)

    def _about(self):
        messagebox.showinfo(t("about.title"),
                           f"{t('app.title')}\n\n"
                           f"{t('about.core_version', version=HERMES_CORE_VERSION)}\n\n"
                           f"{t('about.description')}\n"
                           f"{t('about.portable_credit')}\n"
                           f"{t('about.upstream_credit')}\n\n"
                           f"{t('about.license')}\n"
                           "github.com/aivrar/portable-hermes-agent",
                           parent=self.root)

    def _on_close(self):
        if self.bridge.is_running:
            if not messagebox.askyesno(t("app.title"),
                                       t("app.exit_confirm"),
                                       parent=self.root):
                return
        unregister_listener(self._on_language_changed)
        self._stop_turn_clock()
        self.bridge.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    HermesGUI().run()


if __name__ == "__main__":
    main()
