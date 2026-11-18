#!/usr/bin/env python3
"""
LM Studio Tools — Full LM Studio SDK control.

Modeled after AgentNate's lm_studio_provider.py which works flawlessly.

Key lessons from AgentNate:
- SDK uses api_host (host:port), NOT base_url
- SDK connects via websocket on ports 41343/52993/etc, NOT the HTTP port 1234
- Use Client.find_default_local_api_host() for SDK port discovery
- Use LlmLoadModelConfig + GpuSetting for GPU isolation
- HTTP API (port 1234) is only for inference, SDK is for model management
- Store handles from load_new_instance() for later unload
"""

import json
import logging
import time

from tools.registry import registry

logger = logging.getLogger(__name__)


def _resolve_lms_base() -> str:
    """Derive LM Studio base URL from env vars or default.

    Priority: LM_STUDIO_BASE_URL > OPENAI_BASE_URL > http://localhost:1234
    LM_STUDIO_BASE_URL is preferred because OPENAI_BASE_URL may point to
    another service (e.g. a local TTS server on port 8100).
    """
    import os
    # Prefer dedicated LM Studio var to avoid conflicts with other services
    base = os.environ.get("LM_STUDIO_BASE_URL", "").strip().rstrip("/")
    if not base:
        base = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    if base:
        # Strip /v1 suffix to get the base
        if base.endswith("/v1"):
            return base[:-3]
        return base
    return "http://localhost:1234"


_LMS_HTTP_BASE = _resolve_lms_base()

# SDK imports (graceful degradation)
try:
    import lmstudio
    from lmstudio import LlmLoadModelConfig
    from lmstudio._sdk_models import GpuSetting
    _HAS_SDK = True
except ImportError:
    lmstudio = None
    LlmLoadModelConfig = None
    GpuSetting = None
    _HAS_SDK = False

# Cache SDK client + handles across tool calls (module-level singleton)
_sdk_client = None
_sdk_api_host = None
_sdk_handles = {}  # identifier -> SDK model handle


