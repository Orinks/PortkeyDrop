"""Portkey Drop entry point."""

from __future__ import annotations

import logging
import sys


def main() -> None:
    """Launch Portkey Drop."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        filename="portkeydrop.log",
    )
    try:
        import wx  # noqa: F401

        from portkeydrop.app import Portkey DropApp

        app = Portkey DropApp(False)
        app.MainLoop()
    except ImportError:
        print("Portkey Drop v0.1.0")
        print("Accessible file transfer client")
        print()
        print("wxPython is required for the GUI. Install with:")
        print("  pip install 'portkeydrop[gui]'")
        sys.exit(1)


if __name__ == "__main__":
    main()
