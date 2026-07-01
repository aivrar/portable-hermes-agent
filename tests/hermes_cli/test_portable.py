import argparse
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import hermes_cli.portable as portable_mod
from hermes_cli.portable import (
    cmd_portable,
    collect_extension_status,
    collect_migration_plan,
    collect_status,
    create_portable_runtime_backup,
    extension_catalog,
    initialize_portable_root,
    portable_home_for_root,
    render_desktop_command,
    render_env,
    render_install_command,
)
from hermes_cli.subcommands.portable import build_portable_parser


REPO_ROOT = Path(__file__).resolve().parents[2]
PORTABLE_SOURCE_FILES = (
    REPO_ROOT / "hermes_cli" / "portable.py",
    REPO_ROOT / "hermes_cli" / "subcommands" / "portable.py",
)


def test_portable_home_is_folder_local(tmp_path):
    assert portable_home_for_root(tmp_path) == tmp_path.resolve() / ".hermes"


def test_render_env_uses_existing_hermes_home_only(tmp_path):
    rendered = render_env(tmp_path, shell="powershell")

    assert "HERMES_HOME" in rendered
    assert "HERMES_PORTABLE" not in rendered
    assert str(tmp_path.resolve() / ".hermes") in rendered


def test_render_install_command_is_explicit_and_folder_local(tmp_path):
    rendered = render_install_command(tmp_path, shell="powershell")

    assert "install.ps1" in rendered
    assert "-HermesHome" in rendered
    assert "-InstallDir" in rendered
    assert "-NonInteractive" in rendered
    assert "-SkipSetup" in rendered
    assert "HERMES_PORTABLE" not in rendered
    assert str(tmp_path.resolve() / ".hermes") in rendered
    assert str(tmp_path.resolve()) in rendered


def test_render_install_command_can_include_desktop(tmp_path):
    rendered = render_install_command(tmp_path, shell="cmd", include_desktop=True)

    assert "-IncludeDesktop" in rendered


def test_render_install_command_respects_pwsh_shell(tmp_path):
    rendered = render_install_command(tmp_path, shell="pwsh")

    assert rendered.startswith("pwsh ")


def test_render_desktop_command_pins_root_and_cwd(tmp_path):
    rendered = render_desktop_command(tmp_path, shell="powershell", skip_build=True)

    assert "hermes-portable.ps1" in rendered
    assert "-Root" in rendered
    assert "-Desktop" in rendered
    assert "--skip-build" in rendered
    assert str(tmp_path.resolve()) in rendered
    assert "'desktop'" not in rendered
    assert "--hermes-root" not in rendered
    assert "--cwd" not in rendered


def test_render_desktop_command_cmd_uses_cmd_launcher(tmp_path):
    rendered = render_desktop_command(tmp_path, shell="cmd")

    assert "hermes-portable.cmd" in rendered
    assert "-Root" in rendered
    assert "-Desktop" in rendered
    assert '"desktop"' not in rendered


def test_render_desktop_command_bash_passes_direct_desktop_args(tmp_path):
    rendered = render_desktop_command(tmp_path, shell="bash", build_only=True)

    assert "hermes-portable.sh" in rendered
    assert "'desktop'" in rendered
    assert "--hermes-root" in rendered
    assert "--cwd" in rendered
    assert "--build-only" in rendered


