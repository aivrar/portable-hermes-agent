#!/usr/bin/env python3
"""
Extension Tools — Music Server, TTS Server, and ComfyUI REST APIs.

Uses httpx to call local extension servers directly (no bash/curl).
Audio files are saved to ~/.hermes/audio_cache/ and file paths returned.

Each server has its own check_fn so tools only appear when their
respective service is running.

Toolsets: music, extension_tts, comfyui
"""

import datetime
import json
import logging
import os
from pathlib import Path

from tools.registry import registry

logger = logging.getLogger(__name__)

_MUSIC_BASE = os.getenv("MUSIC_SERVER_URL", "http://localhost:9150").rstrip("/")
_TTS_BASE = os.getenv("TTS_SERVER_URL", "http://localhost:8200").rstrip("/")
_COMFYUI_BASE = os.getenv("COMFYUI_URL", "http://localhost:8188").rstrip("/")

_HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
_AUDIO_CACHE = _HERMES_HOME / "audio_cache"


def _ensure_audio_cache() -> Path:
    _AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    return _AUDIO_CACHE


# ===========================================================================
# Health checks
# ===========================================================================
def _check_music_server() -> bool:
    try:
        import httpx
        r = httpx.get(f"{_MUSIC_BASE}/api/models/status", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _check_tts_server() -> bool:
    try:
        import httpx
        r = httpx.get(f"{_TTS_BASE}/api/models/status", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _check_comfyui() -> bool:
    try:
        import httpx
        # ComfyUI uses /system_stats or /queue as health endpoints
        r = httpx.get(f"{_COMFYUI_BASE}/system_stats", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


# ===========================================================================
# Music Tools
# ===========================================================================
def music_status_handler(args: dict, **kwargs) -> str:
    """Get music server status and available models."""
    try:
        import httpx
        r = httpx.get(f"{_MUSIC_BASE}/api/models/status", timeout=5.0)
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Music server unreachable: {e}"})


def music_generate_handler(args: dict, **kwargs) -> str:
    """Generate music from a text prompt."""
    prompt = args.get("prompt", "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"})

    model = args.get("model", "musicgen").strip()
    duration = min(int(args.get("duration", 30)), 300)

    try:
        import httpx
        r = httpx.post(
            f"{_MUSIC_BASE}/api/music/{model}",
            json={"prompt": prompt, "duration": duration},
            timeout=180.0,  # music generation can be slow
        )
        if r.status_code != 200:
            return json.dumps({"error": f"Music generation failed ({r.status_code}): {r.text[:500]}"})

        # Save audio to disk
        cache = _ensure_audio_cache()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # Determine extension from content-type
        ct = r.headers.get("content-type", "")
        ext = ".wav" if "wav" in ct else ".mp3" if "mp3" in ct else ".audio"
        file_path = cache / f"music_{timestamp}{ext}"
        file_path.write_bytes(r.content)

        return json.dumps({
            "file_path": str(file_path),
            "duration": duration,
            "model": model,
            "prompt": prompt,
            "media_tag": f"MEDIA:{file_path}",
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Music generation failed: {e}"})


# ===========================================================================
# TTS Server Tools (extension_tts — distinct from Edge TTS 'tts' toolset)
# ===========================================================================
def tts_server_status_handler(args: dict, **kwargs) -> str:
    """Get TTS server status and available models/voices."""
    try:
        import httpx
        r = httpx.get(f"{_TTS_BASE}/api/models/status", timeout=5.0)
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"TTS server unreachable: {e}"})


def tts_server_generate_handler(args: dict, **kwargs) -> str:
    """Generate speech audio via the local TTS server."""
    text = args.get("text", "").strip()
    if not text:
        return json.dumps({"error": "text is required"})

    model = args.get("model", "kokoro").strip()
    voice = args.get("voice")

    try:
        import httpx
        payload = {"text": text}
        if voice:
            payload["voice"] = voice

        r = httpx.post(
            f"{_TTS_BASE}/api/tts/{model}",
            json=payload,
            timeout=60.0,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"TTS generation failed ({r.status_code}): {r.text[:500]}"})

        # Save audio to disk
        cache = _ensure_audio_cache()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        ct = r.headers.get("content-type", "")
        ext = ".wav" if "wav" in ct else ".ogg" if "ogg" in ct else ".mp3"
        file_path = cache / f"tts_ext_{timestamp}{ext}"
        file_path.write_bytes(r.content)

        return json.dumps({
            "file_path": str(file_path),
            "model": model,
            "voice": voice,
            "media_tag": f"MEDIA:{file_path}",
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"TTS generation failed: {e}"})


# ===========================================================================
# ComfyUI Tools
# ===========================================================================
def comfyui_status_handler(args: dict, **kwargs) -> str:
    """Get ComfyUI server status and system info."""
    try:
        import httpx
        r = httpx.get(f"{_COMFYUI_BASE}/system_stats", timeout=5.0)
        if r.status_code != 200:
            return json.dumps({"error": f"ComfyUI returned status {r.status_code}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"ComfyUI unreachable: {e}"})


# ===========================================================================
# Music Model Management Tools
# ===========================================================================
def music_models_handler(args: dict, **kwargs) -> str:
    """List available music models with their load/install status."""
    try:
        import httpx
        r = httpx.get(f"{_MUSIC_BASE}/api/models", timeout=5.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Music server returned {r.status_code}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Music server unreachable: {e}"})


def music_model_load_handler(args: dict, **kwargs) -> str:
    """Load (spawn worker for) a music model."""
    model = args.get("model", "").strip()
    if not model:
        return json.dumps({"error": "model is required"})
    try:
        import httpx
        r = httpx.post(f"{_MUSIC_BASE}/api/models/{model}/load", json={}, timeout=60.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Load failed ({r.status_code}): {r.text[:500]}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to load music model: {e}"})


def music_model_unload_handler(args: dict, **kwargs) -> str:
    """Unload a music model to free GPU memory."""
    model = args.get("model", "").strip()
    if not model:
        return json.dumps({"error": "model is required"})
    try:
        import httpx
        r = httpx.post(f"{_MUSIC_BASE}/api/models/{model}/unload", json={}, timeout=30.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Unload failed ({r.status_code}): {r.text[:500]}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to unload music model: {e}"})


def music_outputs_handler(args: dict, **kwargs) -> str:
    """List generated music from the output library."""
    try:
        import httpx
        r = httpx.get(f"{_MUSIC_BASE}/api/outputs", timeout=5.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Failed to list outputs ({r.status_code})"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to list music outputs: {e}"})


def music_install_handler(args: dict, **kwargs) -> str:
    """Install a music model (download weights + create venv)."""
    model = args.get("model", "").strip()
    if not model:
        return json.dumps({"error": "model is required"})
    try:
        import httpx
        r = httpx.post(f"{_MUSIC_BASE}/api/install/{model}", json={}, timeout=600.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Install failed ({r.status_code}): {r.text[:500]}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to install music model: {e}"})


# ===========================================================================
# TTS Model Management Tools
# ===========================================================================
def tts_server_models_handler(args: dict, **kwargs) -> str:
    """List available TTS models with their load status."""
    try:
        import httpx
        r = httpx.get(f"{_TTS_BASE}/api/models", timeout=5.0)
        if r.status_code != 200:
            return json.dumps({"error": f"TTS server returned {r.status_code}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"TTS server unreachable: {e}"})


def tts_server_model_load_handler(args: dict, **kwargs) -> str:
    """Load a TTS model (spawn worker)."""
    model = args.get("model", "").strip()
    if not model:
        return json.dumps({"error": "model is required"})
    try:
        import httpx
        r = httpx.post(f"{_TTS_BASE}/api/models/{model}/load", json={}, timeout=60.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Load failed ({r.status_code}): {r.text[:500]}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to load TTS model: {e}"})


def tts_server_model_unload_handler(args: dict, **kwargs) -> str:
    """Unload a TTS model to free GPU memory."""
    model = args.get("model", "").strip()
    if not model:
        return json.dumps({"error": "model is required"})
    try:
        import httpx
        r = httpx.post(f"{_TTS_BASE}/api/models/{model}/unload", json={}, timeout=30.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Unload failed ({r.status_code}): {r.text[:500]}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to unload TTS model: {e}"})


def tts_server_voices_handler(args: dict, **kwargs) -> str:
    """List available voices for a TTS model."""
    model = args.get("model", "kokoro").strip()
    try:
        import httpx
        r = httpx.get(f"{_TTS_BASE}/api/tts/{model}/voices", timeout=5.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Failed to get voices ({r.status_code}): {r.text[:500]}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to list voices: {e}"})


def tts_server_jobs_handler(args: dict, **kwargs) -> str:
    """List TTS generation jobs."""
    try:
        import httpx
        r = httpx.get(f"{_TTS_BASE}/api/jobs", timeout=5.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Failed to list jobs ({r.status_code})"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to list TTS jobs: {e}"})


# ===========================================================================
# ComfyUI Management Tools
# ===========================================================================
_COMFYUI_MGMT_BASE = "http://localhost:5000"


def _check_comfyui_mgmt() -> bool:
    """Check if ComfyUI management API is reachable."""
    try:
        import httpx
        r = httpx.get(f"{_COMFYUI_MGMT_BASE}/api/instances", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def comfyui_instances_handler(args: dict, **kwargs) -> str:
    """List all ComfyUI instances with status, GPU, and port."""
    try:
        import httpx
        r = httpx.get(f"{_COMFYUI_MGMT_BASE}/api/instances", timeout=5.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Management API returned {r.status_code}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"ComfyUI management API unreachable: {e}"})


def comfyui_instance_start_handler(args: dict, **kwargs) -> str:
    """Start a ComfyUI instance."""
    instance_id = args.get("instance_id", "").strip()
    if not instance_id:
        return json.dumps({"error": "instance_id is required"})
    try:
        import httpx
        r = httpx.post(
            f"{_COMFYUI_MGMT_BASE}/api/instances/{instance_id}/start",
            json={}, timeout=30.0,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"Start failed ({r.status_code}): {r.text[:500]}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to start instance: {e}"})


def comfyui_instance_stop_handler(args: dict, **kwargs) -> str:
    """Stop a ComfyUI instance."""
    instance_id = args.get("instance_id", "").strip()
    if not instance_id:
        return json.dumps({"error": "instance_id is required"})
    try:
        import httpx
        r = httpx.post(
            f"{_COMFYUI_MGMT_BASE}/api/instances/{instance_id}/stop",
            json={}, timeout=30.0,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"Stop failed ({r.status_code}): {r.text[:500]}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to stop instance: {e}"})


def comfyui_generate_handler(args: dict, **kwargs) -> str:
    """Generate an image via ComfyUI simple generation endpoint."""
    prompt = args.get("prompt", "").strip()
    if not prompt:
        return json.dumps({"error": "prompt is required"})

    instance_id = args.get("instance_id", "")
    checkpoint = args.get("checkpoint", "")
    negative_prompt = args.get("negative_prompt", "")
    width = int(args.get("width", 512))
    height = int(args.get("height", 512))
    steps = int(args.get("steps", 20))
    cfg = float(args.get("cfg", 7.0))

    try:
        import httpx
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg": cfg,
        }
        if instance_id:
            payload["instance_id"] = instance_id
        if checkpoint:
            payload["checkpoint"] = checkpoint

        r = httpx.post(
            f"{_COMFYUI_MGMT_BASE}/generate",
            json=payload, timeout=300.0,
        )
        if r.status_code != 200:
            return json.dumps({"error": f"Generate failed ({r.status_code}): {r.text[:500]}"})

        result = r.json()

        # If we got image data, save it
        if "image" in result or "images" in result:
            return json.dumps(result, ensure_ascii=False)

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Image generation failed: {e}"})


def comfyui_models_handler(args: dict, **kwargs) -> str:
    """List available ComfyUI models (checkpoints, loras, etc.)."""
    category = args.get("category", "")
    try:
        import httpx
        url = f"{_COMFYUI_MGMT_BASE}/api/models/local"
        if category:
            url += f"?category={category}"
        r = httpx.get(url, timeout=10.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Failed to list models ({r.status_code})"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to list ComfyUI models: {e}"})


def comfyui_nodes_handler(args: dict, **kwargs) -> str:
    """List installed ComfyUI custom nodes."""
    try:
        import httpx
        r = httpx.get(f"{_COMFYUI_MGMT_BASE}/api/nodes/installed", timeout=5.0)
        if r.status_code != 200:
            return json.dumps({"error": f"Failed to list nodes ({r.status_code})"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to list custom nodes: {e}"})


# ===========================================================================
# Schemas & Registration
# ===========================================================================

# --- Music ---
MUSIC_STATUS_SCHEMA = {
    "name": "music_status",
    "description": "Check music generation server status and available models (musicgen, etc.).",
    "parameters": {"type": "object", "properties": {}},
}

MUSIC_GENERATE_SCHEMA = {
    "name": "music_generate",
    "description": (
        "Generate music from a text prompt using the local music server. "
        "Returns a file path to the generated audio. Supports models like musicgen. "
        "Duration in seconds (default 30, max 300)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text description of the music to generate.",
            },
            "model": {
                "type": "string",
                "description": "Music model to use (default: 'musicgen').",
            },
            "duration": {
                "type": "integer",
                "description": "Duration in seconds (default 30, max 300).",
            },
        },
        "required": ["prompt"],
    },
}

registry.register(
    name="music_status",
    toolset="music",
    schema=MUSIC_STATUS_SCHEMA,
    handler=music_status_handler,
    check_fn=_check_music_server,
)

registry.register(
    name="music_generate",
    toolset="music",
    schema=MUSIC_GENERATE_SCHEMA,
    handler=music_generate_handler,
    check_fn=_check_music_server,
)

# --- Extension TTS ---
TTS_SERVER_STATUS_SCHEMA = {
    "name": "tts_server_status",
    "description": (
        "Check the local TTS server status and available models/voices "
        "(Kokoro, etc.). This is the local high-quality TTS server, "
        "separate from the built-in Edge TTS tool."
    ),
    "parameters": {"type": "object", "properties": {}},
}

TTS_SERVER_GENERATE_SCHEMA = {
    "name": "tts_server_generate",
    "description": (
        "Generate speech using the local TTS server (Kokoro, etc.). "
        "Returns a file path to the audio. Separate from the built-in "
        "Edge TTS — this uses locally-running AI voice models."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to convert to speech.",
            },
            "model": {
                "type": "string",
                "description": "TTS model to use (default: 'kokoro').",
            },
            "voice": {
                "type": "string",
                "description": "Voice name/ID. Omit for server default.",
            },
        },
        "required": ["text"],
    },
}

registry.register(
    name="tts_server_status",
    toolset="extension_tts",
    schema=TTS_SERVER_STATUS_SCHEMA,
    handler=tts_server_status_handler,
    check_fn=_check_tts_server,
)

registry.register(
    name="tts_server_generate",
    toolset="extension_tts",
    schema=TTS_SERVER_GENERATE_SCHEMA,
    handler=tts_server_generate_handler,
    check_fn=_check_tts_server,
)

# --- ComfyUI ---
COMFYUI_STATUS_SCHEMA = {
    "name": "comfyui_status",
    "description": (
        "Check ComfyUI server status and system info (GPU memory, loaded models). "
        "Use this to verify ComfyUI is running before attempting image generation workflows."
    ),
    "parameters": {"type": "object", "properties": {}},
}

registry.register(
    name="comfyui_status",
    toolset="comfyui",
    schema=COMFYUI_STATUS_SCHEMA,
    handler=comfyui_status_handler,
    check_fn=_check_comfyui,
)

# --- Music Model Management ---
MUSIC_MODELS_SCHEMA = {
    "name": "music_models",
    "description": "List all available music generation models with their load/install status.",
    "parameters": {"type": "object", "properties": {}},
}

MUSIC_MODEL_LOAD_SCHEMA = {
    "name": "music_model_load",
    "description": (
        "Load a music model (spawn a GPU worker). "
        "Use music_models to see available models first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model name (e.g. 'musicgen', 'stable_audio', 'ace_step').",
            },
        },
        "required": ["model"],
    },
}

MUSIC_MODEL_UNLOAD_SCHEMA = {
    "name": "music_model_unload",
    "description": "Unload a music model to free GPU memory.",
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model name to unload.",
            },
        },
        "required": ["model"],
    },
}

