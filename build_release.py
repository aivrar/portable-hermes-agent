"""Build a release zip for portable-hermes-agent."""
import os
import zipfile
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION = "0.5.1"
ZIP_NAME = f"portable-hermes-agent-v{VERSION}.zip"
ZIP_PATH = os.path.join(os.path.dirname(PROJECT_ROOT), ZIP_NAME)

# Directories to exclude entirely
EXCLUDE_DIRS = {
    ".git",
    "python_embedded",
    "node_modules",
    "__pycache__",
    ".hermes",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
}

# Specific paths to exclude
EXCLUDE_PATHS = {
    ".env",
    "build_release.py",
    "test_script.sh",
    "smoke_test_all_tools.py",
    "test_all_tools.py",
    "agent_debug.log",
    "bridge_debug.log",
    "thinking_debug.log",
}

# File extensions to exclude
EXCLUDE_EXTS = {".pyc", ".pyo"}

# Extension subdirs that are cloned repos (exclude their contents)
EXCLUDE_EXT_REPOS = {
    os.path.join("extensions", "comfyui"),
    os.path.join("extensions", "music-server"),
    os.path.join("extensions", "tts-server"),
}


def should_exclude(rel_path):
    parts = rel_path.replace("\\", "/").split("/")

    # Check dir exclusions
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True

    # Check path exclusions
    if rel_path in EXCLUDE_PATHS:
        return True

    # Check extension repos
    for repo in EXCLUDE_EXT_REPOS:
        if rel_path.startswith(repo + os.sep) or rel_path.startswith(repo + "/"):
            return True

    # Check extensions
    _, ext = os.path.splitext(rel_path)
    if ext in EXCLUDE_EXTS:
        return True

    # Skip the weird unicode filename
    if "check_lm_studio" in rel_path and rel_path.startswith("E"):
        return True

    return False


def main():
    print(f"Building release: {ZIP_NAME}")
    print(f"Source: {PROJECT_ROOT}")
    print(f"Output: {ZIP_PATH}")
    print()

    count = 0
    prefix = "portable-hermes-agent"

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # Prune excluded dirs in-place to avoid walking into them
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for fname in sorted(files):
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, PROJECT_ROOT)

                if should_exclude(rel_path):
                    continue

                archive_name = os.path.join(prefix, rel_path).replace("\\", "/")
                try:
                    zf.write(full_path, archive_name)
                    count += 1
                except (PermissionError, OSError):
                    pass

    size_mb = os.path.getsize(ZIP_PATH) / (1024 * 1024)
    print(f"Done! {count} files, {size_mb:.1f} MB")
    print(f"Output: {ZIP_PATH}")


if __name__ == "__main__":
    main()
