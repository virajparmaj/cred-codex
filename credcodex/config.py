"""Configuration, paths, and logging setup for CredCodex."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger("credcodex")

APP_NAME = "CredCodex"
BUNDLE_IDENTIFIER = "com.local.credcodex"
APP_DIR = Path.home() / ".credcodex"
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "credcodex.log"
SNAPSHOT_PATH = APP_DIR / "last_limit_snapshot.json"
KEEPALIVE_STATE_PATH = APP_DIR / "keepalive_state.json"
PID_PATH = APP_DIR / "monitor.pid"
NOTIFICATION_DIR = APP_DIR / "notifications"
RESET_NOTIFICATION_LOCK = NOTIFICATION_DIR / "last_reset_available.txt"
REAUTH_NOTIFICATION_LOCK = NOTIFICATION_DIR / "last_reauth_notice.txt"

CODEX_HOME = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
CODEX_CONFIG_PATH = CODEX_HOME / "config.toml"
CODEX_AUTH_PATH = CODEX_HOME / "auth.json"
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"

DEFAULT_REFRESH_INTERVAL_SEC = 60
DEFAULT_AUTO_REAUTH_COOLDOWN_SEC = 1800

DEFAULT_CONFIG: dict[str, object] = {
    "auto_refresh": True,
    "refresh_interval_sec": DEFAULT_REFRESH_INTERVAL_SEC,
    "auto_reauth_enabled": True,
    "auto_reauth_cooldown_sec": DEFAULT_AUTO_REAUTH_COOLDOWN_SEC,
    "keepalive_enabled": True,
    "keepalive_wake_system_enabled": False,
    "codex_bin": None,
}

REFRESH_INTERVAL_MIN_SEC = 15
REFRESH_INTERVAL_MAX_SEC = 3600
REAUTH_COOLDOWN_MIN_SEC = 30
REAUTH_COOLDOWN_MAX_SEC = 86400
MENU_OPEN_STALE_SEC = 30
STARTUP_SNAPSHOT_MAX_AGE_SEC = 600
IN_MEMORY_CACHE_TTL_SEC = 55
SESSION_TELEMETRY_STALE_SEC = 900
NOTIFICATION_CHECK_INTERVAL_SEC = 60


def ensure_app_dir() -> None:
    """Create the app support directory structure when missing."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    NOTIFICATION_DIR.mkdir(parents=True, exist_ok=True)


def clamp_refresh_interval(value: object) -> int:
    """Clamp refresh interval to a safe range."""
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_INTERVAL_SEC
    if parsed < REFRESH_INTERVAL_MIN_SEC or parsed > REFRESH_INTERVAL_MAX_SEC:
        return DEFAULT_REFRESH_INTERVAL_SEC
    return parsed


def clamp_reauth_cooldown(value: object) -> int:
    """Clamp re-auth cooldown to a safe range."""
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_AUTO_REAUTH_COOLDOWN_SEC
    if parsed < REAUTH_COOLDOWN_MIN_SEC or parsed > REAUTH_COOLDOWN_MAX_SEC:
        return DEFAULT_AUTO_REAUTH_COOLDOWN_SEC
    return parsed


def sanitize_codex_bin(value: object) -> str | None:
    """Normalize the optional `codex` binary override path.

    Returns the trimmed string when a non-empty path is provided, else None
    so the scheduler falls back to PATH-based auto-discovery.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def sanitize_config(raw: dict[str, object] | None) -> dict[str, object]:
    """Backfill defaults and normalize unsafe values."""
    cfg = DEFAULT_CONFIG.copy()
    if raw:
        cfg.update(raw)
    cfg["auto_refresh"] = bool(cfg.get("auto_refresh", True))
    cfg["refresh_interval_sec"] = clamp_refresh_interval(cfg.get("refresh_interval_sec"))
    cfg["auto_reauth_enabled"] = bool(cfg.get("auto_reauth_enabled", True))
    cfg["auto_reauth_cooldown_sec"] = clamp_reauth_cooldown(cfg.get("auto_reauth_cooldown_sec"))
    cfg["keepalive_enabled"] = bool(cfg.get("keepalive_enabled", True))
    cfg["keepalive_wake_system_enabled"] = bool(cfg.get("keepalive_wake_system_enabled", False))
    cfg["codex_bin"] = sanitize_codex_bin(cfg.get("codex_bin"))
    return cfg


def load_config() -> dict[str, object]:
    """Load persisted config, falling back to defaults on error."""
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    try:
        return sanitize_config(json.loads(CONFIG_PATH.read_text()))
    except Exception as exc:
        logger.warning("Failed to load config, using defaults: %s", exc)
        return DEFAULT_CONFIG.copy()


def save_config(config: dict[str, object]) -> dict[str, object]:
    """Persist sanitized config and return the normalized result."""
    ensure_app_dir()
    normalized = sanitize_config(config)
    CONFIG_PATH.write_text(json.dumps(normalized, indent=2, sort_keys=True))
    return normalized


def load_codex_cli_config() -> dict[str, object]:
    """Load local Codex CLI config when present."""
    if not CODEX_CONFIG_PATH.exists():
        return {}
    try:
        with CODEX_CONFIG_PATH.open("rb") as handle:
            loaded = tomllib.load(handle)
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        logger.debug("Failed to read Codex config: %s", exc)
        return {}


def codex_auth_storage_mode() -> str:
    """Return the configured Codex auth storage mode."""
    mode = load_codex_cli_config().get("cli_auth_credentials_store")
    if isinstance(mode, str) and mode.strip():
        return mode.strip().lower()
    return "auto"


def compute_keyring_account_key(codex_home: Path | None = None) -> str:
    """Compute the keyring account name used by Codex for this CODEX_HOME."""
    home = (codex_home or CODEX_HOME).expanduser()
    try:
        canonical = home.resolve()
    except Exception:
        canonical = home
    digest = hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()[:16]
    return f"cli|{digest}"


def setup_logging() -> None:
    """Configure rotating file logging for the package."""
    ensure_app_dir()
    root_logger = logging.getLogger("credcodex")
    root_logger.setLevel(logging.DEBUG)
    if any(isinstance(handler, RotatingFileHandler) for handler in root_logger.handlers):
        return

    file_handler = RotatingFileHandler(str(LOG_PATH), maxBytes=2_000_000, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root_logger.addHandler(file_handler)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(stderr_handler)
