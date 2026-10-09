"""An existing portable runtime must not keep a vulnerable urllib3 wheel."""

from importlib import metadata

import pytest

from hermes_cli import update_cmd


@pytest.mark.parametrize(
    ("installed", "needs_rewrite"),
    [("2.7.0", True), ("2.8.0", False)],
)
def test_update_rewrites_pre_patch_urllib3(monkeypatch, installed, needs_rewrite):
    monkeypatch.setattr(metadata, "version", lambda _name: installed)
    assert update_cmd._dependency_sync_would_rewrite("urllib3") is needs_rewrite
