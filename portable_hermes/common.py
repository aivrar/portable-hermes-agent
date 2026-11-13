"""Shared machinery for the portable updaters (stdlib only).

* HTTPS downloads and GitHub API reads (no credentials are ever sent)
* safe archive extraction (zip-slip, absolute paths and symlinks rejected)
* a journaled file transaction: every file move is a same-filesystem rename
  under ``<root>/.portable``, so an interrupted swap can always be rolled back
* an inter-process lock and atomic JSON state files

Nothing here imports Hermes core code.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from portable_hermes import ownership

STATE_DIR = ".portable"
USER_AGENT = "portable-hermes-updater"
_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")


class UpdateError(RuntimeError):
    """A failure with a precise, user-readable reason."""

    def __init__(self, reason: str, *, code: str = "error"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_dir(root: Path) -> Path:
    return Path(root) / STATE_DIR


# Staging and backup directories use one-letter names on purpose: upstream
# ships files up to ~130 characters deep, and Windows without long-path
# support fails beyond 259 characters. The install lock means only one
# updater runs at a time, so no per-process names are needed.
def staging_dir(root: Path) -> Path:
    return state_dir(root) / "s"


def backup_root(root: Path) -> Path:
    return state_dir(root) / "b"


MAX_PATH = 259


def long_paths_enabled() -> bool:
    """True when Windows long paths are on (or this is not Windows)."""
    if os.name != "nt":
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def check_path_lengths(root: Path, rels, *, overhead: int, what: str) -> None:
    """Refuse up front when the deepest file would exceed MAX_PATH.

    *overhead* is the extra length staging and backups add under *root*.
    Raises ``UpdateError(code="path_too_long")`` with the limit for this
    archive, instead of failing halfway with a cryptic "file not found".
    """
    if long_paths_enabled():
        return
    longest = max((len(r) for r in rels), default=0)
    base = len(str(Path(root).resolve()))
    if base + 1 + overhead + longest <= MAX_PATH:
        return
    limit = MAX_PATH - 1 - overhead - longest
    raise UpdateError(
        f"the install folder path is {base} characters long; {what} needs it to be at "
        f"most {limit} on this PC because Windows long paths are turned off. Move the "
        f"folder to a shorter path (for example C:\\PortableHermes) or enable long paths "
        f"(LongPathsEnabled), then run the update again.", code="path_too_long")


def read_json(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_json_atomic(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def log(message: str, *, quiet: bool = False) -> None:
    """Print console-safe (ASCII) progress text."""
    if quiet:
        return
    text = str(message).encode("ascii", "replace").decode("ascii")
    print(text, flush=True)


# --------------------------------------------------------------------------
# lock
# --------------------------------------------------------------------------

class InstallLock:
    """Exclusive, non-blocking lock released by the OS if the holder dies."""

    def __init__(self, root: Path):
        self.path = state_dir(root) / "lock"
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - the product is Windows-only
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        if not self.acquire():
            raise UpdateError(
                "another portable update or repair is running for this install",
                code="locked",
            )
        return self

    def __exit__(self, *exc):
        self.release()


# --------------------------------------------------------------------------
# network (HTTPS only, no credentials)
# --------------------------------------------------------------------------

class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).lower().startswith("https://"):
            raise urllib.error.URLError(f"refusing non-HTTPS redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(_HttpsOnlyRedirect())


def _request(url: str, accept: str | None = None):
    if not str(url).lower().startswith("https://"):
        raise UpdateError(f"refusing non-HTTPS URL: {url}", code="insecure_url")
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def http_get(url: str, *, accept: str | None = None, timeout: float = 30) -> bytes:
    try:
        with _opener().open(_request(url, accept), timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"HTTP {exc.code} from {url}", code=f"http_{exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise UpdateError(f"network error fetching {url}: {exc}", code="network") from exc


def download(url: str, dest: Path, *, timeout: float = 600, quiet: bool = False) -> Path:
    """Stream *url* to *dest* (HTTPS only). Returns *dest*."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    deadline = time.monotonic() + timeout
    try:
        with _opener().open(_request(url), timeout=min(timeout, 60)) as resp, \
                open(tmp, "wb") as out:
            total = 0
            last_report = 0
            while True:
                if time.monotonic() > deadline:
                    raise UpdateError(f"download timed out after {timeout}s: {url}",
                                      code="timeout")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                total += len(chunk)
                if total - last_report >= 8 << 20:
                    log(f"  downloaded {total >> 20} MB", quiet=quiet)
                    last_report = total
    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"HTTP {exc.code} downloading {url}", code=f"http_{exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        tmp.unlink(missing_ok=True)
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"network error downloading {url}: {exc}", code="network") from exc
    os.replace(tmp, dest)
    return dest


