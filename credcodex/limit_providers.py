"""Provider pipeline for CredCodex."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from credcodex import __version__
from credcodex.config import (
    CODEX_AUTH_PATH,
    CODEX_HOME,
    CODEX_SESSIONS_DIR,
    IN_MEMORY_CACHE_TTL_SEC,
    SESSION_TELEMETRY_STALE_SEC,
    SNAPSHOT_PATH,
    STARTUP_SNAPSHOT_MAX_AGE_SEC,
    codex_auth_storage_mode,
    compute_keyring_account_key,
)
from credcodex.models import Confidence, FailureCategory, LimitInfo, ProviderState

logger = logging.getLogger("credcodex.limit_providers")

USAGE_URL = os.environ.get("CREDCODEX_USAGE_URL", "https://chatgpt.com/backend-api/codex/usage")
TOKEN_REFRESH_URL = os.environ.get(
    "CREDCODEX_TOKEN_REFRESH_URL",
    "https://auth.openai.com/oauth/token",
)
KEYCHAIN_SERVICE = "Codex Auth"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_RETRY_COOLDOWN_SEC = 300
RATE_LIMIT_BACKOFF_STEPS_SEC = (120, 300, 600)


def _now() -> datetime:
    """Return the current timezone-aware local datetime."""
    return datetime.now(timezone.utc).astimezone()


def _normalize_utilization(value: float | int | None) -> float | None:
    """Normalize fractions and percentages into a 0..100 percentage."""
    if value is None:
        return None
    normalized = float(value)
    if normalized <= 1.0:
        normalized *= 100.0
    return max(0.0, min(100.0, round(normalized, 1)))


def _dt_from_any(value: object) -> datetime | None:
    """Parse unix timestamps or ISO strings into timezone-aware datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc).astimezone()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone()
        except ValueError:
            try:
                return datetime.fromtimestamp(float(text), tz=timezone.utc).astimezone()
            except ValueError:
                return None
    return None


def _is_expired(limit: LimitInfo, now: datetime | None = None) -> bool:
    """Return True when the primary reset window has already passed."""
    instant = now or _now()
    return bool(limit.resets_at and limit.resets_at <= instant)


