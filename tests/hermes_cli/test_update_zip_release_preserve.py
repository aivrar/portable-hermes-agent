"""#70337/#87331: the ZIP swap must preserve apps/desktop/release/.

The GitHub source ZIP carries only source; the BUILT desktop app
(release/win-unpacked/Hermes.exe) exists only in the live tree. Swapping
`apps` without grafting the live release dir deletes the desktop build.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace
import urllib.request
import zipfile

import pytest


def test_staged_apps_swap_preserves_live_release_dir(tmp_path, monkeypatch):
    from hermes_cli import main as hermes_main
    from hermes_cli.update_cmd import (
        _commit_staged_replacements,
        _stage_replacement,
    )

    # live tree: apps/desktop/release/win-unpacked/Hermes.exe + old source
    root = tmp_path / "install"
    live_apps = root / "apps" / "desktop"
    (live_apps / "release" / "win-unpacked").mkdir(parents=True)
    (live_apps / "release" / "win-unpacked" / "Hermes.exe").write_bytes(b"MZbuilt")
    (live_apps / "electron").mkdir()
    (live_apps / "electron" / "main.ts").write_text("old source")

    # extracted ZIP: new source, NO release dir (GitHub source archive shape)
    extracted = tmp_path / "extracted"
    zip_apps = extracted / "apps" / "desktop"
    (zip_apps / "electron").mkdir(parents=True)
    (zip_apps / "electron" / "main.ts").write_text("new source")

    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", root)

    # Reproduce the _update_via_zip staging loop for the `apps` entry,
    # including the release-dir graft.
    src = str(extracted / "apps")
    dst = str(root / "apps")
    staged_path = _stage_replacement(src, dst)
    live_release = os.path.join(dst, "desktop", "release")
    staged_release = os.path.join(staged_path, "desktop", "release")
    if os.path.isdir(live_release) and not os.path.exists(staged_release):
        os.makedirs(os.path.dirname(staged_release), exist_ok=True)
        shutil.copytree(live_release, staged_release)

    _commit_staged_replacements([(staged_path, dst)])

    # New source landed AND the built desktop app survived.
    assert (root / "apps" / "desktop" / "electron" / "main.ts").read_text() == (
        "new source"
    )
    exe = root / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
    assert exe.exists() and exe.read_bytes() == b"MZbuilt"


def test_portable_zip_update_installs_complete_gui_and_preserves_user_state(tmp_path, monkeypatch):
    from hermes_cli import main as hermes_main
    from hermes_cli import update_cmd

    root = tmp_path / "installed"
    root.mkdir()
    preserved = {
        ".hermes/gui_config.json": b'{"language":"zh-hant"}',
        ".hermes/.lmstudio_config": b'{"base_url":"http://localhost:1234","api_key":"test-only"}',
        ".hermes/custom_tools/personal.py": b"# personal tool",
        ".env": b"FAKE_TEST_KEY=keep",
        "python_embedded/python.exe": b"embedded runtime",
        "extensions/comfyui/user-model.bin": b"user model",
        "apps/desktop/release/win-unpacked/Hermes.exe": b"desktop build",
    }
    for name, content in preserved.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "README.md").write_bytes(b"old portable readme")
    source = Path(__file__).resolve().parents[2]
    delivered = {p.relative_to(source).as_posix(): p.read_bytes()
                 for p in (source / "gui").rglob("*.py")}
    for name in ("README.md", "README.zh-TW.md", "START.bat", "hermes_gui.bat",
                 "tools/update_hermes_tool.py"):
        delivered[name] = (source / name).read_bytes()
    delivered["apps/desktop/electron/main.cjs"] = b"// updated desktop source"
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, content in delivered.items():
            zf.writestr("portable-hermes-agent-main/" + name, content)
        for name in preserved:
            if not name.startswith("apps/"):
                zf.writestr("portable-hermes-agent-main/" + name, b"must not replace user data")

    def download(url, target):
        assert url == "https://github.com/aivrar/portable-hermes-agent/archive/refs/heads/main.zip"
        shutil.copyfile(archive, target)

    class SourceUpdateFinished(Exception):
        pass

    def stop_before_dependency_install():
        raise SourceUpdateFinished

    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", root)
    monkeypatch.setattr(hermes_main, "_capture_active_tool_dependencies", lambda: [])
    monkeypatch.setattr(hermes_main, "_resolve_update_branch", lambda args: "main")
    monkeypatch.setattr(urllib.request, "urlretrieve", download)
    monkeypatch.setattr(update_cmd, "_read_project_version", lambda: "old")
    monkeypatch.setattr(hermes_main, "_clear_bytecode_cache", lambda *args: None)
    monkeypatch.setattr(hermes_main, "_record_bytecode_fingerprint", lambda: None)
    monkeypatch.setattr(hermes_main, "_refresh_bootstrap_cache_scripts", lambda *args: None)
    monkeypatch.setattr(hermes_main, "_abort_dependency_sync_if_self_locked", stop_before_dependency_install)
    # Run the real download/extract/stage/swap path, stopping only before package installation.
    with pytest.raises(SourceUpdateFinished):
        update_cmd._update_via_zip(SimpleNamespace())
    for name, content in {**delivered, **preserved}.items():
        assert (root / name).read_bytes() == content, name
