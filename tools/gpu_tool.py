#!/usr/bin/env python3
"""
GPU Info Tool — Query NVIDIA GPU status via nvidia-smi.

Returns structured GPU data (name, memory, temperature, utilization)
without requiring the LLM to parse CSV output from a terminal command.
"""

import json
import logging
import shutil
import subprocess

from tools.registry import registry

logger = logging.getLogger(__name__)


def _check_nvidia_smi() -> bool:
    return shutil.which("nvidia-smi") is not None


def gpu_info_handler(args: dict, **kwargs) -> str:
    """Query nvidia-smi and return structured GPU info."""
    query = "index,name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return json.dumps({"error": f"nvidia-smi failed: {result.stderr.strip()}"})

        gpus = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 7:
                gpus.append({
                    "index": int(parts[0]),
                    "name": parts[1],
                    "memory_total_mb": int(parts[2]),
                    "memory_used_mb": int(parts[3]),
                    "memory_free_mb": int(parts[4]),
                    "temperature_c": int(parts[5]) if parts[5] != "N/A" else None,
                    "utilization_pct": int(parts[6]) if parts[6] != "N/A" else None,
                })

        return json.dumps({"gpus": gpus, "count": len(gpus)}, ensure_ascii=False)

    except subprocess.TimeoutExpired:
        return json.dumps({"error": "nvidia-smi timed out"})
    except Exception as e:
        return json.dumps({"error": f"GPU query failed: {e}"})


# ---------------------------------------------------------------------------
# Schema & Registration
# ---------------------------------------------------------------------------
GPU_INFO_SCHEMA = {
    "name": "gpu_info",
    "description": (
        "Get NVIDIA GPU status: name, memory (total/used/free in MB), temperature, "
        "and utilization percentage for each GPU. Use this before loading models to "
        "check available VRAM."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

registry.register(
    name="gpu_info",
    toolset="gpu",
    schema=GPU_INFO_SCHEMA,
    handler=gpu_info_handler,
    check_fn=_check_nvidia_smi,
)
