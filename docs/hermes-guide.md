# Hermes Agent - Complete User Guide

Welcome to Hermes Agent! This is a comprehensive guide that covers everything from your very first launch to building advanced automation pipelines. Whether you're completely new to AI or an experienced developer, this guide will walk you through every feature in detail.

No technical background is required. Every step is explained as if you've never done this before.

---

## Part 1: What is Hermes Agent?

### The Big Picture

Hermes Agent is a personal AI assistant that runs as a desktop application on your Windows computer. Unlike web-based AI chatbots (like ChatGPT), Hermes runs locally and can actually interact with your computer — reading files, running commands, browsing the web, generating images and music, and automating tasks.

Think of it as having a smart assistant sitting at your computer who can:

- **Answer questions** — about anything, using the latest AI models
- **Search the web** — find information, read articles, research topics
- **Work with files** — read, write, edit, and organize files on your computer
- **Browse websites** — navigate pages, fill forms, take screenshots
- **Generate images** — create artwork, logos, illustrations from text descriptions
- **Generate music** — compose songs, sound effects, jingles from descriptions
- **Generate speech** — convert text to natural-sounding audio with voice cloning
- **Run code** — write and execute Python scripts, automate repetitive tasks
- **Control local AI models** — load, manage, and switch between AI models on your GPU
- **Build custom tools** — create new capabilities on the fly
- **Automate workflows** — chain multiple actions into repeatable pipelines
- **Control smart home devices** — via Home Assistant integration
- **Send messages** — via Telegram, Discord, email, and more

### How It Works

Hermes connects to an AI model (either online or running locally on your GPU) and uses that model as its "brain" to understand your requests and decide what to do. The model can call "tools" — specialized functions that perform actions like searching the web, reading files, or generating images.

You type a message in plain English, and Hermes figures out what tools to use, in what order, to accomplish your request. It shows you what it's doing at each step.

### What You Need

**Minimum requirements:**
- Windows 10 or 11
- Internet connection (for cloud AI models)
- A free OpenRouter API key (takes 2 minutes to get)

**For local AI models (optional):**
- NVIDIA GPU with 8GB+ VRAM (RTX 3060 or better)
- LM Studio (free download from lmstudio.ai)

**For extensions (optional):**
- NVIDIA GPU with 4-6GB+ VRAM for TTS, Music, or Image generation

---

## Part 2: First Launch — Getting Started

### Step 1: Launch Hermes

Double-click `hermes.bat` or `hermes_gui.bat` to start the application. The main window will open centered on your screen.

