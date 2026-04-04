# 06 — API Contracts

CredCodex has no backend API of its own. It consumes two external OpenAI/ChatGPT endpoints.

---

## External: Codex usage endpoint

**URL**: `https://chatgpt.com/backend-api/codex/usage`
(overridable via `CREDCODEX_USAGE_URL` env var)
**Method**: `GET`

### Request headers (`limit_providers.py:_request_usage`)

```
Authorization: Bearer <access_token>
chatgpt-account-id: <account_id>
User-Agent: CredCodex/<version>
```

### Response shape (Strongly inferred from normalization code)

```json
{
  "plan_type": "plus",
  "rate_limit": {
    "primary_window": {
      "used_percent": 34.0,
      "limit_window_seconds": 18000,
      "reset_at": 1712345678
    },
    "secondary_window": {
      "used_percent": 74.0,
      "limit_window_seconds": 604800,
      "reset_at": 1712950000
    },
    "credits": {
      "balance": "12.5",
      "unlimited": false
    }
  },
  "credits": { ... }
}
```

Notes:
- `used_percent` can be a fraction (0.0–1.0) or a percentage (1.0–100.0) — normalized by `_normalize_utilization()`.
- Reset time can be Unix timestamp (int/float), ISO 8601 string, or relative `reset_after_seconds`.
- `secondary_window` is optional; only labeled "weekly" when `window_minutes ≈ 10080 ± 60`.
- `credits` may appear at root or nested inside `rate_limit`.

### Error handling

| HTTP status | Behavior |
|---|---|
| 429 | `_RateLimitedError` → stepped backoff (120/300/600s) |
| 401, 403 | `_AuthExpiredError` → attempt silent token refresh |
| Other 4xx/5xx | `_TransportError` → stale cache or offline state |
| Network error | `_TransportError` |

---

## External: OpenAI token refresh endpoint

**URL**: `https://auth.openai.com/oauth/token`
(overridable via `CREDCODEX_TOKEN_REFRESH_URL` env var)
**Method**: `POST`

### Request body (`limit_providers.py:_refresh_auth_snapshot`)

```json
{
  "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
  "grant_type": "refresh_token",
  "refresh_token": "<stored_refresh_token>"
}
```

### Response shape (Strongly inferred)

```json
{
  "access_token": "<new_access_token>",
  "refresh_token": "<new_or_same_refresh_token>",
  "id_token": "<optional_id_token>"
}
```

### Error handling

| HTTP status | Behavior |
|---|---|
| 400, 401, 403 | `_AuthExpiredError` — session truly expired |
| Other | `_TransportError` — transient failure |

---

## Internal: no API

CredCodex has no HTTP server, REST API, or IPC socket. All communication is via file I/O and macOS system calls.
