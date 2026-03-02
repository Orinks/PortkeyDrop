"""Host key verification utilities for asyncssh-based SFTP connections.

With asyncssh, host key policy is handled via the ``known_hosts`` parameter
to ``asyncssh.connect()``.  This module provides helpers for managing the
PortkeyDrop known-hosts file.
"""

from __future__ import annotations

from pathlib import Path


def get_known_hosts_path() -> Path:
    """Return the path to PortkeyDrop's known_hosts file."""
    return Path.home() / ".portkeydrop" / "known_hosts"
