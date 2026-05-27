"""Stable Nuitka entrypoint for PortkeyDrop builds."""

from __future__ import annotations

import sys

if getattr(sys, "frozen", False) and sys.platform == "win32":
    try:
        import win32timezone  # noqa: F401
    except ModuleNotFoundError:
        from portkeydrop._compat import win32timezone as _portkeydrop_win32timezone

        sys.modules.setdefault("win32timezone", _portkeydrop_win32timezone)

from portkeydrop.main import main


if __name__ == "__main__":
    main()