def _check_lm_studio() -> bool:
    """Check if LM Studio HTTP server is reachable."""
    try:
        import httpx
        r = httpx.get(f"{_LMS_HTTP_BASE}/v1/models", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def _get_sdk_client():
    """Get or create a cached SDK client using proper api_host discovery.

    This matches AgentNate's pattern:
    1. Client.find_default_local_api_host() to discover the websocket port
    2. Client(api_host=host) to connect
    """
    global _sdk_client, _sdk_api_host

    if not _HAS_SDK:
        raise RuntimeError("lmstudio SDK not installed")

    if _sdk_client is not None:
        return _sdk_client

    # Discover SDK API host (scans default ports: 41343, 52993, etc.)
    start = time.time()
    _sdk_api_host = lmstudio.Client.find_default_local_api_host()
    elapsed = time.time() - start
    logger.info("LM Studio SDK host lookup took %.2fs: %s", elapsed, _sdk_api_host)

    if not _sdk_api_host:
        raise ConnectionError("Could not discover LM Studio SDK port")

    _sdk_client = lmstudio.Client(api_host=_sdk_api_host)
    return _sdk_client


_GPU_MODES = ("auto", "cpu", "split")


def _gpu_placement_for(args: dict):
    """``(placement, error)`` from the tool's gpu_index / gpu_mode arguments.

    gpu_index (nvidia-smi index, as lm_studio_status lists GPUs) pins the model
    to that GPU; gpu_mode is auto (LM Studio decides), cpu or split (every GPU,
    largest first). Neither given: auto, as before."""
    gpu_index = args.get("gpu_index")
    mode = str(args.get("gpu_mode") or "").strip().lower()
    if mode and mode not in _GPU_MODES:
        return None, f"gpu_mode must be one of {', '.join(_GPU_MODES)}"
    if gpu_index is not None:
        if mode and mode != "auto":
            return None, "give either gpu_index or gpu_mode, not both"
        try:
            gpu_index = int(gpu_index)
        except (TypeError, ValueError):
            return None, f"gpu_index must be an integer, got {gpu_index!r}"
        if gpu_index < 0:
            return None, f"gpu_index must be 0 or more, got {gpu_index}"
        return f"gpu:{gpu_index}", None
    return mode or "auto", None


# ---------------------------------------------------------------------------
# Tool: lm_studio_status
# ---------------------------------------------------------------------------
def lm_studio_status_handler(args: dict, **kwargs) -> str:
    """Check LM Studio status, loaded models, and GPU info."""
    result = {"running": False, "loaded_models": [], "gpus": []}
    try:
        import httpx
        r = httpx.get(f"{_LMS_HTTP_BASE}/v1/models", timeout=3.0)
        if r.status_code != 200:
            return json.dumps(result)
        result["running"] = True

        # List loaded models via SDK (preferred) or REST fallback
        try:
            client = _get_sdk_client()
            loaded = list(client.llm.list_loaded())
            result["loaded_models"] = [
                {
                    "identifier": m.identifier,
                    "path": getattr(m, "path", ""),
                }
                for m in loaded
            ]
        except Exception as e:
            logger.debug("SDK list_loaded failed, using REST fallback: %s", e)
            data = r.json()
            models = data.get("data", [])
            result["loaded_models"] = [
                {"identifier": m.get("id", ""), "path": ""}
                for m in models
            ]

        # GPU info
        try:
            import subprocess
            proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                for line in proc.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 5:
                        result["gpus"].append({
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_total_mb": int(parts[2]),
                            "memory_used_mb": int(parts[3]),
                            "memory_free_mb": int(parts[4]),
                        })
        except Exception:
            pass

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"running": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Tool: lm_studio_models
# ---------------------------------------------------------------------------
def lm_studio_models_handler(args: dict, **kwargs) -> str:
    """List downloaded models, optionally filtered by search string."""
    search = (args.get("search") or "").lower().strip()
    try:
        client = _get_sdk_client()
        downloaded = list(client.llm.list_downloaded())
        models = []
        for m in downloaded:
            path = m.path if hasattr(m, "path") else str(m)
            if search and search not in path.lower():
                continue
            models.append({"path": path})

        return json.dumps({"models": models, "count": len(models)}, ensure_ascii=False)

    except Exception as e:
        # Fallback: HTTP API
        try:
            import httpx
            r = httpx.get(f"{_LMS_HTTP_BASE}/v1/models", timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                models = []
                for m in data.get("data", []):
                    mid = m.get("id", "")
                    if search and search not in mid.lower():
                        continue
                    models.append({"path": mid})
                return json.dumps({"models": models, "count": len(models)}, ensure_ascii=False)
        except Exception:
            pass
        return json.dumps({"error": f"Failed to list models: {e}"})


# ---------------------------------------------------------------------------
# Tool: lm_studio_load
# ---------------------------------------------------------------------------
def lm_studio_load_handler(args: dict, **kwargs) -> str:
    """Load a model into LM Studio with GPU isolation (AgentNate pattern)."""
    model_path = args.get("model_path", "").strip()
    if not model_path:
        return json.dumps({"error": "model_path is required"})

    context_length = int(args.get("context_length", 4096))
    placement, problem = _gpu_placement_for(args)
    if problem:
        return json.dumps({"error": problem})

    if not _HAS_SDK:
        return json.dumps({"error": "lmstudio SDK not installed (pip install lmstudio)"})

    try:
        client = _get_sdk_client()

        # Same placement rules and nvidia-smi -> LM Studio GPU mapping as the
        # GUI's LM Studio panel and sidebar auto-load.
        from portable_hermes import lmstudio_gpu as gpu_place
        needs_gpus = placement not in (gpu_place.AUTO, gpu_place.CPU)
        nvidia = gpu_place.list_nvidia_gpus() if needs_gpus else []
        if placement.startswith("gpu:") and not nvidia:
            logger.warning("No GPUs detected, ignoring gpu_index (%s)", placement)
            placement = gpu_place.AUTO
        try:
            plan = gpu_place.plan(placement, nvidia=nvidia)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        gpu_config = GpuSetting(**plan.gpu) if plan.gpu else None
        logger.info("GPU placement %s -> %r (LM Studio GPU %r, mapping %s)",
                    plan.placement, plan.gpu, plan.lmstudio_gpu, plan.mapping)

        # Build load config
        load_config = LlmLoadModelConfig(
            gpu=gpu_config,
            context_length=context_length,
            **plan.load,
        )

        # No instance identifier: LM Studio names the instance after the model
        # key ("key:2" for a second copy), like the GUI's LM Studio panel, so
        # the agent and the user see the real model name. Report the id LM
        # Studio actually used; chat/unload/info take that id.
        logger.info("Loading model via SDK: %s", model_path)

        handle = client.llm.load_new_instance(
            model_path,
            config=load_config,
            ttl=3600,  # 1 hour auto-unload
        )
        instance_id = getattr(handle, "identifier", None)
        if not isinstance(instance_id, str) or not instance_id:
            instance_id = model_path

        # Store handle for later unload
        _sdk_handles[instance_id] = handle

        return json.dumps({
            "loaded": True,
            "model": model_path,
            "identifier": instance_id,
            "context_length": context_length,
            "gpu_index": int(plan.placement[4:]) if plan.placement.startswith("gpu:") else None,
            "gpu_placement": plan.placement,
            "lmstudio_gpu": plan.lmstudio_gpu,
            "gpu_mapping": plan.mapping,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Failed to load model: {e}"})


# ---------------------------------------------------------------------------
# Tool: lm_studio_unload
# ---------------------------------------------------------------------------
def lm_studio_unload_handler(args: dict, **kwargs) -> str:
    """Unload a model from LM Studio."""
    model_id = args.get("model_id", "").strip()
    if not model_id:
        return json.dumps({"error": "model_id is required"})

    # Try stored handle first (fast path, matches AgentNate)
    handle = _sdk_handles.pop(model_id, None)
    if handle is not None:
        try:
            handle.unload()
            return json.dumps({"unloaded": True, "model_id": model_id}, ensure_ascii=False)
        except Exception as e:
            logger.warning("Handle unload failed for %s: %s", model_id, e)

    # Fallback: find by identifier via SDK and unload
    try:
        client = _get_sdk_client()
        loaded = list(client.llm.list_loaded())
        for m in loaded:
            ident = getattr(m, "identifier", "") or ""
            m_path = getattr(m, "path", "") or ""
            if model_id in ident or model_id.lower() in m_path.lower():
                m.unload()
                return json.dumps({
                    "unloaded": True,
                    "model_id": model_id,
                    "matched": ident,
                }, ensure_ascii=False)

        return json.dumps({"error": f"Model '{model_id}' not found in loaded models"})

    except Exception as e:
        return json.dumps({"error": f"Failed to unload model: {e}"})


# ---------------------------------------------------------------------------
# Tool: lm_studio_search
# ---------------------------------------------------------------------------
def lm_studio_search_handler(args: dict, **kwargs) -> str:
    """Search HuggingFace for models to download via LM Studio SDK."""
    query = args.get("query", "").strip()
    if not query:
        return json.dumps({"error": "query is required"})

    limit = min(int(args.get("limit", 10)), 20)

    if not _HAS_SDK:
        return json.dumps({"error": "lmstudio SDK not installed"})

    try:
        client = _get_sdk_client()
        results = list(client.repository.search_models(query, limit=limit))

        models = []
        for r in results:
            entry = {"result": str(r.search_result)}
            try:
                options = list(r.get_download_options())
                entry["download_options"] = [str(o.info) for o in options]
            except Exception:
                entry["download_options"] = []
            models.append(entry)

        return json.dumps({"query": query, "results": models, "count": len(models)}, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Search failed: {e}"})


# ---------------------------------------------------------------------------
# Tool: lm_studio_download
# ---------------------------------------------------------------------------
def lm_studio_download_handler(args: dict, **kwargs) -> str:
    """Download a model from HuggingFace via LM Studio SDK."""
    query = args.get("query", "").strip()
    if not query:
        return json.dumps({"error": "query is required"})

    option_index = int(args.get("option_index", 0))

    if not _HAS_SDK:
        return json.dumps({"error": "lmstudio SDK not installed"})

    try:
        client = _get_sdk_client()
        results = list(client.repository.search_models(query, limit=1))
        if not results:
            return json.dumps({"error": f"No models found for '{query}'"})

        options = list(results[0].get_download_options())
        if not options:
            return json.dumps({"error": "No download options available"})

        if option_index >= len(options):
            return json.dumps({
                "error": f"option_index {option_index} out of range (0-{len(options)-1})",
                "available_options": [str(o.info) for o in options],
            })

        selected = options[option_index]
        logger.info("Downloading: %s", selected.info)
        selected.download()

        return json.dumps({
            "downloaded": True,
            "model": str(results[0].search_result),
            "option": str(selected.info),
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Download failed: {e}"})


# ---------------------------------------------------------------------------
# Tool: lm_studio_model_info
# ---------------------------------------------------------------------------
def lm_studio_model_info_handler(args: dict, **kwargs) -> str:
    """Get detailed info about a loaded model (context length, config)."""
    model_id = (args.get("model_id") or "").strip()

    try:
        client = _get_sdk_client()
        loaded = list(client.llm.list_loaded())

        if not loaded:
            return json.dumps({"error": "No models loaded"})

        # If model_id given, find it; otherwise return first
        target = None
        for m in loaded:
            ident = getattr(m, "identifier", "") or ""
            m_path = getattr(m, "path", "") or ""
            if not model_id or model_id in ident or model_id.lower() in m_path.lower():
                target = m
                break

        if target is None:
            return json.dumps({"error": f"Model '{model_id}' not found in loaded models"})

        info = {}
        try:
            info["identifier"] = target.identifier
        except Exception:
            pass
        try:
            info["info"] = str(target.get_info())
        except Exception:
            pass
        try:
            info["context_length"] = target.get_context_length()
        except Exception:
            pass
        try:
            config = target.get_load_config()
            info["load_config"] = str(config)
        except Exception:
            pass

        return json.dumps(info, ensure_ascii=False)

    except Exception as e:
        # Fallback: try native API
        try:
            import httpx
            r = httpx.get(f"{_LMS_HTTP_BASE}/api/v0/models", timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                models = data if isinstance(data, list) else data.get("data", [])
                for m in models:
                    mid = m.get("id", m.get("path", ""))
                    if not model_id or model_id.lower() in mid.lower():
                        return json.dumps({
                            "identifier": mid,
                            "context_length": m.get("max_context_length"),
                            "quantization": m.get("quantization"),
                            "state": m.get("state"),
                        }, ensure_ascii=False)
        except Exception:
            pass
        return json.dumps({"error": f"Failed to get model info: {e}"})


# ---------------------------------------------------------------------------
# Tool: lm_studio_tokenize
# ---------------------------------------------------------------------------
def lm_studio_tokenize_handler(args: dict, **kwargs) -> str:
    """Count tokens or tokenize text using a loaded model."""
    text = args.get("text", "")
    if not text:
        return json.dumps({"error": "text is required"})

    model_id = (args.get("model_id") or "").strip()
    show_tokens = args.get("show_tokens", False)

    if not _HAS_SDK:
        return json.dumps({"error": "lmstudio SDK not installed"})

    try:
        client = _get_sdk_client()
        loaded = list(client.llm.list_loaded())
        if not loaded:
            return json.dumps({"error": "No models loaded — load a model first"})

        # Find target model
        target = None
        for m in loaded:
            ident = getattr(m, "identifier", "") or ""
            m_path = getattr(m, "path", "") or ""
            if not model_id or model_id in ident or model_id.lower() in m_path.lower():
                target = m
                break

        if target is None:
            target = loaded[0]

        result = {"model": target.identifier}
        result["token_count"] = target.count_tokens(text)

        if show_tokens:
            tokens = target.tokenize(text)
            result["tokens"] = tokens

        try:
            result["context_length"] = target.get_context_length()
        except Exception:
            pass

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Tokenize failed: {e}"})


# ---------------------------------------------------------------------------
# Tool: lm_studio_embed
# ---------------------------------------------------------------------------
def lm_studio_embed_handler(args: dict, **kwargs) -> str:
    """Generate embeddings for text using LM Studio or OpenRouter."""
    text = args.get("text")
    if not text:
        return json.dumps({"error": "text is required"})

    model = (args.get("model") or "").strip()

    # Normalize input to list
    if isinstance(text, str):
        inputs = [text]
    elif isinstance(text, list):
        inputs = text
    else:
        inputs = [str(text)]

    try:
        import httpx

        # Use the same base URL as LM Studio / OpenRouter
        base_url = _LMS_HTTP_BASE
        payload = {"input": inputs}
        if model:
            payload["model"] = model

        r = httpx.post(
            f"{base_url}/v1/embeddings",
            json=payload,
            timeout=30.0,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"Embeddings failed ({r.status_code}): {r.text[:500]}"})

        data = r.json()
        embeddings = data.get("data", [])

        result = {
            "model": data.get("model", model or "default"),
            "count": len(embeddings),
            "dimensions": len(embeddings[0]["embedding"]) if embeddings else 0,
            "embeddings": [
                {
                    "index": e.get("index", i),
                    "embedding": e["embedding"][:5] + ["..."],  # Truncate for display
                    "full_length": len(e["embedding"]),
                }
                for i, e in enumerate(embeddings)
            ],
        }
        # Include full embeddings if requested
        if args.get("full", False):
            result["full_embeddings"] = [e["embedding"] for e in embeddings]

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Embeddings failed: {e}"})


# ---------------------------------------------------------------------------
# Tool: lm_studio_chat (direct inference)
# ---------------------------------------------------------------------------
def lm_studio_chat_handler(args: dict, **kwargs) -> str:
    """Send a chat message directly to LM Studio for inference."""
    prompt = args.get("prompt", "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"})

    model = (args.get("model") or "").strip()
    max_tokens = int(args.get("max_tokens", 1024))
    temperature = float(args.get("temperature", 0.7))
    system = args.get("system", "")

    try:
        import httpx

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if model:
            payload["model"] = model

        r = httpx.post(
            f"{_LMS_HTTP_BASE}/v1/chat/completions",
            json=payload,
            timeout=120.0,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"Chat failed ({r.status_code}): {r.text[:500]}"})

        data = r.json()
        choices = data.get("choices", [])
        if not choices:
            return json.dumps({"error": "No response from model"})

        choice = choices[0]
        usage = data.get("usage", {})

        return json.dumps({
            "response": choice.get("message", {}).get("content", ""),
            "model": data.get("model", model),
            "finish_reason": choice.get("finish_reason"),
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Chat failed: {e}"})


# ===========================================================================
# Schemas & Registration
# ===========================================================================

EMBED_SCHEMA = {
    "name": "lm_studio_embed",
    "description": (
        "Generate text embeddings using LM Studio or OpenRouter. "
        "Works with any loaded embedding model (e.g. nomic-embed-text). "
        "Input can be a single string or array of strings."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to embed. For multiple texts, separate with newlines.",
            },
            "model": {
                "type": "string",
                "description": "Embedding model to use. Omit for default loaded model.",
            },
            "full": {
                "type": "boolean",
                "description": "If true, return full embedding vectors (default false, returns truncated preview).",
            },
        },
        "required": ["text"],
    },
}

CHAT_SCHEMA = {
    "name": "lm_studio_chat",
    "description": (
        "Send a prompt directly to LM Studio for inference. "
        "Useful for quick one-off queries to a loaded local model "
        "without affecting the main conversation. "
        "Works with any loaded LLM."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The user prompt to send.",
            },
            "model": {
                "type": "string",
                "description": "Model to use. Omit for default loaded model.",
            },
            "system": {
                "type": "string",
                "description": "Optional system message.",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Max tokens in response (default 1024).",
            },
            "temperature": {
                "type": "number",
                "description": "Sampling temperature (default 0.7).",
            },
        },
        "required": ["prompt"],
    },
}

SEARCH_SCHEMA = {
    "name": "lm_studio_search",
    "description": (
        "Search HuggingFace for GGUF models available to download in LM Studio. "
        "Returns model names and available quantization options (Q4_K_M, Q8_0, etc.). "
        "Use lm_studio_download to download a found model."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g. 'llama 3.1 8b', 'phi-4', 'qwen 2.5 coder').",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 10, max 20).",
            },
        },
        "required": ["query"],
    },
}