def github_commit_sha(repo: str, ref: str, *, timeout: float = 20) -> str:
    """Resolve *ref* to a commit SHA through the GitHub API."""
    body = http_get(f"https://api.github.com/repos/{repo}/commits/{ref}",
                    accept="application/vnd.github.sha", timeout=timeout)
    text = body.decode("ascii", "replace").strip()
    if not _SHA_RE.fullmatch(text):
        raise UpdateError(f"unexpected commit lookup answer for {repo}@{ref}", code="api")
    return text


def github_compare(repo: str, base: str, head: str, *, timeout: float = 20) -> dict:
    body = http_get(f"https://api.github.com/repos/{repo}/compare/{base}...{head}",
                    accept="application/vnd.github+json", timeout=timeout)
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise UpdateError("unreadable compare answer from GitHub", code="api") from exc
    return {
        "status": data.get("status"),
        "ahead_by": data.get("ahead_by"),
        "behind_by": data.get("behind_by"),
    }


def github_json(url: str, *, timeout: float = 20) -> dict:
    body = http_get(url, accept="application/vnd.github+json", timeout=timeout)
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise UpdateError(f"unreadable JSON from {url}", code="api") from exc
    if not isinstance(data, dict):
        raise UpdateError(f"unexpected JSON from {url}", code="api")
    return data


# --------------------------------------------------------------------------
# archives
# --------------------------------------------------------------------------

def archive_commit(zip_path: Path) -> str | None:
    """The commit GitHub records in an archive's ZIP comment, if any."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            comment = zf.comment.decode("ascii", "replace")
    except (OSError, zipfile.BadZipFile):
        return None
    match = _SHA_RE.search(comment)
    return match.group(0) if match else None


def _unsafe_member_reason(info: zipfile.ZipInfo) -> str | None:
    name = info.filename
    if "\x00" in name:
        return "NUL byte in name"
    norm = name.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        return "absolute path"
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return "parent directory reference"
    if any(":" in p for p in parts):
        return "drive or stream separator in name"
    mode = (info.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        return "symbolic link"
    return None


def safe_extract(zip_path: Path, dest: Path, keep=None, strip_top: bool = False) -> list[str]:
    """Extract *zip_path* into *dest*, refusing unsafe members.

    Returns the extracted file names relative to *dest* (POSIX style).
    The whole archive is validated before anything is written. *keep*, if
    given, receives each file's POSIX name and decides whether to write it.
    With *strip_top*, a single top-level folder shared by every member (as in
    GitHub source archives) is dropped from the written paths and names.
    """
    dest = Path(dest)
    try:
        zf = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"not a readable ZIP archive: {zip_path} ({exc})",
                          code="bad_archive") from exc
    with zf:
        infos = zf.infolist()
        for info in infos:
            reason = _unsafe_member_reason(info)
            if reason:
                raise UpdateError(f"unsafe archive member {info.filename!r}: {reason}",
                                  code="unsafe_archive")
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        top = None
        if strip_top:
            top = single_top_dir([ownership.normalize(i.filename) for i in infos
                                  if not i.is_dir()])
        names = []
        for info in infos:
            parts = [p for p in info.filename.replace("\\", "/").split("/")
                     if p not in ("", ".")]
            if top and parts and parts[0] == top:
                parts = parts[1:]
            rel = PurePosixPath(*parts)
            target = (root / Path(*rel.parts)).resolve() if rel.parts else root
            if target != root and root not in target.parents:
                raise UpdateError(f"archive member escapes target: {info.filename!r}",
                                  code="unsafe_archive")
            if info.is_dir():
                continue
            if keep is not None and not keep(rel.as_posix()):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            names.append(rel.as_posix())
    return names


def archive_names(zip_path: Path) -> list[str]:
    """POSIX names of the files in an archive (directories omitted)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return [ownership.normalize(info.filename) for info in zf.infolist()
                    if not info.is_dir()]
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"not a readable ZIP archive: {zip_path} ({exc})",
                          code="bad_archive") from exc


