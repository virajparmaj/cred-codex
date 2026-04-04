"""Helpers for launching Codex authentication flows."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
import time
import webbrowser

from credcodex.models import FailureCategory

AUTH_DOCS_URL = "https://developers.openai.com/codex/auth"
AUTH_ERROR_MARKERS = (
    "auth expired",
    "reauthenticate",
    "refresh token",
    "chatgpt authentication required",
    "unsupported auth mode",
    "api key auth does not expose codex limits",
)


def is_auth_error(error: str | None, category: FailureCategory | None = None) -> bool:
    """Return True when the failure requires re-authentication."""
    if category in {FailureCategory.AUTH_EXPIRED, FailureCategory.UNSUPPORTED_AUTH_MODE}:
        return True
    if not error:
        return False
    text = error.lower()
    return any(marker in text for marker in AUTH_ERROR_MARKERS)


@dataclass(frozen=True)
class LaunchResult:
    """Result of an attempted auth launch."""

    success: bool
    message: str


class ReauthGate:
    """Cooldown gate that avoids repeated auth prompts."""

    def __init__(self, cooldown_sec: int = 1800) -> None:
        self._cooldown_sec = max(30, int(cooldown_sec))
        self._last_attempt_mono = 0.0

    def update_cooldown(self, cooldown_sec: int) -> None:
        self._cooldown_sec = max(30, int(cooldown_sec))

    def mark_attempt(self, now_mono: float | None = None) -> None:
        self._last_attempt_mono = time.monotonic() if now_mono is None else now_mono

    def seconds_until_next_attempt(self, now_mono: float | None = None) -> int:
        now = time.monotonic() if now_mono is None else now_mono
        if self._last_attempt_mono <= 0:
            return 0
        remaining = self._cooldown_sec - (now - self._last_attempt_mono)
        return max(0, int(remaining))

    def eligible_for_auto_launch(
        self,
        error: str | None,
        category: FailureCategory | None = None,
        now_mono: float | None = None,
    ) -> bool:
        if not is_auth_error(error, category=category):
            return False
        return self.seconds_until_next_attempt(now_mono=now_mono) == 0


def launch_auth_docs(timeout_sec: int = 12) -> LaunchResult:
    """Open the official Codex auth docs in the default browser."""
    try:
        opened = webbrowser.open(AUTH_DOCS_URL, new=1, autoraise=True)
    except Exception as exc:
        return LaunchResult(False, f"Failed to open the Codex auth docs: {exc}")
    if not opened:
        return LaunchResult(False, "Could not open the Codex auth docs in a browser.")
    return LaunchResult(True, "Opened the Codex authentication docs in your browser.")


def launch_codex_login(timeout_sec: int = 12) -> LaunchResult:
    """Open Terminal and run `codex login`, or fall back to docs."""
    if shutil.which("codex") is None:
        return launch_auth_docs(timeout_sec=timeout_sec)

    script = (
        'tell application "Terminal"\n'
        "  activate\n"
        '  do script "codex login"\n'
        "end tell\n"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return LaunchResult(False, "Timed out while asking macOS to open Terminal.")
    except FileNotFoundError:
        return LaunchResult(False, "osascript is unavailable on this machine.")
    except Exception as exc:
        return LaunchResult(False, f"Failed to launch Terminal: {exc}")

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if "not allowed" in detail.lower():
            return LaunchResult(
                False,
                "macOS denied Terminal automation. Allow permissions in System Settings.",
            )
        if detail:
            return LaunchResult(False, f"Terminal launch failed: {detail}")
        return LaunchResult(False, f"Terminal launch failed (exit {result.returncode}).")

    return LaunchResult(
        True,
        "Opened Terminal and started `codex login`. Complete the browser flow to finish.",
    )
