"""Shared test settings for the Portable Hermes wrapper.

Most tests need only ``portable_hermes`` and the standard library. Tests that
need the Hermes core are marked ``needs_core`` (or skip their whole module)
and are skipped when the checkout has no core; under CI a missing core stops
the run before any test (see ``tests/__init__.py``).

Every test runs hermetically, so the developer's machine cannot leak in and
a test can never write the real Hermes home:

- HERMES_HOME points at a temporary folder, from before any test module is
  imported (importing parts of the core resolves it at once), then at a fresh
  folder per test;
- credential-shaped and HERMES_* variables from the shell are removed;
- locale, time zone and hash seed are fixed;
- the core's implicit network installs are off, and browser windows are
  recorded instead of opened.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import HAS_CORE, IN_CI, NO_CORE_REASON  # noqa: E402

# Sandbox HERMES_HOME before any test module is imported.
_SESSION_HOME = tempfile.mkdtemp(prefix="hermes-test-home-")
atexit.register(shutil.rmtree, _SESSION_HOME, True)
os.environ["HERMES_HOME"] = _SESSION_HOME
# The core's state database refuses the real home in any process that carries
# this marker, including child processes a test starts.
os.environ["HERMES_TEST_ISOLATION"] = _SESSION_HOME

_CREDENTIAL_SUFFIXES = ("_API_KEY", "_KEY", "_TOKEN", "_TOKEN_ID", "_SECRET", "_PASSWORD",
                        "_CREDENTIALS", "_BASE_URL")
_CREDENTIAL_NAMES = frozenset({"AWS_ACCESS_KEY_ID", "GATEWAY_PROXY_URL"})


def _looks_like_credential(name: str) -> bool:
    name = name.upper()
    return name in _CREDENTIAL_NAMES or name.endswith(_CREDENTIAL_SUFFIXES)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "needs_core: needs the Hermes core installed in this checkout")
    config.addinivalue_line(
        "markers", "integration: needs the network or external services (not run by default)")
    if not HAS_CORE and IN_CI:
        raise pytest.UsageError(f"{NO_CORE_REASON}. In CI the core must be installed "
                                "before the tests run.")


def pytest_report_header(config):
    return f"Hermes core in this checkout: {'yes' if HAS_CORE else 'no (' + NO_CORE_REASON + ')'}"


def pytest_collection_modifyitems(config, items):
    if HAS_CORE:
        return
    skip = pytest.mark.skip(reason=NO_CORE_REASON)
    for item in items:
        if item.get_closest_marker("needs_core"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _hermetic_environment(tmp_path, monkeypatch):
    for name in list(os.environ):
        if _looks_like_credential(name) or name.upper().startswith("HERMES_"):
            monkeypatch.delenv(name, raising=False)

    home = tmp_path / "hermes_test"
    for sub in ("sessions", "cron", "memories", "skills"):
        (home / sub).mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_TEST_ISOLATION", str(home))
    # hermes_state computes its database path when it is first imported,
    # which may have happened at collection: point it at this test's home.
    state = sys.modules.get("hermes_state")
    if state is not None and hasattr(state, "DEFAULT_DB_PATH"):
        monkeypatch.setattr(state, "DEFAULT_DB_PATH", home / "state.db")

    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    # No implicit network use by core code under test: no AWS metadata
    # lookups, no Tirith download, no on-demand pip installs.
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("TIRITH_ENABLED", "false")
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")

    # The core's plugin manager is a process-wide singleton.
    try:
        import hermes_cli.plugins as plugins
        monkeypatch.setattr(plugins, "_plugin_manager", None)
        plugins._reset_plugin_managers_for_tests()
    except Exception:  # noqa: BLE001 - no core, or an older core without it
        pass


@pytest.fixture(autouse=True)
def _no_browser_windows(monkeypatch):
    """Record browser-open attempts instead of opening real browser windows."""
    import webbrowser

    opened: list = []

    def record(url=None, *args, **kwargs):
        opened.append(url)
        return True

    class Browser:
        open = open_new = open_new_tab = staticmethod(record)

    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, record)
    monkeypatch.setattr(webbrowser, "get", lambda *args, **kwargs: Browser())
    return opened
