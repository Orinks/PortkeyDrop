"""Integration tests for SSH agent authentication paths.

Tests verify that SFTPClient correctly attempts agent authentication first,
falls back to key file and password authentication, and handles errors
when all methods fail.
"""

from __future__ import annotations

from unittest import mock

import paramiko
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
    """Verify agent authentication is attempted first (allow_agent=True)."""

    def test_connect_uses_allow_agent_true_by_default(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_sftp = mock.MagicMock()
            mock_instance.open_sftp.return_value = mock_sftp
            mock_sftp.normalize.return_value = "/"

            client.connect()

            mock_instance.connect.assert_called_once()
            call_kwargs = mock_instance.connect.call_args[1]
            assert call_kwargs["allow_agent"] is True
            assert call_kwargs["look_for_keys"] is True

    def test_connect_with_password_still_uses_agent(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.password = "secret"
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_sftp = mock.MagicMock()
            mock_instance.open_sftp.return_value = mock_sftp
            mock_sftp.normalize.return_value = "/"

            client.connect()

            call_kwargs = mock_instance.connect.call_args[1]
            # When password is provided (no key_path), agent is still allowed
            assert call_kwargs["allow_agent"] is True
            assert call_kwargs["password"] == "secret"


class TestFallbackToKeyFile:
    """Verify fallback to key file authentication."""

    def test_connect_with_key_path_disables_agent(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.key_path = "/home/user/.ssh/id_rsa"
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_sftp = mock.MagicMock()
            mock_instance.open_sftp.return_value = mock_sftp
            mock_sftp.normalize.return_value = "/"

            with mock.patch("paramiko.RSAKey.from_private_key_file") as mock_key:
                mock_key.return_value = mock.MagicMock()
                client.connect()

                call_kwargs = mock_instance.connect.call_args[1]
                assert call_kwargs["allow_agent"] is False
                assert call_kwargs["look_for_keys"] is False
                assert "pkey" in call_kwargs

    def test_key_path_takes_precedence_over_password(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.key_path = "/home/user/.ssh/id_rsa"
        sftp_info.password = "secret"
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_sftp = mock.MagicMock()
            mock_instance.open_sftp.return_value = mock_sftp
            mock_sftp.normalize.return_value = "/"

            with mock.patch("paramiko.RSAKey.from_private_key_file") as mock_key:
                mock_key.return_value = mock.MagicMock()
                client.connect()

                call_kwargs = mock_instance.connect.call_args[1]
                # key_path branch: agent disabled, password not passed
                assert call_kwargs["allow_agent"] is False
                assert "password" not in call_kwargs
                assert "pkey" in call_kwargs


class TestFallbackToPassword:
    """Verify fallback to password authentication."""

    def test_connect_with_password_only(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.password = "mypassword"
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_sftp = mock.MagicMock()
            mock_instance.open_sftp.return_value = mock_sftp
            mock_sftp.normalize.return_value = "/"

            client.connect()

            call_kwargs = mock_instance.connect.call_args[1]
            assert call_kwargs["password"] == "mypassword"
            # Agent still allowed as a first attempt
            assert call_kwargs["allow_agent"] is True

    def test_connect_no_credentials_uses_agent_and_key_discovery(
        self, sftp_info: ConnectionInfo
    ) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_sftp = mock.MagicMock()
            mock_instance.open_sftp.return_value = mock_sftp
            mock_sftp.normalize.return_value = "/"

            client.connect()

            call_kwargs = mock_instance.connect.call_args[1]
            assert call_kwargs["allow_agent"] is True
            assert call_kwargs["look_for_keys"] is True
            assert "password" not in call_kwargs
            assert "pkey" not in call_kwargs


class TestErrorHandlingAllMethodsFail:
    """Verify proper error handling when all auth methods fail."""

    def test_connection_error_raised_on_auth_failure(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.side_effect = paramiko.AuthenticationException(
                "All auth methods failed"
            )

            with pytest.raises(ConnectionError, match="SFTP connection failed"):
                client.connect()

            assert client.connected is False

    def test_connection_error_on_ssh_exception(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.side_effect = paramiko.SSHException("SSH error")

            with pytest.raises(ConnectionError, match="SFTP connection failed"):
                client.connect()

            assert client.connected is False

    def test_connection_error_on_socket_error(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.side_effect = OSError("Connection refused")

            with pytest.raises(ConnectionError, match="SFTP connection failed"):
                client.connect()

            assert client.connected is False

    def test_connection_error_on_key_file_not_found(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.key_path = "/nonexistent/key"
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient"):
            with mock.patch(
                "paramiko.RSAKey.from_private_key_file",
                side_effect=FileNotFoundError("Key not found"),
            ):
                with pytest.raises(ConnectionError, match="SFTP connection failed"):
                    client.connect()

                assert client.connected is False

    def test_sftp_session_failure(self, sftp_info: ConnectionInfo) -> None:
        """Test error when SSH connects but SFTP session fails."""
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_instance.open_sftp.return_value = None

            with pytest.raises(ConnectionError, match="Failed to create SFTP session"):
                client.connect()

            assert client.connected is False


class TestHostKeyPolicies:
    """Verify host key policy configuration during agent auth."""

    def test_strict_host_key_policy(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.host_key_policy = HostKeyPolicy.STRICT
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_sftp = mock.MagicMock()
            mock_instance.open_sftp.return_value = mock_sftp
            mock_sftp.normalize.return_value = "/"

            client.connect()

            # Should have set RejectPolicy for strict mode
            mock_instance.set_missing_host_key_policy.assert_called()
            policy_arg = mock_instance.set_missing_host_key_policy.call_args[0][0]
            assert isinstance(policy_arg, paramiko.RejectPolicy)

    def test_auto_add_host_key_policy(self, sftp_info: ConnectionInfo) -> None:
        sftp_info.host_key_policy = HostKeyPolicy.AUTO_ADD
        client = SFTPClient(sftp_info)
        with mock.patch("paramiko.SSHClient") as MockSSHClient:
            mock_instance = MockSSHClient.return_value
            mock_instance.connect.return_value = None
            mock_sftp = mock.MagicMock()
            mock_instance.open_sftp.return_value = mock_sftp
            mock_sftp.normalize.return_value = "/"

            client.connect()

            policy_arg = mock_instance.set_missing_host_key_policy.call_args[0][0]
            assert isinstance(policy_arg, paramiko.AutoAddPolicy)
