"""Native settings window for CredCodex."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Callable

from credcodex import __version__
from credcodex.config import DEFAULT_CONFIG, LOG_PATH, save_config, sanitize_config
from credcodex.icon_assets import runtime_icon_path

try:
    import objc
    from AppKit import (
        NSBackingStoreBuffered,
        NSButton,
        NSClosableWindowMask,
        NSFont,
        NSImage,
        NSLeftTextAlignment,
        NSMakeRect,
        NSMiniaturizableWindowMask,
        NSObject,
        NSSwitch,
        NSTextField,
        NSTitledWindowMask,
        NSWindow,
    )
except Exception:  # pragma: no cover - exercised only on non-macOS test paths.
    objc = None
    NSObject = object
    NSImage = None
    NSWindow = None


def _label(text: str, x: float, y: float, w: float = 240, h: float = 18, size: float = 13) -> object:
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setAlignment_(NSLeftTextAlignment)
    field.setFont_(NSFont.systemFontOfSize_(size))
    return field


def _input(x: float, y: float, value: str, w: float = 72, h: float = 22) -> object:
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    field.setStringValue_(value)
    field.setFont_(NSFont.systemFontOfSize_(13))
    return field


if objc is not None:
    class _SettingsDelegate(NSObject):
        """Window delegate and action callbacks."""

        window_ref = objc.ivar()

        def windowWillClose_(self, _notification):
            if self.window_ref is not None:
                self.window_ref._save_and_close()

        def onToggle_(self, _sender):
            if self.window_ref is not None:
                self.window_ref._sync_enabled_state()

        def onViewLogs_(self, _sender):
            if self.window_ref is not None:
                self.window_ref._open_logs()

        def onResetDefaults_(self, _sender):
            if self.window_ref is not None:
                self.window_ref._reset_defaults()


if NSWindow is None:  # pragma: no cover - macOS-only execution path.
    class SettingsWindow:
        """Fallback stub when AppKit is unavailable."""

        @classmethod
        def show(cls, _config: dict[str, object], _on_save: Callable[[dict[str, object]], None], data_source: str = "") -> None:
            raise RuntimeError(f"CredCodex settings require AppKit. Current source: {data_source}")


else:
    class SettingsWindow:  # pragma: no cover - AppKit runtime not exercised in unit tests.
        """Singleton native settings window."""

        _instance: "SettingsWindow | None" = None

        def __init__(self, config: dict[str, object], on_save: Callable[[dict[str, object]], None], data_source: str) -> None:
            self._config = sanitize_config(config)
            self._on_save = on_save
            self._data_source = data_source

        @classmethod
        def show(
            cls,
            config: dict[str, object],
            on_save: Callable[[dict[str, object]], None],
            data_source: str = "",
        ) -> None:
            if cls._instance is not None:
                cls._instance._window.makeKeyAndOrderFront_(None)
                return
            instance = cls(config, on_save, data_source)
            cls._instance = instance
            instance._build()
            instance._window.center()
            instance._window.makeKeyAndOrderFront_(None)

        def _build(self) -> None:
            style = NSTitledWindowMask | NSClosableWindowMask | NSMiniaturizableWindowMask
            self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 460, 300),
                style,
                NSBackingStoreBuffered,
                False,
            )
            self._window.setTitle_("CredCodex Settings")
            self._window.setReleasedWhenClosed_(False)
            icon_path = runtime_icon_path()
            if NSImage is not None and icon_path.exists():
                mini_icon = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
                if mini_icon:
                    self._window.setMiniwindowImage_(mini_icon)

            delegate = _SettingsDelegate.alloc().init()
            delegate.window_ref = self
            self._delegate = delegate
            self._window.setDelegate_(delegate)

            content = self._window.contentView()
            content.addSubview_(_label("Auto-refresh", 24, 246))
            content.addSubview_(_label("Refresh interval (sec)", 24, 208))
            content.addSubview_(_label("Auto re-authenticate", 24, 170))
            content.addSubview_(_label("Re-auth cooldown (sec)", 24, 132))
            content.addSubview_(_label(f"Version: {__version__}", 24, 88, size=12))
            content.addSubview_(_label(f"Data source: {self._data_source or 'Waiting for provider'}", 24, 64, w=400, size=12))

            self._auto_refresh_switch = NSSwitch.alloc().initWithFrame_(NSMakeRect(320, 238, 48, 24))
            self._auto_refresh_switch.setState_(1 if self._config.get("auto_refresh", True) else 0)
            self._auto_refresh_switch.setTarget_(self._delegate)
            self._auto_refresh_switch.setAction_("onToggle:")
            content.addSubview_(self._auto_refresh_switch)

            self._refresh_field = _input(320, 204, str(self._config.get("refresh_interval_sec", 60)))
            content.addSubview_(self._refresh_field)

            self._auto_reauth_switch = NSSwitch.alloc().initWithFrame_(NSMakeRect(320, 162, 48, 24))
            self._auto_reauth_switch.setState_(1 if self._config.get("auto_reauth_enabled", True) else 0)
            self._auto_reauth_switch.setTarget_(self._delegate)
            self._auto_reauth_switch.setAction_("onToggle:")
            content.addSubview_(self._auto_reauth_switch)

            self._reauth_field = _input(320, 128, str(self._config.get("auto_reauth_cooldown_sec", 1800)))
            content.addSubview_(self._reauth_field)

            view_logs = NSButton.alloc().initWithFrame_(NSMakeRect(24, 20, 120, 28))
            view_logs.setTitle_("View Logs")
            view_logs.setTarget_(self._delegate)
            view_logs.setAction_("onViewLogs:")
            content.addSubview_(view_logs)

            reset_defaults = NSButton.alloc().initWithFrame_(NSMakeRect(156, 20, 140, 28))
            reset_defaults.setTitle_("Reset to Defaults")
            reset_defaults.setTarget_(self._delegate)
            reset_defaults.setAction_("onResetDefaults:")
            content.addSubview_(reset_defaults)

            self._sync_enabled_state()

        def _sync_enabled_state(self) -> None:
            enabled = bool(self._auto_refresh_switch.state())
            self._refresh_field.setEditable_(enabled)
            self._refresh_field.setEnabled_(enabled)
            self._reauth_field.setEditable_(True)
            self._reauth_field.setEnabled_(True)

        def _open_logs(self) -> None:
            Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(LOG_PATH)], capture_output=True, text=True, check=False)

        def _reset_defaults(self) -> None:
            defaults = sanitize_config(DEFAULT_CONFIG)
            self._auto_refresh_switch.setState_(1 if defaults["auto_refresh"] else 0)
            self._refresh_field.setStringValue_(str(defaults["refresh_interval_sec"]))
            self._auto_reauth_switch.setState_(1 if defaults["auto_reauth_enabled"] else 0)
            self._reauth_field.setStringValue_(str(defaults["auto_reauth_cooldown_sec"]))
            self._sync_enabled_state()

        def _save_and_close(self) -> None:
            config = {
                "auto_refresh": bool(self._auto_refresh_switch.state()),
                "refresh_interval_sec": self._refresh_field.stringValue(),
                "auto_reauth_enabled": bool(self._auto_reauth_switch.state()),
                "auto_reauth_cooldown_sec": self._reauth_field.stringValue(),
            }
            saved = save_config(config)
            self._on_save(saved)
            SettingsWindow._instance = None
