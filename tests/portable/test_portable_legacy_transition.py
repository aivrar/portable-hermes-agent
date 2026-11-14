"""A v1.4.18 install moving to the evergreen wrapper, the way it really happens.

The v1.4.18 UPDATE.bat runs the fork's old ``hermes update``, which downloads
the repository's main-branch source ZIP and swaps every top-level entry in it
(except a small preserve set) into the install. This test builds that ZIP with
``git archive`` of this branch, applies the same swap to a v1.4.18 tree (from
``git archive v1.4.18``) that has a Python-3.13-style runtime and user data,
then runs what the user runs next: a launch (repair), the wrapper check, and a
wrapper update from a release ZIP built by ``build_release.py``.

Offline. Slow (about a minute): it extracts two full repository archives.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from portable_hermes import bridge, ownership, wrapper
from portable_hermes.wrapper import WrapperUpdater
from tests import IN_CI

from test_portable_lifecycle import FakeVerify, write_files  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

#: hermes_cli/update_cmd.py in v1.4.18: what its ZIP swap leaves alone.
V1418_PRESERVED = {".env", ".git", ".hermes", ".mypy_cache", ".pytest_cache", ".venv",
                   "extensions", "node_modules", "python_embedded", "venv"}

USER_DATA = {
    ".env": b"OPENROUTER_API_KEY=x\n",
    "cli-config.yaml": b"model: x\n",
    ".hermes/config.yaml": b"a: 1\n",
    ".hermes/custom_tools/personal.py": b"# personal tool\n",
    ".lmstudio_config": b'{"base_url": "http://localhost:1234"}\n',
    "extensions/tts-server/server.py": b"print('tts')\n",
    "workflows/mine.json": b"{}\n",
    "workspace/notes.txt": b"notes\n",
    "apps/desktop/release/win-unpacked/Hermes.exe": b"MZ desktop\n",
    "node_modules/pkg/index.js": b"1\n",
    # A Python 3.13 portable runtime, as v1.4.18's install.bat built it.
    "python_embedded/python.exe": b"MZ python\n",
    "python_embedded/python313.dll": b"MZ dll\n",
    "python_embedded/python313._pth": b"python313.zip\r\n.\r\nLib\r\nLib\\site-packages\r\n"
                                      b"DLLs\r\n\r\nimport site\r\n",
    "python_embedded/Lib/site-packages/requests/__init__.py": b"__version__ = '2.32'\n",
}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True)


def archive(ref: str, dest: Path, prefix: str) -> Path:
    proc = git("archive", "--format=zip", f"--prefix={prefix}/", "-o", str(dest), ref)
    if proc.returncode != 0:
        # In CI the v1.4.18 tag is fetched on purpose: never skip this test there.
        (pytest.fail if IN_CI else pytest.skip)(
            f"git archive {ref} unavailable: {proc.stderr.decode(errors='replace')}")
    return dest


def extract(zip_path: Path, dest: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    (top,) = list(dest.iterdir())
    return top


def v1418_zip_swap(root: Path, top: Path) -> None:
    """hermes_cli/update_cmd.py::_update_via_zip of v1.4.18, minus staging."""
    for entry in sorted(os.listdir(top)):
        if entry in V1418_PRESERVED:
            continue
        src, dst = top / entry, root / entry
        if entry == "apps" and (dst / "desktop" / "release").is_dir():
            shutil.copytree(dst / "desktop" / "release", src / "desktop" / "release",
                            dirs_exist_ok=True)
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        shutil.move(str(src), str(dst))


def user_tier(root: Path) -> dict:
    """Content of every user-tier file, except the updater's own state folder
    and the toolsets hook the launcher is meant to install."""
    hook = f"python_embedded/Lib/site-packages/{bridge.PTH_NAME}"
    out = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".portable/") or rel == hook or ownership.classify(rel) != "user":
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_a_v1_4_18_install_moves_to_the_evergreen_wrapper(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    old_top = extract(archive("v1.4.18", tmp_path / "old.zip", "portable-hermes-agent-1.4.18"),
                      tmp_path / "old")
    root = tmp_path / "install"
    shutil.move(str(old_top), str(root))
    write_files(root, USER_DATA)
    write_files(root, {"python_embedded/Lib/site-packages/hermes_project.pth":
                       (str(root) + "\n").encode()})
    assert not (root / "portable_hermes").exists()           # v1.4.18 had no wrapper package

    # What the v1.4.18 UPDATE.bat did: swap in the repository's main ZIP.
    new_top = extract(archive("HEAD", tmp_path / "main.zip", "portable-hermes-agent-main"),
                      tmp_path / "new")
    v1418_zip_swap(root, new_top)
    assert (root / "portable_hermes" / "ownership.py").is_file()
    assert not (root / ownership.RELEASE_MANIFEST).exists()  # no manifest ...
    assert not (root / ownership.PAYLOAD_DIR).exists()       # ... and no payload
    assert not (root / ".portable").exists()                 # no evergreen state yet
    for rel, data in USER_DATA.items():
        assert (root / rel).read_bytes() == data, rel        # the swap kept user data
    before = user_tier(root)

    # 1. The next launch: repair.
    report = wrapper.repair(root, quiet=True)
    assert report["restored"] == []
    assert any("nothing to repair" in note for note in report["notes"])
    hook = root / "python_embedded/Lib/site-packages" / bridge.PTH_NAME
    assert hook.read_text(encoding="utf-8") == bridge.pth_line()

    # 2. The wrapper check: unknown version, the newest evergreen release is offered.
    monkeypatch.setattr(wrapper, "latest_release", lambda timeout=20: {
        "tag": "v1.5.0", "url": "https://github.com/aivrar/portable-hermes-agent/x.zip",
        "asset": "portable-hermes-agent-v1.5.0.zip"})
    verify = FakeVerify(root)
    info = WrapperUpdater(root, quiet=True, run_verify=verify).check()
    assert info["installed_version"] == "unknown" and info["update_available"] is True

    # 3. The wrapper update from a release ZIP built from this branch.
    import build_release
    monkeypatch.setattr(sys, "argv", ["build_release.py", "--version", "v1.5.0",
                                      "--output-dir", str(tmp_path / "dist"),
                                      "--no-git-check"])
    build_release.main()
    built = tmp_path / "dist" / "portable-hermes-agent-v1.5.0.zip"
    result = WrapperUpdater(root, quiet=True, run_verify=verify).update(zip_path=str(built))
    assert result["ok"], result
    assert result["version"] in ("v1.5.0", "1.5.0")
    assert (root / ownership.RELEASE_MANIFEST).is_file()
    assert json.loads((root / ".portable/wrapper-state.json").read_text())["version"] == \
        result["version"]
    assert user_tier(root) == before

    # 4. Launches after that: the payload exists and nothing needs restoring.
    report = wrapper.repair(root, quiet=True)
    assert report["restored"] == [] and report["kept"] == 0
    assert hook.read_text(encoding="utf-8") == bridge.pth_line()
    assert user_tier(root) == before
    for name in ("hermes.bat", "hermes_gui.bat", "START.bat", "UPDATE.bat"):
        assert (root / name).read_bytes() == (REPO_ROOT / name).read_bytes(), name
