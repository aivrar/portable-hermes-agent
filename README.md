# Portable Hermes Agent

**Portable AI agent desktop for Windows** — 100 tools, GUI, local models via LM Studio, TTS, Music, ComfyUI, workflows, tool maker. No install. No Docker. No admin rights.

Built on [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT License) with extensive customization for non-technical users.

---

## Features

### Desktop GUI
- Dark-themed Tkinter interface with chat, sidebar, and session management
- Image attachment with thumbnails (vision model support)
- Guided mode — works even without an AI model connected
- API key setup wizard with individual service configuration
- Permissions panel with granular control over file, network, and system access

### 100 Tools Across 20+ Toolsets

| Toolset | Tools | What It Does |
|---------|-------|-------------|
| **LM Studio** | 10 | Load/unload models, search HuggingFace, tokenize, embed, direct chat |
| **Music** | 7 | Generate music, manage models, GPU workers, output library |
| **TTS** | 7 | Text-to-speech, 10 voice models, voice cloning, job management |
| **ComfyUI** | 7 | Image generation, instance management, model/node browsing |
| **Workflows** | 6 | Create, run, schedule, and manage multi-step automation pipelines |
| **Tool Maker** | 3 | Dynamically create API wrapper or Python handler tools at runtime |
| **Serper** | 1 | Google-quality search via Serper.dev API |
| **Guide** | 1 | Searchable built-in user manual |
| **GPU** | 1 | NVIDIA GPU status (memory, temp, utilization) |
| **Model Switcher** | 1 | Switch between cloud and local AI models |
| **Hermes Update** | 2 | Update from this portable repo with backups and runtime preservation |

Plus all built-in hermes-agent tools: web search, file operations, browser automation, code execution, delegation, memory, skills, messaging, Home Assistant, and more.

### Extension Modules

Three portable AI generation servers from [aivrar](https://github.com/aivrar):

| Extension | Port | Models | GPU |
|-----------|------|--------|-----|
| **[TTS Server](https://github.com/aivrar/portable-tts-server)** | 8200 | Kokoro, XTTS, Dia, Bark, Fish, + 5 more | 4 GB+ |
| **[Music Server](https://github.com/aivrar/portable-music-server)** | 9150 | MusicGen, Stable Audio, ACE-Step, Riffusion | 4 GB+ |
| **[ComfyUI](https://github.com/aivrar/comfyui-portable-installer)** | 5000 | SD 1.5, SDXL, Flux, 100+ registry models | 6 GB+ |

Each extension auto-installs on first use. No system dependencies.

### Workflow Engine
Chain tool calls into automated pipelines with data flow, conditions, loops, parallel execution, error handling, and cron scheduling.

### Dynamic Tool Maker
Create new tools at runtime — wrap any REST API or write custom Python handlers. Tools persist across sessions and reload automatically.

### Guided Mode
No API key? No problem. The chat works offline using a built-in 1,054-line user guide. New users get step-by-step guidance to set up their first AI model.

---

## Quick Start

### 1. Download
Download the latest `portable-hermes-agent-v*.zip` from [Releases](https://github.com/aivrar/portable-hermes-agent/releases/latest), then extract it to a normal folder.

Recommended:
```text
C:\Users\YourName\Portable-Hermes-Agent
```

Avoid protected folders such as `C:\Program Files`.

### 2. Start
Double-click:
```batch
START.bat
```

On first launch, `START.bat` runs the portable setup automatically. It downloads embedded Python, dependencies, LM Studio SDK, and Node.js tools into this folder only. No admin rights are needed.

Manual setup:
```batch
install.bat
```

PowerShell users can run:

```powershell
.\scripts\install.ps1
```

### 3. Launch Again
```batch
START.bat           :: easiest GUI launch
UPDATE.bat          :: safest one-click update
hermes_gui.bat      :: GUI mode
hermes.bat          :: CLI mode
```

### Updating

For the easiest safe update, double-click:

```batch
UPDATE.bat
```

Or run:

```batch
hermes.bat update --backup --yes
```

Updates come from `aivrar/portable-hermes-agent`. Runtime folders such as `.hermes/`, `.hermes/custom_tools/`, `.hermes/extensions/`, `extensions/`, and `python_embedded/` are preserved. Upstream Hermes changes from NousResearch are included only after this portable repo has merged, tested, and released them.

### 4. Connect an AI Model

**Cloud (2 minutes, free):**
1. File > API Key Setup > OpenRouter
2. Sign up at openrouter.ai (free, no credit card)
3. Paste your API key
4. Start chatting

**Local (needs NVIDIA GPU):**
1. Download [LM Studio](https://lmstudio.ai)
2. Download a model, start the server
3. Tools > LM Studio in the GUI
4. Load model, click "Use for Chat"

---

## Requirements

- Windows 10/11
- Internet connection (for cloud AI) or NVIDIA GPU 8GB+ (for local AI)
- No admin rights, no system Python, no Docker

---

## Documentation

A searchable user guide is built into the agent — ask it anything or use the `search_guide` tool. The [PDF manual](https://github.com/aivrar/portable-hermes-agent/releases/latest) is included in every release.

Key topics: getting started, API setup, the interface, permissions, LM Studio local models, extensions (TTS/Music/ComfyUI), all 100 tools, custom tool creation, workflows, and a glossary of AI terms.

---

## Architecture

```
User
 |
 v
GUI (Tkinter) / CLI
 |
 v
Agent Bridge (threading, sessions)
 |
 v
AIAgent (run_agent.py)
 |
 +-- Tool Registry (100 tools)
 |    +-- LM Studio tools (SDK + HTTP)
 |    +-- Extension tools (Music, TTS, ComfyUI)
 |    +-- Workflow engine
 |    +-- Tool maker (dynamic creation)
 |    +-- Serper, GPU, Guide, etc.
 |    +-- Custom tools (user-created)
 |
 +-- LLM Provider
      +-- OpenRouter (cloud)
      +-- LM Studio (local, GPU)
      +-- Any OpenAI-compatible endpoint
```

---

## Credits

- **Base framework**: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT License)
- **Extension modules**: [aivrar](https://github.com/aivrar) — portable-tts-server, portable-music-server, comfyui-portable-installer
- **Custom tools, GUI, and integrations**: Built with [Claude Code](https://claude.ai/claude-code)

---

## License

MIT License — see [LICENSE](LICENSE) for details.

Original framework copyright (c) 2025 Nous Research.
