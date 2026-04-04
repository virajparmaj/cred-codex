"""Menu bar app and pure UI rendering helpers for CredCodex."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time

from credcodex import __version__
from credcodex.auth_launcher import ReauthGate, launch_codex_login
from credcodex.config import (
    APP_NAME,
    MENU_OPEN_STALE_SEC,
    REAUTH_NOTIFICATION_LOCK,
    RESET_NOTIFICATION_LOCK,
    clamp_reauth_cooldown,
    load_config,
)
from credcodex.icon_assets import menu_bar_icon_path, runtime_icon_path
from credcodex.limit_providers import CompositeLimitProvider
from credcodex.models import FailureCategory, LimitInfo, ProviderState
from credcodex.notifications import (
    cleanup_notification_locks,
    send_notification,
    should_notify_once,
    write_lock,
)

logger = logging.getLogger("credcodex.app")

try:
    import objc
    import rumps
    from AppKit import NSApplication, NSBundle, NSImage, NSObject
    from Foundation import NSProcessInfo
except Exception:  # pragma: no cover - exercised only on non-macOS test paths.
    objc = None
    rumps = None
    NSApplication = None
    NSBundle = None
    NSImage = None
    NSObject = object
    NSProcessInfo = None


def format_relative_countdown(target: datetime | None, now: datetime | None = None) -> str:
    """Render a compact relative countdown."""
    if target is None:
        return "--"
    current = now or datetime.now(timezone.utc).astimezone()
    delta = target - current
    seconds = max(0, int(delta.total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m"
    return "now"


def format_menu_datetime(target: datetime | None) -> str:
    """Render an absolute local reset time for dropdown rows."""
    if target is None:
        return "--"
    localized = target.astimezone()
    hour = localized.strftime("%I").lstrip("0") or "0"
    return f"{localized.strftime('%b')} {localized.day}, {hour}:{localized.strftime('%M %p')}"


def make_bar(percent_used: float | None, width: int = 15) -> str:
    """Render a fixed-width percent bar."""
    if percent_used is None:
        return "░" * width
    filled = max(0, min(width, int(round((percent_used / 100.0) * width))))
    return ("█" * filled) + ("░" * (width - filled))


def derive_title(limit: LimitInfo, now: datetime | None = None) -> str:
    """Return the short menu bar title."""
    if limit.utilization_pct is not None and limit.resets_at is not None:
        return f"{limit.utilization_pct:.0f}% | {format_relative_countdown(limit.resets_at, now=now)}"
    if limit.utilization_pct is not None:
        return f"{limit.utilization_pct:.0f}%"
    if limit.failure_category in {FailureCategory.AUTH_EXPIRED, FailureCategory.UNSUPPORTED_AUTH_MODE}:
        return "⚠ auth"
    if limit.failure_category == FailureCategory.RATE_LIMITED:
        return "⚠ wait"
    if limit.state == ProviderState.STALE:
        return "⏸ stale"
    if limit.state == ProviderState.OFFLINE:
        return "⏸ off"
    return "⏸ --"


@dataclass
class MenuSections:
    """Pure render state for optional dropdown rows."""

    plan_title: str | None = None
    weekly_title: str | None = None
    weekly_reset_title: str | None = None
    credits_title: str | None = None
    extra_title: str | None = None

    @property
    def has_any_info(self) -> bool:
        return any(
            value is not None
            for value in (
                self.plan_title,
                self.weekly_title,
                self.weekly_reset_title,
                self.credits_title,
                self.extra_title,
            )
        )


def derive_menu_sections(limit: LimitInfo) -> MenuSections:
    """Return visible menu rows for the current limit info."""
    plan_label = None
    plan_value = limit.plan_name or limit.plan_tier
    if plan_value:
        plan_label = f"Plan: {str(plan_value).replace('_', ' ').title()}"

    weekly_title = None
    weekly_reset = None
    if limit.weekly_utilization_pct is not None:
        weekly_title = f"Weekly: {make_bar(limit.weekly_utilization_pct)} {limit.weekly_utilization_pct:.0f}%"
    if limit.weekly_resets_at is not None:
        weekly_reset = f"  Resets: {format_menu_datetime(limit.weekly_resets_at)}"

    credits_title = None
    if limit.credits_unlimited is True:
        credits_title = "Credits: Unlimited"
    elif limit.credits_balance:
        credits_title = f"Credits: {limit.credits_balance} credits"

    extra_title = None
    if limit.extra_usage_enabled is True:
        if limit.extra_usage_utilization is not None:
            extra_title = f"Extra usage: {make_bar(limit.extra_usage_utilization)} {limit.extra_usage_utilization:.0f}%"
        elif limit.extra_usage_used is not None and limit.extra_usage_monthly_limit is not None:
            extra_title = (
                f"Extra usage: ${limit.extra_usage_used:.2f}"
                f" / ${limit.extra_usage_monthly_limit:.2f}"
            )
        else:
            extra_title = "Extra usage: enabled"

    return MenuSections(
        plan_title=plan_label,
        weekly_title=weekly_title,
        weekly_reset_title=weekly_reset,
        credits_title=credits_title,
        extra_title=extra_title,
    )


if objc is not None:
    class _MenuDelegate(NSObject):
        """Refresh the menu when it opens after the stale threshold."""

        app_ref = objc.ivar()

        def menuWillOpen_(self, _menu):
            app = self.app_ref
            if app is None:
                return
            if time.monotonic() - app._last_refresh_time >= MENU_OPEN_STALE_SEC:
                app._refresh_now(None)


if rumps is None:  # pragma: no cover - macOS-only execution path.
    class CredCodexApp:
        """Fallback stub when macOS UI dependencies are unavailable."""

        def __init__(self) -> None:
            raise RuntimeError("CredCodex requires rumps and PyObjC to run on macOS.")


else:
    class CredCodexApp(rumps.App):  # pragma: no cover - UI runtime not exercised in unit tests.
        """CredCodex menu bar application."""

        def __init__(self) -> None:
            info = NSBundle.mainBundle().infoDictionary() if NSBundle is not None else None
            if info is not None:
                info["CFBundleName"] = APP_NAME
                info["CFBundleDisplayName"] = APP_NAME

            status_icon = menu_bar_icon_path()
            super().__init__(APP_NAME, title=None, icon=str(status_icon) if status_icon else None, quit_button=None)

            if NSApplication is not None and NSProcessInfo is not None:
                dock_icon = runtime_icon_path()
                if dock_icon is not None and dock_icon.exists():
                    ns_icon = NSImage.alloc().initWithContentsOfFile_(str(dock_icon))
                    if ns_icon:
                        NSApplication.sharedApplication().setApplicationIconImage_(ns_icon)
                NSProcessInfo.processInfo().setValue_forKey_(APP_NAME, "processName")

            self.config = load_config()
            self._provider = CompositeLimitProvider(self.config)
            self._reauth_gate = ReauthGate(self._reauth_cooldown_sec())
            self._last_limit: LimitInfo | None = None
            self._last_refresh_time = 0.0

            cleanup_notification_locks()

            noop = lambda _: None
            self._plan_item = rumps.MenuItem("Plan: --", callback=noop)
            self._weekly_item = rumps.MenuItem("Weekly: --", callback=noop)
            self._weekly_reset_item = rumps.MenuItem("  Resets: --", callback=noop)
            self._credits_item = rumps.MenuItem("Credits: --", callback=noop)
            self._extra_item = rumps.MenuItem("Extra usage: --", callback=noop)
            self._info_separator = rumps.MenuItem("")
            self.menu = [
                self._plan_item,
                self._weekly_item,
                self._weekly_reset_item,
                self._credits_item,
                self._extra_item,
                self._info_separator,
                rumps.MenuItem("Refresh", callback=self._refresh_now),
                rumps.MenuItem("Re-authenticate", callback=self._reauth_now),
                rumps.MenuItem("Settings", callback=self._show_settings),
                rumps.separator,
                rumps.MenuItem("Quit", callback=rumps.quit_application),
            ]

            info_separator = self._info_separator._menuitem
            info_menu = info_separator.menu()
            if info_menu is not None:
                index = info_menu.indexOfItem_(info_separator)
                info_menu.removeItemAtIndex_(index)
                real_separator = __import__("AppKit").NSMenuItem.separatorItem()
                info_menu.insertItem_atIndex_(real_separator, index)
                self._info_separator._menuitem = real_separator

            self._set_info_visibility(MenuSections())

            self._menu_delegate = _MenuDelegate.alloc().init()
            self._menu_delegate.app_ref = self
            ns_menu = getattr(self._menu, "_menu", None)
            if ns_menu is not None:
                ns_menu.setDelegate_(self._menu_delegate)

            self._startup_timer = rumps.Timer(self._startup_update, 1)
            self._startup_timer.start()
            self._refresh_timer = rumps.Timer(self._tick, int(self.config.get("refresh_interval_sec", 60)))
            if self.config.get("auto_refresh", True):
                self._refresh_timer.start()
            logger.info("CredCodex started (v%s)", __version__)

        def _set_info_visibility(self, sections: MenuSections) -> None:
            self._plan_item._menuitem.setHidden_(sections.plan_title is None)
            self._weekly_item._menuitem.setHidden_(sections.weekly_title is None)
            self._weekly_reset_item._menuitem.setHidden_(sections.weekly_reset_title is None)
            self._credits_item._menuitem.setHidden_(sections.credits_title is None)
            self._extra_item._menuitem.setHidden_(sections.extra_title is None)
            self._info_separator._menuitem.setHidden_(not sections.has_any_info)

        def _startup_update(self, sender) -> None:
            sender.stop()
            if self._provider.try_snapshot_startup():
                self._apply_limit(self._provider.get_limit_info())
                return
            self._update()

        def _tick(self, _sender) -> None:
            self.config = load_config()
            self._provider.update_config(self.config)
            self._reauth_gate.update_cooldown(self._reauth_cooldown_sec())
            self._update()

        def _update(self) -> None:
            try:
                self._apply_limit(self._provider.get_limit_info())
            except Exception as exc:
                logger.error("Update cycle failed: %s", exc, exc_info=True)
                self.title = "⚠ err"

        def _apply_limit(self, limit: LimitInfo) -> None:
            previous = self._last_limit
            sections = derive_menu_sections(limit)

            self.title = derive_title(limit)
            if sections.plan_title:
                self._plan_item.title = sections.plan_title
            if sections.weekly_title:
                self._weekly_item.title = sections.weekly_title
            if sections.weekly_reset_title:
                self._weekly_reset_item.title = sections.weekly_reset_title
            if sections.credits_title:
                self._credits_item.title = sections.credits_title
            if sections.extra_title:
                self._extra_item.title = sections.extra_title

            self._set_info_visibility(sections)
            self._last_limit = limit
            self._last_refresh_time = time.monotonic()
            self._maybe_notify_reset_available(previous, limit)
            self._maybe_auto_reauth(limit)

        def _maybe_notify_reset_available(self, previous: LimitInfo | None, current: LimitInfo) -> None:
            now = datetime.now(timezone.utc).astimezone()
            if previous is None or previous.resets_at is None:
                return
            if previous.resets_at > now:
                return
            if current.resets_at is None or current.resets_at == previous.resets_at:
                return
            value = previous.resets_at.isoformat()
            if not should_notify_once(RESET_NOTIFICATION_LOCK, value):
                return
            send_notification("CredCodex reset available", "Your Codex limit window appears to have reset.")
            write_lock(RESET_NOTIFICATION_LOCK, value)

        def _maybe_auto_reauth(self, limit: LimitInfo) -> None:
            if not self.config.get("auto_reauth_enabled", True):
                return
            if not self._reauth_gate.eligible_for_auto_launch(limit.error, category=limit.failure_category):
                return
            self._trigger_reauth(auto=True, reason="provider requested re-auth")

        def _trigger_reauth(self, auto: bool, reason: str) -> None:
            self._reauth_gate.mark_attempt()
            result = launch_codex_login()
            value = f"{'ok' if result.success else 'err'}:{result.message}"
            if should_notify_once(REAUTH_NOTIFICATION_LOCK, value):
                send_notification("CredCodex re-authentication", result.message)
                write_lock(REAUTH_NOTIFICATION_LOCK, value)
            logger.info("Re-auth launch (%s): %s", reason, result.message)

        def _refresh_now(self, sender) -> None:
            self.config = load_config()
            self._provider.update_config(self.config)
            if sender is not None:
                self._apply_limit(self._provider.force_refresh())
            else:
                self._update()

        def _reauth_now(self, _sender) -> None:
            self._trigger_reauth(auto=False, reason="manual menu action")

        def _show_settings(self, _sender) -> None:
            from credcodex.settings import SettingsWindow

            current_source = self._last_limit.source if self._last_limit is not None else "Waiting for provider"
            SettingsWindow.show(self.config, self._on_settings_saved, data_source=current_source)

        def _on_settings_saved(self, config: dict[str, object]) -> None:
            previous_interval = int(self.config.get("refresh_interval_sec", 60))
            previous_auto = bool(self.config.get("auto_refresh", True))
            self.config = config
            self._provider.update_config(config)
            self._reauth_gate.update_cooldown(self._reauth_cooldown_sec())
            next_interval = int(config.get("refresh_interval_sec", 60))
            next_auto = bool(config.get("auto_refresh", True))

            if previous_auto != next_auto or previous_interval != next_interval:
                self._refresh_timer.stop()
                self._refresh_timer = rumps.Timer(self._tick, next_interval)
                if next_auto:
                    self._refresh_timer.start()

        def _reauth_cooldown_sec(self) -> int:
            return clamp_reauth_cooldown(self.config.get("auto_reauth_cooldown_sec", 1800))
