"""
Hermes Agent - Bridge between AIAgent and tkinter GUI.
Handles threading, callbacks, event marshalling, and session persistence.
Matches CLI feature parity.
"""
import os
import sys
import re
import uuid
import queue
import threading
import traceback
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment before anything else
from dotenv import load_dotenv
_hermes_home = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
_user_env = _hermes_home / ".env"
_project_env = PROJECT_ROOT / ".env"
if _user_env.exists():
    load_dotenv(dotenv_path=_user_env, encoding="utf-8")
elif _project_env.exists():
    load_dotenv(dotenv_path=_project_env, encoding="utf-8")


def _load_cli_config() -> dict:
    """Load configuration from config.yaml (same logic as CLI)."""
    import yaml
    user_config = _hermes_home / "config.yaml"
    project_config = PROJECT_ROOT / "cli-config.yaml"
    config_path = user_config if user_config.exists() else project_config

    defaults = {
        "model": {"default": "google/gemini-2.5-flash"},
        "agent": {"max_turns": 90},
        "compression": {"enabled": True, "threshold": 0.5},
        "display": {"show_reasoning": False},
    }

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}
            # Handle model as string or dict
            if "model" in file_config:
                if isinstance(file_config["model"], str):
                    defaults["model"]["default"] = file_config["model"]
                elif isinstance(file_config["model"], dict):
                    defaults["model"].update(file_config["model"])
                del file_config["model"]
            # Merge rest
            for key in file_config:
                if key in defaults and isinstance(defaults[key], dict) and isinstance(file_config[key], dict):
                    defaults[key].update(file_config[key])
                elif key not in defaults or not isinstance(defaults.get(key), dict):
                    defaults[key] = file_config[key]
        except Exception:
            pass

    return defaults


