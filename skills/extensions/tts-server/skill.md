# Text-to-Speech Server - Hermes Skill

You have access to a **portable TTS Server** running locally. Use it to generate speech, clone voices, and create dialogue with emotions.

## Server Info
- **Base URL:** `http://127.0.0.1:8100`
- **Docs:** `http://127.0.0.1:8100/docs`
- **Location:** `extensions/tts-server/`

## Quick Start
If the server isn't running, start it:
```
cd extensions/tts-server && launcher.bat api
```

If not installed yet:
```
cd extensions/tts-server && install.bat
```

## Available TTS Models
10 models, each with different strengths:

| Model | Best For | Voice Cloning | Multilingual |
|-------|----------|---------------|-------------|
| `xtts` | General purpose, cloning | Yes | Yes (17 languages) |
| `fish` | Fast, natural | Yes | Yes |
| `kokoro` | English quality | No (preset voices) | Limited |
| `bark` | Expressive, sound effects | No (preset) | Yes |
| `chatterbox` | Conversational | Yes | English |
| `f5` | Natural flow | Yes | Yes |
| `dia` | Dialogue with emotions | No | English |
| `qwen` | Chinese + English | Yes | Chinese/English |
| `vibevoice` | Emotional range | Yes | English |
| `higgs` | High quality | Yes | English |

## Core API Endpoints (use via terminal with python httpx)

### Generate Speech
```python
import httpx
r = httpx.post("http://127.0.0.1:8100/api/tts/kokoro", json={
    "text": "Hello! This is Hermes speaking.",
    "voice": "af_heart",
}, timeout=120)
result = r.json()  # Returns job info with audio URL
```

### Generate Speech with Voice Cloning (xtts, fish, f5, etc.)
```python
r = httpx.post("http://127.0.0.1:8100/api/tts/xtts", json={
    "text": "This sounds like the reference voice.",
    "voice": "path/to/reference.wav",
    "language": "en",
}, timeout=120)
```

### Generate Dialogue with Emotions (dia model)
```python
r = httpx.post("http://127.0.0.1:8100/api/tts/dia", json={
    "text": "[S1] Hello, how are you? [S2] (laughs) I'm great, thanks!",
}, timeout=120)
```

### List Available Voices per Model
```python
r = httpx.get("http://127.0.0.1:8100/api/tts/kokoro/voices")
r = httpx.get("http://127.0.0.1:8100/api/tts/xtts/voices")
r = httpx.get("http://127.0.0.1:8100/api/tts/bark/voices")
# ... (each model has /voices endpoint)
```

### List All Models & Status
```python
r = httpx.get("http://127.0.0.1:8100/api/models")
r = httpx.get("http://127.0.0.1:8100/api/models/status")
```

### Job Management
```python
r = httpx.get("http://127.0.0.1:8100/api/jobs")          # List all jobs
r = httpx.get("http://127.0.0.1:8100/api/jobs/{job_id}")  # Get job status + audio URL
```

### Load/Unload Models (GPU memory)
```python
httpx.post("http://127.0.0.1:8100/api/models/{model}/load")
httpx.post("http://127.0.0.1:8100/api/models/{model}/unload")
```

### Worker Management
```python
r = httpx.get("http://127.0.0.1:8100/api/workers")
httpx.post("http://127.0.0.1:8100/api/workers/spawn", json={"model": "kokoro", "device": "cuda:0"})
httpx.delete("http://127.0.0.1:8100/api/workers/{worker_id}")
```

### Whisper (Speech-to-Text)
```python
r = httpx.get("http://127.0.0.1:8100/api/whisper")
httpx.post("http://127.0.0.1:8100/api/whisper/base/load")
```

### GPU/Device Info
```python
r = httpx.get("http://127.0.0.1:8100/api/devices")
```

## Available Tools (use these instead of raw API calls)

| Tool | What it does |
|------|-------------|
| `tts_server_status` | Check server status and model availability |
| `tts_server_generate` | Generate speech from text |
| `tts_server_models` | List all models with load status |
| `tts_server_model_load` | Load a TTS model (spawn worker) |
| `tts_server_model_unload` | Unload model to free GPU memory |
| `tts_server_voices` | List available voices for a model |
| `tts_server_jobs` | List TTS generation jobs |

## Tips
- Workers auto-spawn when you request a model
- For voice cloning, place reference audio (WAV/MP3) in `extensions/tts-server/voices/`
- Generated audio saved to `extensions/tts-server/output/jobs/`
- Use `python -c "import httpx; ..."` via terminal tool to call endpoints
- Check health: `httpx.get("http://127.0.0.1:8100/health")`
