# Music Generation Server - Hermes Skill

You have access to a **portable Music Generation Server** running locally. Use it to generate music, songs, and sound effects from text prompts.

## Server Info
- **Base URL:** `http://127.0.0.1:9150`
- **Docs:** `http://127.0.0.1:9150/docs`
- **Location:** `extensions/music-server/`

## Quick Start
If the server isn't running, start it with the terminal tool:
```
cd extensions/music-server && launcher.bat api
```

If it's not installed yet, install it:
```
cd extensions/music-server && install.bat
```

## Available Models
Check installed models: `GET /api/models/status`

Supported models: `stable-audio`, `musicgen`, `musicgen-large`, `audioldm2`, `audioldm2-large`, `riffusion`, `mustango`, `tango2`

## Core API Endpoints (use via terminal with curl or python httpx)

### Generate Music
```python
import httpx, json
r = httpx.post("http://127.0.0.1:9150/api/music/{model}", json={
    "prompt": "upbeat electronic dance music with synths",
    "duration": 10.0,  # seconds
    "guidance_scale": 7.0,
}, timeout=300)
result = r.json()  # Returns {"output_id": "...", "audio_url": "/api/outputs/{id}/audio", ...}
```

### List Available Models
```python
r = httpx.get("http://127.0.0.1:9150/api/models")
```

### Check Model Status (installed/loaded/running)
```python
r = httpx.get("http://127.0.0.1:9150/api/models/status")
```

### Install a Model
```python
r = httpx.post("http://127.0.0.1:9150/api/install/{model_id}")
```

### Download Model Weights
```python
r = httpx.post("http://127.0.0.1:9150/api/install/{model_id}/download")
```

### Load/Unload Model (GPU memory management)
```python
httpx.post("http://127.0.0.1:9150/api/models/{model}/load")
httpx.post("http://127.0.0.1:9150/api/models/{model}/unload")
```

### List Workers
```python
r = httpx.get("http://127.0.0.1:9150/api/workers")
```

### Spawn/Kill Workers
```python
httpx.post("http://127.0.0.1:9150/api/workers/spawn", json={"model": "musicgen", "device": "cuda:0"})
httpx.delete("http://127.0.0.1:9150/api/workers/{worker_id}")
httpx.post("http://127.0.0.1:9150/api/workers/kill-all")
```

### List Generated Outputs
```python
r = httpx.get("http://127.0.0.1:9150/api/outputs")
```

### Get/Download Audio
```python
r = httpx.get("http://127.0.0.1:9150/api/outputs/{entry_id}/audio")
# Returns audio file bytes
```

### Get Model Parameters & Presets
```python
r = httpx.get("http://127.0.0.1:9150/api/models/{model}/params")
r = httpx.get("http://127.0.0.1:9150/api/models/{model}/presets")
```

### CLAP Audio Scoring (optional)
```python
httpx.post("http://127.0.0.1:9150/api/clap/start")
r = httpx.post("http://127.0.0.1:9150/api/clap/score", json={"audio_url": "...", "text": "..."})
```

### GPU/Device Info
```python
r = httpx.get("http://127.0.0.1:9150/api/devices")
```

## Available Tools (use these instead of raw API calls)

| Tool | What it does |
|------|-------------|
| `music_status` | Check server status and model availability |
| `music_generate` | Generate music from text prompt |
| `music_models` | List all models with load/install status |
| `music_model_load` | Load a model (spawn GPU worker) |
| `music_model_unload` | Unload model to free GPU memory |
| `music_outputs` | List generated music library |
| `music_install` | Install a model (venv + weights download) |

## Tips
- Workers auto-spawn when you request a model that isn't loaded yet
- Use `duration` param to control length (5-60 seconds depending on model)
- Generated audio is saved to `extensions/music-server/output/`
- Use terminal tool with `python -c "import httpx; ..."` to call these endpoints
- Always check server health first: `httpx.get("http://127.0.0.1:9150/health")`
