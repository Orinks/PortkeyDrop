"""SSH agent authentication utilities.

Provides helper functions for detecting SSH agent availability.
"""

from __future__ import annotations

import os
import platform


def check_ssh_agent_available() -> bool:
    """Check whether an SSH agent is available on the current platform.

    Checks for the following agent sources in order:

    - **Linux/macOS**: ``SSH_AUTH_SOCK`` environment variable pointing to
      an existing Unix socket.
    - **Windows (OpenSSH)**: The named pipe
      ``\\\\.\\pipe\\openssh-ssh-agent``.

    Returns:
        ``True`` if at least one SSH agent source is detected, ``False``
        otherwise.
    """
    # Check SSH_AUTH_SOCK (Linux/macOS, also works on Windows with WSL)
    auth_sock = os.environ.get("SSH_AUTH_SOCK")
    if auth_sock and os.path.exists(auth_sock):
        return True

    if platform.system() == "Windows":
        # Check Windows OpenSSH agent named pipe
        pipe_path = r"\\.\pipe\openssh-ssh-agent"
        if os.path.exists(pipe_path):
            return True

    return False
