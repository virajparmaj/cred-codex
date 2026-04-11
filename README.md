# CredCodex

<p align="center">
  <img src="assets/credcodex_logo.png" alt="CredCodex" width="120">
</p>

CredCodex is a local macOS menu bar app that keeps your Codex usage limits, reset timers, and auth state visible without living in a browser tab.

## App Preview

<!-- Screenshots pending -->
<table>
  <tr>
    <td><sub>Fresh screenshots are pending for the current build.</sub></td>
  </tr>
</table>

## What You Can Do With It

- See your current usage at a glance in the menu bar, including the current utilization percentage and time remaining until the next reset when that data is available.
- Open the dropdown for richer account details such as your plan, weekly usage progress, weekly reset time, credits balance, and extra usage when your account exposes them.
- Refresh on a timer or on demand from the menu, with settings for auto-refresh, refresh interval, auto re-authentication, and re-auth cooldown.
- Recover more gracefully when live usage data is unavailable by falling back to recent saved data and local Codex session telemetry instead of going blank immediately.
- Re-authenticate quickly from the menu when your Codex session expires. CredCodex opens `codex login` in Terminal when it can, and falls back to the official auth docs when the CLI is unavailable.
- Get native macOS notifications when a limit window appears to reset and when CredCodex completes a re-auth launch attempt.
- Open logs, keep settings local, and run the app without sending data through a separate hosted service.

> Live monitoring depends on a ChatGPT-authenticated Codex session. API-key-only auth does not expose the same limit data, so CredCodex reports that mode as unsupported instead of guessing.

## Install / Getting Started

CredCodex is for macOS users who already use Codex locally and want a lightweight menu bar view of their current limit state.

Requires:

- macOS
- Python 3.11 or later

Install with:

```bash
bash install.sh
```

The installer will:

1. Create a local virtual environment in `./venv`
2. Install CredCodex into that environment
3. Build `CredCodex.app`
4. Copy the app to `~/Applications/CredCodex.app`
5. Register a `launchd` login item
6. Launch the app immediately

After install, CredCodex appears in the menu bar. Open the menu to refresh manually, trigger re-authentication, or open **Settings**.

Uninstall with:

```bash
bash uninstall.sh
```

That removes the app bundle and login item. Local data in `~/.credcodex/` is left in place so you can inspect logs or delete it yourself later.

## Developer Install / Local Setup

Clone the repo and run the app locally:

```bash
git clone <repo-url>
cd cred-codex

python3 -m venv venv
./venv/bin/pip install -e .
./venv/bin/python -m credcodex
```

Install test dependencies and run tests:

```bash
./venv/bin/pip install -r requirements-dev.txt
pytest
```

Build the macOS app bundle:

```bash
bash build_app.sh
```

Helpful local paths:

- Runtime data: `~/.credcodex/`
- Config: `~/.credcodex/config.json`
- Logs: `~/.credcodex/credcodex.log`
- Snapshot cache: `~/.credcodex/last_limit_snapshot.json`

The app is macOS-only and depends on native tooling used by the install and build scripts, including `launchctl`, `osascript`, `open`, `sips`, `iconutil`, `plutil`, and `cc`.