DOWNLOAD_SCHEMA = {
    "name": "lm_studio_download",
    "description": (
        "Download a model from HuggingFace into LM Studio. "
        "First use lm_studio_search to find the model and see available quantizations, "
        "then specify the query and option_index to download."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query that matches the model to download.",
            },
            "option_index": {
                "type": "integer",
                "description": "Index of the quantization option to download (default 0 = first option).",
            },
        },
        "required": ["query"],
    },
}

MODEL_INFO_SCHEMA = {
    "name": "lm_studio_model_info",
    "description": (
        "Get detailed info about a loaded model: context length, load config, "
        "quantization. Omit model_id to get info on the first loaded model."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model_id": {
                "type": "string",
                "description": "Identifier or partial name of the loaded model. Omit for first loaded model.",
            },
        },
    },
}

TOKENIZE_SCHEMA = {
    "name": "lm_studio_tokenize",
    "description": (
        "Count tokens in text using a loaded model's tokenizer. "
        "Useful for checking if text fits within context length. "
        "Optionally returns the raw token IDs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to tokenize.",
            },
            "model_id": {
                "type": "string",
                "description": "Loaded model to use for tokenization. Omit for first loaded model.",
            },
            "show_tokens": {
                "type": "boolean",
                "description": "If true, also return the raw token ID array (default false).",
            },
        },
        "required": ["text"],
    },
}

