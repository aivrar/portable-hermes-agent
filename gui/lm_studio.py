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
import queue
import tempfile
from urllib.parse import urlsplit
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import List, Dict, Optional

from gui.theme import C, FONTS, set_dark_title_bar, Tooltip, SF
from gui.i18n import t, register_listener, unregister_listener
from hermes_constants import get_hermes_home
from portable_hermes import lmstudio_gpu as gpu_place
try:
    from agent.model_metadata import MINIMUM_CONTEXT_LENGTH
except ImportError:          # an older core without the minimum
    MINIMUM_CONTEXT_LENGTH = 64000

# The panel and the sidebar load models with this window by default.
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

def detect_gpus() -> List["gpu_place.NvidiaGpu"]:
    """NVIDIA GPUs in nvidia-smi order (empty without nvidia-smi).

    Also warms LM Studio's hardware survey, which maps these to LM Studio's
    own GPU numbering at load time; call it off the Tk thread."""
    gpus = gpu_place.list_nvidia_gpus()
    if gpus:
        gpu_place.lmstudio_gpu_survey()
    return gpus


def gpu_choice_label(placement: str, gpus=()) -> str:
    """Display text for one GPU placement choice (translated where it is words)."""
    kind, index = gpu_place.parse_placement(placement)
    if kind == "gpu":
        for gpu in gpus:
            if gpu.index == index:
                return f"GPU {gpu.index}: {gpu.name} ({gpu.memory_mib} MiB)"
        return f"GPU {index}"
    return t({gpu_place.AUTO: "lmstudio.gpu_auto",
              gpu_place.CPU: "lmstudio.gpu_cpu",
              gpu_place.SPLIT: "lmstudio.gpu_split"}[kind])


def gpu_choices(gpus) -> List[tuple]:
    """``[(placement, label), ...]`` for a GPU combobox, in display order."""
    return [(p, gpu_choice_label(p, gpus)) for p in gpu_place.placements_for(gpus)]


def gpu_unconfirmed_note(plan, choice_label: str) -> Optional[str]:
    """User-facing warning when *plan*'s GPU could not be confirmed: the
    numbering was only estimated, or CPU only could not disable any GPU."""
    if plan is None or getattr(plan, "confirmed", True):
        return None
    if plan.mapping == gpu_place.MAP_NO_GPU_LIST:
        return t("lmstudio.gpu_cpu_unconfirmed")
    return t("lmstudio.gpu_unconfirmed", choice=choice_label)


def get_available_gpus() -> List[str]:
    """Display labels of the GPU choices (kept for older callers)."""
    return [label for _placement, label in gpu_choices(detect_gpus())]


#: Selection preference for LMStudioPanel._display_models: the row marked
#: loaded, when exactly one is.
ONLY_LOADED_ROW = object()


def _one_row_per_model(models: List[Dict]) -> List[Dict]:
    """Keep one row per model id (first position), preferring a loaded row."""
    rows: Dict[str, Dict] = {}
    for m in models:
        kept = rows.get(m["id"])
        if kept is None or (m.get("state") == "loaded" and kept.get("state") != "loaded"):
            rows[m["id"]] = m
    return list(rows.values())


# ============================================================================
# LM Studio Client
# ============================================================================