You'll see:
- A **sidebar** on the left (for conversation sessions)
- A **chat area** in the center (where you'll talk to Hermes)
- An **input box** at the bottom (where you type messages)
- A **menu bar** at the top (File, Tools, Help)
- A **status bar** at the bottom (shows current model and status)

### Step 2: Connect to an AI Model

Hermes needs a connection to an AI model to function. You have two paths:

#### Path A: Cloud AI via OpenRouter (Easiest — 2 minutes, no GPU needed)

OpenRouter is a service that gives you access to dozens of AI models through a single API key. Many models are completely free.

1. The **API Setup Wizard** will open automatically on first launch
   - If it doesn't, go to **File > API Key Setup**
2. Click the **OpenRouter** row
3. Click **"Get Key"** — this opens the OpenRouter website in your browser
4. On the OpenRouter website:
   - Click **Sign Up** (you can use Google, GitHub, or email)
   - No credit card is required
   - After signing in, you'll see a **Dashboard**
   - Click **"Create Key"** (or go to the Keys page)
   - A key will appear that starts with `sk-or-...`
   - Click the copy button next to the key
5. Go back to the Hermes wizard
   - The key should auto-paste (Hermes watches your clipboard)
   - If it didn't, click **"Paste from Clipboard"**
   - Click **"Save & Next"**
6. You're connected! Start chatting.

**Which model should I use?**

The default model is `google/gemini-2.5-flash` which is:
- Completely free (no cost per message)
- Very fast (responds in 1-3 seconds)
- Smart enough for most tasks

Other good free options:
- `deepseek/deepseek-chat-v3` — excellent at reasoning and coding
- `meta-llama/llama-4-maverick` — Meta's latest open model

If you want the most capable models (small cost per message):
- `anthropic/claude-sonnet-4` — excellent at writing and analysis
- `google/gemini-2.5-pro` — great at complex reasoning
- `openai/gpt-4o` — OpenAI's flagship model

You can change your model anytime in **File > Settings > Model** tab.

#### Path B: Local AI via LM Studio (Private — needs NVIDIA GPU)

LM Studio lets you run AI models entirely on your own computer. Nothing is sent to the internet. This is ideal if you care about privacy or want to experiment with open-source models.

**Prerequisites:**
- NVIDIA GPU with at least 8GB VRAM (RTX 3060 or better)
- LM Studio installed (free from https://lmstudio.ai)

**Setup steps:**

1. **Download and install LM Studio** from https://lmstudio.ai
2. **Open LM Studio** and let it detect your GPU
3. **Download a model:**
   - In LM Studio, go to the **Discover** tab
   - Search for a model (recommendations below)
   - Click **Download** — it will download the model file (1-10 GB depending on model)
   - Wait for the download to complete
4. **Start the server:**
   - Go to the **Developer** tab in LM Studio
   - Click **Start Server**
   - Note the port number (default is 1234, yours might be different)
   - The server status should show "Running"
5. **Configure Hermes:**
   - In Hermes, go to **File > Settings**
   - In the **Model** tab, type the model name
   - Click **Save & Close**
   - Or, go to **Tools > LM Studio** to use the visual model manager

**Recommended starter models by GPU size:**

| Your GPU | Recommended Model | VRAM Used |
|----------|------------------|-----------|
| 8 GB (RTX 3060/4060) | Qwen 2.5 7B Q4 | ~5 GB |
| 8 GB | Phi-4 Mini Q8 | ~4 GB |
| 12 GB (RTX 3060 12GB) | Llama 3.1 8B Q6 | ~7 GB |
| 12 GB | Qwen 2.5 14B Q4 | ~9 GB |
| 24 GB (RTX 3090/4090) | Qwen 2.5 32B Q4 | ~20 GB |
| 24 GB | Llama 3.1 70B Q2 | ~22 GB |

**What do Q4, Q6, Q8 mean?**
These are quantization levels — how much the model is compressed:
- **Q4** = smallest file, fastest, slightly less accurate
- **Q6** = good balance of size and quality
- **Q8** = largest file, slowest, most accurate
- **FP16** = uncompressed (rarely needed, very large)

For most users, Q4 or Q6 is the sweet spot.

#### Path C: Both Cloud and Local (Recommended for power users)

You can have both configured and switch between them:
- Use cloud AI (OpenRouter) for complex tasks that need the smartest models
- Use local AI (LM Studio) for private conversations or offline work

To switch, just tell Hermes:
- "Switch to my local model" — uses LM Studio
- "Switch to OpenRouter" — uses cloud AI
- Or use **File > Settings** to change the model

### Step 3: Set Up Optional API Keys

Each key unlocks additional abilities. None of them are required — Hermes works with just the OpenRouter key. You can add these anytime later.

| Service | What It Unlocks | Free Tier | How to Get |
|---------|----------------|-----------|------------|
| **OpenRouter** | All AI conversations | Many free models | openrouter.ai/keys |
| **Firecrawl** | Web search + page reading | 500 credits/month | firecrawl.dev |
| **Serper** | Google-quality search results | 2,500 searches/month | serper.dev |
| **FAL.ai** | Image generation (FLUX) | $10 free credits | fal.ai/dashboard/keys |
| **Browserbase** | Cloud browser automation | 1000 sessions/month | browserbase.com |

To set up any key individually:
1. Go to **File > API Key Setup**
2. Click the **"Set up"** link next to any service
3. Follow the step-by-step instructions

---

## Part 3: The Interface in Detail

### The Chat Area

This is the main workspace. You type messages at the bottom and Hermes responds above.

**Sending messages:**
- Type your message and press **Enter** to send
- Press **Shift+Enter** to add a new line without sending
- Click the **Send** button as an alternative to Enter

**Attaching images:**
- Click the **paperclip button** next to Send (or press **Ctrl+Shift+I**)
- Select one or more image files (PNG, JPG, GIF, BMP, WEBP)
- Thumbnails appear above the input box
- Click the X on any thumbnail to remove it
- Type your message about the images and press Enter
- Requires a vision-capable model (Gemini, GPT-4o, or local LLaVA/Moondream)

**Message types you'll see:**
- **Your messages** — shown on the right side in a blue-tinted card
- **Hermes responses** — shown on the left in a green-tinted card, streamed token-by-token in real time
- **Tool calls** — shown as compact cards showing the tool name and arguments
- **System messages** — gray informational messages

**Streaming responses:**
- Hermes streams responses in real time — you see each word as it's generated
- A blinking cursor shows the response is still being generated
- The chat auto-scrolls as new text arrives

**Stopping a response:**
- Press **Escape** or click the **Stop** button to interrupt Hermes mid-response
- The partial response is kept and a "Generation stopped" message appears
- You can immediately send a new message

### The Sidebar

The sidebar shows your conversation history. Each conversation is a "session."

- **New Chat** — Click the + button or press **Ctrl+N**
- **Resume a conversation** — Click any session in the list
- **Rename a session** — Right-click > Rename
- **Delete a session** — Hover to reveal the X button, click to delete (confirmation dialog will appear)

Sessions are saved automatically. You can close and reopen Hermes without losing conversations. Deleting sessions removes the entry instantly and cleans up the database in the background.

### The Menu Bar

**File menu:**
- **New Chat** (Ctrl+N) — Start a fresh conversation
- **API Key Setup** — Open the setup wizard for API keys
- **Settings** (Ctrl+,) — Model selection, API keys
- **Quit** — Close Hermes

**View menu:**
- **LM Studio (Local Models)** — Visual model manager for local AI models
- **Skills Browser** — Browse and install skill packages
- **Extensions** — Install and manage add-on modules (TTS, Music, ComfyUI)
- **Toggle Sidebar** — Show or hide the sidebar

**Help menu:**
- **About** — Version information
- **Keyboard Shortcuts** — Quick reference

### The Status Bar

At the bottom of the window, shows:
- **Current model** — which AI model is active
- **Status** — Ready, Thinking, Error
- **Token count** — how many tokens the current conversation has used

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Enter** | Send message |
| **Shift+Enter** | New line (don't send) |
| **Escape** | Stop/interrupt the AI |
| **Ctrl+N** | New chat |
| **Ctrl+,** | Open settings |
| **Ctrl+Shift+I** | Attach image |

---

## Part 4: Permissions — Keeping You Safe

Hermes can interact with your computer, but you control exactly how much access it has. The permission system has five categories, each with five levels.

### How to Access

Go to **Tools > Permissions** to open the permission panel.

### Permission Categories

#### File Reading
Controls where Hermes can read files from.
- **Level 0 — Disabled**: Cannot read any files
- **Level 1 — App Only**: Can only read files inside the Hermes application folder
- **Level 2 — App + Home** (default): Can read files in the Hermes folder and your user folder (C:\Users\YourName)
- **Level 3 — Anywhere**: Can read any file on your computer
- **Level 4 — System**: Can read system files, configuration files, and registry

#### File Writing
Controls where Hermes can create or modify files.
- **Level 0 — Disabled**: Cannot write any files
- **Level 1 — App Only** (default): Can only write files inside the Hermes folder
- **Level 2 — App + Home**: Can write in the Hermes folder and your user folder
- **Level 3 — Anywhere**: Can write files anywhere
- **Level 4 — System**: Can modify system files (use with extreme caution)

#### Package Installation
Controls where software packages (Python libraries, etc.) can be installed.
- **Level 0 — Disabled**: Cannot install any packages
- **Level 1 — App Only** (default): Can only install into the portable Python that comes with Hermes
- **Level 2 — App + User**: Can install to the portable Python and your user-level packages
- **Level 3 — System-wide**: Can install packages system-wide
- **Level 4 — Admin**: Can install system services and drivers

#### Command Execution
Controls what commands Hermes can run in the terminal.
- **Level 0 — Disabled**: Cannot run any commands
- **Level 1 — App Only**: Can only run commands inside the Hermes folder
- **Level 2 — App + Safe** (default): Can run commands anywhere but no admin/system changes
- **Level 3 — Unrestricted**: Can run any command
- **Level 4 — Admin**: Can run elevated/administrator commands

#### File Deletion
Controls where Hermes can delete files.
- **Level 0 — Disabled**: Cannot delete any files
- **Level 1 — App Only** (default): Can only delete files inside the Hermes folder
- **Level 2 — App + Home**: Can delete in the Hermes folder and your user folder
- **Level 3 — Anywhere**: Can delete any file
- **Level 4 — System**: Can delete system files (dangerous!)

#### Network Access
Controls what network resources Hermes can access.
- **Level 0 — Offline**: No network access at all
- **Level 1 — Local Only**: Can only access localhost services (LM Studio, extensions)
- **Level 2 — Web + APIs** (default): Can browse web, call APIs, search online
- **Level 3 — Full Network**: Can access any network resource, SSH, etc.
- **Level 4 — Full + Listen**: Can open ports and accept incoming connections

### Recommended Settings

**For new users (safe defaults):**
Everything at Level 1-2. This lets Hermes work within its own folder and browse the web, but can't modify files outside the app.

**For power users:**
Read=3, Write=2, Execute=3, Network=3. This gives Hermes wide access to help with real work.

**For maximum capability:**
Everything at Level 3-4. Only do this if you trust the AI model and understand the risks.

---

## Part 5: LM Studio — Local AI Models

### What is LM Studio?

LM Studio is a free application that lets you run AI models directly on your computer using your NVIDIA GPU. Models run entirely locally — no data is sent to the internet.

### Why Use Local Models?

- **Privacy** — conversations stay on your computer
- **No cost** — no per-message fees after downloading the model
- **Offline** — works without internet
- **Speed** — can be faster than cloud for small models on a good GPU
- **Experimentation** — try different models, quantizations, and settings

### The LM Studio Panel

Open via **View > LM Studio (Local Models)** in the menu bar. The panel shows:

- **Endpoint field** — the LM Studio server address (default `http://localhost:1234`), with a Connect button to change it
- **Status indicator** — green dot = LM Studio is running and connected
- **Model browser** — list of all downloaded models with display names
- **GPU selector** — choose which GPU to load the model on
- **Context length slider** — minimum 32,768 tokens (Hermes needs ~26K for its tool definitions)
- **Load Model / Cancel Load** — load a model onto your GPU, or cancel a load in progress
- **Unload** — free GPU memory
- **Use for Chat** — switch Hermes to use the loaded model for all conversations

### Step-by-Step: Loading Your First Local Model

1. **Start LM Studio** — open LM Studio on your computer
2. **Download a model** if you haven't already:
   - In LM Studio, go to the Discover tab
   - Search for "Qwen 2.5 7B" (good starter model)
   - Click Download on a Q4 or Q6 quantization
3. **Open the LM Studio panel** in Hermes (**Tools > LM Studio**)
4. **Wait for status** — the green dot should appear showing LM Studio is connected
5. **Select your model** from the model browser list
6. **Choose your GPU** — if you have multiple GPUs, pick the one with more VRAM
7. **Set context length** — leave at 32,768 (minimum required) or increase if your GPU has room
8. **Click Load Model** — the model loads into your GPU memory (click Cancel Load if it hangs)
9. **Click Use for Chat** — Hermes switches to using this model
10. **Start chatting!** — your messages now go to the local model

### Understanding VRAM (GPU Memory)

Your GPU has a fixed amount of VRAM. Models need to fit in VRAM to run:

| Model Parameters | Q4 VRAM | Q6 VRAM | Q8 VRAM |
|-----------------|---------|---------|---------|
| 1-3 Billion | ~2 GB | ~2.5 GB | ~3 GB |
| 7-8 Billion | ~4 GB | ~6 GB | ~8 GB |
| 13-14 Billion | ~7 GB | ~10 GB | ~13 GB |
| 27-34 Billion | ~18 GB | ~24 GB | ~34 GB |
| 70 Billion | ~40 GB | ~55 GB | ~70 GB |

Context length also uses VRAM. Higher context = more VRAM used.

**Example:** You have an RTX 3060 with 12 GB VRAM.
- Qwen 2.5 7B Q6 = ~6 GB + ~1 GB for context = fits easily
- Qwen 2.5 14B Q4 = ~9 GB + ~1 GB for context = fits tightly
- Llama 3.1 70B = too large, won't fit

### GPU Isolation (Multi-GPU Systems)

If you have multiple GPUs, Hermes loads models on a single GPU to prevent "model splitting" — where a model is spread across GPUs, which hurts performance.

When you select a GPU in the LM Studio panel or use the `lm_studio_load` tool, Hermes automatically disables all other GPUs for that load to force single-GPU loading.

### LM Studio Tools (Available in Chat)

When LM Studio is running, these tools become available:

| Tool | What to Say | What It Does |
|------|------------|--------------|
| `lm_studio_status` | "Check LM Studio" | Shows if it's running, loaded models, GPU memory |
| `lm_studio_models` | "List my local models" | Shows all downloaded models |
| `lm_studio_load` | "Load Qwen 7B on my 3090" | Loads a model onto a specific GPU |
| `lm_studio_unload` | "Unload the current model" | Frees GPU memory |
| `lm_studio_search` | "Search for Llama models" | Searches HuggingFace for downloadable models |
| `lm_studio_download` | "Download that model" | Downloads a model from HuggingFace |
| `lm_studio_model_info` | "What model is loaded?" | Shows loaded model details (context, config) |
| `lm_studio_tokenize` | "How many tokens in this text?" | Counts tokens in text |
| `lm_studio_embed` | "Generate embeddings for this text" | Creates vector embeddings |
| `lm_studio_chat` | "Ask the local model: what is 2+2?" | Sends a prompt directly to a loaded model |

### Switching Between Cloud and Local

You can switch at any time through the UI:

**To local model:**
1. Open **View > LM Studio (Local Models)**
2. Load your model and click **Use for Chat**
3. Hermes automatically switches to local mode

**To cloud (OpenRouter):**
- Select any cloud model from the sidebar dropdown (e.g. Gemini Flash, Claude Sonnet)
- Hermes automatically switches back to OpenRouter

The switch is instant — no need to change settings or edit config files. Hermes tracks which provider is active internally.

### Troubleshooting LM Studio

**"LM Studio not running" or "Connection refused":**
- Make sure LM Studio is open and the server is started (Developer tab)
- Check the port number — it should match what Hermes expects
- The port is auto-detected from your `OPENAI_BASE_URL` in `.env`

**"Model won't load — out of memory":**
- Try a smaller quantization (Q4 instead of Q8)
- Reduce context length (4096 instead of 8192)
- Close other GPU-intensive applications
- Check GPU memory with the `gpu_info` tool

**"Responses are very slow":**
- Reduce context length (smaller = faster)
- Use a smaller model
- Make sure no other models are loaded (check with `lm_studio_status`)

**"Model gives bad/random responses":**
- Try a different model — quality varies significantly between models
- Increase context length if conversations are being cut off
- Make sure you're using an "instruct" or "chat" variant, not a base model

---

## Part 6: Extensions — TTS, Music, and Image Generation

Hermes supports three powerful extension modules that add local AI generation capabilities. Each extension is a separate server that runs alongside Hermes.

### How Extensions Work

Each extension is:
- **Portable** — nothing is installed system-wide, everything stays in the `extensions/` folder
- **Self-installing** — downloads its own Python environment, dependencies, and model weights
- **GPU-accelerated** — uses your NVIDIA GPU for fast generation
- **Server-based** — runs as a local web server that Hermes talks to via tools

### Managing Extensions

Go to **Tools > Extensions** in the menu bar to:
- See which extensions are installed
- Install new extensions
- Start/stop extension servers
- Check server status

---

### Extension 1: TTS Server (Text-to-Speech)

The TTS Server converts text to natural-sounding speech. It supports 10 different AI voice models, voice cloning, multi-language support, and emotional expression.

**Server port:** 8200 (configurable via `TTS_SERVER_URL` environment variable)

#### Installation

1. Go to **Tools > Extensions**
2. Click **Install** next to "Text-to-Speech Server"
3. Wait for the installation to complete (downloads ~2-5 GB depending on models)
4. Click **Start** to launch the server

Or install manually:
```
cd extensions/tts-server
install.bat
launcher.bat api
```

#### Available TTS Models

| Model | Size | Best For | Voice Cloning | Languages | GPU VRAM |
|-------|------|----------|--------------|-----------|----------|
| **kokoro** | 82M | Fast English TTS, 54 built-in voices | No (preset voices only) | English | ~1 GB |
| **xtts** | 500M | General purpose, best multilingual | Yes (from WAV/MP3 reference) | 17 languages | ~2 GB |
| **dia** | 1.6B | Two-speaker dialogue with emotions | No (uses [S1]/[S2] tags) | English | ~4 GB |
| **bark** | 1B | Expressive speech with laughter, music, non-verbal sounds | No (preset voices) | Multilingual | ~3 GB |
| **fish** | 500M | Fast voice cloning with minimal reference audio | Yes (few seconds of audio) | Multilingual | ~2 GB |
| **chatterbox** | 500M | Conversational with emotion control | Yes | English | ~2 GB |
| **f5** | 300M | Diffusion-based high-quality cloning | Yes | Multilingual | ~2 GB |
| **qwen** | 7B | Chinese + English bilingual | Yes | Chinese, English | ~8 GB |
| **vibevoice** | 1.5B | Wide emotional range | Yes | English | ~4 GB |
| **higgs** | 3B | Works on CPU (no GPU needed) | Yes | English | CPU or ~3 GB |

#### How to Use TTS

**Simple text-to-speech:**
Say: "Read this text aloud: Hello, welcome to Hermes Agent!"
Or: "Generate speech saying 'The quick brown fox jumps over the lazy dog' using Kokoro"

**With a specific voice:**
Say: "Generate speech with the af_heart voice: I love this application"

**Dialogue with Dia model:**
Say: "Generate a dialogue: [S1] Hey, how's it going? [S2] (laughs) I'm doing great! [S1] That's wonderful to hear."

The `[S1]` and `[S2]` tags mark different speakers. Dia automatically uses different voices for each speaker and can express emotions in parentheses.

**Voice cloning (xtts, fish, f5):**
1. Place a reference audio file (WAV or MP3, 5-30 seconds of clear speech) in:
   ```
   extensions/tts-server/voices/
   ```
2. Say: "Generate speech using xtts with voice 'my_voice.wav': Hello, this is my cloned voice"

#### TTS Tools Reference

| Tool | How to Use It |
|------|--------------|
| `tts_server_status` | "Is the TTS server running?" |
| `tts_server_generate` | "Generate speech: [your text]" with optional model and voice |
| `tts_server_models` | "What TTS models are available?" |
| `tts_server_model_load` | "Load the xtts model" |
| `tts_server_model_unload` | "Unload the TTS model to free GPU memory" |
| `tts_server_voices` | "List available voices for Kokoro" |
| `tts_server_jobs` | "Show TTS generation jobs" |

#### TTS Troubleshooting

**"TTS server unreachable":**
- Make sure the TTS server is running (check **Tools > Extensions**)
- Start it with `launcher.bat api` in the `extensions/tts-server/` folder
- Check that the port (8200) isn't being used by another application

**"Model not loaded":**
- The server needs to load a model before generating speech
- Say "Load the kokoro model" or use the `tts_server_model_load` tool
- First-time loading downloads model weights (~1-8 GB depending on model)

**"Out of GPU memory":**
- Unload other models (LM Studio models, other TTS models)
- Use a smaller model (kokoro is smallest at 82M)
- Use higgs if you want to run on CPU without GPU

**Audio sounds robotic/bad:**
- Try a different model — each model has different strengths
- For English, kokoro and xtts produce the best quality
- For emotional expression, dia or bark are best
- Make sure the text is clear and properly punctuated

---

### Extension 2: Music Server

The Music Server generates music, songs, and sound effects from text descriptions. Describe what you want to hear, and it creates an audio file.

**Server port:** 9150

#### Installation

1. Go to **Tools > Extensions**
2. Click **Install** next to "Music Generation Server"
3. Wait for the installation to complete
4. Click **Start** to launch the server

Or install manually:
```
cd extensions/music-server
install.bat
launcher.bat api
```

#### Available Music Models

| Model | Best For | Duration | GPU VRAM |
|-------|----------|----------|----------|
| **musicgen** | General music from text prompts | 5-30 sec | ~4 GB |
| **musicgen-large** | Higher quality music | 5-30 sec | ~8 GB |
| **stable_audio** | High-quality, longer music | 5-90 sec | ~6 GB |
| **ace_step** | Fast music with style control | 5-60 sec | ~4 GB |
| **riffusion** | Spectrogram-based (unique sound) | 5-15 sec | ~4 GB |
| **audioldm2** | Music + sound effects | 5-30 sec | ~6 GB |

#### How to Generate Music

**Simple prompt:**
Say: "Generate 30 seconds of upbeat electronic dance music with synths and a driving beat"

**Specific genre:**
Say: "Generate a calm acoustic guitar melody with light percussion, 20 seconds"

**Sound effects:**
Say: "Generate the sound of rain falling on a tin roof with distant thunder"

**With model selection:**
Say: "Generate music using stable_audio: epic orchestral film soundtrack, 60 seconds"

#### Music Tools Reference

| Tool | How to Use It |
|------|--------------|
| `music_status` | "Is the music server running?" |
| `music_generate` | "Generate music: [description]" with optional model and duration |
| `music_models` | "What music models are available?" |
| `music_model_load` | "Load the musicgen model" |
| `music_model_unload` | "Unload the music model" |
| `music_outputs` | "Show my generated music files" |
| `music_install` | "Install the stable_audio model" |

#### Music Tips

- **Be descriptive** — "upbeat jazz with saxophone solo and walking bass" works better than "jazz music"
- **Specify instruments** — mention specific instruments for better results
- **Set duration** — start with 10-15 seconds to test, then increase
- **Try different models** — each model has a different sound character
- Generated audio files are saved in `extensions/music-server/output/`

#### Music Troubleshooting

**"Music server unreachable":**
- Start the server with `launcher.bat api` in `extensions/music-server/`
- Check that port 9150 isn't in use

**"No music model loaded":**
- Say "Load the musicgen model" before generating
- First-time loading downloads model weights

**Generated music sounds bad:**
- Try a more specific prompt
- Try a different model
- Some models work better for certain genres

---

### Extension 3: ComfyUI (Image Generation)

ComfyUI is a powerful image generation system based on Stable Diffusion. It can create images, edit photos, generate video frames, and more using a visual workflow editor.

**Management API port:** 5000
**ComfyUI instance ports:** 8188+

#### Installation

1. Go to **Tools > Extensions**
2. Click **Install** next to "ComfyUI Image Generator"
3. Wait for the installation to complete (downloads ~3-5 GB for base install)
4. Click **Start** to launch the management server

Or install manually:
```
cd extensions/comfyui
install.bat
launcher.bat
```

#### How ComfyUI Works

ComfyUI has two layers:
1. **Management Server** (port 5000) — manages instances, models, and custom nodes
2. **ComfyUI Instances** (port 8188+) — the actual image generation servers

Each GPU can run its own instance. If you have two GPUs, you can have two instances generating images simultaneously.

#### Available Model Types

| Category | Examples | What It Does |
|----------|----------|-------------|
| **Checkpoints** | SD 1.5, SDXL, Flux | Base image generation models |
| **LoRAs** | Style LoRAs, Character LoRAs | Fine-tuned additions for specific styles |
| **VAEs** | SDXL VAE, SD VAE | Encoder/decoder for better image quality |
| **ControlNet** | Canny, Depth, Pose | Guide generation with reference images |
| **Upscalers** | RealESRGAN, SwinIR | Increase image resolution |

The model registry has 100+ pre-defined models you can download with one click.

#### How to Generate Images

**Simple prompt:**
Say: "Generate an image of a sunset over mountains with dramatic clouds"

**With settings:**
Say: "Generate a 1024x768 image of a cyberpunk city at night, 30 steps, high detail"

**Through the web UI:**
1. Open your browser to `http://localhost:8188`
2. You'll see the visual workflow editor
3. Build or load a workflow
4. Click "Queue Prompt" to generate

#### ComfyUI Tools Reference

| Tool | How to Use It |
|------|--------------|
| `comfyui_status` | "Is ComfyUI running?" |
| `comfyui_instances` | "List ComfyUI instances" |
| `comfyui_instance_start` | "Start a ComfyUI instance on GPU 0" |
| `comfyui_instance_stop` | "Stop the ComfyUI instance" |
| `comfyui_generate` | "Generate an image: [description]" |
| `comfyui_models` | "List available ComfyUI models" |
| `comfyui_nodes` | "List installed ComfyUI nodes" |

#### ComfyUI Troubleshooting

**"ComfyUI unreachable":**
- Start the management server with `launcher.bat` in `extensions/comfyui/`
- Check that ports 5000 and 8188 aren't in use

**"No checkpoints installed":**
- You need to download at least one checkpoint model
- Say "List ComfyUI models" to see what's available in the registry
- Download via the management API or web UI

**Images look bad or distorted:**
- Try different prompts — be more specific
- Increase step count (20-30 is usually good)
- Try a different checkpoint model
- Adjust CFG scale (7-9 is typical)

---

## Part 7: All Tools — Complete Reference

Hermes has 100 tools organized into categories. Each tool is a specific capability that Hermes can use to accomplish your requests. You don't need to remember tool names — just describe what you want and Hermes will pick the right tool.

### Web and Search Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **web_search** | Search the web for information | Firecrawl API key |
| **web_extract** | Read and extract content from a web page URL | Firecrawl API key |
| **serper_search** | Google-quality search with knowledge graphs and direct answers | Serper API key |

**Example requests:**
- "Search for the best restaurants in Portland"
- "Read this article: [URL]"
- "Find recent news about artificial intelligence"

### File Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **read_file** | Read contents of any file | File Read permission |
| **write_file** | Create or overwrite a file | File Write permission |
| **patch** | Make targeted edits to a file | File Write permission |
| **search_files** | Find files by name or search contents | File Read permission |

**Example requests:**
- "Read the file at C:\Users\me\notes.txt"
- "Create a new Python script called hello.py"
- "Find all PDF files in my Documents folder"
- "Replace 'old text' with 'new text' in config.json"

### Terminal and System Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **terminal** | Run shell commands | Execute permission |
| **process** | List, monitor, or kill processes | Execute permission |
| **run_python** | Execute Python code directly | None (uses built-in Python) |
| **gpu_info** | Show GPU status (memory, temp, usage) | NVIDIA GPU |
| **execute_code** | Run sandboxed code that can call other tools | Execute permission |

**Example requests:**
- "Run 'dir /s *.txt' to find all text files"
- "What processes are using the most CPU?"
- "Run this Python code: print('hello')"
- "How much GPU memory is free?"

### Vision and Image Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **vision_analyze** | Analyze/describe an image using AI vision | Vision-capable model |
| **image_generate** | Generate images from text descriptions | FAL.ai API key |

**Example requests:**
- "What's in this image?" (with image attached)
- "Generate an image of a golden retriever wearing sunglasses"

### Browser Automation Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **browser_navigate** | Open a URL in a controlled browser | Network permission |
| **browser_snapshot** | Screenshot + accessibility tree of current page | Active browser |
| **browser_click** | Click a page element | Active browser |
| **browser_type** | Type text into a form field | Active browser |
| **browser_scroll** | Scroll the page | Active browser |
| **browser_back** | Go to previous page | Active browser |
| **browser_press** | Press a keyboard key | Active browser |
| **browser_close** | Close the browser | Active browser |
| **browser_get_images** | Extract all images from a page | Active browser |
| **browser_vision** | Analyze screenshot with AI vision | Active browser + vision model |

**Example requests:**
- "Go to google.com and search for weather in my city"
- "Navigate to that product page and read the reviews"
- "Take a screenshot of the current page"

### Text-to-Speech Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **text_to_speech** | Built-in TTS using Edge/ElevenLabs/OpenAI | None (Edge TTS is built-in) |

Plus all the TTS Server tools (see Extension 1 section above).

### LM Studio Tools

See Part 5 for complete details on all 10 LM Studio tools.

### AI and Reasoning Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **mixture_of_agents** | Ask multiple AI models and synthesize answers | OpenRouter key |
| **delegate_task** | Spawn a sub-agent for isolated tasks | None |
| **switch_model** | Change the active AI model | None |

**Example requests:**
- "Use mixture of agents to analyze this complex problem from multiple angles"
- "Delegate this research task to a sub-agent"
- "Switch to the Claude Sonnet model"

### Planning and Memory Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **todo** | Task list for multi-step projects | None |
| **memory** | Persistent notes across sessions | None |
| **session_search** | Search past conversations | None |
| **clarify** | Ask you a clarifying question | None |

### Scheduling and Automation Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **cronjob** | Schedule recurring tasks | None |
| **workflow_create** | Build multi-step automation pipelines | None |
| **workflow_run** | Execute a saved workflow | None |
| **workflow_list** | List all saved workflows | None |
| **workflow_show** | View workflow details | None |
| **workflow_delete** | Remove a workflow | None |
| **workflow_schedule** | Schedule a workflow on a timer | None |

### Tool Creation Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **create_tool** | Dynamically create a new tool | None |
| **delete_tool** | Remove a custom tool | None |
| **list_custom_tools** | Show all custom tools | None |

### System Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **update_hermes** | Pull latest updates from upstream | Git |
| **check_hermes_updates** | Check if updates are available | Git |
| **search_guide** | Search this user guide | None |

### Messaging Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **send_message** | Send messages via Telegram, Discord, etc. | Gateway configured |

### Smart Home Tools

| Tool | What It Does | Requirements |
|------|-------------|-------------|
| **ha_list_entities** | List Home Assistant devices | HASS_TOKEN |
| **ha_get_state** | Check device state | HASS_TOKEN |
| **ha_list_services** | List available services | HASS_TOKEN |
| **ha_call_service** | Control a device | HASS_TOKEN |

---

## Part 8: Custom Tools — Build Your Own

One of Hermes' most powerful features is the ability to create new tools on the fly. This means you can extend Hermes' capabilities without programming knowledge — just describe what you want.

### API Wrapper Tools

Wrap any web API as a Hermes tool. You give it a URL, HTTP method, and parameters, and it generates a tool that calls that API.

**Example: Weather API tool**
Say: "Create a tool called 'get_weather' that calls https://api.openweathermap.org/data/2.5/weather with a 'q' query parameter for the city name"

After creation, you can say: "Get the weather in Portland" and Hermes will use your new tool.

**Example: Discord webhook tool**
Say: "Create a tool that posts messages to my Discord webhook at [URL]"

**Example: Stock price tool**
Say: "Create a tool that fetches stock prices from the Yahoo Finance API"

### Custom Code Tools

Write arbitrary Python logic as a tool. You describe the parameters and the code, and Hermes generates a working tool.

**Example: File size calculator**
Say: "Create a tool called 'dir_size' that takes a path and returns the total size of all files in that directory in MB"

**Example: Text statistics**
Say: "Create a tool that counts words, sentences, and paragraphs in text"

### Managing Custom Tools

- Custom tools persist across sessions (saved in `tools/custom/`)
- Say "List my custom tools" to see what you've created
- Say "Delete the [tool_name] tool" to remove one
- Custom tools reload automatically when Hermes restarts

---

## Part 9: Workflows — Automate Multi-Step Tasks

Workflows let you chain multiple tool calls together into automated pipelines. Think of them as recipes — a series of steps that run in order, passing data from one step to the next.

### Creating a Workflow

Just describe what you want automated:

**Example: Morning briefing**
Say: "Create a workflow called 'morning-briefing' that searches for today's top news, summarizes it, and reads it aloud with TTS"

**Example: GPU health check**
Say: "Create a workflow that checks GPU status, lists loaded models, and reports the results"

**Example: Model loader**
Say: "Create a workflow called 'load-qwen' that checks GPU memory, loads Qwen 7B on GPU 1 with 8192 context, and runs a test prompt"

### Workflow Features

**Data flow between steps:**
Each step can use the output of previous steps. For example, step 2 can use the search results from step 1.

**Conditional steps:**
Steps can be skipped based on conditions. For example: "Only load the model if GPU has more than 6GB free."

**Loops:**
Steps can repeat over a list. For example: "For each loaded model, get its info and print a summary."

**Error handling:**
Steps can be configured to continue, skip, or stop on error.

**Parallel execution:**
Independent steps can run simultaneously for faster completion.

**Scheduling:**
Workflows can be scheduled to run automatically on a timer (daily, hourly, etc.).

### Managing Workflows

| Command | What It Does |
|---------|-------------|
| "List my workflows" | Shows all saved workflows |
| "Show the [name] workflow" | Displays the workflow steps |
| "Run the [name] workflow" | Executes the workflow |
| "Schedule [name] to run at 8am daily" | Sets up automatic execution |
| "Delete the [name] workflow" | Removes the workflow |

Workflows are saved as JSON files in the `workflows/` directory.

---

## Part 10: Settings Reference

### Environment Variables (.env file)

The `.env` file is for **API keys only**. Model selection, LM Studio settings, GPU preferences, and other runtime state are managed through the GUI — not through environment variables.

**API keys:**

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key (required for cloud models) | `sk-or-v1-...` |
| `FIRECRAWL_API_KEY` | Web search and page reading | |
| `SERPER_API_KEY` | Google search via Serper.dev | |
| `FAL_KEY` | Image generation (FAL.ai) | |
| `BROWSERBASE_API_KEY` | Cloud browser automation | |
| `GITHUB_TOKEN` | Skills Hub (higher rate limits) | |

**Extension ports (optional):**

| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_SERVER_URL` | `http://localhost:8200` | TTS server address |
| `MUSIC_SERVER_URL` | `http://localhost:9150` | Music server address |
| `COMFYUI_URL` | `http://localhost:8188` | ComfyUI address |

### Runtime Settings (managed by GUI)

These settings are selected through the interface and do not need to be edited manually:

- **Active model** — selected from the sidebar dropdown or LM Studio panel
- **Cloud vs Local provider** — automatically set when you pick a cloud model or click "Use for Chat" in LM Studio
- **LM Studio endpoint** — configured in the LM Studio panel's Endpoint field
- **GPU selection, context length, temperature** — configured in the sidebar's local model settings or the LM Studio panel

---

## Glossary

| Term | Plain English Explanation |
|------|--------------------------|
| **API** | A way for programs to talk to each other. An API key is like a password that lets Hermes use an online service. |
| **API Key** | A long code (like a password) that gives Hermes permission to use an online service. You get these from the service's website. |
| **Model** | The AI "brain." Different models are good at different things. Think of them like different experts — one might be great at writing, another at math. |
| **GPU** | Your graphics card. Originally designed for gaming, but perfect for running AI models. NVIDIA GPUs are required for local AI. |
| **VRAM** | Memory on your GPU. Determines how big an AI model you can run. More VRAM = bigger/smarter models. |
| **Token** | A piece of text, roughly 4 characters or 3/4 of a word. AI models process text in tokens. "Hello world" = 2 tokens. |
| **Context Length** | How much text the AI can "see" at once. Like the AI's short-term memory. 4096 tokens ≈ 3,000 words. |
| **GGUF** | A file format for AI models that run on your computer. Like .mp3 is for music, .gguf is for AI models. |
| **Quantization** | Compression for AI models. Q4 = very compressed (small, fast), Q8 = light compression (bigger, more accurate). Like JPEG quality settings for images. |
| **Inference** | When the AI generates a response. "Running inference" = "the AI is thinking." |
| **Tool** | A specific action Hermes can take — like searching the web, reading a file, or generating an image. Hermes has 100 tools. |
| **Toolset** | A group of related tools. The "web" toolset includes web_search and web_extract. |
| **Workflow** | A saved sequence of tool calls that run automatically. Like a macro or recipe. |
| **Extension** | An add-on module that gives Hermes new abilities (TTS, Music, Image Generation). Each is a separate program that runs alongside Hermes. |
| **OpenRouter** | An online service that lets you use many different AI models through one API key. Like a universal remote for AI. |
| **LM Studio** | A free program for running AI models on your own computer. Like a music player, but for AI models. |
| **Prompt** | The text you send to an AI model. Your message is the prompt. |
| **Streaming** | When the AI response appears word-by-word instead of all at once. |
| **Session** | A single conversation from start to finish. Each session is saved separately. |
| **Sub-agent** | A separate AI instance that Hermes creates to work on a specific task, then reports back. Like delegating work to an assistant. |

---

## Getting Help

- **Ask Hermes!** Type your question in the chat — Hermes can search this guide for answers using the `search_guide` tool
- **File > API Key Setup** — Check which services are connected
- **Tools > Permissions** — Adjust what Hermes can do if something is blocked
- **Tools > Extensions** — Check if extension servers are running
- **Tools > LM Studio** — Manage local AI models
- Visit the GitHub repository for bug reports and feature requests
