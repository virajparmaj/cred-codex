"""macOS notification helpers and local dedupe locks."""

from __future__ import annotations

import datetime as dt
import json
import logging
import subprocess
import time
from pathlib import Path

from credcodex.config import NOTIFICATION_DIR

logger = logging.getLogger("credcodex.notifications")


def send_notification(title: str, message: str) -> None:
    """Send a macOS notification via AppleScript."""
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{safe_message}" with title "{safe_title}" sound name "Glass"',
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        logger.warning("Failed to send notification: %s", exc)


def read_lock(path: Path) -> str:
    """Return the current lock value, or an empty string when missing."""
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        return ""


def write_lock(path: Path, value: str) -> None:
    """Persist a lock payload locally."""
    NOTIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"value": value, "written_at": time.time()}
    path.write_text(json.dumps(payload))


def read_lock_value(path: Path) -> str:
    """Read a JSON lock payload and return its value."""
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return ""
    except Exception:
        return read_lock(path)
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, str):
            return value
    return ""


def lock_age_seconds(path: Path) -> float | None:
    """Return the age of a lock file in seconds, when present."""
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except Exception:
        return None
    written_at = payload.get("written_at")
    if not isinstance(written_at, (int, float)):
        return None
    return max(0.0, time.time() - float(written_at))


def should_notify_once(path: Path, value: str) -> bool:
    """Return True when a new notification should be emitted for the value."""
    return read_lock_value(path) != value


def cleanup_notification_locks(days: int = 30, base_dir: Path | None = None) -> None:
    """Delete notification lock files older than the requested age."""
    target = base_dir or NOTIFICATION_DIR
    if not target.exists():
        return
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    for path in target.glob("*.txt"):
        try:
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
            if modified < cutoff:
                path.unlink()
        except OSError as exc:
            logger.debug("Skipping lock cleanup for %s: %s", path, exc)
