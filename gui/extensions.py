"""
Hermes Agent - Extensions Manager
Install and manage portable app extensions (Music Server, TTS Server, ComfyUI).
Each extension clones a repo, runs install.bat, and registers API tools with Hermes.
"""
import os
import sys
import json
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime

from gui.theme import C, FONTS, set_dark_title_bar, Tooltip, S, SF

PROJECT_ROOT = Path(__file__).parent.parent
EXTENSIONS_DIR = PROJECT_ROOT / "extensions"

# ============================================================================
# Extension Definitions
# ============================================================================

EXTENSIONS = [
    {
        "id": "music-server",
        "name": "Music Generation Server",
        "icon": "MUSIC",
        "description": "Generate music, songs, and sound effects from text prompts.\n"
                       "8 AI models, multi-GPU, production mastering pipeline.",
        "repo": "https://github.com/aivrar/portable-music-server.git",
        "port": 9150,
        "api_base": "http://127.0.0.1:9150",
        "start_cmd": "launcher.bat api",
        "health_endpoint": "/docs",
        "tools": [
            {
                "name": "generate_music",
                "description": "Generate music or sound effects from a text prompt using AI models.",
                "endpoint": "/api/music/{model}",
                "method": "POST",
            },
        ],
        "size_estimate": "~5 GB (models downloaded separately)",
        "requires_gpu": True,
    },
    {
        "id": "tts-server",
        "name": "Text-to-Speech Server",
        "icon": "TTS",
        "description": "Convert text to broadcast-quality speech with voice cloning.\n"
                       "10 TTS models, emotions, multilingual, post-processing.",
        "repo": "https://github.com/aivrar/portable-tts-server.git",
        "port": 8200,
        "api_base": "http://127.0.0.1:8200",
        "start_cmd": "launcher.bat api",
        "health_endpoint": "/docs",
        "tools": [
            {
                "name": "generate_speech",
                "description": "Generate speech audio from text using various TTS models with voice cloning support.",
                "endpoint": "/api/tts/{model}",
                "method": "POST",
            },
        ],
        "size_estimate": "~5 GB (models downloaded separately)",
        "requires_gpu": True,
    },
    {
        "id": "comfyui",
        "name": "ComfyUI Image Generator",
        "icon": "IMG",
        "description": "Full ComfyUI installation for AI image generation.\n"
                       "100+ models, workflows, multi-GPU, custom nodes.",
        "repo": "https://github.com/aivrar/comfyui-portable-installer.git",
        "port": 8188,
        "api_base": "http://127.0.0.1:8188",
        "start_cmd": "launcher.bat run",
        "health_endpoint": "/",
        "tools": [
            {
                "name": "comfyui_generate",
                "description": "Generate images using ComfyUI workflows with Stable Diffusion and other models.",
                "endpoint": "/prompt",
                "method": "POST",
            },
        ],
        "size_estimate": "~10 GB (with base model)",
        "requires_gpu": True,
    },
]


def get_extension_status():
    """Check which extensions are installed and running."""
    status = {}
    for ext in EXTENSIONS:
        ext_dir = EXTENSIONS_DIR / ext["id"]
        installed = ext_dir.exists() and (ext_dir / "launcher.bat").exists()
        running = False
        if installed:
            try:
                import httpx
                resp = httpx.get(ext["api_base"] + ext["health_endpoint"], timeout=2)
                running = resp.status_code < 500
            except Exception:
                running = False
        status[ext["id"]] = {
            "installed": installed,
            "running": running,
            "path": str(ext_dir),
        }
    return status


