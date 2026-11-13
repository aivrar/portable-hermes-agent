"""Build the wrapper-only release ZIP for portable-hermes-agent.

The archive holds only wrapper-owned files (``portable_hermes.ownership``):
launchers, the GUI, the portable tools and skills, docs and the
``portable_hermes`` package. The upstream Hermes core is not shipped; the
installer fetches it from NousResearch/hermes-agent at install time.

Guarantees kept from the full-fork builder:

* built from git's tracked files (ignored scratch files cannot leak in);
* fails when a required file is missing;
* every member is re-read and hash-checked before the archive is published;
* a failed build never replaces a previously published archive.

Added for the evergreen wrapper:

* ``portable_hermes/payload/<path>``: pristine copies of wrapper files that
  live inside the core tree (portable tools, skills, README files, ...).
  Launch-time repair restores them after upstream's own updater replaced
  them. Generated here, never committed.
* ``portable_hermes/release.json``: version, source commit, the hash of every
  member and the payload list. The wrapper updater checks it.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from portable_hermes import ownership  # noqa: E402

PREFIX = "portable-hermes-agent"

# Minimum bootable portable surface (from the ownership model).
REQUIRED_RELEASE_FILES = set(ownership.REQUIRED_RELEASE_FILES)

# Paths that never ship even when tracked inside a wrapper tree.
EXCLUDE_DIRS = {"__pycache__", "tests"}
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
EXCLUDE_EXTS = {".pyc", ".pyo"}


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
    """True for every tracked path that does not belong in a wrapper release."""
    norm_path = ownership.normalize(rel_path)
    parts = norm_path.split("/")
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    if norm_path in EXCLUDE_PATHS:
        return True
    if os.path.splitext(norm_path)[1] in EXCLUDE_EXTS:
        return True
    return not ownership.is_release_member(norm_path)


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
    """Fallback walk of the wrapper locations for trees without git metadata."""
    yield from ownership.iter_wrapper_files(PROJECT_ROOT)


def _source_commit():
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                                capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _digest(path):
    with open(path, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


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

    candidates = sorted({ownership.normalize(p) for p in iter_release_files()
                         if not should_exclude(p)})
    missing = REQUIRED_RELEASE_FILES - set(candidates)
    if missing:
        raise RuntimeError(f"Incomplete portable inventory: {', '.join(sorted(missing))}")

    # member name (inside the prefix) -> source path on disk
    members = {rel: os.path.join(PROJECT_ROOT, rel) for rel in candidates}
    payload = {}
    for rel in candidates:
        if ownership.is_payload_path(rel):
            members[f"{ownership.PAYLOAD_DIR}/{rel}"] = members[rel]
            payload[rel] = None

    # Never replace a good published build with a partial ZIP. Every included
    # source must be readable, and every archive entry must match its source.
    fd, staging_path = tempfile.mkstemp(prefix=zip_name + ".", suffix=".tmp", dir=output_dir)
    os.close(fd)
    try:
        expected = {}
        with zipfile.ZipFile(staging_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel, full_path in members.items():
                digest = _digest(full_path)
                zf.write(full_path, f"{PREFIX}/{rel}")
                expected[f"{PREFIX}/{rel}"] = digest
            for rel in payload:
                payload[rel] = expected[f"{PREFIX}/{rel}"]
            manifest = {
                "schema": 1,
                "version": f"v{version}",
                "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "source_commit": _source_commit(),
                "files": {name[len(PREFIX) + 1:]: digest for name, digest in expected.items()},
                "payload": payload,
            }
            manifest_bytes = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()
            manifest_name = f"{PREFIX}/{ownership.RELEASE_MANIFEST}"
            zf.writestr(manifest_name, manifest_bytes)
            expected[manifest_name] = hashlib.sha256(manifest_bytes).hexdigest()
        with zipfile.ZipFile(staging_path) as zf:
            if len(zf.namelist()) != len(expected) or set(zf.namelist()) != set(expected):
                raise RuntimeError("Release archive inventory mismatch")
            for name, digest in expected.items():
                with zf.open(name) as member:
                    if hashlib.file_digest(member, "sha256").hexdigest() != digest:
                        raise RuntimeError(f"Release archive content mismatch: {name}")
        os.replace(staging_path, zip_path)
    finally:
        if os.path.exists(staging_path):
            os.unlink(staging_path)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"Verified! {len(expected)} files ({len(payload)} payload copies), {size_mb:.1f} MB")
    print(f"Output: {zip_path}")


if __name__ == "__main__":
    main()
