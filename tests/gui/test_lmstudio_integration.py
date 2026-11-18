"""LM Studio network, persistence, and UI boundary contracts."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests import HAS_CORE, NO_CORE_REASON

if not HAS_CORE:          # gui.lm_studio imports the core (agent.model_metadata)
    pytest.skip(NO_CORE_REASON, allow_module_level=True)

from gui import lm_studio as lm  # noqa: E402


def test_context_selection_obeys_core_floor():
    panel = SimpleNamespace(ctx_var=Mock(), ctx_label=Mock())
    lm.LMStudioPanel._on_ctx_change(panel, "8192")
    panel.ctx_var.set.assert_called_once_with(lm.MINIMUM_CONTEXT_LENGTH)
    assert lm.DEFAULT_CONTEXT_LENGTH >= lm.MINIMUM_CONTEXT_LENGTH


def _panel_with(**attributes):
    """A real LMStudioPanel instance (its helper methods work) without Tk."""
    panel = object.__new__(lm.LMStudioPanel)
    panel.__dict__.update(attributes)
    return panel


def test_too_small_model_is_rejected_before_loading(monkeypatch):
    warning = Mock()
    monkeypatch.setattr(lm.messagebox, "showwarning", warning)
    panel = _panel_with(model_list=Mock(curselection=lambda: (0,)),
                        models=[{"id": "small", "context_length": lm.MINIMUM_CONTEXT_LENGTH // 2}])
    lm.LMStudioPanel._load_model(panel)
    warning.assert_called_once()


def test_loaded_sdk_models_use_identifier_not_debug_repr():
    model = SimpleNamespace(identifier="hermes-live-instance")
    assert lm.LMStudioClient._extract_model_id(model) == "hermes-live-instance"


def test_load_without_sdk_never_reports_success():
    with pytest.raises(RuntimeError, match="not connected"):
        lm.LMStudioClient(api_key="").load_model("test-model")


def test_profile_storage_clear_and_atomic_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(lm, "LMSTUDIO_CONFIG_PATH", None)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "one"))
    monkeypatch.setenv("LM_API_TOKEN", "environment-key")
    assert lm._write_lmstudio_config(base_url="http://localhost:1234/v1", api_key="saved-key")
    path = tmp_path / "one" / ".lmstudio_config"
    before = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(lm.os, "replace", Mock(side_effect=OSError("disk failure")))
        assert not lm._write_lmstudio_config(api_key="replacement")
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".lmstudio-*"))
    assert lm._write_lmstudio_config(api_key="")
    assert lm.LMStudioClient().api_key == ""
    assert lm.LMStudioPanel._resolve_api_key() == ""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "two"))
    assert lm._read_lmstudio_config() == {}


def test_explicit_empty_key_and_other_host_do_not_reuse_saved_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(lm, "LMSTUDIO_CONFIG_PATH", tmp_path / "settings")
    monkeypatch.delenv("LM_API_KEY", raising=False)
    monkeypatch.delenv("LM_API_TOKEN", raising=False)
    assert lm._write_lmstudio_config(base_url="http://localhost:1234", api_key="saved")
    assert lm.LMStudioClient(api_key="")._auth_headers() == {}
    assert lm.LMStudioClient(base_url="http://other.example:1234")._auth_headers() == {}


@pytest.mark.parametrize("endpoint,envelope", [
    ("/api/v0/models", "data"), ("/v1/models", "data"),
    ("/models", None), ("/api/v1/models", "models"),
])
def test_real_http_auth_fallback_and_metadata(endpoint, envelope):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            self.send_response(200 if self.path == endpoint else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            models = [{"id": "publisher/model", "max_context_length": 32768,
                       "quantization": "Q4", "state": "loaded"}]
            self.wfile.write(json.dumps({envelope: models} if envelope else models).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        client = lm.LMStudioClient(f"http://127.0.0.1:{server.server_port}/v1/", "test-token")
        # Having an SDK connection must not bypass metadata or return id-less rows.
        client._sdk_client = Mock()
        models = client.list_models_api()
        assert models[0]["id"] == "publisher/model"
        assert models[0]["context_length"] == 32768
        assert models[0]["quantization"] == "Q4"
        assert models[0]["state"] == "loaded"
        assert all(auth == "Bearer test-token" for _, auth in requests)
        assert requests[0][0] == "/api/v0/models"
        assert requests[-1][0] == endpoint
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_sdk_uses_selected_host_and_documented_token_argument(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr(lm, "HAS_SDK", True)
    monkeypatch.setattr(lm, "lmstudio", SimpleNamespace(Client=constructor))
    client = lm.LMStudioClient("http://127.0.0.1:4321/v1", "test-token")
    assert client.connect_sdk()
    constructor.assert_called_once_with(api_host="127.0.0.1:4321", api_token="test-token")


def test_save_failure_does_not_connect_or_change_active_credentials(monkeypatch):
    monkeypatch.setattr(lm, "_write_lmstudio_config", lambda **kwargs: False)
    panel = SimpleNamespace(_key_var=Mock(get=lambda: "new"),
                            _ep_var=Mock(get=lambda: "http://localhost:1234"),
                            client=SimpleNamespace(api_key="old"),
                            status_lbl=Mock(), _connect=Mock(), _set_status=Mock())
    lm.LMStudioPanel._apply_api_key(panel)
    lm.LMStudioPanel._apply_endpoint(panel)
    assert panel.client.api_key == "old"
    panel._connect.assert_not_called()


def test_connection_reads_tk_variables_only_on_ui_thread(monkeypatch):
    ui_thread = threading.get_ident()
    complete = threading.Event()
    def read_key():
        assert threading.get_ident() == ui_thread
        return "test-key"
    client = Mock()
    client.is_running.side_effect = lambda: complete.set() or False
    panel = SimpleNamespace(client=client, _key_var=Mock(get=read_key), after=Mock())
    monkeypatch.setattr(lm, "HAS_SDK", False)
    lm.LMStudioPanel._connect(panel)
    assert complete.wait(5)
    assert client.api_key == "test-key"


def _sdk_with_downloaded(*downloaded):
    llm = Mock()
    llm.list_loaded.return_value = []
    llm.list_downloaded.return_value = list(downloaded)
    return SimpleNamespace(llm=llm)


@pytest.mark.skipif(not lm.HAS_SDK, reason="lmstudio SDK not installed")
def test_panel_load_keeps_lm_studio_default_identifier_model_key(monkeypatch):
    """No opaque "hermes-<time>" id: LM Studio names the instance after the model key."""
    target = Mock(model_key="gemma-4-e4b-it", path="lmstudio-community/gemma-4-e4b-it",
                  display_name="Gemma 4 E4B")
    client = lm.LMStudioClient(api_key="")
    client._sdk_client = _sdk_with_downloaded(target)

    assert client.load_model("gemma-4-e4b-it", context_length=65536)

    target.load_new_instance.assert_called_once()
    assert "instance_identifier" not in target.load_new_instance.call_args.kwargs


@pytest.mark.skipif(not lm.HAS_SDK, reason="lmstudio SDK not installed")
def test_panel_string_load_fallback_passes_no_identifier():
    client = lm.LMStudioClient(api_key="")
    client._sdk_client = _sdk_with_downloaded()

    assert client.load_model("unlisted-model", context_length=65536)

    call = client._sdk_client.llm.load_new_instance.call_args
    assert call.args == ("unlisted-model",)
    assert "instance_identifier" not in call.kwargs


def test_model_list_shows_a_loaded_model_once():
    rows = lm._one_row_per_model([
        {"id": "qwen", "state": "not-loaded"},
        {"id": "gemma-4-e4b-it", "state": "not-loaded"},
        {"id": "gemma-4-e4b-it", "state": "loaded"},
    ])
    assert rows == [{"id": "qwen", "state": "not-loaded"},
                    {"id": "gemma-4-e4b-it", "state": "loaded"}]


class FakeListbox:
    def __init__(self):
        self.rows, self.selected = [], ()

    def curselection(self):
        return self.selected

    def delete(self, first, last):
        self.rows, self.selected = [], ()

    def insert(self, _index, label):
        self.rows.append(label)

    def selection_set(self, row):
        self.selected = (row,)

    def see(self, _row):
        pass


def _listed_panel(ids, selected_id):
    panel = SimpleNamespace(model_list=FakeListbox(), models=[])
    lm.LMStudioPanel._display_models(panel, [{"id": i} for i in ids])
    panel.model_list.selection_set(ids.index(selected_id))
    return panel


def test_refresh_keeps_selection_on_the_same_model_when_rows_shift():
    panel = _listed_panel(["gemma-4-e4b-it", "qwen3.6-27b-mtp"], "gemma-4-e4b-it")

    lm.LMStudioPanel._display_models(panel, [
        {"id": "new-row", "state": "loaded"},
        {"id": "gemma-4-e4b-it"}, {"id": "qwen3.6-27b-mtp"}])

    assert panel.model_list.curselection() == (1,)


def test_refresh_after_load_selects_the_loaded_model():
    panel = _listed_panel(["qwen3.6-27b-mtp", "gemma-4-e4b-it"], "qwen3.6-27b-mtp")

    lm.LMStudioPanel._display_models(panel, [
        {"id": "gemma-4-e4b-it", "state": "loaded"}, {"id": "qwen3.6-27b-mtp"}],
        "gemma-4-e4b-it")

    assert panel.model_list.curselection() == (0,)


def test_refresh_without_the_selected_model_selects_nothing():
    panel = _listed_panel(["gone", "other"], "gone")

    lm.LMStudioPanel._display_models(panel, [{"id": "other"}])

    assert panel.model_list.curselection() == ()


VARIANT = "deepseek-r1-0528-qwen3-8b@q4_k_m"


def _panel_refreshing_to(rows, requested):
    """A panel with *requested* selected whose refresh shows *rows*."""
    panel = _listed_panel([VARIANT, "deepseek-r1-0528-qwen3-8b@q6_k", "other"], requested)
    panel._restore_load_btn = Mock()
    panel.status_dot = Mock()
    panel._set_status = Mock()
    panel._refresh_models = lambda **kw: lm.LMStudioPanel._display_models(panel, rows, **kw)
    return panel


def _selected_id(panel):
    (row,) = panel.model_list.curselection()
    return panel.models[row]["id"]


def test_load_success_selects_the_real_instance_id_when_it_differs():
    rows = [{"id": "deepseek-r1-0528-qwen3-8b", "state": "loaded"},
            {"id": "earlier-instance", "state": "loaded"},
            {"id": VARIANT, "state": "not-loaded"},
            {"id": "deepseek-r1-0528-qwen3-8b@q6_k", "state": "not-loaded"}]
    panel = _panel_refreshing_to(rows, VARIANT)

    lm.LMStudioPanel._on_load_success(panel, VARIANT, "deepseek-r1-0528-qwen3-8b")

    assert _selected_id(panel) == "deepseek-r1-0528-qwen3-8b"


def test_load_success_with_unknown_id_selects_the_only_loaded_row():
    rows = [{"id": VARIANT, "state": "not-loaded"},
            {"id": "deepseek-r1-0528-qwen3-8b", "state": "loaded"},
            {"id": "other", "state": "not-loaded"}]
    panel = _panel_refreshing_to(rows, VARIANT)

    lm.LMStudioPanel._on_load_success(panel, VARIANT, None)

    assert _selected_id(panel) == "deepseek-r1-0528-qwen3-8b"


def test_load_success_with_unknown_id_and_no_single_loaded_row_selects_requested():
    rows = [{"id": "other", "state": "loaded"}, {"id": "more", "state": "loaded"},
            {"id": VARIANT, "state": "not-loaded"}]
    panel = _panel_refreshing_to(rows, "other")

    lm.LMStudioPanel._on_load_success(panel, VARIANT, None)

    assert _selected_id(panel) == VARIANT


def _tk_root_or_skip():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("requires a Tk display")
    root.withdraw()
    return root


def test_load_and_restore_keep_the_button_order():
    """[Load Model][Unload][Refresh] -> [Cancel][Unload][Refresh] -> back again."""
    from tkinter import ttk

    root = _tk_root_or_skip()
    try:
        row = ttk.Frame(root)
        load_btn, unload_btn, refresh_btn = (ttk.Button(row) for _ in range(3))
        for button in (load_btn, unload_btn, refresh_btn):
            button.pack(side="left")
        panel = _panel_with(
            model_list=Mock(curselection=lambda: (0,)),
            models=[{"id": "gemma-4-e4b-it"}],
            ctx_var=Mock(get=lambda: lm.DEFAULT_CONTEXT_LENGTH),
            gpu_var=Mock(get=lambda: "CPU"),
            _set_status=Mock(), status_dot=Mock(), _cancel_load=Mock(),
            client=Mock(), _post_ui=Mock(),
            load_btn=load_btn, unload_btn=unload_btn)

        lm.LMStudioPanel._load_model(panel)
        assert row.pack_slaves() == [panel._cancel_btn, unload_btn, refresh_btn]

        lm.LMStudioPanel._restore_load_btn(panel)
        assert row.pack_slaves() == [load_btn, unload_btn, refresh_btn]
    finally:
        root.destroy()


@pytest.mark.skipif(not lm.HAS_SDK, reason="lmstudio SDK not installed")
def test_load_records_the_identifier_lm_studio_returned():
    target = Mock(model_key=VARIANT, path="publisher/deepseek", display_name="DeepSeek")
    target.load_new_instance.return_value = SimpleNamespace(identifier="deepseek-r1-0528-qwen3-8b")
    client = lm.LMStudioClient(api_key="")
    client._sdk_client = _sdk_with_downloaded(target)

    assert client.load_model(VARIANT, context_length=65536)

    assert client.last_loaded_identifier == "deepseek-r1-0528-qwen3-8b"


@pytest.mark.skipif(not lm.HAS_SDK, reason="lmstudio SDK not installed")
def test_load_without_handle_identifier_uses_the_newly_listed_instance():
    target = Mock(model_key=VARIANT, path="publisher/deepseek", display_name="DeepSeek")
    target.load_new_instance.return_value = None
    client = lm.LMStudioClient(api_key="")
    client._sdk_client = _sdk_with_downloaded(target)
    survivor = SimpleNamespace(identifier="survivor", unload=Mock())
    fresh = SimpleNamespace(identifier="deepseek-r1-0528-qwen3-8b", unload=Mock())
    client._sdk_client.llm.list_loaded.side_effect = [
        [survivor],          # unload pass
        [survivor],          # before the load
        [survivor, fresh],   # after the load
    ]

    assert client.load_model(VARIANT, context_length=65536)

    assert client.last_loaded_identifier == "deepseek-r1-0528-qwen3-8b"


# --- GPU placement (shared helper: portable_hermes.lmstudio_gpu) -------------

OWNER_NVIDIA = [  # nvidia-smi order on the owner's PC
    lm.gpu_place.NvidiaGpu(0, "NVIDIA GeForce RTX 3060", 12288, "80c24f57"),
    lm.gpu_place.NvidiaGpu(1, "NVIDIA GeForce RTX 3090", 24576, "36feccef"),
]
OWNER_SURVEY = [  # LM Studio's own order (CUDA, fastest first)
    lm.gpu_place.LmStudioGpu(0, "NVIDIA GeForce RTX 3090", 24575, "36feccef"),
    lm.gpu_place.LmStudioGpu(1, "NVIDIA GeForce RTX 3060", 12287, "80c24f57"),
]


@pytest.fixture
def owner_gpus(monkeypatch):
    monkeypatch.setattr(lm.gpu_place, "list_nvidia_gpus", lambda timeout=10: list(OWNER_NVIDIA))
    monkeypatch.setattr(lm.gpu_place, "lmstudio_gpu_survey", lambda *a, **k: list(OWNER_SURVEY))


def _loaded_gpu_setting(placement=None, gpu_index=None):
    target = Mock(model_key="gemma-4-e4b-it", path="p/gemma", display_name="Gemma")
    client = lm.LMStudioClient(api_key="")
    client._sdk_client = _sdk_with_downloaded(target)
    client.load_model("gemma-4-e4b-it", gpu_index=gpu_index, gpu_placement=placement,
                      context_length=65536)
    return target.load_new_instance.call_args.kwargs["config"]


@pytest.mark.skipif(not lm.HAS_SDK, reason="lmstudio SDK not installed")
def test_load_split_favours_the_largest_gpu_in_lm_studio_numbering(owner_gpus):
    config = _loaded_gpu_setting("split")
    assert config.gpu.split_strategy == "favorMainGpu"
    assert config.gpu.main_gpu == 0          # LM Studio's 0 is the 3090
    assert list(config.gpu.disabled_gpus) == []


@pytest.mark.skipif(not lm.HAS_SDK, reason="lmstudio SDK not installed")
def test_load_single_gpu_maps_the_nvidia_smi_index(owner_gpus):
    config = _loaded_gpu_setting(gpu_index=0)    # older callers: nvidia-smi 0 = 3060
    assert config.gpu.main_gpu == 1 and list(config.gpu.disabled_gpus) == [0]


@pytest.mark.skipif(not lm.HAS_SDK, reason="lmstudio SDK not installed")
def test_load_cpu_only_and_auto(owner_gpus):
    cpu = _loaded_gpu_setting("cpu")
    assert cpu.gpu.ratio == 0.0 and cpu.offload_kv_cache_to_gpu is False
    assert list(cpu.gpu.disabled_gpus) == [0, 1]      # every GPU disabled
    assert _loaded_gpu_setting("auto").gpu is None
    assert _loaded_gpu_setting().gpu is None


@pytest.mark.skipif(not lm.HAS_SDK, reason="lmstudio SDK not installed")
def test_load_on_a_missing_gpu_fails_before_unloading_anything(owner_gpus):
    loaded = Mock(identifier="current")
    client = lm.LMStudioClient(api_key="")
    client._sdk_client = _sdk_with_downloaded()
    client._sdk_client.llm.list_loaded.return_value = [loaded]

    with pytest.raises(RuntimeError, match="GPU 7 not found"):
        client.load_model("gemma-4-e4b-it", gpu_placement="gpu:7", context_length=65536)

    loaded.unload.assert_not_called()
    client._sdk_client.llm.load_new_instance.assert_not_called()


class _ComboVar:
    """gpu_var + gpu_combo stand-in: current(i) selects values[i]."""

    def __init__(self):
        self.value, self.values = "", []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def configure(self, values):
        self.values = list(values)

    def current(self, index):
        self.value = self.values[index]


def _gpu_panel():
    combo = _ComboVar()
    panel = object.__new__(lm.LMStudioPanel)
    panel.__dict__.update(gpus=[], _gpu_label_to_placement={}, gpu_var=combo, gpu_combo=combo)
    panel._show_gpu_choices(lm.gpu_place.default_placement([]))    # before detection
    return panel, combo


def _pick(panel, combo, placement):
    combo.set({p: label for label, p in panel._gpu_label_to_placement.items()}[placement])
    panel._on_gpu_chosen()


@pytest.mark.parametrize("choice", ["cpu", "auto"])
def test_panel_keeps_a_choice_made_while_gpus_were_detected(choice):
    panel, combo = _gpu_panel()
    assert panel._selected_gpu_placement() == "auto"
    _pick(panel, combo, choice)

    panel._set_gpus(OWNER_NVIDIA)                    # detection finishes late

    assert panel._selected_gpu_placement() == choice   # not reset to GPU 0
    assert len(combo.values) == 5


def test_panel_without_a_choice_defaults_to_the_first_gpu_after_detection():
    panel, combo = _gpu_panel()
    panel._set_gpus(OWNER_NVIDIA)
    assert panel._selected_gpu_placement() == "gpu:0"
    _pick(panel, combo, "split")
    panel._set_gpus(OWNER_NVIDIA[:1])               # chosen entry no longer offered
    assert panel._selected_gpu_placement() == "gpu:0"


def test_load_success_with_an_estimated_gpu_warns(monkeypatch):
    rows = [{"id": VARIANT, "state": "loaded"}]
    panel = _panel_refreshing_to(rows, VARIANT)
    order = []
    refresh = panel._refresh_models
    panel._refresh_models = lambda **kw: (order.append("refresh"), refresh(**kw))
    warn = Mock(side_effect=lambda *a, **k: order.append("dialog"))
    monkeypatch.setattr(lm.messagebox, "showwarning", warn)
    plan = lm.gpu_place.plan("gpu:1", OWNER_NVIDIA, None)
    note = lm.gpu_unconfirmed_note(plan, "GPU 1: RTX 3090")
    assert "GPU 1: RTX 3090" in note and "nvidia-smi" in note

    lm.LMStudioPanel._on_load_success(panel, VARIANT, None, note)

    panel._set_status.assert_called_with("lmstudio.loaded_model_gpu_unconfirmed", model=VARIANT)
    assert warn.call_args.args[1] == note
    assert order == ["refresh", "dialog"]           # list refreshed before the modal dialog
    assert lm.gpu_unconfirmed_note(lm.gpu_place.plan("gpu:1", OWNER_NVIDIA, OWNER_SURVEY),
                                   "x") is None


def test_cpu_load_says_lm_studio_may_still_use_some_gpu_memory(monkeypatch):
    panel = _panel_refreshing_to([{"id": VARIANT, "state": "loaded"}], VARIANT)
    warn = Mock()
    monkeypatch.setattr(lm.messagebox, "showwarning", warn)

    lm.LMStudioPanel._on_load_success(panel, VARIANT, None, None, True)

    panel._set_status.assert_called_with("lmstudio.loaded_model_cpu", model=VARIANT)
    warn.assert_not_called()                         # a status line, no dialog
    assert lm.gpu_place.plan("cpu", OWNER_NVIDIA, OWNER_SURVEY).confirmed


def test_cpu_only_without_a_gpu_list_gets_its_own_warning():
    blind = lm.gpu_place.plan("cpu", [], None)
    assert lm.gpu_unconfirmed_note(blind, "x") == lm.t("lmstudio.gpu_cpu_unconfirmed")


def test_failed_load_refreshes_the_list_keeping_the_selection(monkeypatch):
    rows = [{"id": "previous", "state": "not-loaded"},     # unloaded after the failure
            {"id": "lfm3-1.7b", "state": "not-loaded"}]
    panel = _listed_panel(["previous", "lfm3-1.7b"], "lfm3-1.7b")
    lm.LMStudioPanel._display_models(panel, [{"id": "previous", "state": "loaded"},
                                             {"id": "lfm3-1.7b"}])
    assert lm.t("lmstudio.loaded_tag") in panel.model_list.rows[0]    # before: stale tag
    panel._restore_load_btn, panel.status_dot, panel._set_status = Mock(), Mock(), Mock()
    panel.client = SimpleNamespace(_sdk_client=None)
    refreshed = []

    def refresh(**kw):
        refreshed.append(kw)
        lm.LMStudioPanel._display_models(panel, rows, **kw)

    panel._refresh_models = refresh
    monkeypatch.setattr(lm.messagebox, "showerror", Mock())

    lm.LMStudioPanel._on_load_error(panel, "unknown model architecture", "lfm3-1.7b")

    assert refreshed == [{"select_ids": ("lfm3-1.7b",)}]
    assert _selected_id(panel) == "lfm3-1.7b"
    assert not any(lm.t("lmstudio.loaded_tag") in row for row in panel.model_list.rows)


def test_gpu_unconfirmed_strings_exist_in_every_language():
    from gui import i18n
    for code in i18n.LANGUAGE_CODES:
        table = i18n.TRANSLATIONS[code]
        for key in ("lmstudio.gpu_unconfirmed", "lmstudio.gpu_unconfirmed_title",
                    "lmstudio.loaded_model_gpu_unconfirmed",
                    "sidebar.model_loaded_gpu_unconfirmed", "lmstudio.gpu_cpu_unconfirmed",
                    "lmstudio.loaded_model_cpu", "sidebar.model_loaded_cpu"):
            assert table[key], (code, key)
        assert "RAM" in table["lmstudio.gpu_cpu"] or "記憶體" in table["lmstudio.gpu_cpu"] \
            or "内存" in table["lmstudio.gpu_cpu"]
        assert "{model}" in table["lmstudio.loaded_model_cpu"]
        assert "{choice}" in table["lmstudio.gpu_unconfirmed"]
        assert "nvidia-smi" in table["lmstudio.gpu_unconfirmed"]
        assert "{model}" in table["lmstudio.loaded_model_gpu_unconfirmed"]


def test_gpu_choices_are_labelled_in_every_language():
    from gui import i18n
    old = i18n.get_language()
    try:
        for code in i18n.LANGUAGE_CODES:
            i18n.set_language(code, persist=False)
            choices = dict(lm.gpu_choices(OWNER_NVIDIA))
            assert list(choices) == ["auto", "cpu", "split", "gpu:0", "gpu:1"]
            for key in ("auto", "cpu", "split"):
                assert choices[key] == i18n.TRANSLATIONS[code][f"lmstudio.gpu_{key}"]
            assert choices["gpu:1"] == "GPU 1: NVIDIA GeForce RTX 3090 (24576 MiB)"
    finally:
        i18n.set_language(old, persist=False)


def test_panel_loads_with_the_placement_behind_the_chosen_label(monkeypatch):
    class InlineThread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(lm.threading, "Thread", InlineThread)
    choices = lm.gpu_choices(OWNER_NVIDIA)
    split_label = dict(choices)["split"]
    panel = object.__new__(lm.LMStudioPanel)
    panel.__dict__.update(
        model_list=Mock(curselection=lambda: (0,)),
        models=[{"id": "gemma-4-e4b-it"}],
        ctx_var=Mock(get=lambda: lm.DEFAULT_CONTEXT_LENGTH),
        gpu_var=Mock(get=lambda: split_label),
        _gpu_label_to_placement={label: p for p, label in choices},
        _set_status=Mock(), status_dot=Mock(), _cancel_load=Mock(),
        client=Mock(last_loaded_identifier="gemma-4-e4b-it"), _post_ui=Mock(),
        load_btn=Mock(), unload_btn=Mock())
    monkeypatch.setattr(lm.ttk, "Button", Mock())

    lm.LMStudioPanel._load_model(panel)

    assert panel.client.load_model.call_args.kwargs["gpu_placement"] == "split"


def _working_panel(monkeypatch, client, reply_running=False):
    """A panel whose load/cancel workers really run in threads; *tracked*
    collects the threads the app would treat as "a model is loading"."""
    tracked, posted = [], []
    panel = object.__new__(lm.LMStudioPanel)
    panel.__dict__.update(
        model_list=Mock(curselection=lambda: (0,)), models=[{"id": "gemma-4-e4b-it"}],
        ctx_var=Mock(get=lambda: lm.DEFAULT_CONTEXT_LENGTH), gpu_var=Mock(get=lambda: ""),
        _gpu_label_to_placement={}, _set_status=Mock(), status_dot=Mock(),
        load_btn=Mock(), unload_btn=Mock(), client=client,
        _post_ui=lambda name, *a: posted.append(name),
        can_change_model=lambda: not reply_running, track_model_work=tracked.append)
    monkeypatch.setattr(lm.ttk, "Button", Mock())
    return panel, tracked, posted


def _all_done(tracked):
    for worker in tracked:
        worker.join(10)
    return tracked and not any(w.is_alive() for w in tracked)


def test_panel_load_and_unload_are_refused_during_a_reply(monkeypatch):
    info = Mock()
    monkeypatch.setattr(lm.messagebox, "showinfo", info)
    client = Mock()
    panel, tracked, _posted = _working_panel(monkeypatch, client, reply_running=True)

    lm.LMStudioPanel._load_model(panel)
    lm.LMStudioPanel._unload_model(panel)

    client.load_model.assert_not_called()
    client.unload_model.assert_not_called()
    assert tracked == [] and info.call_count == 2
    assert info.call_args.args[1] == lm.t("chat.busy_stop_first", stop=lm.t("chat.stop"))


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel", "closed"])
def test_panel_model_work_ends_on_every_path(monkeypatch, outcome):
    import threading
    gate = threading.Event()
    loaded = Mock()
    client = Mock(last_loaded_identifier="gemma-4-e4b-it", last_gpu_plan=None)
    client._sdk_client.llm.list_loaded.return_value = [loaded]

    def load_model(*a, **k):
        gate.wait(10)
        if outcome == "failure":
            raise RuntimeError("unknown model architecture")

    client.load_model.side_effect = load_model
    panel, tracked, posted = _working_panel(monkeypatch, client)

    lm.LMStudioPanel._load_model(panel)
    assert len(tracked) == 1 and tracked[0].is_alive()        # sending waits now
    if outcome == "cancel":
        lm.LMStudioPanel._cancel_load(panel)                   # second worker
    if outcome == "closed":
        panel._closed = True                                   # window closed mid-load
    gate.set()

    assert _all_done(tracked)                                  # busy over on every path
    if outcome == "failure":                                   # unloaded inside the worker
        loaded.unload.assert_called_once_with()
        assert posted == ["_on_load_error"]
    if outcome == "cancel":
        assert len(tracked) == 2 and posted == ["_on_cancel_done"]
    if outcome == "success":
        assert posted == ["_on_load_success"]
