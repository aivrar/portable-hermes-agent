"""
Hermes Agent - Permissions Panel (GUI)
Visual configuration for read/write/install/execute/network permissions.
"""
import tkinter as tk
from tkinter import ttk

from gui.theme import C, FONTS, set_dark_title_bar, Tooltip, center_window, SF
from gui.permissions import (
    PERMISSION_DEFS, load_permissions, save_permissions,
    get_level_name, get_level_description,
)


class PermissionsPanel(tk.Toplevel):
    """Visual permissions configuration panel."""

    def __init__(self, parent, on_save=None):
        super().__init__(parent)
        self.on_save = on_save
        self.title("Permissions")
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        self.grab_set()
        set_dark_title_bar(self)
        center_window(self, 600, 650, parent)

        self.perms = load_permissions()
        self.sliders = {}

        # Title
        tk.Label(self, text="Permissions", font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(pady=(16, 2))
        tk.Label(self, text="Control what Hermes is allowed to do on your computer",
                font=FONTS["small"], fg=C["text_hint"],
                bg=C["bg_main"]).pack()

        # Scrollable permission cards
        canvas_frame = tk.Frame(self, bg=C["bg_main"])
        canvas_frame.pack(fill="both", expand=True, padx=20, pady=8)

        canvas = tk.Canvas(canvas_frame, bg=C["bg_main"],
                          highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical",
                                  command=canvas.yview)
        cards = tk.Frame(canvas, bg=C["bg_main"])

        cards.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=cards, anchor="nw",
                            tags="cards_win")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Stretch cards to canvas width
        def _on_canvas_configure(event):
            canvas.itemconfig("cards_win", width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        for key, defn in PERMISSION_DEFS.items():
            self._build_card(cards, key, defn)

        # Buttons
        btn_frame = tk.Frame(self, bg=C["bg_main"])
        btn_frame.pack(fill="x", padx=20, pady=(0, 16))

        ttk.Button(btn_frame, text="Save", style="Primary.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(btn_frame, text="Reset to Defaults", style="TButton",
                   command=self._reset).pack(side="right", padx=(0, 8))

    def _build_card(self, parent, key, defn):
        card = tk.Frame(parent, bg=C["bg_card"],
                       highlightbackground=C["border"], highlightthickness=1,
                       padx=12, pady=8)
        card.pack(fill="x", pady=4)

        # Header
        hdr = tk.Frame(card, bg=C["bg_card"])
        hdr.pack(fill="x")

        tk.Label(hdr, text=defn["name"], font=FONTS["subheading"],
                fg=C["text_primary"], bg=C["bg_card"]).pack(side="left")

        current = self.perms.get(key, defn["default"])
        level_name = get_level_name(key, current)

        self.level_labels = getattr(self, 'level_labels', {})
        lbl = tk.Label(hdr, text=f"{level_name} ({current})",
                      font=FONTS["mono_small"], fg=C["accent"],
                      bg=C["bg_card"])
        lbl.pack(side="right")
        self.level_labels[key] = lbl

        # Description
        desc_lbl = tk.Label(card, text=get_level_description(key, current),
                           font=FONTS["small"], fg=C["text_hint"],
                           bg=C["bg_card"], anchor="w")
        desc_lbl.pack(fill="x")
        self.__dict__[f"_desc_{key}"] = desc_lbl

        # Slider
        slider_frame = tk.Frame(card, bg=C["bg_card"])
        slider_frame.pack(fill="x", pady=(4, 0))

        # Level labels under slider
        max_level = max(defn["levels"].keys())
        var = tk.IntVar(value=current)

        slider = ttk.Scale(slider_frame, from_=0, to=max_level,
                          variable=var, orient="horizontal",
                          command=lambda val, k=key, v=var: self._on_slide(k, v))
        slider.pack(fill="x")

        # Tick labels
        tick_frame = tk.Frame(card, bg=C["bg_card"])
        tick_frame.pack(fill="x")
        for lvl in range(max_level + 1):
            name = defn["levels"].get(lvl, ("?",))[0]
            anchor = "w" if lvl == 0 else ("e" if lvl == max_level else "center")
            tk.Label(tick_frame, text=name, font=SF("Segoe UI", 7),
                    fg=C["text_disabled"], bg=C["bg_card"],
                    anchor=anchor).pack(side="left", expand=True, fill="x")

        self.sliders[key] = var

    def _on_slide(self, key, var):
        level = int(float(var.get()))
        var.set(level)  # Snap to integer
        self.perms[key] = level

        # Update display
        level_name = get_level_name(key, level)
        if key in self.level_labels:
            self.level_labels[key].configure(text=f"{level_name} ({level})")

        desc_widget = self.__dict__.get(f"_desc_{key}")
        if desc_widget:
            desc_widget.configure(text=get_level_description(key, level))

        # Color-code: green for restrictive, yellow for moderate, red for permissive
        if level <= 1:
            color = C["success"]
        elif level <= 2:
            color = C["accent"]
        elif level <= 3:
            color = C["warning_dark"]
        else:
            color = C["danger"]
        if key in self.level_labels:
            self.level_labels[key].configure(fg=color)

    def _save(self):
        # Snap all values to int
        for key, var in self.sliders.items():
            self.perms[key] = int(float(var.get()))
        save_permissions(self.perms)
        if self.on_save:
            self.on_save(self.perms)
        self.destroy()

    def _reset(self):
        for key, defn in PERMISSION_DEFS.items():
            default = defn["default"]
            self.sliders[key].set(default)
            self.perms[key] = default
            self._on_slide(key, self.sliders[key])