def single_top_dir(names: list[str]) -> str | None:
    """The one top-level directory every member sits under, if there is one."""
    tops = {name.split("/", 1)[0] for name in names}
    if len(tops) == 1 and all("/" in name for name in names):
        return tops.pop()
    return None


# --------------------------------------------------------------------------
# journaled file transaction
# --------------------------------------------------------------------------

class Transaction:
    """Apply a planned set of file replacements atomically enough to undo.

    The plan is written to ``.portable/journal.json`` before the first rename.
    Every live file that is replaced or removed is first renamed into
    ``.portable/b/<id>/``; staged files are renamed into place. If any
    step fails, or the process dies, :func:`recover` undoes exactly what the
    journal describes. Nothing outside the plan is touched.
    """

    def __init__(self, root: Path, kind: str):
        self.root = Path(root)
        self.kind = kind
        self.id = os.urandom(3).hex()           # short: see staging_dir()
        while (backup_root(root) / self.id).exists():
            self.id = os.urandom(3).hex()
        self.backup = backup_root(root) / self.id
        self.journal_path = state_dir(root) / "journal.json"
        self.ops: list[dict] = []
        self.created_dirs: list[str] = []

    # plan ---------------------------------------------------------------
    def put(self, rel: str, staged: Path) -> None:
        rel = ownership.normalize(rel)
        live = self.root / rel
        self.ops.append({"rel": rel, "src": str(staged),
                         "action": "replace" if live.exists() else "add"})

    def remove(self, rel: str) -> None:
        rel = ownership.normalize(rel)
        if (self.root / rel).is_file():
            self.ops.append({"rel": rel, "action": "remove"})

    # apply --------------------------------------------------------------
    def _plan_dirs(self) -> None:
        missing = set()
        for op in self.ops:
            if op["action"] == "remove":
                continue
            parent = (self.root / op["rel"]).parent
            while parent != self.root and not parent.exists():
                missing.add(parent.relative_to(self.root).as_posix())
                parent = parent.parent
        self.created_dirs = sorted(missing, key=lambda p: p.count("/"))

    def apply(self) -> None:
        if self.journal_path.exists():
            raise UpdateError("an unfinished update journal exists; run repair first",
                              code="journal_exists")
        self._plan_dirs()
        write_json_atomic(self.journal_path, {
            "id": self.id, "kind": self.kind, "state": "applying",
            "backup": str(self.backup), "ops": self.ops,
            "created_dirs": self.created_dirs, "started": now_iso(),
        })
        try:
            for op in self.ops:
                live = self.root / op["rel"]
                if op["action"] in ("replace", "remove"):
                    keep = self.backup / op["rel"]
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(live, keep)
                if op["action"] in ("replace", "add"):
                    live.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(op["src"], live)
        except OSError as exc:
            failed = op["rel"]
            rollback(self.root)
            raise UpdateError(f"could not replace {failed}: {exc}; all changes were rolled back",
                              code="swap_failed") from exc

    def commit(self) -> None:
        journal = read_json(self.journal_path) or {}
        journal["state"] = "committed"
        write_json_atomic(self.journal_path, journal)
        finish(self.root)


