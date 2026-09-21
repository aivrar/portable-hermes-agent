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
import tempfile
from urllib.parse import urlsplit
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import List, Dict, Optional

from gui.theme import C, FONTS, set_dark_title_bar, Tooltip, SF
from gui.i18n import t
from hermes_constants import get_hermes_home
from agent.model_metadata import MINIMUM_CONTEXT_LENGTH

DEFAULT_CONTEXT_LENGTH = max(65536, MINIMUM_CONTEXT_LENGTH)

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
# Resolve per profile at use time; never store credentials in the source tree.
LMSTUDIO_CONFIG_PATH = None


def _lmstudio_config_path():
    return LMSTUDIO_CONFIG_PATH or get_hermes_home() / ".lmstudio_config"


def _read_lmstudio_config() -> Dict[str, str]:
    """Read LM Studio config from disk, supporting legacy plain-text endpoint files."""
    path = _lmstudio_config_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception:
        return {}
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {
                    "base_url": str(data.get("base_url", "")).strip(),
                    "api_key": str(data.get("api_key", "")).strip(),
                }
        except Exception:
            return {}
    return {"base_url": raw}


def _write_lmstudio_config(*, base_url: Optional[str] = None, api_key: Optional[str] = None) -> bool:
    """Persist LM Studio endpoint and API key to disk."""
    data = _read_lmstudio_config()
    if base_url is not None:
        data["base_url"] = base_url.strip().rstrip("/")
    if api_key is not None:
        data["api_key"] = api_key.strip()
    temporary = None
    try:
        path = _lmstudio_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".lmstudio-", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(data, stream, ensure_ascii=True, indent=2)
        os.replace(temporary, path)
        return True
    except Exception:
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

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

    def __init__(self, base_url: str = "http://localhost:1234/v1", api_key: Optional[str] = None):
        self.base_url = base_url.strip().rstrip("/")
        cfg = _read_lmstudio_config()
        saved_url = cfg.get("base_url", "http://localhost:1234/v1").rstrip("/").removesuffix("/v1")
        saved_key = cfg.get("api_key") if saved_url == self._server_root() else None
        self.api_key = (api_key if api_key is not None else
                        saved_key if saved_key is not None else
                        os.environ.get("LM_API_TOKEN", os.environ.get("LM_API_KEY", "")))
        self._sdk_client = None
        self._sdk_api_host = None

    def _server_root(self) -> str:
        """Return the LM Studio server root without the OpenAI `/v1` suffix."""
        if self.base_url.endswith("/v1"):
            return self.base_url[:-3]
        return self.base_url

    def _openai_base(self) -> str:
        """Return the OpenAI-compatible base URL ending with `/v1`."""
        if self.base_url.endswith("/v1"):
            return self.base_url
        return self.base_url + "/v1"

    def _auth_headers(self) -> Dict[str, str]:
        """Build authorization headers for LM Studio."""
        if not self.api_key:
            return {}
        
        # LM Studio expects Bearer token format
        # Use the full key as-is (they support sk-lm-*:password format)
        # Add minimal headers to match PowerShell behavior
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "LMStudioClient/1.0"
        }

    def is_running(self) -> bool:
        """Check if LM Studio is reachable."""
        if not HAS_HTTPX:
            return False
        try:
            # 200 means ready, 401/403 means reachable but protected.
            for url in (
                self._openai_base() + "/models",
                self._server_root() + "/api/v1/models",
                self._server_root(),
            ):
                try:
                    r = httpx.get(url, headers=self._auth_headers(), timeout=3)
                    if r.status_code in (200, 401, 403):
                        return True
                    if url == self._server_root() and r.status_code == 404:
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
            # Use the selected host, not a different auto-discovered local server.
            self._sdk_api_host = urlsplit(self._server_root()).netloc
            if self._sdk_api_host:
                # Apply API key if available
                kwargs = {"api_host": self._sdk_api_host}
                if self.api_key:
                    kwargs["api_token"] = self.api_key
                self._sdk_client = lmstudio.Client(**kwargs)
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
        for attr in ("identifier", "path", "model_key", "id", "name"):
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
        if "/" in mid:
            return mid.split("/")[-1]
        elif mid and mid != "unknown":
            return mid
        else:
            return "Local LM Studio Model"

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
        headers = self._auth_headers()
        
        # Try API endpoints with proper error handling
        urls_to_try = [
            # LM Studio native v0 endpoint (preserves context_length and quantization)
            self._server_root() + "/api/v0/models",
            # LM Studio native v1 / OpenAI endpoints
            self._openai_base() + "/models",
            self._server_root() + "/models",
            self._server_root() + "/api/v1/models",
        ]
        
        for url in urls_to_try:
            try:
                r = httpx.get(url, headers=headers, timeout=5)
                import logging
                logging.getLogger("hermes.lmstudio").debug(
                    "%s -> status=%s, content-type=%s", url, r.status_code, r.headers.get("content-type", "unknown")
                )
                
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except Exception:
                        continue
                    
                    if isinstance(data, dict):
                        models_list = data.get("data", data.get("models", []))
                    elif isinstance(data, list):
                        models_list = data
                    else:
                        continue
                    
                    result = []
                    for m in models_list:
                        if not isinstance(m, dict):
                            continue
                        model_id = m.get("id") or m.get("key") or m.get("path") or ""
                        if not model_id:
                            continue
                        
                        path = m.get("path") or model_id
                        raw_name = m.get("display_name") or model_id
                        display_name = raw_name
                        if "@" in display_name:
                            display_name = display_name.split("@")[0]
                        elif "/" in display_name:
                            display_name = display_name.split("/")[-1]
                        
                        context_length = m.get("max_context_length") or m.get("context_length")
                        quantization = m.get("quantization") or "unknown"
                        state = m.get("state") or "ready"
                        
                        result.append({
                            "id": model_id,
                            "path": path,
                            "display_name": display_name,
                            "context_length": context_length,
                            "quantization": quantization,
                            "state": state,
                        })
                    if result:
                        return result
            except Exception:
                continue
        
        # Fallback: return empty list (let UI show "no models" instead of fake ones)
        return []

    def load_model(self, model_key: str, gpu_index: Optional[int] = None,
                   context_length: int = DEFAULT_CONTEXT_LENGTH, flash_attention: bool = True) -> bool:
        """Load a model via SDK with GPU and context control.

        Finds the model object from downloaded models by matching model_key,
        then calls load_new_instance() on it directly.
        """
        if not self._sdk_client:
            raise RuntimeError("LM Studio SDK is not connected; reconnect before loading a model.")
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
        self.title(t("lmstudio.title"))
        self.configure(bg=C["bg_main"])
        self.transient(parent)
        set_dark_title_bar(self)
        from gui.theme import center_window
        center_window(self, 650, 580, parent)

        # Read configured endpoint from environment or .env file
        base_url = self._resolve_base_url()
        api_key = self._resolve_api_key()
        self.client = LMStudioClient(base_url=base_url, api_key=api_key)
        self.gpus = ["CPU"]
        self.models = []

        self._build_ui()
        self.after(100, self._connect)
        def discover_gpus():
            gpus = get_available_gpus()
            self.after(0, lambda: self._set_gpus(gpus))
        threading.Thread(target=discover_gpus, daemon=True).start()

    def _set_gpus(self, gpus):
        self.gpus = gpus
        self.gpu_combo.configure(values=gpus)
        self.gpu_combo.current(1 if len(gpus) > 1 else 0)

    @staticmethod
    def _resolve_base_url() -> str:
        """Return the LM Studio endpoint. Default is localhost:1234."""
        config = _read_lmstudio_config()
        if config.get("base_url"):
            return config["base_url"].strip().rstrip("/")
        # Fallback to environment variable
        if "LM_BASE_URL" in os.environ:
            return os.environ["LM_BASE_URL"].strip().rstrip("/")
        # Default
        return "http://localhost:1234/v1"

    @staticmethod
    def _resolve_api_key() -> str:
        """Return the LM Studio API key from config or environment."""
        config = _read_lmstudio_config()
        if "api_key" in config:
            return config["api_key"].strip()
        return os.environ.get("LM_API_TOKEN", os.environ.get("LM_API_KEY", "")).strip()

    def _build_ui(self):
        # Title
        hdr = tk.Frame(self, bg=C["bg_main"], padx=20, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text=t("lmstudio.heading", "LM Studio"), font=FONTS["title"],
                fg=C["accent"], bg=C["bg_main"]).pack(side="left")

        self.status_dot = tk.Label(hdr, text="\u25CF", font=SF("Segoe UI", 12),
                                  fg=C["text_disabled"], bg=C["bg_main"])
        self.status_dot.pack(side="left", padx=(8, 4))
        self.status_lbl = tk.Label(hdr, text=t("lmstudio.status_connecting", "Connecting..."), font=FONTS["small"],
                                  fg=C["text_hint"], bg=C["bg_main"])
        self.status_lbl.pack(side="left")

        if not HAS_SDK:
            tk.Label(hdr, text="(SDK not installed)", font=FONTS["small"],
                    fg=C["danger"], bg=C["bg_main"]).pack(side="right")

        # Endpoint config
        ep_row = tk.Frame(self, bg=C["bg_main"], padx=20)
        ep_row.pack(fill="x", pady=(0, 8))
        tk.Label(ep_row, text=t("lmstudio.endpoint", "Endpoint:"), font=FONTS["body"],
                fg=C["text_secondary"], bg=C["bg_main"]).pack(side="left")
        self._ep_var = tk.StringVar(value=self.client.base_url)
        ep_entry = tk.Entry(ep_row, textvariable=self._ep_var,
                           font=FONTS["mono_small"], bg=C["bg_input"],
                           fg=C["text_primary"], insertbackground=C["text_primary"],
                           relief="flat")
        ep_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), ipady=2)
        ttk.Button(ep_row, text=t("lmstudio.connect", "Connect"), style="Small.TButton",
                   command=self._apply_endpoint).pack(side="left")

        # API Key config
        key_row = tk.Frame(self, bg=C["bg_main"], padx=20)
        key_row.pack(fill="x", pady=(0, 8))
        tk.Label(key_row, text=t("lmstudio.api_key", "API Key:"), font=FONTS["body"],
                fg=C["text_secondary"], bg=C["bg_main"]).pack(side="left")
        self._key_var = tk.StringVar(value=self._resolve_api_key())
        key_entry = tk.Entry(key_row, textvariable=self._key_var,
                            font=FONTS["mono_small"], bg=C["bg_input"],
                            fg=C["text_primary"], insertbackground=C["text_primary"],
                            show="*", relief="flat")
        key_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), ipady=2)
        ttk.Button(key_row, text=t("lmstudio.save_key", "Save"), style="Small.TButton",
                   command=self._apply_api_key).pack(side="left")

        # Model list
        model_frame = tk.LabelFrame(self, text=f"  {t('lmstudio.available_models', 'Available Models')}  ",
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
        tk.Label(gpu_row, text=t("lmstudio.gpu", "GPU:"), font=FONTS["body"],
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
        tk.Label(ctx_row, text=t("lmstudio.context", "Context:"), font=FONTS["body"],
                fg=C["text_secondary"], bg=C["bg_main"], width=12,
                anchor="w").pack(side="left")

        self.ctx_var = tk.IntVar(value=DEFAULT_CONTEXT_LENGTH)
        # Use a tk.Scale for better visual control (ttk.Scale is too thin)
        # Match the core's context floor rather than loading a model it rejects.
        self.ctx_slider = tk.Scale(ctx_row, from_=MINIMUM_CONTEXT_LENGTH, to=max(131072, DEFAULT_CONTEXT_LENGTH),
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

        self.ctx_label = tk.Label(ctx_row, text=f"{DEFAULT_CONTEXT_LENGTH:,}", font=FONTS["mono_small"],
                                 fg=C["accent"], bg=C["bg_main"], width=10)
        self.ctx_label.pack(side="right")

        # Buttons
        btn_row = tk.Frame(self, bg=C["bg_main"], padx=20, pady=12)
        btn_row.pack(fill="x")

        self.load_btn = ttk.Button(btn_row, text=t("lmstudio.load", "Load Model"), style="Primary.TButton",
                                   command=self._load_model)
        self.load_btn.pack(side="left", padx=(0, 8))

        self.unload_btn = ttk.Button(btn_row, text=t("lmstudio.unload", "Unload"), style="Danger.TButton",
                                     command=self._unload_model)
        self.unload_btn.pack(side="left", padx=(0, 8))

        ttk.Button(btn_row, text=t("lmstudio.refresh", "Refresh"), style="TButton",
                   command=self._refresh_models).pack(side="left", padx=(0, 8))

        self.use_btn = ttk.Button(btn_row, text=t("lmstudio.use_chat", "Use for Chat"), style="Primary.TButton",
                                  command=self._use_model)
        self.use_btn.pack(side="right")

    def _connect(self):
        """Connect to LM Studio in background."""
        client = self.client
        client.api_key = self._key_var.get().strip()
        def _do():
            running = client.is_running()
            sdk_ok = False
            if running and HAS_SDK:
                sdk_ok = client.connect_sdk()
            self.after(0, lambda: self._on_connected(running, sdk_ok)
                       if self.client is client else None)

        threading.Thread(target=_do, daemon=True).start()

    def _on_connected(self, running, sdk_ok):
        if running:
            self.status_dot.configure(fg=C["success"])
            status = t("lmstudio.status_connected", "Connected")
            if sdk_ok:
                status += " (SDK active)"
            self.status_lbl.configure(text=status)
            self._refresh_models()
        else:
            self.status_dot.configure(fg=C["danger"])
            self.status_lbl.configure(text=t("lmstudio.status_not_running", "Not running — start LM Studio first"))

    def _apply_endpoint(self):
        """Apply a new LM Studio endpoint URL and reconnect."""
        url = self._ep_var.get().strip().rstrip("/")
        if not url:
            return
        if not _write_lmstudio_config(base_url=url, api_key=self._key_var.get().strip()):
            self.status_lbl.configure(text=t("lmstudio.save_failed", "Failed to save configuration"))
            return
        self.client = LMStudioClient(base_url=url, api_key=self._key_var.get().strip())
        # Update status and reconnect
        self.status_dot.configure(fg=C["text_disabled"])
        self.status_lbl.configure(text=t("lmstudio.status_connecting", "Connecting..."))
        self._connect()

    def _apply_api_key(self):
        """Save API key and reconnect."""
        key = self._key_var.get().strip()
        saved = _write_lmstudio_config(base_url=self._ep_var.get().strip().rstrip("/"), api_key=key)
        if not saved:
            self.status_lbl.configure(text=t("lmstudio.save_failed", "Failed to save configuration"))
            return
        elif key:
            self.status_lbl.configure(text=t("lmstudio.api_key_saved", "API key saved"))
        else:
            self.status_lbl.configure(text=t("lmstudio.api_key_cleared", "API key cleared"))
        self.client = LMStudioClient(base_url=self._ep_var.get().strip().rstrip("/"), api_key=key)
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
            self.ctx_slider.configure(to=max(max_ctx, DEFAULT_CONTEXT_LENGTH))
            # Only set a default if user hasn't touched the slider yet
            current = self.ctx_var.get()
            if current > max_ctx >= MINIMUM_CONTEXT_LENGTH:
                safe = max(MINIMUM_CONTEXT_LENGTH, (max_ctx // 512) * 512)
                self.ctx_var.set(safe)
                self.ctx_label.configure(text=f"{safe:,}")

    def _on_ctx_change(self, val):
        v = int(float(val))
        # Snap to nearest 512
        v = max(MINIMUM_CONTEXT_LENGTH, (v // 512) * 512)
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
        supported_context = model.get("context_length")
        if supported_context and supported_context < MINIMUM_CONTEXT_LENGTH:
            messagebox.showwarning(
                "Model Context Too Small",
                f"This model supports {supported_context:,} tokens. Hermes requires "
                f"at least {MINIMUM_CONTEXT_LENGTH:,}; select a larger-context model.",
                parent=self,
            )
            return
        ctx = int(self.ctx_var.get())
        ctx = max(MINIMUM_CONTEXT_LENGTH, (ctx // 512) * 512)

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