def test_find_git_bash_prefers_git_for_windows_over_wsl_bash(monkeypatch, tmp_path):
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"
    git_bash.parent.mkdir(parents=True)
    git_bash.touch()

    monkeypatch.setattr(portable_mod.platform, "system", lambda: "Windows")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.delenv("HERMES_GIT_BASH_PATH", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(
        portable_mod.shutil,
        "which",
        lambda name: r"C:\Windows\System32\bash.exe" if name == "bash" else None,
    )

    assert portable_mod.find_git_bash() == str(git_bash)


def test_extension_catalog_is_disabled_by_default_and_loopback_only():
    catalog = extension_catalog()

    assert {extension.id for extension in catalog} >= {"lm-studio", "comfyui", "piper-tts-http"}
    assert all(extension.enabled_by_default is False for extension in catalog)
    assert all(extension.managed is False for extension in catalog)
    for extension in catalog:
        if extension.default_url:
            assert extension.default_url.startswith("http://127.0.0.1:")


def test_collect_extension_status_does_not_require_services(monkeypatch):
    def fake_probe(url, *, timeout):
        if url.endswith("/v1/models"):
            return True, "HTTP 200"
        return False, "connection refused"

    monkeypatch.setattr("hermes_cli.portable._probe_http_url", fake_probe)

    statuses = collect_extension_status(timeout=0.01)
    by_id = {status.extension.id: status for status in statuses}

    assert by_id["lm-studio"].ready is True
    assert by_id["lm-studio"].status == "ready"
    assert by_id["comfyui"].ready is False
    assert by_id["piper-tts-http"].status == "manual"


def test_collect_migration_plan_is_dry_run_by_default(tmp_path):
    legacy_env = tmp_path / ".env"
    legacy_env.write_text("OPENAI_API_KEY=test\n", encoding="utf-8")

    plan = collect_migration_plan(tmp_path)
    env_action = next(action for action in plan["actions"] if action["source"] == str(legacy_env.resolve()))

    assert plan["applied"] is False
    assert env_action["action"] == "would-copy"
    assert not (tmp_path / ".hermes" / ".env").exists()


def test_collect_migration_plan_apply_copies_without_deleting_source(tmp_path):
    legacy_config = tmp_path / "config.yaml"
    legacy_config.write_text("model: test/model\n", encoding="utf-8")

    plan = collect_migration_plan(tmp_path, apply=True)
    config_action = next(action for action in plan["actions"] if action["source"] == str(legacy_config.resolve()))

    assert config_action["action"] == "copied"
    assert legacy_config.exists()
    assert (tmp_path / ".hermes" / "config.yaml").read_text(encoding="utf-8") == "model: test/model\n"


def test_collect_migration_plan_preserves_existing_targets(tmp_path):
    legacy_env = tmp_path / ".env"
    legacy_env.write_text("OLD=1\n", encoding="utf-8")
    target = tmp_path / ".hermes" / ".env"
    target.parent.mkdir()
    target.write_text("NEW=1\n", encoding="utf-8")

    plan = collect_migration_plan(tmp_path, apply=True)
    env_action = next(action for action in plan["actions"] if action["source"] == str(legacy_env.resolve()))

    assert env_action["action"] == "skipped-target-exists"
    assert target.read_text(encoding="utf-8") == "NEW=1\n"


def test_collect_migration_plan_can_copy_explicit_legacy_home(tmp_path):
    legacy_home = tmp_path / "old-home"
    legacy_home.mkdir()
    legacy_permissions = legacy_home / "permissions.json"
    legacy_permissions.write_text('{"allow": []}\n', encoding="utf-8")
    portable_root = tmp_path / "portable"
    portable_root.mkdir()

    plan = collect_migration_plan(portable_root, apply=True, legacy_home=legacy_home)
    permission_action = next(
        action for action in plan["actions"]
        if action["source"] == str(legacy_permissions.resolve())
    )

    assert plan["legacy_home"] == str(legacy_home.resolve())
    assert permission_action["action"] == "copied"
    assert (portable_root / ".hermes" / "permissions.json").read_text(encoding="utf-8") == '{"allow": []}\n'


def test_collect_migration_plan_copies_legacy_root_extensions(tmp_path):
    legacy_extension = tmp_path / "extensions" / "local-service" / "README.md"
    legacy_extension.parent.mkdir(parents=True)
    legacy_extension.write_text("legacy extension\n", encoding="utf-8")

    plan = collect_migration_plan(tmp_path, apply=True)
    extension_action = next(
        action for action in plan["actions"]
        if action["source"] == str((tmp_path / "extensions").resolve())
    )

    assert extension_action["action"] == "copied"
    copied = tmp_path / ".hermes" / "extensions" / "legacy-root-extensions" / "local-service" / "README.md"
    assert copied.read_text(encoding="utf-8") == "legacy extension\n"


def test_collect_status_detects_active_portable_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))

    status = collect_status(tmp_path)

    assert status.portable_home == str(home.resolve())
    assert status.active_hermes_home == str(home)
    assert status.portable_home_active is True