STATUS_SCHEMA = {
    "name": "lm_studio_status",
    "description": (
        "Check LM Studio status: whether it's running, which models are loaded, "
        "and GPU memory availability. Use this to verify LM Studio is ready before "
        "loading or switching models."
    ),
    "parameters": {"type": "object", "properties": {}},
}

MODELS_SCHEMA = {
    "name": "lm_studio_models",
    "description": (
        "List all models downloaded in LM Studio. Optionally filter by a search "
        "string to find specific models. Returns model paths that can be used "
        "with lm_studio_load."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": "Optional filter string to match against model paths (case-insensitive).",
            },
        },
    },
}

LOAD_SCHEMA = {
    "name": "lm_studio_load",
    "description": (
        "Load a model into LM Studio. Specify the model path (from lm_studio_models), "
        "where to place it, and context length. Placement: gpu_index pins the model "
        "to one GPU (other GPUs disabled); gpu_mode 'split' spreads it across all "
        "GPUs, filling the largest first; 'cpu' keeps it off the GPUs; 'auto' (the "
        "default) lets LM Studio decide. lm_studio_status lists the GPUs with free VRAM."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model_path": {
                "type": "string",
                "description": "Full model path as returned by lm_studio_models.",
            },
            "gpu_index": {
                "type": "integer",
                "description": (
                    "GPU to load the model on, by the index lm_studio_status and "
                    "nvidia-smi show (0-based). Disables the other GPUs. "
                    "Do not combine with gpu_mode."
                ),
            },
            "gpu_mode": {
                "type": "string",
                "enum": list(_GPU_MODES),
                "description": (
                    "Placement when no gpu_index is given: 'auto' (LM Studio decides, "
                    "default), 'cpu' (no GPU offload), 'split' (all GPUs, largest first)."
                ),
            },
            "context_length": {
                "type": "integer",
                "description": "Context window size (default 4096).",
            },
        },
        "required": ["model_path"],
    },
}

