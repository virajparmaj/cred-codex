# 11 — Known Issues

## Critical

### App bundle is non-relocatable
`Confirmed from code — build_app.sh:175`
The C launcher embeds the absolute repo path at compile time (`@@REPO_DIR@@` substitution). Moving `~/Applications/CredCodex.app` to any other machine or directory breaks launch silently. Must rebuild with `install.sh` from the correct location.

### No code signing
`Confirmed from code — build_app.sh` (no `codesign` call)
Gatekeeper may quarantine the unsigned bundle. Users may need to explicitly allow it in System Settings or use `xattr -d com.apple.quarantine` manually.

## Medium

### `KeepAlive = false` in launchd plist
`Confirmed from code — install.sh`
If the app crashes, launchd will not restart it. The user must manually reopen the app or re-run `install.sh`.

### Hardcoded pixel coordinates in settings window
`Confirmed from code — settings.py`
The `NSWindow` layout uses absolute `NSMakeRect` coordinates. The window cannot be resized. Any future settings additions require manual coordinate recalculation.

### `_normalize_utilization` heuristic for fraction vs. percent
`Confirmed from code — limit_providers.py:49-56`
Values ≤ 1.0 are multiplied by 100; values > 1.0 are used as-is. A value of exactly `1.0` is treated as 1%, not 100%. If the API ever sends `1.0` meaning 100%, this will render as 1%.

### Weekly window detection is heuristic
`Confirmed from code — limit_providers.py:_is_weekly_window`
A secondary window is labeled "weekly" only if its duration is within ±60 minutes of 10080 minutes. Non-standard Codex billing cycles will not be labeled correctly.

### `should_notify_once` compares only the lock value string
`Confirmed from code — notifications.py:82-84`
If a user quits and relaunches, the lock file persists, so duplicate reset notifications are correctly suppressed. However, if `~/.credcodex/notifications/` is deleted mid-session, the same notification fires again.

### No retry on `_TransportError` after token refresh
`Confirmed from code — limit_providers.py:743-754`
Transport errors after a successful token refresh fall back to stale cache without reattempting the usage request with the new token.

## Low

### Notification dedup locks never automatically remove for old entries
`Confirmed from code — notifications.py:cleanup_notification_locks`
Only `*.txt` files older than 30 days are removed. Lock files accumulate until cleanup runs.

### Test coverage of macOS UI paths is zero
`Confirmed from code — app.py:39, settings.py:28` (`# pragma: no cover`)
`CredCodexApp` and `SettingsWindow` are entirely excluded from unit tests. UI bugs cannot be caught by the test suite.

### No test for `install.sh` / `uninstall.sh` / `build_app.sh`
`Not found in repository` — shell scripts have no automated tests. A broken build script would only be caught manually.

### Single `conftest.py` fixture (`repo_root`) not used by any test currently
`Confirmed from code — tests/conftest.py:10-12`
The `repo_root` fixture is defined but not referenced in `test_app.py`, `test_limit_providers.py`, or `test_config.py` (based on visible test content).
