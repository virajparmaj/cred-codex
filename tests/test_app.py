"""Tests for pure app helpers, locks, PID locking, and script sanity."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from credcodex import __main__ as main_mod
from credcodex.app import derive_menu_sections, derive_title, format_menu_datetime, format_relative_countdown
from credcodex.models import Confidence, FailureCategory, LimitInfo, ProviderState
from credcodex.notifications import cleanup_notification_locks, read_lock_value, should_notify_once, write_lock


def _limit(**overrides: object) -> LimitInfo:
    base = LimitInfo(
        source="test",
        confidence=Confidence.HIGH,
        state=ProviderState.HEALTHY,
    )
    return base.with_overrides(**overrides)


class TestFormattingHelpers:
    def test_relative_countdown(self):
        now = dt.datetime(2026, 4, 3, 12, 0, tzinfo=dt.timezone.utc)
        target = now + dt.timedelta(hours=2, minutes=15)
        assert format_relative_countdown(target, now=now) == "2h 15m"

    def test_menu_datetime(self):
        target = dt.datetime(2026, 4, 7, 14, 30, tzinfo=dt.timezone.utc)
        rendered = format_menu_datetime(target)
        assert "Apr" in rendered
        assert "7" in rendered


class TestTitleRendering:
    def test_healthy_title(self):
        now = dt.datetime(2026, 4, 3, 12, 0, tzinfo=dt.timezone.utc)
        limit = _limit(utilization_pct=34.0, resets_at=now + dt.timedelta(hours=5))
        assert derive_title(limit, now=now) == "34% | 5h 0m"

    def test_auth_title(self):
        limit = _limit(
            state=ProviderState.DEGRADED,
            failure_category=FailureCategory.AUTH_EXPIRED,
            utilization_pct=None,
        )
        assert derive_title(limit) == "⚠ auth"

    def test_offline_title(self):
        limit = _limit(state=ProviderState.OFFLINE, utilization_pct=None)
        assert derive_title(limit) == "⏸ off"

    def test_stale_title(self):
        limit = _limit(state=ProviderState.STALE, utilization_pct=None)
        assert derive_title(limit) == "⏸ stale"


class TestMenuSections:
    def test_optional_sections_hide_cleanly(self):
        sections = derive_menu_sections(_limit())
        assert sections.plan_title is None
        assert sections.weekly_title is None
        assert sections.credits_title is None
        assert sections.extra_title is None
        assert sections.has_any_info is False

    def test_sections_render_when_present(self):
        limit = _limit(
            plan_tier="plus",
            weekly_utilization_pct=74.0,
            weekly_resets_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7),
            credits_balance="12.5",
            extra_usage_enabled=True,
            extra_usage_utilization=45.0,
        )
        sections = derive_menu_sections(limit)
        assert sections.plan_title == "Plan: Plus"
        assert "Weekly:" in sections.weekly_title
        assert "Credits: 12.5 credits" == sections.credits_title
        assert "Extra usage:" in sections.extra_title
        assert sections.has_any_info is True


class TestNotificationLocks:
    def test_dedupe_lock_round_trip(self, tmp_path):
        lock = tmp_path / "notice.txt"
        assert should_notify_once(lock, "abc") is True
        write_lock(lock, "abc")
        assert read_lock_value(lock) == "abc"
        assert should_notify_once(lock, "abc") is False

    def test_cleanup_old_locks(self, tmp_path):
        lock = tmp_path / "old.txt"
        write_lock(lock, "abc")
        old = dt.datetime.now().timestamp() - (40 * 86400)
        os.utime(lock, (old, old))
        cleanup_notification_locks(base_dir=tmp_path, days=30)
        assert not lock.exists()


class TestPidLock:
    def test_second_lock_exits(self, tmp_path, monkeypatch):
        pid_path = tmp_path / "monitor.pid"
        monkeypatch.setattr(main_mod, "PID_PATH", pid_path)
        monkeypatch.setattr(main_mod, "_LOCK_HANDLE", None)
        main_mod._acquire_pid_lock()
        try:
            with pytest.raises(SystemExit):
                main_mod._acquire_pid_lock()
        finally:
            main_mod._release_pid_lock()


class TestScriptSanity:
    def test_scripts_reference_expected_tools(self, repo_root: Path):
        build_text = (repo_root / "build_app.sh").read_text()
        install_text = (repo_root / "install.sh").read_text()
        uninstall_text = (repo_root / "uninstall.sh").read_text()

        assert "CredCodex" in build_text
        assert "AppIconRuntime.png" in build_text
        assert "TARGET_ALPHA_BOUNDS_RATIO" in build_text
        assert "DOCK_ICON_BOUNDS_RATIO" in build_text
        assert "iconutil" in build_text
        assert "sips" in build_text
        assert "cc" in build_text
        assert "launchctl" in install_text
        assert "ditto" in install_text
        assert "osascript" in uninstall_text
