"""Shared machinery for the portable updaters (stdlib only).

* HTTPS downloads and GitHub API reads (no credentials are ever sent),
  tried again after a transient network failure
* safe archive extraction (zip-slip, absolute paths, symlinks, Windows device
  names, names Windows cannot store and case-only duplicates rejected)
* a journaled file transaction: old content is kept by hard link (or copy)
  under ``<root>/.portable`` before a staged file replaces it, so a file is
  always either old or new, and an interrupted swap can always be undone -
  even by the standalone ``.portable/recover.py`` (see :mod:`recovery`)
* an inter-process lock and atomic JSON state files

Nothing here imports Hermes core code.
"""

from __future__ import annotations

import contextlib
import email.utils
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from portable_hermes import ownership, recovery

STATE_DIR = ".portable"
USER_AGENT = "portable-hermes-updater"
_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")

#: The recovery code of the running (known-good) wrapper, read once at import
#: so a transaction can drop a copy into ``.portable/recover.py`` even after
#: its own swap has started replacing ``portable_hermes/*.py``.
_RECOVERY_SOURCE = Path(recovery.__file__).read_bytes()
RECOVERY_SCRIPT = "recover.py"


class UpdateError(RuntimeError):
    """A failure with a precise, user-readable reason."""

    def __init__(self, reason: str, *, code: str = "error", details: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.code = code
        self.details = dict(details or {})


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


#: User-visible copies of files an update or repair replaced although they
#: were not what was recorded (user edits). Never deleted automatically.
KEPT_DIR = "kept"


def new_kept_dir(root: Path, kind: str) -> str:
    """A fresh ``.portable/kept/<date>-<kind>`` folder name (relative, POSIX)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{STATE_DIR}/{KEPT_DIR}/{stamp}-{kind}"
    rel, n = base, 1
    while (Path(root) / rel).exists():
        n += 1
        rel = f"{base}-{n}"
    return rel


#: Longest ``.portable/...`` prefix a file gets while an update runs: kept
#: copies of edited files (``.portable/kept/YYYYMMDD-HHMMSS-wrapper-9/``).
STATE_PATH_OVERHEAD = len(f"{STATE_DIR}/{KEPT_DIR}/20261113-101500-wrapper-9/")


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


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write *data* so that *path* is never seen half-written (a power cut
    leaves the previous file, or none): a temporary file in the same folder,
    flushed to disk, then renamed over *path*."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def log(message: str, *, quiet: bool = False) -> None:
    """Print console-safe (ASCII) progress text."""
    if quiet:
        return
    text = str(message).encode("ascii", "replace").decode("ascii")
    print(text, flush=True)


def flush_output() -> None:
    """Flush our own output before a child process starts.

    When the output is piped or logged, Python buffers it while the child
    writes straight to the same handle, so without this a child's lines can
    appear before lines printed earlier."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except (OSError, ValueError):
            pass


def folder_size_mb(path: Path) -> int:
    """Size of the files under *path* in MB (unreadable entries are skipped)."""
    total = 0
    for item in Path(path).rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return round(total / (1 << 20))


def kept_sentence(result: dict) -> str | None:
    """One sentence about the copies an update kept (None when it kept none).

    Adopting a legacy install keeps the previous files, which have no record
    of what was installed: they are not the user's edits, so they get their
    own sentence. ``adopted_what`` names them (the core's result leaves it
    out; the wrapper's says "the previous Portable Hermes version")."""
    count, where = result.get("kept_edits_count"), result.get("kept_edits")
    if not count:
        return None
    if result.get("adopted"):
        what = result.get("adopted_what") or "the previous Hermes core"
        size = result.get("kept_edits_mb")
        size_text = f" ({size} MB)" if isinstance(size, int) else ""
        return (f"{count} file(s) of {what} were kept in {where}{size_text}, "
                "as they were before this update (with any change you made to them). "
                "Once Hermes works, you may delete that folder.")
    return (f"{count} file(s) that differed from what was installed (your edits or files we "
            f"did not install) were kept in {where}")


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


#: A dropped connection must not fail an install or an update. Transient
#: failures (connection errors, timeouts, a cut-off body, HTTP 5xx and 429, a
#: rate-limited 403) are tried again after these pauses, in seconds; anything
#: else (404, an ordinary 403, a certificate error, ...) fails at once.
#: Downloads: up to 4 attempts, all within the download's overall deadline.
DOWNLOAD_PAUSES = (2, 5, 10)
#: Small GitHub API reads: up to 3 attempts. A whole call ends within about
#: ``timeout + sum(API_PAUSES)`` seconds, so an update check made while the
#: PC is offline returns at most 3 seconds later than with a single attempt.
API_PAUSES = (1, 2)
#: Longest "Retry-After" a download waits for (an API read waits only as long
#: as its own deadline allows).
RETRY_AFTER_CAP = 60
_sleep = time.sleep          # replaced by tests


class _Truncated(OSError):
    """The connection closed before the announced number of bytes arrived."""


def _retry_after(headers) -> float | None:
    """Seconds a ``Retry-After`` header asks for (delta or HTTP date)."""
    value = (headers.get("Retry-After") if headers is not None else None) or ""
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _retry_wait(exc: BaseException) -> float | None:
    """Least wait before another attempt, or None when retrying cannot help."""
    if isinstance(exc, urllib.error.HTTPError):
        headers = exc.headers
        asked = _retry_after(headers)
        if exc.code >= 500 or exc.code == 429:
            return asked or 0.0
        if exc.code == 403 and headers is not None:
            if asked is not None:                       # GitHub secondary rate limit
                return asked
            if headers.get("X-RateLimit-Remaining") == "0":   # primary rate limit
                try:
                    return max(0.0, float(headers.get("X-RateLimit-Reset", "")) - time.time())
                except ValueError:
                    return None
        return None
    if isinstance(exc, urllib.error.URLError):
        # No connection was made: name lookup, refused, unreachable, TLS. A
        # reason that is text is our own refusal (a non-HTTPS redirect).
        reason = exc.reason
        if isinstance(reason, OSError) and not isinstance(reason, ssl.SSLCertVerificationError):
            return 0.0
        return None
    if isinstance(exc, ssl.SSLCertVerificationError):
        return None
    # The connection broke while the answer was read. Any other OSError (a
    # full disk while writing the file, for example) is final.
    if isinstance(exc, (ConnectionError, TimeoutError, socket.gaierror, ssl.SSLError,
                        http.client.HTTPException, _Truncated)):
        return 0.0
    return None


def _describe(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        exc = exc.reason if isinstance(exc.reason, BaseException) else exc
    return str(exc) or type(exc).__name__


def _attempts_note(attempts: int, note: str = "") -> str:
    text = f"{attempts} attempt" + ("s" if attempts != 1 else "")
    return f" ({text}; {note})" if note else f" ({text})"


def _final_error(exc: BaseException, what: str, url: str, attempts: int,
                 note: str = "") -> UpdateError:
    tried = _attempts_note(attempts, note)
    if isinstance(exc, urllib.error.HTTPError):
        where = "from" if what == "fetching" else what
        return UpdateError(f"HTTP {exc.code} {where} {url}{tried}", code=f"http_{exc.code}",
                           details={"attempts": attempts})
    return UpdateError(f"network error {what} {url}: {_describe(exc)}{tried}", code="network",
                       details={"attempts": attempts})


#: What :func:`_with_retries` catches from one attempt (everything else, such
#: as an ``UpdateError`` for the overall deadline, ends the call at once).
_NETWORK_ERRORS = (urllib.error.URLError, OSError, http.client.HTTPException)


def _with_retries(attempt, *, url: str, what: str, pauses, deadline: float,
                  wait_cap: float, on_retry=None):
    """Run ``attempt()`` until it succeeds or a failure is final.

    A failure is retried when it is transient, a pause is left in *pauses*,
    and the wait (the scheduled pause, or longer if the server asked for it
    with Retry-After, at most *wait_cap*) leaves at least a second before
    *deadline* for the next attempt."""
    attempts = len(pauses) + 1
    for number in range(1, attempts + 1):
        try:
            return attempt()
        except _NETWORK_ERRORS as exc:
            wanted = _retry_wait(exc)
            if wanted is None:
                raise _final_error(exc, what, url, number,
                                   "not retried" if number == 1 else "") from exc
            if number == attempts:
                raise _final_error(exc, what, url, number) from exc
            pause = float(pauses[number - 1])
            wait = max(pause, wanted)
            if wait > wait_cap or time.monotonic() + wait + 1 >= deadline:
                note = (f"the server asked to wait {wanted:.0f} s" if wanted > pause
                        else "no time left to try again")
                raise _final_error(exc, what, url, number, note) from exc
            if on_retry is not None:
                on_retry(exc, number + 1, attempts)
            _sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


def _attempt_timeout(timeout: float, deadline: float) -> float:
    """Socket timeout for one attempt: never past the call's deadline."""
    return max(1.0, min(timeout, deadline - time.monotonic()))


def http_get(url: str, *, accept: str | None = None, timeout: float = 30,
             pauses=API_PAUSES) -> bytes:
    """GET a small resource (HTTPS only), retrying transient failures.

    The whole call, retries included, ends within about ``timeout +
    sum(pauses)`` seconds."""
    request = _request(url, accept)
    deadline = time.monotonic() + timeout + sum(pauses)

    def attempt() -> bytes:
        with _opener().open(request, timeout=_attempt_timeout(timeout, deadline)) as resp:
            return resp.read()

    return _with_retries(attempt, url=url, what="fetching", pauses=pauses,
                         deadline=deadline, wait_cap=RETRY_AFTER_CAP)


def download(url: str, dest: Path, *, timeout: float = 600, quiet: bool = False,
             pauses=DOWNLOAD_PAUSES) -> Path:
    """Stream *url* to *dest* (HTTPS only). Returns *dest*.

    Each attempt writes ``<dest>.part``, which becomes *dest* only when the
    whole body arrived (a body cut short of its announced length counts as a
    failure). A transient failure discards the partial file and tries again
    after *pauses*; every attempt and pause stays within *timeout* seconds.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    request = _request(url)
    deadline = time.monotonic() + timeout

    def attempt() -> None:
        try:
            _download_once(request, tmp, url=url, timeout=timeout, deadline=deadline,
                           quiet=quiet)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def say_retry(exc: BaseException, number: int, attempts: int) -> None:
        log(f"  download failed ({_describe(exc)}); trying again ({number} of {attempts}) ...",
            quiet=quiet)

    _with_retries(attempt, url=url, what="downloading", pauses=pauses, deadline=deadline,
                  wait_cap=RETRY_AFTER_CAP, on_retry=say_retry)
    # Not a network failure and not retried: the file arrived, but it cannot
    # take its final name (on Windows, for example, when that file is open).
    # An existing *dest* stays as it was.
    try:
        os.replace(tmp, dest)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise UpdateError(f"the download finished but could not be saved as {dest}: {exc}",
                          code="save_failed", details={"path": str(dest)}) from exc
    return dest


def _download_once(request, tmp: Path, *, url: str, timeout: float, deadline: float,
                   quiet: bool) -> None:
    with _opener().open(request, timeout=_attempt_timeout(min(timeout, 60), deadline)) \
            as resp, open(tmp, "wb") as out:
        expected = resp.headers.get("Content-Length")
        expected = int(expected) if expected and expected.strip().isdigit() else None
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
        if expected is not None and total < expected:
            raise _Truncated(f"the connection closed after {total} of {expected} bytes")


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


_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)})
_BAD_CHARS = set('<>"|?*') | {chr(c) for c in range(1, 32)}


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
    for part in parts:
        if part.endswith((".", " ")):
            return "a name ends with a dot or space (Windows drops it)"
        if any(ch in _BAD_CHARS for ch in part):
            return "a character Windows does not allow in file names"
        if part.split(".", 1)[0].strip().lower() in _RESERVED_NAMES:
            return "a Windows reserved device name (CON, NUL, AUX, PRN, COM1-9, LPT1-9)"
    mode = (info.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        return "symbolic link"
    return None


def _case_conflict(names: list[str]) -> str | None:
    """A member whose path differs from another only by letter case, if any."""
    files, seen = set(), {}
    for name in names:
        key = name.lower()
        if key in seen:
            return name
        seen[key] = name
    for name in names:
        if not name.endswith("/"):
            files.add(name.lower())
    for key in seen:
        parts = key.rstrip("/").split("/")
        if key.endswith("/") and key.rstrip("/") in files:
            return seen[key]
        for i in range(1, len(parts)):
            if "/".join(parts[:i]) in files:
                return seen[key]
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
        clash = _case_conflict(["/".join(p for p in i.filename.replace("\\", "/").split("/")
                                         if p not in ("", ".")) + ("/" if i.is_dir() else "")
                                for i in infos])
        if clash:
            raise UpdateError(f"unsafe archive member {clash!r}: another member has the same "
                              "path apart from letter case (Windows would overwrite one "
                              "with the other)", code="unsafe_archive")
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

def _keep_old(live: Path, keep: Path) -> None:
    """Make *keep* hold *live*'s current content without touching *live*.

    A hard link costs nothing; where links are not supported (exFAT, FAT32,
    some network shares) a copy is written under a temporary name first, so
    an existing *keep* is always complete.
    """
    keep.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(live, keep)
        return
    except OSError:
        pass
    part = keep.with_name(keep.name + ".part")
    shutil.copy2(live, part)
    os.replace(part, keep)


class Transaction:
    """Apply a planned set of file changes so that it can always be undone.

    Before the first change, the running wrapper's recovery code is copied to
    ``.portable/recover.py`` and the plan is written to
    ``.portable/journal.json`` (paths relative to the root, see
    :mod:`portable_hermes.recovery`). A replaced file's old content is kept
    under ``.portable/b/<id>/`` by hard link (or copy) and the staged file is
    then renamed over it, so the live file is never missing. If any step fails,
    or the process dies, the journal is undone exactly. Files marked
    *preserve* (user edits) are moved into a dated ``.portable/kept/`` folder
    at commit instead of being dropped with the backup.
    """

    def __init__(self, root: Path, kind: str):
        self.root = Path(root)
        self.kind = kind
        self.id = os.urandom(3).hex()           # short: see staging_dir()
        while (backup_root(root) / self.id).exists():
            self.id = os.urandom(3).hex()
        self.backup_rel = f"{STATE_DIR}/b/{self.id}"
        self.backup = self.root / self.backup_rel
        self.journal_path = recovery.journal_path(self.root)
        self.ops: list[dict] = []
        self.created_dirs: list[str] = []
        self.keep_rel: str | None = None
        self.applied = False
        self.committed = False
        self._claimed: set[str] = set()

    # plan ---------------------------------------------------------------
    def _claim(self, rel: str) -> str:
        rel = ownership.normalize(rel)
        if rel.lower() in self._claimed:
            raise UpdateError(f"{rel} is planned twice (paths differing only by case?)",
                              code="swap_failed")
        self._claimed.add(rel.lower())
        return rel

    def _staged_rel(self, staged: Path) -> str:
        staged = Path(staged).resolve()
        base = staging_dir(self.root).resolve()
        if base not in staged.parents:
            raise UpdateError(f"staged file {staged} is not under {base}", code="internal")
        return staged.relative_to(self.root.resolve()).as_posix()

    def _mark_preserved(self, op: dict) -> None:
        if self.keep_rel is None:
            self.keep_rel = new_kept_dir(self.root, self.kind)
        op["preserve"] = True

    def put(self, rel: str, staged: Path, *, preserve: bool = False) -> None:
        rel = self._claim(rel)
        live = self.root / rel
        op = {"rel": rel, "src": self._staged_rel(staged),
              "action": "replace" if live.exists() else "add"}
        if preserve and op["action"] == "replace":
            self._mark_preserved(op)
        self.ops.append(op)

    def remove(self, rel: str, *, preserve: bool = False) -> None:
        rel = ownership.normalize(rel)
        if (self.root / rel).is_file():
            rel = self._claim(rel)
            op = {"rel": rel, "action": "remove"}
            if preserve:
                self._mark_preserved(op)
            self.ops.append(op)

    @property
    def preserved(self) -> int:
        return sum(1 for op in self.ops if op.get("preserve"))

    @property
    def file_ops(self) -> list[dict]:
        """Operations on install files (not the channel state files)."""
        return [op for op in self.ops if op["rel"] not in recovery.STATE_RELS]

    def journal(self, state: str) -> dict:
        data = {
            "schema": recovery.SCHEMA, "id": self.id, "kind": self.kind, "state": state,
            "backup": self.backup_rel, "ops": self.ops,
            "created_dirs": self.created_dirs, "started": now_iso(),
        }
        if self.keep_rel:
            data["keep"] = self.keep_rel
        return data

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
            raise UpdateError("an unfinished update journal exists; start Hermes once (or "
                              "run repair) to settle it first", code="journal_exists")
        self._plan_dirs()
        try:
            journal = recovery.validate(self.root, self.journal("applying"))
        except recovery.JournalError as exc:
            raise UpdateError(f"refusing an unsafe file plan: {exc}", code="internal") from exc
        # The standalone recovery script first, so a kill at any later point
        # can be settled without importing the (possibly half-replaced) wrapper.
        script = state_dir(self.root) / RECOVERY_SCRIPT
        tmp = script.with_name(script.name + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(_RECOVERY_SOURCE)
        os.replace(tmp, script)
        recovery.write_journal(self.root, journal)
        self.applied = True
        op = None
        try:
            for op in self.ops:
                live = self.root / op["rel"]
                if op["action"] == "replace":
                    _keep_old(live, self.backup / op["rel"])
                    os.replace(self.root / op["src"], live)
                elif op["action"] == "remove":
                    keep = self.backup / op["rel"]
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(live, keep)
                else:
                    live.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(self.root / op["src"], live)
        except OSError as exc:
            failed = op["rel"] if op else "?"
            try:
                recovery.rollback(self.root, journal)
            except OSError as undo:
                raise UpdateError(
                    f"could not replace {failed}: {exc}; undoing the partial change also "
                    f"failed ({undo}). Close every Hermes window and start Hermes again: "
                    "the launcher finishes the undo.", code="rollback_failed") from exc
            raise UpdateError(f"could not replace {failed}: {exc}; all changes were rolled back",
                              code="swap_failed") from exc

    def rollback(self) -> list[str]:
        """Undo this transaction after a successful :meth:`apply`."""
        journal = recovery.load(self.root)
        if not journal or journal["id"] != self.id:
            return []
        return recovery.rollback(self.root, journal)

    def commit(self) -> dict:
        journal = self.journal("committed")
        recovery.write_journal(self.root, journal)
        self.committed = True
        return recovery.finish(self.root, journal)


def rollback(root: Path) -> list[str]:
    """Undo an ``applying`` journal. Returns the paths that were put back."""
    try:
        journal = recovery.load(root)
    except recovery.JournalError as exc:
        raise UpdateError(f"the update journal is damaged ({exc}); nothing was changed",
                          code="journal_damaged") from exc
    if not journal:
        return []
    return recovery.rollback(root, journal)


def recover(root: Path) -> str | None:
    """Settle a journal left by an interrupted run (caller holds the lock).

    Returns what was done. A damaged journal raises ``UpdateError`` and
    nothing is changed.
    """
    try:
        return recovery.recover(root)
    except recovery.JournalError as exc:
        raise UpdateError(
            f"the update journal {state_dir(root) / 'journal.json'} is damaged ({exc}); "
            "nothing was changed. Rename it to journal.damaged.json and run install.bat.",
            code="journal_damaged") from exc


def _rmdir_if_empty(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.rmdir()


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
