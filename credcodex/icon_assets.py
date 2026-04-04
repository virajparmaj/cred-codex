"""Shared icon asset lookups for CredCodex."""

from __future__ import annotations

from pathlib import Path

from credcodex.config import APP_NAME

try:
    from AppKit import NSBundle
except Exception:  # pragma: no cover - exercised only on non-macOS test paths.
    NSBundle = None


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_ROOT / "assets"
MENU_BAR_ICON = ASSETS_DIR / "credcodex_menubar.png"
RUNTIME_FALLBACK_ICON = ASSETS_DIR / "icons" / "macos" / "credcodex_icon_512.png"
DIST_RESOURCES_DIR = REPO_ROOT / "dist" / f"{APP_NAME}.app" / "Contents" / "Resources"


def _bundle_resources_dir() -> Path | None:
    """Return the current app bundle's Resources directory when available."""
    if NSBundle is None:
        return None
    try:
        resource_path = NSBundle.mainBundle().resourcePath()
    except Exception:
        return None
    if not resource_path:
        return None
    return Path(str(resource_path))


def _resource_candidate(name: str) -> Path | None:
    """Resolve a resource name from the live bundle or local dist bundle."""
    bundle_dir = _bundle_resources_dir()
    if bundle_dir is not None:
        candidate = bundle_dir / name
        if candidate.exists():
            return candidate

    candidate = DIST_RESOURCES_DIR / name
    if candidate.exists():
        return candidate
    return None


def menu_bar_icon_path() -> Path:
    """Return the checked-in menu bar icon asset."""
    return MENU_BAR_ICON


def runtime_icon_path() -> Path:
    """Return the runtime icon, preferring bundled resources when present."""
    for name in ("AppIconRuntime.png", "AppIcon.icns"):
        candidate = _resource_candidate(name)
        if candidate is not None:
            return candidate
    return RUNTIME_FALLBACK_ICON