def install_extension(ext_id, progress_callback=None, done_callback=None):
    """Install an extension by cloning repo and running install.bat."""
    ext = next((e for e in EXTENSIONS if e["id"] == ext_id), None)
    if not ext:
        if done_callback:
            done_callback(False, "Unknown extension")
        return

    def _run():
        try:
            EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
            ext_dir = EXTENSIONS_DIR / ext["id"]

            # Clone
            if progress_callback:
                progress_callback(f"Cloning {ext['name']}...")

            if not ext_dir.exists():
                result = subprocess.run(
                    ["git", "clone", ext["repo"], str(ext_dir)],
                    capture_output=True, text=True, timeout=300
                )
                if result.returncode != 0:
                    if done_callback:
                        done_callback(False, f"Git clone failed: {result.stderr}")
                    return

            # Run install.bat
            if progress_callback:
                progress_callback(f"Installing {ext['name']}... (this may take a while)")

            install_bat = ext_dir / "install.bat"
            if install_bat.exists():
                result = subprocess.run(
                    ["cmd.exe", "/c", str(install_bat)],
                    cwd=str(ext_dir),
                    capture_output=True, text=True, timeout=1800,  # 30 min
                    env={**os.environ, "PATH": os.environ.get("PATH", "")}
                )

            if done_callback:
                done_callback(True, f"{ext['name']} installed successfully!")

        except subprocess.TimeoutExpired:
            if done_callback:
                done_callback(False, "Installation timed out (30 min limit)")
        except Exception as e:
            if done_callback:
                done_callback(False, str(e))

    threading.Thread(target=_run, daemon=True).start()


