"""In-place upgrade of the portable Python runtime: decisions and messages.

When the newest Hermes core needs a newer Python than this folder's
``python_embedded``, ``core install`` exits with code 4 (``runtime_too_old``).
UPDATE.bat and install.bat then run ``portable_hermes/launch/runtime.cmd``,
which does the swap at batch level, because no Hermes Python may run from
``python_embedded`` while it is renamed:

1. ``runtime plan`` (old Python): explain what happens, choose the folder
   names, write ``.portable/runtime-plan.cmd``;
2. ask (unless unattended), rename ``python_embedded`` to
   ``python_embedded.old-<version>`` (a failed rename changes nothing);
3. ``install.bat --runtime-upgrade`` builds the pinned runtime from nothing
   and installs the core through the normal path (legacy adoption included);
4. ``runtime done`` (new Python): keep the old folder, save its package list,
   report the folder size; or, when the new core did not commit, the
   half-built runtime is renamed to ``python_embedded.failed-<version>``, the
   old one is renamed back and ``runtime undone`` (old Python) says nothing
   changed; or ``runtime partial`` when the core committed but a later setup
   step failed (install.bat must run again).

The plan file is also the marker of an upgrade in progress: runtime.cmd
removes it on every exit path that settles the upgrade. When a launcher or
install.bat finds it (the window was closed, the PC lost power), it runs
``runtime.cmd resume``; ``runtime resume`` (previous Python) settles any
update journal, then decides: ``discard`` (nothing was moved yet),
``forward`` (the new core already committed with the new Python: finish the
setup, never undo), ``rebuild`` (set the incomplete runtime aside and build
again from nothing; undo on failure) or ``undo`` (the undo itself was
interrupted). Either way the folder ends upgraded, or with the previous
Python back.

Set-aside runtime folders are user data for every updater
(``ownership.USER_TOP_LEVEL_PREFIXES``) and are never deleted automatically.
Stdlib only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from portable_hermes import common, core

PLAN_FILE = "runtime-plan.cmd"
RESUME_FILE = "runtime-resume.cmd"
RUNTIME_DIR = "python_embedded"
RESUME_DECISIONS = ("discard", "forward", "rebuild", "undo")
_SAFE_RE = re.compile(r"^[0-9A-Za-z._-]+$")

#: install.bat exit codes runtime.cmd tells apart.
INSTALL_OK = 0
INSTALL_CORE_COMMITTED_THEN_FAILED = 11

#: Rough download sizes for the explanation (python.org sizes for 3.14.9:
#: embeddable ZIP 12.6 MB, tcltk.msi 5.4 MB; packages measured on a full
#: install: about 330 MB installed, typically 150-300 MB to download).
RUNTIME_DOWNLOAD_MB = 18
PACKAGES_DOWNLOAD_MB = "150-300"


def unique_name(root: Path, base: str, taken=()) -> str:
    root = Path(root)
    name, n = base, 1
    while (root / name).exists() or name in taken:
        n += 1
        name = f"{base}-{n}"
    return name


def plan(root: Path, current: str, target: str) -> dict:
    """Folder names and words for moving *root*'s runtime from *current* to *target*."""
    for value in (current, target):
        if not re.fullmatch(r"\d+\.\d+\.\d+", value or ""):
            raise common.UpdateError(f"not a Python version: {value!r}", code="usage")
    old = unique_name(root, f"{RUNTIME_DIR}.old-{current}")
    failed = unique_name(root, f"{RUNTIME_DIR}.failed-{target}")
    # Printed right after the core step's one line saying which Python the
    # newest core needs (core.runtime_too_old_sentence), so not repeated here.
    lines = [
        "  The portable Python can be upgraded here, in place. Everything in this folder",
        "  stays: settings, keys, chats, extensions, workflows and custom tools.",
        "",
        "  What happens:",
        f"    1. The current Python folder is renamed to {old} (kept, not deleted).",
        f"    2. Python {target} and Tcl/Tk are downloaded (about {RUNTIME_DOWNLOAD_MB} MB) and the",
        f"       Python packages Hermes needs are installed (about {PACKAGES_DOWNLOAD_MB} MB to download).",
        "    3. The newest Hermes core is installed and checked.",
        "  If the new core cannot be installed, the upgrade is undone and your current",
        "  Python and Hermes core are put back exactly as they are now. If this window",
        "  is closed or the PC loses power, the next start of Hermes finishes or undoes it.",
        "  Close Hermes first (GUI, CLI and gateway). This usually takes 5 to 15 minutes.",
        "",
    ]
    return {"old_name": old, "failed_name": failed, "current": current, "target": target,
            "text": "\n".join(lines)}


