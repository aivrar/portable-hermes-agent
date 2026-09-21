"""LM Studio network, persistence, and UI boundary contracts."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gui import lm_studio as lm


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
                            status_lbl=Mock(), _connect=Mock())
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
