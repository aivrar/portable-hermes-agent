"""GPU placement for LM Studio: nvidia-smi -> LM Studio mapping and load settings."""
from __future__ import annotations

import pytest

from portable_hermes import lmstudio_gpu as g

# nvidia-smi --query-gpu=index,name,memory.total,uuid --format=csv,noheader,nounits
# on the owner's machine (PCI order: the 3060 sits in the first slot).
NVIDIA_SMI = (
    "0, NVIDIA GeForce RTX 3060, 12288, GPU-80c24f57-c604-b55c-5433-5d248304eec9\n"
    "1, NVIDIA GeForce RTX 3090, 24576, GPU-36feccef-50ef-2eaf-5c0c-5448e28a4d8a\n"
)


def _gpu_info(device_id, name, memory, uuid):
    return {"name": name, "deviceId": device_id,
            "totalMemoryCapacityBytes": memory, "dedicatedMemoryCapacityBytes": memory,
            "integrationType": "discrete", "detectionPlatform": "CUDA",
            "otherInfo": {"computeCapability": "8.6", "deviceUUID": uuid}}


# `lms runtime survey --json` on the same machine (trimmed): CUDA order,
# fastest first, so LM Studio calls the 3090 device 0.
SURVEY = {"status": "ok", "engines": [{
    "name": "llama.cpp-win-x86_64-nvidia-cuda12-avx2",
    "hardwareSurvey": {"gpuSurveyResult": {"result": {"code": "success"}, "gpuInfo": [
        _gpu_info(0, "NVIDIA GeForce RTX 3090", 25769279488, "36feccef50ef2eaf5c0c5448e28a4d8a"),
        _gpu_info(1, "NVIDIA GeForce RTX 3060", 12884246528, "80c24f57c604b55c54335d248304eec9"),
    ]}},
    "visibleDevicesConfig": {"visibleDevices": [0, 1], "changesOrder": False},
}]}


@pytest.fixture
def owner():
    return g.parse_nvidia_smi(NVIDIA_SMI), g.parse_lms_survey(SURVEY)


def test_parses_nvidia_smi_and_the_lm_studio_survey(owner):
    nvidia, survey = owner
    assert [(n.index, n.name, n.memory_mib) for n in nvidia] == [
        (0, "NVIDIA GeForce RTX 3060", 12288), (1, "NVIDIA GeForce RTX 3090", 24576)]
    assert nvidia[0].uuid == "80c24f57c604b55c54335d248304eec9"
    assert [(s.device_id, s.name, s.memory_mib) for s in survey] == [
        (0, "NVIDIA GeForce RTX 3090", 24575), (1, "NVIDIA GeForce RTX 3060", 12287)]


def test_maps_the_owners_gpus_by_uuid(owner):
    assert g.map_to_lmstudio(*owner) == ({0: 1, 1: 0}, g.MAP_UUID)


def test_identical_cards_are_told_apart_by_uuid():
    nvidia = [g.NvidiaGpu(0, "RTX 3090", 24576, "aa"), g.NvidiaGpu(1, "RTX 3090", 24576, "bb")]
    survey = [g.LmStudioGpu(0, "RTX 3090", 24575, "bb"), g.LmStudioGpu(1, "RTX 3090", 24575, "aa")]
    assert g.map_to_lmstudio(nvidia, survey) == ({0: 1, 1: 0}, g.MAP_UUID)


def test_without_uuids_unique_name_and_memory_still_match(owner):
    nvidia, survey = owner
    no_uuid = [g.LmStudioGpu(s.device_id, s.name, s.memory_mib) for s in survey]
    assert g.map_to_lmstudio(nvidia, no_uuid) == ({0: 1, 1: 0}, g.MAP_NAME)


def test_identical_cards_without_uuids_use_the_documented_fallback():
    nvidia = [g.NvidiaGpu(0, "RTX 3090", 24576), g.NvidiaGpu(1, "RTX 3090", 24576)]
    survey = [g.LmStudioGpu(0, "RTX 3090", 24575), g.LmStudioGpu(1, "RTX 3090", 24575)]
    assert g.map_to_lmstudio(nvidia, survey) == ({0: 1, 1: 0}, g.MAP_FALLBACK)


