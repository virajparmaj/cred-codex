# 03 — Architecture

## Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.11+ |
| Menu bar framework | `rumps` ≥ 0.4.0 |
| Native macOS UI | `pyobjc-core` + `pyobjc-framework-Cocoa` ≥ 10.3 |
| HTTP | stdlib `urllib.request` (no third-party HTTP lib) |
| Config serialization | stdlib `json`, `tomllib` |
| App bundle launcher | C binary compiled by `build_app.sh` |
| Install/deploy | Bash scripts + launchd `LaunchAgent` |
| Tests | `pytest` |

## Module map

```
credcodex/
  __init__.py          # version constant
  __main__.py          # process entrypoint, PID lock
  app.py               # CredCodexApp (rumps.App), pure render helpers
  auth_launcher.py     # ReauthGate, launch_codex_login()
  config.py            # paths, constants, config load/save, Codex CLI config
  limit_providers.py   # provider pipeline (Live, LocalSession, Composite)
  models.py            # LimitInfo dataclass, Confidence/ProviderState/FailureCategory enums
  notifications.py     # macOS notifications via AppleScript, dedup locks
  settings.py          # SettingsWindow (NSWindow native panel)
```

## Data / state flow

```
  ~/.codex/auth.json          ~/.codex/sessions/*.jsonl
        │                              │
        ▼                              ▼
 LiveCodexLimitProvider     LocalSessionLimitProvider
  (HTTPS to chatgpt.com)    (JSONL scan for token_count)
        │                              │
        └──────────┬───────────────────┘
                   ▼
        ~/.credcodex/last_limit_snapshot.json
                   │
                   ▼
          CompositeLimitProvider
          (fallback merge logic)
                   │
                   ▼
            CredCodexApp
          (rumps timer tick)
                   │
                   ▼
           macOS status bar title + dropdown
```

## Fallback priority (Confirmed from code — `limit_providers.py:_merge_fallbacks`)

1. Live HTTPS result with `has_live_utilization == True`
2. Disk snapshot (`~/.credcodex/last_limit_snapshot.json`) — not expired, not > 600s old at startup
3. Local session telemetry (`~/.codex/sessions/*.jsonl`) — most recent `token_count` event
4. Bare `_offline_limit_info` with error state

## Timers (`app.py`)

- `_startup_timer`: fires once after 1s, attempts snapshot seed, else calls `_update()`.
- `_refresh_timer`: periodic tick at `refresh_interval_sec` (default 60s), calls `_tick()`.
- `_MenuDelegate.menuWillOpen_`: triggers refresh if menu was last refreshed > 30s ago.

## Process lifecycle

- Single-instance enforced via `fcntl.flock` on `~/.credcodex/monitor.pid`.
- Launched by macOS `open` via launchd `LaunchAgent` (`com.local.credcodex`).
- App bundle has a compiled C launcher (`CredCodex` binary) that `execv`s `venv/bin/python -m credcodex`.

## External services

| Service | URL | Purpose |
|---|---|---|
| Codex usage endpoint | `https://chatgpt.com/backend-api/codex/usage` | Live limit data |
| OpenAI token refresh | `https://auth.openai.com/oauth/token` | Access token renewal |
| Codex auth docs (fallback) | `https://developers.openai.com/codex/auth` | Opened in browser when `codex` CLI missing |

Both URLs are overridable via env vars `CREDCODEX_USAGE_URL` and `CREDCODEX_TOKEN_REFRESH_URL`. `Confirmed from code — limit_providers.py:33-37`.

## Local storage

| Path | Purpose |
|---|---|
| `~/.credcodex/config.json` | User preferences |
| `~/.credcodex/credcodex.log` | Rotating log (2 MB × 3 backups) |
| `~/.credcodex/last_limit_snapshot.json` | Last healthy live result |
| `~/.credcodex/monitor.pid` | Single-instance lock |
| `~/.credcodex/notifications/*.txt` | Notification dedup locks |
| `~/.codex/auth.json` | Codex CLI auth (read-only by CredCodex in file mode) |
| `~/.codex/sessions/*.jsonl` | Codex session telemetry (read-only) |

## No database, no network server, no web frontend

`Confirmed from code` — entirely local.
