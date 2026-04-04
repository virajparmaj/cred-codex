# 08 — Pages and Routes

CredCodex is a native macOS menu bar app. There are no web pages or URL routes. The UI surfaces are:

---

## Menu bar title (status item)

| Surface | Purpose | Auth needed | Key source |
|---|---|---|---|
| Status bar title text | Shows utilization % + reset countdown (or error state) | Reads Codex local auth | `app.py:derive_title` |

States:
- `34% | 5h 0m` — healthy
- `⚠ auth` — auth expired or unsupported
- `⚠ wait` — rate limited
- `⏸ stale` — stale cached data
- `⏸ off` — offline

---

## Dropdown menu (rumps menu)

| Item | Visibility | Purpose |
|---|---|---|
| `Plan: <name>` | Hidden when `plan_name` and `plan_tier` both absent | Shows plan tier |
| `Weekly: ░░░ 74%` | Hidden when `weekly_utilization_pct` absent | Weekly usage bar |
| `  Resets: Apr 7, 2:30 PM` | Hidden when `weekly_resets_at` absent | Weekly reset time |
| `Credits: 12.5 credits` / `Credits: Unlimited` | Hidden when credits absent | Credits remaining |
| `Extra usage: ░░░ 12%` | Hidden when `extra_usage_enabled` falsy | Extra usage bar or dollar amounts |
| *(separator)* | Hidden when all info rows hidden | Visual separator |
| `Refresh` | Always visible | Triggers force refresh |
| `Re-authenticate` | Always visible | Launches `codex login` |
| `Settings` | Always visible | Opens settings window |
| `Quit` | Always visible | Quits the app |

`Confirmed from code — app.py:234-246`

---

## Settings window (NSWindow)

| Control | Purpose | Valid range |
|---|---|---|
| Auto-refresh toggle | Enable/disable periodic refresh | on/off |
| Refresh interval (sec) | How often to poll | 15–3600 |
| Auto re-authenticate toggle | Enable/disable auto re-auth | on/off |
| Re-auth cooldown (sec) | Min time between auto re-auth attempts | 30–86400 |
| Version label | Informational | — |
| Data source label | Shows current provider source string | — |
| View Logs button | Opens log file in default app | — |
| Reset to Defaults button | Resets all fields to defaults | — |

`Confirmed from code — settings.py`

---

## No web UI

`Not found in repository` — no HTML, CSS, JS, React, or web server of any kind.
