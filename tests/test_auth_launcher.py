"""Tests for auth launcher helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from credcodex.auth_launcher import ReauthGate, is_auth_error, launch_auth_docs, launch_codex_login
from credcodex.models import FailureCategory


class TestLaunchCodexLogin:
    def test_success(self, monkeypatch):
        monkeypatch.setattr("credcodex.auth_launcher.shutil.which", lambda name: "/opt/homebrew/bin/codex")
        monkeypatch.setattr(
            "credcodex.auth_launcher.subprocess.run",
            lambda *args, **kwargs: MagicMock(returncode=0, stdout="", stderr=""),
        )
        result = launch_codex_login()
        assert result.success is True
        assert "codex login" in result.message

    def test_permission_denied(self, monkeypatch):
        monkeypatch.setattr("credcodex.auth_launcher.shutil.which", lambda name: "/opt/homebrew/bin/codex")
        monkeypatch.setattr(
            "credcodex.auth_launcher.subprocess.run",
            lambda *args, **kwargs: MagicMock(returncode=1, stdout="", stderr="Not allowed"),
        )
        result = launch_codex_login()
        assert result.success is False
        assert "denied" in result.message.lower()

    def test_timeout(self, monkeypatch):
        monkeypatch.setattr("credcodex.auth_launcher.shutil.which", lambda name: "/opt/homebrew/bin/codex")
        monkeypatch.setattr(
            "credcodex.auth_launcher.subprocess.run",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(cmd="osascript", timeout=12)
            ),
        )
        result = launch_codex_login()
        assert result.success is False
        assert "Timed out" in result.message

    def test_falls_back_to_docs_when_codex_missing(self, monkeypatch):
        monkeypatch.setattr("credcodex.auth_launcher.shutil.which", lambda name: None)
        monkeypatch.setattr("credcodex.auth_launcher.webbrowser.open", lambda *args, **kwargs: True)
        result = launch_codex_login()
        assert result.success is True
        assert "docs" in result.message.lower()

    def test_launch_auth_docs_failure(self, monkeypatch):
        monkeypatch.setattr("credcodex.auth_launcher.webbrowser.open", lambda *args, **kwargs: False)
        result = launch_auth_docs()
        assert result.success is False


class TestReauthGate:
    def test_auth_failure_respects_cooldown(self):
        gate = ReauthGate(cooldown_sec=1800)
        assert gate.eligible_for_auto_launch("refresh token expired", now_mono=10.0) is True
        gate.mark_attempt(now_mono=10.0)
        assert gate.eligible_for_auto_launch("refresh token expired", now_mono=20.0) is False
        assert gate.eligible_for_auto_launch("refresh token expired", now_mono=1811.0) is True

    def test_is_auth_error_uses_category(self):
        assert is_auth_error(None, category=FailureCategory.AUTH_EXPIRED) is True
        assert is_auth_error(None, category=FailureCategory.UNSUPPORTED_AUTH_MODE) is True
        assert is_auth_error("Rate limited", category=FailureCategory.RATE_LIMITED) is False