def start_extension(ext_id):
    """Start an extension's server."""
    ext = next((e for e in EXTENSIONS if e["id"] == ext_id), None)
    if not ext:
        return False
    ext_dir = EXTENSIONS_DIR / ext["id"]
    if not ext_dir.exists():
        return False

    subprocess.Popen(
        ["cmd.exe", "/c", ext["start_cmd"]],
        cwd=str(ext_dir),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    return True


def stop_extension(ext_id):
    """Stop an extension's server by killing processes on its port."""
    ext = next((e for e in EXTENSIONS if e["id"] == ext_id), None)
    if not ext:
        return
    try:
        subprocess.run(
            ["cmd.exe", "/c", f"for /f \"tokens=5\" %a in ('netstat -aon ^| findstr :{ext['port']}') do taskkill /f /pid %a"],
            capture_output=True, timeout=10
        )
    except Exception:
        pass


# ============================================================================
# Extensions Manager GUI
# ============================================================================

class ExtensionsManager(tk.Toplevel):
    """GUI for managing portable app extensions."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Extensions Manager")
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        set_dark_title_bar(self)
        from gui.theme import center_window
        center_window(self, 700, 550, parent)

        tk.Label(self, text="Extensions", font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(pady=(20, 4))
        tk.Label(self, text="Add powerful AI capabilities to Hermes",
                font=FONTS["small"], fg=C["text_hint"],
                bg=C["bg_main"]).pack()

        # Scrollable extension cards
        container = tk.Frame(self, bg=C["bg_main"])
        container.pack(fill="both", expand=True, padx=20, pady=16)

        canvas = tk.Canvas(container, bg=C["bg_main"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.cards_frame = tk.Frame(canvas, bg=C["bg_main"])

        self.cards_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.cards_frame, anchor="nw",
                            width=canvas.winfo_reqwidth())
        canvas.configure(yscrollcommand=scrollbar.set)
        # Resize inner frame when canvas resizes
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(canvas.find_withtag("all")[0], width=e.width))
        # Mousewheel scrolling
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Load extension status in background to avoid freeze
        self.status = {}
        self._build_cards()
        import threading
        threading.Thread(target=self._load_status, daemon=True).start()

    def _load_status(self):
        """Load extension status in background, then refresh cards."""
        self.status = get_extension_status()
        try:
            self.after(0, self._build_cards)
        except Exception:
            pass  # window may have been closed

    def _build_cards(self):
        for widget in self.cards_frame.winfo_children():
            widget.destroy()

        for ext in EXTENSIONS:
            self._build_card(ext)

    def _build_card(self, ext):
        s = self.status.get(ext["id"], {})
        installed = s.get("installed", False)
        running = s.get("running", False)

        card = tk.Frame(self.cards_frame, bg=C["bg_card"],
                       highlightbackground=C["border"], highlightthickness=1,
                       padx=16, pady=12)
        card.pack(fill="x", pady=6)

        # Header row
        hdr = tk.Frame(card, bg=C["bg_card"])
        hdr.pack(fill="x")

        # Status dot
        if running:
            dot_color, status_text = C["success"], "Running"
        elif installed:
            dot_color, status_text = C["warning_dark"], "Installed (stopped)"
        else:
            dot_color, status_text = C["text_disabled"], "Not installed"

        tk.Label(hdr, text="\u25CF", font=SF("Segoe UI", 12),
                fg=dot_color, bg=C["bg_card"]).pack(side="left", padx=(0, 8))

        # Title and icon
        tk.Label(hdr, text=f"[{ext['icon']}]", font=FONTS["mono_small"],
                fg=C["text_disabled"], bg=C["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(hdr, text=ext["name"], font=FONTS["subheading"],
                fg=C["text_primary"], bg=C["bg_card"]).pack(side="left")

        tk.Label(hdr, text=status_text, font=FONTS["small"],
                fg=dot_color, bg=C["bg_card"]).pack(side="right")

        # Description
        tk.Label(card, text=ext["description"], font=FONTS["small"],
                fg=C["text_secondary"], bg=C["bg_card"],
                justify="left", anchor="w", wraplength=S(600)).pack(fill="x", pady=(6, 0))

        # Info row
        info = tk.Frame(card, bg=C["bg_card"])
        info.pack(fill="x", pady=(6, 0))

        tk.Label(info, text=f"Port: {ext['port']}", font=FONTS["mono_small"],
                fg=C["text_disabled"], bg=C["bg_card"]).pack(side="left", padx=(0, 16))
        tk.Label(info, text=f"Size: {ext['size_estimate']}", font=FONTS["mono_small"],
                fg=C["text_disabled"], bg=C["bg_card"]).pack(side="left", padx=(0, 16))
        if ext.get("requires_gpu"):
            tk.Label(info, text="GPU recommended", font=FONTS["mono_small"],
                    fg=C["warning_dark"], bg=C["bg_card"]).pack(side="left")

        # Action buttons
        btn_frame = tk.Frame(card, bg=C["bg_card"])
        btn_frame.pack(fill="x", pady=(10, 0))

        if not installed:
            ttk.Button(btn_frame, text="Install", style="Primary.TButton",
                       command=lambda eid=ext["id"]: self._install(eid)).pack(side="left", padx=(0, 8))
        else:
            if running:
                ttk.Button(btn_frame, text="Stop", style="Danger.TButton",
                           command=lambda eid=ext["id"]: self._stop(eid)).pack(side="left", padx=(0, 8))
            else:
                ttk.Button(btn_frame, text="Start", style="Primary.TButton",
                           command=lambda eid=ext["id"]: self._start(eid)).pack(side="left", padx=(0, 8))

            ttk.Button(btn_frame, text="Open Folder", style="Small.TButton",
                       command=lambda p=s.get("path", ""): os.startfile(p) if p else None).pack(side="left", padx=(0, 8))

    def _install(self, ext_id):
        ext = next((e for e in EXTENSIONS if e["id"] == ext_id), None)
        if not ext:
            return

        # Confirmation
        if not messagebox.askyesno("Install Extension",
                                    f"Install {ext['name']}?\n\n"
                                    f"Size: {ext['size_estimate']}\n"
                                    f"This will download and set up everything automatically.\n"
                                    f"The install window will open — follow any prompts there.",
                                    parent=self):
            return

        self._show_progress(f"Installing {ext['name']}...")

        def on_progress(msg):
            self.after(0, lambda: self._show_progress(msg))

        def on_done(success, msg):
            self.after(0, lambda: self._install_done(success, msg))

        install_extension(ext_id, progress_callback=on_progress, done_callback=on_done)

    def _show_progress(self, msg):
        # Simple progress indicator
        if hasattr(self, '_progress_label'):
            self._progress_label.configure(text=msg)
        else:
            self._progress_label = tk.Label(self, text=msg, font=FONTS["body"],
                                           fg=C["info"], bg=C["bg_main"])
            self._progress_label.pack(pady=8)

    def _install_done(self, success, msg):
        if hasattr(self, '_progress_label'):
            self._progress_label.destroy()
            del self._progress_label

        if success:
            messagebox.showinfo("Success", msg, parent=self)
        else:
            messagebox.showerror("Error", msg, parent=self)

        # Refresh
        self.status = get_extension_status()
        self._build_cards()

    def _start(self, ext_id):
        if start_extension(ext_id):
            # Wait a moment then refresh
            self.after(3000, self._refresh)

    def _stop(self, ext_id):
        stop_extension(ext_id)
        self.after(1000, self._refresh)

    def _refresh(self):
        self.status = get_extension_status()
        self._build_cards()
