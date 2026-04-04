# 00 — Overview

## What is it?

CredCodex is a macOS-only, local-first menu bar app that monitors OpenAI Codex usage limits. It reads the same Codex credentials used by the official Codex CLI and displays live utilization and reset timing directly in the macOS status bar.

## Who it serves

Developers who use OpenAI Codex (the ChatGPT-backed agentic coding tool) and want a lightweight ambient indicator of how much of their limit window they have consumed — without switching to a browser dashboard.

## Primary problem solved

The Codex limit window is invisible by default. CredCodex surfaces utilization and reset time in one glance from the menu bar.

## Core user journey

1. User installs via `bash install.sh` — venv created, app bundle built, launchd login item registered, app launched.
2. On startup, CredCodex loads the user's local Codex auth from `~/.codex/auth.json` or macOS Keychain.
3. Every 60 seconds (configurable), it calls `https://chatgpt.com/backend-api/codex/usage` with the local ChatGPT bearer token.
4. The menu bar title shows `34% | 5h 0m` (utilization + countdown to reset).
5. Clicking the title opens a dropdown with optional plan, weekly usage, credits, and extra-usage rows.
6. When auth expires, the app auto-launches `codex login` in Terminal (with configurable cooldown).

## Current maturity

v0.1.0 — initial scaffold. All core provider, UI, config, notification, and re-auth paths are implemented and unit-tested. macOS UI paths (AppKit/rumps) are excluded from unit tests by design.

## Repo reality

| Feature | Status |
|---|---|
| Live Codex usage polling | Confirmed from code |
| Disk snapshot fallback | Confirmed from code |
| Local session telemetry fallback | Confirmed from code |
| Menu bar title + dropdown | Confirmed from code |
| Config UI (NSWindow settings panel) | Confirmed from code |
| Auto re-auth via `codex login` | Confirmed from code |
| macOS notifications (reset, re-auth) | Confirmed from code |
| launchd login item install/uninstall | Confirmed from code |
| App bundle with asset-driven macOS icon pipeline | Confirmed from code |
