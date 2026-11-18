"""Where LM Studio puts a model: GPU detection, index mapping, load settings.

Shared by the LM Studio panel, the sidebar auto-load and the agent's
``lm_studio_load`` tool, so all three place a model the same way.

Placements (plain strings, so settings and tool arguments stay simple):

``auto``    no GPU setting at all; LM Studio uses its own default placement.
``cpu``     no layers and no KV cache offloaded to a GPU (offload ratio 0).
``split``   every detected GPU, filling the largest card first and spilling
            the rest onto the next ("favorMainGpu" in the LM Studio SDK).
``gpu:N``   only nvidia-smi GPU *N*; every other GPU is disabled.

The user picks GPUs by their **nvidia-smi** index (PCI bus order). LM Studio
numbers GPUs in **CUDA** order, which defaults to fastest-first, so the two
often disagree (e.g. nvidia-smi 0 = RTX 3060, 1 = RTX 3090, while CUDA and
LM Studio call the 3090 device 0). The mapping is taken, in order, from:

1. LM Studio's own hardware survey (``lms runtime survey --json``), matched
   by GPU UUID. Exact, also for identical cards.
2. The same survey matched by name and memory, when every match is unique.
3. An estimate when there is no usable survey (``lms`` missing, unexpected
   output, ambiguous matches): CUDA's default order is "fastest first", which
   is approximated as most memory first, cards with equal memory keeping
   their nvidia-smi (PCI) order. Any GPU count. Such a plan is marked
   unconfirmed (:attr:`GpuPlan.confirmed`) and the GUI and the tool say so.

Detection never raises: every subprocess has a timeout and runs without a
console window (the GUI can run windowless), and unexpected output counts as
"nothing detected".

Standard library only (this package must import without Hermes or the SDK);
callers turn :attr:`GpuPlan.gpu` into the SDK's ``GpuSetting``.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("portable_hermes.lmstudio_gpu")

AUTO = "auto"
CPU = "cpu"
SPLIT = "split"
_SINGLE_PREFIX = "gpu:"

#: SDK split strategy used for ``split`` (fill the main GPU first, then spill).
SPLIT_STRATEGY = "favorMainGpu"

#: How the nvidia-smi -> LM Studio mapping was found.
MAP_UUID = "lmstudio-survey-uuid"
MAP_NAME = "lmstudio-survey-name"
MAP_FALLBACK = "estimated"
#: CPU only, but no GPU could be listed at all, so none could be disabled.
MAP_NO_GPU_LIST = "no-gpu-list"
#: Sources that identify the GPU for sure.
CONFIRMED_MAPPINGS = (MAP_UUID, MAP_NAME)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class NvidiaGpu:
    """One GPU as nvidia-smi lists it (``index`` is the nvidia-smi index)."""

    index: int
    name: str
    memory_mib: int
    uuid: str = ""


@dataclass(frozen=True)
class LmStudioGpu:
    """One GPU as LM Studio's hardware survey lists it."""

    device_id: int
    name: str
    memory_mib: int
    uuid: str = ""


@dataclass
class GpuPlan:
    """What to send for one placement.

    ``gpu`` holds keyword arguments for the SDK's ``GpuSetting`` (``None``
    means: send no GPU setting). ``load`` holds extra ``LlmLoadModelConfig``
    keyword arguments. ``lmstudio_gpu`` is the LM Studio device the model is
    pinned to or favours, ``mapping`` how that index was found.
    """

    placement: str
    gpu: Optional[dict] = None
    load: dict = field(default_factory=dict)
    lmstudio_gpu: Optional[int] = None
    mapping: Optional[str] = None

    @property
    def confirmed(self) -> bool:
        """False when the GPU indices are only an estimate (no usable survey),
        or when CPU only could not disable any GPU (none could be listed).

        Auto names no GPU, so it needs no confirmation."""
        return self.mapping is None or self.mapping in CONFIRMED_MAPPINGS

    @property
    def note(self) -> Optional[str]:
        """English notes for this plan (tool results): unconfirmed GPU, and
        for CPU only what LM Studio may still put on a GPU. None if none."""
        notes = []
        if not self.confirmed:
            notes.append(UNCONFIRMED_HINTS[self.mapping])
        if self.placement == CPU:
            notes.append(CPU_HINT)
        return " ".join(notes) or None


