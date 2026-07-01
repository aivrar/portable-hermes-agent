# Hermes Agent - Diagnostic Log
> Generated: 2026-03-17 | Repo: `E:\hermes`

---

## SYSTEM HARDWARE

| Component | Details |
|-----------|---------|
| **CPU** | Intel Core i7-5930K @ 3.50GHz (6 cores / 12 threads) |
| **RAM** | 64 GB total, ~39.6 GB free |
| **GPU 1** | NVIDIA RTX 3060 12GB (10.4 GB free) |
| **GPU 2** | NVIDIA RTX 3090 24GB (23.8 GB free) |
| **GPU Driver** | 591.86 |
| **OS** | Windows 10 Pro 10.0.19045 |
| **Disk C:** | 480 GB total, 34.5 GB free |
| **Disk D:** | 2 TB total, 412 GB free |
| **Disk E:** | 4 TB total, 1.08 TB free (repo lives here) |

---

## PYTHON ENVIRONMENTS

### Embedded Python (primary - used by START.bat, hermes.bat)
- **Path:** `E:\hermes\python_embedded\python.exe`
- **Version:** Python 3.13.12
- **Status:** HEALTHY - all core dependencies installed

### System Python (NOT used by Hermes)
- **Version:** Python 3.13.11
- **Status:** Missing most Hermes dependencies (expected - Hermes uses embedded Python)

### Venv (exists but secondary)
- **Path:** `E:\hermes\venv\Scripts\python.exe`
- **Status:** Present, minimal packages

---

## CORE DEPENDENCY STATUS (Embedded Python)

| Package | Status | Version |
|---------|--------|---------|
| openai | OK | 2.28.0 |
| anthropic | OK | 0.84.0 |
| python-dotenv | OK | - |
| fire | OK | 0.7.1 |
| httpx | OK | 0.28.1 |
| rich | OK | - |
| tenacity | OK | - |
| pyyaml | OK | 6.0.3 |
| requests | OK | 2.32.5 |
| jinja2 | OK | 3.1.6 |
| pydantic | OK | 2.12.5 |
| prompt_toolkit | OK | 3.0.52 |
| firecrawl-py | OK | 4.19.0 |
| fal-client | OK | 0.13.1 |
| edge-tts | OK | 7.2.7 |
| faster-whisper | OK | 1.2.1 |
| litellm | OK | - |

## OPTIONAL DEPENDENCY STATUS (Embedded Python)

| Package | Status | Used By |
|---------|--------|---------|
| croniter | OK | Cron jobs |
| telegram | OK (22.6) | Gateway - Telegram |
| discord.py | OK (2.7.1) | Gateway - Discord |
| aiohttp | OK (3.13.3) | Gateway - Slack/web |
| mcp | OK | MCP tool integration |
| numpy | OK (2.4.3) | Audio/ML tools |
| honcho | OK (2.0.1) | Cross-session memory |
| sounddevice | MISSING | Voice input (STT mic) |

---

## CONFIGURATION

### Active Model Config (`~/.hermes/config.yaml`)
| Setting | Value |
|---------|-------|
| **Model** | `anthropic/claude-opus-4.6` |
| **Toolsets** | `hermes-cli` |
| **Max Turns** | 90 |
| **Terminal Backend** | local |
| **Terminal Timeout** | 180s |
| **Context Compression** | Enabled at 50% threshold |
| **Compression Model** | `google/gemini-3-flash-preview` |
| **Memory** | Enabled |
| **User Profile** | Enabled |
| **Personality** | kawaii |
| **Skin** | default |
| **TTS Provider** | edge (en-US-AriaNeural) |
| **STT Provider** | local (whisper base) |
| **Timezone** | (not set - uses system) |
| **Security: Redact Secrets** | true |
| **Security: Tirith** | enabled (but install failed - see ISSUES) |

### Defaults from cli-config.yaml
| Setting | Value |
|---------|-------|
| **Default Model** | `anthropic/claude-opus-4.6` |
| **Default Provider** | auto |
| **Default Base URL** | `https://openrouter.ai/api/v1` |
| **Compression Threshold** | 0.85 (overridden to 0.5 in user config) |

---

## API KEY STATUS (`.env`)

| Key | Status | Service |
|-----|--------|---------|
| `OPENROUTER_API_KEY` | SET | Main LLM routing |
| `FIRECRAWL_API_KEY` | SET | Web extraction |
| `FAL_KEY` | SET | Image generation |
| `SERPER_API_KEY` | SET | Google search |
| `BROWSERBASE_API_KEY` | EMPTY | Browser automation |
| `BROWSERBASE_PROJECT_ID` | EMPTY | Browser automation |
| `GLM_API_KEY` | EMPTY | Z.AI / GLM provider |
| `KIMI_API_KEY` | EMPTY | Kimi / Moonshot |
| `MINIMAX_API_KEY` | EMPTY | MiniMax |
| `HONCHO_API_KEY` | EMPTY | Cross-session memory |
| `VOICE_TOOLS_OPENAI_KEY` | EMPTY | OpenAI TTS/STT |
| `TINKER_API_KEY` | EMPTY | RL training |
| `WANDB_API_KEY` | EMPTY | Experiment tracking |

