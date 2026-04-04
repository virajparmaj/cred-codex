# 07 — User Flows

## 1. First-time install

```
User runs: bash install.sh
  → python3 -m venv venv
  → pip install -e .
  → bash build_app.sh  (scales checked-in icon assets, builds `AppIcon.icns`/`AppIconRuntime.png`, writes C launcher + Info.plist)
  → ditto dist/CredCodex.app ~/Applications/CredCodex.app
  → launchd login item registered (com.local.credcodex)
  → open ~/Applications/CredCodex.app
App starts → PID lock acquired → logging initialized
  → startup timer fires (1s)
  → tries disk snapshot seed (must be < 600s old)
    → if seed succeeds: shows snapshot data with STALE state
    → else: calls live provider
      → reads ~/.codex/auth.json or Keychain
      → GET chatgpt.com/backend-api/codex/usage
      → renders result in menu bar title
```

## 2. Normal auto-refresh cycle

```
Every refresh_interval_sec (default 60s):
  _tick() fires
    → reloads config from disk (picks up settings changes)
    → CompositeLimitProvider.get_limit_info()
      → LiveCodexLimitProvider checks in-memory cache (55s TTL)
        → cache hit: returns cached result
        → cache miss: calls usage API
          → success: saves snapshot, updates cache, renders
          → 429: backed-off, falls back to stale cache / snapshot / session telemetry
          → 401/403: attempts token refresh, retries
          → transport error: falls back to stale cache / snapshot / session telemetry
    → _apply_limit(): updates title + dropdown visibility
    → checks for reset notification (previous reset time passed)
    → checks for auto re-auth trigger
```

## 3. Manual refresh from menu

```
User clicks "Refresh"
  → _refresh_now(sender) called
  → reloads config
  → CompositeLimitProvider.force_refresh()
    → clears in-memory cache TTL
    → calls live provider unconditionally
  → applies result to UI
```

## 4. Re-authentication (auto)

```
_apply_limit() detects failure_category in {AUTH_EXPIRED, UNSUPPORTED_AUTH_MODE}
  AND ReauthGate cooldown has expired (default 1800s since last attempt)
  → _trigger_reauth(auto=True)
    → ReauthGate.mark_attempt()
    → launch_codex_login():
        if `codex` CLI on PATH:
          osascript → Terminal → "codex login"
        else:
          webbrowser.open(auth docs URL)
    → sends macOS notification (once per unique result, deduped by lock file)
    → logs result
```

## 5. Re-authentication (manual)

```
User clicks "Re-authenticate" in dropdown
  → _reauth_now(sender)
  → _trigger_reauth(auto=False)  (same flow as auto, no cooldown check)
```

## 6. Opening settings

```
User clicks "Settings"
  → SettingsWindow.show(config, on_save_callback)
  → Singleton NSWindow appears (or raises if already open)
  → User adjusts toggles / interval fields
  → Window closes → _save_and_close()
    → sanitize_config() clamps values to valid ranges
    → save_config() writes ~/.credcodex/config.json
    → _on_settings_saved() callback:
        updates provider config
        resets refresh timer if interval or auto_refresh changed
```

## 7. Reset notification

```
On each _apply_limit():
  if previous.resets_at was in the past
  AND current.resets_at is new (window rolled over)
  AND lock file does not already contain this reset timestamp
    → send_notification("CredCodex reset available", ...)
    → write_lock(RESET_NOTIFICATION_LOCK, reset_at_iso)
```

## 8. Uninstall

```
User runs: bash uninstall.sh
  → stops and removes launchd login item
  → removes ~/Applications/CredCodex.app
  → ~/.credcodex/ is preserved (logs, config, snapshots)
```
