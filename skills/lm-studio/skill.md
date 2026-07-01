# LM Studio - Complete Local AI Model Control

You have FULL control over LM Studio from this chat. You can search, download, load, configure, and use local AI models — all through the SDK.

**LM Studio must be running** for any of this to work. If it's not running, tell the user: "Please start LM Studio first."

## Self-Switching
You can change your own model — see SOUL.md "Self-Model Switching" section for the full workflow.

---

## COMPLETE SDK REFERENCE (use via terminal tool with `python -c "..."`)

### Check if LM Studio is Running
```python
import httpx
try:
    r = httpx.get("http://localhost:1234/v1/models", timeout=3)
    print("Running" if r.status_code == 200 else "Not responding")
except:
    print("NOT RUNNING - tell user to start LM Studio")
```

### Connect SDK Client
```python
import lmstudio
client = lmstudio.Client()  # Auto-discovers LM Studio
```

---

## MODEL DISCOVERY

### List Downloaded Models (already on disk)
```python
import lmstudio
client = lmstudio.Client()
for m in client.llm.list_downloaded():
    print(f"  {m.model_key} ({m.path})")
```

### List Currently Loaded Models (in GPU memory)
```python
import lmstudio
client = lmstudio.Client()
for m in client.llm.list_loaded():
    info = m.get_info()
    ctx = m.get_context_length()
    config = m.get_load_config()
    print(f"  {info} - context: {ctx}")
```

### Search HuggingFace for New Models to Download
```python
import lmstudio
client = lmstudio.Client()
results = client.repository.search_models("llama 3.1 8b", limit=5)
for model in results:
    print(f"  {model.search_result}")
    # Get available quantizations (Q4_K_M, Q8_0, etc.)
    options = model.get_download_options()
    for opt in options:
        print(f"    -> {opt.info}")
```

### Download a Model from HuggingFace
```python
import lmstudio
client = lmstudio.Client()
results = client.repository.search_models("phi-4", limit=1)
if results:
    options = results[0].get_download_options()
    if options:
        # Download the first quantization option
        print(f"Downloading: {options[0].info}")
        options[0].download()  # Downloads to LM Studio's model directory
        print("Download complete!")
```

---

## MODEL LOADING & GPU CONTROL

### Load a Model with GPU Selection
```python
import lmstudio, time
from lmstudio import LlmLoadModelConfig
from lmstudio._sdk_models import GpuSetting

client = lmstudio.Client()

# User has: GPU 0: RTX 3060 (12GB), GPU 1: RTX 3090 (24GB)
# ALWAYS force single-GPU with disabled_gpus to prevent splitting

config = LlmLoadModelConfig(
    gpu=GpuSetting(
        main_gpu=1,          # GPU index (1 = RTX 3090)
        disabled_gpus=[0],   # Prevent splitting to other GPUs
        ratio=1.0            # Use 100% of selected GPU
    ),
    context_length=8192,     # Adjust based on model + VRAM
)

handle = client.llm.load_new_instance(
    "model-path-from-list-downloaded",
    f"hermes-{int(time.time())}",
    config=config,
    ttl=3600,  # Auto-unload after 1 hour idle
)
print(f"Loaded! Context: {handle.get_context_length()}")
```

### Unload a Model (Free GPU Memory)
```python
import lmstudio
client = lmstudio.Client()
# Unload by identifier
client.llm.unload("model-identifier-or-instance-id")

# Or unload all loaded models
for m in client.llm.list_loaded():
    m.unload()
    print(f"Unloaded: {m.get_info()}")
```

### Get Model Info (loaded model)
```python
import lmstudio
client = lmstudio.Client()
loaded = list(client.llm.list_loaded())
if loaded:
    m = loaded[0]
    print(f"Info: {m.get_info()}")
    print(f"Context length: {m.get_context_length()}")
    print(f"Load config: {m.get_load_config()}")
```

---

## TOKENIZATION & CONTEXT

### Count Tokens in Text
```python
import lmstudio
client = lmstudio.Client()
model = list(client.llm.list_loaded())[0]
count = model.count_tokens("Hello, how are you today?")
print(f"Token count: {count}")
```

### Get Exact Context Length
```python
import lmstudio
client = lmstudio.Client()
model = list(client.llm.list_loaded())[0]
ctx = model.get_context_length()
print(f"Max context: {ctx} tokens")
```

