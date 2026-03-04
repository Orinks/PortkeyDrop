"""Screen reader announcement wrapper for Portkey Drop.

Uses prismatoid when available and degrades gracefully when unavailable.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _try_import_prismatoid():
    """Lazily import prismatoid, returning the module or None."""
    try:
        import prismatoid

        return prismatoid
    except Exception:
        logger.debug("prismatoid not available", exc_info=True)
        return None


try:
    # Module-level flag useful for tests/diagnostics.
    PRISMATOID_AVAILABLE = _try_import_prismatoid() is not None
except Exception:
    PRISMATOID_AVAILABLE = False


class ScreenReaderAnnouncer:
    """Announce text via screen reader with graceful fallback."""

    def __init__(self) -> None:
        self._backend = _try_import_prismatoid()
        self._available = self._backend is not None
        if self._available:
            logger.info("prismatoid available; announcements enabled")
        else:
            logger.debug("prismatoid unavailable; announcements will use status bar only")

    def announce(self, text: str) -> None:
        """Speak text, if backend is available."""
        if self._backend is None:
            return
        try:
            self._backend.speak(text)
        except Exception:
            logger.warning("Failed to announce text via prismatoid", exc_info=True)

    def is_available(self) -> bool:
        return self._available
