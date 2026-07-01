# ComfyUI Image Generator - Hermes Skill

You have access to a **portable ComfyUI installation** for AI image generation with Stable Diffusion and other models.

## Server Info
- **Installer API:** `http://127.0.0.1:8188` (management)
- **ComfyUI Web UI:** `http://127.0.0.1:8188` (when instance is running)
- **Location:** `extensions/comfyui/`

## Quick Start
If not running, start the management server:
```
cd extensions/comfyui && launcher.bat
```

If not installed yet:
```
cd extensions/comfyui && install.bat
```

## Architecture
ComfyUI has two layers:
1. **Installer/Manager API** (port 8188) — manages instances, models, nodes
2. **ComfyUI instances** (port 8188+) — the actual image generation servers

## Management API Endpoints (use via terminal with python httpx)

### System Status
```python
import httpx
r = httpx.get("http://127.0.0.1:8188/api/status")   # Overall status
r = httpx.get("http://127.0.0.1:8188/api/gpus")      # GPU info
r = httpx.get("http://127.0.0.1:8188/api/settings")  # Current settings
```

### Install ComfyUI
```python
r = httpx.post("http://127.0.0.1:8188/api/install")        # Full install
r = httpx.post("http://127.0.0.1:8188/api/update")         # Update ComfyUI
r = httpx.post("http://127.0.0.1:8188/api/install/sage-attention")  # Install SageAttention
```

### Instance Management (multi-GPU)
```python
# List all instances
r = httpx.get("http://127.0.0.1:8188/api/instances")

# Create new instance
r = httpx.post("http://127.0.0.1:8188/api/instances", json={
    "gpu": 0,       # GPU index
    "port": 8189,   # Port for this instance
    "vram": "normal" # normal, low, cpu
})

# Start/Stop instances
httpx.post("http://127.0.0.1:8188/api/instances/{id}/start")
httpx.post("http://127.0.0.1:8188/api/instances/{id}/stop")
httpx.post("http://127.0.0.1:8188/api/instances/start-all")
httpx.post("http://127.0.0.1:8188/api/instances/stop-all")
```

### Model Management
```python
# Browse model registry (101+ pre-defined models)
r = httpx.get("http://127.0.0.1:8188/api/models/registry")
r = httpx.get("http://127.0.0.1:8188/api/models/categories")
r = httpx.get("http://127.0.0.1:8188/api/models/search?q=sdxl")

# See locally installed models
r = httpx.get("http://127.0.0.1:8188/api/models/local")

# Download a model
r = httpx.post("http://127.0.0.1:8188/api/models/download", json={
    "id": "sd15-base"  # Model ID from registry
})
```

### Custom Nodes
```python
# Browse node registry
r = httpx.get("http://127.0.0.1:8188/api/nodes/registry")

# See installed nodes
r = httpx.get("http://127.0.0.1:8188/api/nodes/installed")

# Install custom node
r = httpx.post("http://127.0.0.1:8188/api/nodes/install", json={
    "url": "https://github.com/author/custom-node.git"
})

# Update nodes
httpx.post("http://127.0.0.1:8188/api/nodes/update-all")
```

### ComfyUI Target Directory
```python
r = httpx.get("http://127.0.0.1:8188/api/comfyui/target")           # Current target
httpx.put("http://127.0.0.1:8188/api/comfyui/target", json={"path": "..."})  # Change target
httpx.post("http://127.0.0.1:8188/api/comfyui/target/reset")        # Reset to default
```

### Jobs & Logs
```python
r = httpx.get("http://127.0.0.1:8188/api/jobs")          # List background jobs
r = httpx.get("http://127.0.0.1:8188/api/jobs/{id}")      # Job status
r = httpx.get("http://127.0.0.1:8188/api/logs")           # Server logs
```

### Cleanup
```python
httpx.post("http://127.0.0.1:8188/api/purge")      # Remove ComfyUI (keep models)
httpx.post("http://127.0.0.1:8188/api/purge-all")   # Remove everything
```

## Generating Images (via ComfyUI Instance API)
Once a ComfyUI instance is running (e.g., on port 8189):
```python
# Queue a prompt/workflow
r = httpx.post("http://127.0.0.1:8189/prompt", json={
    "prompt": {workflow_json},
    "client_id": "hermes"
})

# Get generated images
r = httpx.get("http://127.0.0.1:8189/view", params={"filename": "output.png"})
```

## Available Tools (use these instead of raw API calls)

| Tool | What it does |
|------|-------------|
| `comfyui_status` | Check ComfyUI server status and system info |
| `comfyui_instances` | List all instances with status, GPU, port |
| `comfyui_instance_start` | Start a ComfyUI instance |
| `comfyui_instance_stop` | Stop a running instance |
| `comfyui_generate` | Generate an image from text prompt |
| `comfyui_models` | List locally installed models |
| `comfyui_nodes` | List installed custom nodes |

## Tips
- Install ComfyUI first via the installer API, then download models, then start an instance
- Use `api/models/registry` to browse all 101+ pre-defined models
- Each GPU can run its own instance on a separate port
- The web UI at the instance port provides a visual workflow editor
- Models are stored in `extensions/comfyui/comfyui/models/`
- All portable — nothing installed system-wide