_CHECK = ("Check where the model is loaded in LM Studio, or compare GPU memory use "
          "in nvidia-smi.")
#: Shown (in English, e.g. in tool results) when a plan is not confirmed.
UNCONFIRMED_HINTS = {
    MAP_FALLBACK: ("The GPU could not be confirmed: LM Studio's GPU list was not available, "
                   "so the GPU numbering was estimated (largest card first). " + _CHECK),
    MAP_NO_GPU_LIST: ("CPU only could not be confirmed: no GPU could be listed (nvidia-smi "
                      "and LM Studio's GPU list were both unavailable), so no GPU could be "
                      "disabled. " + _CHECK),
}
UNCONFIRMED_HINT = UNCONFIRMED_HINTS[MAP_FALLBACK]
#: CPU only keeps the model's layers in RAM; LM Studio's runtime and a vision
#: model's image part may still use a GPU (measured: ~0.6 GB for a text model,
#: ~3 GB for a vision model on the owner's PC); the SDK cannot prevent it.
CPU_HINT = ("The model's layers are in RAM; LM Studio may still use some GPU memory, "
            "more for vision models.")


# ---------------------------------------------------------------------------
# Placement strings
# ---------------------------------------------------------------------------

def single(index: int) -> str:
    """Placement for nvidia-smi GPU *index* only."""
    return f"{_SINGLE_PREFIX}{int(index)}"


def parse_placement(placement) -> Tuple[str, Optional[int]]:
    """``(kind, nvidia index)``; kind is auto, cpu, split or gpu.

    Raises ValueError for anything else."""
    value = str(placement if placement is not None else AUTO).strip().lower()
    if value in (AUTO, CPU, SPLIT):
        return value, None
    if value.startswith(_SINGLE_PREFIX):
        try:
            index = int(value[len(_SINGLE_PREFIX):])
        except ValueError:
            index = -1
        if index >= 0:
            return "gpu", index
    raise ValueError(f"unknown GPU placement {placement!r} "
                     f"(use auto, cpu, split or gpu:<nvidia-smi index>)")


def placement_from_index(gpu_index: Optional[int]) -> str:
    """The placement older callers meant with ``gpu_index`` (None = auto)."""
    return AUTO if gpu_index is None else single(gpu_index)


def placements_for(gpus: Sequence[NvidiaGpu]) -> List[str]:
    """Choices to offer, in display order: auto, cpu, [split], each GPU."""
    choices = [AUTO, CPU]
    if len(gpus) >= 2:
        choices.append(SPLIT)
    choices.extend(single(g.index) for g in gpus)
    return choices


def default_placement(gpus: Sequence[NvidiaGpu]) -> str:
    """First GPU when there is one (the long-standing default), else auto."""
    return single(gpus[0].index) if gpus else AUTO


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _normalise_uuid(value) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("gpu-"):
        text = text[4:]
    return text.replace("-", "")