@pytest.mark.parametrize("count, expected", [
    (1, {0: 0}),
    (2, {0: 1, 1: 0}),            # the reversal the panel always used
    (3, {0: 0, 1: 1, 2: 2}),      # no rule known: nvidia-smi order unchanged
])
def test_without_a_survey_only_two_gpus_are_reversed(count, expected):
    nvidia = [g.NvidiaGpu(i, f"GPU{i}", 8192) for i in range(count)]
    assert g.map_to_lmstudio(nvidia, None) == (expected, g.MAP_FALLBACK)


def test_choices_offer_split_only_with_two_or_more_gpus(owner):
    nvidia, _survey = owner
    assert g.placements_for(nvidia) == ["auto", "cpu", "split", "gpu:0", "gpu:1"]
    assert g.placements_for(nvidia[:1]) == ["auto", "cpu", "gpu:0"]
    assert g.placements_for([]) == ["auto", "cpu"]
    assert g.default_placement(nvidia) == "gpu:0"
    assert g.default_placement([]) == "auto"


def test_plans_for_the_owners_machine(owner):
    nvidia, survey = owner
    assert g.plan("auto", nvidia, survey).gpu is None
    cpu = g.plan("cpu", nvidia, survey)
    assert cpu.gpu == {"ratio": 0.0} and cpu.load == {"offload_kv_cache_to_gpu": False}

    on_3060 = g.plan("gpu:0", nvidia, survey)
    assert on_3060.gpu == {"main_gpu": 1, "disabled_gpus": [0], "ratio": 1.0}
    on_3090 = g.plan("gpu:1", nvidia, survey)
    assert on_3090.gpu == {"main_gpu": 0, "disabled_gpus": [1], "ratio": 1.0}

    split = g.plan("split", nvidia, survey)
    assert split.gpu == {"main_gpu": 0, "split_strategy": "favorMainGpu",
                         "disabled_gpus": [], "ratio": 1.0}       # 3090 first
    assert split.mapping == g.MAP_UUID


@pytest.mark.parametrize("placement, message", [
    ("gpu:5", "GPU 5 not found"),
    ("split", "at least two GPUs"),
    ("gpu", "unknown GPU placement"),
    ("everything", "unknown GPU placement"),
])
def test_impossible_placements_are_refused(owner, placement, message):
    nvidia, survey = owner
    with pytest.raises(ValueError, match=message):
        g.plan(placement, nvidia[:1] if placement == "split" else nvidia, survey)


def test_survey_is_cached_after_success(monkeypatch):
    calls = []
    monkeypatch.setattr(g, "_survey_cache", {})
    monkeypatch.setattr(g, "_run_lms_survey", lambda timeout: calls.append(1) or ["gpu"])
    assert g.lmstudio_gpu_survey() == ["gpu"]
    assert g.lmstudio_gpu_survey() == ["gpu"]
    assert len(calls) == 1


def test_sdk_sends_the_planned_split_and_cpu_settings(owner):
    """The installed SDK turns the plans into the settings LM Studio reads."""
    lmstudio = pytest.importorskip("lmstudio")
    from lmstudio._kv_config import load_config_to_kv_config_stack
    from lmstudio._sdk_models import GpuSetting

    def sent(plan):
        config = lmstudio.LlmLoadModelConfig(gpu=GpuSetting(**plan.gpu), **plan.load)
        stack = load_config_to_kv_config_stack(config, lmstudio.LlmLoadModelConfig).to_dict()
        return {f["key"]: f["value"] for f in stack["layers"][0]["config"]["fields"]}

    nvidia, survey = owner
    split = sent(g.plan("split", nvidia, survey))
    assert split["load.gpuSplitConfig"]["strategy"] == "priorityOrder"
    assert split["load.gpuSplitConfig"]["priority"] == [0]
    assert split["load.gpuSplitConfig"]["disabledGpus"] == []

    cpu = sent(g.plan("cpu", nvidia, survey))
    assert cpu["llm.load.llama.acceleration.offloadRatio"] == 0.0
    assert cpu["llm.load.offloadKVCacheToGpu"] is False

    pinned = sent(g.plan("gpu:1", nvidia, survey))
    assert pinned["load.gpuSplitConfig"]["disabledGpus"] == [1]
