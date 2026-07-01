"""Portable-mode helpers for Windows-folder style Hermes distributions.

This module intentionally stays outside the agent loop and model tool surface.
Portable mode is a launch/runtime layout concern: the launcher points
``HERMES_HOME`` at a folder-local state directory, then normal Hermes code uses
the existing ``get_hermes_home()`` path.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


PYTHON_MIN = (3, 11)
PYTHON_MAX_EXCLUSIVE = (3, 14)
PORTABLE_BACKUP_PREFIX = "portable-runtime-"
PORTABLE_BACKUP_KEEP = 5


@dataclass(frozen=True)
class PortableDirectory:
    path: str
    exists: bool
    purpose: str


@dataclass(frozen=True)
class PortableExecutable:
    name: str
    path: str | None
    required: bool
    purpose: str

    @property
    def found(self) -> bool:
        return bool(self.path)


@dataclass(frozen=True)
class PortableStatus:
    root: str
    portable_home: str
    active_hermes_home: str | None
    portable_home_active: bool
    python_version: str
    python_supported: bool
    directories: list[PortableDirectory]
    executables: list[PortableExecutable]
    warnings: list[str]

    @property
    def ready(self) -> bool:
        required_tools_ok = all(exe.found for exe in self.executables if exe.required)
        return self.portable_home_active and self.python_supported and required_tools_ok

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ready"] = self.ready
        return data


@dataclass(frozen=True)
class PortableExtension:
    id: str
    name: str
    category: str
    default_url: str | None
    health_path: str | None
    docs_url: str
    ports: list[int]
    notes: list[str]
    managed: bool = False
    enabled_by_default: bool = False

    @property
    def health_url(self) -> str | None:
        if not self.default_url or not self.health_path:
            return None
        return urllib.parse.urljoin(self.default_url.rstrip("/") + "/", self.health_path.lstrip("/"))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["health_url"] = self.health_url
        return data


@dataclass(frozen=True)
class PortableExtensionStatus:
    extension: PortableExtension
    ready: bool
    status: str
    reason: str

    def to_dict(self) -> dict:
        data = self.extension.to_dict()
        data.update(
            {
                "ready": self.ready,
                "status": self.status,
                "reason": self.reason,
            }
        )
        return data


@dataclass(frozen=True)
class PortableMigrationItem:
    source: str
    target: str
    kind: str
    exists: bool
    target_exists: bool
    action: str
    notes: list[str]


PORTABLE_EXTENSIONS: tuple[PortableExtension, ...] = (
    PortableExtension(
        id="lm-studio",
        name="LM Studio local server",
        category="local-llm",
        default_url="http://127.0.0.1:1234",
        health_path="/v1/models",
        docs_url="https://lmstudio.ai/docs/developer/core/server",
        ports=[1234],
        notes=[
            "OpenAI-compatible local API server.",
            "Start explicitly from LM Studio or `lms server start --port 1234`.",
        ],
    ),
    PortableExtension(
        id="comfyui",
        name="ComfyUI",
        category="image-video-workflows",
        default_url="http://127.0.0.1:8188",
        health_path="/system_stats",
        docs_url="https://docs.comfy.org/development/comfyui-server/comms_routes",
        ports=[8188],
        notes=[
            "Default UI/API service is port 8188.",
            "Workflow execution uses ComfyUI's REST/WebSocket API; no management port is assumed.",
        ],
    ),
    PortableExtension(
        id="piper-tts-http",
        name="Piper TTS HTTP adapter",
        category="local-tts",
        default_url=None,
        health_path=None,
        docs_url="https://github.com/rhasspy/piper",
        ports=[],
        notes=[
            "Piper itself is a local TTS engine; HTTP wrappers vary by project.",
            "Configure a specific adapter/plugin before exposing model tools.",
        ],
    ),
)


def source_root() -> Path:
    """Return the source checkout root for the current Hermes import."""
    return Path(__file__).resolve().parent.parent


def normalize_root(root: str | os.PathLike[str] | None = None) -> Path:
    """Resolve a portable root path without requiring it to exist."""
    candidate = Path(root) if root else source_root()
    return candidate.expanduser().resolve()


def portable_home_for_root(root: str | os.PathLike[str] | None = None) -> Path:
    """Return the folder-local ``HERMES_HOME`` path for a portable root."""
    return normalize_root(root) / ".hermes"


def expected_directories(root: str | os.PathLike[str] | None = None) -> list[tuple[Path, str]]:
    """Directories a portable distribution owns directly."""
    portable_root = normalize_root(root)
    home = portable_home_for_root(portable_root)
    return [
        (home, "Portable HERMES_HOME state"),
        (home / "logs", "Hermes logs"),
        (home / "plugins", "User-installed plugins"),
        (home / "skills", "Synced and user-installed skills"),
        (home / "extensions", "Optional local AI extension installs"),
    ]


def _python_supported(version_info=sys.version_info) -> bool:
    version = (int(version_info.major), int(version_info.minor))
    return PYTHON_MIN <= version < PYTHON_MAX_EXCLUSIVE


def _same_path(left: str | os.PathLike[str] | None, right: str | os.PathLike[str]) -> bool:
    if not left:
        return False
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return False


def _first_existing(paths: Iterable[Path]) -> str | None:
    for path in paths:
        try:
            if path.exists():
                return str(path)
        except OSError:
            continue
    return None


def _is_windows_system_bash(path: str | os.PathLike[str] | None) -> bool:
    if platform.system() != "Windows" or not path:
        return False
    try:
        system_root = Path(os.getenv("SystemRoot") or os.getenv("WINDIR") or r"C:\Windows")
        return Path(path).resolve() == (system_root / "System32" / "bash.exe").resolve()
    except OSError:
        return False


def _directory_has_entries(path: Path) -> bool:
    try:
        next(path.iterdir())
        return True
    except (OSError, StopIteration):
        return False


def find_git_bash() -> str | None:
    """Find a Bash executable suitable for Hermes terminal tools."""
    if platform.system() != "Windows":
        return shutil.which("bash")

    custom = os.getenv("HERMES_GIT_BASH_PATH")
    if custom and Path(custom).is_file():
        return custom

    local_appdata = os.getenv("LOCALAPPDATA")
    candidates: list[Path] = []
    if local_appdata:
        candidates.extend(
            [
                Path(local_appdata) / "hermes" / "git" / "bin" / "bash.exe",
                Path(local_appdata) / "hermes" / "git" / "usr" / "bin" / "bash.exe",
                Path(local_appdata) / "Programs" / "Git" / "bin" / "bash.exe",
            ]
        )
    candidates.extend(
        [
            Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
            Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Git" / "usr" / "bin" / "bash.exe",
            Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "bin" / "bash.exe",
        ]
    )
    found = _first_existing(candidates)
    if found:
        return found

    on_path = shutil.which("bash")
    if on_path and not _is_windows_system_bash(on_path):
        return on_path
    return None



def collect_status(root: str | os.PathLike[str] | None = None) -> PortableStatus:
    """Collect non-mutating portable-mode diagnostics."""
    portable_root = normalize_root(root)
    home = portable_home_for_root(portable_root)
    active_home = os.getenv("HERMES_HOME")

    directories = [
        PortableDirectory(path=str(path), exists=path.exists(), purpose=purpose)
        for path, purpose in expected_directories(portable_root)
    ]

    executables = [
        PortableExecutable("git", shutil.which("git"), True, "updates and extension installs"),
        PortableExecutable("bash", find_git_bash(), True, "Hermes local terminal backend"),
        PortableExecutable("node", shutil.which("node"), False, "desktop/browser tooling"),
        PortableExecutable("npm", shutil.which("npm"), False, "desktop build tooling"),
        PortableExecutable("rg", shutil.which("rg"), False, "fast file search"),
        PortableExecutable("ffmpeg", shutil.which("ffmpeg"), False, "media and voice tooling"),
    ]

    warnings: list[str] = []
    if not _same_path(active_home, home):
        warnings.append(
            "HERMES_HOME is not pointed at the portable home. "
            "Run `hermes portable env` and apply the printed environment before launch."
        )
    if not _python_supported():
        warnings.append(
            f"Python {sys.version.split()[0]} is outside Hermes' supported "
            "portable range >=3.11,<3.14."
        )
    for exe in executables:
        if exe.required and not exe.found:
            warnings.append(f"Missing required executable for portable mode: {exe.name}.")
    if _directory_has_entries(portable_root / "extensions"):
        warnings.append(
            "Legacy root-level extensions/ detected. Run `hermes portable migrate --apply` "
            "to copy them under .hermes/extensions/legacy-root-extensions before relying on updates."
        )

    return PortableStatus(
        root=str(portable_root),
        portable_home=str(home),
        active_hermes_home=active_home,
        portable_home_active=_same_path(active_home, home),
        python_version=sys.version.split()[0],
        python_supported=_python_supported(),
        directories=directories,
        executables=executables,
        warnings=warnings,
    )


def initialize_portable_root(
    root: str | os.PathLike[str] | None = None,
    *,
    apply: bool = False,
) -> dict:
    """Plan or create the folder-local portable directory layout."""
    actions = []
    for path, purpose in expected_directories(root):
        existed_before = path.exists()
        exists = existed_before
        created = False
        if apply and not existed_before:
            path.mkdir(parents=True, exist_ok=True)
            exists = True
            created = True
        actions.append(
            {
                "path": str(path),
                "purpose": purpose,
                "exists": exists,
                "created": created,
            }
        )
    return {"root": str(normalize_root(root)), "applied": apply, "actions": actions}


def _migration_specs(
    root: Path,
    *,
    legacy_home: str | os.PathLike[str] | None = None,
) -> list[tuple[Path, Path, str, list[str]]]:
    home = portable_home_for_root(root)
    specs = [
        (
            root / ".env",
            home / ".env",
            "file",
            ["Provider API keys and local environment variables."],
        ),
        (
            root / "config.yaml",
            home / "config.yaml",
            "file",
            ["Legacy root-level Hermes config."],
        ),
        (
            root / "permissions.json",
            home / "permissions.json",
            "file",
            ["Legacy portable permission policy, if present."],
        ),
        (
            root / "sessions",
            home / "sessions",
            "directory",
            ["Conversation/session database files."],
        ),
        (
            root / "memories",
            home / "memories",
            "directory",
            ["Persistent memory store."],
        ),
        (
            root / "memory",
            home / "memories" / "legacy-memory",
            "directory",
            ["Older singular memory directory; copied under memories/legacy-memory."],
        ),
        (
            root / "extensions",
            home / "extensions" / "legacy-root-extensions",
            "directory",
            [
                "Legacy root-level portable extensions; new portable extension state lives under .hermes/extensions.",
            ],
        ),
    ]
    if legacy_home:
        legacy = normalize_root(legacy_home)
        specs.extend(
            [
                (
                    legacy / ".env",
                    home / ".env",
                    "file",
                    ["Provider API keys from an explicit legacy Hermes home."],
                ),
                (
                    legacy / "config.yaml",
                    home / "config.yaml",
                    "file",
                    ["Config from an explicit legacy Hermes home."],
                ),
                (
                    legacy / "permissions.json",
                    home / "permissions.json",
                    "file",
                    ["Permission policy from an explicit legacy Hermes home."],
                ),
                (
                    legacy / "sessions",
                    home / "sessions",
                    "directory",
                    ["Sessions from an explicit legacy Hermes home."],
                ),
                (
                    legacy / "skills",
                    home / "skills",
                    "directory",
                    ["User-installed skills from an explicit legacy Hermes home."],
                ),
            ]
        )
    return specs


def collect_migration_plan(
    root: str | os.PathLike[str] | None = None,
    *,
    apply: bool = False,
    overwrite: bool = False,
    legacy_home: str | os.PathLike[str] | None = None,
) -> dict:
    """Plan or copy legacy portable state into folder-local ``.hermes``.

    ``apply=True`` copies files/directories but never deletes the source.
    Existing targets are preserved unless ``overwrite=True`` is explicit.
    """
    portable_root = normalize_root(root)
    actions: list[PortableMigrationItem] = []
    for source, target, kind, notes in _migration_specs(portable_root, legacy_home=legacy_home):
        exists = source.exists()
        target_exists = target.exists()
        action = "missing"
        if exists:
            if target_exists and not overwrite:
                action = "skipped-target-exists"
            elif apply:
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    if target.exists() and overwrite:
                        shutil.rmtree(target)
                    shutil.copytree(source, target, dirs_exist_ok=overwrite)
                else:
                    if target.exists() and overwrite:
                        target.unlink()
                    shutil.copy2(source, target)
                target_exists = True
                action = "copied"
            else:
                action = "would-copy"
        actions.append(
            PortableMigrationItem(
                source=str(source),
                target=str(target),
                kind=kind,
                exists=exists,
                target_exists=target_exists,
                action=action,
                notes=notes,
            )
        )
    return {
        "root": str(portable_root),
        "portable_home": str(portable_home_for_root(portable_root)),
        "applied": apply,
        "overwrite": overwrite,
        "legacy_home": str(normalize_root(legacy_home)) if legacy_home else None,
        "actions": [asdict(action) for action in actions],
    }


def _iter_portable_backup_files(root: Path, *, include_python: bool = False) -> Iterable[Path]:
    home = portable_home_for_root(root)
    # .hermes is the primary portable state root.  The root-level extensions
    # directory is kept here only for legacy portable checkouts created before
    # extension payloads moved under .hermes/extensions.
    candidates = [home, root / "extensions"]
    if include_python:
        candidates.append(root / "python_embedded")

    for base in candidates:
        if not base.exists():
            continue
        if base.is_file() and not base.is_symlink():
            yield base
            continue
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            current = Path(dirpath)
            if current == home:
                # Do not recursively include prior backups in new backups.
                dirnames[:] = [name for name in dirnames if name != "backups"]
            dirnames[:] = [name for name in dirnames if name != "__pycache__"]
            for filename in filenames:
                path = current / filename
                if path.is_symlink():
                    continue
                yield path


def _prune_portable_backups(backup_dir: Path, *, keep: int) -> int:
    keep = max(int(keep), 1)
    if not backup_dir.is_dir():
        return 0
    backups = sorted(
        (
            path
            for path in backup_dir.iterdir()
            if path.is_file()
            and path.name.startswith(PORTABLE_BACKUP_PREFIX)
            and path.suffix.lower() == ".zip"
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    removed = 0
    for old_backup in backups[keep:]:
        try:
            old_backup.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _next_portable_backup_path(backup_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S-%f")
    for attempt in range(1000):
        suffix = "" if attempt == 0 else f"-{attempt}"
        candidate = backup_dir / f"{PORTABLE_BACKUP_PREFIX}{stamp}{suffix}.zip"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Unable to allocate a unique portable backup archive path")


def create_portable_runtime_backup(
    root: str | os.PathLike[str] | None = None,
    *,
    include_python: bool = False,
    keep: int = PORTABLE_BACKUP_KEEP,
) -> dict:
    """Create a portable runtime backup for folder-local custom state.

    This covers ``.hermes`` plus ``extensions``.  ``python_embedded`` is
    optional because it can be large and is usually reinstallable.
    """
    portable_root = normalize_root(root)
    home = portable_home_for_root(portable_root)
    backup_dir = home / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    files = list(_iter_portable_backup_files(portable_root, include_python=include_python))
    if not files:
        return {
            "created": False,
            "root": str(portable_root),
            "portable_home": str(home),
            "path": None,
            "files": 0,
            "bytes": 0,
            "included": [],
            "pruned": 0,
            "reason": "No portable runtime files found.",
        }

    out_path = _next_portable_backup_path(backup_dir)
    written = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            try:
                rel = path.relative_to(portable_root)
            except ValueError:
                continue
            try:
                archive.write(path, arcname=rel.as_posix())
                written += 1
            except (OSError, ValueError):
                continue

    if written == 0:
        out_path.unlink(missing_ok=True)
        return {
            "created": False,
            "root": str(portable_root),
            "portable_home": str(home),
            "path": None,
            "files": 0,
            "bytes": 0,
            "included": [],
            "pruned": 0,
            "reason": "No portable runtime files could be written.",
        }

    pruned = _prune_portable_backups(backup_dir, keep=keep)
    included = [".hermes"]
    if _directory_has_entries(portable_root / "extensions"):
        included.append("extensions")
    if include_python and (portable_root / "python_embedded").exists():
        included.append("python_embedded")
    return {
        "created": True,
        "root": str(portable_root),
        "portable_home": str(home),
        "path": str(out_path),
        "files": written,
        "bytes": out_path.stat().st_size,
        "included": included,
        "pruned": pruned,
        "reason": None,
    }


def render_env(root: str | os.PathLike[str] | None = None, *, shell: str = "powershell") -> str:
    """Render commands that activate folder-local portable state."""
    home = portable_home_for_root(root)
    shell = (shell or "powershell").lower()
    if shell in {"powershell", "pwsh"}:
        value = str(home).replace("'", "''")
        return f"$env:HERMES_HOME = '{value}'"
    if shell == "cmd":
        return f'set "HERMES_HOME={home}"'
    if shell in {"bash", "sh"}:
        value = str(home).replace("'", "'\"'\"'")
        return f"export HERMES_HOME='{value}'"
    raise ValueError(f"Unsupported shell: {shell}")


def _quote_powershell(value: str | os.PathLike[str]) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _quote_cmd(value: str | os.PathLike[str]) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _quote_sh(value: str | os.PathLike[str]) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def render_install_command(
    root: str | os.PathLike[str] | None = None,
    *,
    shell: str = "powershell",
    include_desktop: bool = False,
    run_setup: bool = False,
) -> str:
    """Render the upstream installer command for a folder-local portable root.

    The command is printed for explicit user execution. It is intentionally not
    run by ``hermes portable`` so package installation and git mutation remain
    visible operator actions.
    """
    portable_root = normalize_root(root)
    home = portable_home_for_root(portable_root)
    shell = (shell or "powershell").lower()

    if shell in {"powershell", "pwsh", "cmd"}:
        quote = _quote_powershell if shell in {"powershell", "pwsh"} else _quote_cmd
        shell_command = "pwsh" if shell == "pwsh" else "powershell"
        command = [
            shell_command,
            "-ExecutionPolicy",
            "Bypass",
            "-NoProfile",
            "-File",
            quote(portable_root / "scripts" / "install.ps1"),
            "-HermesHome",
            quote(home),
            "-InstallDir",
            quote(portable_root),
            "-NonInteractive",
        ]
        if not run_setup:
            command.append("-SkipSetup")
        if include_desktop:
            command.append("-IncludeDesktop")
        return " ".join(command)

    if shell in {"bash", "sh"}:
        command = [
            _quote_sh(portable_root / "scripts" / "install.sh"),
            "--hermes-home",
            _quote_sh(home),
            "--dir",
            _quote_sh(portable_root),
            "--non-interactive",
        ]
        if not run_setup:
            command.append("--skip-setup")
        if include_desktop:
            command.append("--include-desktop")
        return " ".join(command)

    raise ValueError(f"Unsupported shell: {shell}")


def render_desktop_command(
    root: str | os.PathLike[str] | None = None,
    *,
    shell: str = "powershell",
    source: bool = False,
    skip_build: bool = False,
    force_build: bool = False,
    build_only: bool = False,
) -> str:
    """Render a portable Electron desktop launch command."""
    portable_root = normalize_root(root)
    shell = (shell or "powershell").lower()
    desktop_mode_args = []
    if source:
        desktop_mode_args.append("--source")
    if skip_build:
        desktop_mode_args.append("--skip-build")
    if force_build:
        desktop_mode_args.append("--force-build")
    if build_only:
        desktop_mode_args.append("--build-only")

    if shell in {"powershell", "pwsh"}:
        shell_command = "pwsh" if shell == "pwsh" else "powershell"
        script = portable_root / "scripts" / "portable" / "hermes-portable.ps1"
        return " ".join(
            [
                shell_command,
                "-ExecutionPolicy",
                "Bypass",
                "-NoProfile",
                "-File",
                _quote_powershell(script),
                "-Root",
                _quote_powershell(portable_root),
                "-Desktop",
                *(_quote_powershell(arg) for arg in desktop_mode_args),
            ]
        )
    if shell == "cmd":
        script = portable_root / "scripts" / "portable" / "hermes-portable.cmd"
        return " ".join(
            [
                _quote_cmd(script),
                "-Root",
                _quote_cmd(portable_root),
                "-Desktop",
                *(_quote_cmd(arg) for arg in desktop_mode_args),
            ]
        )
    if shell in {"bash", "sh"}:
        script = portable_root / "scripts" / "portable" / "hermes-portable.sh"
        desktop_args = [
            "desktop",
            "--hermes-root",
            str(portable_root),
            "--cwd",
            str(portable_root),
            *desktop_mode_args,
        ]
        return " ".join([_quote_sh(script), *(_quote_sh(arg) for arg in desktop_args)])
    raise ValueError(f"Unsupported shell: {shell}")


def _is_loopback_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() in {
        "localhost",
        "127.0.0.1",
        "::1",
    }


def _probe_http_url(url: str, *, timeout: float = 0.35) -> tuple[bool, str]:
    if not _is_loopback_url(url):
        return False, "refusing to probe non-loopback URL"
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return False, str(exc)

    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 0) or 0
            if 200 <= status < 300 or status in {401, 403}:
                return True, f"HTTP {status}"
            return False, f"HTTP {status}"
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return True, f"HTTP {exc.code}"
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def extension_catalog() -> list[PortableExtension]:
    """Return known optional local AI extensions.

    Entries are informational and disabled by default. They do not register
    model tools or start services.
    """
    return list(PORTABLE_EXTENSIONS)


def collect_extension_status(timeout: float = 0.35) -> list[PortableExtensionStatus]:
    statuses: list[PortableExtensionStatus] = []
    for extension in extension_catalog():
        health_url = extension.health_url
        if not health_url:
            statuses.append(
                PortableExtensionStatus(
                    extension=extension,
                    ready=False,
                    status="manual",
                    reason="No canonical local HTTP endpoint is defined for this adapter.",
                )
            )
            continue
        ready, reason = _probe_http_url(health_url, timeout=timeout)
        statuses.append(
            PortableExtensionStatus(
                extension=extension,
                ready=ready,
                status="ready" if ready else "offline",
                reason=reason,
            )
        )
    return statuses


def _print_extension_status(statuses: list[PortableExtensionStatus]) -> None:
    print("Portable local AI extensions:")
    for status in statuses:
        extension = status.extension
        endpoint = extension.health_url or "(manual adapter)"
        ports = ", ".join(str(port) for port in extension.ports) or "none"
        print(f"  [{status.status}] {extension.id} - {extension.name}")
        print(f"      category: {extension.category}")
        print(f"      endpoint: {endpoint}")
        print(f"      ports: {ports}")
        print(f"      managed: {'yes' if extension.managed else 'no'}")
        print(f"      enabled by default: {'yes' if extension.enabled_by_default else 'no'}")
        print(f"      reason: {status.reason}")


def _print_migration_plan(plan: dict) -> None:
    print(f"Portable root: {plan['root']}")
    print(f"Portable HERMES_HOME: {plan['portable_home']}")
    print(f"Applied: {'yes' if plan['applied'] else 'no'}")
    print("")
    print("Migration actions:")
    for item in plan["actions"]:
        print(f"  [{item['action']}] {item['source']} -> {item['target']}")
        for note in item.get("notes") or []:
            print(f"      {note}")


def _print_portable_backup(result: dict) -> None:
    print(f"Portable root: {result['root']}")
    print(f"Portable HERMES_HOME: {result['portable_home']}")
    if result["created"]:
        print(f"Backup: {result['path']}")
        print(f"Files: {result['files']}")
        print(f"Included: {', '.join(result['included'])}")
        if result["pruned"]:
            print(f"Pruned old backups: {result['pruned']}")
    else:
        print(f"Backup skipped: {result['reason']}")


def _print_status(status: PortableStatus) -> None:
    print(f"Portable root: {status.root}")
    print(f"Portable HERMES_HOME: {status.portable_home}")
    print(f"Active HERMES_HOME: {status.active_hermes_home or '(not set)'}")
    print(f"Portable home active: {'yes' if status.portable_home_active else 'no'}")
    print(f"Python: {status.python_version} ({'supported' if status.python_supported else 'unsupported'})")
    print("")
    print("Directories:")
    for item in status.directories:
        marker = "ok" if item.exists else "missing"
        print(f"  [{marker}] {item.path} - {item.purpose}")
    print("")
    print("Executables:")
    for exe in status.executables:
        required = "required" if exe.required else "optional"
        marker = "ok" if exe.found else "missing"
        print(f"  [{marker}] {exe.name} ({required}) - {exe.path or exe.purpose}")
    if status.warnings:
        print("")
        print("Warnings:")
        for warning in status.warnings:
            print(f"  - {warning}")


def cmd_portable(args) -> int:
    """Dispatch ``hermes portable`` subcommands."""
    action = getattr(args, "portable_action", None) or "status"
    root = getattr(args, "root", None)

    if action == "status":
        status = collect_status(root)
        if getattr(args, "json", False):
            print(json.dumps(status.to_dict(), indent=2, sort_keys=True))
        else:
            _print_status(status)
        return 0 if status.ready else 1

    if action == "env":
        print(render_env(root, shell=getattr(args, "shell", "powershell")))
        return 0

    if action == "install-command":
        print(
            render_install_command(
                root,
                shell=getattr(args, "shell", "powershell"),
                include_desktop=bool(getattr(args, "include_desktop", False)),
                run_setup=bool(getattr(args, "run_setup", False)),
            )
        )
        return 0

    if action == "desktop-command":
        print(
            render_desktop_command(
                root,
                shell=getattr(args, "shell", "powershell"),
                source=bool(getattr(args, "source", False)),
                skip_build=bool(getattr(args, "skip_build", False)),
                force_build=bool(getattr(args, "force_build", False)),
                build_only=bool(getattr(args, "build_only", False)),
            )
        )
        return 0

    if action == "extensions":
        timeout = float(getattr(args, "timeout", 0.35) or 0.35)
        statuses = collect_extension_status(timeout=timeout)
        if getattr(args, "json", False):
            print(json.dumps({"extensions": [status.to_dict() for status in statuses]}, indent=2, sort_keys=True))
        else:
            _print_extension_status(statuses)
        return 0

    if action == "backup":
        result = create_portable_runtime_backup(
            root,
            include_python=bool(getattr(args, "include_python", False)),
            keep=int(getattr(args, "keep", PORTABLE_BACKUP_KEEP) or PORTABLE_BACKUP_KEEP),
        )
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            _print_portable_backup(result)
        return 0 if result["created"] else 1

    if action == "migrate":
        plan = collect_migration_plan(
            root,
            apply=bool(getattr(args, "apply", False)),
            overwrite=bool(getattr(args, "overwrite", False)),
            legacy_home=getattr(args, "legacy_home", None),
        )
        if getattr(args, "json", False):
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            _print_migration_plan(plan)
        return 0

    if action == "init":
        result = initialize_portable_root(root, apply=bool(getattr(args, "apply", False)))
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for item in result["actions"]:
                if item["created"]:
                    verb = "Created"
                    state = "created"
                elif item["exists"]:
                    verb = "Exists"
                    state = "exists"
                else:
                    verb = "Would create"
                    state = "missing"
                print(f"{verb}: {item['path']} ({item['purpose']}; {state})")
        return 0

    raise ValueError(f"Unknown portable action: {action}")
