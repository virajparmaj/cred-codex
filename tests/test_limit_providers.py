"""Tests for CredCodex limit providers."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from credcodex import limit_providers as lp
from credcodex.models import Confidence, FailureCategory, ProviderState


def _auth(**overrides: object) -> lp.AuthSnapshot:
    base = lp.AuthSnapshot(
        auth_mode="chatgpt",
        access_token="access-token",
        refresh_token="refresh-token",
        account_id="account-123",
        openai_api_key=None,
        storage_backend="file",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _payload(
    primary_used: float = 34.0,
    primary_minutes: int = 300,
    secondary_used: float | None = 74.0,
    secondary_minutes: int | None = 10080,
    plan_type: str | None = "plus",
    credits: dict[str, object] | None = None,
) -> dict[str, object]:
    now = dt.datetime.now(dt.timezone.utc)
    payload: dict[str, object] = {
        "plan_type": plan_type,
        "rate_limit": {
            "primary_window": {
                "used_percent": primary_used,
                "limit_window_seconds": primary_minutes * 60,
                "reset_at": int((now + dt.timedelta(minutes=primary_minutes)).timestamp()),
            },
        },
    }
    if secondary_used is not None and secondary_minutes is not None:
        payload["rate_limit"]["secondary_window"] = {
            "used_percent": secondary_used,
            "limit_window_seconds": secondary_minutes * 60,
            "reset_at": int((now + dt.timedelta(minutes=secondary_minutes)).timestamp()),
        }
    if credits is not None:
        payload["credits"] = credits
    return payload


@pytest.fixture
def isolated_files(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "snapshot.json"
    auth_path = tmp_path / "auth.json"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr(lp, "SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(lp, "CODEX_AUTH_PATH", auth_path)
    monkeypatch.setattr(lp, "CODEX_SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(lp, "CODEX_HOME", tmp_path / ".codex")
    return {"snapshot": snapshot_path, "auth": auth_path, "sessions": sessions_dir}


class TestAuthLoading:
    def test_loads_auth_from_file(self, isolated_files, monkeypatch):
        isolated_files["auth"].write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "account_id": "account-123",
                        "id_token": "id-token",
                    },
                }
            )
        )
        monkeypatch.setattr(lp, "codex_auth_storage_mode", lambda: "file")
        auth = lp.load_auth_snapshot()
        assert auth is not None
        assert auth.is_chatgpt is True
        assert auth.account_id == "account-123"

    def test_loads_auth_from_keychain(self, isolated_files, monkeypatch):
        monkeypatch.setattr(lp, "codex_auth_storage_mode", lambda: "keyring")
        monkeypatch.setattr(lp, "compute_keyring_account_key", lambda _home: "cli|abcd1234")
        monkeypatch.setattr(
            lp.subprocess,
            "run",
            lambda *args, **kwargs: MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {
                            "access_token": "access-token",
                            "refresh_token": "refresh-token",
                            "account_id": "acct",
                        },
                    }
                ),
                stderr="",
            ),
        )
        auth = lp.load_auth_snapshot()
        assert auth is not None
        assert auth.storage_backend == "keychain"
        assert auth.account_key == "cli|abcd1234"

    def test_api_key_mode_is_unsupported(self, monkeypatch):
        provider = lp.LiveCodexLimitProvider()
        monkeypatch.setattr(lp, "load_auth_snapshot", lambda: _auth(auth_mode="api_key", access_token=None, refresh_token=None, account_id=None, openai_api_key="sk-test"))
        result = provider.get_limit_info()
        assert result.failure_category == FailureCategory.UNSUPPORTED_AUTH_MODE
        assert result.state == ProviderState.DEGRADED


class TestPayloadNormalization:
    def test_official_payload_maps_primary_weekly_plan_and_credits(self):
        provider = lp.LiveCodexLimitProvider()
        info = provider._normalize_official_payload(
            _payload(credits={"balance": "12.5", "hasCredits": True, "unlimited": False}),
            _auth(),
        )
        assert info.utilization_pct == pytest.approx(34.0)
        assert info.primary_window_minutes == 300
        assert info.weekly_utilization_pct == pytest.approx(74.0)
        assert info.secondary_window_minutes == 10080
        assert info.plan_tier == "plus"
        assert info.credits_balance == "12.5"
        assert info.credits_unlimited is False

    def test_monthly_primary_window_does_not_populate_weekly(self):
        provider = lp.LiveCodexLimitProvider()
        info = provider._normalize_official_payload(
            _payload(primary_used=12.0, primary_minutes=43200, secondary_used=None, secondary_minutes=None, plan_type="pro"),
            _auth(),
        )
        assert info.primary_window_minutes == 43200
        assert info.weekly_utilization_pct is None
        assert info.plan_tier == "pro"

    def test_fraction_normalizes_to_percent(self):
        provider = lp.LiveCodexLimitProvider()
        info = provider._normalize_official_payload(_payload(primary_used=0.34, secondary_used=0.74), _auth())
        assert info.utilization_pct == pytest.approx(34.0)
        assert info.weekly_utilization_pct == pytest.approx(74.0)


class TestSnapshots:
    def test_snapshot_round_trip(self, isolated_files):
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        info = lp.LimitInfo(
            source="official",
            confidence=Confidence.HIGH,
            state=ProviderState.HEALTHY,
            utilization_pct=45.0,
            resets_at=future,
            credits_balance="8.5",
        )
        lp._save_snapshot(info)
        loaded = lp._load_snapshot()
        assert loaded is not None
        assert loaded.utilization_pct == pytest.approx(45.0)
        assert loaded.credits_balance == "8.5"

    def test_expired_snapshot_is_rejected(self, isolated_files):
        info = lp.LimitInfo(
            source="official",
            confidence=Confidence.HIGH,
            state=ProviderState.HEALTHY,
            utilization_pct=80.0,
            resets_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1),
        )
        lp._save_snapshot(info)
        assert lp._load_snapshot() is None

    def test_startup_snapshot_seed(self, isolated_files):
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        snapshot = {
            "source": "official",
            "confidence": "high",
            "state": "healthy",
            "utilization_pct": 55.0,
            "resets_at": future.isoformat(),
            "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        isolated_files["snapshot"].write_text(json.dumps(snapshot))
        provider = lp.LiveCodexLimitProvider()
        assert provider.try_snapshot_startup() is True
        seeded = provider.get_limit_info()
        assert seeded.utilization_pct == pytest.approx(55.0)

    def test_old_startup_snapshot_is_rejected(self, isolated_files):
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        snapshot = {
            "source": "official",
            "confidence": "high",
            "state": "healthy",
            "utilization_pct": 55.0,
            "resets_at": future.isoformat(),
            "saved_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)).isoformat(),
        }
        isolated_files["snapshot"].write_text(json.dumps(snapshot))
        provider = lp.LiveCodexLimitProvider()
        assert provider.try_snapshot_startup() is False


class TestLocalSessionFallback:
    def test_reads_recent_session_telemetry(self, isolated_files):
        session_file = isolated_files["sessions"] / "latest.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "rate_limits": {
                            "plan_type": "plus",
                            "primary": {
                                "used_percent": 34.0,
                                "window_minutes": 300,
                                "resets_at": int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5)).timestamp()),
                            },
                            "secondary": {
                                "used_percent": 74.0,
                                "window_minutes": 10080,
                                "resets_at": int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)).timestamp()),
                            },
                        },
                    },
                }
            )
        )
        provider = lp.LocalSessionLimitProvider()
        info = provider.get_limit_info()
        assert info.state == ProviderState.DEGRADED
        assert info.utilization_pct == pytest.approx(34.0)
        assert info.weekly_utilization_pct == pytest.approx(74.0)

    def test_stale_session_telemetry_marks_state_stale(self, isolated_files):
        session_file = isolated_files["sessions"] / "latest.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "timestamp": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat(),
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "rate_limits": {
                            "primary": {
                                "used_percent": 12.0,
                                "window_minutes": 300,
                                "resets_at": int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).timestamp()),
                            },
                        },
                    },
                }
            )
        )
        provider = lp.LocalSessionLimitProvider()
        info = provider.get_limit_info()
        assert info.state == ProviderState.STALE
        assert info.failure_category == FailureCategory.STALE_CACHED_DATA


class TestLiveProviderResilience:
    def test_cache_ttl_uses_memory_cache(self, monkeypatch):
        provider = lp.LiveCodexLimitProvider()
        auth = _auth()
        calls = {"count": 0}
        monkeypatch.setattr(lp, "load_auth_snapshot", lambda: auth)

        def request(_auth):
            calls["count"] += 1
            return _payload()

        monkeypatch.setattr(provider, "_request_usage", request)
        first = provider.get_limit_info()
        second = provider.get_limit_info()
        assert first.utilization_pct == pytest.approx(34.0)
        assert second.utilization_pct == pytest.approx(34.0)
        assert calls["count"] == 1

    def test_401_refresh_success(self, monkeypatch):
        provider = lp.LiveCodexLimitProvider()
        old_auth = _auth(access_token="old-token")
        new_auth = _auth(access_token="new-token")
        seen_tokens: list[str] = []
        monkeypatch.setattr(lp, "load_auth_snapshot", lambda: old_auth)
        monkeypatch.setattr(lp, "_refresh_auth_snapshot", lambda auth: new_auth)

        def request(auth):
            seen_tokens.append(auth.access_token or "")
            if auth.access_token == "old-token":
                raise lp._AuthExpiredError("expired")
            return _payload(plan_type="pro")

        monkeypatch.setattr(provider, "_request_usage", request)
        info = provider.get_limit_info()
        assert seen_tokens == ["old-token", "new-token"]
        assert info.state == ProviderState.HEALTHY
        assert info.plan_tier == "pro"

    def test_401_refresh_failure_degrades(self, monkeypatch):
        provider = lp.LiveCodexLimitProvider()
        monkeypatch.setattr(lp, "load_auth_snapshot", lambda: _auth())
        monkeypatch.setattr(provider, "_request_usage", lambda auth: (_ for _ in ()).throw(lp._AuthExpiredError("expired")))
        monkeypatch.setattr(lp, "_refresh_auth_snapshot", lambda auth: (_ for _ in ()).throw(lp._AuthExpiredError("refresh failed")))
        info = provider.get_limit_info()
        assert info.failure_category == FailureCategory.AUTH_EXPIRED
        assert info.state == ProviderState.DEGRADED

    def test_rate_limit_backoff_progression_and_manual_refresh(self, monkeypatch):
        provider = lp.LiveCodexLimitProvider()
        monkeypatch.setattr(lp, "load_auth_snapshot", lambda: _auth())
        calls = {"count": 0}

        def request(_auth):
            calls["count"] += 1
            raise lp._RateLimitedError("Rate limited")

        monkeypatch.setattr(provider, "_request_usage", request)
        first = provider.get_limit_info()
        second = provider.get_limit_info()
        third = provider.force_refresh()
        assert first.failure_category == FailureCategory.RATE_LIMITED
        assert second.failure_category == FailureCategory.RATE_LIMITED
        assert third.failure_category == FailureCategory.RATE_LIMITED
        assert calls["count"] == 2
        assert provider._rate_limit_step == 2

    def test_stale_cached_data_on_transport_failure(self, monkeypatch):
        provider = lp.LiveCodexLimitProvider()
        monkeypatch.setattr(lp, "load_auth_snapshot", lambda: _auth())
        monkeypatch.setattr(provider, "_request_usage", lambda auth: _payload())
        provider.get_limit_info()
        provider._cache_time = dt.datetime.now(dt.timezone.utc).astimezone() - dt.timedelta(seconds=100)
        monkeypatch.setattr(provider, "_request_usage", lambda auth: (_ for _ in ()).throw(lp._TransportError("offline")))
        info = provider.get_limit_info()
        assert info.state == ProviderState.STALE
        assert info.failure_category == FailureCategory.STALE_CACHED_DATA


class TestCompositeFallbacks:
    def test_snapshot_fallback_when_live_has_no_data(self, isolated_files, monkeypatch):
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        isolated_files["snapshot"].write_text(
            json.dumps(
                {
                    "source": "official",
                    "confidence": "high",
                    "state": "healthy",
                    "utilization_pct": 66.0,
                    "resets_at": future.isoformat(),
                    "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            )
        )
        provider = lp.CompositeLimitProvider({})
        monkeypatch.setattr(
            provider._live,
            "get_limit_info",
            lambda: lp.LimitInfo(
                source="official",
                confidence=Confidence.LOW,
                state=ProviderState.DEGRADED,
                failure_category=FailureCategory.AUTH_EXPIRED,
                error="expired",
            ),
        )
        info = provider.get_limit_info()
        assert info.utilization_pct == pytest.approx(66.0)
        assert info.state == ProviderState.STALE