class LMStudioClient:
    """Manages LM Studio SDK connection, model loading, and OpenAI endpoint."""

    def __init__(self, base_url: str = "http://localhost:1234/v1", api_key: Optional[str] = None):
        self.base_url = base_url.strip().rstrip("/")
        self.last_loaded_identifier: Optional[str] = None  # set by load_model()
        self.last_gpu_plan = None  # GpuPlan used by the last load_model()
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
            rows = []
            for m in models:
                info = getattr(m, "info", None)
                key = getattr(m, "model_key", None)
                rows.append({
                    "path": self._extract_model_id(m),
                    # The key the REST list and load_model use for this model.
                    "model_key": key if isinstance(key, str) and key else None,
                    "display_name": (getattr(info, "display_name", None)
                                     or self._extract_display_name(m)),
                    "context_length": getattr(info, "max_context_length", None),
                })
            return rows
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
                        if isinstance(quantization, dict):     # /api/v1: {"name": "Q4_K_M", ...}
                            quantization = quantization.get("name") or "unknown"
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
                        return _one_row_per_model(result)
            except Exception:
                continue
        
        # Fallback: return empty list (let UI show "no models" instead of fake ones)
        return []

    def _loaded_identifiers(self) -> set:
        """Identifiers of the instances LM Studio has loaded (empty if unknown)."""
        try:
            ids = (getattr(m, "identifier", None) for m in self._sdk_client.llm.list_loaded())
            return {i for i in ids if isinstance(i, str) and i}
        except Exception:
            return set()

    def load_model(self, model_key: str, gpu_index: Optional[int] = None,
                   context_length: int = DEFAULT_CONTEXT_LENGTH, flash_attention: bool = True,
                   gpu_placement: Optional[str] = None) -> bool:
        """Load a model via SDK with GPU and context control.

        *gpu_placement* is ``auto``, ``cpu``, ``split`` or ``gpu:<nvidia-smi
        index>`` (see portable_hermes.lmstudio_gpu); when it is not given,
        *gpu_index* means ``gpu:<index>`` and None means ``auto``.

        Finds the model object from downloaded models by matching model_key,
        then calls load_new_instance() on it directly.
        """
        if not self._sdk_client:
            raise RuntimeError("LM Studio SDK is not connected; reconnect before loading a model.")
        placement = gpu_placement or gpu_place.placement_from_index(gpu_index)
        try:
            # Resolve the placement before unloading anything, so an unknown
            # GPU leaves the current model loaded.
            plan = gpu_place.plan(placement)
        except ValueError as e:
            raise RuntimeError(f"Failed to load model: {e}")
        self.last_gpu_plan = plan
        import logging
        _log = logging.getLogger("hermes.lmstudio")
        try:
            # Find the SDK model object by model_key, path or display name.
            downloaded = list(self._sdk_client.llm.list_downloaded())
        except Exception as e:
            raise RuntimeError(f"Failed to load model: {e}")
        _log.info("Looking for model_key=%r among %d downloaded models", model_key, len(downloaded))
        # An exact key first: variants of one model ("name@q4_k_m", "name@q6_k")
        # can share a display name, so the first match on any field could be
        # another quantisation.
        target = next((m for field in ("model_key", "path", "display_name") for m in downloaded
                       if getattr(m, field, "") == model_key), None)
        # Hermes cannot chat with a window below the core's minimum: raise a
        # smaller request to it, and refuse a model that cannot go that far,
        # before anything is unloaded.
        context_length = max(MINIMUM_CONTEXT_LENGTH, int(context_length))
        max_ctx = getattr(getattr(target, "info", None), "max_context_length", None)
        if isinstance(max_ctx, int) and max_ctx > 0:
            if max_ctx < MINIMUM_CONTEXT_LENGTH:
                raise RuntimeError(t("lmstudio.context_too_small_msg", supported=f"{max_ctx:,}",
                                     required=f"{MINIMUM_CONTEXT_LENGTH:,}"))
            context_length = min(context_length, max_ctx)
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

            # nvidia-smi and LM Studio number GPUs differently; the plan holds
            # LM Studio's indices (mapping in portable_hermes.lmstudio_gpu).
            gpu_config = GpuSetting(**plan.gpu) if plan.gpu else None
            config = LlmLoadModelConfig(
                gpu=gpu_config,
                context_length=context_length,
                flash_attention=flash_attention,
                **plan.load,
            )

            _log.info("GPU placement %s -> %r (LM Studio GPU %r, mapping %s)",
                      plan.placement, plan.gpu, plan.lmstudio_gpu, plan.mapping)

            # No instance_identifier: LM Studio then names the instance after
            # the model key (e.g. "gemma-4-e4b-it"; "key:2" only if another
            # instance survived the unload above). That id is what the model
            # list, the chat requests and every label show, so the user sees
            # the real model name and the list shows it once, as loaded.
            # The instance id can still differ from the requested key (e.g. a
            # "name@q4_k_m" variant), so remember the id LM Studio really used.
            self.last_loaded_identifier = None
            before = self._loaded_identifiers()
            if target is not None:
                # Use the SDK model object's own load method
                _log.info("Loading via SDK model object, ctx=%d gpu=%s", context_length, plan.placement)
                handle = target.load_new_instance(config=config, ttl=86400)
            else:
                # Fallback: try string-based load
                _log.warning("No SDK model object found, trying string key: %r", model_key)
                handle = self._sdk_client.llm.load_new_instance(
                    model_key, config=config, ttl=86400,
                )
            identifier = getattr(handle, "identifier", None)
            if not isinstance(identifier, str) or not identifier:
                new = self._loaded_identifiers() - before
                identifier = next(iter(new)) if len(new) == 1 else None
            self.last_loaded_identifier = identifier
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

    def __init__(self, parent, on_model_ready=None, can_change_model=None,
                 track_model_work=None):
        super().__init__(parent)
        self.on_model_ready = on_model_ready
        # can_change_model() -> False while a chat reply runs (Load/Unload
        # would unload the model it uses); track_model_work(thread) tells the
        # app a load is running (sending waits for it).
        self.can_change_model = can_change_model
        self.track_model_work = track_model_work
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
        self.gpus = []  # NvidiaGpu entries; choices come from gpu_choices()
        self._gpu_label_to_placement = {}
        self._gpu_user_choice = None  # placement the user picked, if any
        self.models = []
        self._ui_results = queue.SimpleQueue()
        self._closed = False

        self._build_ui()
        register_listener(self.update_ui_language)
        self._ui_poll_id = self.after(50, self._drain_ui_results)
        self.after(100, self._connect)
        def discover_gpus():
            gpus = detect_gpus()
            self._post_ui("_set_gpus", gpus)
        threading.Thread(target=discover_gpus, daemon=True).start()

    def destroy(self):
        self._closed = True
        self.after_cancel(self._ui_poll_id)
        unregister_listener(self.update_ui_language)
        super().destroy()

    def _post_ui(self, method_name, *args):
        """Workers queue results; only the Tk thread may schedule callbacks."""
        if not self._closed:
            self._ui_results.put((method_name, args))

    def _drain_ui_results(self):
        if self._closed:
            return
        try:
            while not self._closed:
                try:
                    method_name, args = self._ui_results.get_nowait()
                except queue.Empty:
                    break
                getattr(self, method_name)(*args)
        finally:
            if not self._closed:
                self._ui_poll_id = self.after(50, self._drain_ui_results)

    def _set_status(self, key, **kwargs):
        self._status_key = key
        self._status_kwargs = kwargs
        self.status_lbl.configure(text=t(key, **kwargs))

    def update_ui_language(self, _lang_code=None):
        self.title(t("lmstudio.title"))
        for widget, key in self._localized_widgets:
            widget.configure(text=t(key))
        self._model_frame.configure(text=f"  {t('lmstudio.available_models')}  ")
        if hasattr(self, "_cancel_btn"):
            self._cancel_btn.configure(text=t("lmstudio.cancel_load"))
        self._set_status(self._status_key, **self._status_kwargs)
        self._display_models(self.models)
        self._show_gpu_choices(self._selected_gpu_placement())

    def _selected_gpu_placement(self) -> str:
        """Placement of the GPU combobox entry (auto when unknown)."""
        return self._gpu_label_to_placement.get(self.gpu_var.get(), gpu_place.AUTO)

    def _show_gpu_choices(self, selected: str):
        choices = gpu_choices(self.gpus)
        self._gpu_label_to_placement = {label: p for p, label in choices}
        placements = [p for p, _label in choices]
        if selected not in placements:
            selected = gpu_place.default_placement(self.gpus)
        self.gpu_combo.configure(values=[label for _p, label in choices])
        self.gpu_combo.current(placements.index(selected))

    def _on_gpu_chosen(self, _event=None):
        """The user picked a GPU entry: remember it (by placement, not label)."""
        self._gpu_user_choice = self._selected_gpu_placement()

    def _set_gpus(self, gpus):
        """Detection finished (possibly after the user already chose an entry,
        e.g. CPU only): keep that choice when it is still offered."""
        self.gpus = list(gpus)
        chosen = getattr(self, "_gpu_user_choice", None)
        self._show_gpu_choices(chosen or gpu_place.default_placement(self.gpus))

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
        self._localized_widgets = []
        heading = tk.Label(hdr, text=t("lmstudio.heading"), font=FONTS["title"],
                           fg=C["accent"], bg=C["bg_main"])
        heading.pack(side="left")
        self._localized_widgets.append((heading, "lmstudio.heading"))

        self.status_dot = tk.Label(hdr, text="\u25CF", font=SF("Segoe UI", 12),
                                  fg=C["text_disabled"], bg=C["bg_main"])
        self.status_dot.pack(side="left", padx=(8, 4))
        self._status_key = "lmstudio.status_connecting"
        self._status_kwargs = {}
        self.status_lbl = tk.Label(hdr, text=t(self._status_key), font=FONTS["small"],
                                  fg=C["text_hint"], bg=C["bg_main"])
        self.status_lbl.pack(side="left")

        if not HAS_SDK:
            sdk_label = tk.Label(hdr, text=t("lmstudio.sdk_missing"), font=FONTS["small"],
                                 fg=C["danger"], bg=C["bg_main"])
            sdk_label.pack(side="right")
            self._localized_widgets.append((sdk_label, "lmstudio.sdk_missing"))

        # Endpoint config
        ep_row = tk.Frame(self, bg=C["bg_main"], padx=20)
        ep_row.pack(fill="x", pady=(0, 8))
        endpoint_label = tk.Label(ep_row, text=t("lmstudio.endpoint"), font=FONTS["body"],
                                  fg=C["text_secondary"], bg=C["bg_main"])
        endpoint_label.pack(side="left")
        self._localized_widgets.append((endpoint_label, "lmstudio.endpoint"))
        self._ep_var = tk.StringVar(value=self.client.base_url)
        ep_entry = tk.Entry(ep_row, textvariable=self._ep_var,
                           font=FONTS["mono_small"], bg=C["bg_input"],
                           fg=C["text_primary"], insertbackground=C["text_primary"],
                           relief="flat")
        ep_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), ipady=2)
        connect_btn = ttk.Button(ep_row, text=t("lmstudio.connect"), style="Small.TButton",
                                 command=self._apply_endpoint)
        connect_btn.pack(side="left")
        self._localized_widgets.append((connect_btn, "lmstudio.connect"))

        # API Key config
        key_row = tk.Frame(self, bg=C["bg_main"], padx=20)
        key_row.pack(fill="x", pady=(0, 8))
        key_label = tk.Label(key_row, text=t("lmstudio.api_key"), font=FONTS["body"],
                             fg=C["text_secondary"], bg=C["bg_main"])
        key_label.pack(side="left")
        self._localized_widgets.append((key_label, "lmstudio.api_key"))
        self._key_var = tk.StringVar(value=self._resolve_api_key())
        key_entry = tk.Entry(key_row, textvariable=self._key_var,
                            font=FONTS["mono_small"], bg=C["bg_input"],
                            fg=C["text_primary"], insertbackground=C["text_primary"],
                            show="*", relief="flat")
        key_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), ipady=2)
        save_btn = ttk.Button(key_row, text=t("lmstudio.save_key"), style="Small.TButton",
                              command=self._apply_api_key)
        save_btn.pack(side="left")
        self._localized_widgets.append((save_btn, "lmstudio.save_key"))

        # Model list
        self._model_frame = tk.LabelFrame(self, text=f"  {t('lmstudio.available_models')}  ",
                                    bg=C["bg_main"], fg=C["text_secondary"],
                                    font=FONTS["subheading"], padx=12, pady=8)
        model_frame = self._model_frame
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
        gpu_label = tk.Label(gpu_row, text=t("lmstudio.gpu"), font=FONTS["body"],
                             fg=C["text_secondary"], bg=C["bg_main"], width=12,
                             anchor="w")
        gpu_label.pack(side="left")
        self._localized_widgets.append((gpu_label, "lmstudio.gpu"))
        self.gpu_var = tk.StringVar()
        self.gpu_combo = ttk.Combobox(gpu_row, textvariable=self.gpu_var,
                                      font=FONTS["body"], state="readonly")
        # Style the dropdown list to match the parent font
        self.option_add("*TCombobox*Listbox.font", FONTS["body"])
        # Auto until GPU detection finishes; then the first GPU (_set_gpus).
        self._show_gpu_choices(gpu_place.default_placement(self.gpus))
        self.gpu_combo.bind("<<ComboboxSelected>>", self._on_gpu_chosen)
        self.gpu_combo.pack(side="left", fill="x", expand=True)

        # Context length slider
        from gui.theme import S as _S
        ctx_row = tk.Frame(ctrl, bg=C["bg_main"])
        ctx_row.pack(fill="x", pady=4)
        context_label = tk.Label(ctx_row, text=t("lmstudio.context"), font=FONTS["body"],
                                 fg=C["text_secondary"], bg=C["bg_main"], width=12,
                                 anchor="w")
        context_label.pack(side="left")
        self._localized_widgets.append((context_label, "lmstudio.context"))

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
        self._localized_widgets.append((self.load_btn, "lmstudio.load"))

        self.unload_btn = ttk.Button(btn_row, text=t("lmstudio.unload", "Unload"), style="Danger.TButton",
                                     command=self._unload_model)
        self.unload_btn.pack(side="left", padx=(0, 8))
        self._localized_widgets.append((self.unload_btn, "lmstudio.unload"))

        refresh_btn = ttk.Button(btn_row, text=t("lmstudio.refresh"), style="TButton",
                                 command=self._refresh_models)
        refresh_btn.pack(side="left", padx=(0, 8))
        self._localized_widgets.append((refresh_btn, "lmstudio.refresh"))

        self.use_btn = ttk.Button(btn_row, text=t("lmstudio.use_chat", "Use for Chat"), style="Primary.TButton",
                                  command=self._use_model)
        self.use_btn.pack(side="right")
        self._localized_widgets.append((self.use_btn, "lmstudio.use_chat"))

    def _connect(self):
        """Connect to LM Studio in background."""
        client = self.client
        client.api_key = self._key_var.get().strip()
        def _do():
            running = client.is_running()
            sdk_ok = False
            if running and HAS_SDK:
                sdk_ok = client.connect_sdk()
            self._post_ui("_finish_connect", client, running, sdk_ok)

        threading.Thread(target=_do, daemon=True).start()

    def _finish_connect(self, client, running, sdk_ok):
        if self.client is client:
            self._on_connected(running, sdk_ok)

    def _on_connected(self, running, sdk_ok):
        if running:
            self.status_dot.configure(fg=C["success"])
            self._set_status("lmstudio.status_connected_sdk" if sdk_ok else "lmstudio.status_connected")
            self._refresh_models()
        else:
            self.status_dot.configure(fg=C["danger"])
            self._set_status("lmstudio.status_not_running")

    def _apply_endpoint(self):
        """Apply a new LM Studio endpoint URL and reconnect."""
        url = self._ep_var.get().strip().rstrip("/")
        if not url:
            return
        if not _write_lmstudio_config(base_url=url, api_key=self._key_var.get().strip()):
            self._set_status("lmstudio.save_failed")
            return
        self.client = LMStudioClient(base_url=url, api_key=self._key_var.get().strip())
        # Update status and reconnect
        self.status_dot.configure(fg=C["text_disabled"])
        self._set_status("lmstudio.status_connecting")
        self._connect()

    def _apply_api_key(self):
        """Save API key and reconnect."""
        key = self._key_var.get().strip()
        saved = _write_lmstudio_config(base_url=self._ep_var.get().strip().rstrip("/"), api_key=key)
        if not saved:
            self._set_status("lmstudio.save_failed")
            return
        elif key:
            self._set_status("lmstudio.api_key_saved")
        else:
            self._set_status("lmstudio.api_key_cleared")
        self.client = LMStudioClient(base_url=self._ep_var.get().strip().rstrip("/"), api_key=key)
        self._connect()

    def _refresh_models(self, select_id=None, select_ids=()):
        """Refresh model list, then select *select_id* or the first of
        *select_ids* that is listed (see _display_models)."""
        def _do():
            models = self.client.list_models_api()
            if HAS_SDK and self.client._sdk_client:
                try:
                    downloaded = self.client.list_downloaded_models()
                    # Add downloaded models the REST list lacks. The REST list
                    # names models by key; the SDK by key and file path, so
                    # match on both (on the path alone every model came twice).
                    api_ids = {m["id"] for m in models}
                    for d in downloaded:
                        key = d.get("model_key")
                        if d["path"] in api_ids or key in api_ids:
                            continue
                        models.append({
                            "id": key or d["path"],
                            "display_name": d.get("display_name") or key or d["path"],
                            "context_length": d.get("context_length"),
                            "state": "not-loaded",
                        })
                except Exception:
                    pass
            self._post_ui("_display_models", models, select_id, select_ids)

        threading.Thread(target=_do, daemon=True).start()

    def _display_models(self, models, select_id=None, select_ids=()):
        """Show *models*; select the first listed of *select_id*, *select_ids*
        (ONLY_LOADED_ROW: the row marked loaded, if exactly one) and the
        previously selected model."""
        # Keep the selection on the same model (by id, not row: a refresh can
        # add, drop or reorder rows), or move it to *select_id* if given.
        selected = self.model_list.curselection()
        previous_id = (self.models[selected[0]]["id"]
                       if selected and selected[0] < len(self.models) else None)
        self.models = models
        self.model_list.delete(0, "end")
        for m in models:
            mid = m["id"]
            display = m.get("display_name") or mid
            if "@" in mid:      # one of several variants of a model: say which
                quant = m.get("quantization")
                display += f" [{quant if quant and quant != 'unknown' else mid.split('@', 1)[1]}]"
            state = m.get("state", "")
            ctx = m.get("context_length")
            label = display
            if state == "loaded":
                label = f"{t('lmstudio.loaded_tag')} {display}"
            if ctx:
                label += f"  {t('lmstudio.context_suffix', count=f'{ctx:,}')}"
            self.model_list.insert("end", label)
        ids = [m["id"] for m in models]
        loaded = [m["id"] for m in models if m.get("state") == "loaded"]
        only_loaded = loaded[0] if len(loaded) == 1 else None
        candidates = [select_id, *select_ids, previous_id]
        for wanted in candidates:
            if wanted is ONLY_LOADED_ROW:
                wanted = only_loaded
            if wanted is not None and wanted in ids:
                row = ids.index(wanted)
                self.model_list.selection_set(row)
                self.model_list.see(row)
                break

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

    def _refuse_during_reply(self) -> bool:
        """True (and says why) while a chat reply is running."""
        can_change = getattr(self, "can_change_model", None)
        if can_change is None or can_change():
            return False
        messagebox.showinfo(t("lmstudio.title"), t("chat.busy_stop_first", stop=t("chat.stop")),
                            parent=self)
        return True

    def model_work_pending(self) -> bool:
        """A load (or its cancel) has not completed on the Tk side yet: the
        Cancel button is shown until _restore_load_btn. A closed panel's
        completion never runs, so it no longer counts (its worker thread
        still does, see track_model_work)."""
        return not self._closed and hasattr(self, "_cancel_btn")

    def _start_model_work(self, target):
        """Run a load/unload worker; the app knows while it is alive."""
        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        track = getattr(self, "track_model_work", None)
        if track:
            track(worker)

    def _load_model(self):
        if self._refuse_during_reply():
            return
        sel = self.model_list.curselection()
        if not sel:
            messagebox.showwarning(t("lmstudio.no_model_title"),
                                   t("lmstudio.select_model_first"), parent=self)
            return

        idx = sel[0]
        model = self.models[idx]
        # The row's key ("name@q6_k" for one variant) is what is loaded: the
        # REST path can be shared by several variants of one model.
        model_id = model["id"]
        supported_context = model.get("context_length")
        if supported_context and supported_context < MINIMUM_CONTEXT_LENGTH:
            messagebox.showwarning(
                t("lmstudio.context_too_small_title"),
                t("lmstudio.context_too_small_msg", supported=f"{supported_context:,}",
                  required=f"{MINIMUM_CONTEXT_LENGTH:,}"),
                parent=self,
            )
            return
        ctx = int(self.ctx_var.get())
        ctx = max(MINIMUM_CONTEXT_LENGTH, (ctx // 512) * 512)

        # GPU selection (labels are translated, so map back to the placement)
        gpu_label = self.gpu_var.get()
        placement = getattr(self, "_gpu_label_to_placement", {}).get(gpu_label, gpu_place.AUTO)

        short = model_id.split("/")[-1] if "/" in model_id else model_id
        self._set_status("lmstudio.loading_model", model=short)
        self.status_dot.configure(fg=C["warning_dark"])

        # Show cancel button, hide load button
        self.load_btn.pack_forget()
        self._cancel_btn = ttk.Button(self.load_btn.master, text=t("lmstudio.cancel_load"),
                                       style="Danger.TButton",
                                       command=self._cancel_load)
        self._cancel_btn.pack(side="left", padx=(0, 8), before=self.unload_btn)
        self._loading = True

        def _do():
            try:
                # Log to file for debugging
                import logging
                _log = logging.getLogger("hermes.lmstudio")
                _log.warning("PANEL LOAD: model_id=%r ctx=%d gpu=%s", model_id, ctx, placement)
                self.client.load_model(model_id, gpu_placement=placement,
                                       context_length=ctx)
                if self._loading:
                    plan = getattr(self.client, "last_gpu_plan", None)
                    self._post_ui("_on_load_success", model_id,
                                  getattr(self.client, "last_loaded_identifier", None),
                                  gpu_unconfirmed_note(plan, gpu_label),
                                  getattr(plan, "placement", None) == gpu_place.CPU)
            except Exception as e:
                import logging
                logging.getLogger("hermes.lmstudio").error("PANEL LOAD FAILED: %s", e)
                if self._loading:
                    # Unload to stop JIT retry loops - here, so the model work
                    # (and the app's "busy") ends only after it.
                    self._unload_all()
                    err = t("lmstudio.load_error_details", model=model_id, context=ctx,
                            gpu=gpu_label, error=e)
                    self._post_ui("_on_load_error", err, model_id)

        self._start_model_work(_do)

    def _unload_all(self):
        try:
            if self.client._sdk_client:
                for m in list(self.client._sdk_client.llm.list_loaded()):
                    try:
                        m.unload()
                    except Exception:
                        pass
        except Exception:
            pass

    def _cancel_load(self):
        """Cancel an in-progress model load by unloading all models."""
        if self._refuse_during_reply():   # it unloads every model
            return
        self._loading = False
        self._set_status("lmstudio.cancelling")
        def _do():
            self._unload_all()   # whatever was loaded
            self._post_ui("_on_cancel_done")
        self._start_model_work(_do)

    def _on_cancel_done(self):
        self._restore_load_btn()
        self.status_dot.configure(fg=C["text_disabled"])
        self._set_status("lmstudio.load_cancelled")
        self._refresh_models()

    def _restore_load_btn(self):
        """Swap cancel button back to load button."""
        if hasattr(self, '_cancel_btn'):
            self._cancel_btn.destroy()
            del self._cancel_btn
        # Back in its original slot: [Load Model][Unload][Refresh Models]
        self.load_btn.pack(side="left", padx=(0, 8), before=self.unload_btn)

    def _on_load_success(self, model_id, loaded_id=None, gpu_note=None, in_ram=False):
        """*loaded_id*: the instance id LM Studio gave the load, if known; it can
        differ from the requested row id (e.g. for "name@quant" variants).
        *gpu_note*: set when the GPU could not be confirmed (gpu_unconfirmed_note).
        *in_ram*: a CPU-only load (LM Studio may still use some GPU memory)."""
        self._restore_load_btn()
        short = model_id.split("/")[-1] if "/" in model_id else model_id
        if gpu_note:
            self.status_dot.configure(fg=C["warning_dark"])
            self._set_status("lmstudio.loaded_model_gpu_unconfirmed", model=short)
        else:
            self.status_dot.configure(fg=C["success"])
            self._set_status("lmstudio.loaded_model_cpu" if in_ram else "lmstudio.loaded_model",
                             model=short)
        # Prefer the real instance id, else the only row marked loaded, else
        # the requested row. Started before the (modal) warning below, so the
        # list is not stale while it is open.
        prefer = (loaded_id,) if loaded_id else ()
        self._refresh_models(select_ids=prefer + (ONLY_LOADED_ROW, model_id))
        if gpu_note:
            messagebox.showwarning(t("lmstudio.gpu_unconfirmed_title"), gpu_note, parent=self)

    def _on_load_error(self, error, model_id=None):
        """*model_id*: the row the user tried to load; it stays selected when
        the list is refreshed (the load worker unloaded everything)."""
        self._restore_load_btn()
        self.status_dot.configure(fg=C["danger"])
        self._set_status("lmstudio.load_failed")
        # The unload changed what is loaded: refresh so no row still shows
        # [LOADED], keeping the user's selection.
        self._refresh_models(select_ids=(model_id,) if model_id else ())
        messagebox.showerror(t("lmstudio.load_error_title"), error, parent=self)

    def _unload_model(self):
        if self._refuse_during_reply():
            return
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
