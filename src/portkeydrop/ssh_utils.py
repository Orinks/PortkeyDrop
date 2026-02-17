"""SSH agent authentication utilities.

Provides helper functions for detecting SSH agent availability and creating
paramiko SSHClient instances configured for agent-based authentication.
"""

from __future__ import annotations

import os
import platform

import paramiko


def check_ssh_agent_available() -> bool:
    """Check whether an SSH agent is available on the current platform.

    Checks for the following agent sources in order:

    - **Linux/macOS**: ``SSH_AUTH_SOCK`` environment variable pointing to
      an existing Unix socket.
    - **Windows (OpenSSH)**: The named pipe
      ``\\\\.\\pipe\\openssh-ssh-agent``.
    - **Windows (Pageant)**: Attempts to connect via paramiko's Pageant
      support.

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

        # Check Pageant
        try:
            agent = paramiko.Agent()
            keys = agent.get_keys()
            if keys:
                agent.close()
                return True
            agent.close()
        except Exception:
            pass

    return False


def create_ssh_client(
    *,
    auto_add_host_key: bool = True,
    allow_agent: bool = True,
    look_for_keys: bool = True,
) -> paramiko.SSHClient:
    """Create a configured :class:`paramiko.SSHClient` for SSH agent auth.

    The returned client is pre-configured with sensible defaults for
    agent-based authentication, including automatic host key acceptance.

    Args:
        auto_add_host_key: If ``True`` (default), automatically accept
            unknown host keys using
            :class:`paramiko.AutoAddPolicy`.
        allow_agent: If ``True`` (default), allow the client to connect
            to a running SSH agent for key-based authentication.
        look_for_keys: If ``True`` (default), allow the client to search
            for discoverable private key files in ``~/.ssh/``.

    Returns:
        A configured :class:`paramiko.SSHClient` instance ready for
        connection.
    """
    client = paramiko.SSHClient()

    if auto_add_host_key:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

    # Load system host keys if available
    try:
        client.load_system_host_keys()
    except Exception:
        pass

    # Store settings as attributes so callers can inspect them
    client._allow_agent = allow_agent  # type: ignore[attr-defined]
    client._look_for_keys = look_for_keys  # type: ignore[attr-defined]

    return client
