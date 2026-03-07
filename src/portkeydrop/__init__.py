"""Portkey Drop - Accessible file transfer client."""

try:
    from portkeydrop._build_meta import __version__  # type: ignore[import]
except ImportError:
    __version__ = "0.1.1"