UNLOAD_SCHEMA = {
    "name": "lm_studio_unload",
    "description": (
        "Unload a model from LM Studio to free GPU memory. "
        "Use lm_studio_status to see currently loaded model identifiers."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model_id": {
                "type": "string",
                "description": "Identifier of the loaded model to unload (from lm_studio_status).",
            },
        },
        "required": ["model_id"],
    },
}

registry.register(
    name="lm_studio_status",
    toolset="lm_studio",
    schema=STATUS_SCHEMA,
    handler=lm_studio_status_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_models",
    toolset="lm_studio",
    schema=MODELS_SCHEMA,
    handler=lm_studio_models_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_load",
    toolset="lm_studio",
    schema=LOAD_SCHEMA,
    handler=lm_studio_load_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_unload",
    toolset="lm_studio",
    schema=UNLOAD_SCHEMA,
    handler=lm_studio_unload_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_search",
    toolset="lm_studio",
    schema=SEARCH_SCHEMA,
    handler=lm_studio_search_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_download",
    toolset="lm_studio",
    schema=DOWNLOAD_SCHEMA,
    handler=lm_studio_download_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_model_info",
    toolset="lm_studio",
    schema=MODEL_INFO_SCHEMA,
    handler=lm_studio_model_info_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_tokenize",
    toolset="lm_studio",
    schema=TOKENIZE_SCHEMA,
    handler=lm_studio_tokenize_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_embed",
    toolset="lm_studio",
    schema=EMBED_SCHEMA,
    handler=lm_studio_embed_handler,
    check_fn=_check_lm_studio,
)
registry.register(
    name="lm_studio_chat",
    toolset="lm_studio",
    schema=CHAT_SCHEMA,
    handler=lm_studio_chat_handler,
    check_fn=_check_lm_studio,
)
