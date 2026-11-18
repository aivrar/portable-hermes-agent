"""Sign-in accounts for the GUI: ChatGPT/Codex and Grok.

The only GUI module that calls the core's account functions. It adds no
login code of its own: sign-in uses the device-code starter and session
table of the core's own dashboard. Those are private names, imported
optionally: a core without them gets the terminal command instead. The public
functions below are plain imports, so the update check (verify.py) catches a
core that drops one.

No token, key or other secret ever leaves this module: status is True/False,
sign-in returns only the address and the code to show.

Blocking calls (start_sign_in, models, use) run on worker threads.
"""
from __future__ import annotations

import asyncio

PROVIDERS = ("openai-codex", "xai-oauth")
SHORT_NAMES = {"openai-codex": "ChatGPT", "xai-oauth": "Grok"}
_FALLBACK_NAMES = {"openai-codex": "ChatGPT or Codex Subscription",
                   "xai-oauth": "xAI Grok (SuperGrok / Premium+)"}
FINISHED = ("approved", "denied", "expired", "error", "cancelled")


class Rejected(Exception):
    """The core refused the model for this account; the message says why."""


def short_name(provider: str) -> str:
    return SHORT_NAMES.get(provider, provider)


def terminal_command(provider: str) -> str:
    return f"hermes auth add {provider}"


def rows() -> list[tuple[str, str]]:
    """(provider, display name) for the two accounts; names from the core's catalog."""
    names = dict(_FALLBACK_NAMES)
    try:
        from hermes_cli.provider_catalog import provider_catalog_by_slug
        catalog = provider_catalog_by_slug()
        for provider in PROVIDERS:
            label = getattr(catalog.get(provider), "label", "")
            if label:
                names[provider] = label
    except Exception:
        pass
    return [(p, names[p]) for p in PROVIDERS]


def account_in_config(config) -> str | None:
    """The account the config's model.provider names, if it is one of ours."""
    model = config.get("model") if isinstance(config, dict) else None
    provider = str(model.get("provider") or "").strip().lower() if isinstance(model, dict) else ""
    return provider if provider in PROVIDERS else None


def status(provider: str) -> bool:
    """Signed in or not (never anything else from the status dict)."""
    from hermes_cli.auth import get_auth_status
    try:
        return bool(get_auth_status(provider).get("logged_in"))
    except Exception:
        return False


def _sessions():
    try:
        from hermes_cli.web_server_oauth import _oauth_sessions, _oauth_sessions_lock
    except Exception:
        return None
    return _oauth_sessions, _oauth_sessions_lock


def start_sign_in(provider: str) -> dict:
    """Blocking (worker thread). {session, url, user_code, expires_in}, or
    {error: text}, or {unavailable: True, command: ...} on a core without
    the in-app sign-in."""
    try:
        from hermes_cli.web_routers.oauth import _start_device_code_flow
    except Exception:
        _start_device_code_flow = None
    if _start_device_code_flow is None or _sessions() is None:
        return {"unavailable": True, "command": terminal_command(provider)}
    try:
        body = asyncio.run(_start_device_code_flow(provider))
    except Exception as exc:
        return {"error": str(getattr(exc, "detail", "") or exc or type(exc).__name__)}
    return {"session": str(body["session_id"]), "url": str(body["verification_url"]),
            "user_code": str(body["user_code"]), "expires_in": int(body.get("expires_in") or 900)}


def poll(session: str) -> tuple[str, str]:
    """(state, message): pending, approved, denied, expired, error or
    cancelled. A finished session is forgotten."""
    found = _sessions()
    if found is None:
        return "error", ""
    sessions, lock = found
    with lock:
        sess = sessions.get(session)
        if sess is None:
            return "cancelled", ""
        state = "cancelled" if sess.get("cancelled") else str(sess.get("status") or "pending")
        message = str(sess.get("error_message") or "")
        if state != "pending":
            sessions.pop(session, None)
    if state != "pending" and state not in FINISHED:
        state = "error"
    return state, message


def cancel(session: str) -> None:
    """Stop a sign-in: the core saves nothing once the session is cancelled."""
    found = _sessions()
    if found is None:
        return
    sessions, lock = found
    with lock:
        sess = sessions.pop(session, None)
        if sess is not None:
            sess["cancelled"] = True


def disconnect(provider: str) -> bool:
    from hermes_cli.auth import clear_provider_auth
    return bool(clear_provider_auth(provider))


def models(provider: str) -> list[str]:
    """Blocking (worker thread): the account's model ids (may fetch the list)."""
    from hermes_cli.models import provider_model_ids
    try:
        return [str(m) for m in provider_model_ids(provider)]
    except Exception:
        return []


def default_model(provider: str, model_ids: list[str]) -> str:
    """Codex: the core's implicit default (it works on every plan) when listed;
    otherwise the core's cost-safe pick."""
    if provider == "openai-codex":
        try:
            from hermes_cli.codex_models import DEFAULT_CODEX_MODELS
            if DEFAULT_CODEX_MODELS and DEFAULT_CODEX_MODELS[0] in model_ids:
                return DEFAULT_CODEX_MODELS[0]
        except Exception:
            pass
    from hermes_cli.models import pick_silent_default_model
    try:
        return pick_silent_default_model(list(model_ids), provider=provider) or ""
    except Exception:
        return model_ids[0] if model_ids else ""


def use(provider: str, model: str) -> str:
    """Blocking (worker thread): validate, then write provider and model together
    (the dashboard's main-model path). Returns the model as written; raises
    Rejected (config untouched) when the core refuses it."""
    from hermes_cli.config import load_config, save_config
    from hermes_cli.model_assignment import (
        ModelAssignmentRejected, apply_main_model_assignment,
        normalize_main_model_assignment, validated_main_model_selection)
    config = load_config()
    provider, model = normalize_main_model_assignment(provider, model)
    try:
        result = validated_main_model_selection(config, provider, model)
    except ModelAssignmentRejected as exc:
        raise Rejected(str(exc)) from exc
    config["model"] = apply_main_model_assignment(config.get("model", {}), result)
    save_config(config)
    return result.new_model


def use_openrouter(model: str) -> None:
    """An OpenRouter pick names its provider, so "auto" can never send an
    OpenRouter id to a signed-in account. Local file write only, no network."""
    from hermes_cli.config import load_config, save_config
    from hermes_cli.model_assignment import apply_main_model_assignment
    from hermes_cli.model_switch import ModelSwitchResult
    config = load_config()
    current = config.get("model") if isinstance(config.get("model"), dict) else {}
    if (str(current.get("provider") or "").lower(), current.get("default")) == ("openrouter", model):
        return
    result = ModelSwitchResult(success=True, target_provider="openrouter", new_model=model)
    config["model"] = apply_main_model_assignment(config.get("model", {}), result)
    save_config(config)
