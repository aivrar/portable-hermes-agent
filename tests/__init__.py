"""Tests of the Portable Hermes wrapper.

The repository holds only the wrapper. The Hermes core is installed into the
checkout by START.bat (in CI: ``python -m portable_hermes core install``).
Tests that need it are skipped, with :data:`NO_CORE_REASON`, when there is
none; under CI a missing core stops the whole run (``tests/conftest.py``).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: True when the core installer has put a Hermes core into this checkout: its
#: record, not an upstream file name, so a renamed upstream file makes the core
#: tests fail loudly instead of skipping them.
HAS_CORE = (REPO_ROOT / ".portable" / "core-state.json").is_file()

NO_CORE_REASON = ("no Hermes core in this checkout: run START.bat first "
                  "(see docs/portable-release-checklist.md, Developing from a clone)")

#: Set by GitHub Actions (and most CI systems). Missing prerequisites fail
#: there instead of being skipped, so nothing is skipped silently.
IN_CI = os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no")
