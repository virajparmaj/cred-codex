"""Tests for icon asset path resolution."""

from __future__ import annotations

from pathlib import Path

from credcodex import icon_assets


class _FakeBundle:
    def __init__(self, resource_dir: Path) -> None:
        self._resource_dir = resource_dir

    def resourcePath(self) -> str:
        return str(self._resource_dir)


class _FakeNSBundle:
    def __init__(self, resource_dir: Path) -> None:
        self._resource_dir = resource_dir

    def mainBundle(self) -> _FakeBundle:
        return _FakeBundle(self._resource_dir)


def test_menu_bar_icon_path_returns_checked_in_asset(repo_root: Path):
    path = icon_assets.menu_bar_icon_path()
    assert path == repo_root / "assets" / "credcodex_menubar.png"
    assert path.exists()


def test_menu_bar_icon_2x_path_returns_checked_in_asset(repo_root: Path):
    path = icon_assets.menu_bar_icon_2x_path()
    assert path == repo_root / "assets" / "credcodex_menubar@2x.png"
    assert path.exists()


def test_runtime_icon_prefers_bundle_runtime_png(tmp_path, monkeypatch):
    resource_dir = tmp_path / "Resources"
    resource_dir.mkdir()
    runtime_png = resource_dir / "AppIconRuntime.png"
    runtime_png.write_bytes(b"png")
    (resource_dir / "AppIcon.icns").write_bytes(b"icns")

    monkeypatch.setattr(icon_assets, "NSBundle", _FakeNSBundle(resource_dir))
    monkeypatch.setattr(icon_assets, "DIST_RESOURCES_DIR", tmp_path / "dist")
    monkeypatch.setattr(icon_assets, "RUNTIME_FALLBACK_ICON", tmp_path / "fallback.png")

    assert icon_assets.runtime_icon_path() == runtime_png


def test_runtime_icon_falls_back_to_bundle_icns(tmp_path, monkeypatch):
    resource_dir = tmp_path / "Resources"
    resource_dir.mkdir()
    icns = resource_dir / "AppIcon.icns"
    icns.write_bytes(b"icns")

    monkeypatch.setattr(icon_assets, "NSBundle", _FakeNSBundle(resource_dir))
    monkeypatch.setattr(icon_assets, "DIST_RESOURCES_DIR", tmp_path / "dist")
    monkeypatch.setattr(icon_assets, "RUNTIME_FALLBACK_ICON", tmp_path / "fallback.png")

    assert icon_assets.runtime_icon_path() == icns


def test_runtime_icon_falls_back_to_checked_in_asset(tmp_path, monkeypatch):
    fallback = tmp_path / "assets" / "icons" / "macos" / "credcodex_icon_512.png"
    fallback.parent.mkdir(parents=True)
    fallback.write_bytes(b"png")

    monkeypatch.setattr(icon_assets, "NSBundle", None)
    monkeypatch.setattr(icon_assets, "DIST_RESOURCES_DIR", tmp_path / "dist")
    monkeypatch.setattr(icon_assets, "RUNTIME_FALLBACK_ICON", fallback)

    assert icon_assets.runtime_icon_path() == fallback