class AgentBridge:
    """Bridge between AIAgent and the GUI. Full CLI feature parity."""

    def __init__(self, root, on_response=None, on_tool_call=None,
                 on_thinking=None, on_error=None, on_step=None,
                 on_clarify=None, on_complete=None, on_approval=None,
                 on_reasoning=None, on_stream_delta=None):
        self.root = root
        self.on_response = on_response
        self.on_tool_call = on_tool_call
        self.on_thinking = on_thinking
        self.on_error = on_error
        self.on_step = on_step
        self.on_clarify = on_clarify
        self.on_complete = on_complete
        self.on_approval = on_approval
        self.on_reasoning = on_reasoning
        self.on_stream_delta = on_stream_delta

        self.agent = None
        self.conversation_history: List[Dict[str, Any]] = []
        self.session_id: Optional[str] = None
        self.is_running = False
        self._agent_thread: Optional[threading.Thread] = None
        self._clarify_queue = queue.Queue()
        self._approval_queue = queue.Queue()
        self._interrupted = False
        self._lm_studio_base_url: Optional[str] = None
        self._known_local_models: set = set()  # Model IDs discovered from LM Studio
        self._active_provider: str = "cloud"  # "cloud" or "local"
        self._startup_fallback = False  # True if we fell back from a local model

        # Load config (same as CLI)
        self.config = _load_cli_config()

        # Session database for persistence
        try:
            from hermes_state import SessionDB
            self._session_db = SessionDB()
        except Exception:
            self._session_db = None

        # Set critical environment variables (matching CLI)
        # Use YOLO mode for GUI — the approval system's prompt_dangerous_approval()
        # is a CLI-only function that blocks on terminal input. The GUI has no
        # equivalent interactive terminal, so commands would silently fail.
        # Instead we auto-approve and rely on the permissions system for safety.
        os.environ["HERMES_YOLO_MODE"] = "1"
        os.environ["HERMES_INTERACTIVE"] = "1"
        os.environ.setdefault("HERMES_REDACT_SECRETS", "1")

        # Lock all Python/pip operations to portable Python
        self.python_dir = PROJECT_ROOT / "python_embedded"
        python_dir = self.python_dir
        scripts_dir = python_dir / "Scripts"
        site_packages = python_dir / "Lib" / "site-packages"
        node_bin = PROJECT_ROOT / "node_modules" / ".bin"

        current_path = os.environ.get("PATH", "")
        portable_paths = f"{python_dir};{scripts_dir};{node_bin}"
        if str(python_dir) not in current_path:
            os.environ["PATH"] = f"{portable_paths};{current_path}"

        # PIP_TARGET and PIP_PREFIX conflict with each other — use only PIP_TARGET
        # which forces all installs into portable site-packages
        os.environ["PIP_TARGET"] = str(site_packages)
        os.environ.pop("PIP_PREFIX", None)  # Remove to avoid conflict
        os.environ["PYTHONPATH"] = str(site_packages)
        os.environ.setdefault("TERMINAL_CWD", str(PROJECT_ROOT))

        # Wire up approval callback for dangerous command detection
        try:
            from tools.approval import set_approval_callback
            set_approval_callback(self._approval_callback)
        except Exception:
            pass

    def _is_local_model(self, model: str = None) -> bool:
        """Check if the active provider is local (LM Studio)."""
        return self._active_provider == "local"

    def set_local_mode(self, base_url: str, model_id: str):
        """Switch to LM Studio as the active provider."""
        self._active_provider = "local"
        self._lm_studio_base_url = base_url.rstrip("/")
        self._selected_model = model_id
        self.agent = None  # Force recreation

    def set_cloud_mode(self, model: str):
        """Switch to OpenRouter as the active provider."""
        self._active_provider = "cloud"
        self._lm_studio_base_url = None
        self._selected_model = model
        self.agent = None

    def register_local_models(self, model_ids: list):
        """Register model IDs discovered from LM Studio so routing works correctly."""
        self._known_local_models = set(model_ids)


    def _resolve_lm_studio_url(self) -> Optional[str]:
        """Probe LM Studio and return its OpenAI-compatible base URL if running, else None.

        Returns the URL as configured — no /v1 mangling.
        """
        try:
            from gui.lm_studio import LMStudioPanel
            url = LMStudioPanel._resolve_base_url()
            from gui.lm_studio import LMStudioClient
            client = LMStudioClient(base_url=url)
            if client.is_running():
                return url.rstrip("/")
        except Exception:
            pass
        return None

    def _validate_startup_model(self):
        """Detect LM Studio on startup and register any discovered models.
        Default is always cloud mode — user switches to local via UI.
        """
        self._active_provider = "cloud"

        # Probe LM Studio in case it's running — register models for sidebar
        url = self._resolve_lm_studio_url()
        if url:
            try:
                from gui.lm_studio import LMStudioClient
                client = LMStudioClient(base_url=url)
                for m in client.list_models_api():
                    mid = m.get("id", "")
                    if mid:
                        self._known_local_models.add(mid)
            except Exception:
                pass

    def get_model(self) -> str:
        if not hasattr(self, '_selected_model') or not self._selected_model:
            self._selected_model = self.config.get("model", {}).get("default", "google/gemini-2.5-flash")
        return self._selected_model

    def get_api_key(self) -> str:
        return os.getenv("OPENROUTER_API_KEY", "")

    def _create_agent(self):
        from run_agent import AIAgent
        model = self.get_model()
        api_key = self.get_api_key()
        agent_config = self.config.get("agent", {})

        # Only disable what's truly broken on Windows
        disabled = ["code_execution"]

        # Route based on active provider
        if self._active_provider == "local" and self._lm_studio_base_url:
            # OpenAI SDK expects /v1 suffix for API calls
            lm_url = self._lm_studio_base_url.rstrip("/")
            base_url = lm_url if lm_url.endswith("/v1") else lm_url + "/v1"
        else:
            base_url = None

        # Generate session ID
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]

        # Create session in database
        if self._session_db:
            try:
                self._session_db.create_session(
                    session_id=self.session_id,
                    source="gui",
                    model=model,
                )
            except Exception:
                pass

        # Provider routing from config
        routing = self.config.get("provider_routing", {})

        # Reasoning config from config
        reasoning_config = None
        reasoning_effort = agent_config.get("reasoning_effort")
        if reasoning_effort:
            if reasoning_effort == "none":
                reasoning_config = {"enabled": False}
            else:
                reasoning_config = {"enabled": True, "effort": reasoning_effort}

        # Fallback model from config
        fallback = self.config.get("fallback_model")

        # Build ephemeral system prompt with permissions and environment info
        prompt_parts = []

        # Permissions
        try:
            from gui.permissions import get_permissions_summary
            prompt_parts.append(get_permissions_summary())
        except Exception:
            pass

        # CRITICAL: Tell the agent about the actual OS and environment
        import platform
        os_name = platform.system()  # "Windows", "Linux", "Darwin"
        os_version = platform.version()
        os_release = platform.release()

        # Detect GPUs
        gpu_info = ""
        try:
            import subprocess as _sp
            _r = _sp.run(
                ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if _r.returncode == 0:
                gpu_lines = []
                for line in _r.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        gpu_lines.append(
                            f"  - GPU {parts[0]}: {parts[1]} ({parts[3]} MiB free / {parts[2]} MiB total)")
                if gpu_lines:
                    gpu_info = "**GPUs available:**\n" + "\n".join(gpu_lines)
        except Exception:
            gpu_info = "**GPU:** Could not detect (nvidia-smi not found)"

        # Compute bash-compatible paths (terminal uses Git Bash on Windows)
        py_win = str(self.python_dir / "python.exe")
        # Convert E:\hermes\python_embedded\python.exe -> /e/hermes/python_embedded/python.exe
        py_bash = "/" + py_win.replace("\\", "/").replace(":", "", 1)
        py_bash = py_bash[0] + py_bash[1].lower() + py_bash[2:]  # lowercase drive letter
        proj_bash = "/" + str(PROJECT_ROOT).replace("\\", "/").replace(":", "", 1)
        proj_bash = proj_bash[0] + proj_bash[1].lower() + proj_bash[2:]

        # Get current permissions to adjust guidance
        try:
            from gui.permissions import load_permissions
            perms = load_permissions()
        except Exception:
            perms = {"read": 2, "write": 1, "install": 1, "execute": 2, "remove": 1, "network": 2}

        exec_level = perms.get("execute", 2)
        write_level = perms.get("write", 1)
        install_level = perms.get("install", 1)

        # Build path access guidance based on permissions
        if write_level >= 3:
            path_guidance = "You can read and write files **anywhere** on this computer."
        elif write_level >= 2:
            path_guidance = f"You can read/write in the app folder (`{proj_bash}`) and the user's home folder."
        else:
            path_guidance = f"You can only read/write inside the app folder (`{proj_bash}`)."

        if install_level >= 3:
            install_guidance = ("You can install packages system-wide with `pip install` or into the "
                               f"portable Python with `{py_bash} -m pip install`.")
        else:
            install_guidance = (f"All package installs MUST use the portable Python: "
                               f"`{py_bash} -m pip install PACKAGE`")

        if exec_level >= 3:
            exec_guidance = ("You can run commands anywhere on the system. "
                            "Both the portable Python and system tools are available.")
        else:
            exec_guidance = ("Use the portable Python for all commands. "
                            "Do NOT use system Python (`python`, `python3`).")

        if os_name == "Windows":
            prompt_parts.append(f"""## Your Environment (IMPORTANT — READ THIS CAREFULLY)
You are running on **Windows {os_release}** ({os_version}).
The terminal tool uses **Git Bash** with working directory `/e/hermes`.

### How to run Python commands:

**For simple one-liners:**
```
./run_py.sh -c "print('hello')"
./run_py.sh -c "import httpx; print(httpx.__version__)"
```

**For anything with try/except, if/else, or multiple lines:**
Use write_file to create a .py script first, then run it:
```
# Step 1: use write_file tool to create the script (use Windows path for write_file)
# Step 2: run with terminal: ./run_py.sh scriptname.py
# Step 3: clean up: rm scriptname.py
```

**To install packages:** `./run_py.sh -m pip install PACKAGE`

### RULES — FOLLOW EXACTLY:
- **ALWAYS** use `./run_py.sh` to run Python (relative path from working directory)
- **NEVER** use absolute paths — they break. No `E:/hermes/...`, no `/e/hermes/...`, no `/mnt/e/...`
- **NEVER** use `python`, `python3`, `pip`, `pip3` — they don't exist or point to wrong Python
- **NEVER** use `apt`, `sudo`, `netstat`, or Linux package managers — this is Windows
- **NEVER** put try/except in a `python -c` one-liner — write a .py file instead
- For write_file tool, **ALWAYS write temp scripts to `workspace/`** folder: `E:\\hermes\\workspace\\myscript.py`
- For terminal tool, run them with: `./run_py.sh workspace/myscript.py`
- **ALWAYS** clean up temp scripts when done: `rm workspace/myscript.py`
- **NEVER** write files to the app root directory — use `workspace/` for all temp files

### Pre-installed packages (already available, do NOT install):
httpx, lmstudio, ddgs, Pillow, openai, rich, pyyaml, requests, aiohttp, json, subprocess

{exec_guidance}
{install_guidance}
{path_guidance}

**User config (Windows path):** `{_hermes_home}`

{gpu_info}
""")
        else:
            prompt_parts.append(f"""## Your Environment
You are running on **{os_name} {os_release}**.
- Portable Python: `{self.python_dir / 'python'}`
- Working directory: `{PROJECT_ROOT}`
{path_guidance}
{exec_guidance}
{gpu_info}
""")

        permissions_prompt = "\n\n".join(prompt_parts)

        self.agent = AIAgent(
            model=model,
            api_key=api_key or "lm-studio",
            base_url=base_url,
            quiet_mode=True,
            platform="gui",
            disabled_toolsets=disabled,
            ephemeral_system_prompt=permissions_prompt or None,
            session_id=self.session_id,
            session_db=self._session_db,
            max_iterations=agent_config.get("max_turns", 90),
            reasoning_config=reasoning_config,
            fallback_model=fallback,
            # Provider routing
            providers_allowed=routing.get("allowed"),
            providers_ignored=routing.get("ignored"),
            providers_order=routing.get("order"),
            provider_sort=routing.get("sort"),
            # Callbacks
            tool_progress_callback=self._on_tool_progress,
            thinking_callback=self._on_thinking,
            reasoning_callback=self._on_reasoning,
            step_callback=self._on_step,
            clarify_callback=self._on_clarify,
            stream_delta_callback=self._on_stream_delta,
        )

    def _post(self, callback, *args):
        """Post a callback to the tkinter main thread."""
        if callback:
            try:
                self.root.after(0, lambda: callback(*args))
            except Exception:
                pass

    def _on_tool_progress(self, tool_name, args_preview, *extra):
        self._post(self.on_tool_call, tool_name, args_preview)

    def _on_thinking(self, text):
        self._post(self.on_thinking, text)

    def _on_reasoning(self, text):
        self._post(self.on_reasoning, text)

    def _on_stream_delta(self, text):
        """Stream text token to the GUI. None signals end-of-turn."""
        self._post(self.on_stream_delta, text)

    def _on_step(self, iteration, prev_tools):
        self._post(self.on_step, iteration, prev_tools)

    def _on_clarify(self, question, choices=None):
        """Called from agent thread. Posts to GUI and blocks until response."""
        self._post(self.on_clarify, question, choices)
        try:
            return self._clarify_queue.get(timeout=300)
        except queue.Empty:
            return "No response provided."

    def _approval_callback(self, command, risk_level=None, **kwargs):
        """Called when agent wants to run a dangerous command. Blocks until user approves."""
        self._post(self.on_approval, command, risk_level)
        try:
            return self._approval_queue.get(timeout=60)
        except queue.Empty:
            return False  # Deny on timeout

    def respond_to_clarify(self, response: str):
        self._clarify_queue.put(response)

    def respond_to_approval(self, approved: bool):
        self._approval_queue.put(approved)

    def send_message(self, message: str, image_paths: list = None):
        """Send a message to the agent (non-blocking).

        Args:
            message: Text message from the user.
            image_paths: Optional list of local image file paths to attach.
        """
        if self.is_running:
            return
        self.is_running = True
        self._interrupted = False
        self._agent_thread = threading.Thread(
            target=self._run_agent, args=(message, image_paths), daemon=True
        )
        self._agent_thread.start()

    @staticmethod
    def _encode_image(path: str) -> Optional[str]:
        """Read an image file and return a data URL string."""
        import base64, mimetypes
        mime, _ = mimetypes.guess_type(path)
        if not mime:
            mime = "image/png"
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime};base64,{data}"
        except Exception:
            return None

    def _is_model_configured(self) -> bool:
        """Check if an LLM provider is configured and reachable."""
        api_key = self.get_api_key()
        base_url = os.environ.get("OPENAI_BASE_URL", "")
        # Has OpenRouter key
        if api_key:
            return True
        # Has a local LM Studio / other endpoint
        if base_url and ("localhost" in base_url or "127.0.0.1" in base_url):
            try:
                import httpx
                r = httpx.get(f"{base_url.rstrip('/')}/models", timeout=2)
                return r.status_code == 200
            except Exception:
                return False
        return False

    def _guided_response(self, message: str) -> str:
        """Generate an offline response using the built-in guide search.

        Used when no AI model is configured yet — gives new users
        helpful guidance to get started.
        """
        import re as _re

        msg_lower = message.lower().strip()

        # Load guide search
        try:
            guide_path = os.path.join(
                os.path.dirname(__file__), "..", "docs", "hermes-guide.md"
            )
            guide_path = os.path.normpath(guide_path)
            with open(guide_path, "r", encoding="utf-8") as f:
                guide_content = f.read()
        except Exception:
            guide_content = ""

        # Parse guide into sections
        sections = []
        if guide_content:
            parts = _re.split(r"(?=^## )", guide_content, flags=_re.MULTILINE)
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                lines = part.split("\n", 1)
                heading = lines[0].lstrip("#").strip()
                body = lines[1].strip() if len(lines) > 1 else ""
                sections.append({"heading": heading, "body": body})

        # Quick-match common intents
        setup_keywords = ["setup", "start", "begin", "install", "configure", "connect",
                          "api key", "openrouter", "get started", "first", "new"]
        lmstudio_keywords = ["lm studio", "lmstudio", "local", "gpu", "vram", "model",
                             "download model", "load model", "private", "offline"]
        tts_keywords = ["tts", "speech", "voice", "speak", "read aloud", "clone"]
        music_keywords = ["music", "song", "generate music", "sound"]
        comfyui_keywords = ["image", "comfyui", "stable diffusion", "generate image", "picture"]
        help_keywords = ["help", "what can", "how do", "guide", "manual", "tutorial"]
        tool_keywords = ["tool", "tools", "what tools", "capabilities"]
        workflow_keywords = ["workflow", "automate", "automation", "pipeline"]

        def _match(keywords):
            return any(kw in msg_lower for kw in keywords)

        # Build response
        response_parts = []

        if _match(["hello", "hi ", "hey", "greetings"]) or msg_lower in ("hi", "hey", "hello"):
            response_parts.append(
                "Welcome to Hermes Agent! I'm running in **guided mode** right now "
                "because no AI model is connected yet.\n\n"
                "I can help you get set up! Here's what you can do:\n\n"
                "**Quickest way to start (2 minutes):**\n"
                "1. Go to **File > API Key Setup**\n"
                "2. Click the **OpenRouter** row\n"
                "3. Click **Get Key** — sign up (free, no credit card)\n"
                "4. Copy your key and paste it back here\n"
                "5. Start chatting with full AI!\n\n"
                "Or ask me about: `getting started`, `local models`, `LM Studio`, "
                "`extensions`, `tools`, `permissions`, or anything else!"
            )

        elif _match(setup_keywords):
            # Find the getting started section
            for s in sections:
                if "first launch" in s["heading"].lower() or "getting started" in s["heading"].lower():
                    # Extract just the key steps
                    body = s["body"]
                    if len(body) > 2000:
                        body = body[:2000] + "\n\n*(Type 'more setup' for the full guide)*"
                    response_parts.append(f"## {s['heading']}\n\n{body}")
                    break
            if not response_parts:
                response_parts.append(
                    "**To get started:**\n\n"
                    "1. Go to **File > API Key Setup**\n"
                    "2. Click **OpenRouter** and follow the steps to get a free API key\n"
                    "3. Once saved, you'll have full AI capabilities!\n\n"
                    "For local/private AI, you'll need LM Studio + an NVIDIA GPU. "
                    "Ask me about `LM Studio` for details."
                )

        elif _match(lmstudio_keywords):
            for s in sections:
                if "lm studio" in s["heading"].lower():
                    body = s["body"]
                    if len(body) > 2500:
                        body = body[:2500] + "\n\n*(Type 'more lm studio' for the full guide)*"
                    response_parts.append(f"## {s['heading']}\n\n{body}")
                    break

        elif _match(tts_keywords):
            for s in sections:
                if "extension" in s["heading"].lower() and "tts" in s["body"].lower():
                    body = s["body"]
                    # Extract just the TTS part
                    tts_start = body.find("### Extension 1:") if "### Extension 1:" in body else body.find("TTS Server")
                    if tts_start > 0:
                        body = body[tts_start:tts_start+2000]
                    elif len(body) > 2000:
                        body = body[:2000]
                    response_parts.append(f"## Text-to-Speech\n\n{body}")
                    break

        elif _match(music_keywords):
            for s in sections:
                if "extension" in s["heading"].lower() and "music" in s["body"].lower():
                    body = s["body"]
                    music_start = body.find("### Extension 2:") if "### Extension 2:" in body else body.find("Music Server")
                    if music_start > 0:
                        body = body[music_start:music_start+1500]
                    elif len(body) > 1500:
                        body = body[:1500]
                    response_parts.append(f"## Music Generation\n\n{body}")
                    break

        elif _match(comfyui_keywords):
            for s in sections:
                if "extension" in s["heading"].lower() and "comfyui" in s["body"].lower():
                    body = s["body"]
                    cui_start = body.find("### Extension 3:") if "### Extension 3:" in body else body.find("ComfyUI")
                    if cui_start > 0:
                        body = body[cui_start:cui_start+1500]
                    elif len(body) > 1500:
                        body = body[:1500]
                    response_parts.append(f"## ComfyUI Image Generation\n\n{body}")
                    break

        elif _match(tool_keywords):
            for s in sections:
                if "all tools" in s["heading"].lower() or "complete reference" in s["heading"].lower():
                    body = s["body"]
                    if len(body) > 3000:
                        body = body[:3000] + "\n\n*(Type 'more tools' for the complete list)*"
                    response_parts.append(f"## {s['heading']}\n\n{body}")
                    break

        elif _match(workflow_keywords):
            for s in sections:
                if "workflow" in s["heading"].lower():
                    body = s["body"]
                    if len(body) > 2000:
                        body = body[:2000]
                    response_parts.append(f"## {s['heading']}\n\n{body}")
                    break

        elif _match(["permission", "safe", "security", "access"]):
            for s in sections:
                if "permission" in s["heading"].lower():
                    body = s["body"]
                    if len(body) > 2000:
                        body = body[:2000]
                    response_parts.append(f"## {s['heading']}\n\n{body}")
                    break

        elif _match(help_keywords) or "?" in message:
            response_parts.append(
                "I'm in **guided mode** (no AI model connected yet). "
                "I can answer questions by searching the built-in user guide.\n\n"
                "**Try asking about:**\n"
                "- `How do I get started?`\n"
                "- `What is OpenRouter?`\n"
                "- `How do I use LM Studio?`\n"
                "- `What tools are available?`\n"
                "- `Tell me about the TTS extension`\n"
                "- `How do I generate music?`\n"
                "- `What are workflows?`\n"
                "- `How do permissions work?`\n\n"
                "Or go to **File > API Key Setup** to connect an AI model for full capabilities."
            )

        # Fallback: keyword search through all sections
        if not response_parts:
            keywords = _re.findall(r"[a-zA-Z0-9_\-]+", message.lower())
            best_score = 0
            best_section = None
            for s in sections:
                score = 0
                h = s["heading"].lower()
                b = s["body"].lower()
                for kw in keywords:
                    if kw in h:
                        score += 10
                    score += b.count(kw)
                if score > best_score:
                    best_score = score
                    best_section = s

            if best_section and best_score > 2:
                body = best_section["body"]
                if len(body) > 2000:
                    body = body[:2000] + "\n\n*(Section truncated)*"
                response_parts.append(
                    f"Here's what I found in the guide:\n\n"
                    f"## {best_section['heading']}\n\n{body}"
                )
            else:
                response_parts.append(
                    "I'm in **guided mode** — no AI model is connected yet, "
                    "so I can only answer from the built-in guide.\n\n"
                    "I couldn't find a specific answer for that. Try:\n"
                    "- `How do I get started?` — to set up an AI model\n"
                    "- `What tools are available?` — to see capabilities\n"
                    "- `Help` — for a list of topics I can help with\n\n"
                    "To unlock full AI capabilities, go to **File > API Key Setup**."
                )

        return "\n\n".join(response_parts)

    def _run_agent(self, message: str, image_paths: list = None):
        import logging as _log
        _dbg = _log.getLogger("hermes.bridge")
        if not _dbg.handlers:
            # Use ~/.hermes/logs/ instead of project root for bridge debug log
            import os as _os
            from pathlib import Path as _Path
            _log_dir = _Path(_os.getenv("HERMES_HOME", _Path.home() / ".hermes")) / "logs"
            _log_dir.mkdir(parents=True, exist_ok=True)
            _fh = _log.FileHandler(str(_log_dir / "bridge.log"), encoding="utf-8")
            _fh.setFormatter(_log.Formatter("%(asctime)s %(levelname)s %(message)s"))
            _dbg.addHandler(_fh)
            _dbg.setLevel(_log.DEBUG)

        _dbg.debug("_run_agent START model=%r provider=%s msg=%r",
                    self.get_model(), self._active_provider, message[:80])

        # Check if model is configured — if not, use guided mode
        if not self._is_model_configured():
            _dbg.debug("model NOT configured -> guided mode")
            try:
                response = self._guided_response(message)
                self._post(self.on_response, response)
                self._post(self.on_complete, {
                    "final_response": response,
                    "messages": [],
                    "guided_mode": True,
                })
            except Exception as e:
                self._post(self.on_error, f"Guided mode error: {e}")
            finally:
                self.is_running = False
            return

        try:
            if self.agent is None:
                _dbg.debug("creating agent...")
                self._create_agent()
                _dbg.debug("agent created, base_url=%r api_key=%s",
                           self.agent.base_url,
                           "set" if getattr(self.agent, 'api_key', None) else "none")

            # Build user message content — multimodal if images attached
            if image_paths:
                content_parts = [{"type": "text", "text": message}]
                for img_path in image_paths:
                    data_url = self._encode_image(img_path)
                    if data_url:
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        })
                user_content = content_parts
            else:
                user_content = message

            _dbg.debug("calling run_conversation...")
            result = self.agent.run_conversation(
                user_message=user_content,
                conversation_history=self.conversation_history,
            )

            final_response = result.get("final_response") or ""
            messages = result.get("messages", [])
            self.conversation_history = messages
            _dbg.debug("run_conversation done, response=%d chars", len(final_response))

            self._post(self.on_response, final_response)
            self._post(self.on_complete, result)

        except Exception as e:
            error_msg = f"Error: {e}\n{traceback.format_exc()}"
            _dbg.error("run_agent EXCEPTION: %s", error_msg)
            self._post(self.on_error, error_msg)
        finally:
            self.is_running = False

    def interrupt(self):
        if self.agent and self.is_running:
            self._interrupted = True
            try:
                self.agent.interrupt("")
            except Exception:
                pass

    def new_session(self):
        """Start a fresh session. Flushes memory first."""
        # Flush memories before ending session
        if self.agent:
            try:
                if hasattr(self.agent, '_memory_store') and self.agent._memory_store:
                    self.agent._memory_store.flush(self.conversation_history)
            except Exception:
                pass

        # End old session in database
        if self._session_db and self.session_id:
            try:
                self._session_db.end_session(self.session_id, reason="new_chat")
            except Exception:
                pass

        self.conversation_history = []
        self.session_id = None
        self.agent = None

    def set_model(self, model: str):
        """Switch model from the sidebar dropdown — always cloud."""
        self.set_cloud_mode(model)

    def get_token_usage(self) -> Dict[str, int]:
        """Get token usage from current agent."""
        if not self.agent:
            return {}
        return {
            "prompt": getattr(self.agent, 'session_prompt_tokens', 0),
            "completion": getattr(self.agent, 'session_completion_tokens', 0),
            "total": getattr(self.agent, 'session_total_tokens', 0),
        }
