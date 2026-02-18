"""Portkey Drop entry point."""

from __future__ import annotations

import logging
import sys


def main() -> None:
    """Launch Portkey Drop."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
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

    from portkeydrop.app import PortkeyDropApp

    app = PortkeyDropApp(False)
    app.MainLoop()


if __name__ == "__main__":
    main()