MUSIC_OUTPUTS_SCHEMA = {
    "name": "music_outputs",
    "description": "List generated music in the output library.",
    "parameters": {"type": "object", "properties": {}},
}

MUSIC_INSTALL_SCHEMA = {
    "name": "music_install",
    "description": (
        "Install a music model (download weights + create venv). "
        "This can take a while. Use music_models to see what's available."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model name to install (e.g. 'musicgen', 'stable_audio').",
            },
        },
        "required": ["model"],
    },
}

for name, schema, handler in [
    ("music_models", MUSIC_MODELS_SCHEMA, music_models_handler),
    ("music_model_load", MUSIC_MODEL_LOAD_SCHEMA, music_model_load_handler),
    ("music_model_unload", MUSIC_MODEL_UNLOAD_SCHEMA, music_model_unload_handler),
    ("music_outputs", MUSIC_OUTPUTS_SCHEMA, music_outputs_handler),
    ("music_install", MUSIC_INSTALL_SCHEMA, music_install_handler),
]:
    registry.register(
        name=name, toolset="music", schema=schema,
        handler=handler, check_fn=_check_music_server,
    )

# --- TTS Model Management ---
TTS_SERVER_MODELS_SCHEMA = {
    "name": "tts_server_models",
    "description": (
        "List all available TTS models with their load status. "
        "Models: kokoro, xtts, dia, bark, fish, chatterbox, f5, qwen, vibevoice, higgs."
    ),
    "parameters": {"type": "object", "properties": {}},
}

