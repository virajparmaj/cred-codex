# 04 — Auth and Roles

## Auth status: exists (credential reader, not user auth)

CredCodex does not authenticate its own users. There are no accounts, sessions, or roles within the app itself. Instead, it reads and manages the **Codex CLI's existing local authentication** on behalf of the user.

## What auth means here

### Codex CLI credential loading (`limit_providers.py:load_auth_snapshot`)

1. Read `~/.codex/config.toml` to determine storage mode (`cli_auth_credentials_store`): `file`, `keyring`, or `auto`.
2. **File mode**: parse `~/.codex/auth.json` — contains `auth_mode`, `tokens.access_token`, `tokens.refresh_token`, `tokens.account_id`.
3. **Keyring mode**: invoke `security find-generic-password -s "Codex Auth" -a <account_key> -w` to retrieve the same JSON from the macOS Keychain.
4. **Auto mode** (default): try keychain first, fall back to file.

### Supported auth modes

| `auth_mode` | Behavior |
|---|---|
| `chatgpt` | Full support — uses bearer token + account ID for usage API |
| `api_key` | Unsupported — surfaces `UNSUPPORTED_AUTH_MODE` failure, shows `⚠ auth` in title |
| `None` / missing | Treated as expired / unauthenticated |

### Token refresh (`limit_providers.py:_refresh_auth_snapshot`)

- When the usage API returns 401/403, CredCodex attempts a silent token refresh.
- POST to `https://auth.openai.com/oauth/token` with `client_id = app_EMoamEEZ73f0CkXaXp7hrann` and the stored `refresh_token`.
- On success: persists new `access_token` (and optionally `refresh_token`, `id_token`) back to file or Keychain.
- On failure: backs off 300s (`AUTH_RETRY_COOLDOWN_SEC`), sets `AUTH_EXPIRED` failure category.

### Manual re-authentication (`auth_launcher.py:launch_codex_login`)

- Detected when `failure_category` is `AUTH_EXPIRED` or `UNSUPPORTED_AUTH_MODE`.
- If `codex` CLI is on PATH: opens Terminal via `osascript` and runs `codex login`.
- Fallback: opens `https://developers.openai.com/codex/auth` in the default browser.
- `ReauthGate` enforces a cooldown (default 1800s) to prevent repeated prompts.

## Roles

None. Single-user, local app. No RBAC, no multi-user concept.

## Security notes

- The `access_token` is used directly as a Bearer token to `chatgpt.com`. It is never logged (log calls use `exc` messages, not token values — `Confirmed from code`).
- Keychain account key is derived via SHA-256 of the resolved `CODEX_HOME` path (`config.py:compute_keyring_account_key`).
- The `client_id` (`app_EMoamEEZ73f0CkXaXp7hrann`) is the same public client used by the Codex CLI — `Strongly inferred` from the token refresh flow pattern.
