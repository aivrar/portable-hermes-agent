"""
Hermes Agent - Theme System
Matching ImageBuddy/ImageDownloader visual style.
Pure tkinter + ttk, no external UI libraries.
"""
import ctypes
import tkinter as tk
from tkinter import ttk


# ============================================================================
# DPI Scaling
# ============================================================================

_DPI_SCALE = 1.0  # Set by init_dpi_scaling() after root window creation


def _enable_dpi_awareness():
    """Set process DPI awareness — must be called BEFORE creating any windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# Call immediately at import time, before any Tk() window is created
_enable_dpi_awareness()


def init_dpi_scaling(root: tk.Tk):
    """Query the actual DPI and set the global scale factor.

    Call this AFTER creating the Tk root but BEFORE building any widgets.
    On a 150% display this sets _DPI_SCALE = 1.5, etc.
    """
    global _DPI_SCALE

    # Ask Windows what the real DPI is
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(
            ctypes.windll.user32.GetParent(root.winfo_id())
        )
        if dpi and dpi > 0:
            _DPI_SCALE = dpi / 96.0
        else:
            _DPI_SCALE = root.winfo_fpixels('1i') / 96.0
    except Exception:
        try:
            _DPI_SCALE = root.winfo_fpixels('1i') / 96.0
        except Exception:
            _DPI_SCALE = 1.0

    # Clamp to reasonable range
    _DPI_SCALE = max(1.0, min(_DPI_SCALE, 4.0))

    # Rebuild font sizes with the actual scale factor
    init_fonts()


def S(px: int) -> int:
    """Scale a pixel value by the DPI factor."""
    return int(px * _DPI_SCALE)


def F(pt: int) -> int:
    """Scale a font point size by the DPI factor."""
    return max(1, int(pt * _DPI_SCALE))


def SF(family: str, size: int, *args) -> tuple:
    """Build a DPI-scaled font tuple: SF("Segoe UI", 10, "bold") -> ("Segoe UI", 15, "bold") at 150%."""
    return (family, F(size)) + args


# ============================================================================
# Color Palettes
# ============================================================================

DARK = {
    # Backgrounds
    "bg_main": "#1e1e1e",
    "bg_card": "#2d2d2d",
    "bg_sidebar": "#252525",
    "bg_input": "#3c3c3c",
    "bg_hover": "#383838",
    "bg_selected": "#404040",

    # Text — bright enough to read against dark backgrounds
    "text_primary": "#f0f0f0",
    "text_secondary": "#c8c8c8",
    "text_hint": "#b0b0b0",
    "text_disabled": "#888888",

    # Accent
    "accent": "#5ab0ff",
    "accent_dark": "#3d94e0",
    "accent_light": "#1a3a52",

    # Status — brighter for readability on dark backgrounds
    "success": "#90EE90",
    "success_dark": "#7CDB7C",
    "warning": "#FFD699",
    "warning_dark": "#FFC266",
    "danger": "#FF9E9E",
    "danger_dark": "#FF7C7C",
    "info": "#64B5F6",

    # Borders
    "border": "#505050",
    "border_light": "#444444",
    "border_dark": "#666666",
    "separator": "#454545",

    # Scrollbar
    "scrollbar_bg": "#2a2a2a",
    "scrollbar_fg": "#606060",

    # Misc
    "treeview_alt": "#262626",
    "tooltip_bg": "#e0e0e0",
    "tooltip_fg": "#1e1e1e",

    # Message bubbles (Hermes-specific)
    "msg_user": "#1a3a52",
    "msg_user_border": "#3d94e0",
    "msg_ai": "#1e2e1e",
    "msg_ai_border": "#4a8a4a",
    "msg_tool": "#2e2a1a",
    "msg_tool_border": "#6a5a3a",
    "msg_system": "#2a2a2a",
    "msg_system_border": "#555555",
    "msg_error": "#3a1a1a",
    "msg_error_border": "#FF7C7C",
}

# Base font sizes (design units) — scaled by F() at init
_FONT_SIZES = {
    "heading": 13,
    "subheading": 11,
    "body": 10,
    "small": 9,
    "mono": 10,
    "mono_small": 9,
    "button": 10,
    "title": 16,
    "logo": 24,
    "logo_sub": 14,
}

# Fonts — rebuilt by init_fonts() after DPI is known
FONTS = {
    "heading": ("Segoe UI", 13, "bold"),
    "subheading": ("Segoe UI", 11, "bold"),
    "body": ("Segoe UI", 10),
    "small": ("Segoe UI", 9),
    "mono": ("Consolas", 10),
    "mono_small": ("Consolas", 9),
    "button": ("Segoe UI", 10, "bold"),
    "title": ("Segoe UI", 16, "bold"),
    "logo": ("Segoe UI", 24, "bold"),
    "logo_sub": ("Segoe UI", 14),
}


def init_fonts():
    """Rebuild FONTS dict with DPI-scaled point sizes."""
    FONTS["heading"] = ("Segoe UI", F(_FONT_SIZES["heading"]), "bold")
    FONTS["subheading"] = ("Segoe UI", F(_FONT_SIZES["subheading"]), "bold")
    FONTS["body"] = ("Segoe UI", F(_FONT_SIZES["body"]))
    FONTS["small"] = ("Segoe UI", F(_FONT_SIZES["small"]))
    FONTS["mono"] = ("Consolas", F(_FONT_SIZES["mono"]))
    FONTS["mono_small"] = ("Consolas", F(_FONT_SIZES["mono_small"]))
    FONTS["button"] = ("Segoe UI", F(_FONT_SIZES["button"]), "bold")
    FONTS["title"] = ("Segoe UI", F(_FONT_SIZES["title"]), "bold")
    FONTS["logo"] = ("Segoe UI", F(_FONT_SIZES["logo"]), "bold")
    FONTS["logo_sub"] = ("Segoe UI", F(_FONT_SIZES["logo_sub"]))


# Active color set
C = DARK


def get_color(key: str) -> str:
    return C.get(key, "#ff00ff")


# ============================================================================
# Dark Title Bar (Windows 10/11)
# ============================================================================

def set_dark_title_bar(window):
    """Enable dark title bar on Windows 10/11 via DwmSetWindowAttribute.

    To avoid the white title-bar flash, we:
    1. Start the window withdrawn (hidden)
    2. Apply the dark attribute
    3. Then show (deiconify) the window
    """
    try:
        # Hide window before it renders with a white title bar
        was_withdrawn = window.state() == 'withdrawn'
        if not was_withdrawn:
            window.withdraw()

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        # Attribute 20 = DWMWA_USE_IMMERSIVE_DARK_MODE
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )

        if not was_withdrawn:
            window.deiconify()
    except Exception:
        # Make sure we always show the window even if DWM fails
        try:
            window.deiconify()
        except Exception:
            pass


def center_window(window, width=None, height=None, parent=None):
    """Center a window on screen or over its parent window.

    *width* and *height* are in logical (design) pixels — they are
    automatically scaled by the DPI factor so windows look the same
    physical size on every display.

    If *parent* is given (and visible), the window is centered over the parent.
    Otherwise it is centered on the primary monitor.
    """
    window.update_idletasks()
    w = S(width) if width else window.winfo_width()
    h = S(height) if height else window.winfo_height()

    if parent is not None:
        # Center over parent
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        except Exception:
            x = (window.winfo_screenwidth() - w) // 2
            y = (window.winfo_screenheight() - h) // 2
    else:
        x = (window.winfo_screenwidth() - w) // 2
        y = (window.winfo_screenheight() - h) // 2

    # Clamp to screen bounds
    x = max(0, x)
    y = max(0, y)

    window.geometry(f"{w}x{h}+{x}+{y}")


# ============================================================================
# TTK Style Configuration
# ============================================================================

def apply_theme(root: tk.Tk):
    """Apply the full theme to the root window and all ttk styles."""
    style = ttk.Style()
    style.theme_use("classic")

    bg = C["bg_main"]
    card = C["bg_card"]
    sidebar = C["bg_sidebar"]
    inp = C["bg_input"]
    hover = C["bg_hover"]
    txt = C["text_primary"]
    txt2 = C["text_secondary"]
    hint = C["text_hint"]
    dis = C["text_disabled"]
    accent = C["accent"]
    accent_dk = C["accent_dark"]
    danger = C["danger"]
    danger_dk = C["danger_dark"]
    sep = C["separator"]
    sb_bg = C["scrollbar_bg"]
    sb_fg = C["scrollbar_fg"]
    bd_dk = C["border_dark"]

    # ---- Frames ----
    style.configure("TFrame", background=bg)
    style.configure("Main.TFrame", background=bg)
    style.configure("Sidebar.TFrame", background=sidebar)
    style.configure("Card.TFrame", background=card)

    # ---- Labels ----
    style.configure("TLabel", background=bg, foreground=txt, font=FONTS["body"])
    style.configure("Heading.TLabel", font=FONTS["heading"], foreground=txt, background=bg)
    style.configure("Subheading.TLabel", font=FONTS["subheading"], foreground=txt, background=bg)
    style.configure("Hint.TLabel", font=FONTS["small"], foreground=hint, background=bg)
    style.configure("Accent.TLabel", foreground=accent, background=bg, font=FONTS["body"])
    style.configure("Sidebar.TLabel", background=sidebar, foreground=txt, font=FONTS["body"])

    # ---- Buttons ----
    style.configure("TButton", font=FONTS["body"], padding=6,
                    background=sidebar, foreground=txt)
    style.map("TButton",
              background=[("active", hover), ("pressed", hover)],
              foreground=[("disabled", dis)])

    style.configure("Primary.TButton", foreground="white", background=accent,
                    font=FONTS["button"])
    style.map("Primary.TButton",
              background=[("active", accent_dk), ("pressed", accent_dk)],
              foreground=[("disabled", dis)])

    style.configure("Danger.TButton", foreground="white", background=danger,
                    font=FONTS["button"])
    style.map("Danger.TButton",
              background=[("active", danger_dk), ("pressed", danger_dk)],
              foreground=[("disabled", dis)])

    style.configure("Small.TButton", font=FONTS["small"], padding=[6, 3],
                    background=sidebar, foreground=txt)
    style.map("Small.TButton",
              background=[("active", hover), ("pressed", hover)],
              foreground=[("disabled", dis)])

    style.configure("Small.Primary.TButton", font=FONTS["small"], padding=[6, 3],
                    foreground="white", background=accent)
    style.map("Small.Primary.TButton",
              background=[("active", accent_dk), ("pressed", accent_dk)],
              foreground=[("disabled", dis)])

    # ---- Notebook (Tabs) ----
    style.configure("TNotebook", background=bg, borderwidth=0)
    style.configure("TNotebook.Tab", padding=[20, 10], font=FONTS["subheading"],
                    background=sidebar, foreground=txt2)
    style.map("TNotebook.Tab",
              background=[("selected", card), ("active", hover)],
              foreground=[("selected", accent), ("!selected", txt)])

    # ---- Entry ----
    style.configure("TEntry", fieldbackground=inp, foreground=txt, insertcolor=txt)

    # ---- Combobox ----
    style.configure("TCombobox", font=FONTS["body"], padding=4,
                    fieldbackground=inp, foreground=txt,
                    background=inp, arrowcolor=txt)
    style.map("TCombobox",
              fieldbackground=[("readonly", inp), ("disabled", sidebar)],
              foreground=[("readonly", txt), ("disabled", dis)],
              background=[("readonly", inp)])

    root.option_add("*TCombobox*Listbox.background", inp)
    root.option_add("*TCombobox*Listbox.foreground", txt)
    root.option_add("*TCombobox*Listbox.selectBackground", accent)
    root.option_add("*TCombobox*Listbox.selectForeground", "white")

    # ---- Text ----
    root.option_add("*Text.background", inp)
    root.option_add("*Text.foreground", txt)
    root.option_add("*Text.insertBackground", txt)
    root.option_add("*Text.selectBackground", accent)
    root.option_add("*Text.selectForeground", "white")

    # ---- Scrollbar ----
    root.option_add("*Scrollbar.background", sb_fg)
    root.option_add("*Scrollbar.troughColor", sb_bg)
    root.option_add("*Scrollbar.activeBackground", bd_dk)
    root.option_add("*Scrollbar.highlightBackground", bg)
    root.option_add("*Scrollbar.highlightColor", bg)

    style.configure("TScrollbar", background=sb_fg, troughcolor=sb_bg)

    # ---- Checkbutton ----
    style.configure("TCheckbutton", background=bg, foreground=txt)
    style.map("TCheckbutton", foreground=[("disabled", dis)],
              background=[("disabled", bg)])

    # ---- Progressbar ----
    style.configure("TProgressbar", background=accent, troughcolor=sb_bg)
    style.configure("Green.Horizontal.TProgressbar", background=C["success"], troughcolor=sb_bg)
    style.configure("Orange.Horizontal.TProgressbar", background=C["warning_dark"], troughcolor=sb_bg)
    style.configure("Red.Horizontal.TProgressbar", background=C["danger"], troughcolor=sb_bg)

    # ---- Separator ----
    style.configure("TSeparator", background=sep)

    # ---- Labelframe ----
    style.configure("TLabelframe", background=bg, foreground=txt)
    style.configure("TLabelframe.Label", background=bg, foreground=txt, font=FONTS["subheading"])

    # ---- Context menu colors ----
    root.option_add("*Menu.background", "#2a2a2a")
    root.option_add("*Menu.foreground", "#ffffff")
    root.option_add("*Menu.activeBackground", "#404040")
    root.option_add("*Menu.activeForeground", "#ffffff")

    # Set window background
    root.configure(bg=bg)

    # Dark title bar
    set_dark_title_bar(root)


# ============================================================================
# Tooltip Utility
# ============================================================================

class Tooltip:
    """Hover tooltip for any widget."""

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip_window = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)

    def _schedule(self, event):
        self._after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if self.tip_window:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text,
                        background=C["tooltip_bg"], foreground=C["tooltip_fg"],
                        font=FONTS["small"], padx=8, pady=4, relief="solid", borderwidth=1)
        label.pack()

    def _hide(self, event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None
