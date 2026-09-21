"""Build a release zip for portable-hermes-agent."""
import argparse
import hashlib
import os
import subprocess
import tempfile
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Minimum bootable portable surface. The complete tracked inventory is checked
# separately below; these catch accidental removal from that inventory itself.
REQUIRED_RELEASE_FILES = {
    "README.md", "README.zh-TW.md", "START.bat", "UPDATE.bat", "install.bat",
    "hermes.bat", "hermes_gui.bat", "hermes_gui.vbs", "START_HERE.txt",
    "gui/__init__.py", "gui/app.py", "gui/agent_bridge.py", "gui/i18n.py",
    "gui/theme.py", "gui/api_setup_wizard.py", "gui/permissions.py",
    "gui/permissions_panel.py", "gui/extensions.py", "gui/lm_studio.py",
    "tools/update_hermes_tool.py", "docs/Portable-Hermes-Agent-Manual.pdf",
    ".gitattributes", "README.es.md", "README.ur-pk.md", "README.zh-CN.md",
    "scripts/install.cmd", "scripts/install.ps1", "scripts/install.sh",
    "docs/hermes-guide.md", "docs/portable-release-checklist.md", "assets/SOUL.md",
    "tools/run_python_tool.py", "tools/lm_studio_tools.py", "tools/gpu_tool.py",
    "tools/model_switcher_tool.py", "tools/extension_tools.py", "tools/tool_maker.py",
    "tools/workflow_tool.py", "tools/serper_search_tool.py", "tools/guide_tool.py",
    "skills/extensions/portable-comfyui/SKILL.md", "skills/extensions/music-server/SKILL.md",
    "skills/extensions/tts-server/SKILL.md", "skills/getting-started/SKILL.md",
    "skills/lm-studio/SKILL.md",
}

# Directories to exclude entirely
EXCLUDE_DIRS = {
    ".git",
    ".github",
    ".claude",
    ".codex",
    ".plans",
    "python_embedded",
    "node_modules",
    "__pycache__",
    ".hermes",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "venv",
    "tests",
    "codex",
    "plans",
    "workspace",
    "tinker-atropos",
    "mini-swe-agent",
}

# Specific paths to exclude
EXCLUDE_PATHS = {
    ".env",
    ".lmstudio_config",
    "build_release.py",
    "test_script.sh",
    "test.pdf",
    "smoke_test_all_tools.py",
    "test_all_tools.py",
    "agent_debug.log",
    "bridge_debug.log",
    "thinking_debug.log",
}

# Generated Docusaurus source is published on the documentation site and is
# not consumed by the portable runtime.  Keeping it in the ZIP duplicates
# skill instructions (including shell examples) and can trigger download-time
# antivirus heuristics such as Norton's MD:HttpRequest-inf signature.  This
# includes localized copies under website/i18n/<locale>/.  Retain
# website/static/api/model-catalog.json, which the updater uses to seed the
# local model catalog cache.
EXCLUDE_PREFIXES = {
    "website/docs",
}
I18N_DOCS_PLUGIN_PREFIX = "docusaurus-plugin-content-docs"

# File extensions to exclude
EXCLUDE_EXTS = {".pyc", ".pyo"}

# Extension subdirs that are cloned repos (exclude their contents)
EXCLUDE_EXT_REPOS = {
    os.path.join("extensions", "comfyui"),
    os.path.join("extensions", "music-server"),
    os.path.join("extensions", "tts-server"),
}


def parse_args():
    parser = argparse.ArgumentParser(description="Build a portable Hermes release zip.")
    parser.add_argument(
        "--version",
        default=os.environ.get("HERMES_RELEASE_VERSION", "dev"),
        help="Version suffix for the zip name, for example 1.2.0 or 2026.7.1.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.dirname(PROJECT_ROOT),
        help="Directory where the release zip should be written.",
    )
    return parser.parse_args()


