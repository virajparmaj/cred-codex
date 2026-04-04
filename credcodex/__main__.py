"""Process entrypoint for CredCodex."""

from __future__ import annotations

import atexit
import fcntl
import os
import sys

from credcodex.config import APP_DIR, PID_PATH, ensure_app_dir, setup_logging

_LOCK_HANDLE = None


def _acquire_pid_lock() -> None:
    """Acquire the single-instance PID lock."""
    global _LOCK_HANDLE
    ensure_app_dir()
    if _LOCK_HANDLE is not None:
        print("Another CredCodex instance is already running. Exiting.", file=sys.stderr)
        sys.exit(0)
    try:
        _LOCK_HANDLE = open(PID_PATH, "w")
        fcntl.flock(_LOCK_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another CredCodex instance is already running. Exiting.", file=sys.stderr)
        sys.exit(0)
    _LOCK_HANDLE.write(str(os.getpid()))
    _LOCK_HANDLE.flush()
    atexit.register(_release_pid_lock)


def _release_pid_lock() -> None:
    """Release the single-instance PID lock."""
    global _LOCK_HANDLE
    if _LOCK_HANDLE is None:
        return
    try:
        fcntl.flock(_LOCK_HANDLE, fcntl.LOCK_UN)
        _LOCK_HANDLE.close()
    except OSError:
        pass
    PID_PATH.unlink(missing_ok=True)
    _LOCK_HANDLE = None


def main() -> None:
    ensure_app_dir()
    setup_logging()
    _acquire_pid_lock()
    from credcodex.app import CredCodexApp

    CredCodexApp().run()


if __name__ == "__main__":
    main()
