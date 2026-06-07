"""Scheduler for sending a small Codex keepalive ping after session reset.

Persists its state to disk so it can detect missed firings after sleep or
app restart, and optionally schedules a `pmset` system wake so the Mac can
wake from sleep at reset time.
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

from credcodex.keepalive_state import KeepaliveState, load_state, save_state

logger = logging.getLogger("credcodex.keepalive")

_DEFAULT_BUFFER_SEC = 10
_DEFAULT_PING_TIMEOUT_SEC = 60
_DEFAULT_CATCH_UP_WINDOW_SEC = 7200  # 2 hours
_WAKE_DEBOUNCE_SEC = 5
_PMSET_PATH = "/usr/bin/pmset"
_SUDO_PATH = "/usr/bin/sudo"

# Minimal, non-interactive Codex invocation used for the keepalive ping.
# `codex exec` runs Codex non-interactively and exits 0 when it completes;
# `--skip-git-repo-check` lets it run from any working directory, and the
# read-only sandbox avoids any approval prompts for a prompt that only needs
# to register usage against the account.
_PING_ARGS = ("exec", "--skip-git-repo-check", "--sandbox", "read-only")
_PING_PROMPT = "ping"


def _fallback_path_dirs() -> list[str]:
    """Common install locations for the `codex` CLI on macOS.

    GUI-launched apps inherit a minimal PATH that excludes per-user dirs like
    ``~/.local/bin``, so we probe these explicitly when ``shutil.which`` fails.
    """
    home = Path.home()
    return [
        str(home / ".local" / "bin"),
        str(home / ".npm-global" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(home / ".volta" / "bin"),
    ]


class KeepaliveScheduler:
    """Schedule a post-reset ping so the next usage window starts promptly."""

    def __init__(
        self,
        buffer_sec: int = _DEFAULT_BUFFER_SEC,
        ping_timeout_sec: int = _DEFAULT_PING_TIMEOUT_SEC,
        state_path: Path | None = None,
        catch_up_window_sec: int = _DEFAULT_CATCH_UP_WINDOW_SEC,
    ) -> None:
        self._buffer_sec = int(buffer_sec)
        self._ping_timeout_sec = int(ping_timeout_sec)
        self._catch_up_window_sec = int(catch_up_window_sec)
        self._state_path = state_path
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._timer_generation = 0
        self._last_wake_at: datetime.datetime | None = None
        self._wake_system_enabled = False
        self._last_wake_scheduled: datetime.datetime | None = None
        self._codex_bin: str | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def set_wake_system_enabled(self, enabled: bool) -> None:
        """Enable/disable pmset system-wake scheduling (Tier 2)."""
        self._wake_system_enabled = bool(enabled)

    def set_codex_bin(self, codex_bin: str | None) -> None:
        """Configure an explicit absolute path to the `codex` binary.

        ``None`` (default) falls back to auto-discovery via PATH and common
        per-user install dirs. Set this when the binary lives in a location
        the GUI-app PATH doesn't include.
        """
        if codex_bin is None or not str(codex_bin).strip():
            self._codex_bin = None
        else:
            self._codex_bin = str(codex_bin).strip()

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    def schedule(self, resets_at: datetime.datetime | None) -> bool:
        """Schedule a keepalive ping shortly after ``resets_at``.

        Persists the planned fire time and, if enabled, schedules a pmset
        system wake a few seconds before the ping so the Mac is awake when
        the timer fires.
        """
        if resets_at is None:
            return False

        reset_time = resets_at.astimezone()
        now = datetime.datetime.now().astimezone()
        if reset_time <= now:
            logger.debug("Skipping keepalive schedule for past reset time: %s", resets_at)
            return False
        fire_at = reset_time + datetime.timedelta(seconds=self._buffer_sec)
        delay_sec = (fire_at - now).total_seconds()

        with self._lock:
            old_timer = self._timer
            self._timer_generation += 1
            generation = self._timer_generation
            timer = threading.Timer(delay_sec, self._run_scheduled_ping, args=(generation,))
            timer.daemon = True
            self._timer = timer

        if old_timer is not None:
            old_timer.cancel()

        timer.start()
        self._persist_scheduled(fire_at)
        self._maybe_schedule_system_wake(fire_at)
        logger.info("Scheduled keepalive ping in %.1fs for %s", delay_sec, fire_at.isoformat())
        return True

    def cancel(self) -> None:
        """Cancel any pending keepalive ping and clear the persisted schedule."""
        with self._lock:
            timer = self._timer
            self._timer = None
            self._timer_generation += 1
        if timer is not None:
            timer.cancel()
        self._persist_scheduled(None)
        self._cancel_system_wake()

    # ------------------------------------------------------------------
    # Sleep/wake handling
    # ------------------------------------------------------------------
    def handle_wake(self, resets_at: datetime.datetime | None) -> None:
        """Called when the system wakes from sleep.

        Catches up any missed ping and re-schedules against the latest
        known reset time. Debounces duplicate wake events that some macOS
        versions emit back-to-back.
        """
        now = datetime.datetime.now().astimezone()
        if self._last_wake_at is not None:
            delta = (now - self._last_wake_at).total_seconds()
            if 0 <= delta < _WAKE_DEBOUNCE_SEC:
                logger.debug("Ignoring duplicate wake event (%.1fs since last).", delta)
                return
        self._last_wake_at = now

        self.catch_up_if_needed(resets_at)
        if resets_at is not None:
            self.schedule(resets_at)

    def catch_up_if_needed(self, resets_at: datetime.datetime | None) -> bool:
        """Fire an immediate ping if a scheduled firing was missed.

        Returns True if a catch-up ping was fired. Never fires more than
        once per missed scheduled time: ``last_fired_at >= scheduled_fire_at``
        is treated as "already handled".
        """
        state = self._load_state()
        scheduled = state.scheduled_fire_at
        if scheduled is None:
            return False

        now = datetime.datetime.now().astimezone()
        if scheduled > now:
            return False

        if state.last_fired_at is not None and state.last_fired_at >= scheduled:
            return False

        overdue_sec = (now - scheduled).total_seconds()
        if overdue_sec > self._catch_up_window_sec:
            logger.info(
                "Keepalive catch-up skipped: scheduled fire was %.0fs ago (>%ds window).",
                overdue_sec,
                self._catch_up_window_sec,
            )
            self._persist_status(now, "skipped")
            # Clear stale schedule so we don't re-attempt on next wake.
            self._persist_scheduled(None)
            # If a live resets_at is known, the caller will reschedule.
            return False

        # Fire on a background thread so we never block the wake callback.
        threading.Thread(
            target=self._fire_catch_up,
            args=(scheduled,),
            daemon=True,
        ).start()
        return True

    # ------------------------------------------------------------------
    # Status / snapshot
    # ------------------------------------------------------------------
    def status_snapshot(self) -> KeepaliveState:
        """Return the current persisted state for UI display."""
        return self._load_state()

    # ------------------------------------------------------------------
    # Internal: ping execution
    # ------------------------------------------------------------------
    def _run_scheduled_ping(self, generation: int) -> None:
        with self._lock:
            if generation != self._timer_generation:
                return
            self._timer = None
        self._fire_ping()

    def _fire_catch_up(self, scheduled: datetime.datetime) -> None:
        logger.info("Keepalive catch-up firing for missed schedule %s", scheduled.isoformat())
        self._fire_ping()

    def _fire_ping(self) -> bool:
        """Send a lightweight Codex prompt to start the next window promptly."""
        now = datetime.datetime.now().astimezone()
        codex_path = self._resolve_codex_binary()
        if not codex_path:
            searched = os.pathsep.join(self._search_paths())
            logger.warning(
                "Keepalive ping skipped: `codex` not found. Searched: %s. "
                "Set `codex_bin` in config to override.",
                searched,
            )
            self._persist_status(now, "failed")
            return False

        try:
            result = subprocess.run(
                [codex_path, *_PING_ARGS, _PING_PROMPT],
                capture_output=True,
                text=True,
                timeout=self._ping_timeout_sec,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Keepalive ping timed out after %ss.", self._ping_timeout_sec)
            self._persist_status(now, "failed")
            return False
        except FileNotFoundError:
            logger.warning("Keepalive ping failed: `codex` became unavailable.")
            self._persist_status(now, "failed")
            return False
        except Exception as exc:
            logger.warning("Keepalive ping failed: %s", exc)
            self._persist_status(now, "failed")
            return False

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if detail:
                logger.warning("Keepalive ping failed: %s", detail)
            else:
                logger.warning("Keepalive ping failed (exit %s).", result.returncode)
            self._persist_status(now, "failed")
            return False

        logger.info("Keepalive ping sent successfully.")
        self._persist_status(now, "ok")
        return True

    # ------------------------------------------------------------------
    # Internal: codex binary resolution
    # ------------------------------------------------------------------
    def _search_paths(self) -> list[str]:
        """Augmented PATH used when bare ``shutil.which`` fails."""
        env_path = os.environ.get("PATH", "")
        dirs = list(_fallback_path_dirs())
        if env_path:
            dirs.append(env_path)
        return dirs

    def _resolve_codex_binary(self) -> str | None:
        """Locate the ``codex`` CLI, tolerant of GUI-app minimal PATH.

        Resolution order: explicit config override → ``$CODEX_BIN`` env →
        ``shutil.which`` against current PATH → ``shutil.which`` against an
        augmented PATH covering common per-user install dirs.
        """
        override = self._codex_bin
        if override and os.path.isfile(override) and os.access(override, os.X_OK):
            return override

        env_override = os.environ.get("CODEX_BIN")
        if env_override and os.path.isfile(env_override) and os.access(env_override, os.X_OK):
            return env_override

        found = shutil.which("codex")
        if found:
            return found

        augmented = os.pathsep.join(self._search_paths())
        return shutil.which("codex", path=augmented)

    # ------------------------------------------------------------------
    # Internal: state persistence helpers
    # ------------------------------------------------------------------
    def _load_state(self) -> KeepaliveState:
        if self._state_path is None:
            return KeepaliveState()
        return load_state(self._state_path)

    def _persist_status(self, fired_at: datetime.datetime, status: str) -> None:
        if self._state_path is None:
            return
        try:
            current = load_state(self._state_path)
            save_state(self._state_path, current.with_fired(fired_at, status))
        except Exception as exc:
            logger.warning("Could not persist keepalive status: %s", exc)

    def _persist_scheduled(self, scheduled_fire_at: datetime.datetime | None) -> None:
        if self._state_path is None:
            return
        try:
            current = load_state(self._state_path)
            save_state(
                self._state_path, current.with_scheduled(scheduled_fire_at)
            )
        except Exception as exc:
            logger.warning("Could not persist keepalive schedule: %s", exc)

    # ------------------------------------------------------------------
    # Internal: Tier 2 system-wake via pmset
    # ------------------------------------------------------------------
    def _maybe_schedule_system_wake(self, fire_at: datetime.datetime) -> None:
        if not self._wake_system_enabled:
            return
        # Wake the Mac a few seconds before the ping so the timer can fire
        # on an already-awake system.
        wake_at = fire_at - datetime.timedelta(seconds=max(5, self._buffer_sec // 2))
        if wake_at <= datetime.datetime.now().astimezone():
            return

        if self._last_wake_scheduled is not None:
            if abs((self._last_wake_scheduled - wake_at).total_seconds()) < 1:
                return
            self._cancel_system_wake()

        formatted = wake_at.strftime("%m/%d/%Y %H:%M:%S")
        try:
            subprocess.run(
                [_SUDO_PATH, "-n", _PMSET_PATH, "schedule", "wake", formatted],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            logger.warning("pmset schedule wake failed: %s", exc)
            return
        self._last_wake_scheduled = wake_at
        logger.info("Scheduled pmset system wake at %s", formatted)

    def _cancel_system_wake(self) -> None:
        if not self._wake_system_enabled or self._last_wake_scheduled is None:
            self._last_wake_scheduled = None
            return
        formatted = self._last_wake_scheduled.strftime("%m/%d/%Y %H:%M:%S")
        try:
            subprocess.run(
                [_SUDO_PATH, "-n", _PMSET_PATH, "schedule", "cancel", "wake", formatted],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            logger.debug("pmset schedule cancel failed: %s", exc)
        self._last_wake_scheduled = None
