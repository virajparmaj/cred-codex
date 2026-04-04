# 09 — Dev Setup

## Requirements

- **macOS** (Apple Silicon or Intel) — PyObjC and rumps are macOS-only
- **Python 3.11+** (`requires-python = ">=3.11"` in `pyproject.toml`)
- **Xcode Command Line Tools** — needed for `cc`, `sips`, `iconutil`, `plutil` used by `build_app.sh`
- **Codex CLI** — must be installed and signed in for live limit data

## Install for production use

```bash
bash install.sh
```

This:
1. Creates `./venv`
2. `pip install -e .`
3. Runs `bash build_app.sh`
4. Copies app bundle to `~/Applications/CredCodex.app`
5. Registers `com.local.credcodex` launchd login item
6. Launches the app

## Run in development (no app bundle)

```bash
python3 -m venv venv
./venv/bin/pip install -e .
./venv/bin/python -m credcodex
```

This runs the full menu bar app in the current terminal session.

## Run tests

```bash
pip install pytest          # or: pip install -r requirements-dev.txt
pytest
```

No additional fixtures or env vars required. Tests use `tmp_path` and `monkeypatch` to isolate file paths. macOS UI paths (`rumps`, AppKit) are skipped (`# pragma: no cover`) when those imports fail.

## Environment variables (optional overrides)

| Variable | Default | Purpose |
|---|---|---|
| `CREDCODEX_USAGE_URL` | `https://chatgpt.com/backend-api/codex/usage` | Override usage API endpoint |
| `CREDCODEX_TOKEN_REFRESH_URL` | `https://auth.openai.com/oauth/token` | Override token refresh endpoint |
| `CODEX_HOME` | `~/.codex` | Override Codex CLI home directory |
| `CREDCODEX_REPO` | Embedded in C launcher at build time | Override repo path for app bundle launcher |

`Confirmed from code — limit_providers.py:33-37, config.py:26`

## No .env file

`Not found in repository` — CredCodex reads no `.env` file. All runtime secrets are sourced from the Codex CLI's own auth storage.

## Common setup pitfalls

- **`rumps` install on non-macOS fails silently** — the app stub raises `RuntimeError` at runtime rather than at import time. Unit tests work on any platform.
- **`sips`/`iconutil` not found** — `build_app.sh` will fail on non-macOS. Only needed for the app bundle; not needed for `python -m credcodex` dev mode.
- **Codex auth missing** — if `~/.codex/auth.json` does not exist and no Keychain entry is present, the app shows `⚠ auth` and prompts for `codex login`.
- **API-key-only Codex auth** — shows `⚠ auth` with `UNSUPPORTED_AUTH_MODE`; must re-sign-in with ChatGPT flow.

## Local runtime state

All persisted state lands in `~/.credcodex/`. Delete this directory to reset to a clean state (config, logs, snapshot, notification locks all removed).
