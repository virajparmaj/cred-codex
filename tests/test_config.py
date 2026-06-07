"""Tests for config loading and persistence."""

from __future__ import annotations

import json

import pytest

from credcodex import config as config_mod


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    app_dir = tmp_path / ".credcodex"
    config_path = app_dir / "config.json"
    log_path = app_dir / "credcodex.log"
    notif_dir = app_dir / "notifications"
    monkeypatch.setattr(config_mod, "APP_DIR", app_dir)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_mod, "LOG_PATH", log_path)
    monkeypatch.setattr(config_mod, "NOTIFICATION_DIR", notif_dir)
    monkeypatch.setattr(config_mod, "RESET_NOTIFICATION_LOCK", notif_dir / "last_reset_available.txt")
    monkeypatch.setattr(config_mod, "REAUTH_NOTIFICATION_LOCK", notif_dir / "last_reauth_notice.txt")
    return config_path


class TestLoadConfig:
    def test_returns_defaults_when_missing(self, isolated_config):
        loaded = config_mod.load_config()
        assert loaded["auto_refresh"] is True
        assert loaded["refresh_interval_sec"] == 60
        assert loaded["auto_reauth_enabled"] is True
        assert loaded["auto_reauth_cooldown_sec"] == 1800

    def test_reads_existing_config(self, isolated_config):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text(json.dumps({"auto_refresh": False, "refresh_interval_sec": 120}))
        loaded = config_mod.load_config()
        assert loaded["auto_refresh"] is False
        assert loaded["refresh_interval_sec"] == 120

    def test_invalid_values_clamp_to_safe_ranges(self, isolated_config):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text(
            json.dumps(
                {
                    "auto_refresh": True,
                    "refresh_interval_sec": -10,
                    "auto_reauth_enabled": "yes",
                    "auto_reauth_cooldown_sec": 999999,
                }
            )
        )
        loaded = config_mod.load_config()
        assert loaded["refresh_interval_sec"] == 60
        assert loaded["auto_reauth_enabled"] is True
        assert loaded["auto_reauth_cooldown_sec"] == 1800

    def test_corrupt_file_uses_defaults(self, isolated_config):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text("{bad json")
        loaded = config_mod.load_config()
        assert loaded == config_mod.DEFAULT_CONFIG

    def test_keepalive_defaults(self, isolated_config):
        loaded = config_mod.load_config()
        assert loaded["keepalive_enabled"] is True
        assert loaded["keepalive_wake_system_enabled"] is False
        assert loaded["codex_bin"] is None


class TestSanitizeKeepalive:
    def test_flags_coerced_to_bool(self):
        cfg = config_mod.sanitize_config(
            {"keepalive_enabled": 0, "keepalive_wake_system_enabled": "yes"}
        )
        assert cfg["keepalive_enabled"] is False
        assert cfg["keepalive_wake_system_enabled"] is True

    def test_codex_bin_valid_string_preserved(self):
        cfg = config_mod.sanitize_config({"codex_bin": "  /opt/homebrew/bin/codex  "})
        assert cfg["codex_bin"] == "/opt/homebrew/bin/codex"

    def test_codex_bin_invalid_resets_to_none(self):
        assert config_mod.sanitize_config({"codex_bin": ""})["codex_bin"] is None
        assert config_mod.sanitize_config({"codex_bin": 123})["codex_bin"] is None
        assert config_mod.sanitize_config({"codex_bin": None})["codex_bin"] is None


class TestSaveConfig:
    def test_round_trip(self, isolated_config):
        saved = config_mod.save_config(
            {
                "auto_refresh": False,
                "refresh_interval_sec": 90,
                "auto_reauth_enabled": False,
                "auto_reauth_cooldown_sec": 2400,
            }
        )
        assert saved["refresh_interval_sec"] == 90
        written = json.loads(isolated_config.read_text())
        assert written["auto_refresh"] is False
        assert written["auto_reauth_enabled"] is False

    def test_compute_keyring_account_key_is_stable(self):
        first = config_mod.compute_keyring_account_key(config_mod.CODEX_HOME)
        second = config_mod.compute_keyring_account_key(config_mod.CODEX_HOME)
        assert first == second
        assert first.startswith("cli|")
