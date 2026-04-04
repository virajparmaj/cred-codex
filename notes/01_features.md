# 01 — Features

## Confirmed implemented

### Menu bar display (`credcodex/app.py`)
- Status bar title shows `{utilization}% | {countdown}` when live data is available.
- Falls back to `⚠ auth`, `⚠ wait`, `⏸ stale`, `⏸ off` for error/degraded states.
- Unicode progress bars (`make_bar`) for utilization.

### Provider pipeline (`credcodex/limit_providers.py`)
- **Live provider**: calls `https://chatgpt.com/backend-api/codex/usage` with ChatGPT bearer token + account ID.
- **In-memory cache**: 55-second TTL (`IN_MEMORY_CACHE_TTL_SEC`).
- **Disk snapshot**: saves last healthy result to `~/.credcodex/last_limit_snapshot.json`; loaded on startup if < 600s old.
- **Local session telemetry fallback**: scans `~/.codex/sessions/*.jsonl` for `token_count` events when live + snapshot fail.
- Composite orchestration via `CompositeLimitProvider` with explicit fallback priority.

### Token refresh (`credcodex/limit_providers.py:_refresh_auth_snapshot`)
- Auto-refreshes expired access tokens via `https://auth.openai.com/oauth/token`.
- Persists refreshed tokens back to file or Keychain.
- Backs off for 300s after failed refresh.

### Rate-limit backoff (`credcodex/limit_providers.py`)
- Stepped backoff: 120s → 300s → 600s on repeated 429 responses.

### Config (`credcodex/config.py`, `credcodex/settings.py`)
- Persisted JSON config at `~/.credcodex/config.json`.
- `auto_refresh` toggle, `refresh_interval_sec` (15–3600), `auto_reauth_enabled`, `auto_reauth_cooldown_sec` (30–86400).
- Native settings window (`NSWindow`) with toggle switches and text inputs.
- "View Logs" and "Reset to Defaults" buttons.

### Re-auth (`credcodex/auth_launcher.py`)
- Manual re-auth from dropdown menu.
- Auto re-auth when auth error detected, with cooldown gate (default 30 min).
- Launches `codex login` via `osascript`; falls back to opening auth docs in browser when `codex` CLI not found.

### Notifications (`credcodex/notifications.py`)
- macOS system notification when the primary limit window resets.
- macOS notification on re-auth launch (success or failure).
- Dedup via lock files in `~/.credcodex/notifications/` to avoid repeated alerts.
- Auto-cleanup of lock files older than 30 days.

### Single-instance lock (`credcodex/__main__.py`)
- `fcntl.flock` on `~/.credcodex/monitor.pid` prevents duplicate processes.

### Install / uninstall (`install.sh`, `uninstall.sh` mentioned in README)
- `install.sh`: venv creation, pip install, `build_app.sh`, copy to `~/Applications/`, launchd login item.
- `uninstall.sh`: removes app bundle and login item; leaves `~/.credcodex/` intact.

### App bundle (`build_app.sh`)
- Builds `dist/CredCodex.app` with C launcher, Info.plist, bundled `AppIcon.icns`, and bundled `AppIconRuntime.png`.
- Icon assets are checked into `assets/`, then scaled and normalized with `sips` + `iconutil` during the build.

## Partially implemented

- **Extra usage display**: Renders `extra_usage_*` fields when the upstream API exposes them, but the upstream source for those fields isn't fully specified in comments. Confirmed from code: fields are normalized and rendered; no integration test confirms upstream exposure.
- **Weekly window detection**: `_is_weekly_window` tolerates ±60 min from 10080 min — covers most weekly cadences but is heuristic. `Strongly inferred` to work for standard Codex Plus plans.

## Not implemented but implied

- No Keychain write UI — users cannot set the Keychain entry via CredCodex; it must be created by the Codex CLI.
- No telemetry or usage history graphing beyond the current window.

## Nice-to-have / future

- Historical usage chart.
- Multi-account support.
- Notification threshold customization (e.g., alert at 80%).
- Menu bar icon color/badge changes based on utilization level.
