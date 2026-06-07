"""Tests for the post-reset keepalive scheduler and its persistent state."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest

from credcodex import keepalive as keepalive_mod
from credcodex.keepalive import KeepaliveScheduler
from credcodex.keepalive_state import KeepaliveState, load_state, save_state


def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


class _SyncThread:
    """Drop-in for threading.Thread that runs the target synchronously."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self) -> None:
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "keepalive_state.json"


# ----------------------------------------------------------------------
# keepalive_state round-trip
# ----------------------------------------------------------------------
class TestKeepaliveState:
    def test_round_trip(self, state_path):
        fired = _now().replace(microsecond=0)
        scheduled = (fired + datetime.timedelta(hours=5)).replace(microsecond=0)
        state = KeepaliveState().with_scheduled(scheduled).with_fired(fired, "ok")
        save_state(state_path, state)

        loaded = load_state(state_path)
        assert loaded.last_fired_at == fired
        assert loaded.last_status == "ok"
        assert loaded.scheduled_fire_at == scheduled

    def test_missing_file_returns_empty(self, state_path):
        loaded = load_state(state_path)
        assert loaded == KeepaliveState()

    def test_corrupt_file_returns_empty(self, state_path):
        state_path.write_text("{not valid json")
        assert load_state(state_path) == KeepaliveState()

    def test_non_object_returns_empty(self, state_path):
        state_path.write_text(json.dumps([1, 2, 3]))
        assert load_state(state_path) == KeepaliveState()

    def test_invalid_status_coerced_to_none(self, state_path):
        state_path.write_text(json.dumps({"last_status": "bogus"}))
        assert load_state(state_path).last_status is None

    def test_with_fired_rejects_invalid_status(self):
        with pytest.raises(ValueError):
            KeepaliveState().with_fired(_now(), "nonsense")


# ----------------------------------------------------------------------
# Scheduling
# ----------------------------------------------------------------------
class TestSchedule:
    def test_schedule_none_returns_false(self, state_path):
        scheduler = KeepaliveScheduler(state_path=state_path)
        assert scheduler.schedule(None) is False

    def test_schedule_past_returns_false(self, state_path):
        scheduler = KeepaliveScheduler(state_path=state_path)
        past = _now() - datetime.timedelta(minutes=5)
        assert scheduler.schedule(past) is False
        assert load_state(state_path).scheduled_fire_at is None

    def test_schedule_future_persists(self, state_path):
        scheduler = KeepaliveScheduler(state_path=state_path)
        future = _now() + datetime.timedelta(hours=5)
        try:
            assert scheduler.schedule(future) is True
            stored = load_state(state_path).scheduled_fire_at
            assert stored is not None
            # fire_at = reset + buffer (default 10s)
            assert abs((stored - future).total_seconds() - 10) < 1
        finally:
            scheduler.cancel()
        assert load_state(state_path).scheduled_fire_at is None


# ----------------------------------------------------------------------
# Catch-up behaviour
# ----------------------------------------------------------------------
class TestCatchUp:
    def test_no_schedule_does_not_fire(self, state_path):
        scheduler = KeepaliveScheduler(state_path=state_path)
        assert scheduler.catch_up_if_needed(None) is False

    def test_future_schedule_does_not_fire(self, state_path):
        scheduler = KeepaliveScheduler(state_path=state_path)
        future = _now() + datetime.timedelta(hours=1)
        save_state(state_path, KeepaliveState().with_scheduled(future))
        assert scheduler.catch_up_if_needed(None) is False

    def test_fires_once_not_twice(self, state_path, monkeypatch):
        # Run the catch-up thread synchronously and stub the codex call to OK.
        monkeypatch.setattr(keepalive_mod.threading, "Thread", _SyncThread)
        monkeypatch.setattr(
            keepalive_mod.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        scheduler = KeepaliveScheduler(state_path=state_path)
        monkeypatch.setattr(scheduler, "_resolve_codex_binary", lambda: "/usr/bin/true")

        missed = _now() - datetime.timedelta(minutes=2)
        save_state(state_path, KeepaliveState().with_scheduled(missed))

        assert scheduler.catch_up_if_needed(None) is True
        assert load_state(state_path).last_status == "ok"

        # Already handled: last_fired_at >= scheduled_fire_at.
        assert scheduler.catch_up_if_needed(None) is False

    def test_beyond_window_skipped(self, state_path):
        scheduler = KeepaliveScheduler(state_path=state_path, catch_up_window_sec=7200)
        stale = _now() - datetime.timedelta(hours=3)
        save_state(state_path, KeepaliveState().with_scheduled(stale))

        assert scheduler.catch_up_if_needed(None) is False
        state = load_state(state_path)
        assert state.last_status == "skipped"
        assert state.scheduled_fire_at is None


# ----------------------------------------------------------------------
# Ping execution
# ----------------------------------------------------------------------
class TestFirePing:
    def test_binary_not_found_persists_failed(self, state_path, monkeypatch):
        scheduler = KeepaliveScheduler(state_path=state_path)
        monkeypatch.setattr(scheduler, "_resolve_codex_binary", lambda: None)

        assert scheduler._fire_ping() is False
        assert load_state(state_path).last_status == "failed"

    def test_success_persists_ok_with_exec_command(self, state_path, monkeypatch):
        scheduler = KeepaliveScheduler(state_path=state_path)
        monkeypatch.setattr(scheduler, "_resolve_codex_binary", lambda: "/usr/bin/codex")
        captured = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(keepalive_mod.subprocess, "run", _fake_run)

        assert scheduler._fire_ping() is True
        assert load_state(state_path).last_status == "ok"
        assert captured["cmd"][0] == "/usr/bin/codex"
        assert captured["cmd"][1] == "exec"
        assert "--skip-git-repo-check" in captured["cmd"]

    def test_nonzero_exit_persists_failed(self, state_path, monkeypatch):
        scheduler = KeepaliveScheduler(state_path=state_path)
        monkeypatch.setattr(scheduler, "_resolve_codex_binary", lambda: "/usr/bin/codex")
        monkeypatch.setattr(
            keepalive_mod.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
        )
        assert scheduler._fire_ping() is False
        assert load_state(state_path).last_status == "failed"

    def test_timeout_persists_failed(self, state_path, monkeypatch):
        scheduler = KeepaliveScheduler(state_path=state_path)
        monkeypatch.setattr(scheduler, "_resolve_codex_binary", lambda: "/usr/bin/codex")

        def _raise(*a, **k):
            raise keepalive_mod.subprocess.TimeoutExpired(cmd="codex", timeout=1)

        monkeypatch.setattr(keepalive_mod.subprocess, "run", _raise)
        assert scheduler._fire_ping() is False
        assert load_state(state_path).last_status == "failed"


# ----------------------------------------------------------------------
# Binary resolution
# ----------------------------------------------------------------------
class TestResolveBinary:
    def test_explicit_override_used(self, state_path, tmp_path, monkeypatch):
        fake = tmp_path / "codex"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        scheduler = KeepaliveScheduler(state_path=state_path)
        scheduler.set_codex_bin(str(fake))
        assert scheduler._resolve_codex_binary() == str(fake)

    def test_blank_override_falls_back_to_which(self, state_path, monkeypatch):
        scheduler = KeepaliveScheduler(state_path=state_path)
        scheduler.set_codex_bin("   ")
        monkeypatch.delenv("CODEX_BIN", raising=False)
        monkeypatch.setattr(keepalive_mod.shutil, "which", lambda *a, **k: "/found/codex")
        assert scheduler._resolve_codex_binary() == "/found/codex"