def should_exclude(rel_path):
    norm_path = rel_path.replace("\\", "/")
    parts = norm_path.split("/")

    # Check dir exclusions
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True

    # Check path exclusions
    if norm_path in {path.replace("\\", "/") for path in EXCLUDE_PATHS}:
        return True

    # Check path-prefix exclusions
    for prefix in EXCLUDE_PREFIXES:
        norm_prefix = prefix.replace("\\", "/").rstrip("/")
        if norm_path == norm_prefix or norm_path.startswith(norm_prefix + "/"):
            return True

    # Docusaurus stores localized docs below a locale directory. Plugin IDs may
    # add a suffix to this component, so match the component prefix rather than
    # hard-coding the currently shipped locale and plugin directory name.
    if (
        len(parts) >= 4
        and parts[:2] == ["website", "i18n"]
        and (
            parts[3] == I18N_DOCS_PLUGIN_PREFIX
            or parts[3].startswith(I18N_DOCS_PLUGIN_PREFIX + "-")
        )
    ):
        return True

    # Check extension repos
    for repo in EXCLUDE_EXT_REPOS:
        norm_repo = repo.replace("\\", "/")
        if norm_path.startswith(norm_repo + "/"):
            return True

    # Check extensions
    _, ext = os.path.splitext(norm_path)
    if ext in EXCLUDE_EXTS:
        return True

    # Skip the weird unicode filename
    if "check_lm_studio" in norm_path and norm_path.startswith("E"):
        return True

    return False


def iter_release_files():
    """Yield release candidate files.

    Prefer git's tracked-file list so ignored local scratch files in a
    maintainer checkout cannot leak into a published portable ZIP. Fall back to
    a worktree walk when this script is run outside a git checkout.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        yield from iter_worktree_files()
        return

    for rel_path in result.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        if rel_path:
            yield rel_path


def iter_worktree_files():
    """Fallback file walk for source trees without git metadata."""
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Prune excluded dirs in-place to avoid walking into them
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for fname in sorted(files):
            yield os.path.relpath(os.path.join(root, fname), PROJECT_ROOT)


def main():
    args = parse_args()
    version = args.version[1:] if args.version.startswith("v") else args.version
    output_dir = os.path.abspath(args.output_dir)
    zip_name = f"portable-hermes-agent-v{version}.zip"
    zip_path = os.path.join(output_dir, zip_name)

    os.makedirs(output_dir, exist_ok=True)

    print(f"Building release: {zip_name}")
    print(f"Source: {PROJECT_ROOT}")
    print(f"Output: {zip_path}")
    print()

    prefix = "portable-hermes-agent"
    candidates = sorted({p.replace("\\", "/") for p in iter_release_files()
                         if not should_exclude(p)})
    missing = REQUIRED_RELEASE_FILES - set(candidates)
    if missing:
        raise RuntimeError(f"Incomplete portable inventory: {', '.join(sorted(missing))}")

    # Never replace a good published build with a partial ZIP. Every included
    # source must be readable, and every archive entry must match its source.
    fd, staging_path = tempfile.mkstemp(prefix=zip_name + ".", suffix=".tmp", dir=output_dir)
    os.close(fd)
    try:
        expected = {}
        with zipfile.ZipFile(staging_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel_path in candidates:
                full_path = os.path.join(PROJECT_ROOT, rel_path)
                with open(full_path, "rb") as source:
                    digest = hashlib.file_digest(source, "sha256").digest()
                archive_name = f"{prefix}/{rel_path}"
                zf.write(full_path, archive_name)
                expected[archive_name] = digest
        with zipfile.ZipFile(staging_path) as zf:
            if len(zf.namelist()) != len(expected) or set(zf.namelist()) != set(expected):
                raise RuntimeError("Release archive inventory mismatch")
            for name, digest in expected.items():
                with zf.open(name) as member:
                    if hashlib.file_digest(member, "sha256").digest() != digest:
                        raise RuntimeError(f"Release archive content mismatch: {name}")
        os.replace(staging_path, zip_path)
    finally:
        if os.path.exists(staging_path):
            os.unlink(staging_path)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"Verified! {len(candidates)} files, {size_mb:.1f} MB")
    print(f"Output: {zip_path}")


if __name__ == "__main__":
    main()