def _window_minutes(window: dict[str, object] | None) -> int | None:
    """Normalize various upstream duration keys into minutes."""
    if not window:
        return None
    if isinstance(window.get("window_minutes"), (int, float)):
        return int(float(window["window_minutes"]))
    if isinstance(window.get("windowDurationMins"), (int, float)):
        return int(float(window["windowDurationMins"]))
    seconds = window.get("limit_window_seconds")
    if isinstance(seconds, (int, float)):
        return int(float(seconds) // 60)
    return None


def _window_resets_at(window: dict[str, object] | None, captured_at: datetime | None = None) -> datetime | None:
    """Return a reset time from the upstream window shape."""
    if not window:
        return None
    reset = _dt_from_any(window.get("reset_at") or window.get("resets_at"))
    if reset is not None:
        return reset
    reset_after_seconds = window.get("reset_after_seconds")
    if isinstance(reset_after_seconds, (int, float)):
        return (captured_at or _now()) + timedelta(seconds=float(reset_after_seconds))
    return None


def _is_weekly_window(window_minutes: int | None) -> bool:
    """Return True when the upstream duration should be shown as a weekly window."""
    if window_minutes is None:
        return False
    return abs(window_minutes - 10080) <= 60


@dataclass
class AuthSnapshot:
    """Normalized local Codex auth state."""

    auth_mode: str | None
    access_token: str | None
    refresh_token: str | None
    account_id: str | None
    openai_api_key: str | None
    id_token: str | None = None
    storage_backend: str = "file"
    account_key: str | None = None

    @property
    def is_chatgpt(self) -> bool:
        return bool(self.access_token and self.account_id)

    @property
    def is_api_key_only(self) -> bool:
        return bool(self.openai_api_key and not self.is_chatgpt)


def _load_auth_json_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def _parse_auth_snapshot(raw_text: str, storage_backend: str, account_key: str | None = None) -> AuthSnapshot:
    data = json.loads(raw_text)
    tokens = data.get("tokens") or {}
    auth_mode = data.get("auth_mode")
    if isinstance(auth_mode, str):
        normalized_mode = auth_mode.lower()
    else:
        normalized_mode = None
    return AuthSnapshot(
        auth_mode=normalized_mode,
        access_token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        account_id=tokens.get("account_id"),
        openai_api_key=data.get("OPENAI_API_KEY"),
        id_token=tokens.get("id_token"),
        storage_backend=storage_backend,
        account_key=account_key,
    )


def _load_file_auth_snapshot() -> AuthSnapshot | None:
    raw = _load_auth_json_text(CODEX_AUTH_PATH)
    if raw is None:
        return None
    try:
        return _parse_auth_snapshot(raw, storage_backend="file")
    except Exception as exc:
        logger.debug("Failed to parse %s: %s", CODEX_AUTH_PATH, exc)
        return None


def _load_keychain_auth_snapshot() -> AuthSnapshot | None:
    account_key = compute_keyring_account_key(CODEX_HOME)
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                account_key,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.debug("Failed to read keychain auth: %s", exc)
        return None

    if result.returncode != 0:
        return None

    try:
        return _parse_auth_snapshot(
            result.stdout.strip(),
            storage_backend="keychain",
            account_key=account_key,
        )
    except Exception as exc:
        logger.debug("Failed to parse keychain auth payload: %s", exc)
        return None


def load_auth_snapshot() -> AuthSnapshot | None:
    """Load local Codex auth based on the configured storage mode."""
    mode = codex_auth_storage_mode()
    if mode == "file":
        return _load_file_auth_snapshot()
    if mode == "keyring":
        return _load_keychain_auth_snapshot()
    return _load_keychain_auth_snapshot() or _load_file_auth_snapshot()


def _persist_auth_snapshot(snapshot: AuthSnapshot, raw_data: dict[str, object]) -> None:
    """Persist refreshed auth details back to the original storage backend."""
    serialized = json.dumps(raw_data, indent=2, sort_keys=True)
    if snapshot.storage_backend == "keychain" and snapshot.account_key:
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                snapshot.account_key,
                "-w",
                serialized,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "failed to update keychain auth")
        return

    CODEX_AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    CODEX_AUTH_PATH.write_text(serialized)


