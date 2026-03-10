"""Portkey Drop entry point."""

from __future__ import annotations

import atexit
import logging
import sys
import tempfile
from pathlib import Path


def _get_lock_path() -> Path:
    """Return the path to the single-instance lock file."""
    return Path(tempfile.gettempdir()) / "portkeydrop.lock"


def _acquire_lock(skip_prompt: bool = False) -> bool:
    """Try to acquire the single-instance lock file.

    Returns ``True`` if the lock was acquired successfully or the user chose to
    force start.  Returns ``False`` if the user cancelled.
    """
    lock_path = _get_lock_path()
    if lock_path.exists():
        if skip_prompt:
            # Post-update restart – stale lock from the old process is expected.
            pass
        else:
            try:
                import wx  # noqa: F811 – wx may already be imported

                # Need a temporary app for the dialog if one isn't running yet.
                temp_app = wx.App(False)  # noqa: F841
                result = wx.MessageBox(
                    "Portkey Drop appears to be already running.\n\n"
                    "If the previous instance crashed or did not shut down cleanly, "
                    "you can force start.\n\n"
                    "Force start?",
                    "Already Running",
                    wx.YES_NO | wx.ICON_WARNING,
                )
                if result != wx.YES:
                    return False
            except Exception:
                pass

    # Write our PID so the lock file is not empty.
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(__import__("os").getpid()), encoding="utf-8")
    atexit.register(_release_lock)
    return True


def _release_lock() -> None:
    """Remove the lock file on normal exit."""
    try:
        _get_lock_path().unlink(missing_ok=True)
    except OSError:
        pass


def main() -> None:
    """Launch Portkey Drop."""

    debug = "--debug" in sys.argv
    updated = "--updated" in sys.argv
    log_file = None
    for arg in sys.argv:
        if arg.startswith("--log="):
            log_file = arg.split("=", 1)[1]

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        handlers=handlers,
    )
    try:
        import wx  # noqa: F401
    except ModuleNotFoundError:
        print("Portkey Drop v0.1.0")
        print("Accessible file transfer client")
        print()
        print("GUI dependency missing: wxPython")
        print("Try:")
        print("  uv sync")
        print()
        print("If sync succeeds but wxPython is still missing, use Python 3.12:")
        print("  uv python install 3.12")
        print("  uv sync --python 3.12")
        print("  uv run --python 3.12 portkeydrop")
        sys.exit(1)

    if not _acquire_lock(skip_prompt=updated):
        sys.exit(0)

    from portkeydrop.app import PortkeyDropApp

    app = PortkeyDropApp(False)
    app.MainLoop()


if __name__ == "__main__":
    main()
