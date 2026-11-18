"""lm_studio_load reports the instance id LM Studio chose; unload finds it."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests import HAS_CORE, NO_CORE_REASON

if not HAS_CORE:          # the tool imports the core's tools.registry
    pytest.skip(NO_CORE_REASON, allow_module_level=True)

import tools.lm_studio_tools as tool  # noqa: E402

pytestmark = pytest.mark.skipif(not tool._HAS_SDK, reason="lmstudio SDK not installed")


@pytest.fixture
def sdk(monkeypatch):
    llm = Mock()
    monkeypatch.setattr(tool, "_get_sdk_client", lambda: SimpleNamespace(llm=llm))
    monkeypatch.setattr(tool, "_sdk_handles", {})
    return llm


def test_load_passes_no_identifier_and_reports_the_real_one(sdk):
    handle = Mock(identifier="deepseek-r1-0528-qwen3-8b@q4_k_m")
    sdk.load_new_instance.return_value = handle

    result = json.loads(tool.lm_studio_load_handler(
        {"model_path": "deepseek-r1-0528-qwen3-8b@q4_k_m", "context_length": 8192}))

    args, kwargs = sdk.load_new_instance.call_args
    assert args == ("deepseek-r1-0528-qwen3-8b@q4_k_m",)
    assert "instance_identifier" not in kwargs
    assert result["identifier"] == "deepseek-r1-0528-qwen3-8b@q4_k_m"
    assert not result["identifier"].startswith("hermes-")
    assert tool._sdk_handles == {"deepseek-r1-0528-qwen3-8b@q4_k_m": handle}


def test_unload_finds_the_instance_by_the_reported_identifier(sdk):
    handle = Mock(identifier="gemma-4-e4b-it:2")
    sdk.load_new_instance.return_value = handle
    loaded = json.loads(tool.lm_studio_load_handler({"model_path": "gemma-4-e4b-it"}))

    result = json.loads(tool.lm_studio_unload_handler({"model_id": loaded["identifier"]}))

    assert result == {"unloaded": True, "model_id": "gemma-4-e4b-it:2"}
    handle.unload.assert_called_once()


def test_unload_after_restart_matches_listed_instance(sdk):
    instance = Mock(identifier="gemma-4-e4b-it", path="lmstudio-community/gemma-4-e4b-it")
    sdk.list_loaded.return_value = [instance]

    result = json.loads(tool.lm_studio_unload_handler({"model_id": "gemma-4-e4b-it"}))

    assert result["unloaded"] is True and result["matched"] == "gemma-4-e4b-it"
    instance.unload.assert_called_once()