def _refresh_auth_snapshot(snapshot: AuthSnapshot) -> AuthSnapshot:
    """Refresh local ChatGPT auth using the official token refresh flow."""
    if not snapshot.refresh_token:
        raise _AuthExpiredError("No refresh token is available for Codex.")

    body = json.dumps(
        {
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": snapshot.refresh_token,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_REFRESH_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"CredCodex/{__version__}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code in {400, 401, 403}:
            raise _AuthExpiredError(detail or "Your Codex session has expired.") from exc
        raise _TransportError(detail or f"Token refresh failed ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise _TransportError(f"Token refresh failed: {exc.reason}") from exc

    existing_raw = {"auth_mode": snapshot.auth_mode}
    if snapshot.storage_backend == "file":
        text = _load_auth_json_text(CODEX_AUTH_PATH)
        if text:
            try:
                existing_raw = json.loads(text)
            except Exception:
                existing_raw = {"auth_mode": snapshot.auth_mode}
    elif snapshot.storage_backend == "keychain":
        keychain_snapshot = _load_keychain_auth_snapshot()
        if keychain_snapshot:
            try:
                result = subprocess.run(
                    [
                        "security",
                        "find-generic-password",
                        "-s",
                        KEYCHAIN_SERVICE,
                        "-a",
                        snapshot.account_key or "",
                        "-w",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode == 0:
                    existing_raw = json.loads(result.stdout.strip())
            except Exception:
                pass

    tokens = existing_raw.get("tokens") or {}
    tokens["access_token"] = payload.get("access_token") or snapshot.access_token
    tokens["refresh_token"] = payload.get("refresh_token") or snapshot.refresh_token
    if payload.get("id_token"):
        tokens["id_token"] = payload["id_token"]
    existing_raw["tokens"] = tokens
    existing_raw["last_refresh"] = _now().astimezone(timezone.utc).isoformat()
    _persist_auth_snapshot(snapshot, existing_raw)

    refreshed = load_auth_snapshot()
    if refreshed is None:
        raise _TransportError("Codex auth refresh succeeded, but refreshed credentials could not be reloaded.")
    return refreshed


def _offline_limit_info(
    error: str,
    failure_category: FailureCategory,
    auth_mode: str | None = None,
    source: str = "official (unavailable)",
    state: ProviderState = ProviderState.OFFLINE,
) -> LimitInfo:
    """Build a normalized empty-state result."""
    return LimitInfo(
        source=source,
        confidence=Confidence.LOW,
        state=state,
        failure_category=failure_category,
        error=error,
        last_sync=_now(),
        auth_mode=auth_mode,
    )


def _serialize_snapshot(info: LimitInfo) -> dict[str, object]:
    """Serialize a snapshot payload to disk."""
    return {
        "source": info.source,
        "confidence": info.confidence.value,
        "state": info.state.value,
        "failure_category": info.failure_category.value if info.failure_category else None,
        "error": info.error,
        "last_sync": info.last_sync.isoformat() if info.last_sync else None,
        "utilization_pct": info.utilization_pct,
        "resets_at": info.resets_at.isoformat() if info.resets_at else None,
        "plan_name": info.plan_name,
        "plan_tier": info.plan_tier,
        "weekly_utilization_pct": info.weekly_utilization_pct,
        "weekly_resets_at": info.weekly_resets_at.isoformat() if info.weekly_resets_at else None,
        "extra_usage_enabled": info.extra_usage_enabled,
        "extra_usage_monthly_limit": info.extra_usage_monthly_limit,
        "extra_usage_used": info.extra_usage_used,
        "extra_usage_utilization": info.extra_usage_utilization,
        "primary_window_minutes": info.primary_window_minutes,
        "secondary_window_minutes": info.secondary_window_minutes,
        "credits_balance": info.credits_balance,
        "credits_unlimited": info.credits_unlimited,
        "auth_mode": info.auth_mode,
        "saved_at": _now().isoformat(),
    }


def _info_from_snapshot(data: dict[str, object]) -> LimitInfo:
    """Deserialize a snapshot payload into a LimitInfo."""
    failure_category = data.get("failure_category")
    state = data.get("state")
    confidence = data.get("confidence")
    return LimitInfo(
        source=str(data.get("source") or "snapshot"),
        confidence=Confidence(confidence) if isinstance(confidence, str) else Confidence.HIGH,
        state=ProviderState(state) if isinstance(state, str) else ProviderState.STALE,
        failure_category=FailureCategory(failure_category) if isinstance(failure_category, str) else None,
        error=data.get("error") if isinstance(data.get("error"), str) else None,
        last_sync=_dt_from_any(data.get("last_sync")),
        utilization_pct=_normalize_utilization(data.get("utilization_pct")),
        resets_at=_dt_from_any(data.get("resets_at")),
        plan_name=data.get("plan_name") if isinstance(data.get("plan_name"), str) else None,
        plan_tier=data.get("plan_tier") if isinstance(data.get("plan_tier"), str) else None,
        weekly_utilization_pct=_normalize_utilization(data.get("weekly_utilization_pct")),
        weekly_resets_at=_dt_from_any(data.get("weekly_resets_at")),
        extra_usage_enabled=data.get("extra_usage_enabled")
        if isinstance(data.get("extra_usage_enabled"), bool)
        else None,
        extra_usage_monthly_limit=float(data["extra_usage_monthly_limit"])
        if isinstance(data.get("extra_usage_monthly_limit"), (int, float))
        else None,
        extra_usage_used=float(data["extra_usage_used"])
        if isinstance(data.get("extra_usage_used"), (int, float))
        else None,
        extra_usage_utilization=_normalize_utilization(data.get("extra_usage_utilization")),
        primary_window_minutes=int(data["primary_window_minutes"])
        if isinstance(data.get("primary_window_minutes"), (int, float))
        else None,
        secondary_window_minutes=int(data["secondary_window_minutes"])
        if isinstance(data.get("secondary_window_minutes"), (int, float))
        else None,
        credits_balance=data.get("credits_balance")
        if isinstance(data.get("credits_balance"), str)
        else None,
        credits_unlimited=data.get("credits_unlimited")
        if isinstance(data.get("credits_unlimited"), bool)
        else None,
        auth_mode=data.get("auth_mode") if isinstance(data.get("auth_mode"), str) else None,
    )


def _save_snapshot(info: LimitInfo) -> None:
    """Persist the last successful live result to disk."""
    if _is_expired(info):
        return
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(_serialize_snapshot(info), indent=2, sort_keys=True))


def _load_snapshot(startup_only: bool = False) -> LimitInfo | None:
    """Load a snapshot from disk, rejecting expired data."""
    try:
        payload = json.loads(SNAPSHOT_PATH.read_text())
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.debug("Failed to load snapshot: %s", exc)
        return None

    info = _info_from_snapshot(payload)
    if _is_expired(info):
        return None

    if startup_only:
        saved_at = _dt_from_any(payload.get("saved_at"))
        if saved_at is None:
            return None
        if (_now() - saved_at).total_seconds() > STARTUP_SNAPSHOT_MAX_AGE_SEC:
            return None

    return info


class LimitProvider(ABC):
    """Interface for normalized limit providers."""

    @abstractmethod
    def get_limit_info(self) -> LimitInfo:
        """Return the current normalized limit information."""

    @abstractmethod
    def get_state(self) -> ProviderState:
        """Return the provider health state."""


class _RateLimitedError(Exception):
    pass


class _AuthExpiredError(Exception):
    pass


class _TransportError(Exception):
    pass


class LiveCodexLimitProvider(LimitProvider):
    """Live Codex limits provider backed by the official ChatGPT usage flow."""

    def __init__(self) -> None:
        self._cached: LimitInfo | None = None
        self._cache_time: datetime | None = None
        self._retry_after: datetime | None = None
        self._retry_category: FailureCategory | None = None
        self._retry_error: str | None = None
        self._rate_limit_step = 0
        self._last_result: LimitInfo | None = None

    def get_state(self) -> ProviderState:
        if self._last_result is not None:
            return self._last_result.state
        if self._cache_is_fresh():
            return ProviderState.HEALTHY
        return ProviderState.OFFLINE

    def get_limit_info(self) -> LimitInfo:
        self._last_result = self._get_limit_info(force=False)
        return self._last_result

    def force_refresh(self) -> LimitInfo:
        if self._cached is not None:
            self._cache_time = None
        self._last_result = self._get_limit_info(force=True)
        return self._last_result

    def try_snapshot_startup(self) -> bool:
        snapshot = _load_snapshot(startup_only=True)
        if snapshot is None:
            return False
        self._cached = snapshot.with_overrides(
            state=ProviderState.STALE,
            failure_category=FailureCategory.STALE_CACHED_DATA,
            error="Loaded recent disk snapshot on startup.",
        )
        self._cache_time = _now()
        self._last_result = self._cached
        return True

    def _cache_is_fresh(self) -> bool:
        if self._cached is None or self._cache_time is None:
            return False
        if _is_expired(self._cached):
            self._cached = None
            self._cache_time = None
            return False
        return (_now() - self._cache_time).total_seconds() < IN_MEMORY_CACHE_TTL_SEC

    def _stale_cache_result(
        self,
        category: FailureCategory,
        error: str,
        state: ProviderState = ProviderState.STALE,
    ) -> LimitInfo | None:
        if self._cached is None or _is_expired(self._cached):
            return None
        return self._cached.with_overrides(
            state=state,
            failure_category=category,
            error=error,
            source=f"{self._cached.source}; cached",
        )

    def _retry_guard_active(self) -> bool:
        return bool(self._retry_after and self._retry_after > _now())

    def _set_retry_guard(self, seconds: int, category: FailureCategory, error: str) -> None:
        self._retry_after = _now() + timedelta(seconds=seconds)
        self._retry_category = category
        self._retry_error = error

    def _clear_retry_guard(self) -> None:
        self._retry_after = None
        self._retry_category = None
        self._retry_error = None

    def _request_usage(self, auth: AuthSnapshot) -> dict[str, object]:
        if not auth.access_token or not auth.account_id:
            raise _AuthExpiredError("Your local Codex ChatGPT session is incomplete.")

        request = urllib.request.Request(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {auth.access_token}",
                "chatgpt-account-id": auth.account_id,
                "User-Agent": f"CredCodex/{__version__}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 429:
                raise _RateLimitedError(body or "Rate limited by the Codex usage endpoint.") from exc
            if exc.code in {401, 403}:
                raise _AuthExpiredError(body or "Your Codex authentication has expired.") from exc
            raise _TransportError(body or f"Codex usage endpoint failed ({exc.code}).") from exc
        except urllib.error.URLError as exc:
            raise _TransportError(f"Failed to reach the Codex usage endpoint: {exc.reason}") from exc

    def _normalize_official_payload(self, payload: dict[str, object], auth: AuthSnapshot) -> LimitInfo:
        captured_at = _now()
        rate_limit = payload.get("rate_limit") or {}
        primary = rate_limit.get("primary_window") if isinstance(rate_limit, dict) else None
        secondary = rate_limit.get("secondary_window") if isinstance(rate_limit, dict) else None
        primary = primary if isinstance(primary, dict) else {}
        secondary = secondary if isinstance(secondary, dict) else {}

        primary_minutes = _window_minutes(primary)
        secondary_minutes = _window_minutes(secondary)
        primary_pct = _normalize_utilization(primary.get("used_percent"))
        secondary_pct = _normalize_utilization(secondary.get("used_percent"))
        primary_reset = _window_resets_at(primary, captured_at=captured_at)
        secondary_reset = _window_resets_at(secondary, captured_at=captured_at)

        credits = payload.get("credits")
        if not isinstance(credits, dict) and isinstance(rate_limit, dict):
            maybe_credits = rate_limit.get("credits")
            if isinstance(maybe_credits, dict):
                credits = maybe_credits

        plan_type = payload.get("plan_type")
        if plan_type is not None:
            plan_tier = str(plan_type)
            plan_name = plan_tier.replace("_", " ").title()
        else:
            plan_tier = None
            plan_name = None

        weekly_pct = secondary_pct if _is_weekly_window(secondary_minutes) else None
        weekly_reset = secondary_reset if _is_weekly_window(secondary_minutes) else None

        return LimitInfo(
            source="official (chatgpt codex usage)",
            confidence=Confidence.HIGH,
            state=ProviderState.HEALTHY,
            failure_category=None,
            error=None,
            last_sync=captured_at,
            utilization_pct=primary_pct,
            resets_at=primary_reset,
            plan_name=plan_name,
            plan_tier=plan_tier,
            weekly_utilization_pct=weekly_pct,
            weekly_resets_at=weekly_reset,
            primary_window_minutes=primary_minutes,
            secondary_window_minutes=secondary_minutes,
            credits_balance=credits.get("balance") if isinstance(credits, dict) else None,
            credits_unlimited=credits.get("unlimited") if isinstance(credits, dict) and isinstance(credits.get("unlimited"), bool) else None,
            auth_mode="chatgpt",
        )

    def _get_limit_info(self, force: bool) -> LimitInfo:
        if not force and self._cache_is_fresh() and self._cached is not None:
            return self._cached

        if not force and self._retry_guard_active():
            fallback = self._stale_cache_result(
                self._retry_category or FailureCategory.OFFLINE,
                self._retry_error or "Temporarily unavailable.",
            )
            if fallback is not None:
                return fallback
            return _offline_limit_info(
                error=self._retry_error or "Temporarily unavailable.",
                failure_category=self._retry_category or FailureCategory.OFFLINE,
                auth_mode="chatgpt",
                state=ProviderState.DEGRADED,
            )

        auth = load_auth_snapshot()
        if auth is None:
            fallback = self._stale_cache_result(
                FailureCategory.AUTH_EXPIRED,
                "No local Codex sign-in was found. Run `codex login`.",
            )
            if fallback is not None:
                return fallback
            return _offline_limit_info(
                error="No local Codex sign-in was found. Run `codex login`.",
                failure_category=FailureCategory.AUTH_EXPIRED,
                auth_mode=None,
                state=ProviderState.DEGRADED,
            )

        if auth.is_api_key_only or auth.auth_mode == "api_key":
            fallback = self._stale_cache_result(
                FailureCategory.UNSUPPORTED_AUTH_MODE,
                "API key auth does not expose Codex ChatGPT usage limits. Sign in with ChatGPT.",
                state=ProviderState.DEGRADED,
            )
            if fallback is not None:
                return fallback
            return _offline_limit_info(
                error="API key auth does not expose Codex ChatGPT usage limits. Sign in with ChatGPT.",
                failure_category=FailureCategory.UNSUPPORTED_AUTH_MODE,
                auth_mode="api_key",
                state=ProviderState.DEGRADED,
            )

        try:
            payload = self._request_usage(auth)
            info = self._normalize_official_payload(payload, auth)
            self._cached = info
            self._cache_time = _now()
            self._rate_limit_step = 0
            self._clear_retry_guard()
            _save_snapshot(info)
            return info

        except _RateLimitedError as exc:
            backoff = RATE_LIMIT_BACKOFF_STEPS_SEC[
                min(self._rate_limit_step, len(RATE_LIMIT_BACKOFF_STEPS_SEC) - 1)
            ]
            self._rate_limit_step = min(self._rate_limit_step + 1, len(RATE_LIMIT_BACKOFF_STEPS_SEC) - 1)
            self._set_retry_guard(backoff, FailureCategory.RATE_LIMITED, str(exc) or "Rate limited.")
            fallback = self._stale_cache_result(FailureCategory.RATE_LIMITED, str(exc) or "Rate limited.")
            if fallback is not None:
                return fallback
            return _offline_limit_info(
                error=str(exc) or "Rate limited.",
                failure_category=FailureCategory.RATE_LIMITED,
                auth_mode="chatgpt",
                state=ProviderState.DEGRADED,
            )

        except _AuthExpiredError as exc:
            try:
                refreshed = _refresh_auth_snapshot(auth)
                payload = self._request_usage(refreshed)
                info = self._normalize_official_payload(payload, refreshed)
                self._cached = info
                self._cache_time = _now()
                self._clear_retry_guard()
                _save_snapshot(info)
                return info
            except Exception as refresh_exc:
                message = str(refresh_exc) or str(exc) or "Your Codex session expired."
                self._set_retry_guard(
                    AUTH_RETRY_COOLDOWN_SEC,
                    FailureCategory.AUTH_EXPIRED,
                    message,
                )
                fallback = self._stale_cache_result(FailureCategory.AUTH_EXPIRED, message)
                if fallback is not None:
                    return fallback
                return _offline_limit_info(
                    error=message,
                    failure_category=FailureCategory.AUTH_EXPIRED,
                    auth_mode="chatgpt",
                    state=ProviderState.DEGRADED,
                )

        except _TransportError as exc:
            fallback = self._stale_cache_result(
                FailureCategory.STALE_CACHED_DATA,
                str(exc),
            )
            if fallback is not None:
                return fallback
            return _offline_limit_info(
                error=str(exc),
                failure_category=FailureCategory.OFFLINE,
                auth_mode="chatgpt",
            )


class LocalSessionLimitProvider(LimitProvider):
    """Fallback provider that reads recent local Codex session telemetry."""

    def __init__(self) -> None:
        self._last_result: LimitInfo | None = None

    def get_state(self) -> ProviderState:
        if self._last_result is None:
            return ProviderState.OFFLINE
        return self._last_result.state

    def get_limit_info(self) -> LimitInfo:
        self._last_result = self._load_latest_session_limit()
        return self._last_result

    def _load_latest_session_limit(self) -> LimitInfo:
        if not CODEX_SESSIONS_DIR.exists():
            return _offline_limit_info(
                error="No local Codex session telemetry was found.",
                failure_category=FailureCategory.OFFLINE,
                source="local session telemetry",
                state=ProviderState.OFFLINE,
            )

        latest_event: tuple[datetime, dict[str, object]] | None = None
        files = sorted(CODEX_SESSIONS_DIR.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)[:20]
        for path in files:
            try:
                lines = path.read_text().splitlines()
            except Exception:
                continue
            for line in reversed(lines):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("type") != "event_msg":
                    continue
                payload = item.get("payload") or {}
                if not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                rate_limits = payload.get("rate_limits")
                if not isinstance(rate_limits, dict):
                    continue
                timestamp = _dt_from_any(item.get("timestamp")) or _now()
                latest_event = (timestamp, rate_limits)
                break
            if latest_event is not None:
                break

        if latest_event is None:
            return _offline_limit_info(
                error="No usable Codex rate-limit telemetry was found in local sessions.",
                failure_category=FailureCategory.OFFLINE,
                source="local session telemetry",
            )

        captured_at, rate_limits = latest_event
        primary = rate_limits.get("primary") if isinstance(rate_limits.get("primary"), dict) else {}
        secondary = rate_limits.get("secondary") if isinstance(rate_limits.get("secondary"), dict) else {}
        credits = rate_limits.get("credits") if isinstance(rate_limits.get("credits"), dict) else {}
        primary_minutes = _window_minutes(primary)
        secondary_minutes = _window_minutes(secondary)
        age_seconds = (_now() - captured_at).total_seconds()
        state = ProviderState.DEGRADED if age_seconds <= SESSION_TELEMETRY_STALE_SEC else ProviderState.STALE
        failure_category = None if age_seconds <= SESSION_TELEMETRY_STALE_SEC else FailureCategory.STALE_CACHED_DATA

        return LimitInfo(
            source="local session telemetry",
            confidence=Confidence.MEDIUM if state == ProviderState.DEGRADED else Confidence.LOW,
            state=state,
            failure_category=failure_category,
            error=None if state == ProviderState.DEGRADED else "Local session telemetry is stale.",
            last_sync=captured_at,
            utilization_pct=_normalize_utilization(primary.get("used_percent")),
            resets_at=_window_resets_at(primary, captured_at=captured_at),
            plan_name=str(rate_limits.get("plan_type")).replace("_", " ").title()
            if rate_limits.get("plan_type") is not None
            else None,
            plan_tier=str(rate_limits.get("plan_type")) if rate_limits.get("plan_type") is not None else None,
            weekly_utilization_pct=_normalize_utilization(secondary.get("used_percent"))
            if _is_weekly_window(secondary_minutes)
            else None,
            weekly_resets_at=_window_resets_at(secondary, captured_at=captured_at)
            if _is_weekly_window(secondary_minutes)
            else None,
            primary_window_minutes=primary_minutes,
            secondary_window_minutes=secondary_minutes,
            credits_balance=credits.get("balance") if isinstance(credits, dict) else None,
            credits_unlimited=credits.get("unlimited")
            if isinstance(credits, dict) and isinstance(credits.get("unlimited"), bool)
            else None,
            auth_mode="chatgpt",
        )


class CompositeLimitProvider(LimitProvider):
    """App-facing orchestration entrypoint for all provider paths."""

    def __init__(self, config: dict[str, object] | None = None) -> None:
        self._config = config or {}
        self._live = LiveCodexLimitProvider()
        self._local = LocalSessionLimitProvider()
        self._last_result: LimitInfo | None = None

    def update_config(self, config: dict[str, object]) -> None:
        self._config = config

    def get_state(self) -> ProviderState:
        if self._last_result is not None:
            return self._last_result.state
        return self._live.get_state()

    def try_snapshot_startup(self) -> bool:
        ok = self._live.try_snapshot_startup()
        if ok:
            self._last_result = self._live.get_limit_info()
        return ok

    def force_refresh(self) -> LimitInfo:
        live_result = self._live.force_refresh()
        self._last_result = self._merge_fallbacks(live_result)
        return self._last_result

    def get_limit_info(self) -> LimitInfo:
        live_result = self._live.get_limit_info()
        self._last_result = self._merge_fallbacks(live_result)
        return self._last_result

    def _merge_fallbacks(self, live_result: LimitInfo) -> LimitInfo:
        if live_result.has_live_utilization:
            return live_result

        snapshot = _load_snapshot()
        if snapshot is not None:
            return snapshot.with_overrides(
                source=f"{snapshot.source}; disk snapshot",
                state=ProviderState.STALE,
                failure_category=live_result.failure_category or FailureCategory.STALE_CACHED_DATA,
                error=live_result.error or "Using a saved disk snapshot.",
                auth_mode=live_result.auth_mode or snapshot.auth_mode,
            )

        local = self._local.get_limit_info()
        if local.has_live_utilization:
            return local.with_overrides(
                failure_category=live_result.failure_category if local.failure_category is None else local.failure_category,
                error=live_result.error or local.error,
                auth_mode=live_result.auth_mode or local.auth_mode,
            )

        return live_result
