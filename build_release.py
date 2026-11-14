"""Build the wrapper-only release ZIP for portable-hermes-agent.

The archive holds only wrapper-owned files (``portable_hermes.ownership``):
launchers, the GUI, the portable tools and skills, docs and the
``portable_hermes`` package, plus the release-only ``LICENSE`` at the root
(``ownership.RELEASE_ONLY_FILES``; no updater installs it). The upstream
Hermes core is not shipped; the installer fetches it from
NousResearch/hermes-agent at install time.

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

Before the ZIP is written, the files it would ship must be exactly HEAD's
release files (none deleted or added), each committed and byte-identical to
``git archive HEAD`` (no line-ending conversion, as GitHub builds its source
archives). Installs that took these files from GitHub's
archive (the v1.4.18 updater downloads main.zip) would otherwise see other
bytes, and the wrapper updater would keep unedited files as user edits. A
checkout with ``core.autocrlf=true`` gives CRLF copies of files that have no
line-ending rule in ``.gitattributes``; the check names them.

``tools/`` and ``skills/`` are left out of the archive (``export-ignore`` in
``.gitattributes``, see there). Their shipped files are compared with the
committed file instead, and must be LF text (``text eol=lf``): for those the
committed bytes are exactly what every checkout holds.
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from portable_hermes import ownership  # noqa: E402

PREFIX = "portable-hermes-agent"

# Minimum bootable portable surface (from the ownership model), plus the
# release-only files such as the licence.
REQUIRED_RELEASE_FILES = set(ownership.REQUIRED_RELEASE_FILES) | set(ownership.RELEASE_ONLY_FILES)

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
    parser.add_argument(
        "--no-git-check",
        action="store_true",
        help="Build from a folder that is not a git checkout (an extracted archive). The "
             "shipped files are not compared with `git archive HEAD`, and release.json "
             "records no source commit.",
    )
    return parser.parse_args()


class SourceCheckError(RuntimeError):
    """The files to ship are not exactly what the source commit's archive holds."""


def _is_git_checkout():
    """True when PROJECT_ROOT is the top folder of a git checkout."""
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return False

    def same(path):
        return os.path.normcase(os.path.realpath(path))

    return bool(top) and same(top) == same(PROJECT_ROOT)


def _uncommitted(rels):
    """The paths among *rels* with changes that are not committed (staged or not)."""
    proc = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=no"],
                          cwd=PROJECT_ROOT, capture_output=True, check=True)
    entries = proc.stdout.decode("utf-8", "surrogateescape").split("\0")
    wanted = set(rels)
    found = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            index += 1          # the original path of a rename or copy follows
        if path in wanted:
            found.add(path)
    return sorted(found)


def _archived(rels):
    """{path: bytes} for *rels* as ``git archive HEAD`` holds them, built the way
    GitHub builds its source archives (core.autocrlf=false)."""
    found = {}
    rels = sorted(rels)
    for start in range(0, len(rels), 100):
        chunk = rels[start:start + 100]
        try:
            proc = subprocess.run(
                ["git", "--literal-pathspecs", "-c", "core.autocrlf=false", "archive",
                 "--format=tar", "HEAD", "--", *chunk],
                cwd=PROJECT_ROOT, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            raise SourceCheckError(
                "Release build stopped: `git archive HEAD` failed: "
                + exc.stderr.decode("utf-8", "replace").strip()) from exc
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    found[member.name] = tar.extractfile(member).read()
    return found


def _git_output(*args):
    try:
        return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True,
                              check=True).stdout
    except subprocess.CalledProcessError as exc:
        raise SourceCheckError(
            f"Release build stopped: `git {args[0]}` failed: "
            + exc.stderr.decode("utf-8", "replace").strip()) from exc


def _export_ignored(rels):
    """For *rels*, which ``git archive HEAD`` left out: ({path: bytes}, problems).

    A path left out by an ``export-ignore`` rule of HEAD's ``.gitattributes``
    (on the file or on a folder above it, such as ``/tools export-ignore``)
    gets its committed bytes, if it is LF text; anything else is a problem."""
    rels = sorted(rels)

    def folders(rel):
        parts = rel.split("/")[:-1]
        return ["/".join(parts[:end]) for end in range(1, len(parts) + 1)]

    asked = sorted(set(rels).union(*(folders(rel) for rel in rels)))
    attrs = {}
    for start in range(0, len(asked), 100):
        out = _git_output("check-attr", "--source=HEAD", "-z", "export-ignore", "text", "eol",
                          "--", *asked[start:start + 100])
        fields = out.decode("utf-8", "surrogateescape").split("\0")
        for path, name, value in zip(fields[0::3], fields[1::3], fields[2::3]):
            attrs.setdefault(path, {})[name] = value
    found, problems = {}, []
    for rel in rels:
        attr = attrs.get(rel, {})
        if not any(attrs.get(path, {}).get("export-ignore") == "set"
                   for path in [rel, *folders(rel)]):
            problems.append(f"{rel}: not in the archive")
        elif attr.get("text") != "set" or attr.get("eol") != "lf":
            problems.append(f"{rel}: left out of the archive (export-ignore) but not LF text; "
                            "give it a `text eol=lf` rule in .gitattributes")
        else:
            found[rel] = _git_output("cat-file", "blob", f"HEAD:{rel}")
    return found, problems


