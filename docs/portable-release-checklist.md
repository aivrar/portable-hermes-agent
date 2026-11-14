# Portable update and release contract

Portable Hermes is a **wrapper** around the upstream Hermes core. The release
ZIP contains only wrapper-owned files; the core is installed from
`NousResearch/hermes-agent` at install time and updated on request.

One ownership model, `portable_hermes/ownership.py`, decides for every path
whether it is `user` (never written by any updater), `wrapper` (shipped in the
release, replaced only by the wrapper updater) or `core` (installed and
recorded by the core lifecycle). The release builder, installer, both
updaters, launch-time repair and the tests all read it.

There are two distinct update channels. Do not substitute one repository for
the other:

- **Wrapper**: `UPDATE.bat` / `hermes.bat update` step 1, or
  `portable_hermes wrapper update`. Installs the latest
  `aivrar/portable-hermes-agent` release asset, hash-checked against its
  `portable_hermes/release.json`, staged, verified, journaled and rolled back
  on failure. Never touches core or user paths.
- **Core**: `UPDATE.bat` step 2 (asks first), `UPDATE.bat --core`, the
  `update_hermes` agent tool, or `portable_hermes core update`. Fetches the
  upstream source ZIP (latest `main`, `--ref`, or `--zip`), installs its
  `uv.lock` dependencies hash-pinned, verifies in a fresh process, swaps with a
  journal, verifies again, and rolls files and packages back on failure.
  Records repo/ref/commit/files in `.portable/core-state.json`. A first install
  refuses a core without a usable `uv.lock` (and falls back to last-known-good);
  an update of an existing core may use the `pyproject.toml` ranges without
  hashes and reports that in its dependency line. Package changes are tracked
  in `.portable/deps-pending.json` until the new core commits or the previous
  set is verified back; while it exists, launchers print a note and the
  install shortcut that skips unchanged dependencies is disabled.
- **Portable Python**: `portable_hermes/manifests/python-runtime.txt` pins the
  embedded Python version for this release. When a core's `requires-python`
  needs a newer Python than `python_embedded` but the pin satisfies it, `core
  install/update` exits 4 and `portable_hermes/launch/runtime.cmd` upgrades in
  place: rename `python_embedded` to `python_embedded.old-<ver>`, run
  `install.bat --runtime-upgrade`, and on failure rename everything back. Old
  and failed runtime folders are user data and never deleted automatically.

Launch layout: the four root launchers are single-line trampolines into
`portable_hermes/launch/*.cmd` (`env.cmd` sets the shared environment,
`prepare.cmd` runs first-time or unfinished setup and settles an interrupted
update with the standalone `.portable/recover.py` before any portable Python
code is imported). `UPDATE.bat` is padded so that the v1.4.18 updater, which
resumes reading at a byte offset after replacing it, lands on a tail that asks
the user to run it again. Keep root launchers to one line plus that tail;
`tests/portable/test_portable_launchers.py` replays the v1.4.18 swap.

Upstream files are never edited. The portable tools register themselves with
upstream's registry; `portable_hermes/bridge.py` adds them to upstream's
default tool selection in memory, from a `.pth` hook in `python_embedded`.

## Recorded regressions to keep covered

