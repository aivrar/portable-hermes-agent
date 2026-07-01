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
import shutil
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
    return "http://localhost:8100"


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


def _get_gpu_count() -> int:
    """Detect number of NVIDIA GPUs."""
    if not shutil.which("nvidia-smi"):
        return 0
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        return len(r.stdout.strip().splitlines()) if r.returncode == 0 else 0
    except Exception:
        return 0


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

    gpu_index = args.get("gpu_index")
    context_length = int(args.get("context_length", 4096))

    if not _HAS_SDK:
        return json.dumps({"error": "lmstudio SDK not installed (pip install lmstudio)"})

    try:
        client = _get_sdk_client()

        # Build GPU config for single-GPU loading (matches AgentNate exactly)
        gpu_config = None
        if gpu_index is not None:
            gpu_index = int(gpu_index)
            num_gpus = _get_gpu_count()

            if num_gpus == 0:
                logger.warning("No GPUs detected, ignoring gpu_index=%d", gpu_index)
            elif gpu_index >= num_gpus:
                return json.dumps({
                    "error": f"GPU {gpu_index} requested but only {num_gpus} GPU(s) available (0-{num_gpus-1})"
                })
            else:
                # Disable all other GPUs to force single-GPU loading
                disabled_gpus = [i for i in range(num_gpus) if i != gpu_index]
                gpu_config = GpuSetting(
                    main_gpu=gpu_index,
                    disabled_gpus=disabled_gpus,
                    ratio=1.0,
                )
                logger.info("GPU config: main_gpu=%d, disabled=%s", gpu_index, disabled_gpus)

        # Build load config
        load_config = LlmLoadModelConfig(
            gpu=gpu_config,
            context_length=context_length,
        )

        # Generate instance identifier (matches AgentNate's naming)
        instance_id = f"hermes-{int(time.time())}"

        logger.info("Loading model via SDK: %s (instance: %s)", model_path, instance_id)

        handle = client.llm.load_new_instance(
            model_path,
            instance_id,
            config=load_config,
            ttl=3600,  # 1 hour auto-unload
        )

        # Store handle for later unload
        _sdk_handles[instance_id] = handle

        return json.dumps({
            "loaded": True,
            "model": model_path,
            "identifier": instance_id,
            "context_length": context_length,
            "gpu_index": gpu_index,
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
        "optional GPU index for multi-GPU systems, and context length. "
        "Check gpu_info first to see available VRAM. "
        "Uses the LM Studio SDK with proper GPU isolation (disables other GPUs "
        "to prevent model splitting)."
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
                "description": "GPU index to load the model on (0-based). Disables other GPUs to prevent splitting.",
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

_ALL_SCHEMAS = [
    STATUS_SCHEMA, MODELS_SCHEMA, LOAD_SCHEMA, UNLOAD_SCHEMA,
    SEARCH_SCHEMA, DOWNLOAD_SCHEMA, MODEL_INFO_SCHEMA, TOKENIZE_SCHEMA,
    EMBED_SCHEMA, CHAT_SCHEMA,
]

_ALL_HANDLERS = {
    "lm_studio_status": lm_studio_status_handler,
    "lm_studio_models": lm_studio_models_handler,
    "lm_studio_load": lm_studio_load_handler,
    "lm_studio_unload": lm_studio_unload_handler,
    "lm_studio_search": lm_studio_search_handler,
    "lm_studio_download": lm_studio_download_handler,
    "lm_studio_model_info": lm_studio_model_info_handler,
    "lm_studio_tokenize": lm_studio_tokenize_handler,
    "lm_studio_embed": lm_studio_embed_handler,
    "lm_studio_chat": lm_studio_chat_handler,
}

for schema in _ALL_SCHEMAS:
    registry.register(
        name=schema["name"],
        toolset="lm_studio",
        schema=schema,
        handler=_ALL_HANDLERS[schema["name"]],
        check_fn=_check_lm_studio,
    )
