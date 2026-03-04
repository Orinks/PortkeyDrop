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
        self._module, self._backend_name = _try_import_backend()
        self._speaker = None
        self._available = False

        if self._module is None:
            logger.debug("No speech backend available; announcements will use status bar only")
            return

        # Preferred API: Context()->acquire_best()->speak(...)
        ctx_cls = getattr(self._module, "Context", None)
        if ctx_cls is not None:
            try:
                ctx = ctx_cls()
                backend = ctx.acquire_best()
                self._speaker = backend.speak
                self._available = True
                logger.info(
                    "%s backend active: %s",
                    self._backend_name,
                    getattr(backend, "name", "unknown"),
                )
                return
            except Exception:
                logger.debug("%s Context backend unavailable", self._backend_name, exc_info=True)

        # Fallback API: module-level speak(text)
        speak_fn = getattr(self._module, "speak", None)
        if callable(speak_fn):
            self._speaker = speak_fn
            self._available = True
            logger.info("%s module-level speak() available", self._backend_name)
            return

        logger.warning(
            "%s loaded but no usable speech API found (expected Context or speak)",
            self._backend_name,
        )

    def announce(self, text: str) -> None:
        """Speak text, if backend is available."""
        if self._speaker is None:
            return
        try:
            self._speaker(text)
        except Exception:
            logger.warning(
                "Failed to announce text via %s",
                self._backend_name or "speech backend",
                exc_info=True,
            )

    def is_available(self) -> bool:
        return self._available
