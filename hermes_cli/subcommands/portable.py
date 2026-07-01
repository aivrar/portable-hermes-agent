"""``hermes portable`` subcommand parser."""

from __future__ import annotations

import argparse
from typing import Callable


def _add_root_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        help="Portable distribution root. Defaults to the current Hermes source root.",
    )


def build_portable_parser(subparsers, *, cmd_portable: Callable) -> None:
    """Attach the ``portable`` subcommand to ``subparsers``."""
    portable_parser = subparsers.add_parser(
        "portable",
        help="Inspect and prepare folder-local portable mode",
        description=(
            "Portable mode keeps Hermes state beside the distribution folder by "
            "launching with HERMES_HOME pointed at <portable-root>/.hermes. "
            "This command inspects that layout and prints activation commands."
        ),
    )
    portable_sub = portable_parser.add_subparsers(dest="portable_action")

    status = portable_sub.add_parser(
        "status",
        help="Show portable-mode readiness and dependency checks",
    )
    _add_root_arg(status)
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    status.set_defaults(func=cmd_portable, portable_action="status")

    env = portable_sub.add_parser(
        "env",
        help="Print the HERMES_HOME command needed to activate portable mode",
    )
    _add_root_arg(env)
    env.add_argument(
        "--shell",
        choices=("powershell", "pwsh", "cmd", "bash", "sh"),
        default="powershell",
        help="Shell syntax to print",
    )
    env.set_defaults(func=cmd_portable, portable_action="env")

    install_command = portable_sub.add_parser(
        "install-command",
        help="Print the upstream installer command for this portable root",
    )
    _add_root_arg(install_command)
    install_command.add_argument(
        "--shell",
        choices=("powershell", "pwsh", "cmd", "bash", "sh"),
        default="powershell",
        help="Shell syntax to print",
    )
    install_command.add_argument(
        "--include-desktop",
        action="store_true",
        help="Include the Electron desktop build in the printed install command",
    )
    install_command.add_argument(
        "--run-setup",
        action="store_true",
        help="Do not add the installer's non-interactive setup skip flag",
    )
    install_command.set_defaults(func=cmd_portable, portable_action="install-command")

    desktop_command = portable_sub.add_parser(
        "desktop-command",
        help="Print a portable Electron desktop launch command",
    )
    _add_root_arg(desktop_command)
    desktop_command.add_argument(
        "--shell",
        choices=("powershell", "pwsh", "cmd", "bash", "sh"),
        default="powershell",
        help="Shell syntax to print",
    )
    desktop_command.add_argument("--source", action="store_true", help="Launch Electron in source mode")
    desktop_command.add_argument("--skip-build", action="store_true", help="Use an existing desktop build")
    desktop_command.add_argument("--force-build", action="store_true", help="Force a desktop rebuild")
    desktop_command.add_argument("--build-only", action="store_true", help="Build desktop and do not launch")
    desktop_command.set_defaults(func=cmd_portable, portable_action="desktop-command")

    extensions = portable_sub.add_parser(
        "extensions",
        help="Show optional local AI extension manifests and readiness",
    )
    extensions.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    extensions.add_argument(
        "--timeout",
        type=float,
        default=0.35,
        help="Loopback HTTP probe timeout in seconds",
    )
    extensions.set_defaults(func=cmd_portable, portable_action="extensions")

    backup = portable_sub.add_parser(
        "backup",
        help="Back up portable .hermes and extension payloads",
    )
    _add_root_arg(backup)
    backup.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    backup.add_argument(
        "--include-python",
        action="store_true",
        help="Include python_embedded in the backup archive",
    )
    backup.add_argument(
        "--keep",
        type=int,
        default=5,
        help="Number of portable runtime backup archives to keep",
    )
    backup.set_defaults(func=cmd_portable, portable_action="backup")

    migrate = portable_sub.add_parser(
        "migrate",
        help="Plan or copy legacy portable state into folder-local .hermes",
    )
    _add_root_arg(migrate)
    migrate.add_argument(
        "--legacy-home",
        help="Explicit old Hermes home to copy from, such as %USERPROFILE%\\.hermes",
    )
    migrate.add_argument("--apply", action="store_true", help="Copy detected legacy state")
    migrate.add_argument("--overwrite", action="store_true", help="Replace existing migration targets")
    migrate.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    migrate.set_defaults(func=cmd_portable, portable_action="migrate")

    init = portable_sub.add_parser(
        "init",
        help="Create the folder-local portable state directories",
    )
    _add_root_arg(init)
    init.add_argument("--apply", action="store_true", help="Create directories")
    init.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    init.set_defaults(func=cmd_portable, portable_action="init")

    portable_parser.set_defaults(func=cmd_portable, portable_action="status")