- [Issue #94](https://github.com/aivrar/portable-hermes-agent/issues/94): missing
  `hermes_gui.bat`. The release minimum (`ownership.REQUIRED_RELEASE_FILES`)
  must include every launcher.
- [Issue #96](https://github.com/aivrar/portable-hermes-agent/issues/96): missing
  `gui/`. Wrapper trees are owned as whole trees, never as file allowlists.
- Portable README replaced by upstream README: `README*.md` are wrapper-owned;
  the core installer never writes them, and launch-time repair restores them
  (and every other wrapper file inside core directories) from
  `portable_hermes/payload/` after upstream's own `hermes update`.
- Custom tools and skills disappear after an upstream refresh: verification
  must prove, on real tool definitions, that the portable tools are registered,
  selected by the default CLI configuration and offered to a real
  `AIAgent(platform="gui")`.
- [Issue #56](https://github.com/aivrar/portable-hermes-agent/issues/56): antivirus
  flagged duplicated generated website documentation. The core installer skips
  generated docs (`ownership.is_core_installable`) but keeps the runtime
  model-catalog asset and optional skills.
- Windows installer exits at an npm `.cmd` invocation or skips Tk setup: retain
  `call`, safe batch variable expansion, the single `:fail` exit path and the
  final embedded-runtime verification. Upstream cores that are pnpm workspaces
  skip the npm step instead of failing.
- [PR #110](https://github.com/aivrar/portable-hermes-agent/pull/110): exercise real
  language-switching widgets, saved preferences, status state and listener cleanup;
  one LM Studio connect click must start one connection, not two.
- PR #114: retain LM Studio settings under the active `HERMES_HOME` through
  both update paths; never bundle `.lmstudio_config`. Exercise authenticated
  model discovery and chat-key propagation, native metadata, key clearing,
  failed saves, profile isolation, and Tk responsiveness during network work.
- Live LM Studio verification after v1.4.7 exposed missing Windows logging
  dependencies after source-only upstream updates. A core update is not complete
  until its dependencies are installed and the fresh-process verification
  (core imports, AIAgent, portable tools, CLI and GUI selection, GUI modules)
  passes; the core lifecycle enforces this.
- When a local LM Studio server is available, exercise the packaged GUI's real
  agent conversation, not just mock widgets or direct HTTP. Record its model,
  context size, authentication mode, response, and UI heartbeat. Restore only
  test-owned loaded models afterward; do not alter the user's security settings.
- Keep LM Studio's default loaded context at or above the core's minimum, and
  warn before loading a model whose reported maximum is below that floor.

## Before publishing

1. Use a clean release checkout; never package an operator's local environment.
   Every file in the release ZIP must be byte-identical to GitHub's archive of
   the same commit (`git archive`, no line-ending conversion). Installs updated
   from that archive (v1.4.18's updater downloads it) otherwise see different
   bytes, and the wrapper updater keeps unedited files as "your edits".
2. Run `scripts/run_tests.sh` for `tests/portable`, `tests/gui`,
   `tests/test_portable_gui.py`, `tests/test_build_release.py`,
   `tests/tools/test_update_hermes_tool.py`,
   `tests/tools/test_portable_dependency_refresh.py` and
   `tests/hermes_cli/test_update_zip*.py`. Use an existing development Python;
   this does not change the embedded Python used by the portable application.
3. Run real Tk widget tests on a machine with a display. A skipped display test
   is not evidence that the GUI works. On Windows use
   `scripts/run_tests.sh tests/gui -j 1 --file-retries 0 --capture=sys`:
   pytest's default file-descriptor capture can interfere with Tcl file channels.
   Do not mask failures with retries.
4. Run the real-upstream test against the upstream commit you intend to vouch
   for, with a Python version upstream supports (today 3.14):

   ```bash
   PORTABLE_REAL_UPSTREAM=1 PORTABLE_REAL_PYTHON=<python3.14.exe> \
     [PORTABLE_REAL_UPSTREAM_ZIP=<upstream.zip>] \
     <dev python> -m pytest tests/portable/test_portable_real_upstream.py -o addopts="" -q
   ```

   When it passes, add that commit to
   `portable_hermes/manifests/last-known-good.json` (with its Python range).
   A fresh install falls back to it if the newest upstream fails.
5. If you change the embedded Python version (`portable_hermes/manifests/python-runtime.txt`;
   `install.bat` reads it), check that the embed ZIP and `tcltk.msi` URLs exist
   for that version, and run one real runtime upgrade from an install made with
   the previous pin (`UPDATE.bat --yes --core` in a scratch copy).
   Optional real-pip check of package rollback with a loaded `.pyd`:
   `HERMES_PORTABLE_REAL_PIP=1 <dev python> -m pytest tests/portable/test_portable_real_pip.py -s -o addopts=""`
   (downloads two MarkupSafe wheels from PyPI).
6. New wrapper files: put them in a wrapper tree (`gui/`, `portable_hermes/`,
   the portable skill folders) or add them to `ownership.py`. Add bootable
   essentials to `REQUIRED_RELEASE_FILES`. Tests enforce that only wrapper
   files ship (plus `ownership.RELEASE_ONLY_FILES`: the root `LICENSE`, which
   no updater installs) and that the required files exist.
   The launch scripts `env.cmd`, `update-finish.cmd`, `runtime.cmd` and
   `install.bat` are an interface between wrapper versions (an older running
   `update.cmd` calls the newer copies): keep their variable names, file names
   and exit codes.
7. Build with `python build_release.py --version <tag> --output-dir <outside-checkout>`.
   It must fail on missing/unreadable sources or archive hash mismatches and must
   retain any prior good archive on failure. Never suppress those errors.
   Before writing the ZIP it compares every shipped file with `git archive HEAD`
   and stops on uncommitted changes or different bytes (usually line endings),
   naming the files. `--no-git-check` is only for a source that is not a git
   checkout; the release then records no source commit.
8. Do one real install from the built ZIP in a scratch folder (see "Scratch
   install" below), then one wrapper update from a second built ZIP and one core
   update. Check the GUI starts and lists the portable tools.
9. Verify the tag resolves to the reviewed, passing commit. Upload the verified
   `portable-hermes-agent-<tag>.zip`, not GitHub's automatic source archive (the
   wrapper updater rejects archives without `portable_hermes/release.json`).
   Download the published asset and compare SHA-256 with the local verified ZIP.
10. Check README and release-page download links, CI results, and release notes.
    Record test results and any untested boundaries; never claim all future
    upstream changes are guaranteed compatible.

## Scratch install, core update and wrapper update

Use a scratch Hermes home so the real one is not touched:

```bat
set HERMES_HOME=C:\scratch\hermes-home
set HERMES_PORTABLE_NONINTERACTIVE=1
cd C:\scratch\ph\portable-hermes-agent
install.bat --yes
:: optional pins: set HERMES_PORTABLE_CORE_REF=<branch|tag|commit>
::                set HERMES_PORTABLE_CORE_ZIP=C:\path\upstream.zip
hermes.bat update --yes --no-core --zip C:\path\portable-hermes-agent-vX.zip
hermes.bat update --yes --core
```

## Removing the in-repo core copy (follow-up)

This repository still tracks a copy of the fork-era core next to the wrapper.
Nothing in the wrapper uses it at runtime; it is kept until the wrapper model
has shipped. To remove it mechanically:

```bash
# every tracked path the ownership model classifies as "core"
python -c "import subprocess; from portable_hermes import ownership as o; \
paths = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, text=True).stdout.split('\0'); \
print('\n'.join(p for p in paths if p and o.classify(p) == 'core'))" > core-files.txt
# drop the developer files the wrapper repository still needs from the list
# (pyproject.toml and uv.lock for the test environment, scripts/run_tests.sh,
# tests/conftest.py and the portable tests, .github/workflows/portable-integrity.yml,
# LICENSE), then:
git rm -q --pathspec-from-file=core-files.txt
```

Tests that import core modules (the bridge proof, `tests/gui`, the tool tests)
then need a core: have CI install a pinned upstream commit first (the same
`portable_hermes core install --ref <commit>` the installer uses) and point
`PYTHONPATH` at it. The `tests/hermes_cli/test_update_zip*.py` files test the
fork-era core's own updater and are deleted with it.
