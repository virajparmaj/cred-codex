# CredCodex Implementation Prompt

Paste the prompt below into Codex in a brand-new empty repository.

---

You are building `CredCodex` from scratch in this empty repository.

Your job is to implement a local macOS menu bar app that mirrors the current CredClaude architecture and UX for showing "limits remaining", but adapted for Codex/OpenAI. The result must be a local-first desktop utility, not a web app or cloud product.

## Product Goal

Build `CredCodex`, a macOS-only menu bar app that shows the user's current usage-limit utilization and reset timing at a glance, with a lightweight dropdown and native settings window. The app should feel like the existing CredClaude limits monitor, but the Codex/OpenAI-specific data source and re-auth details must be discovered safely and isolated behind the provider layer.

## Hard Constraints

- Do not build a web frontend.
- Do not build a backend service.
- Do not add a database.
- Do not add a React dashboard.
- Do not assume any cloud component is required unless you can prove a local desktop-only design is insufficient.
- Keep the architecture single-process and local-first.
- Scope is live limit monitoring only. Do not carry over CredClaude's spend/pricing/JSONL billing monitor into v1 unless you find a reliable Codex-specific local usage ledger and keep it clearly optional and cleanly separated from the core limit-monitor path.

## Architecture To Mirror

Mirror this architecture closely:

- Python app package named `credcodex`
- `rumps` for the menu bar shell
- AppKit/PyObjC native settings window
- local config, logs, PID lock, and snapshots only
- `.app` bundle packaging
- `launchd` auto-start via `install.sh`
- `uninstall.sh` to remove the app bundle and login item
- compiled launcher stub inside the `.app` so macOS gives the process a real app identity instead of showing `Python`

Keep the runtime local and resilient:

- delayed startup render after app launch
- on startup, attempt to seed UI from a recent disk snapshot before making a live provider call
- periodic background refresh on a safe default interval of 60 seconds
- manual refresh action that bypasses local retry cooldowns without breaking the long-lived backoff state
- lightweight menu-open staleness gate that refreshes only when the last refresh is at least 30 seconds old

Preserve the provider pipeline:

- live provider
- in-memory cache
- disk snapshot
- fallback provider or offline state

## Repository Shape

Create this project structure:

```text
pyproject.toml
README.md
requirements-dev.txt
build_app.sh
install.sh
uninstall.sh
credcodex/
  __init__.py
  __main__.py
  app.py
  models.py
  limit_providers.py
  config.py
  settings.py
  notifications.py
  auth_launcher.py
tests/
  __init__.py
  conftest.py
  test_app.py
  test_auth_launcher.py
  test_config.py
  test_limit_providers.py
```

You may add small supporting files only when necessary, but do not dissolve the required module boundaries above.

Use Python `3.11+`.

In `pyproject.toml`, declare the app as a normal installable Python package and include the runtime dependencies needed for:

- `rumps`
- PyObjC/AppKit access for the native settings window

Use `requirements-dev.txt` for test-only tooling such as `pytest`.

## Naming And Local Paths

Use `CredCodex` everywhere user-facing and packaging-related:

- app name: `CredCodex`
- Python package: `credcodex`
- app support directory: `~/.credcodex/`
- app bundle: `~/Applications/CredCodex.app`
- bundle identifier: `com.local.credcodex`
- log file under app support dir
- snapshot file under app support dir
- config file under app support dir

## Stable Interfaces To Lock In Up Front

Define and use these interfaces immediately. Do not let the app layer depend on provider-specific shapes.

### `Confidence`

Create an enum:

- `HIGH`
- `MEDIUM`
- `LOW`

### `ProviderState`

Create an enum:

- `HEALTHY`
- `DEGRADED`
- `STALE`
- `OFFLINE`

### `FailureCategory`

Create a normalized failure-category enum so the UI never branches on raw provider error text:

- `AUTH_EXPIRED`
- `RATE_LIMITED`
- `STALE_CACHED_DATA`
- `OFFLINE`

### `LimitInfo`

Create a dataclass named `LimitInfo` with normalized optional fields. Provider-specific data must become optional normalized fields rather than special-case dicts.

Include at least:

- `source: str`
- `confidence: Confidence`
- `state: ProviderState`
- `failure_category: FailureCategory | None`
- `error: str | None`
- `last_sync: datetime | None`
- `utilization_pct: float | None`
- `resets_at: datetime | None`
- `plan_name: str | None`
- `plan_tier: str | None`
- `weekly_utilization_pct: float | None`
- `weekly_resets_at: datetime | None`
- `extra_usage_enabled: bool | None`
- `extra_usage_monthly_limit: float | None`
- `extra_usage_used: float | None`
- `extra_usage_utilization: float | None`

