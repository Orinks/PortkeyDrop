"""AccessiTransfer entry point."""

from __future__ import annotations

import sys


def main() -> None:
    """Launch AccessiTransfer."""
    try:
        import wx  # noqa: F401

        from accessitransfer.app import AccessiTransferApp

        app = AccessiTransferApp(False)
        app.MainLoop()
    except ImportError:
        print("AccessiTransfer v0.1.0")
        print("Accessible file transfer client")
        print()
        print("wxPython is required for the GUI. Install with:")
        print("  pip install 'accessitransfer[gui]'")
        sys.exit(1)


if __name__ == "__main__":
    main()