TTS_SERVER_MODEL_LOAD_SCHEMA = {
    "name": "tts_server_model_load",
    "description": "Load a TTS model (spawn worker). Use tts_server_models to see available models.",
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model name (e.g. 'kokoro', 'xtts', 'dia', 'bark', 'fish').",
            },
        },
        "required": ["model"],
    },
}

TTS_SERVER_MODEL_UNLOAD_SCHEMA = {
    "name": "tts_server_model_unload",
    "description": "Unload a TTS model to free GPU memory.",
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model name to unload.",
            },
        },
        "required": ["model"],
    },
}

TTS_SERVER_VOICES_SCHEMA = {
    "name": "tts_server_voices",
    "description": (
        "List available voices for a TTS model. "
        "Use this to find voice names before generating speech."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "TTS model to list voices for (default: 'kokoro').",
            },
        },
    },
}

TTS_SERVER_JOBS_SCHEMA = {
    "name": "tts_server_jobs",
    "description": "List TTS generation jobs and their status.",
    "parameters": {"type": "object", "properties": {}},
}

for name, schema, handler in [
    ("tts_server_models", TTS_SERVER_MODELS_SCHEMA, tts_server_models_handler),
    ("tts_server_model_load", TTS_SERVER_MODEL_LOAD_SCHEMA, tts_server_model_load_handler),
    ("tts_server_model_unload", TTS_SERVER_MODEL_UNLOAD_SCHEMA, tts_server_model_unload_handler),
    ("tts_server_voices", TTS_SERVER_VOICES_SCHEMA, tts_server_voices_handler),
    ("tts_server_jobs", TTS_SERVER_JOBS_SCHEMA, tts_server_jobs_handler),
]:
    registry.register(
        name=name, toolset="extension_tts", schema=schema,
        handler=handler, check_fn=_check_tts_server,
    )