def write_plan_file(root: Path, info: dict) -> Path:
    values = {"PH_OLD_NAME": info["old_name"], "PH_FAILED_NAME": info["failed_name"],
              "PH_OLD_VERSION": info["current"], "PH_TARGET": info["target"]}
    for key, value in values.items():
        if not _SAFE_RE.match(value):
            raise common.UpdateError(f"unsafe value for {key}: {value!r}", code="internal")
    path = common.state_dir(root) / PLAN_FILE
    body = "".join(f'set "{k}={v}"\r\n' for k, v in values.items())
    # The note is the marker of an upgrade in progress: never half-written.
    common.write_bytes_atomic(
        path, ("@rem written by portable_hermes runtime plan\r\n" + body).encode("ascii"))
    return path


folder_size_mb = common.folder_size_mb


def save_package_list(root: Path, old_name: str) -> Path | None:
    """``pip freeze`` of the set-aside runtime into ``.portable/``."""
    python = Path(root) / old_name / "python.exe"
    if not python.is_file():
        return None
    try:
        proc = subprocess.run([str(python), "-I", "-m", "pip", "freeze",
                               "--disable-pip-version-check"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300,
                              env=common.clean_python_env({"PORTABLE_HERMES_NO_HOOK": "1"}))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = common.state_dir(root) / f"{old_name}-packages.txt"
    out.write_text(f"# pip freeze of {old_name}, saved {common.now_iso()}\n"
                   + proc.stdout, encoding="utf-8")
    return out


def done_text(root: Path, old_name: str, packages: Path | None) -> str:
    size = folder_size_mb(Path(root) / old_name)
    lines = ["", f"  Portable Python upgraded to {common.python_tag()}, and the Hermes core is "
             "installed.",
             f"  The previous Python is kept in the folder {old_name} ({size} MB)."]
    if packages:
        lines += [f"  The list of packages it had is saved in .portable\\{packages.name}",
                  "  (install any you added yourself again with",
                  "   python_embedded\\python.exe -m pip install <name>)."]
    lines += [f"  You may delete the folder {old_name} once Hermes works for you.", ""]
    return "\n".join(lines)


def undone_text(root: Path, failed_name: str) -> str:
    lines = ["", "  The Python upgrade did not complete, so it was undone. Nothing changed: your",
             f"  portable Python {common.python_tag()} and your Hermes core are exactly as before."]
    failed = Path(root) / failed_name
    if failed.is_dir():
        lines.append(f"  The incomplete new runtime was moved to {failed_name} "
                     f"({folder_size_mb(failed)} MB); you may delete that folder.")
    lines += ["  To try again later, run UPDATE.bat --core.", ""]
    return "\n".join(lines)


def partial_text(old_name: str) -> str:
    return "\n".join([
        "", f"  The new portable Python {common.python_tag()} and the Hermes core are installed, "
        "but a later",
        "  setup step failed (see the messages above). Run install.bat again to finish;",
        "  Hermes also runs it by itself at the next start.",
        f"  The previous Python is kept in {old_name}; it cannot run the new core.", ""])


def resume_decision(root: Path, old_name: str, failed_base: str, target: str,
                    undoing: bool = False) -> dict:
    """What to do with an interrupted upgrade (see the module docstring)."""
    root = Path(root)
    for what, value in (("old", old_name), ("failed", failed_base), ("target", target)):
        if not value or not _SAFE_RE.match(value) or (
                what != "target" and not value.startswith(RUNTIME_DIR + ".")):
            raise common.UpdateError(f"unsafe or missing {what} name in the upgrade plan: "
                                     f"{value!r}", code="usage")
    notes = []
    if (common.state_dir(root) / "journal.json").exists():
        # Decide on the files as they are on disk, not on a half-applied swap.
        with common.InstallLock(root):
            done = common.recover(root)
        if done:
            notes.append(f"  ({done})")
    runtime = root / RUNTIME_DIR
    old_present = (root / old_name / "python.exe").is_file()
    if undoing:
        decision = "undo"
    elif not old_present:
        decision = "discard"
    else:
        state = common.read_json(common.state_dir(root) / core.STATE_FILE) or {}
        committed = state.get("python") == target and (runtime / "python.exe").is_file()
        decision = "forward" if committed else "rebuild"
    # Two distinct free names: one for an incomplete runtime set aside before
    # the rebuild, one for the rebuilt runtime if that fails and is undone.
    if decision == "rebuild" and runtime.exists():
        aside = unique_name(root, failed_base)
        failed = unique_name(root, failed_base, taken={aside})
    else:
        failed = unique_name(root, failed_base)
        aside = unique_name(root, failed_base, taken={failed})
    if decision == "discard":
        text = ("  It stopped before anything was moved. Nothing was changed; Hermes "
                "starts with\n  your current portable Python.")
    elif decision == "forward":
        text = (f"  The new Hermes core was already installed with Python {target}. "
                "Finishing the\n  remaining setup steps; the previous Python stays in "
                f"{old_name}.")
    elif decision == "rebuild":
        text = f"  Python {target} is installed again from the beginning"
        if runtime.exists():
            text += f";\n  the incomplete new runtime is moved to {aside} first"
        text += (".\n  If that fails, your previous Python and Hermes core are put back "
                 "as they were.")
    else:
        text = "  The upgrade was being undone. Finishing that now."
    return {"decision": decision, "failed_name": failed, "aside_name": aside,
            "text": "\n".join(notes + [text])}


def write_resume_file(root: Path, info: dict) -> Path:
    names = (info.get("failed_name") or "", info.get("aside_name") or "")
    if info.get("decision") not in RESUME_DECISIONS or not all(
            _SAFE_RE.match(n) and n.startswith(RUNTIME_DIR + ".") for n in names):
        raise common.UpdateError(f"unsafe resume decision: {info!r}", code="internal")
    path = common.state_dir(root) / RESUME_FILE
    body = (f'set "PH_RESUME={info["decision"]}"\r\n'
            f'set "PH_FAILED_NAME={info["failed_name"]}"\r\n'
            f'set "PH_ASIDE_NAME={info["aside_name"]}"\r\n')
    common.write_bytes_atomic(
        path, ("@rem written by portable_hermes runtime resume\r\n" + body).encode("ascii"))
    return path


def main(args) -> int:
    """``python -m portable_hermes runtime <action>`` (called by runtime.cmd)."""
    root = Path(args.root)
    if args.action == "resume":
        try:
            info = resume_decision(root, args.old, args.failed, args.target,
                                   getattr(args, "undoing", False))
            write_resume_file(root, info)
        except common.UpdateError as exc:
            print(f"  {exc.reason}")
            return 1
        print(info["text"])
        return 0
    if args.action == "plan":
        target = core.target_python()
        if not target:
            print("  This Portable Hermes release has no Python version pin "
                  "(portable_hermes/manifests/python-runtime.txt).")
            return 1
        info = plan(root, common.python_tag(), target)
        write_plan_file(root, info)
        print(info["text"])
        return 0
    if args.action == "done":
        print(done_text(root, args.old, save_package_list(root, args.old)))
        return 0
    if args.action == "undone":
        print(undone_text(root, args.failed))
        return 0
    if args.action == "partial":
        print(partial_text(args.old))
        return 0
    print(f"unknown runtime action {args.action!r}", file=sys.stderr)
    return 2