---

## SERVICES & PORTS

| Port | Service | Status |
|------|---------|--------|
| 8100 | TTS Server (local) | RUNNING (PID 15736) |
| 8188 | ComfyUI | Not running |
| 8200 | TTS Extension Server | Not running |
| 9150 | Music Extension Server | Not running |
| 1234 | LM Studio | Not running |
| 11434 | Ollama | Not running |

---

## GIT STATUS

| Property | Value |
|----------|-------|
| **Origin** | `github.com/aivrar/portable-hermes-agent.git` |
| **Upstream** | `github.com/nousresearch/hermes-agent.git` |
| **Branch** | main |
| **Last Commit** | `f9bff32` fix: rewrite PDF builder with fpdf2 built-in table support |

### Commit History
```
f9bff32 fix: rewrite PDF builder with fpdf2 built-in table support
8283fb1 fix: PDF manual table layout and page header spacing
03f7428 docs: add PDF manual + build scripts
533bd39 fix: update tool pulls from upstream (NousResearch), not origin
bdbcb2e feat: add START.bat for first-time users
648fcef feat: portable desktop build with custom README
6d333a0 Initial base: hermes-agent by NousResearch
```

### Submodules
| Submodule | Commit | Branch/Tag | Notes |
|-----------|--------|------------|-------|
| mini-swe-agent | `07aa6a73` | v1.17.3-22 (detached) | Pinned for compatibility |
| tinker-atropos | `65f084ee` | cleanup_fixes (remote) | Custom fork branch |

### Untracked Files
- `check_lm_studio.py` (test script)
- `test_script.sh` (test script)

---

## USER CONFIG DIRECTORY (`~/.hermes/`)

| Item | Size/Info |
|------|-----------|
| `config.yaml` | 3.1 KB - active config |
| `SOUL.md` | 8.2 KB - custom personality |
| `state.db` | 360 KB - session database (SQLite WAL active) |
| `permissions.json` | r=2, w=1, install=1, exec=2, remove=1, network=2 |
| `.hermes_history` | CLI command history |
| `auth.lock` | Auth token lock |
| `skills/` | 88+ installed skills |
| `memories/` | Persistent memory store |
| `sessions/` | Conversation archives |
| `logs/` | Session logs |
| `cron/` | Scheduled jobs |
| `sandboxes/` | Isolated environments |

---

## ARCHITECTURE OVERVIEW

```
User Interfaces
├── GUI (Tkinter)        → gui/app.py → gui/agent_bridge.py
├── CLI (TUI/Rich)       → hermes_cli/main.py → cli.py
├── Gateway (24/7 daemon) → gateway/run.py (Telegram/Discord/Slack)
└── ACP Server           → acp_adapter/entry.py (VS Code/Zed/JetBrains)
        │
        ▼
   AIAgent Core (run_agent.py - 313KB)
   ├── Conversation loop with tool calling
   ├── Provider abstraction (OpenRouter/Anthropic/OpenAI/etc.)
   ├── Context compression (auto-summarize at threshold)
   ├── Memory injection (persistent facts)
   └── Session persistence (SQLite FTS5)
        │
        ▼
   Tool Registry (tools/registry.py + model_tools.py)
   └── 99 registered tools across 58 files
       ├── File ops, Web search, Terminal, Code exec
       ├── Browser automation, Vision, Image gen
       ├── LM Studio, TTS, Music, ComfyUI
       ├── Skills, Memory, Workflows, MCP
       ├── Messaging, Home Assistant, Honcho
       └── GPU info, Model switching, Cron jobs
```

### Tool Count by Category
| Category | Tools |
|----------|-------|
| Web/Search | 3 (web_search, web_extract, serper_search) |
| File Operations | 4 (read, write, patch, search) |
| Terminal/Process | 2 (terminal, process) |
| Browser | 10 (navigate, snapshot, click, type, scroll, etc.) |
| LM Studio | 10 (status, models, load, unload, search, etc.) |
| TTS Server | 7 (status, generate, models, load, unload, voices, jobs) |
| Music Server | 7 (status, generate, models, load, unload, outputs, install) |
| ComfyUI | 7 (status, instances, start, stop, generate, models, nodes) |
| Honcho Memory | 4 (context, profile, search, conclude) |
| Home Assistant | 4 (list_entities, get_state, list_services, call_service) |
| Workflows | 6 (create, run, list, delete, show, schedule) |
| Skills | 3 (list, view, manage) |
| Tool Making | 3 (create, delete, list_custom) |
| Other | 29 (vision, image_gen, todo, memory, delegate, etc.) |
| **Total** | **99** |

