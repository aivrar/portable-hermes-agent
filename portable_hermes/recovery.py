"""Settle an interrupted portable update. Standard library only, self-contained.

Before the first rename of every journaled swap, the running (known-good)
updater copies this file to ``<root>/.portable/recover.py``. The launchers run
that copy whenever ``.portable/journal.json`` exists, before they import any
wrapper code::

    python -I .portable/recover.py <root>

so an update killed halfway through replacing ``portable_hermes/*.py`` itself
is still undone, even though the live wrapper may be a mix of two versions.
The in-process updaters use the same functions through ``portable_hermes.common``.

This file must never import anything from ``portable_hermes``.

Journal (schema 2), every path relative to the install root, POSIX style::

    {"schema": 2, "id": "a1b2c3", "kind": "core", "state": "applying",
     "backup": ".portable/b/a1b2c3", "keep": ".portable/kept/20261113-101500-core",
     "ops": [{"rel": "tools/x.py", "action": "replace",
              "src": ".portable/s/c/tools/x.py", "preserve": true}, ...],
     "created_dirs": ["tools/new_dir"], "started": "..."}

Nothing is moved or deleted until the whole journal has been validated:
backups, staged files and kept copies must resolve inside ``<root>/.portable``,
live paths must be clean relative paths outside user data. A journal that
fails validation is reported and left alone.

Exit codes of the script: 0 nothing to do or settled, 1 could not settle
(retry after closing Hermes), 2 the journal is damaged (nothing was changed),
3 another update is running right now.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

SCHEMA = 2
STATE_DIR = ".portable"
JOURNAL = STATE_DIR + "/journal.json"
BACKUP_PREFIX = STATE_DIR + "/b/"
STAGING_PREFIX = STATE_DIR + "/s/"
KEPT_PREFIX = STATE_DIR + "/kept/"

#: The only paths under ``.portable`` a journal may swap: the channel state
#: files, which change together with the files they describe.
STATE_RELS = frozenset({".portable/core-state.json", ".portable/wrapper-state.json"})

#: Top-level entries that hold user data. A journal naming a live path below
#: one of these is refused as a whole. Mirrors ``ownership.USER_TOP_LEVEL``
#: (a test keeps the two equal); compared case-insensitively.
PROTECTED_TOP_LEVEL = frozenset({
    ".env", ".git", ".hermes", ".lmstudio_config", ".mypy_cache", ".portable",
    ".pytest_cache", ".venv", "_tcltk_temp", "cli-config.yaml", "extensions",
    "hermes_agent.egg-info", "mini-swe-agent", "node_modules", "python_embedded",
    "python_embedded.zip", "run_py.bat", "run_py.sh", "tcltk.msi", "tinker-atropos",
    "venv", "workflows", "workspace",
})
PROTECTED_PREFIX = "python_embedded."     # runtimes set aside by a Python upgrade

ACTIONS = ("replace", "add", "remove")
_ID_RE = re.compile(r"^[0-9a-f]{6,32}$")
_KEEP_NAME_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")


class JournalError(ValueError):
    """The journal is malformed; nothing was changed."""


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _clean_rel(value, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise JournalError(f"{what} is missing or not text")
    if "\\" in value or "\x00" in value or ":" in value:
        raise JournalError(f"{what} {value!r} is not a relative POSIX path")
    if value.startswith("/"):
        raise JournalError(f"{what} {value!r} is an absolute path")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise JournalError(f"{what} {value!r} has empty, '.' or '..' segments")
    return value


def _inside(root: Path, rel: str, prefix: str, what: str) -> Path:
    """``root/rel``, after checking it resolves inside ``root/prefix``."""
    if not rel.lower().startswith(prefix.lower()) or len(rel) <= len(prefix):
        raise JournalError(f"{what} {rel!r} is not inside {prefix}")
    base = (root / prefix).resolve()
    target = (root / rel).resolve()
    if base not in target.parents:
        raise JournalError(f"{what} {rel!r} resolves outside {prefix}")
    return root / rel


def _live_rel(rel: str, what: str) -> str:
    rel = _clean_rel(rel, what)
    if rel.lower() in {r.lower() for r in STATE_RELS}:
        return rel
    top = rel.split("/", 1)[0].lower()
    if top in PROTECTED_TOP_LEVEL or top.startswith(PROTECTED_PREFIX):
        raise JournalError(f"{what} {rel!r} is user data; a journal may never touch it")
    return rel


def validate(root: Path, journal) -> dict:
    """Return the journal if every field is well formed, else raise JournalError."""
    root = Path(root)
    if not isinstance(journal, dict):
        raise JournalError("the journal is not a JSON object")
    if journal.get("schema") != SCHEMA:
        raise JournalError(f"unsupported journal schema {journal.get('schema')!r}")
    jid = journal.get("id")
    if not isinstance(jid, str) or not _ID_RE.match(jid):
        raise JournalError("the journal id is missing or malformed")
    if journal.get("state") not in ("applying", "committed"):
        raise JournalError(f"unknown journal state {journal.get('state')!r}")
    if not isinstance(journal.get("kind"), str):
        raise JournalError("the journal kind is missing")
    backup = journal.get("backup")
    if backup != BACKUP_PREFIX + jid:
        raise JournalError(f"backup {backup!r} is not {BACKUP_PREFIX}{jid}")
    _inside(root, backup, BACKUP_PREFIX, "backup")
    keep = journal.get("keep")
    if keep is not None:
        keep = _clean_rel(keep, "keep")
        if not keep.startswith(KEPT_PREFIX) or not _KEEP_NAME_RE.match(keep[len(KEPT_PREFIX):]):
            raise JournalError(f"keep {keep!r} is not a folder directly inside {KEPT_PREFIX}")
        _inside(root, keep, KEPT_PREFIX, "keep")
    ops = journal.get("ops")
    if not isinstance(ops, list):
        raise JournalError("the journal has no list of operations")
    seen = set()
    for index, op in enumerate(ops):
        what = f"operation {index}"
        if not isinstance(op, dict):
            raise JournalError(f"{what} is not an object")
        action = op.get("action")
        if action not in ACTIONS:
            raise JournalError(f"{what} has unknown action {action!r}")
        rel = _live_rel(op.get("rel"), f"{what} path")
        if rel.lower() in seen:
            raise JournalError(f"{what} repeats {rel!r}")
        seen.add(rel.lower())
        if action in ("replace", "add"):
            _inside(root, _clean_rel(op.get("src"), f"{what} source"), STAGING_PREFIX,
                    f"{what} source")
        elif "src" in op:
            raise JournalError(f"{what} removes a file but names a source")
        if op.get("preserve") and keep is None:
            raise JournalError(f"{what} keeps a copy but the journal names no keep folder")
    dirs = journal.get("created_dirs", [])
    if not isinstance(dirs, list):
        raise JournalError("created_dirs is not a list")
    for rel in dirs:
        rel = _live_rel(rel, "created directory")
        if rel.lower().startswith(STATE_DIR + "/"):
            raise JournalError(f"created directory {rel!r} is inside {STATE_DIR}")
    return journal


def journal_path(root: Path) -> Path:
    return Path(root) / JOURNAL


def load(root: Path) -> dict | None:
    """The validated journal, ``None`` when there is none; JournalError if damaged."""
    path = journal_path(root)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise JournalError(f"the journal is not valid JSON ({exc})") from exc
    except OSError as exc:
        raise JournalError(f"the journal cannot be read ({exc})") from exc
    return validate(root, data)


def write_journal(root: Path, journal: dict) -> None:
    path = journal_path(root)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(journal, fh, indent=1, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# undo / finish
# --------------------------------------------------------------------------

def _same_content(a: Path, b: Path) -> bool:
    try:
        if os.path.samefile(a, b):
            return True
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    return _digest(a) == _digest(b)


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _remove_tree(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)


def rollback(root: Path, journal: dict) -> list[str]:
    """Undo a (validated) journal. Returns the live paths put back.

    Raises OSError if a file could not be put back; the journal and backups are
    then left in place so the next launch can try again.
    """
    root = Path(root)
    backup = root / journal["backup"]
    restored = []
    for op in reversed(journal["ops"]):
        rel = op["rel"]
        live = root / rel
        keep = backup / rel
        action = op["action"]
        if action == "add":
            src = root / op["src"]
            # Only a file we moved in is moved back out (never a user's file).
            if live.is_file() and not src.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                os.replace(live, src)
                restored.append(rel)
        elif action == "replace":
            # The backup is complete before the staged file replaces the live
            # one, so a backup that exists always holds the old content.
            if keep.is_file():
                if not (live.is_file() and _same_content(live, keep)):
                    live.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(keep, live)
                    restored.append(rel)
        else:  # remove
            if keep.is_file() and not live.exists():
                live.parent.mkdir(parents=True, exist_ok=True)
                os.replace(keep, live)
                restored.append(rel)
    for rel in sorted(journal.get("created_dirs", []), key=lambda p: -p.count("/")):
        with contextlib.suppress(OSError):
            (root / rel).rmdir()
    _remove_tree(backup)
    journal_path(root).unlink(missing_ok=True)
    return restored


def finish(root: Path, journal: dict) -> dict:
    """Complete a committed (validated) journal.

    Copies marked ``preserve`` move from the backup into the journal's keep
    folder (never deleted automatically); the rest of the backup is dropped.
    """
    root = Path(root)
    backup = root / journal["backup"]
    kept = 0
    keep_rel = journal.get("keep")
    for op in journal["ops"]:
        if not op.get("preserve"):
            continue
        old = backup / op["rel"]
        if not old.is_file():
            continue
        target = root / keep_rel / op["rel"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        os.replace(old, target)
        kept += 1
    if keep_rel and (root / keep_rel).is_dir():
        kept = sum(1 for p in (root / keep_rel).rglob("*") if p.is_file())
    _remove_tree(backup)
    journal_path(root).unlink(missing_ok=True)
    return {"kept": kept, "keep": keep_rel if kept else None}


def recover(root: Path) -> str | None:
    """Settle the journal under *root*. Returns what was done, ``None`` if nothing.

    The caller holds the install lock. Raises JournalError (nothing changed)
    or OSError (journal kept for another try).
    """
    journal = load(root)
    if journal is None:
        return None
    if journal["state"] == "committed":
        done = finish(root, journal)
        note = "finished an interrupted update (the new files stay)"
        if done["kept"]:
            note += f"; {done['kept']} earlier file(s) kept in {done['keep']}"
        return note
    restored = rollback(root, journal)
    return f"rolled back an interrupted {journal['kind']} update ({len(restored)} files put back)"


# --------------------------------------------------------------------------
# lock (same file and byte as portable_hermes.common.InstallLock)
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _locked(root: Path):
    path = Path(root) / STATE_DIR / "lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - the product is Windows-only
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        fh.close()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: recover.py <install root>")
        return 2
    root = Path(argv[0]).resolve()
    shown = str(root / STATE_DIR / "journal.json")
    if not journal_path(root).exists():
        return 0
    with _locked(root) as ok:
        if not ok:
            print("Portable Hermes: another update or repair is running for this folder. "
                  "Wait for it to finish, then start Hermes again.")
            return 3
        try:
            note = recover(root)
        except JournalError as exc:
            print(f"Portable Hermes: the update journal {shown} is damaged ({exc}). "
                  "Nothing was changed. To continue, rename that file to journal.damaged.json "
                  "and run install.bat, which reinstalls the Hermes core and keeps your "
                  "settings and data.")
            return 2
        except OSError as exc:
            print(f"Portable Hermes: could not undo an interrupted update ({exc}). Close every "
                  "Hermes window (GUI, CLI, gateway) and start Hermes again. If this message "
                  "comes back, run install.bat.")
            return 1
    if note:
        print(f"Portable Hermes: {note}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