# --- ComfyUI Management ---
COMFYUI_INSTANCES_SCHEMA = {
    "name": "comfyui_instances",
    "description": "List all ComfyUI instances with their status, GPU assignment, and port.",
    "parameters": {"type": "object", "properties": {}},
}

COMFYUI_INSTANCE_START_SCHEMA = {
    "name": "comfyui_instance_start",
    "description": "Start a ComfyUI instance by ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "instance_id": {
                "type": "string",
                "description": "Instance ID from comfyui_instances.",
            },
        },
        "required": ["instance_id"],
    },
}

COMFYUI_INSTANCE_STOP_SCHEMA = {
    "name": "comfyui_instance_stop",
    "description": "Stop a running ComfyUI instance.",
    "parameters": {
        "type": "object",
        "properties": {
            "instance_id": {
                "type": "string",
                "description": "Instance ID to stop.",
            },
        },
        "required": ["instance_id"],
    },
}

COMFYUI_GENERATE_SCHEMA = {
    "name": "comfyui_generate",
    "description": (
        "Generate an image using ComfyUI. Provide a text prompt and optional settings. "
        "Use comfyui_instances to check which instances are running first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text prompt describing the image to generate.",
            },
            "instance_id": {
                "type": "string",
                "description": "ComfyUI instance ID to use. Omit for default.",
            },
            "checkpoint": {
                "type": "string",
                "description": "Checkpoint/model name to use. Omit for default.",
            },
            "negative_prompt": {
                "type": "string",
                "description": "Negative prompt (things to avoid).",
            },
            "width": {
                "type": "integer",
                "description": "Image width in pixels (default 512).",
            },
            "height": {
                "type": "integer",
                "description": "Image height in pixels (default 512).",
            },
            "steps": {
                "type": "integer",
                "description": "Sampling steps (default 20).",
            },
            "cfg": {
                "type": "number",
                "description": "CFG scale / guidance strength (default 7.0).",
            },
        },
        "required": ["prompt"],
    },
}

