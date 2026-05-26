"""Portkey Drop entry point."""

from __future__ import annotations

import atexit
import logging
import sys

from portkeydrop.single_instance import SingleInstanceManager


def main() -> None:
    """Launch Portkey Drop."""

    debug = "--debug" in sys.argv
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

    single_instance_manager = SingleInstanceManager()
    if not single_instance_manager.try_acquire_lock():
        single_instance_manager.request_existing_instance_show()
        sys.exit(0)
    atexit.register(single_instance_manager.release_lock)

    from portkeydrop.app import PortkeyDropApp

    app = PortkeyDropApp(False)
    app.MainLoop()


if __name__ == "__main__":
    main()
