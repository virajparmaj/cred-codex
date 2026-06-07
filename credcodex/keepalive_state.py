"""Persistent state for the keepalive scheduler.

Stores `last_fired_at`, `last_status`, and `scheduled_fire_at` so the
scheduler can detect missed firings across sleep/wake and app restarts.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

logger = logging.getLogger("credcodex.keepalive_state")

_VALID_STATUSES = ("ok", "failed", "skipped")


@dataclass(frozen=True)
class KeepaliveState:
    last_fired_at: datetime.datetime | None = None
    last_status: str | None = None
    scheduled_fire_at: datetime.datetime | None = None

    def with_fired(
        self, fired_at: datetime.datetime, status: str
    ) -> "KeepaliveState":
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid keepalive status: {status!r}")
        return replace(self, last_fired_at=fired_at, last_status=status)

    def with_scheduled(
        self, scheduled_fire_at: datetime.datetime | None
    ) -> "KeepaliveState":
        return replace(self, scheduled_fire_at=scheduled_fire_at)


def _parse_dt(value: object) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def load_state(path: Path) -> KeepaliveState:
    """Load state from disk, returning an empty state if missing or corrupt."""
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return KeepaliveState()
    except OSError as exc:
        logger.warning("Could not read keepalive state %s: %s", path, exc)
        return KeepaliveState()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Corrupt keepalive state %s: %s", path, exc)
        return KeepaliveState()
    if not isinstance(data, dict):
        logger.warning("Keepalive state %s is not an object; ignoring.", path)
        return KeepaliveState()

    status = data.get("last_status")
    if status not in _VALID_STATUSES:
        status = None

    return KeepaliveState(
        last_fired_at=_parse_dt(data.get("last_fired_at")),
        last_status=status,
        scheduled_fire_at=_parse_dt(data.get("scheduled_fire_at")),
    )


def save_state(path: Path, state: KeepaliveState) -> None:
    """Persist state atomically via os.replace on a sibling tmp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_fired_at": state.last_fired_at.isoformat() if state.last_fired_at else None,
        "last_status": state.last_status,
        "scheduled_fire_at": (
            state.scheduled_fire_at.isoformat() if state.scheduled_fire_at else None
        ),
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".keepalive_state_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
