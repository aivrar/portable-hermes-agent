"""Portable Hermes wrapper: ownership model, core/wrapper updaters, repair.

This package belongs to the portable wrapper, not to upstream Hermes. It must
stay importable with the standard library alone and must not import Hermes
core modules at import time (the toolsets bridge is loaded at interpreter
start-up by a ``.pth`` hook).

Entry point: ``python -m portable_hermes --help``.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
