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


def test_too_small_model_is_rejected_before_loading(monkeypatch):
    warning = Mock()
    monkeypatch.setattr(lm.messagebox, "showwarning", warning)
    panel = SimpleNamespace(model_list=Mock(curselection=lambda: (0,)),
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


def test_load_success_refreshes_with_the_loaded_model_selected():
    refresh = Mock()
    panel = SimpleNamespace(_restore_load_btn=Mock(), status_dot=Mock(),
                            _set_status=Mock(), _refresh_models=refresh)

    lm.LMStudioPanel._on_load_success(panel, "gemma-4-e4b-it")

    refresh.assert_called_once_with(select_id="gemma-4-e4b-it")


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
        panel = SimpleNamespace(
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
