import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The portable tools import the Hermes core (tools.registry, hermes_cli,
# hermes_constants); only the skill check below runs without it.


@pytest.mark.needs_core
def test_lm_studio_tools_default_to_standard_server_port(monkeypatch):
    from tools import lm_studio_tools

    monkeypatch.delenv("LM_STUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    assert lm_studio_tools._resolve_lms_base() == "http://localhost:1234"


@pytest.mark.needs_core
def test_model_switcher_persists_current_config_schema(monkeypatch):
    from tools import model_switcher_tool

    config = {"model": {"default": "old-model", "provider": "openrouter"}}
    saved = {}
    monkeypatch.setattr(model_switcher_tool, "load_config", lambda: config)
    monkeypatch.setattr(
        model_switcher_tool,
        "save_config",
        lambda value, **kwargs: saved.update(config=value, kwargs=kwargs),
    )

    result = json.loads(model_switcher_tool.switch_model_handler({
        "model": "local-model",
        "provider": "lmstudio",
    }))

    assert result["switched"] is True
    assert saved["config"]["model"] == {
        "default": "local-model",
        "provider": "lmstudio",
        "base_url": "http://localhost:1234/v1",
        "api_mode": "chat_completions",
    }
    assert ("model", "default") in saved["kwargs"]["preserve_keys"]


@pytest.mark.needs_core
def test_workflows_use_profile_home_and_migrate_legacy_files(monkeypatch, tmp_path):
    from tools import workflow_tool

    legacy_dir = tmp_path / "portable" / "workflows"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "existing.json").write_text(
        '{"name": "existing", "steps": []}', encoding="utf-8"
    )
    profile_home = tmp_path / "profile"

    monkeypatch.setattr(workflow_tool, "get_hermes_home", lambda: profile_home)
    monkeypatch.setattr(workflow_tool, "_LEGACY_WORKFLOW_DIR", legacy_dir)

    assert workflow_tool._load_workflow("existing") == {
        "name": "existing",
        "steps": [],
    }
    assert (profile_home / "workflows" / "existing.json").is_file()

    workflow_tool._save_workflow("new", {"name": "new", "steps": []})
    assert (profile_home / "workflows" / "new.json").is_file()
    assert not (legacy_dir / "new.json").exists()


@pytest.mark.needs_core
def test_extension_audio_cache_uses_profile_home(monkeypatch, tmp_path):
    from tools import extension_tools

    monkeypatch.setattr(extension_tools, "get_hermes_home", lambda: tmp_path)

    assert extension_tools._ensure_audio_cache() == tmp_path / "audio_cache"
    assert (tmp_path / "audio_cache").is_dir()


def test_extension_skill_ports_match_portable_runtime():
    tts_skill = (REPO_ROOT / "skills/extensions/tts-server/SKILL.md").read_text(
        encoding="utf-8"
    )
    comfyui_skill = (
        REPO_ROOT / "skills/extensions/portable-comfyui/SKILL.md"
    ).read_text(
        encoding="utf-8"
    )

    assert "http://127.0.0.1:8200" in tts_skill
    assert "http://127.0.0.1:8100" not in tts_skill
    assert "http://127.0.0.1:5000/api/status" in comfyui_skill
    assert "http://127.0.0.1:8188/api/status" not in comfyui_skill
