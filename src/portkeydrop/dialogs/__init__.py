"""Portkey Drop dialogs."""

try:
    from .host_key_dialog import HostKeyDialog
except Exception:  # pragma: no cover - wx may be unavailable in headless tests
    HostKeyDialog = None  # type: ignore[assignment]

__all__ = ["HostKeyDialog"]
