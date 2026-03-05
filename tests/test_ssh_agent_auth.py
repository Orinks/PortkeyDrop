"""Integration tests for SSH agent authentication paths.

Tests verify that SFTPClient correctly attempts agent authentication first,
falls back to key file and password authentication, and handles errors
when all methods fail.
"""

from __future__ import annotations

from unittest import mock
from unittest.mock import AsyncMock

import asyncssh
import pytest

from portkeydrop.protocols import ConnectionInfo, HostKeyPolicy, Protocol, SFTPClient


@pytest.fixture
def sftp_info() -> ConnectionInfo:
    """Base SFTP connection info for tests."""
    return ConnectionInfo(
        protocol=Protocol.SFTP,
        host="example.com",
        port=22,
        username="testuser",
        timeout=10,
    )


class TestAgentAuthAttemptedFirst:
    """Verify agent authentication is attempted first (no agent_path override)."""

    def test_connect_allows_agent_by_default(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_sftp = AsyncMock()
            mock_sftp.realpath.return_value = "/"
            mock_conn.start_sftp_client.return_value = mock_sftp
            mock_connect.return_value = mock_conn

            client.connect()

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args[1]
            # No agent_path override = agent is allowed
            assert "agent_path" not in call_kwargs
            assert "client_keys" not in call_kwargs

    def test_connect_with_password_still_allows_agent(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.password = "secret"
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_sftp = AsyncMock()
            mock_sftp.realpath.return_value = "/"
            mock_conn.start_sftp_client.return_value = mock_sftp
            mock_connect.return_value = mock_conn

            client.connect()

            call_kwargs = mock_connect.call_args[1]
            # When password is provided (no key_path), agent is still allowed
            assert "agent_path" not in call_kwargs
            assert call_kwargs["password"] == "secret"


class TestFallbackToKeyFile:
    """Verify fallback to key file authentication."""

    def test_connect_with_key_path_disables_agent(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.key_path = "/home/user/.ssh/id_rsa"
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_sftp = AsyncMock()
            mock_sftp.realpath.return_value = "/"
            mock_conn.start_sftp_client.return_value = mock_sftp
            mock_connect.return_value = mock_conn

            with (
                mock.patch("os.path.exists", return_value=True),
                mock.patch(
                    "portkeydrop.protocols.SFTPClient._read_private_key_file",
                    return_value=b"-----BEGIN OPENSSH PRIVATE KEY-----\n",
                ),
                mock.patch("asyncssh.read_private_key", return_value=object()) as mock_read_key,
            ):
                client.connect()

                call_kwargs = mock_connect.call_args[1]
                assert call_kwargs["agent_path"] is None
                assert call_kwargs["client_keys"] == [mock_read_key.return_value]

    def test_key_path_takes_precedence_over_password(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.key_path = "/home/user/.ssh/id_rsa"
        sftp_info.password = "secret"
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_sftp = AsyncMock()
            mock_sftp.realpath.return_value = "/"
            mock_conn.start_sftp_client.return_value = mock_sftp
            mock_connect.return_value = mock_conn

            with (
                mock.patch("os.path.exists", return_value=True),
                mock.patch(
                    "portkeydrop.protocols.SFTPClient._read_private_key_file",
                    return_value=b"-----BEGIN OPENSSH PRIVATE KEY-----\n",
                ),
                mock.patch("asyncssh.read_private_key", return_value=object()) as mock_read_key,
            ):
                client.connect()

                call_kwargs = mock_connect.call_args[1]
                assert call_kwargs["agent_path"] is None
                assert "password" not in call_kwargs
                assert "passphrase" not in call_kwargs
                assert call_kwargs["client_keys"] == [mock_read_key.return_value]


class TestFallbackToPassword:
    """Verify fallback to password authentication."""

    def test_connect_with_password_only(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.password = "mypassword"
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_sftp = AsyncMock()
            mock_sftp.realpath.return_value = "/"
            mock_conn.start_sftp_client.return_value = mock_sftp
            mock_connect.return_value = mock_conn

            client.connect()

            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["password"] == "mypassword"
            # Agent still allowed as a first attempt
            assert "agent_path" not in call_kwargs

    def test_connect_no_credentials_uses_agent_and_key_discovery(
        self, sftp_info: ConnectionInfo
    ) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_sftp = AsyncMock()
            mock_sftp.realpath.return_value = "/"
            mock_conn.start_sftp_client.return_value = mock_sftp
            mock_connect.return_value = mock_conn

            client.connect()

            call_kwargs = mock_connect.call_args[1]
            assert "agent_path" not in call_kwargs
            assert "client_keys" not in call_kwargs
            assert "password" not in call_kwargs


class TestErrorHandlingAllMethodsFail:
    """Verify proper error handling when all auth methods fail."""

    def test_connection_error_raised_on_auth_failure(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = asyncssh.PermissionDenied("All auth methods failed")

            with pytest.raises(ConnectionError, match="SFTP connection failed"):
                client.connect()

            assert client.connected is False

    def test_connection_error_on_disconnect_error(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = asyncssh.DisconnectError(11, "SSH error")

            with pytest.raises(ConnectionError, match="SFTP connection failed"):
                client.connect()

            assert client.connected is False

    def test_connection_error_on_socket_error(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = OSError("Connection refused")

            with pytest.raises(ConnectionError, match="SFTP connection failed"):
                client.connect()

            assert client.connected is False

    def test_connection_error_on_key_file_not_found(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.key_path = "/nonexistent/key"
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock):
            with mock.patch("os.path.exists", return_value=False):
                with pytest.raises(ConnectionError, match="key file not found"):
                    client.connect()

                assert client.connected is False

    def test_sftp_session_failure(self, sftp_info: ConnectionInfo) -> None:
        """Test error when SSH connects but SFTP session fails."""
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_conn.start_sftp_client.return_value = None
            mock_connect.return_value = mock_conn

            with pytest.raises(ConnectionError, match="Failed to create SFTP session"):
                client.connect()

            assert client.connected is False


class TestHostKeyPolicies:
    """Verify host key policy configuration during agent auth."""

    def test_strict_host_key_policy(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.host_key_policy = HostKeyPolicy.STRICT
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_sftp = AsyncMock()
            mock_sftp.realpath.return_value = "/"
            mock_conn.start_sftp_client.return_value = mock_sftp
            mock_connect.return_value = mock_conn

            client.connect()

            call_kwargs = mock_connect.call_args[1]
            # Strict mode uses default known_hosts (no override)
            assert "known_hosts" not in call_kwargs

    def test_auto_add_host_key_policy(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.host_key_policy = HostKeyPolicy.AUTO_ADD
        client = SFTPClient(sftp_info)
        with mock.patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_conn = AsyncMock()
            mock_sftp = AsyncMock()
            mock_sftp.realpath.return_value = "/"
            mock_conn.start_sftp_client.return_value = mock_sftp
            mock_connect.return_value = mock_conn

            client.connect()

            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["known_hosts"] is None
