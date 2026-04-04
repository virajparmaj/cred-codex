# 13 — Prompt Context

Use this file to orient future AI agents working on CredCodex.

---

## What this app is

A **macOS-only, local-first menu bar app** written in Python. It reads the user's local OpenAI Codex CLI credentials and displays live usage/limit data in the macOS status bar. There is no web frontend, no database, no backend server, and no network listener of any kind.

## Stack

- Python 3.11+, `rumps` (menu bar), `pyobjc` (native AppKit/Cocoa)
- stdlib only for HTTP (`urllib.request`) and JSON
- `pytest` for tests
- Bash scripts for build/install/uninstall
- C launcher inside the `.app` bundle (single file, compiled by `build_app.sh`)

## Architecture guardrails

- **Never add a network server or web frontend** — this is intentionally a zero-server, local-only tool.
- **Never add a database** — all state lives in flat files under `~/.credcodex/`.
- **All `LimitInfo` mutations must use `.with_overrides()`**, not direct field assignment. `LimitInfo` has this helper; use it.
- **UI paths require macOS** — any code that imports `rumps`, `objc`, or `AppKit` must be guarded with `try/except` and `# pragma: no cover` stubs for non-macOS test environments.
- **Provider changes must preserve the 3-tier fallback** — live → disk snapshot → local session telemetry. Don't short-circuit this chain.
- **Config values must always pass through `sanitize_config()`** before being persisted or used to drive timers.

## Design rules

- Status bar title must remain compact: `{pct}% | {countdown}` or a short `⚠`/`⏸` prefix label.
- Dropdown rows must be hidden (not shown as blank) when the upstream API doesn't expose the corresponding field.
- Progress bars use the `make_bar()` function in `app.py` — do not inline bar rendering elsewhere.
- Settings window auto-saves on close; no explicit Save button.

## Behaviors to preserve

- Single-instance enforcement via `fcntl.flock` on `monitor.pid`.
- Notification dedup via lock files — never send the same notification twice for the same event value.
- Rate-limit backoff: stepped (120 → 300 → 600s) on 429 responses.
- `force_refresh()` must bypass the in-memory cache TTL.
- Startup snapshot seed: load disk snapshot only if < 600s old.

## Weak points to watch

- `_normalize_utilization`: values exactly equal to 1.0 are treated as 1%, not 100%.
- `_is_weekly_window`: heuristic tolerance of ±60 min around 10080 min. Not robust for unusual billing cycles.
- The C launcher embeds the repo path at compile time — any path changes require a rebuild.
- AppKit UI code has zero unit test coverage by design. Regressions here are invisible to CI.
- `_refresh_auth_snapshot` Keychain path is lightly tested.

## Editing expectations

- Keep files small and focused — each module has a clear single responsibility.
- When adding config keys: add to `DEFAULT_CONFIG`, add validation in `sanitize_config()`, and document in `09_dev_setup.md`.
- When adding provider fallbacks: add to `CompositeLimitProvider._merge_fallbacks()`, not inline in `_get_limit_info()`.
- When adding menu items: update `_set_info_visibility()` to handle their hidden/shown state.
- Run `pytest` after any change to the non-UI modules.