---

## KNOWN ISSUES & WARNINGS

### ISSUE 1: Tirith Security Scanner - Install Failed
- **File:** `~/.hermes/.tirith-install-failed` → `unsupported_platform`
- **Impact:** Security policy scanning for terminal commands is disabled
- **Config:** `tirith_fail_open: true` (agent continues without it)
- **Action:** Non-blocking. Tirith doesn't support Windows natively.

### ~~ISSUE 2: LM Studio Port Conflict~~ (FIXED 2026-03-17)
- **Was:** `OPENAI_BASE_URL=http://127.0.0.1:8100` pointed LM Studio tools at the TTS server
- **Fix:** Added `LM_STUDIO_BASE_URL=http://127.0.0.1:1234` in `.env`; updated `lm_studio_tools.py`, `model_switcher_tool.py`, and `gui/lm_studio.py` to prefer `LM_STUDIO_BASE_URL`
- **Files changed:** `.env`, `tools/lm_studio_tools.py`, `tools/model_switcher_tool.py`, `gui/lm_studio.py`

### ~~ISSUE 3: GUI Stop Button Overlapping Chat~~ (FIXED 2026-03-17)
- **Was:** Stop button packed in chat header (`hdr`), floating over messages
- **Fix:** Moved Stop button into `btn_frame` in the input area, next to Send button
- **File changed:** `gui/app.py`

### ISSUE 4: Browserbase Not Configured
- **Keys:** `BROWSERBASE_API_KEY` and `BROWSERBASE_PROJECT_ID` are empty
- **Impact:** Browser automation tools (`browser_*`) will fail if invoked
- **Action:** Set keys in `.env` if browser automation is needed, or ignore if not used

### ISSUE 3: sounddevice Not Installed
- **Impact:** Voice input (microphone STT) unavailable
- **Action:** Install with `pip install sounddevice` in embedded Python if needed

### ISSUE 4: Honcho API Key Empty
- **Impact:** Cross-session user memory via Honcho is disabled
- **Config:** `honcho: {}` (empty config in user config)
- **Action:** Set `HONCHO_API_KEY` in `.env` if cross-session memory desired

### ISSUE 5: Compression Threshold Set Very Low
- **Config:** User set `compression.threshold: 0.5` (50%)
- **Default:** 0.85 (85%)
- **Impact:** Context will be compressed much earlier than normal. This may cause loss of conversation detail sooner than expected.
- **Action:** Intentional? If experiencing context issues, consider raising to 0.7-0.85.

### ISSUE 6: No Fallback Model Configured
- **Config:** `fallback_model` section is commented out
- **Impact:** If primary model (claude-opus-4.6 via OpenRouter) fails, no automatic failover
- **Action:** Uncomment and configure in `~/.hermes/config.yaml` if reliability is important

### ISSUE 7: Timezone Not Set
- **Config:** `timezone: ''` (empty)
- **Impact:** Agent uses system timezone. May cause issues with cron jobs or time-sensitive operations if system TZ is incorrect.

---

## EXTENSION SERVERS

### TTS Server (port 8100) - RUNNING
- Local OpenAI-compatible TTS endpoint
- Configured as `OPENAI_BASE_URL=http://127.0.0.1:8100`

### TTS Extension (port 8200) - NOT RUNNING
- Supports: Kokoro, XTTS, Dia, Bark, Fish + 5 more
- Requires 4GB+ GPU VRAM
- Launch from: `extensions/tts-server/`

### Music Extension (port 9150) - NOT RUNNING
- Supports: MusicGen, Stable Audio, ACE-Step, Riffusion
- Requires 4GB+ GPU VRAM
- Launch from: `extensions/music-server/`

### ComfyUI (port 8188) - NOT RUNNING
- Supports: SD 1.5, SDXL, Flux, 100+ registry models
- Requires 6GB+ GPU VRAM
- Launch from: `extensions/comfyui/`

---

## SKILLS INVENTORY (88+ installed in ~/.hermes/skills/)

**Categories:** apple, autonomous-ai-agents, creative, data-science, domain, email, feeds, gaming, gifs, github, leisure, mcp, media, mlops

---

## QUICK REFERENCE

| Action | Command |
|--------|---------|
| Launch GUI | `START.bat` |
| Launch CLI | `hermes.bat` |
| Run setup wizard | `hermes.bat setup` |
| Check config | `hermes.bat config show` |
| Doctor/diagnostics | `hermes.bat doctor` |
| Run with embedded Python | `run_py.bat <script.py>` |

---

*This log can be regenerated or updated by asking Claude Code to refresh it.*