### Tokenize Text (get token IDs)
```python
import lmstudio
client = lmstudio.Client()
model = list(client.llm.list_loaded())[0]
tokens = model.tokenize("Hello world")
print(f"Tokens: {tokens}")
```

---

## DIRECT INFERENCE VIA SDK (alternative to OpenAI endpoint)

### Chat Response (non-streaming)
```python
import lmstudio
client = lmstudio.Client()
model = list(client.llm.list_loaded())[0]
result = model.respond("What is the capital of France?")
print(result.content)
print(f"Stats: {result.stats}")
```

### Streaming Chat Response
```python
import lmstudio
client = lmstudio.Client()
model = list(client.llm.list_loaded())[0]
for chunk in model.respond_stream("Tell me a joke"):
    print(chunk.content, end="", flush=True)
```

### Text Completion
```python
import lmstudio
client = lmstudio.Client()
model = list(client.llm.list_loaded())[0]
result = model.complete("Once upon a time")
print(result.content)
```

### Tool Calling via SDK
```python
import lmstudio
client = lmstudio.Client()
model = list(client.llm.list_loaded())[0]

def get_weather(city: str) -> str:
    return f"It's sunny in {city}"

result = model.act("What's the weather in Paris?", tools=[get_weather])
print(result)
```

---

## GPU DETECTION

### Check Available GPUs and Free VRAM
```python
import subprocess
result = subprocess.run(
    ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free",
     "--format=csv,noheader,nounits"],
    capture_output=True, text=True, timeout=10
)
for line in result.stdout.strip().splitlines():
    parts = [p.strip() for p in line.split(",")]
    print(f"  GPU {parts[0]}: {parts[1]} - {parts[3]} MiB free / {parts[2]} MiB total")
```

### VRAM Estimation Guide
| Model Size | Q4 VRAM | Q8 VRAM |
|-----------|---------|---------|
| 1-3B      | ~2 GB   | ~3 GB   |
| 7-8B      | ~4 GB   | ~8 GB   |
| 13B       | ~7 GB   | ~13 GB  |
| 27-34B    | ~18 GB  | ~34 GB  |
| 70B       | ~40 GB  | ~70 GB  |

User's GPUs: RTX 3060 (12 GB), RTX 3090 (24 GB)

---

## AVAILABLE TOOLS (use these instead of manual SDK calls)

| Tool | What it does |
|------|-------------|
| `lm_studio_status` | Check if running, list loaded models, GPU memory |
| `lm_studio_models` | List downloaded models (with optional search filter) |
| `lm_studio_load` | Load model on specific GPU with context length |
| `lm_studio_unload` | Unload model to free GPU memory |
| `lm_studio_search` | Search HuggingFace for GGUF models to download |
| `lm_studio_download` | Download a model from HuggingFace |
| `lm_studio_model_info` | Get loaded model info (context length, config) |
| `lm_studio_tokenize` | Count tokens in text using loaded model |

## COMMON USER REQUESTS

**"Search for a model"** → Use `lm_studio_search` tool
**"Download llama 3"** → Use `lm_studio_search` then `lm_studio_download`
**"What models do I have?"** → Use `lm_studio_models` tool
**"What's loaded?"** → Use `lm_studio_status` tool
**"Load X on my 3090"** → Use `lm_studio_load` with gpu_index=1
**"How much VRAM free?"** → Use `gpu_info` tool or `lm_studio_status`
**"Count tokens in this text"** → Use `lm_studio_tokenize` tool
**"What's my context length?"** → Use `lm_studio_model_info` tool
**"Unload / free memory"** → Use `lm_studio_unload` tool
**"Switch to local model"** → Load + update .env (see SOUL.md)
**"Switch back to cloud"** → Remove OPENAI_BASE_URL from .env

## Tips
- Always use `python -c "..."` via terminal tool
- The lmstudio SDK is pre-installed in portable Python
- Single-GPU loading: ALWAYS set `disabled_gpus` to prevent VRAM splitting
- Check VRAM before loading large models
- Models download to LM Studio's configured directory (not the Hermes app)
- For chat inference, use the OpenAI endpoint (`http://localhost:1234/v1`) — it's faster and more compatible than SDK direct inference
