"""Fixtures shared across hermes_cli kanban tests."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture
def all_assignees_spawnable(monkeypatch):
    """Pretend every assignee maps to a real Hermes profile.

    Most dispatcher tests use synthetic assignees ("alice", "bob") that
    don't correspond to actual profile directories on disk. Without this
    patch, the dispatcher's profile-exists guard (PR #20105) routes
    those tasks into ``skipped_nonspawnable`` instead of spawning, which
    would break tests that assert spawn behavior.
    """
    from hermes_cli import profiles
    monkeypatch.setattr(profiles, "profile_exists", lambda name: True)


@pytest.fixture(autouse=True)
def _suppress_concurrent_hermes_gate(request, monkeypatch):
    """Default ``_detect_concurrent_hermes_instances`` to ``[]`` for every test.

    The Windows update path now refuses to proceed when another
    ``hermes.exe`` is detected (issue #26670). On a developer's Windows
    machine running the test suite via ``hermes`` itself, this would
    flag the running agent as a concurrent instance and abort every
    ``cmd_update`` test. Tests that want to exercise the gate explicitly
    re-patch ``_detect_concurrent_hermes_instances`` with their own
    return value — autouse here gives a clean default without touching
    the rest of the suite.

    Tests that need to call the REAL function (e.g. unit tests for the
    helper itself) opt out with ``@pytest.mark.real_concurrent_gate``.
    """
    if request.node.get_closest_marker("real_concurrent_gate"):
        return
    try:
        from hermes_cli import main as _cli_main
    except Exception:
        return
    # raising=False: under pytest's per-test spawn isolation, a concurrent
    # xdist worker importing a module that transitively touches hermes_cli.main
    # can briefly expose a partially-initialized module object here — one where
    # _detect_concurrent_hermes_instances isn't defined yet. A bare setattr
    # would raise AttributeError and error the (unrelated) test. The attribute
    # always exists once main.py finishes importing, so a no-op when it's
    # transiently absent is the correct, race-free default.
    monkeypatch.setattr(
        _cli_main,
        "_detect_concurrent_hermes_instances",
        lambda *_a, **_k: [],
        raising=False,
    )


@pytest.fixture(autouse=True)
def _reset_kanban_worker_exit_state():
    """Keep kanban worker-exit side channels scoped to a single test."""
    kb = sys.modules.get("hermes_cli.kanban_db")
    if kb is None:
        yield
        return

    def reset() -> None:
        exits = getattr(kb, "_recent_worker_exits", None)
        if isinstance(exits, dict):
            exits.clear()
        detector = getattr(kb, "detect_crashed_workers", None)
        for attr in ("_last_auto_blocked", "_last_rate_limited"):
            if detector is not None and hasattr(detector, attr):
                delattr(detector, attr)

    reset()
    try:
        yield
    finally:
        reset()


@pytest.fixture(autouse=True)
def _reset_kanban_route_env(monkeypatch):
    """Prevent board/db routing env vars from leaking between tests."""
    for name in (
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_HOME",
        "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_BOARD",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _reset_model_discovery_caches():
    """Prevent model catalog/recommendation caches from leaking across tests."""
    models = sys.modules.get("hermes_cli.models")
    if models is None:
        yield
        return

    def reset() -> None:
        if hasattr(models, "_openrouter_catalog_cache"):
            models._openrouter_catalog_cache = None
        if hasattr(models, "_free_tier_cache"):
            models._free_tier_cache = None
        for name in (
            "_nous_recommended_cache",
            "_pricing_cache",
            "_copilot_context_cache",
        ):
            cache = getattr(models, name, None)
            if isinstance(cache, dict):
                cache.clear()
        if hasattr(models, "_copilot_context_cache_time"):
            models._copilot_context_cache_time = 0.0

    reset()
    try:
        yield
    finally:
        reset()