All plan metadata, weekly fields, extra usage fields, and source labels must be truly optional. If Codex/OpenAI does not expose one of those concepts, keep the field `None` and hide the related menu section.

### `LimitProvider`

Create an abstract provider interface with:

- `get_limit_info() -> LimitInfo`
- `get_state() -> ProviderState`

### `CompositeLimitProvider`

Create `CompositeLimitProvider` as the app-facing orchestration entrypoint. It must:

- prefer the live provider
- use in-memory cache when fresh
- use disk snapshot when live fetch fails
- use fallback provider or offline state when nothing reliable is available
- expose a `force_refresh()` path for the menu action
- expose a startup snapshot-seeding path

## Provider Research Rules

You must investigate how Codex/OpenAI currently exposes usage/limit data and choose the safest documented local-first source. Keep that choice isolated inside `limit_providers.py`.

Allowed discovery paths:

- official API
- official OpenAI or Codex docs
- Codex/OpenAI CLI state
- local config or session files
- browser-authenticated local state
- another documented local-first source

Research rules:

- Prefer official/documented sources over reverse-engineered ones.
- Prefer local-first reads over building any server round-trip of your own.
- If multiple sources exist, choose the most stable documented source that can power a local menu bar app.
- If some fields are unavailable, omit them cleanly instead of fabricating them.
- If a source is only partially documented but clearly used by installed official tooling on the same machine, isolate that logic tightly and document the tradeoff in `README.md`.

Do not assume the following exist. Discover them, and degrade gracefully if they do not:

- a 5-hour-style reset window
- weekly limits
- extra paid usage or credits
- plan or tier metadata
- a direct equivalent of `claude auth login`

## Provider Behavior Requirements

Implement the provider layer so the rest of the app remains architecture-compatible even if the data source changes later.

Required provider behavior:

- use a short in-memory cache TTL of 55 seconds under the 60-second poll interval
- save successful live results to a disk snapshot
- treat startup snapshots as usable only when they are recent and not already expired
- use a 10-minute startup snapshot freshness cutoff
- discard expired primary reset windows from cache or snapshot
- normalize utilization to percentage form if the upstream source returns fractions
- normalize errors into the failure categories above

Required failure handling:

- auth expired
  - attempt a safe local re-auth or credential refresh path if the source supports it
  - if silent/local refresh fails, fall back cleanly and surface a normalized auth-expired state
- rate limited
  - apply local retry guard/backoff
  - default backoff progression: 120 seconds, 300 seconds, 600 seconds
- stale cached data
  - return last known usable data when possible
  - mark the result as stale/degraded instead of pretending it is fresh
- offline / transport failure
  - return snapshot or fallback provider output if available
  - otherwise return an offline `LimitInfo`

Manual refresh behavior:

- manual refresh must bypass the current retry guard
- manual refresh must not destroy the broader backoff progression logic
- if the source still fails, return the best available cached/snapshot/fallback result

## UI And UX Requirements

Implement a sparse menu bar UX modeled on CredClaude.

### Title Bar

The menu bar title should show:

- utilization percent plus reset countdown when both exist
- utilization percent only when reset time is unavailable
- a short degraded/offline/auth indicator when live utilization is unavailable

Keep the title clean. Do not show verbose stale/offline prose in the menu bar title.

### Dropdown Menu

The dropdown should contain:

- `Plan: ...` only when plan metadata exists
- weekly section only when weekly fields exist
- extra usage section only when extra usage exists and is enabled
- `Refresh`
- `Re-authenticate`
- `Settings`
- `Quit`

Hide optional info sections cleanly when data is unavailable. Avoid orphan separators or blank rows.

For the weekly section:

- show a compact bar plus percentage when weekly utilization exists
- show a reset line beneath it when weekly reset exists

For the extra usage section:

- show percentage when available
- otherwise show used vs limit if available
- otherwise show a simple enabled state

### Settings Window

Use a native AppKit/PyObjC settings window, not a webview and not chained `rumps` dialogs.

Include:

- auto-refresh toggle
- refresh interval control
- auto re-authenticate toggle
- auto re-auth cooldown control
- app version
- data source / status text
- view logs action
- reset to defaults action
- autosave behavior for settings

