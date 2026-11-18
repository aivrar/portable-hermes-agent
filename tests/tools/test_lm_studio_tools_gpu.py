"""lm_studio_load places models like the GUI: same GPU mapping and modes."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests import HAS_CORE, NO_CORE_REASON

if not HAS_CORE:          # the tool imports the core's tools.registry
    pytest.skip(NO_CORE_REASON, allow_module_level=True)

import tools.lm_studio_tools as tool  # noqa: E402
from portable_hermes import lmstudio_gpu as gpu_place  # noqa: E402

pytestmark = pytest.mark.skipif(not tool._HAS_SDK, reason="lmstudio SDK not installed")

NVIDIA = [gpu_place.NvidiaGpu(0, "NVIDIA GeForce RTX 3060", 12288, "80c24f57"),
          gpu_place.NvidiaGpu(1, "NVIDIA GeForce RTX 3090", 24576, "36feccef")]
SURVEY = [gpu_place.LmStudioGpu(0, "NVIDIA GeForce RTX 3090", 24575, "36feccef"),
          gpu_place.LmStudioGpu(1, "NVIDIA GeForce RTX 3060", 12287, "80c24f57")]


@pytest.fixture
def sdk(monkeypatch):
    llm = Mock()
    llm.load_new_instance.return_value = Mock(identifier="gemma-4-e4b-it")
    monkeypatch.setattr(tool, "_get_sdk_client", lambda: SimpleNamespace(llm=llm))
    monkeypatch.setattr(tool, "_sdk_handles", {})
    monkeypatch.setattr(gpu_place, "list_nvidia_gpus", lambda timeout=10: list(NVIDIA))
    monkeypatch.setattr(gpu_place, "lmstudio_gpu_survey", lambda *a, **k: list(SURVEY))
    return llm


def _load(sdk, **args):
    result = json.loads(tool.lm_studio_load_handler({"model_path": "gemma-4-e4b-it", **args}))
    config = sdk.load_new_instance.call_args.kwargs["config"] if sdk.load_new_instance.called else None
    return result, config


def test_gpu_index_is_the_nvidia_smi_index_mapped_like_the_panel(sdk):
    result, config = _load(sdk, gpu_index=1)          # nvidia-smi 1 = RTX 3090
    assert config.gpu.main_gpu == 0 and list(config.gpu.disabled_gpus) == [1]
    assert result["gpu_index"] == 1 and result["lmstudio_gpu"] == 0
    assert result["gpu_mapping"] == gpu_place.MAP_UUID


def test_split_mode_fills_the_largest_gpu_first(sdk):
    result, config = _load(sdk, gpu_mode="split")
    assert config.gpu.split_strategy == "favorMainGpu" and config.gpu.main_gpu == 0
    assert result["gpu_placement"] == "split" and result["gpu_index"] is None


def test_cpu_and_default_modes(sdk):
    result, cpu = _load(sdk, gpu_mode="cpu")
    assert cpu.gpu.ratio == 0.0 and cpu.offload_kv_cache_to_gpu is False
    assert list(cpu.gpu.disabled_gpus) == [0, 1]              # every GPU off
    assert result["gpu_confirmed"] is True and "gpu_note" not in result
    result, auto = _load(sdk)
    assert auto.gpu is None and result["gpu_placement"] == "auto"


def test_estimated_gpu_numbering_is_reported_plainly(sdk, monkeypatch):
    monkeypatch.setattr(gpu_place, "lmstudio_gpu_survey", lambda *a, **k: None)
    result, config = _load(sdk, gpu_index=1)          # nvidia-smi 1 = RTX 3090
    assert config.gpu.main_gpu == 0                    # largest card first
    assert result["gpu_mapping"] == gpu_place.MAP_FALLBACK
    assert result["gpu_confirmed"] is False
    assert result["gpu_note"] == gpu_place.UNCONFIRMED_HINT

    monkeypatch.setattr(gpu_place, "lmstudio_gpu_survey", lambda *a, **k: list(SURVEY))
    result, _config = _load(sdk, gpu_index=1)
    assert result["gpu_confirmed"] is True and "gpu_note" not in result


@pytest.mark.parametrize("args, message", [
    ({"gpu_index": 0, "gpu_mode": "split"}, "not both"),
    ({"gpu_mode": "everything"}, "gpu_mode must be one of"),
    ({"gpu_index": 4}, "GPU 4 not found"),
])
def test_bad_placements_are_reported_without_loading(sdk, args, message):
    result, config = _load(sdk, **args)
    assert message in result["error"] and config is None


def test_gpu_index_without_nvidia_gpus_falls_back_to_auto_as_before(sdk, monkeypatch):
    monkeypatch.setattr(gpu_place, "list_nvidia_gpus", lambda timeout=10: [])
    result, config = _load(sdk, gpu_index=0)
    assert config.gpu is None and result["gpu_placement"] == "auto"


def test_schema_keeps_gpu_index_and_offers_the_modes():
    props = tool.LOAD_SCHEMA["parameters"]["properties"]
    assert props["gpu_index"]["type"] == "integer"
    assert props["gpu_mode"]["enum"] == ["auto", "cpu", "split"]
    assert "gpu_info" not in tool.LOAD_SCHEMA["description"]
