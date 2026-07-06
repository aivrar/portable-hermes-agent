"""Build a release zip for portable-hermes-agent."""
import argparse
import os
import subprocess
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

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
    "build_release.py",
    "test_script.sh",
    "test.pdf",
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

    count = 0
    prefix = "portable-hermes-agent"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel_path in sorted(iter_release_files()):
            if should_exclude(rel_path):
                continue

            full_path = os.path.join(PROJECT_ROOT, rel_path)
            if not os.path.isfile(full_path):
                continue

            archive_name = os.path.join(prefix, rel_path).replace("\\", "/")
            try:
                zf.write(full_path, archive_name)
                count += 1
            except (PermissionError, OSError):
                pass

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"Done! {count} files, {size_mb:.1f} MB")
    print(f"Output: {zip_path}")


if __name__ == "__main__":
    main()
