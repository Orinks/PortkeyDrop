"""Shared models for connection profile importers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ImportedSite:
    """Normalized imported site profile."""

    name: str
    protocol: str
    host: str
    port: int
    username: str = ""
    password: str = ""
    key_path: str = ""
    ftp_explicit_ssl: bool = False
    initial_dir: str = "/"
    notes: str = ""
