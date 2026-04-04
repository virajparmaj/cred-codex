"""Shared data models for CredCodex."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Confidence(Enum):
    """Confidence level for normalized provider data."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ProviderState(Enum):
    """Health state for provider output."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    OFFLINE = "offline"


class FailureCategory(Enum):
    """Normalized failure reasons for UI and fallback handling."""

    AUTH_EXPIRED = "auth_expired"
    RATE_LIMITED = "rate_limited"
    STALE_CACHED_DATA = "stale_cached_data"
    OFFLINE = "offline"
    UNSUPPORTED_AUTH_MODE = "unsupported_auth_mode"


@dataclass
class LimitInfo:
    """Normalized account limit information."""

    source: str
    confidence: Confidence = Confidence.LOW
    state: ProviderState = ProviderState.OFFLINE
    failure_category: FailureCategory | None = None
    error: str | None = None
    last_sync: datetime | None = None
    utilization_pct: float | None = None
    resets_at: datetime | None = None
    plan_name: str | None = None
    plan_tier: str | None = None
    weekly_utilization_pct: float | None = None
    weekly_resets_at: datetime | None = None
    extra_usage_enabled: bool | None = None
    extra_usage_monthly_limit: float | None = None
    extra_usage_used: float | None = None
    extra_usage_utilization: float | None = None
    primary_window_minutes: int | None = None
    secondary_window_minutes: int | None = None
    credits_balance: str | None = None
    credits_unlimited: bool | None = None
    auth_mode: str | None = None

    def with_overrides(self, **changes: object) -> "LimitInfo":
        """Return a shallow copy with selected fields replaced."""
        data = self.__dict__.copy()
        data.update(changes)
        return LimitInfo(**data)

    @property
    def has_live_utilization(self) -> bool:
        """Return True when a visible live utilization value exists."""
        return self.utilization_pct is not None
