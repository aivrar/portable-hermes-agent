"""Who owns which path in a Portable Hermes install.

Every updater, the release builder, launch-time repair and the tests classify
paths through this module, so there is one answer to "may this be replaced?".

Three categories, checked in this order:

``user``
    Runtime state and user data. No updater, installer step or repair ever
    writes, moves or deletes these paths.
``wrapper``
    Files the portable wrapper ships. Whole trees stay owned as trees, so a
    new file inside ``gui/`` is wrapper-owned without editing this list.
``core``
    Everything else. The core lifecycle installs these from upstream
    NousResearch/hermes-agent and records them in ``.portable/core-state.json``.

Paths are POSIX-style and relative to the install root. Stdlib only: this file
is also executed in a fresh process (``python -I ownership.py``) by the wrapper
updater to read a *staged* release's rules without importing it.
"""

from __future__ import annotations

import fnmatch
import json
import sys

# --------------------------------------------------------------------------
# user / runtime paths: never touched by any updater
# --------------------------------------------------------------------------

#: Top-level entries that hold user data or runtime state.
USER_TOP_LEVEL = frozenset({
    ".env",
    ".git",
    ".hermes",
    ".lmstudio_config",
    ".mypy_cache",
    ".portable",          # updater state, journals, backups (managed separately)
    ".pytest_cache",
    ".venv",
    "_tcltk_temp",
    "cli-config.yaml",
    "extensions",
    "hermes_agent.egg-info",
    "mini-swe-agent",
    "node_modules",
    "python_embedded",
    "python_embedded.zip",
    "run_py.bat",
    "run_py.sh",
    "tcltk.msi",
    "tinker-atropos",
    "venv",
    "workflows",
    "workspace",
})

#: Nested user/runtime paths (the path itself and everything below it).
USER_NESTED = frozenset({
    "apps/desktop/release",   # locally built desktop binaries
    "tools/custom",           # legacy tool_maker storage
})

#: Path components that are always runtime artefacts wherever they appear.
USER_COMPONENTS = frozenset({"__pycache__"})
USER_SUFFIXES = (".pyc", ".pyo")

# --------------------------------------------------------------------------
# wrapper-owned paths
# --------------------------------------------------------------------------

#: Root files only the wrapper has. Upstream never ships these names.
WRAPPER_ROOT_FILES = frozenset({
    "START.bat",
    "START_HERE.txt",
    "UPDATE.bat",
    "hermes.bat",
    "hermes_gui.bat",
    "hermes_gui.vbs",
    "install.bat",
})

#: Root trees only the wrapper has.
WRAPPER_ROOT_TREES = frozenset({"gui", "portable_hermes"})

#: Root-level name patterns the wrapper owns even though upstream ships files
#: with the same names (the portable README must win over upstream's).
WRAPPER_ROOT_PATTERNS = ("README*.md",)

#: Wrapper files that live inside directories upstream also populates.
WRAPPER_CORE_TREE_FILES = frozenset({
    "assets/SOUL.md",
    "docs/Portable-Hermes-Agent-Manual.pdf",
    "docs/hermes-guide.md",
    "docs/portable-release-checklist.md",
    "tools/extension_tools.py",
    "tools/gpu_tool.py",
    "tools/guide_tool.py",
    "tools/lm_studio_tools.py",
    "tools/model_switcher_tool.py",
    "tools/run_python_tool.py",
    "tools/serper_search_tool.py",
    "tools/tool_maker.py",
    "tools/update_hermes_tool.py",
    "tools/workflow_tool.py",
})

#: Wrapper trees that live inside directories upstream also populates.
WRAPPER_CORE_TREE_DIRS = frozenset({
    "skills/extensions",
    "skills/getting-started",
    "skills/lm-studio",
})

#: Wrapper-owned files that are tracked in git for development but are not
#: part of a release (the release builder itself and repo-level metadata).
WRAPPER_DEV_ONLY = frozenset({"build_release.py"})