COMFYUI_MODELS_SCHEMA = {
    "name": "comfyui_models",
    "description": (
        "List locally installed ComfyUI models (checkpoints, LoRAs, VAEs, etc.). "
        "Optionally filter by category."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filter by category (e.g. 'checkpoints', 'loras', 'vae'). Omit for all.",
            },
        },
    },
}

COMFYUI_NODES_SCHEMA = {
    "name": "comfyui_nodes",
    "description": "List installed ComfyUI custom nodes.",
    "parameters": {"type": "object", "properties": {}},
}

for name, schema, handler in [
    ("comfyui_instances", COMFYUI_INSTANCES_SCHEMA, comfyui_instances_handler),
    ("comfyui_instance_start", COMFYUI_INSTANCE_START_SCHEMA, comfyui_instance_start_handler),
    ("comfyui_instance_stop", COMFYUI_INSTANCE_STOP_SCHEMA, comfyui_instance_stop_handler),
    ("comfyui_generate", COMFYUI_GENERATE_SCHEMA, comfyui_generate_handler),
    ("comfyui_models", COMFYUI_MODELS_SCHEMA, comfyui_models_handler),
    ("comfyui_nodes", COMFYUI_NODES_SCHEMA, comfyui_nodes_handler),
]:
    registry.register(
        name=name, toolset="comfyui", schema=schema,
        handler=handler, check_fn=_check_comfyui_mgmt,
    )