def _rmdir_if_empty(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.rmdir()


def rollback(root: Path) -> list[str]:
    """Undo an ``applying`` journal. Returns the paths that were restored."""
    root = Path(root)
    journal_path = state_dir(root) / "journal.json"
    journal = read_json(journal_path)
    if not journal:
        return []
    backup = Path(journal.get("backup", ""))
    restored = []
    for op in reversed(journal.get("ops", [])):
        rel = op["rel"]
        live = root / rel
        keep = backup / rel
        action = op["action"]
        if action == "add":
            src = Path(op["src"])
            if live.exists() and not src.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                os.replace(live, src)
                restored.append(rel)
        elif keep.exists():
            if action == "replace" and live.exists():
                src = Path(op["src"])
                if not src.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(live, src)
                else:
                    live.unlink()
            live.parent.mkdir(parents=True, exist_ok=True)
            os.replace(keep, live)
            restored.append(rel)
    for rel in sorted(journal.get("created_dirs", []), key=lambda p: -p.count("/")):
        _rmdir_if_empty(root / rel)
    shutil.rmtree(backup, ignore_errors=True)
    journal_path.unlink(missing_ok=True)
    return restored


def finish(root: Path) -> None:
    """Drop the backups of a committed journal."""
    journal_path = state_dir(root) / "journal.json"
    journal = read_json(journal_path)
    if journal:
        shutil.rmtree(journal.get("backup", ""), ignore_errors=True)
    journal_path.unlink(missing_ok=True)


def recover(root: Path) -> str | None:
    """Settle a journal left by an interrupted run. Returns what was done."""
    journal = read_json(state_dir(root) / "journal.json")
    if not journal:
        return None
    if journal.get("state") == "committed":
        finish(root)
        return "finished a committed update"
    restored = rollback(root)
    return f"rolled back an interrupted {journal.get('kind', '')} update ({len(restored)} files)"


def prune_empty_dirs(root: Path, rels) -> None:
    """Remove directories left empty by removed files (never above *root*).

    A directory that only holds a ``__pycache__`` of compiled files is
    treated as empty: those caches are regenerated runtime artefacts.
    """
    root = Path(root)
    candidates = set()
    for rel in rels:
        parent = (root / rel).parent
        while parent != root and root in parent.parents:
            candidates.add(parent)
            parent = parent.parent
    for directory in sorted(candidates, key=lambda p: -len(p.parts)):
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        if len(entries) == 1 and entries[0].name == "__pycache__" and entries[0].is_dir():
            cache = entries[0]
            if all(e.is_file() and e.suffix in (".pyc", ".pyo") for e in cache.iterdir()):
                shutil.rmtree(cache, ignore_errors=True)
        _rmdir_if_empty(directory)


def clean_python_env(extra: dict | None = None) -> dict:
    """Environment for child interpreters: no credentials, no pip redirection."""
    keep = {
        "COMSPEC", "LOCALAPPDATA", "APPDATA", "NUMBER_OF_PROCESSORS", "OS",
        "PATH", "PATHEXT", "PROCESSOR_ARCHITECTURE", "PROGRAMDATA", "PROGRAMFILES",
        "PROGRAMFILES(X86)", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
        "WINDIR", "HOME", "LANG", "TCL_LIBRARY", "TK_LIBRARY", "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL", "PIP_CERT", "PIP_TRUSTED_HOST", "HTTP_PROXY", "HTTPS_PROXY",
        "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
    if extra:
        env.update(extra)
    return env


#: Runs ``portable_hermes`` from an explicit root. The embedded interpreter's
#: ``._pth`` file puts it in isolated mode, so neither ``-m`` from the current
#: directory nor PYTHONPATH can be relied on to find the package.
BOOT = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
        "from portable_hermes.__main__ import main; sys.exit(main(sys.argv[1:]))")
VERIFY_BOOT = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
               "from portable_hermes.verify import main; sys.exit(main(sys.argv[1:]))")


def module_command(python: str, root, *args: str) -> list[str]:
    """Command line running ``python -m portable_hermes <args>`` for *root*."""
    return [python, "-X", "utf8", "-c", BOOT, str(root), *args]


def python_tag() -> str:
    return "%d.%d.%d" % sys.version_info[:3]