def test_collect_status_ignores_empty_legacy_root_extensions(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    (tmp_path / "extensions").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    status = collect_status(tmp_path)

    assert not any("Legacy root-level extensions" in warning for warning in status.warnings)


def test_collect_status_warns_about_legacy_root_extensions(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    legacy_file = tmp_path / "extensions" / "local-service" / "README.md"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text("local service\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))

    status = collect_status(tmp_path)

    assert any("Legacy root-level extensions" in warning for warning in status.warnings)


def test_initialize_portable_root_is_dry_run_by_default(tmp_path):
    result = initialize_portable_root(tmp_path)

    assert result["applied"] is False
    assert not (tmp_path / ".hermes").exists()


def test_initialize_portable_root_apply_creates_expected_dirs(tmp_path):
    result = initialize_portable_root(tmp_path, apply=True)

    assert result["applied"] is True
    assert (tmp_path / ".hermes").is_dir()
    assert (tmp_path / ".hermes" / "logs").is_dir()
    assert (tmp_path / ".hermes" / "plugins").is_dir()
    assert (tmp_path / ".hermes" / "skills").is_dir()
    assert (tmp_path / ".hermes" / "extensions").is_dir()


def test_initialize_portable_root_apply_does_not_recreate_existing_dirs(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()

    result = initialize_portable_root(tmp_path, apply=True)
    home_action = next(
        action for action in result["actions"]
        if action["path"] == str(home.resolve())
    )

    assert home_action["exists"] is True
    assert home_action["created"] is False


def test_create_portable_runtime_backup_includes_home_extensions(tmp_path):
    home_config = tmp_path / ".hermes" / "config.yaml"
    home_config.parent.mkdir(parents=True)
    home_config.write_text("model: test/model\n", encoding="utf-8")
    extension_file = tmp_path / ".hermes" / "extensions" / "lm-studio" / "README.md"
    extension_file.parent.mkdir(parents=True)
    extension_file.write_text("local extension notes\n", encoding="utf-8")

    result = create_portable_runtime_backup(tmp_path)

    assert result["created"] is True
    assert result["files"] == 2
    assert result["included"] == [".hermes"]
    with zipfile.ZipFile(result["path"]) as archive:
        names = set(archive.namelist())
    assert ".hermes/config.yaml" in names
    assert ".hermes/extensions/lm-studio/README.md" in names


def test_create_portable_runtime_backup_includes_legacy_root_extensions(tmp_path):
    extension_file = tmp_path / "extensions" / "lm-studio" / "README.md"
    extension_file.parent.mkdir(parents=True)
    extension_file.write_text("legacy root extension notes\n", encoding="utf-8")

    result = create_portable_runtime_backup(tmp_path)

    assert result["created"] is True
    assert "extensions" in result["included"]
    with zipfile.ZipFile(result["path"]) as archive:
        names = set(archive.namelist())
    assert "extensions/lm-studio/README.md" in names


def test_create_portable_runtime_backup_skips_prior_backups(tmp_path):
    prior = tmp_path / ".hermes" / "backups" / "portable-runtime-old.zip"
    prior.parent.mkdir(parents=True)
    prior.write_text("old", encoding="utf-8")
    config = tmp_path / ".hermes" / "config.yaml"
    config.write_text("model: test/model\n", encoding="utf-8")

    result = create_portable_runtime_backup(tmp_path)

    assert result["created"] is True
    with zipfile.ZipFile(result["path"]) as archive:
        names = set(archive.namelist())
    assert ".hermes/config.yaml" in names
    assert ".hermes/backups/portable-runtime-old.zip" not in names


def test_create_portable_runtime_backup_does_not_overwrite_quick_repeated_runs(tmp_path):
    config = tmp_path / ".hermes" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("model: test/model\n", encoding="utf-8")

    first = create_portable_runtime_backup(tmp_path)
    second = create_portable_runtime_backup(tmp_path)

    assert first["created"] is True
    assert second["created"] is True
    assert first["path"] != second["path"]
    assert Path(first["path"]).is_file()
    assert Path(second["path"]).is_file()


def test_create_portable_runtime_backup_can_include_python_embedded(tmp_path):
    python_file = tmp_path / "python_embedded" / "python.exe"
    python_file.parent.mkdir(parents=True)
    python_file.write_text("fake", encoding="utf-8")

    result = create_portable_runtime_backup(tmp_path, include_python=True)

    assert result["created"] is True
    assert "python_embedded" in result["included"]
    with zipfile.ZipFile(result["path"]) as archive:
        names = set(archive.namelist())
    assert "python_embedded/python.exe" in names


def test_cmd_portable_does_not_mutate_yolo_env(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)

    args = SimpleNamespace(portable_action="env", root=tmp_path, shell="powershell")
    assert cmd_portable(args) == 0

    capsys.readouterr()
    assert "HERMES_YOLO_MODE" not in os.environ


def test_portable_parser_defaults_to_status():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    def handler(_args):
        return 0

    build_portable_parser(subparsers, cmd_portable=handler)
    args = parser.parse_args(["portable"])

    assert args.command == "portable"
    assert args.portable_action == "status"
    assert args.func is handler


def test_portable_parser_exposes_expected_actions():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    def handler(_args):
        return 0

    build_portable_parser(subparsers, cmd_portable=handler)
    portable_parser = subparsers.choices["portable"]
    portable_subparsers = next(
        action for action in portable_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert set(portable_subparsers.choices) == {
        "status",
        "env",
        "install-command",
        "desktop-command",
        "extensions",
        "backup",
        "migrate",
        "init",
    }


def test_portable_sources_do_not_register_tools_or_enable_yolo():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in PORTABLE_SOURCE_FILES)

    assert "registry.register" not in combined
    assert "HERMES_YOLO_MODE" not in combined
    assert "run_python" not in combined
    assert "tool_maker" not in combined
    assert "update_hermes" not in combined
