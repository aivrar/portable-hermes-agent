"""Wrapper channel: update the portable wrapper and repair it at launch.

The wrapper channel never imports Hermes core code. It replaces only paths the
ownership model calls wrapper-owned, from a published aivrar release archive,
staged, hash-checked and verified, and leaves the core and user data alone.

Releases are compared by version ("newer than", never "different from").
Releases up to :data:`LAST_PRE_EVERGREEN` predate this updater: when one of
them is the latest published release there is simply no newer wrapper yet,
and installing one explicitly is refused. A tree without a release manifest
(a git checkout, or an old install updated from the repository's main ZIP)
has an unknown version and accepts the newest evergreen release.

Launch-time repair (:func:`repair`) restores wrapper files that live inside
the core tree (portable tools, skills, README files, ``assets/SOUL.md``) from
the pristine copies a release carries under ``portable_hermes/payload/``.
That undoes upstream's own ``hermes update`` ZIP swap, which replaces whole
top-level directories such as ``tools/`` and ``skills/``. A file it overwrites
is copied to ``.portable/kept/`` first: repair cannot tell a user's edit from
an upstream overwrite.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from portable_hermes import common, ownership
from portable_hermes.common import UpdateError, log

PORTABLE_REPO = "aivrar/portable-hermes-agent"
ARCHIVE_PREFIX = "portable-hermes-agent"
STATE_FILE = "wrapper-state.json"
#: The last published release without the evergreen updater (no
#: portable_hermes/ownership.py, no release manifest).
LAST_PRE_EVERGREEN = (1, 4, 18)
_ASSET_RE = re.compile(r"^portable-hermes-agent-v?[0-9A-Za-z.\-]+\.zip$")
_TAG_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.\-]*$")


def read_manifest(root: Path) -> dict | None:
    return common.read_json(Path(root) / ownership.RELEASE_MANIFEST)


def installed_version(root: Path) -> str | None:
    """The installed wrapper release, ``None`` when unknown (no manifest)."""
    state = common.read_json(common.state_dir(root) / STATE_FILE)
    if state and state.get("version"):
        return state["version"]
    manifest = read_manifest(root)
    return manifest.get("version") if manifest else None


def parse_version(tag) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", str(tag or "").strip())
    return tuple(int(p) for p in match.group(1).split(".")) if match else None


def is_evergreen(tag) -> bool:
    version = parse_version(tag)
    return version is not None and version > LAST_PRE_EVERGREEN


def is_newer(candidate, installed) -> bool:
    """True when *candidate* is a newer release than *installed*.

    An unknown installed version accepts any evergreen release.
    """
    cand = parse_version(candidate)
    if cand is None or not is_evergreen(candidate):
        return False
    inst = parse_version(installed)
    return inst is None or cand > inst


# --------------------------------------------------------------------------
# launch-time repair
# --------------------------------------------------------------------------

def repair(root: Path, *, quiet: bool = True) -> dict:
    """Fast, never-raising repair run by every launcher before Hermes starts."""
    root = Path(root)
    report: dict = {"restored": [], "notes": [], "kept": 0, "kept_folder": None}
    lock = common.InstallLock(root)
    try:
        if not lock.acquire():
            report["notes"].append("an update is running; repair skipped")
            return report
    except OSError as exc:
        report["notes"].append(f"repair skipped: {exc}")
        return report
    try:
        try:
            recovered = common.recover(root)
            if recovered:
                report["notes"].append(recovered)
        except (OSError, UpdateError) as exc:
            report["notes"].append("could not settle an interrupted update: "
                                   + getattr(exc, "reason", str(exc)))
        manifest = read_manifest(root)
        payload = (manifest or {}).get("payload") or {}
        keep: dict = {"rel": None}

        def keep_folder() -> str:
            if keep["rel"] is None:
                keep["rel"] = common.new_kept_dir(root, "repair")
            return keep["rel"]

        for rel, digest in sorted(payload.items()):
            try:
                outcome = _restore_payload_file(root, rel, digest, keep_folder)
            except OSError as exc:
                report["notes"].append(f"could not restore {rel}: {exc}")
                continue
            if outcome:
                report["restored"].append(rel)
            if outcome == "kept":
                report["kept"] += 1
        report["kept_folder"] = keep["rel"]
        if not manifest:
            report["notes"].append("development checkout: nothing to repair")
        try:
            from portable_hermes import bridge
            site = bridge.site_packages(root / "python_embedded")
            hook = bridge.ensure_pth(site)
            if hook not in ("ok", "no python_embedded site-packages"):
                report["notes"].append(f"toolsets hook: {hook}")
            if bridge.ROOT == root.resolve():
                moved = bridge.ensure_project_pth(site)
                if moved == "written":
                    report["notes"].append("hermes_project.pth now points at this folder")
            problem = bridge.read_problem(root)
            if problem:
                report["bridge_problem"] = problem
        except Exception as exc:  # noqa: BLE001 - never fail a launch
            report["notes"].append(f"toolsets hook: {exc}")
    finally:
        lock.release()
    if report["restored"]:
        log(f"Portable repair: restored {len(report['restored'])} wrapper file(s) "
            "replaced by an upstream update.", quiet=quiet)
    if report["kept"]:
        log(f"  The {report['kept']} file(s) it overwrote are kept in "
            f"{report['kept_folder']}.", quiet=quiet)
    return report


def _restore_payload_file(root: Path, rel: str, digest: str, keep_folder) -> str | None:
    """Put the pristine copy of *rel* back. Returns None (already right),
    ``"restored"`` (was missing) or ``"kept"`` (overwrote a different file,
    whose content was copied to the keep folder first)."""
    rel = ownership.normalize(rel)
    if not ownership.is_payload_path(rel):
        return None
    live = root / rel
    if live.is_file() and common.sha256_file(live) == digest:
        return None
    source = root / ownership.PAYLOAD_DIR / rel
    if not source.is_file() or common.sha256_file(source) != digest:
        raise OSError(f"pristine copy {ownership.PAYLOAD_DIR}/{rel} is missing or damaged")
    if live.is_dir():
        raise OSError(f"{rel} is a directory")
    outcome = "restored"
    if live.is_file():
        kept = root / keep_folder() / rel
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, kept)
        outcome = "kept"
    live.parent.mkdir(parents=True, exist_ok=True)
    tmp = live.with_name(live.name + ".portable-tmp")
    shutil.copyfile(source, tmp)
    os.replace(tmp, live)
    return outcome


# --------------------------------------------------------------------------
# wrapper update
# --------------------------------------------------------------------------

def latest_release(timeout: float = 20) -> dict:
    """Find the newest published release asset (API first, redirect fallback)."""
    try:
        data = common.github_json(
            f"https://api.github.com/repos/{PORTABLE_REPO}/releases/latest", timeout=timeout)
        tag = str(data.get("tag_name") or "")
        for asset in data.get("assets") or []:
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or "")
            if _ASSET_RE.match(name) and url.startswith("https://github.com/"):
                return {"tag": tag, "url": url, "asset": name}
        raise UpdateError(f"release {tag} has no portable-hermes-agent ZIP asset",
                          code="no_asset")
    except UpdateError as api_error:
        if api_error.code == "no_asset":
            raise
        tag = _latest_tag_from_redirect(timeout)
        if not tag:
            raise
        name = f"portable-hermes-agent-{tag}.zip"
        return {"tag": tag, "asset": name,
                "url": f"https://github.com/{PORTABLE_REPO}/releases/download/{tag}/{name}"}


def _latest_tag_from_redirect(timeout: float) -> str | None:
    import urllib.request
    url = f"https://github.com/{PORTABLE_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": common.USER_AGENT})
        with common._opener().open(req, timeout=timeout) as resp:
            final = resp.geturl()
    except Exception:  # noqa: BLE001 - this is the fallback path
        return None
    match = re.search(r"/releases/tag/([^/?#]+)$", final or "")
    tag = match.group(1) if match else None
    return tag if tag and _TAG_RE.match(tag) else None


def _staged_categories(python: str, top: Path, rels: list[str]) -> dict:
    """Classify *rels* with the STAGED release's ownership rules, in a fresh process."""
    script = top / "portable_hermes" / "ownership.py"
    common.flush_output()
    proc = subprocess.run([python, "-I", str(script), "classify"],
                          input="\n".join(rels), capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env=common.clean_python_env())
    if proc.returncode != 0:
        raise UpdateError("the new release's ownership rules could not be read: "
                          + (proc.stderr or proc.stdout).strip()[-400:], code="bad_release")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise UpdateError("the new release's ownership rules returned unreadable output",
                          code="bad_release") from exc


