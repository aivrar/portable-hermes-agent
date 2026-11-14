"""Command line for the portable wrapper.

    python -m portable_hermes core install|update [--ref R | --zip FILE] [--commit SHA]
    python -m portable_hermes core check
    python -m portable_hermes wrapper update [--zip FILE | --tag vX.Y.Z]
    python -m portable_hermes wrapper check
    python -m portable_hermes update [--core | --no-core] [--yes]   (UPDATE.bat)
    python -m portable_hermes repair [--quiet]                      (launchers)
    python -m portable_hermes verify [--no-gui]
    python -m portable_hermes runtime plan|done|undone|partial|resume   (runtime.cmd)

``--json`` prints one machine-readable result line. Set
``HERMES_PORTABLE_NONINTERACTIVE=1`` (or pass ``--yes``) to never prompt.
Exit codes: 0 success, 1 failure, 2 usage, 3 failed but the existing core
was kept unchanged, 4 the newest core needs a newer portable Python (UPDATE.bat
and install.bat then upgrade it in place, see ``launch/runtime.cmd``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

from portable_hermes import ROOT


def _noninteractive(args) -> bool:
    # Same rule as the batch files: set and not "0" means unattended.
    value = os.environ.get("HERMES_PORTABLE_NONINTERACTIVE", "").strip().lower()
    return bool(getattr(args, "yes", False)) or value not in ("", "0", "false", "no")


def _emit(result: dict, as_json: bool) -> None:
    if as_json:
        print("PORTABLE_RESULT " + json.dumps(result, default=str))
        return
    if result.get("ok"):
        print(result.get("message") or "done")
    elif result.get("code") == "runtime_too_old":
        # The only line about it here: runtime.cmd's explanation follows.
        from portable_hermes.core import runtime_too_old_sentence
        print("  " + runtime_too_old_sentence(result.get("current_python"),
                                              result.get("target_python"),
                                              result.get("requires_python")))
    else:
        print("FAILED: " + str(result.get("reason")))
    for key in ("fallback", "recovered", "kept_modified_count", "skipped_count"):
        if result.get(key):
            print(f"  {key}: {result[key]}")
    from portable_hermes.common import kept_sentence
    kept = kept_sentence(result)
    if kept:
        print(textwrap.fill(kept, width=88, initial_indent="  ", subsequent_indent="  ",
                            break_long_words=False, break_on_hyphens=False))
    for warning in result.get("warnings") or []:
        print(f"  WARNING: {warning}")
    if result.get("dependencies_restored") is False:
        print("  WARNING: Python packages could not all be put back; run UPDATE.bat again "
              "to finish.")
    deps = result.get("dependencies")
    if isinstance(deps, dict):
        line = deps.get("strategy", "")
        if deps.get("skipped"):
            line += f" (not installed: {deps.get('reason')})"
        if deps.get("missing_extras"):
            line += f"; extras not in this core: {', '.join(deps['missing_extras'])}"
        if deps.get("wrapper_warning"):
            line += f"; {deps['wrapper_warning']}"
        if deps.get("lock_note"):
            line += f"; {deps['lock_note']}"
        print(f"  dependencies: {line}")


def _print_check(title: str, info: dict) -> None:
    print(title)
    for key in ("install_type", "installed_version", "latest_version", "repository",
                "commit", "latest_commit", "behind_by", "update_available", "installed_at",
                "missing_files", "network_error", "compare_error", "message"):
        if key in info and info[key] is not None:
            print(f"  {key}: {info[key]}")


def cmd_core(args) -> int:
    from portable_hermes.core import CoreLifecycle
    life = CoreLifecycle(Path(args.root), quiet=args.json)
    if args.action == "check":
        info = life.check(ref=args.ref or "main")
        if args.json:
            print("PORTABLE_RESULT " + json.dumps(info, default=str))
        else:
            _print_check("Hermes core (NousResearch/hermes-agent)", info)
        return 0
    # install.bat passes overrides through the environment (no batch quoting).
    ref = args.ref or os.environ.get("HERMES_PORTABLE_CORE_REF") or None
    zip_path = args.zip or os.environ.get("HERMES_PORTABLE_CORE_ZIP") or None
    commit = args.commit or os.environ.get("HERMES_PORTABLE_CORE_COMMIT") or None
    result = life.install(ref=ref, zip_path=zip_path, commit=commit,
                          skip_deps=args.skip_deps, force=args.force,
                          allow_fallback=not args.no_fallback)
    _emit(result, args.json)
    if result.get("ok") and result.get("changed") and not args.json:
        print("Restart Hermes (close and reopen the GUI or CLI) to load the new core.")
    return int(result.get("exit", 0 if result.get("ok") else 1))


def cmd_wrapper(args) -> int:
    from portable_hermes.wrapper import WrapperUpdater
    updater = WrapperUpdater(Path(args.root), quiet=args.json)
    if args.action == "check":
        info = updater.check()
        if args.json:
            print("PORTABLE_RESULT " + json.dumps(info, default=str))
        else:
            _print_check("Portable wrapper (aivrar/portable-hermes-agent)", info)
        return 0
    result = updater.update(zip_path=args.zip, tag=args.tag, force=args.force)
    _emit(result, args.json)
    return 0 if result.get("ok") else 1


def cmd_update(args) -> int:
    """UPDATE.bat: wrapper channel first, then an optional core refresh."""
    from portable_hermes.core import CoreLifecycle
    from portable_hermes.wrapper import WrapperUpdater
    root = Path(args.root)
    status = 0
    if not args.core_only:
        print("[1/2] Portable wrapper - launchers, GUI, portable tools "
              "(aivrar/portable-hermes-agent releases)")
        wrapper = WrapperUpdater(root).update(zip_path=args.zip, force=args.force)
        _emit(wrapper, False)
        status = 0 if wrapper.get("ok") else 1
        if wrapper.get("changed"):
            # This process still runs the previous wrapper's code; let the
            # wrapper that was just installed handle the core step.
            import subprocess
            from portable_hermes import common
            extra = {True: ["--core"], False: ["--no-core"], None: []}[args.core]
            extra += ["--yes"] if args.yes else []
            cmd = common.module_command(sys.executable, root, "update", "--core-only", *extra)
            common.flush_output()       # our lines first, then the child's
            return status or subprocess.call(cmd)
    print()
    print("[2/2] Hermes core - the agent itself (NousResearch/hermes-agent)")
    want_core = args.core
    life = CoreLifecycle(root)
    if want_core is not False and life.pending_dependencies():
        print("  An earlier update was interrupted while changing Python packages; "
              "finishing it now.")
        want_core = True
    if want_core is None:
        info = life.check()
        behind = info.get("behind_by")
        if info.get("install_type") == "git":
            print("  git checkout: update the core with git.")
            return status
        if info.get("update_available") is False:
            print(f"  core is current ({(info.get('commit') or '')[:12]}).")
            return status
        summary = (f"{behind} upstream commits behind" if isinstance(behind, int)
                   else "an upstream update may be available")
        if info.get("network_error"):
            summary = f"could not reach GitHub ({info['network_error']})"
        print(f"  {summary}.")
        if _noninteractive(args):
            print("  Skipped (non-interactive). Run UPDATE.bat --core to update the core.")
            return status
        try:
            answer = input("  Update the Hermes core now? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        want_core = answer in ("y", "yes")
        if not want_core:
            print("  Core left unchanged.")
            return status
    if not want_core:
        print("  Skipped.")
        return status
    result = life.install()
    _emit(result, False)
    if result.get("ok") and result.get("changed"):
        print("Restart Hermes (close and reopen the GUI or CLI) to load the new core.")
    core_status = int(result.get("exit", 0 if result.get("ok") else 1))
    if core_status == 4:
        # UPDATE.bat (launch/update.cmd) continues with the in-place runtime upgrade.
        return 4
    return status or core_status


def cmd_repair(args) -> int:
    from portable_hermes.wrapper import repair
    try:
        report = repair(Path(args.root), quiet=False)
    except Exception as exc:  # noqa: BLE001 - a launcher must never fail here
        if not args.quiet:
            print(f"portable repair skipped: {exc}")
        return 0
    if not args.quiet:
        for note in report.get("notes", []):
            print(f"  {note}")
    if report.get("bridge_problem"):
        # Always shown: losing the portable tools silently is the worst case.
        print("  Portable tools problem in the last Hermes session: "
              + report["bridge_problem"])
        print("  If the portable tools are missing, run UPDATE.bat (core update) or install.bat.")
    return 0


def cmd_runtime(args) -> int:
    from portable_hermes import runtime
    return runtime.main(args)


def cmd_verify(args) -> int:
    from portable_hermes.core import CoreLifecycle
    root = Path(args.root)
    result = CoreLifecycle(root, quiet=True)._default_verify(root, gui=not args.no_gui)
    for check in result.get("checks", []):
        mark = ("warn" if check.get("warning") else "ok  ") if check["ok"] else "FAIL"
        print(f"[{mark}] {check['name']}: {check['detail']}")
    if not result.get("checks"):
        print(result.get("reason"))
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m portable_hermes",
                                     description="Portable Hermes wrapper tools")
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    core = sub.add_parser("core", help="install, update or check the upstream core")
    core.add_argument("action", choices=["install", "update", "check"])
    core.add_argument("--ref", help="branch, tag or commit of NousResearch/hermes-agent")
    core.add_argument("--zip", help="install from a local upstream source ZIP")
    core.add_argument("--commit", help="commit SHA to record for --zip")
    core.add_argument("--skip-deps", action="store_true", help="do not install dependencies")
    core.add_argument("--force", action="store_true", help="reinstall even if current")
    core.add_argument("--no-fallback", action="store_true",
                      help="never fall back to the last-known-good commit")
    core.add_argument("--json", action="store_true")
    core.set_defaults(func=cmd_core)

    wrapper = sub.add_parser("wrapper", help="update or check the portable wrapper")
    wrapper.add_argument("action", choices=["update", "check"])
    wrapper.add_argument("--zip", help="install from a local release ZIP")
    wrapper.add_argument("--tag", help="install a specific release tag")
    wrapper.add_argument("--force", action="store_true")
    wrapper.add_argument("--json", action="store_true")
    wrapper.set_defaults(func=cmd_wrapper)

    update = sub.add_parser("update", help="wrapper update, then optional core update")
    group = update.add_mutually_exclusive_group()
    group.add_argument("--core", dest="core", action="store_true", default=None)
    group.add_argument("--no-core", dest="core", action="store_false")
    update.add_argument("--zip", help="wrapper release ZIP to install")
    update.add_argument("--force", action="store_true")
    update.add_argument("--yes", "-y", action="store_true", help="never prompt")
    update.add_argument("--backup", action="store_true", help=argparse.SUPPRESS)
    update.add_argument("--core-only", action="store_true", help=argparse.SUPPRESS)
    update.set_defaults(func=cmd_update)

    rep = sub.add_parser("repair", help="restore wrapper files (run by launchers)")
    rep.add_argument("--quiet", action="store_true")
    rep.set_defaults(func=cmd_repair)

    ver = sub.add_parser("verify", help="verify this install in a fresh process")
    ver.add_argument("--no-gui", action="store_true")
    ver.set_defaults(func=cmd_verify)

    run = sub.add_parser("runtime", help=argparse.SUPPRESS)   # used by launch/runtime.cmd
    run.add_argument("action", choices=["plan", "done", "undone", "partial", "resume"])
    run.add_argument("--old", default="")
    run.add_argument("--failed", default="")
    run.add_argument("--target", default="")
    run.add_argument("--undoing", action="store_true")
    run.set_defaults(func=cmd_runtime)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted. Run any launcher to settle an unfinished update.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