The settings window must remain lightweight and local.

## macOS Integrations

### Notifications

Implement macOS notifications with local dedupe locks.

At minimum:

- notify when a limit/reset window becomes available again, with dedupe so the same reset does not spam repeatedly
- notify on re-auth launch success or failure

Store dedupe locks locally under `~/.credcodex/`.

### Auth Launcher

Implement an `auth_launcher.py` module that handles re-auth launches cleanly and safely.

Requirements:

- isolate launch logic from provider logic
- support a manual menu-triggered re-auth flow
- support an auto re-auth cooldown gate
- prefer a local CLI login or browser/account flow if that is the documented Codex/OpenAI path
- never hardcode Claude-specific commands
- if the safest re-auth path is to open a browser/account page, do that
- if the safest re-auth path is to invoke a local CLI login, do that
- document the choice in `README.md`

### App Packaging

Implement:

- `build_app.sh` to build `CredCodex.app`
- `install.sh` to create a local venv, install dependencies, build the app, copy it to `~/Applications`, register a `launchd` login item, and launch it
- `uninstall.sh` to quit the app, unload/remove the `launchd` plist, and remove the app bundle while leaving local data behind unless the user chooses to delete it manually

Your shell scripts should validate the macOS tools they depend on before continuing. Account for tools such as:

- `python3`
- `launchctl`
- `osascript`
- `open`
- `ditto`
- `xattr`
- `sips`
- `iconutil`
- `cc`
- `plutil`

Use a compiled launcher stub inside the `.app` so macOS shows a real app identity. Do not rely on a bare shell wrapper alone.

## Entrypoint And Process Rules

In `credcodex/__main__.py`:

- configure logging before importing the app module
- create the app-support directory if needed
- acquire a single-instance PID lock using `fcntl.flock`
- exit cleanly if another instance is already running
- start the `CredCodex` app

## Config And Logging

In `config.py`:

- centralize app paths, defaults, and logging setup
- use rotating local log files
- validate config values on load
- backfill defaults
- clamp invalid refresh and cooldown values to safe ranges

Suggested defaults:

- `refresh_interval_sec = 60`
- `auto_refresh = true`
- `auto_reauth_enabled = true`
- `auto_reauth_cooldown_sec = 1800`

## Testing Requirements

Write tests that cover the architecture, not just trivial helpers.

Required tests:

- provider parsing and normalization for the chosen Codex/OpenAI source
- cache TTL behavior
- snapshot save/load round trips
- startup snapshot seeding
- expired snapshot rejection
- stale cached data fallback behavior
- offline fallback behavior
- manual refresh bypassing retry guard without flattening backoff logic
- optional menu sections hiding cleanly when fields are unavailable
- settings validation and persistence
- notification dedupe locks
- auth-launch helper behavior and cooldown gate
- single-instance PID lock behavior where practical
- install/build/uninstall script sanity at the level that can be tested locally

Make tests robust to the fact that some Codex/OpenAI fields may truly not exist. Test optional-field omission as a first-class behavior.

## README Requirements

Write a concise `README.md` that explains:

- what CredCodex is
- that it is macOS-only and local-first
- that it does not require a server or database
- what local data directory it uses
- which provider source you chose for Codex/OpenAI limit data
- how re-auth works
- what fields are shown only when the upstream source exposes them
- how to install, run, test, and uninstall the app
- current limitations or source caveats

## Acceptance Criteria

The implementation is only complete if all of the following are true:

- the app is a local macOS menu bar utility first, not a thin client for a cloud dashboard
- the menu remains useful when live reads fail
- provider-specific auth/source details are isolated behind `limit_providers.py` and `auth_launcher.py`
- no server, database, or React dashboard is required
- manual refresh works even during local cooldowns
- optional sections hide cleanly when Codex/OpenAI does not expose those fields
- the settings window is native, lightweight, and local
- the app packages into a usable `.app`
- install and uninstall flows are valid for local macOS usage
- tests cover the resilience and fallback paths, not just happy paths

## Implementation Notes

- Preserve the CredClaude architectural feel, but do not copy Claude-specific naming, endpoints, commands, or account assumptions into CredCodex.
- If you find a trustworthy Codex/OpenAI equivalent for plan, weekly, or extra usage data, surface it.
- If you do not find a trustworthy equivalent, leave the field out and keep the UI clean.
- Keep the app conservative, local, and robust.

Start implementing now in this empty repository.