def _preverify(python: str, top: Path) -> None:
    code = (
        "import compileall, sys; sys.path.insert(0, sys.argv[1]);"
        "ok = all(compileall.compile_dir(sys.argv[1] + '/' + d, quiet=1, legacy=False,"
        " force=True, workers=1, ddir=d) for d in ('portable_hermes', 'gui'));"
        "import portable_hermes.ownership, portable_hermes.common, portable_hermes.core,"
        " portable_hermes.wrapper, portable_hermes.bridge, portable_hermes.verify,"
        " portable_hermes.recovery, portable_hermes.runtime;"
        "sys.exit(0 if ok else 1)"
    )
    env = common.clean_python_env({"PORTABLE_HERMES_NO_HOOK": "1"})
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    common.flush_output()
    proc = subprocess.run([python, "-I", "-c", code, str(top)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300, env=env)
    for cache in top.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    if proc.returncode != 0:
        raise UpdateError("the new wrapper does not compile or import: "
                          + ((proc.stdout or "") + (proc.stderr or "")).strip()[-600:],
                          code="verify_failed")


class WrapperUpdater:
    def __init__(self, root: Path, *, python: str | None = None, quiet: bool = False,
                 run_verify=None):
        self.root = Path(root).resolve()
        self.python = python or sys.executable
        self.quiet = quiet
        if run_verify is None:
            from portable_hermes.core import CoreLifecycle
            run_verify = CoreLifecycle(self.root, python=self.python, quiet=True)._default_verify
        self._run_verify = run_verify

    def say(self, message: str) -> None:
        log(message, quiet=self.quiet)

    @property
    def state_path(self) -> Path:
        return common.state_dir(self.root) / STATE_FILE

    def recorded_files(self) -> dict:
        state = common.read_json(self.state_path)
        if state and isinstance(state.get("files"), dict):
            return state["files"]
        manifest = read_manifest(self.root) or {}
        return manifest.get("files") or {}

    def check(self, timeout: float = 20) -> dict:
        installed = installed_version(self.root)
        info = {"ok": True, "installed_version": installed or "unknown"}
        if (self.root / ".git").exists():
            info["install_type"] = "git"
        try:
            rel = latest_release(timeout)
        except UpdateError as exc:
            info.update(latest_version=None, update_available=None, network_error=exc.reason)
            return info
        info["latest_version"] = rel["tag"]
        if not is_evergreen(rel["tag"]):
            info["update_available"] = False
            info["message"] = (f"no newer Portable Hermes release yet (the latest published "
                               f"release, {rel['tag']}, predates this updater)")
        else:
            info["update_available"] = is_newer(rel["tag"], installed)
            if not info["update_available"]:
                info["message"] = f"wrapper is current (latest release {rel['tag']})"
        return info

    def update(self, *, zip_path: str | None = None, tag: str | None = None,
               force: bool = False) -> dict:
        """Update the wrapper. Returns a result dict (never raises).

        In a git clone git owns the wrapper files: nothing is changed and the
        result says to use ``git pull`` (a success, so UPDATE.bat goes on to
        the core step)."""
        if (self.root / ".git").exists():
            return {"ok": True, "changed": False, "code": "git_checkout",
                    "install_type": "git",
                    "message": "git checkout: update the wrapper with git pull."}
        try:
            with common.InstallLock(self.root):
                recovered = common.recover(self.root)
                staging = common.staging_dir(self.root)
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir(parents=True)
                ctx: dict = {"txn": None}
                try:
                    result = self._update_in(staging, ctx, zip_path=zip_path, tag=tag,
                                             force=force)
                except Exception as exc:  # noqa: BLE001 - the result promise
                    error = exc if isinstance(exc, UpdateError) else UpdateError(
                        f"unexpected {type(exc).__name__} during the wrapper update: {exc}",
                        code="internal")
                    txn = ctx.get("txn")
                    if txn is not None and txn.applied and not txn.committed:
                        try:
                            txn.rollback()
                        except (OSError, UpdateError) as undo:
                            error.reason += (f"; undoing the file swap failed ({undo}). Start "
                                             "Hermes again: the launcher finishes the undo")
                    raise error from (None if error is exc else exc)
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
                if recovered:
                    result["recovered"] = recovered
                return result
        except UpdateError as exc:
            out = {"ok": False, "code": exc.code, "reason": exc.reason}
            out.update({k: v for k, v in exc.details.items() if k not in out})
            return out
        except Exception as exc:  # noqa: BLE001 - the result promise
            return {"ok": False, "code": "internal",
                    "reason": f"unexpected {type(exc).__name__}: {exc}"}

    def _update_in(self, staging: Path, ctx: dict, *, zip_path, tag, force) -> dict:
        current = installed_version(self.root)
        explicit = bool(zip_path or tag)
        if zip_path:
            archive = Path(zip_path).resolve()
            if not archive.is_file():
                raise UpdateError(f"wrapper archive not found: {archive}", code="no_archive")
            source = f"local ZIP {archive.name}"
        else:
            if tag:
                if not _TAG_RE.match(tag):
                    raise UpdateError(f"invalid release tag {tag!r}", code="usage")
                if parse_version(tag) and not is_evergreen(tag):
                    raise UpdateError(f"release {tag} predates the evergreen wrapper; refusing "
                                      "to install it over a newer wrapper", code="downgrade")
                name = f"portable-hermes-agent-{tag}.zip"
                release = {"tag": tag, "asset": name, "url":
                           f"https://github.com/{PORTABLE_REPO}/releases/download/{tag}/{name}"}
            else:
                release = latest_release()
                if not is_evergreen(release["tag"]):
                    return {"ok": True, "changed": False, "version": current or "unknown",
                            "message": "no newer Portable Hermes release yet (the latest "
                                       f"published release, {release['tag']}, predates this "
                                       "updater)"}
                if not force and not is_newer(release["tag"], current):
                    return {"ok": True, "changed": False, "version": current,
                            "message": f"wrapper already at {current} (latest release "
                                       f"{release['tag']})"}
            self.say(f"Downloading Portable Hermes {release['tag']} ...")
            archive = common.download(release["url"], staging / release["asset"],
                                      quiet=self.quiet)
            source = release["url"]
        extract = staging / "x"
        common.check_path_lengths(self.root, common.archive_names(archive),
                                  overhead=common.STATE_PATH_OVERHEAD, what="this release")
        names = common.safe_extract(archive, extract)
        top_name = common.single_top_dir(names)
        if top_name != ARCHIVE_PREFIX:
            raise UpdateError(f"not a Portable Hermes release archive (expected a single "
                              f"{ARCHIVE_PREFIX}/ folder)", code="bad_release")
        top = extract / top_name
        rels = sorted(n.split("/", 1)[1] for n in names)
        rel_keys = {ownership.key(r) for r in rels}
        if "portable_hermes/ownership.py" not in rel_keys:
            raise UpdateError("this release predates the evergreen wrapper; refusing to "
                              "install it over a newer wrapper", code="downgrade")
        manifest = common.read_json(top / ownership.RELEASE_MANIFEST)
        if not manifest or not isinstance(manifest.get("files"), dict):
            raise UpdateError("the release has no readable portable_hermes/release.json",
                              code="bad_release")
        for rel, digest in manifest["files"].items():
            path = top / rel
            if not path.is_file() or common.sha256_file(path) != digest:
                raise UpdateError(f"release file {rel} is missing or does not match its "
                                  "recorded hash", code="bad_release")
        version = str(manifest.get("version") or "unknown")
        if explicit and not force and parse_version(current) and parse_version(version) \
                and parse_version(version) < parse_version(current):
            raise UpdateError(f"release {version} is older than the installed {current}; "
                              "pass --force to install it anyway", code="downgrade")
        categories = _staged_categories(self.python, top, rels)
        install, skipped = [], []
        for rel in rels:
            if ownership.is_release_only(rel):
                continue        # shipped for the download (LICENSE); never installed
            if ownership.classify(rel) == "user":
                skipped.append(f"{rel} (user data)")
            elif categories.get(rel) != "wrapper":
                skipped.append(f"{rel} ({categories.get(rel, 'unknown')} path)")
            else:
                install.append(rel)
        self.say("Checking the new wrapper ...")
        _preverify(self.python, top)
        baseline = self._run_verify(self.root)
        recorded = self.recorded_files()
        recorded_by_key = {ownership.key(r): h for r, h in recorded.items()}
        txn = common.Transaction(self.root, "wrapper")
        ctx["txn"] = txn
        hashes = {}
        for rel in install:
            hashes[rel] = common.sha256_file(top / rel)
            live = self.root / rel
            if live.is_dir():
                raise UpdateError(f"cannot install {rel}: a directory is in the way",
                                  code="swap_failed")
            preserve = False
            if live.is_file():
                live_hash = common.sha256_file(live)
                if live_hash == hashes[rel]:
                    continue
                expected = recorded_by_key.get(ownership.key(rel))
                # Files a release writes about itself (release.json cannot list
                # its own hash) are never anyone's edit.
                preserve = not ownership.is_release_generated(rel) and (
                    expected is None or live_hash != expected)
            txn.put(rel, top / rel, preserve=preserve)
        removed, kept = [], []
        install_keys = {ownership.key(r) for r in hashes}
        for rel, digest in sorted(recorded.items()):
            if ownership.key(rel) in install_keys or not ownership.is_wrapper(rel):
                continue
            if categories.get(rel) == "user" or ownership.classify(rel) == "user":
                continue
            live = self.root / rel
            if not live.is_file():
                continue
            if common.sha256_file(live) == digest:
                txn.remove(rel)
                removed.append(rel)
            else:
                kept.append(rel)
        changed = bool(txn.ops)
        staged_state = staging / "st" / STATE_FILE
        common.write_json_atomic(staged_state, {
            "schema": 1, "version": version, "source": source,
            "installed_at": common.now_iso(), "files": hashes,
        })
        txn.put(f"{common.STATE_DIR}/{STATE_FILE}", staged_state)
        written = len(txn.file_ops) - len(removed)
        self.say(f"Replacing {written} wrapper files, removing {len(removed)} ...")
        txn.apply()
        if baseline.get("ok"):
            after = self._run_verify(self.root)
            if not after.get("ok"):
                raise UpdateError("the updated wrapper failed verification and was rolled "
                                  f"back: {after.get('reason')}", code="verify_failed")
            verification = "full verification passed"
        else:
            verification = ("wrapper compiled and imported; the core was already failing "
                            f"verification before the update ({baseline.get('reason')}), "
                            "run a core update")
        done = txn.commit()
        try:
            common.prune_empty_dirs(self.root, removed)
        except OSError:
            pass
        result = {
            "ok": True, "changed": changed, "version": version, "source": source,
            "files_written": written, "files_removed": len(removed),
            "kept_modified": kept, "skipped": skipped[:50], "skipped_count": len(skipped),
            "kept_edits": done["keep"], "kept_edits_count": done["kept"],
            "verification": verification,
            "message": (f"wrapper updated to {version}" if changed else
                        f"wrapper files already match {version}"),
        }
        if not recorded:
            # Nothing records what was installed (a v1.4.18-or-older install
            # updated from the repository's main ZIP): every differing file
            # is the previous version's copy, not necessarily the user's edit.
            result.update(adopted=True, adopted_what="the previous Portable Hermes version")
        return result