#: Files a release must contain; the builder fails if any is missing.
REQUIRED_RELEASE_FILES = frozenset({
    "README.md",
    "START.bat",
    "START_HERE.txt",
    "UPDATE.bat",
    "hermes.bat",
    "hermes_gui.bat",
    "hermes_gui.vbs",
    "install.bat",
    "assets/SOUL.md",
    "docs/hermes-guide.md",
    "gui/__init__.py",
    "gui/agent_bridge.py",
    "gui/api_setup_wizard.py",
    "gui/app.py",
    "gui/extensions.py",
    "gui/i18n.py",
    "gui/lm_studio.py",
    "gui/permissions.py",
    "gui/permissions_panel.py",
    "gui/theme.py",
    "portable_hermes/__init__.py",
    "portable_hermes/__main__.py",
    "portable_hermes/bridge.py",
    "portable_hermes/common.py",
    "portable_hermes/core.py",
    "portable_hermes/ownership.py",
    "portable_hermes/verify.py",
    "portable_hermes/wrapper.py",
    "portable_hermes/manifests/last-known-good.json",
    "portable_hermes/manifests/legacy-core-files.txt",
    "skills/extensions/music-server/SKILL.md",
    "skills/extensions/portable-comfyui/SKILL.md",
    "skills/extensions/tts-server/SKILL.md",
    "skills/getting-started/SKILL.md",
    "skills/lm-studio/SKILL.md",
} | WRAPPER_CORE_TREE_FILES)

#: Inside a release archive, pristine copies of wrapper files that live in
#: the core tree are stored under this prefix. Launch-time repair restores
#: them after anything (for example upstream's own ``hermes update`` ZIP swap)
#: replaced or removed the live copies. Generated by the release builder, never
#: committed to git.
PAYLOAD_DIR = "portable_hermes/payload"

#: Written into a release by the builder: version, file hashes, payload list.
RELEASE_MANIFEST = "portable_hermes/release.json"

# --------------------------------------------------------------------------
# core install filter
# --------------------------------------------------------------------------

#: Upstream archive entries the core installer never installs. Mirrors what a
#: release would exclude: development-only trees and generated website docs.
CORE_EXCLUDED_COMPONENTS = frozenset({
    ".claude", ".codex", ".github", ".plans", "codex", "plans", "tests",
})
CORE_EXCLUDED_PREFIXES = ("website/docs/",)


def normalize(rel: str) -> str:
    """Return a clean POSIX relative path (no leading ``./`` or slashes)."""
    rel = str(rel).replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.strip("/")


def _within(rel: str, tree: str) -> bool:
    return rel == tree or rel.startswith(tree + "/")


def is_user(rel: str) -> bool:
    rel = normalize(rel)
    if not rel:
        return False
    parts = rel.split("/")
    if parts[0] in USER_TOP_LEVEL:
        return True
    if any(part in USER_COMPONENTS for part in parts):
        return True
    if rel.endswith(USER_SUFFIXES):
        return True
    return any(_within(rel, tree) for tree in USER_NESTED)


def is_wrapper(rel: str) -> bool:
    """True for wrapper-owned paths (user paths are never wrapper paths)."""
    rel = normalize(rel)
    if not rel or is_user(rel):
        return False
    parts = rel.split("/")
    if len(parts) == 1:
        if rel in WRAPPER_ROOT_FILES or rel in WRAPPER_DEV_ONLY:
            return True
        if any(fnmatch.fnmatchcase(rel, pat) for pat in WRAPPER_ROOT_PATTERNS):
            return True
    if parts[0] in WRAPPER_ROOT_TREES:
        return True
    if rel in WRAPPER_CORE_TREE_FILES:
        return True
    return any(_within(rel, tree) for tree in WRAPPER_CORE_TREE_DIRS)


