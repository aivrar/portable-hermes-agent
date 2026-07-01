"""
Hermes Agent - LM Studio Integration
SDK for model loading (GPU/context control), OpenAI endpoint for chat.
Pattern from AgentNate.
"""
import os
import sys
import json
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import List, Dict, Optional

from gui.theme import C, FONTS, set_dark_title_bar, Tooltip, SF

try:
    import lmstudio
    from lmstudio import LlmLoadModelConfig
    from lmstudio._sdk_models import GpuSetting
    HAS_SDK = True
except ImportError:
    lmstudio = None
    HAS_SDK = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

PROJECT_ROOT = Path(__file__).parent.parent

# ============================================================================
# GPU Detection
# ============================================================================

def get_available_gpus() -> List[str]:
    """Detect GPUs via nvidia-smi."""
    gpus = ["CPU"]
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=10
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split(", ")
            if len(parts) >= 3:
                idx, name, mem = parts[0].strip(), parts[1].strip(), parts[2].strip()
                gpus.append(f"GPU {idx}: {name} ({mem} MiB)")
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    return gpus


# ============================================================================
# LM Studio Client
# ============================================================================

class LMStudioClient:
    """Manages LM Studio SDK connection, model loading, and OpenAI endpoint."""

    def __init__(self, base_url: str = "http://localhost:1234"):
        self.base_url = base_url
        self._sdk_client = None
        self._sdk_api_host = None

    def is_running(self) -> bool:
        """Check if LM Studio is reachable."""
        if not HAS_HTTPX:
            return False
        try:
            # Try /v1/models first (OpenAI-compatible), then /models
            for path in ("/v1/models", "/models"):
                try:
                    r = httpx.get(f"{self.base_url}{path}", timeout=3)
                    if r.status_code == 200:
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def connect_sdk(self) -> bool:
        """Initialize SDK client."""
        if not HAS_SDK:
            return False
        try:
            self._sdk_api_host = lmstudio.Client.find_default_local_api_host()
            if self._sdk_api_host:
                self._sdk_client = lmstudio.Client(api_host=self._sdk_api_host)
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _extract_model_id(m) -> str:
        """Extract the usable model identifier from an SDK model object.

        LM Studio SDK's load_new_instance() needs the model path in
        'publisher/repo' format (e.g. 'mradermacher/Huihui-Qwen3.5-2B-abliterated-i1-GGUF').
        We try 'path' first since that's the full model path the SDK uses.
        """
        # 'path' is the full model path the SDK uses for loading
        for attr in ("path", "model_key", "id", "name"):
            val = getattr(m, attr, None)
            if val and isinstance(val, str):
                return val
        # Last resort — parse from repr string
        s = str(m)
        for key in ("path=", "model_key="):
            if key in s:
                import re
                match = re.search(key.replace("=", r"='([^']+)'"), s)
                if match:
                    return match.group(1)
        return s

    @staticmethod
    def _extract_display_name(m) -> str:
        """Extract a human-readable name from an SDK model object."""
        for attr in ("display_name", "name"):
            val = getattr(m, attr, None)
            if val and isinstance(val, str):
                return val
        # Fall back to the last part of the model path
        mid = LMStudioClient._extract_model_id(m)
        return mid.split("/")[-1] if "/" in mid else mid

    def list_downloaded_models(self) -> List[Dict]:
        """List all downloaded models via SDK."""
        if not self._sdk_client:
            return []
        try:
            models = list(self._sdk_client.llm.list_downloaded())
            # Log first model's attributes to help debug ID extraction
            if models:
                import logging
                _log = logging.getLogger("hermes.lmstudio")
                m0 = models[0]
                attrs = {a: getattr(m0, a, None) for a in dir(m0)
                         if not a.startswith("_") and not callable(getattr(m0, a, None))}
                _log.info("SDK DownloadedModel attrs: %s", attrs)
                _log.info("SDK DownloadedModel str: %s", str(m0))
            return [{"path": self._extract_model_id(m),
                     "display_name": self._extract_display_name(m)} for m in models]
        except Exception:
            return []

    def list_loaded_models(self) -> List[Dict]:
        """List currently loaded models via SDK."""
        if not self._sdk_client:
            return []
        try:
            models = list(self._sdk_client.llm.list_loaded())
            return [{"id": self._extract_model_id(m),
                     "display_name": self._extract_display_name(m)} for m in models]
        except Exception:
            return []

    def list_models_api(self) -> List[Dict]:
        """List models via OpenAI-compatible API."""
        if not HAS_HTTPX:
            return []
        try:
            # Try native API first (has context_length)
            base = self.base_url.rstrip("/").replace("/v1", "")
            native_url = base + "/api/v0/models"
            r = httpx.get(native_url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                models_list = data if isinstance(data, list) else data.get("data", [])
                # Log first model's fields to debug ID vs path
                if models_list:
                    import logging
                    logging.getLogger("hermes.lmstudio").info(
                        "Native API model keys: %s", list(models_list[0].keys())
                    )
                    logging.getLogger("hermes.lmstudio").info(
                        "Native API first model: %s", {k: v for k, v in models_list[0].items()
                                                        if k in ("id", "path", "model_key", "display_name", "state")}
                    )
                return [
                    {
                        "id": m.get("id", m.get("path", "unknown")),
                        "path": m.get("path", m.get("id", "unknown")),
                        "display_name": m.get("id", m.get("path", "unknown")),
                        "context_length": m.get("max_context_length"),
                        "quantization": m.get("quantization"),
                        "state": m.get("state", "unknown"),
                    }
                    for m in models_list
                ]
        except Exception:
            pass

        # Fallback to OpenAI-compatible API
        for path in ("/v1/models", "/models"):
            try:
                r = httpx.get(f"{self.base_url}{path}", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    return [
                        {"id": m.get("id", "unknown"), "context_length": None, "state": "unknown"}
                        for m in data.get("data", [])
                    ]
            except Exception:
                continue
        return []

    def load_model(self, model_key: str, gpu_index: Optional[int] = None,
                   context_length: int = 4096, flash_attention: bool = True) -> bool:
        """Load a model via SDK with GPU and context control.

        Finds the model object from downloaded models by matching model_key,
        then calls load_new_instance() on it directly.
        """
        if not self._sdk_client:
            return False
        try:
            # Unload all existing instances to ensure clean GPU placement.
            try:
                loaded = list(self._sdk_client.llm.list_loaded())
                for m in loaded:
                    try:
                        m.unload()
                    except Exception:
                        pass
            except Exception:
                pass

            gpu_config = None
            if gpu_index is not None:
                gpus = get_available_gpus()
                num_gpus = len([g for g in gpus if g.startswith("GPU")])
                # nvidia-smi and CUDA have reversed GPU ordering:
                #   nvidia-smi GPU 0 (3060) = CUDA device 1
                #   nvidia-smi GPU 1 (3090) = CUDA device 0
                # LM Studio uses CUDA ordering, so remap.
                lms_index = (num_gpus - 1) - gpu_index
                disabled = [i for i in range(num_gpus) if i != lms_index]
                gpu_config = GpuSetting(
                    main_gpu=lms_index,
                    disabled_gpus=disabled if disabled else None,
                    ratio=1.0,
                )

            config = LlmLoadModelConfig(
                gpu=gpu_config,
                context_length=context_length,
                flash_attention=flash_attention,
            )

            import logging
            _log = logging.getLogger("hermes.lmstudio")

            # Find the actual SDK model object by matching model_key or path
            downloaded = list(self._sdk_client.llm.list_downloaded())
            _log.info("Looking for model_key=%r among %d downloaded models", model_key, len(downloaded))
            target = None
            for m in downloaded:
                mk = getattr(m, 'model_key', '')
                mp = getattr(m, 'path', '')
                dn = getattr(m, 'display_name', '')
                if model_key in (mk, mp, dn):
                    target = m
                    _log.info("Found match: model_key=%r path=%r", mk, mp)
                    break

            if target is not None:
                # Use the SDK model object's own load method
                _log.info("Loading via SDK model object, ctx=%d gpu=%r", context_length, gpu_index)
                target.load_new_instance(
                    config=config, ttl=86400,
                    instance_identifier=f"hermes-{int(time.time())}",
                )
            else:
                # Fallback: try string-based load
                _log.warning("No SDK model object found, trying string key: %r", model_key)
                self._sdk_client.llm.load_new_instance(
                    model_key, f"hermes-{int(time.time())}",
                    config=config, ttl=86400,
                )
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to load model: {e}")

    def unload_model(self, model_id: str) -> bool:
        """Unload a model via SDK."""
        if not self._sdk_client:
            return False
        try:
            loaded = list(self._sdk_client.llm.list_loaded())
            for m in loaded:
                if model_id in str(m):
                    m.unload()
                    return True
        except Exception:
            pass
        return False


def estimate_context_length(model_id: str) -> int:
    """Estimate context length from model name."""
    m = model_id.lower()
    if "128k" in m: return 131072
    if "64k" in m: return 65536
    if "32k" in m: return 32768
    if "16k" in m: return 16384
    if "8k" in m: return 8192
    if "llama-3" in m or "llama3" in m: return 8192
    if "llama-2" in m: return 4096
    if "mistral" in m or "mixtral" in m: return 32768
    if "qwen" in m: return 32768
    if "phi" in m: return 16384
    if "gemma" in m: return 8192
    if "deepseek" in m: return 32768
    if "command-r" in m: return 128000
    return 4096


# ============================================================================
# LM Studio Panel (GUI)
# ============================================================================

class LMStudioPanel(tk.Toplevel):
    """Full LM Studio management panel — model browser, GPU selector, context slider."""

    def __init__(self, parent, on_model_ready=None):
        super().__init__(parent)
        self.on_model_ready = on_model_ready
        self.title("LM Studio - Local Models")
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        set_dark_title_bar(self)
        from gui.theme import center_window
        center_window(self, 650, 580, parent)

        # Read configured endpoint from environment or .env file
        base_url = self._resolve_base_url()
        self.client = LMStudioClient(base_url=base_url)
        self.gpus = get_available_gpus()
        self.models = []

        self._build_ui()
        self.after(100, self._connect)

    @staticmethod
    def _resolve_base_url() -> str:
        """Return the LM Studio endpoint. Default is localhost:1234."""
        return "http://localhost:1234"

    def _build_ui(self):
        # Title
        hdr = tk.Frame(self, bg=C["bg_main"], padx=20, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="LM Studio", font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(side="left")

        self.status_dot = tk.Label(hdr, text="\u25CF", font=SF("Segoe UI", 12),
                                  fg=C["text_disabled"], bg=C["bg_main"])
        self.status_dot.pack(side="left", padx=(8, 4))
        self.status_lbl = tk.Label(hdr, text="Connecting...", font=FONTS["small"],
                                  fg=C["text_hint"], bg=C["bg_main"])
        self.status_lbl.pack(side="left")

        if not HAS_SDK:
            tk.Label(hdr, text="(SDK not installed)", font=FONTS["small"],
                    fg=C["danger"], bg=C["bg_main"]).pack(side="right")

        # Endpoint config
        ep_row = tk.Frame(self, bg=C["bg_main"], padx=20)
        ep_row.pack(fill="x", pady=(0, 8))
        tk.Label(ep_row, text="Endpoint:", font=FONTS["body"],
                fg=C["text_secondary"], bg=C["bg_main"]).pack(side="left")
        self._ep_var = tk.StringVar(value=self.client.base_url)
        ep_entry = tk.Entry(ep_row, textvariable=self._ep_var,
                           font=FONTS["mono_small"], bg=C["bg_input"],
                           fg=C["text_primary"], insertbackground=C["text_primary"],
                           relief="flat")
        ep_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), ipady=2)
        ttk.Button(ep_row, text="Connect", style="Small.TButton",
                   command=self._apply_endpoint).pack(side="left")

        # Model list
        model_frame = tk.LabelFrame(self, text="  Available Models  ",
                                    bg=C["bg_main"], fg=C["text_secondary"],
                                    font=FONTS["subheading"], padx=12, pady=8)
        model_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        self.model_list = tk.Listbox(model_frame, bg=C["bg_input"], fg=C["text_primary"],
                                     font=FONTS["mono_small"], relief="flat",
                                     selectbackground=C["accent"],
                                     selectforeground="white",
                                     highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(model_frame, command=self.model_list.yview)
        self.model_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.model_list.pack(fill="both", expand=True)
        self.model_list.bind("<<ListboxSelect>>", self._on_model_select)

        # Controls frame
        ctrl = tk.Frame(self, bg=C["bg_main"], padx=20)
        ctrl.pack(fill="x")

        # GPU selector
        gpu_row = tk.Frame(ctrl, bg=C["bg_main"])
        gpu_row.pack(fill="x", pady=4)
        tk.Label(gpu_row, text="GPU:", font=FONTS["body"],
                fg=C["text_secondary"], bg=C["bg_main"], width=12,
                anchor="w").pack(side="left")
        self.gpu_var = tk.StringVar()
        self.gpu_combo = ttk.Combobox(gpu_row, textvariable=self.gpu_var,
                                      values=self.gpus, font=FONTS["body"],
                                      state="readonly")
        # Style the dropdown list to match the parent font
        self.option_add("*TCombobox*Listbox.font", FONTS["body"])
        if len(self.gpus) > 1:
            self.gpu_combo.current(1)  # Default to first GPU
        else:
            self.gpu_combo.current(0)
        self.gpu_combo.pack(side="left", fill="x", expand=True)

        # Context length slider
        from gui.theme import S as _S
        ctx_row = tk.Frame(ctrl, bg=C["bg_main"])
        ctx_row.pack(fill="x", pady=4)
        tk.Label(ctx_row, text="Context:", font=FONTS["body"],
                fg=C["text_secondary"], bg=C["bg_main"], width=12,
                anchor="w").pack(side="left")

        self.ctx_var = tk.IntVar(value=32768)
        # Use a tk.Scale for better visual control (ttk.Scale is too thin)
        # Minimum 32768 — Hermes sends ~17K tokens of tool definitions alone
        self.ctx_slider = tk.Scale(ctx_row, from_=32768, to=131072,
                                   variable=self.ctx_var, orient="horizontal",
                                   command=self._on_ctx_change,
                                   bg=C["bg_main"], fg=C["text_primary"],
                                   troughcolor=C["bg_input"],
                                   activebackground=C["accent"],
                                   highlightthickness=0, borderwidth=0,
                                   sliderrelief="flat", sliderlength=_S(20),
                                   width=_S(14), showvalue=False,
                                   font=FONTS["small"])
        self.ctx_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.ctx_label = tk.Label(ctx_row, text="4,096", font=FONTS["mono_small"],
                                 fg=C["accent"], bg=C["bg_main"], width=10)
        self.ctx_label.pack(side="right")

        # Buttons
        btn_row = tk.Frame(self, bg=C["bg_main"], padx=20, pady=12)
        btn_row.pack(fill="x")

        self.load_btn = ttk.Button(btn_row, text="Load Model", style="Primary.TButton",
                                   command=self._load_model)
        self.load_btn.pack(side="left", padx=(0, 8))

        self.unload_btn = ttk.Button(btn_row, text="Unload", style="Danger.TButton",
                                     command=self._unload_model)
        self.unload_btn.pack(side="left", padx=(0, 8))

        ttk.Button(btn_row, text="Refresh", style="TButton",
                   command=self._refresh_models).pack(side="left", padx=(0, 8))

        self.use_btn = ttk.Button(btn_row, text="Use for Chat", style="Primary.TButton",
                                  command=self._use_model)
        self.use_btn.pack(side="right")

    def _connect(self):
        """Connect to LM Studio in background."""
        def _do():
            running = self.client.is_running()
            sdk_ok = False
            if running and HAS_SDK:
                sdk_ok = self.client.connect_sdk()
            self.after(0, lambda: self._on_connected(running, sdk_ok))

        threading.Thread(target=_do, daemon=True).start()

    def _on_connected(self, running, sdk_ok):
        if running:
            self.status_dot.configure(fg=C["success"])
            status = "Connected"
            if sdk_ok:
                status += " (SDK active)"
            self.status_lbl.configure(text=status)
            self._refresh_models()
        else:
            self.status_dot.configure(fg=C["danger"])
            self.status_lbl.configure(text="Not running — start LM Studio first")

    def _apply_endpoint(self):
        """Apply a new LM Studio endpoint URL and reconnect."""
        url = self._ep_var.get().strip().rstrip("/")
        if not url:
            return
        self.client = LMStudioClient(base_url=url)
        # Update status and reconnect
        self.status_dot.configure(fg=C["text_disabled"])
        self.status_lbl.configure(text="Connecting...")
        self._connect()

    def _refresh_models(self):
        """Refresh model list."""
        def _do():
            models = self.client.list_models_api()
            if HAS_SDK and self.client._sdk_client:
                try:
                    downloaded = self.client.list_downloaded_models()
                    # Merge downloaded models not in API list
                    api_ids = {m["id"] for m in models}
                    for d in downloaded:
                        if d["path"] not in api_ids:
                            models.append({
                                "id": d["path"],
                                "display_name": d.get("display_name", d["path"]),
                                "context_length": None,
                                "state": "not-loaded",
                            })
                except Exception:
                    pass
            self.after(0, lambda: self._display_models(models))

        threading.Thread(target=_do, daemon=True).start()

    def _display_models(self, models):
        self.models = models
        self.model_list.delete(0, "end")
        for m in models:
            mid = m["id"]
            display = m.get("display_name") or mid
            state = m.get("state", "")
            ctx = m.get("context_length")
            label = display
            if state == "loaded":
                label = f"[LOADED] {display}"
            if ctx:
                label += f"  ({ctx:,} ctx)"
            self.model_list.insert("end", label)

    def _on_model_select(self, event):
        sel = self.model_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self.models):
            m = self.models[idx]
            max_ctx = m.get("context_length") or estimate_context_length(m["id"])
            # Update slider range but keep the user's chosen value
            self.ctx_slider.configure(to=max(max_ctx, 131072))
            # Only set a default if user hasn't touched the slider yet
            current = self.ctx_var.get()
            if current > max_ctx:
                safe = min(max_ctx, 8192)
                self.ctx_var.set(safe)
                self.ctx_label.configure(text=f"{safe:,}")

    def _on_ctx_change(self, val):
        v = int(float(val))
        # Snap to nearest 512
        v = max(512, (v // 512) * 512)
        self.ctx_var.set(v)
        self.ctx_label.configure(text=f"{v:,}")

    def _load_model(self):
        sel = self.model_list.curselection()
        if not sel:
            messagebox.showwarning("No Model", "Select a model first.", parent=self)
            return

        idx = sel[0]
        model = self.models[idx]
        # Use 'path' for SDK loading (full model path), 'id' for display/chat
        model_path = model.get("path", model["id"])
        model_id = model["id"]
        ctx = int(self.ctx_var.get())
        ctx = max(512, (ctx // 512) * 512)

        # Parse GPU selection
        gpu_str = self.gpu_var.get()
        gpu_index = None
        if gpu_str.startswith("GPU"):
            try:
                gpu_index = int(gpu_str.split(":")[0].replace("GPU ", ""))
            except ValueError:
                pass

        short = model_id.split("/")[-1] if "/" in model_id else model_id
        self.status_lbl.configure(text=f"Loading {short}...")
        self.status_dot.configure(fg=C["warning_dark"])

        # Show cancel button, hide load button
        self.load_btn.pack_forget()
        self._cancel_btn = ttk.Button(self.load_btn.master, text="Cancel Load",
                                       style="Danger.TButton",
                                       command=self._cancel_load)
        self._cancel_btn.pack(side="left", padx=(0, 8))
        self._loading = True

        def _do():
            try:
                # Log to file for debugging
                import logging
                _log = logging.getLogger("hermes.lmstudio")
                _log.warning("PANEL LOAD: model_path=%r model_id=%r ctx=%d gpu=%r",
                             model_path, model_id, ctx, gpu_index)
                self.client.load_model(model_path, gpu_index=gpu_index,
                                       context_length=ctx)
                if self._loading:
                    self.after(0, lambda: self._on_load_success(model_id))
            except Exception as e:
                import logging
                logging.getLogger("hermes.lmstudio").error("PANEL LOAD FAILED: %s", e)
                if self._loading:
                    err = f"Model: {model_path}\nContext: {ctx}\nGPU: {gpu_index}\n\n{e}"
                    self.after(0, lambda: self._on_load_error(err))

        threading.Thread(target=_do, daemon=True).start()

    def _cancel_load(self):
        """Cancel an in-progress model load by unloading all models."""
        self._loading = False
        self.status_lbl.configure(text="Cancelling...")
        def _do():
            try:
                # Unload whatever was loaded
                loaded = list(self.client._sdk_client.llm.list_loaded())
                for m in loaded:
                    try:
                        m.unload()
                    except Exception:
                        pass
            except Exception:
                pass
            self.after(0, self._on_cancel_done)
        threading.Thread(target=_do, daemon=True).start()

    def _on_cancel_done(self):
        self._restore_load_btn()
        self.status_dot.configure(fg=C["text_disabled"])
        self.status_lbl.configure(text="Load cancelled")
        self._refresh_models()

    def _restore_load_btn(self):
        """Swap cancel button back to load button."""
        if hasattr(self, '_cancel_btn'):
            self._cancel_btn.destroy()
            del self._cancel_btn
        self.load_btn.pack(side="left", padx=(0, 8))

    def _on_load_success(self, model_id):
        self._restore_load_btn()
        short = model_id.split("/")[-1] if "/" in model_id else model_id
        self.status_dot.configure(fg=C["success"])
        self.status_lbl.configure(text=f"Loaded: {short}")
        self._refresh_models()

    def _on_load_error(self, error):
        self._restore_load_btn()
        self.status_dot.configure(fg=C["danger"])
        self.status_lbl.configure(text="Load failed")
        # Unload to stop JIT retry loops
        try:
            if self.client._sdk_client:
                for m in list(self.client._sdk_client.llm.list_loaded()):
                    try:
                        m.unload()
                    except Exception:
                        pass
        except Exception:
            pass
        messagebox.showerror("Load Error", error, parent=self)

    def _unload_model(self):
        sel = self.model_list.curselection()
        if not sel:
            return
        model = self.models[sel[0]]
        self.client.unload_model(model["id"])
        self.after(500, self._refresh_models)

    def _use_model(self):
        """Set LM Studio as the active provider for Hermes chat."""
        if self.on_model_ready:
            sel = self.model_list.curselection()
            model_id = self.models[sel[0]]["id"] if sel and sel[0] < len(self.models) else None
            self.on_model_ready(self.client.base_url, model_id)
        self.destroy()
