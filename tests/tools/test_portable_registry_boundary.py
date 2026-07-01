"""Portable CLI must stay outside the model tool registry."""

from pathlib import Path

import model_tools
from tools.registry import registry
from toolsets import get_all_toolsets, resolve_toolset


REPO_ROOT = Path(__file__).resolve().parents[2]


def _portable_tool_names(names: set[str]) -> set[str]:
    return {name for name in names if name == "portable" or name.startswith("portable_")}


def test_portable_cli_is_not_a_registered_model_tool():
    # Importing model_tools triggers builtin tool discovery.
    assert model_tools is not None

    names = set(registry.get_all_tool_names())

    assert _portable_tool_names(names) == set()


def test_portable_cli_is_not_in_any_toolset():
    exposed = set()
    for toolset_name in get_all_toolsets():
        exposed.update(resolve_toolset(toolset_name))

    assert _portable_tool_names(exposed) == set()


def test_portable_sources_do_not_use_registry_shortcuts():
    combined = "\n".join(
        (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            Path("hermes_cli") / "portable.py",
            Path("hermes_cli") / "subcommands" / "portable.py",
        )
    )

    assert "registry.register" not in combined
    assert "skip_checks" not in combined
