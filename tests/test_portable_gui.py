import importlib
import queue
import subprocess
from pathlib import Path
from types import SimpleNamespace


def _bridge_shell(agent_bridge, tmp_path):
    bridge = object.__new__(agent_bridge.AgentBridge)
    bridge.config = {
        "model": {"default": "provider/current-model"},
        "agent": {"max_turns": 12},
        "provider_routing": {},
    }
    bridge._active_provider = "cloud"
    bridge._lm_studio_base_url = None
    bridge._selected_model = "provider/current-model"
    bridge._session_db = None
    bridge.python_dir = tmp_path / "python_embedded"
    return bridge


def test_portable_gui_modules_import():
    modules = (
        "gui.agent_bridge",
        "gui.api_setup_wizard",
        "gui.app",
        "gui.extensions",
        "gui.lm_studio",
        "gui.permissions",
        "gui.permissions_panel",
        "gui.theme",
    )

    assert all(importlib.import_module(module) for module in modules)


def test_gui_startup_never_probes_lm_studio_on_tk_thread(monkeypatch):
    """Network discovery starts later in Sidebar.refresh_models' worker thread."""
    from gui import app

    class FakeRoot:
        def withdraw(self):
            pass

        def title(self, _value):
            pass

        def geometry(self, _value):
            pass

        def minsize(self, *_args):
            pass

        def deiconify(self):
            pass

        def after(self, *_args):
            pass

        def bind(self, *_args):
            pass

        def protocol(self, *_args):
            pass

    class FakeBridge:
        _startup_fallback = False

        def __init__(self, *_args, **_kwargs):
            pass

        def _validate_startup_model(self):
            raise AssertionError("startup must not perform the LM Studio network probe")

        def get_model(self):
            return "provider/model"

        def _is_local_model(self, _model):
            return False

        def _is_model_configured(self):
            return True

    monkeypatch.setattr(app.tk, "Tk", FakeRoot)
    monkeypatch.setattr(app, "AgentBridge", FakeBridge)
    monkeypatch.setattr(app, "init_dpi_scaling", lambda _root: None)
    monkeypatch.setattr(app, "apply_theme", lambda _root: None)
    monkeypatch.setattr(app, "center_window", lambda *_args: None)
    monkeypatch.setattr(app, "get_missing_keys", lambda: [])
    monkeypatch.setattr(app.HermesGUI, "_build_menu", lambda _self: None)

    def fake_layout(gui):
        gui.status_bar = SimpleNamespace(set_model=lambda _model: None)
        gui.sidebar = SimpleNamespace(set_model=lambda _model: None)

    monkeypatch.setattr(app.HermesGUI, "_build_layout", fake_layout)
    monkeypatch.setattr(app.HermesGUI, "_add_msg", lambda *_args: None)

    app.HermesGUI()


def test_gui_keeps_portable_branding_and_has_no_stale_version_label():
    source = (Path(__file__).resolve().parents[1] / "gui" / "app.py").read_text(
        encoding="utf-8"
    )

    from gui.i18n import TRANSLATIONS

    assert TRANSLATIONS["en"]["app.title"] == "Portable Hermes Agent"
    assert 'self.root.title(t("app.title"))' in source
    assert "github.com/aivrar/portable-hermes-agent" in source
    assert "Hermes Agent v0.2.0" not in source


def test_gui_bridge_uses_current_runtime_provider(monkeypatch, tmp_path):
    from gui import agent_bridge
    import run_agent
    from hermes_cli import runtime_provider

    bridge = _bridge_shell(agent_bridge, tmp_path)
    captured = {}

    def fake_resolve_runtime_provider(**kwargs):
        assert kwargs == {"target_model": "provider/current-model"}
        return {
            "provider": "current-provider",
            "api_mode": "current-api-mode",
            "base_url": "https://current.example/v1",
            "api_key": "current-key",
            "credential_pool": "current-pool",
        }

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", fake_resolve_runtime_provider)
    monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )

    bridge._create_agent()

    assert captured["provider"] == "current-provider"
    assert captured["api_mode"] == "current-api-mode"
    assert captured["base_url"] == "https://current.example/v1"
    assert captured["api_key"] == "current-key"
    assert captured["credential_pool"] == "current-pool"
    assert captured["platform"] == "gui"


def test_gui_approval_bridge_returns_current_approval_choices():
    from gui.agent_bridge import AgentBridge

    seen = []

    class ImmediateRoot:
        @staticmethod
        def after(_delay, callback):
            callback()

    bridge = object.__new__(AgentBridge)
    bridge.root = ImmediateRoot()
    bridge.on_approval = lambda command, description: seen.append(
        (command, description)
    )
    bridge._approval_queue = queue.Queue()
    bridge._approval_queue.put(True)

    assert bridge._approval_callback("dangerous command", "changes files") == "once"
    assert seen == [("dangerous command", "changes files")]

    bridge._approval_queue.put(False)
    assert bridge._approval_callback("dangerous command", "changes files") == "deny"


def test_gui_bridge_close_releases_owned_session_database():
    from gui.agent_bridge import AgentBridge

    class FakeDB:
        closed = False

        def close(self):
            self.closed = True

    bridge = object.__new__(AgentBridge)
    bridge.agent = None
    bridge.is_running = False
    bridge._session_db = FakeDB()

    bridge.close()

    assert bridge._session_db is None


def test_gui_skill_browser_discovers_current_nested_skill_layout(tmp_path):
    from gui.app import _discover_installed_skills

    skill = tmp_path / "extensions" / "lm-studio" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "name: lm-studio\n"
        "description: Control local models.\n"
        "metadata:\n"
        "  hermes:\n"
        "    category: extensions\n"
        "---\n\n# LM Studio\n",
        encoding="utf-8",
    )

    assert _discover_installed_skills(tmp_path) == {
        "extensions": [("lm-studio", "Control local models.")]
    }


def test_gui_api_key_wizard_persists_to_active_hermes_home(monkeypatch, tmp_path):
    from gui import api_setup_wizard

    monkeypatch.setattr(api_setup_wizard, "get_hermes_home", lambda: tmp_path)
    monkeypatch.delenv("PORTABLE_TEST_API_KEY", raising=False)

    api_setup_wizard._save_key_to_env("PORTABLE_TEST_API_KEY", "secret-value")

    assert (tmp_path / ".env").read_text(encoding="utf-8") == (
        "\nPORTABLE_TEST_API_KEY=secret-value\n"
    )
