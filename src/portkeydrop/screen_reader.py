"""Screen reader announcement wrapper for Portkey Drop.

The PyPI distribution is published as ``prismatoid`` but imports as ``prism``
in current releases. We probe both module names for compatibility.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _try_import_backend():
    """Lazily import screen-reader backend module, returning (module, name)."""
    try:
        import prism

        return prism, "prism"
    except Exception:
        logger.debug("prism module not available", exc_info=True)

    try:
        import prismatoid

        return prismatoid, "prismatoid"
    except Exception:
        logger.debug("prismatoid module not available", exc_info=True)

    return None, None


try:
    # Module-level flag useful for tests/diagnostics.
    _mod, _name = _try_import_backend()
    PRISMATOID_AVAILABLE = _mod is not None
except Exception:
    PRISMATOID_AVAILABLE = False


class ScreenReaderAnnouncer:
    """Announce text via screen reader with graceful fallback."""

    def __init__(self) -> None:
        self._backend, self._backend_name = _try_import_backend()
        self._available = self._backend is not None
        if self._available:
            logger.info("%s available; announcements enabled", self._backend_name)
        else:
            logger.debug("No speech backend available; announcements will use status bar only")

    def announce(self, text: str) -> None:
        """Speak text, if backend is available."""
        if self._backend is None:
            return
        try:
            self._backend.speak(text)
        except Exception:
            logger.warning(
                "Failed to announce text via %s",
                self._backend_name or "speech backend",
                exc_info=True,
            )

    def is_available(self) -> bool:
        return self._available
