# 12 — Roadmap

## Immediate fixes

- [ ] Add `codesign` call in `build_app.sh` (at minimum ad-hoc signing: `codesign --force --deep --sign -`) to prevent Gatekeeper quarantine on first launch.
- [ ] Add `KeepAlive = true` + crash detection in launchd plist, or document manual relaunch procedure.
- [ ] Fix `_normalize_utilization` edge case for `value == 1.0` (or confirm API never sends `1.0` as 100%).

## Short-term improvements

- [ ] Configurable notification thresholds (e.g., alert when utilization crosses 80%).
- [ ] Menu bar icon color change at high utilization (e.g., yellow at 80%, red at 95%).
- [ ] Integration test for `CompositeLimitProvider` covering all three fallback tiers end-to-end.
- [ ] Replace hardcoded coordinates in `SettingsWindow` with auto-layout or at minimum a layout constant dict.
- [ ] Document the `repo_root` fixture use case or remove it from `conftest.py`.

## Medium-term improvements

- [ ] Relocatable app bundle: write the repo path to a config file at install time rather than compiling it into the C binary.
- [ ] Usage history graph: persist utilization snapshots over time in a local SQLite or JSONL log; render a sparkline in the dropdown.
- [ ] Notification threshold preferences in the settings window.
- [ ] Multi-account support (multiple Codex accounts / CODEX_HOME paths).

## Long-term enhancements

- [ ] Distributable `.dmg` with proper code signing and notarization for distribution outside the repo.
- [ ] Auto-update check (compare `__version__` against a GitHub release tag).
- [ ] Optional Homebrew formula for `brew install credcodex`.

## Auth / infra hardening

- [ ] Audit token storage: ensure `access_token` is never written to log files (current behavior appears safe; a static analysis check would confirm).
- [ ] Add test coverage for `_refresh_auth_snapshot` Keychain path (currently only the file path is tested).
- [ ] Validate that `client_id` stays in sync with the Codex CLI's actual OAuth client.