def classify(rel: str) -> str:
    """Return ``"user"``, ``"wrapper"`` or ``"core"`` for *rel*."""
    if is_user(rel):
        return "user"
    if is_wrapper(rel):
        return "wrapper"
    return "core"


def is_payload_path(rel: str) -> bool:
    """Wrapper files whose directory upstream also populates.

    These are exposed to upstream's own update (it swaps whole top-level
    entries it ships) and therefore get a pristine copy in the release.
    """
    rel = normalize(rel)
    if not is_wrapper(rel) or rel in WRAPPER_DEV_ONLY:
        return False
    parts = rel.split("/")
    if parts[0] in WRAPPER_ROOT_TREES:
        return False
    return not (len(parts) == 1 and rel in WRAPPER_ROOT_FILES)


def is_release_member(rel: str) -> bool:
    """Tracked files that belong in a wrapper-only release archive."""
    rel = normalize(rel)
    if not is_wrapper(rel) or rel in WRAPPER_DEV_ONLY:
        return False
    return not _within(rel, PAYLOAD_DIR) and rel != RELEASE_MANIFEST


def is_core_installable(rel: str) -> bool:
    """Upstream archive entries the core installer may install."""
    rel = normalize(rel)
    if not rel or classify(rel) != "core":
        return False
    parts = rel.split("/")
    if any(part in CORE_EXCLUDED_COMPONENTS for part in parts):
        return False
    if any(rel.startswith(prefix) for prefix in CORE_EXCLUDED_PREFIXES):
        return False
    # Localized copies of generated docs (keep the theme translations).
    if parts[0] == "website" and len(parts) > 3 and parts[1] == "i18n" \
            and parts[3].startswith("docusaurus-plugin-content-docs"):
        return False
    return True


def iter_wrapper_files(root):
    """Yield the wrapper-owned files that exist under *root* (POSIX rels).

    Only wrapper locations are walked, so this stays fast on a full install.
    """
    from pathlib import Path

    root = Path(root)
    seen = set()

    def emit(rel):
        if rel not in seen and is_wrapper(rel):
            seen.add(rel)
            return True
        return False

    for name in sorted(WRAPPER_ROOT_FILES | WRAPPER_DEV_ONLY):
        if (root / name).is_file() and emit(name):
            yield name
    for pattern in WRAPPER_ROOT_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and emit(path.name):
                yield path.name
    for rel in sorted(WRAPPER_CORE_TREE_FILES):
        if (root / rel).is_file() and emit(rel):
            yield rel
    for tree in sorted(WRAPPER_ROOT_TREES | WRAPPER_CORE_TREE_DIRS):
        base = root / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                if emit(rel):
                    yield rel


def describe() -> dict:
    """JSON-serialisable rules, read by an older wrapper from a staged release."""
    return {
        "schema": 1,
        "user_top_level": sorted(USER_TOP_LEVEL),
        "user_nested": sorted(USER_NESTED),
        "wrapper_root_files": sorted(WRAPPER_ROOT_FILES),
        "wrapper_root_trees": sorted(WRAPPER_ROOT_TREES),
        "wrapper_root_patterns": list(WRAPPER_ROOT_PATTERNS),
        "wrapper_core_tree_files": sorted(WRAPPER_CORE_TREE_FILES),
        "wrapper_core_tree_dirs": sorted(WRAPPER_CORE_TREE_DIRS),
        "wrapper_dev_only": sorted(WRAPPER_DEV_ONLY),
        "payload_dir": PAYLOAD_DIR,
        "release_manifest": RELEASE_MANIFEST,
    }


def classify_many(paths) -> dict:
    return {normalize(p): classify(p) for p in paths}


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests
    # ``python -I ownership.py`` prints the rules; ``... classify`` reads paths
    # from stdin (one per line) and prints their categories as JSON.
    if len(sys.argv) > 1 and sys.argv[1] == "classify":
        lines = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
        json.dump(classify_many(lines), sys.stdout)
    else:
        json.dump(describe(), sys.stdout)