def parse_nvidia_smi(output: str) -> List[NvidiaGpu]:
    """Parse ``index,name,memory.total,uuid`` CSV (noheader, nounits)."""
    gpus = []
    for line in (output or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            index, memory = int(parts[0]), int(float(parts[2]))
        except ValueError:
            continue
        uuid = _normalise_uuid(parts[3]) if len(parts) > 3 else ""
        gpus.append(NvidiaGpu(index=index, name=parts[1], memory_mib=memory, uuid=uuid))
    return gpus


def list_nvidia_gpus(timeout: float = 10) -> List[NvidiaGpu]:
    """GPUs in nvidia-smi order; empty when nvidia-smi is missing or fails."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total,uuid",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return parse_nvidia_smi(result.stdout)
    except Exception:  # missing, timed out, non-zero exit, odd output
        return []


def parse_lms_survey(data) -> Optional[List[LmStudioGpu]]:
    """GPUs from ``lms runtime survey --json`` output, in LM Studio's order.

    Uses the first engine that reports CUDA GPUs (the order the CUDA engine
    and therefore ``GpuSetting`` indices use), else the first that reports
    any GPU. None when the data holds no usable GPU list; never raises."""
    try:
        return _parse_lms_survey(data)
    except Exception as exc:  # unexpected shape: same as "no survey"
        logger.info("LM Studio hardware survey not understood: %s", exc)
        return None


def _parse_lms_survey(data) -> Optional[List[LmStudioGpu]]:
    if not isinstance(data, dict):
        return None
    engines = data.get("engines")
    if not isinstance(engines, list):
        return None
    candidates = []
    for engine in engines:
        hardware = engine.get("hardwareSurvey") if isinstance(engine, dict) else None
        survey = hardware.get("gpuSurveyResult") if isinstance(hardware, dict) else None
        infos = survey.get("gpuInfo") if isinstance(survey, dict) else None
        if isinstance(infos, list) and infos and all(isinstance(g, dict) for g in infos):
            candidates.append(infos)
    if not candidates:
        return None
    cuda = [c for c in candidates
            if all(str(g.get("detectionPlatform", "")).upper() == "CUDA" for g in c)]
    gpus = []
    for info in (cuda or candidates)[0]:
        device_id = info.get("deviceId")
        if isinstance(device_id, bool) or not isinstance(device_id, int) or device_id < 0:
            return None
        memory = info.get("dedicatedMemoryCapacityBytes") or info.get("totalMemoryCapacityBytes") or 0
        if isinstance(memory, bool) or not isinstance(memory, (int, float)):
            memory = 0
        other = info.get("otherInfo") if isinstance(info.get("otherInfo"), dict) else {}
        gpus.append(LmStudioGpu(
            device_id=device_id,
            name=str(info.get("name") or "").strip(),
            memory_mib=int(memory) // (1024 * 1024),
            uuid=_normalise_uuid(other.get("deviceUUID")),
        ))
    if len({g.device_id for g in gpus}) != len(gpus):
        return None  # duplicate device ids: not a list we can map against
    return gpus or None


def find_lms() -> Optional[str]:
    """Path of LM Studio's ``lms`` CLI, if installed."""
    try:
        found = shutil.which("lms")
        if found:
            return found
        home = Path.home()
        for folder in (home / ".lmstudio" / "bin", home / ".cache" / "lm-studio" / "bin"):
            for name in ("lms.exe", "lms"):
                candidate = folder / name
                if candidate.is_file():
                    return str(candidate)
    except Exception:  # no home folder, unreadable PATH entry, ...
        pass
    return None


def _run_lms_survey(timeout: float) -> Optional[List[LmStudioGpu]]:
    """Run ``lms runtime survey --json``; None on any failure (missing CLI,
    timeout, non-zero exit, non-JSON or unexpected output). Never raises."""
    lms = find_lms()
    if not lms:
        return None
    try:
        result = subprocess.run(
            [lms, "runtime", "survey", "--json"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
        if result.returncode != 0:
            logger.info("LM Studio hardware survey exited with %s", result.returncode)
            return None
        return parse_lms_survey(json.loads(result.stdout or ""))
    except Exception as exc:
        logger.info("LM Studio hardware survey unavailable: %s", exc)
        return None


_survey_lock = threading.Lock()
_survey_cache: Dict[str, object] = {}
_SURVEY_RETRY_SECONDS = 60.0


def lmstudio_gpu_survey(timeout: float = 20, refresh: bool = False) -> Optional[List[LmStudioGpu]]:
    """LM Studio's own GPU list (read-only ``lms runtime survey``), cached.

    A successful survey is kept for the life of the process; a failed one is
    retried after a minute. Takes about a second, so call it off the Tk
    thread."""
    with _survey_lock:
        cached = _survey_cache.get("value")
        at = float(_survey_cache.get("at", 0.0) or 0.0)
        if not refresh and "value" in _survey_cache and (
                cached is not None or time.monotonic() - at < _SURVEY_RETRY_SECONDS):
            return cached  # type: ignore[return-value]
        value = _run_lms_survey(timeout)
        _survey_cache.update(value=value, at=time.monotonic())
        return value


# ---------------------------------------------------------------------------
# Mapping and plans
# ---------------------------------------------------------------------------

def _memory_close(a: int, b: int) -> bool:
    return abs(a - b) <= max(64, int(max(a, b) * 0.02))


def map_to_lmstudio(nvidia: Sequence[NvidiaGpu],
                    survey: Optional[Sequence[LmStudioGpu]]) -> Tuple[Dict[int, int], str]:
    """``({nvidia-smi index: LM Studio device id}, how it was found)``."""
    if survey:
        by_uuid = {g.uuid: g.device_id for g in survey if g.uuid}
        if nvidia and all(n.uuid and n.uuid in by_uuid for n in nvidia):
            return {n.index: by_uuid[n.uuid] for n in nvidia}, MAP_UUID
        mapping: Dict[int, int] = {}
        for n in nvidia:
            hits = [g for g in survey
                    if g.name.lower() == n.name.lower() and _memory_close(g.memory_mib, n.memory_mib)]
            if len(hits) != 1:
                break
            mapping[n.index] = hits[0].device_id
        else:
            if nvidia and len(set(mapping.values())) == len(mapping):
                return mapping, MAP_NAME
    # Estimate of CUDA's default (fastest-first) order: most memory first,
    # equal memory keeps the nvidia-smi (PCI) order.
    estimated = sorted(nvidia, key=lambda g: (-g.memory_mib, g.index))
    return {g.index: position for position, g in enumerate(estimated)}, MAP_FALLBACK


_UNSET = object()


def plan(placement, nvidia: Optional[Sequence[NvidiaGpu]] = None, survey=_UNSET) -> GpuPlan:
    """Resolve *placement* into the settings to send.

    *nvidia* and *survey* default to live detection (nvidia-smi and the
    cached LM Studio survey); pass them to plan without touching the system.
    Raises ValueError for an unknown placement, an unknown GPU index or a
    split with fewer than two GPUs."""
    kind, index = parse_placement(placement)
    if kind == AUTO:
        return GpuPlan(placement=AUTO)

    gpus = list(list_nvidia_gpus() if nvidia is None else nvidia)
    lms = lmstudio_gpu_survey() if survey is _UNSET else survey
    mapping, source = map_to_lmstudio(gpus, lms)
    every = sorted({g.device_id for g in lms}) if lms else sorted(set(mapping.values()))

    if kind == CPU:
        # The strongest "no GPU" the SDK can express: offload ratio 0, KV
        # cache in RAM, and every GPU disabled. The model's layers then stay
        # in RAM, but LM Studio's runtime and a vision model's image part
        # still use some GPU memory (CPU_HINT); the installed SDK (1.5.0) has
        # no setting to prevent that. All GPUs are disabled, so their order
        # does not matter; with no GPU list at all none can be disabled and
        # the plan is not confirmed.
        return GpuPlan(placement=CPU, gpu={"ratio": 0.0, "disabled_gpus": every or None},
                       load={"offload_kv_cache_to_gpu": False},
                       mapping=None if every else MAP_NO_GPU_LIST)

    if kind == "gpu":
        if index not in mapping:
            listed = ", ".join(str(g.index) for g in gpus) or "none"
            raise ValueError(f"GPU {index} not found (nvidia-smi GPUs: {listed})")
        target = mapping[index]
        disabled = [i for i in every if i != target]
        return GpuPlan(placement=single(index), lmstudio_gpu=target, mapping=source,
                       gpu={"main_gpu": target, "disabled_gpus": disabled or None, "ratio": 1.0})

    if len(gpus) < 2:
        raise ValueError(f"splitting across GPUs needs at least two GPUs (found {len(gpus)})")
    largest = max(gpus, key=lambda g: (g.memory_mib, -g.index))
    target = mapping[largest.index]
    used = set(mapping.values())
    disabled = [i for i in every if i not in used]
    return GpuPlan(placement=SPLIT, lmstudio_gpu=target, mapping=source,
                   gpu={"main_gpu": target, "split_strategy": SPLIT_STRATEGY,
                        "disabled_gpus": disabled, "ratio": 1.0})
