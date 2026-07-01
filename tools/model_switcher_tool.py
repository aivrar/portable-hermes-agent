#!/usr/bin/env python3
"""
Model Switcher Tool — Change the LLM model used by Hermes.

Updates the .env file's LLM_MODEL line (and optionally OPENAI_BASE_URL for
LM Studio local models) and sets os.environ so the next agent creation
picks up the change without restarting the process.
"""

import json
import logging
import os
import re
from pathlib import Path

from tools.registry import registry

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

def _detect_lmstudio_url() -> str:
    """Use LM_STUDIO_BASE_URL or fall back to OPENAI_BASE_URL, else default."""
    lms = os.environ.get("LM_STUDIO_BASE_URL", "").strip()
    if lms:
        url = lms.rstrip("/")
        return url if url.endswith("/v1") else url + "/v1"
    current = os.environ.get("OPENAI_BASE_URL", "")
    if current and ("localhost" in current or "127.0.0.1" in current):
        return current.rstrip("/")
    return "http://localhost:8100/v1"


# Known provider base URLs
_PROVIDER_URLS = {
    "lmstudio": _detect_lmstudio_url(),
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def _update_env_line(content: str, key: str, value: str) -> str:
    """Update or append a KEY=value line in .env content."""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    if pattern.search(content):
        return pattern.sub(new_line, content)
    # Append if not present
    if not content.endswith("\n"):
        content += "\n"
    return content + new_line + "\n"


def switch_model_handler(args: dict, **kwargs) -> str:
    """Switch the active LLM model by updating .env and os.environ."""
    model = args.get("model", "").strip()
    if not model:
        return json.dumps({"error": "model parameter is required"})

    provider = (args.get("provider") or "").strip().lower()

    try:
        # Read current .env
        if _ENV_FILE.exists():
            content = _ENV_FILE.read_text(encoding="utf-8")
        else:
            content = ""

        old_model = os.environ.get("LLM_MODEL", "")

        # Update LLM_MODEL
        content = _update_env_line(content, "LLM_MODEL", model)
        os.environ["LLM_MODEL"] = model

        # Update OPENAI_BASE_URL if provider specified
        note = "Model updated in .env and environment."
        if provider and provider in _PROVIDER_URLS:
            base_url = _PROVIDER_URLS[provider]
            content = _update_env_line(content, "OPENAI_BASE_URL", base_url)
            os.environ["OPENAI_BASE_URL"] = base_url
            note += f" Base URL set to {base_url}."
        elif provider:
            # Treat as a raw URL
            content = _update_env_line(content, "OPENAI_BASE_URL", provider)
            os.environ["OPENAI_BASE_URL"] = provider
            note += f" Base URL set to {provider}."

        note += " Click + New Chat to apply."

        # Write .env
        _ENV_FILE.write_text(content, encoding="utf-8")
        logger.info("Switched model from %s to %s", old_model, model)

        return json.dumps({
            "switched": True,
            "model": model,
            "previous_model": old_model,
            "note": note,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Failed to switch model: {e}"})


# ---------------------------------------------------------------------------
# Schema & Registration
# ---------------------------------------------------------------------------
SWITCH_MODEL_SCHEMA = {
    "name": "switch_model",
    "description": (
        "Switch the LLM model used by Hermes. Updates the .env file and environment "
        "variables. The change takes effect on the next new chat. "
        "For LM Studio local models, set provider='lmstudio'. "
        "For OpenRouter, set provider='openrouter'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model identifier (e.g. 'anthropic/claude-opus-4.6', 'qwen3-30b-a3b').",
            },
            "provider": {
                "type": "string",
                "description": (
                    "Optional provider hint: 'lmstudio', 'openai', 'openrouter', "
                    "or a custom base URL. Sets OPENAI_BASE_URL accordingly."
                ),
            },
        },
        "required": ["model"],
    },
}

registry.register(
    name="switch_model",
    toolset="model_switcher",
    schema=SWITCH_MODEL_SCHEMA,
    handler=switch_model_handler,
    # Always available — no external dependency
)
