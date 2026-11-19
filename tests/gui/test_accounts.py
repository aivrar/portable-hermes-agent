"""Accounts (ChatGPT/Codex and Grok): the adapter over the core's sign-in,
status and model functions, faked here (no network, no real sign-in)."""
from __future__ import annotations

import sys
import threading
import types

import pytest

from gui import accounts_core as core


def fake(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def sessions(monkeypatch, table):
    fake(monkeypatch, "hermes_cli.web_server_oauth",
         _oauth_sessions=table, _oauth_sessions_lock=threading.Lock())


SECRET = "tok-SECRET-123"


def test_rows_use_the_core_catalog_names_and_survive_without_it(monkeypatch):
    label = types.SimpleNamespace(label="Grok from catalog")
    fake(monkeypatch, "hermes_cli.provider_catalog", provider_catalog_by_slug=lambda: {"xai-oauth": label})
    assert core.rows() == [("openai-codex", "ChatGPT or Codex Subscription"),
                           ("xai-oauth", "Grok from catalog")]

    def broken():
        raise RuntimeError("plugin import failed")
    fake(monkeypatch, "hermes_cli.provider_catalog", provider_catalog_by_slug=broken)
    assert [p for p, _ in core.rows()] == ["openai-codex", "xai-oauth"]


def test_status_is_only_true_or_false(monkeypatch):
    answers = {"openai-codex": {"logged_in": True, "api_key": SECRET}, "xai-oauth": {"logged_in": False}}

    def get_auth_status(provider):
        if provider == "broken":
            raise OSError("auth.json unreadable")
        return answers[provider]
    fake(monkeypatch, "hermes_cli.auth", get_auth_status=get_auth_status)
    assert [core.status(p) for p in ("openai-codex", "xai-oauth", "broken")] == [True, False, False]


def test_start_sign_in_returns_only_what_the_dialog_shows(monkeypatch):
    async def start(provider):
        assert provider == "xai-oauth"
        return {"session_id": "s1", "flow": "device_code", "user_code": "ABCD-1234",
                "verification_url": "https://x.ai/device", "expires_in": 600, "poll_interval": 5,
                "device_code": SECRET}
    fake(monkeypatch, "hermes_cli.web_routers.oauth", _start_device_code_flow=start)
    sessions(monkeypatch, {})
    result = core.start_sign_in("xai-oauth")
    assert result == {"session": "s1", "url": "https://x.ai/device", "user_code": "ABCD-1234",
                      "expires_in": 600}
    assert SECRET not in repr(result)


def test_start_sign_in_failure_is_a_message(monkeypatch):
    class HTTPException(Exception):
        detail = "device-auth timed out before returning a user code"

    async def start(provider):
        raise HTTPException()
    fake(monkeypatch, "hermes_cli.web_routers.oauth", _start_device_code_flow=start)
    sessions(monkeypatch, {})
    assert core.start_sign_in("openai-codex") == {"error": HTTPException.detail}


def test_a_core_without_the_starter_gets_the_terminal_command(monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_cli.web_routers.oauth", None)   # import fails
    assert core.start_sign_in("openai-codex") == {
        "unavailable": True, "command": "hermes auth add openai-codex"}
    fake(monkeypatch, "hermes_cli.web_routers.oauth", _start_device_code_flow=None)
    monkeypatch.setitem(sys.modules, "hermes_cli.web_server_oauth", None)
    assert core.start_sign_in("xai-oauth")["unavailable"] is True
    assert core.poll("s") == ("error", "")
    core.cancel("s")                                           # nothing to do, no exception


@pytest.mark.parametrize("session, expected", [
    ({"status": "pending"}, ("pending", "")),
    ({"status": "approved"}, ("approved", "")),
    ({"status": "denied", "error_message": "Access denied"}, ("denied", "Access denied")),
    ({"status": "expired", "error_message": "Device code expired before approval"},
     ("expired", "Device code expired before approval")),
    ({"status": "error", "error_message": "network down"}, ("error", "network down")),
    ({"status": "pending", "cancelled": True}, ("cancelled", "")),
    ({"status": "something-new"}, ("error", "")),
])
def test_poll_maps_every_state_and_forgets_finished_sessions(monkeypatch, session, expected):
    table = {"s": dict(session, access_token=SECRET)}
    sessions(monkeypatch, table)
    assert core.poll("s") == expected
    assert ("s" in table) == (expected[0] == "pending")
    assert core.poll("gone") == ("cancelled", "")


def test_cancel_marks_the_session_then_drops_it(monkeypatch):
    sess = {"status": "pending"}
    table = {"s": sess}
    sessions(monkeypatch, table)
    core.cancel("s")
    assert sess["cancelled"] is True and table == {}


def test_default_model_prefers_the_core_codex_default(monkeypatch):
    fake(monkeypatch, "hermes_cli.codex_models", DEFAULT_CODEX_MODELS=["gpt-6-sol", "gpt-6-luna"])
    fake(monkeypatch, "hermes_cli.models", pick_silent_default_model=lambda ids, provider: ids[-1])
    assert core.default_model("openai-codex", ["gpt-6.1-terra", "gpt-6-sol"]) == "gpt-6-sol"
    assert core.default_model("openai-codex", ["gpt-6.1-terra"]) == "gpt-6.1-terra"
    assert core.default_model("xai-oauth", ["grok-4.6", "grok-4.7"]) == "grok-4.7"


class _Config:
    """load_config/save_config over one dict; records the call order."""

    def __init__(self, monkeypatch, model):
        self.data = {"model": dict(model), "agent": {}}
        self.calls = []
        fake(monkeypatch, "hermes_cli.config", load_config=self.load, save_config=self.save)

    def load(self):
        self.calls.append("load")
        return {k: dict(v) for k, v in self.data.items()}

    def save(self, config):
        self.calls.append("save")
        self.data = config


def _assignment(monkeypatch, calls, reject=False, during=None):
    class ModelAssignmentRejected(ValueError):
        pass

    def validated(config, provider, model):
        calls.append(("validate", provider, model))
        if during:
            during()
        if reject:
            raise ModelAssignmentRejected("not supported with this account")
        return types.SimpleNamespace(target_provider=provider, new_model=model)

    def apply(model_cfg, result):
        calls.append("apply")
        return dict(model_cfg, provider=result.target_provider, default=result.new_model)

    fake(monkeypatch, "hermes_cli.model_assignment", ModelAssignmentRejected=ModelAssignmentRejected,
         validated_main_model_selection=validated, apply_main_model_assignment=apply,
         normalize_main_model_assignment=lambda p, m: (p, m))


def test_use_validates_then_writes_provider_and_model_together(monkeypatch):
    config = _Config(monkeypatch, {"default": "google/gemini-2.5-flash"})
    calls = config.calls
    _assignment(monkeypatch, calls)
    assert core.use("openai-codex", "gpt-6-sol") == "gpt-6-sol"
    # validate first, then load fresh, apply and save in one short step
    assert calls == ["load", ("validate", "openai-codex", "gpt-6-sol"), "load", "apply", "save"]
    assert config.data["model"] == {"default": "gpt-6-sol", "provider": "openai-codex"}


def test_use_keeps_an_edit_made_while_it_validated(monkeypatch):
    config = _Config(monkeypatch, {"default": "google/gemini-2.5-flash"})

    def edit_elsewhere():          # e.g. the CLI or the dashboard saves meanwhile
        config.data = dict(config.data, agent={"max_turns": 7})
    _assignment(monkeypatch, config.calls, during=edit_elsewhere)
    core.use("xai-oauth", "grok-4.6")
    assert config.data["agent"] == {"max_turns": 7}
    assert config.data["model"]["provider"] == "xai-oauth"


def test_a_rejected_model_leaves_the_config_untouched(monkeypatch):
    config = _Config(monkeypatch, {"default": "google/gemini-2.5-flash"})
    _assignment(monkeypatch, config.calls, reject=True)
    with pytest.raises(core.Rejected, match="not supported"):
        core.use("openai-codex", "google/gemini-2.5-flash")
    assert "save" not in config.calls
    assert config.data["model"] == {"default": "google/gemini-2.5-flash"}


def test_an_openrouter_pick_names_its_provider_once(monkeypatch):
    config = _Config(monkeypatch, {"default": "gpt-6-sol", "provider": "openai-codex"})
    _assignment(monkeypatch, config.calls)
    fake(monkeypatch, "hermes_cli.model_switch",
         ModelSwitchResult=lambda **kw: types.SimpleNamespace(**kw))
    core.use_openrouter("google/gemini-2.5-flash")
    assert config.data["model"] == {"default": "google/gemini-2.5-flash", "provider": "openrouter"}
    assert not any(isinstance(c, tuple) for c in config.calls)       # no validation, no network
    config.calls.clear()
    core.use_openrouter("google/gemini-2.5-flash")
    assert config.calls == ["load"]                                  # already so: nothing written


def test_account_in_config():
    assert core.account_in_config({"model": {"provider": "xai-oauth"}}) == "xai-oauth"
    assert core.account_in_config({"model": {"provider": "OpenAI-Codex "}}) == "openai-codex"
    assert core.account_in_config({"model": {"provider": "openrouter"}}) is None
    assert core.account_in_config({"model": "gpt-6-sol"}) is None


def _contract():
    import ast
    from pathlib import Path
    from portable_hermes.verify import required_imports
    tree = ast.parse(Path(core.__file__).read_text(encoding="utf-8"))
    return {(module, name) for _, module, names in required_imports(tree) for name in names or []}


def test_the_update_check_covers_the_public_core_functions_only():
    needed = _contract()
    assert {("hermes_cli.auth", "get_auth_status"), ("hermes_cli.auth", "clear_provider_auth"),
            ("hermes_cli.models", "provider_model_ids"), ("hermes_cli.models", "pick_silent_default_model"),
            ("hermes_cli.model_assignment", "validated_main_model_selection"),
            ("hermes_cli.model_assignment", "apply_main_model_assignment"),
            ("hermes_cli.model_switch", "ModelSwitchResult"),
            ("hermes_cli.config", "load_config"), ("hermes_cli.config", "save_config")} <= needed
    # The dashboard's private sign-in pieces degrade to the terminal command instead.
    assert not [name for _, name in needed if name.startswith("_")]


@pytest.mark.needs_core
def test_the_installed_core_has_every_function_in_the_contract():
    import importlib
    missing = [f"{m}.{n}" for m, n in sorted(_contract()) if not hasattr(importlib.import_module(m), n)]
    assert missing == []