def _committed_release_files():
    """The release files of HEAD itself: its tracked paths, filtered exactly like
    the candidates (a deletion, staged or not, would otherwise just shrink the
    candidate list)."""
    try:
        proc = subprocess.run(["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
                              cwd=PROJECT_ROOT, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise SourceCheckError(
            "Release build stopped: `git ls-tree HEAD` failed: "
            + exc.stderr.decode("utf-8", "replace").strip()) from exc
    names = proc.stdout.decode("utf-8", "surrogateescape").split("\0")
    return {ownership.normalize(p) for p in names if p and not should_exclude(p)}


def _difference(have, want):
    if have.replace(b"\r\n", b"\n") == want.replace(b"\r\n", b"\n"):
        here = "CRLF" if b"\r\n" in have else "LF"
        there = "CRLF" if b"\r\n" in want else "LF"
        return f"line endings ({here} here, {there} in the archive)"
    return "content differs"


def check_sources(rels):
    """Stop unless *rels* are exactly HEAD's release files, every one committed
    and byte-identical to what ``git archive HEAD`` contains for it (for files
    an export-ignore rule leaves out of the archive: to the committed file).
    Returns how many files were compared with the committed file."""
    committed = _committed_release_files()
    present = {rel for rel in rels if os.path.isfile(os.path.join(PROJECT_ROOT, rel))}
    missing = sorted(committed - present)
    extra = sorted(set(rels) - committed)
    if missing or extra:
        raise SourceCheckError(
            "Release build stopped: the files to be shipped are not the files of the commit.\n"
            + ("  In the commit but missing here:\n" if missing else "")
            + "".join(f"    {rel}\n" for rel in missing)
            + ("  To be shipped here but not in the commit:\n" if extra else "")
            + "".join(f"    {rel}\n" for rel in extra)
            + "A release is built from a commit: restore missing files (`git checkout HEAD -- "
              "<file>`) or commit their removal, commit new files (or unstage them with "
              "`git restore --staged <file>`), then build again.")
    changed = _uncommitted(rels)
    if changed:
        raise SourceCheckError(
            "Release build stopped: these files to be shipped have changes that are not "
            "committed:\n" + "".join(f"  {rel}\n" for rel in changed)
            + "A release is built from a commit: commit them (or check out the committed "
              "version) and build again.")
    archived = _archived(rels)
    committed_bytes, problems = _export_ignored([rel for rel in rels if rel not in archived])
    for rel in sorted(rels):
        want = archived.get(rel, committed_bytes.get(rel))
        if want is None:
            continue                            # already a problem
        with open(os.path.join(PROJECT_ROOT, rel), "rb") as source:
            have = source.read()
        if have != want:
            problems.append(f"{rel}: {_difference(have, want)}")
    if problems:
        raise SourceCheckError(
            "Release build stopped: these files differ from what `git archive HEAD` contains "
            "(the bytes GitHub's source ZIP, and through it the v1.4.18 updater, delivers; for "
            "files an export-ignore rule leaves out of it: the committed file):\n"
            + "".join(f"  {problem}\n" for problem in sorted(problems))
            + "A release must be byte-identical to the archive of its commit. For line "
              "endings: give the file a rule in .gitattributes and commit it (`git add "
              "--renormalize .` first if the committed copy itself has the wrong endings), "
              "then build from a clean checkout made after that commit, for example "
              "`git -c core.autocrlf=false worktree add <new folder> HEAD`.")
    return len(committed_bytes)


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
    if ownership.is_release_only(norm_path):
        return False
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
    for rel in sorted(ownership.RELEASE_ONLY_FILES):
        if os.path.isfile(os.path.join(PROJECT_ROOT, rel)):
            yield rel


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

    if args.no_git_check:
        print("Source check skipped (--no-git-check): no source commit is recorded.")
        git_check, source_commit = "skipped (--no-git-check)", None
    elif not _is_git_checkout():
        raise SourceCheckError(
            f"Release build stopped: {PROJECT_ROOT} is not a git checkout (or git is not "
            "installed), so the files cannot be compared with `git archive HEAD`. Build from "
            "a git checkout, or pass --no-git-check to build anyway (release.json then records "
            "no source commit).")
    else:
        left_out = check_sources(candidates)
        git_check, source_commit = "passed", _source_commit()
        print(f"Source check passed: {len(candidates)} files are identical to "
              f"`git archive {source_commit[:12]}`"
              + (f" or, for the {left_out} it leaves out (export-ignore), to the committed "
                 "files." if left_out else "."))

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
                "source_commit": source_commit,
                "git_archive_check": git_check,
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


def cli():
    """Run :func:`main`; a failed source check prints its reason and returns 1."""
    try:
        main()
    except SourceCheckError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(cli())
