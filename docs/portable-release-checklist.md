# Portable update and release contract

There are two distinct update paths. Do not substitute one repository for the other:

- `UPDATE.bat` / `hermes update`: update the portable distribution from
  `aivrar/portable-hermes-agent`, including its GUI and launchers.
- Agent tool `update_hermes`: refresh the upstream core from
  `NousResearch/hermes-agent`, preserving portable-owned source and user state.

## Recorded regressions to keep covered

- [Issue #94](https://github.com/aivrar/portable-hermes-agent/issues/94): missing
  `hermes_gui.bat`. The release minimum must include every launcher.
- [Issue #96](https://github.com/aivrar/portable-hermes-agent/issues/96): missing
  `gui/`. Preserve the whole directory during upstream updates, not selected files.
- Portable README replaced by upstream README: retain portable branding, translated
  READMEs, manual, and portable release/download links.
- Custom tools and skills disappear after upstream refresh: preserve owned source
  and restore toolset registrations; verify real model-tool discovery.
- [Issue #56](https://github.com/aivrar/portable-hermes-agent/issues/56): antivirus
  flagged duplicated generated website documentation. Keep the intentional docs
  exclusions, without removing the runtime model-catalog asset or optional skills.
- Windows installer exits at an npm `.cmd` invocation or skips Tk setup: retain
  `call`, safe batch variable expansion, and the final embedded-runtime verification.
- [PR #110](https://github.com/aivrar/portable-hermes-agent/pull/110): exercise real
  language-switching widgets, saved preferences, status state and listener cleanup;
  one LM Studio connect click must start one connection, not two.
- PR #114: retain LM Studio settings under the active `HERMES_HOME` through
  both update paths; never bundle `.lmstudio_config`. Exercise authenticated
  model discovery and chat-key propagation, native metadata, key clearing,
  failed saves, profile isolation, and Tk responsiveness during network work.
- Live LM Studio verification after v1.4.7 exposed missing Windows logging
  dependencies after source-only upstream updates and contributor AGENTS.md
  filling the default local context window. Check real AIAgent construction,
  keep profile SOUL/project configuration, and do not report an upstream update
  complete until dependency installation and fresh-process agent imports pass.
- When a local LM Studio server is available, exercise the packaged GUI's real
  agent conversation, not just mock widgets or direct HTTP. Record its model,
  context size, authentication mode, response, and UI heartbeat. Restore only
  test-owned loaded models afterward; do not alter the user's security settings.

## Before publishing

1. Use a clean release checkout; never package an operator's local environment.
2. Run `scripts/run_tests.sh` for `tests/gui`, `tests/test_portable_gui.py`,
   `tests/test_build_release.py`, `tests/tools/test_update_hermes_tool.py`, and
   `tests/hermes_cli/test_update_zip*.py`. Use an existing development Python;
   this does not change the embedded Python used by the portable application.
3. Run real Tk widget tests on a machine with a display (or Xvfb). A skipped
   display test is not evidence that the GUI works.
   On Windows use `scripts/run_tests.sh tests/gui -j 1 --file-retries 0 --capture=sys`:
   pytest's default file-descriptor capture can interfere with Tcl file channels
   and produce misleading `init.tcl` read failures. Do not mask these with retries.
4. Check both source-update paths: upstream Git merge and ZIP overlay retain
   portable files; portable ZIP replacement delivers new GUI modules. Preserve
   user configuration, custom tools, language preferences, downloaded extensions,
   embedded Python, and built desktop binaries. Dependency installation and actual
   provider connections need their own validation when those paths change.
5. Add new owned files to the upstream preservation policy and release minimum.
   Whole owned trees protect future children; do not replace this with a partial
   GUI file allowlist. Tests enforce agreement between the two inventories.
6. Build with `build_release.py --version <tag> --output-dir <outside-checkout>`.
   It must fail on missing/unreadable sources or archive hash mismatches and must
   retain any prior good archive on failure. Never suppress those errors.
7. Verify the tag resolves to the reviewed, passing commit. Upload the verified
   `portable-hermes-agent-<tag>.zip`, not GitHub's automatic source archive.
   Download the published asset and compare SHA-256 with the local verified ZIP.
8. Check README and release-page download links, CI results, and release notes.
   Record test results and any untested boundaries; never claim all future upstream
   changes are guaranteed compatible.
