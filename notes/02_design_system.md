# 02 — Design System

## Context

CredCodex has no web frontend and no CSS. The entire UI is a native macOS menu bar app rendered with `rumps` and `AppKit` via PyObjC. There is no formal design system.

## Visual direction (`credcodex/app.py`, `build_app.sh`)

- **Status bar title**: text-only, uses a compact `{pct}% | {countdown}` format or short emoji-prefixed state labels (`⚠ auth`, `⏸ stale`).
- **Progress bars**: fixed-width Unicode block bars (`█` filled, `░` empty), 15 chars wide by default — `make_bar()` in `app.py:86`.
- **App icon**: checked-in macOS artwork built from `assets/icons/macos/credcodex_icon_*.png` plus dedicated menu bar assets in `assets/credcodex_menubar*.png`.

## Typography

- Settings window uses `NSFont.systemFontOfSize_(13)` for labels and inputs (`credcodex/settings.py`).
- Version and data-source labels use `size=12`.
- `Confirmed from code`; no custom fonts.

## Colors and tokens

- `Not found in repository` — no color constants defined. The menu bar title inherits system menu bar colors.
- App icon color and composition now come from the checked-in raster assets rather than hardcoded pixel math in `build_app.sh`.

## Spacing / layout

- Settings window: `460 × 300 px` (`NSMakeRect(0, 0, 460, 300)` in `settings.py:114`).
- Controls laid out with hardcoded `NSMakeRect` coordinates — no auto-layout.
- `Confirmed from code`.

## Interaction

- Menu refresh triggered on open if last refresh was > 30s ago (`MENU_OPEN_STALE_SEC = 30` in `config.py`).
- Settings auto-saves on window close (no "Save" button).
- Notifications use macOS Glass sound.

## Consistency issues

- Hardcoded pixel coordinates in `settings.py` — resizing the window would break the layout.
- No dark/light mode adaptation beyond what macOS applies automatically to system controls.
