"""Wrapper channel: update the portable wrapper and repair it at launch.

The wrapper channel never imports Hermes core code. It replaces only paths the
ownership model calls wrapper-owned, from a published aivrar release archive,
staged, hash-checked and verified, and leaves the core and user data alone.

Launch-time repair (:func:`repair`) restores wrapper files that live inside
the core tree (portable tools, skills, README files, ``assets/SOUL.md``) from
the pristine copies a release carries under ``portable_hermes/payload/``.
That undoes upstream's own ``hermes update`` ZIP swap, which replaces whole
top-level directories such as ``tools/`` and ``skills/``.
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
_ASSET_RE = re.compile(r"^portable-hermes-agent-v?[0-9A-Za-z.\-]+\.zip$")
_TAG_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.\-]*$")


def read_manifest(root: Path) -> dict | None:
    return common.read_json(Path(root) / ownership.RELEASE_MANIFEST)


def installed_version(root: Path) -> str | None:
    state = common.read_json(common.state_dir(root) / STATE_FILE)
    if state and state.get("version"):
        return state["version"]
    manifest = read_manifest(root)
    return manifest.get("version") if manifest else None


# --------------------------------------------------------------------------
# launch-time repair
# --------------------------------------------------------------------------

def repair(root: Path, *, quiet: bool = True) -> dict:
    """Fast, never-raising repair run by every launcher before Hermes starts."""
    root = Path(root)
    report: dict = {"restored": [], "notes": []}
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
        except OSError as exc:
            report["notes"].append(f"could not settle an interrupted update: {exc}")
        manifest = read_manifest(root)
        payload = (manifest or {}).get("payload") or {}
        for rel, digest in sorted(payload.items()):
            try:
                if _restore_payload_file(root, rel, digest):
                    report["restored"].append(rel)
            except OSError as exc:
                report["notes"].append(f"could not restore {rel}: {exc}")
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
        except Exception as exc:  # noqa: BLE001 - never fail a launch
            report["notes"].append(f"toolsets hook: {exc}")
    finally:
        lock.release()
    if report["restored"]:
        log(f"Portable repair: restored {len(report['restored'])} wrapper file(s) "
            "replaced by an upstream update.", quiet=quiet)
    return report


def _restore_payload_file(root: Path, rel: str, digest: str) -> bool:
    rel = ownership.normalize(rel)
    if not ownership.is_payload_path(rel):
        return False
    live = root / rel
    if live.is_file() and common.sha256_file(live) == digest:
        return False
    source = root / ownership.PAYLOAD_DIR / rel
    if not source.is_file() or common.sha256_file(source) != digest:
        raise OSError(f"pristine copy {ownership.PAYLOAD_DIR}/{rel} is missing or damaged")
    if live.is_dir():
        raise OSError(f"{rel} is a directory")
    live.parent.mkdir(parents=True, exist_ok=True)
    tmp = live.with_name(live.name + ".portable-tmp")
    shutil.copyfile(source, tmp)
    os.replace(tmp, live)
    return True


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
        " portable_hermes.wrapper, portable_hermes.bridge, portable_hermes.verify;"
        "sys.exit(0 if ok else 1)"
    )
    env = common.clean_python_env({"PORTABLE_HERMES_NO_HOOK": "1"})
    env.pop("PYTHONDONTWRITEBYTECODE", None)
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
        info = {"ok": True, "installed_version": installed_version(self.root)}
        if (self.root / ".git").exists():
            info["install_type"] = "git"
        try:
            rel = latest_release(timeout)
            info["latest_version"] = rel["tag"]
            info["update_available"] = (rel["tag"] or "").lstrip("v") != \
                (info["installed_version"] or "").lstrip("v")
        except UpdateError as exc:
            info["latest_version"] = None
            info["update_available"] = None
            info["network_error"] = exc.reason
        return info

    def update(self, *, zip_path: str | None = None, tag: str | None = None,
               force: bool = False, allow_git: bool = False) -> dict:
        if (self.root / ".git").exists() and not allow_git:
            return {"ok": False, "code": "git_checkout",
                    "reason": "this install is a git checkout; update it with git pull"}
        try:
            with common.InstallLock(self.root):
                recovered = common.recover(self.root)
                staging = common.staging_dir(self.root)
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir(parents=True)
                try:
                    result = self._update_in(staging, zip_path=zip_path, tag=tag, force=force)
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
                if recovered:
                    result["recovered"] = recovered
                return result
        except UpdateError as exc:
            return {"ok": False, "code": exc.code, "reason": exc.reason}

    def _update_in(self, staging: Path, *, zip_path, tag, force) -> dict:
        if zip_path:
            archive = Path(zip_path).resolve()
            if not archive.is_file():
                raise UpdateError(f"wrapper archive not found: {archive}", code="no_archive")
            source = f"local ZIP {archive.name}"
        else:
            if tag:
                if not _TAG_RE.match(tag):
                    raise UpdateError(f"invalid release tag {tag!r}", code="usage")
                name = f"portable-hermes-agent-{tag}.zip"
                release = {"tag": tag, "asset": name, "url":
                           f"https://github.com/{PORTABLE_REPO}/releases/download/{tag}/{name}"}
            else:
                release = latest_release()
            current = installed_version(self.root)
            if not force and current and current.lstrip("v") == release["tag"].lstrip("v"):
                return {"ok": True, "changed": False, "version": current,
                        "message": f"wrapper already at {current}"}
            self.say(f"Downloading Portable Hermes {release['tag']} ...")
            archive = common.download(release["url"], staging / release["asset"],
                                      quiet=self.quiet)
            source = release["url"]
        extract = staging / "x"
        common.check_path_lengths(self.root, common.archive_names(archive),
                                  overhead=len(".portable/s/x/"), what="this release")
        names = common.safe_extract(archive, extract)
        top_name = common.single_top_dir(names)
        if top_name != ARCHIVE_PREFIX:
            raise UpdateError(f"not a Portable Hermes release archive (expected a single "
                              f"{ARCHIVE_PREFIX}/ folder)", code="bad_release")
        top = extract / top_name
        rels = sorted(n.split("/", 1)[1] for n in names)
        if "portable_hermes/ownership.py" not in rels:
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
        categories = _staged_categories(self.python, top, rels)
        install, skipped = [], []
        for rel in rels:
            if ownership.classify(rel) == "user":
                skipped.append(f"{rel} (user data)")
            elif categories.get(rel) != "wrapper":
                skipped.append(f"{rel} ({categories.get(rel, 'unknown')} path)")
            else:
                install.append(rel)
        self.say("Checking the new wrapper ...")
        _preverify(self.python, top)
        baseline = self._run_verify(self.root)
        txn = common.Transaction(self.root, "wrapper")
        hashes = {}
        for rel in install:
            hashes[rel] = common.sha256_file(top / rel)
            live = self.root / rel
            if live.is_file() and common.sha256_file(live) == hashes[rel]:
                continue
            if live.is_dir():
                raise UpdateError(f"cannot install {rel}: a directory is in the way",
                                  code="swap_failed")
            txn.put(rel, top / rel)
        removed, kept = [], []
        for rel, digest in sorted(self.recorded_files().items()):
            if rel in hashes or not ownership.is_wrapper(rel):
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
        self.say(f"Replacing {len(txn.ops) - len(removed)} wrapper files, "
                 f"removing {len(removed)} ...")
        txn.apply()
        if baseline.get("ok"):
            after = self._run_verify(self.root)
            if not after.get("ok"):
                common.rollback(self.root)
                raise UpdateError("the updated wrapper failed verification and was rolled "
                                  f"back: {after.get('reason')}", code="verify_failed")
            verification = "full verification passed"
        else:
            verification = ("wrapper compiled and imported; the core was already failing "
                            f"verification before the update ({baseline.get('reason')}), "
                            "run a core update")
        txn.commit()
        common.prune_empty_dirs(self.root, removed)
        common.write_json_atomic(self.state_path, {
            "schema": 1, "version": version, "source": source,
            "installed_at": common.now_iso(), "files": hashes,
        })
        changed = bool(txn.ops)
        return {
            "ok": True, "changed": changed, "version": version, "source": source,
            "files_written": len(txn.ops) - len(removed), "files_removed": len(removed),
            "kept_modified": kept, "skipped": skipped[:50], "skipped_count": len(skipped),
            "verification": verification,
            "message": (f"wrapper updated to {version}" if changed else
                        f"wrapper files already match {version}"),
        }
