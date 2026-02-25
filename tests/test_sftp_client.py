"""Tests for SFTPClient using SSHClient-based authentication."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from portkeydrop.protocols import ConnectionInfo, HostKeyPolicy, Protocol, SFTPClient


@pytest.fixture
def sftp_info() -> ConnectionInfo:
    return ConnectionInfo(
        protocol=Protocol.SFTP,
        host="example.com",
        port=22,
        username="user",
        password="pass",
    )


def _make_mock_ssh() -> MagicMock:
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_ssh.open_sftp.return_value = mock_sftp
    mock_sftp.normalize.return_value = "/home/user"
    return mock_ssh


class TestSFTPClientInit:
    def test_creates_ssh_client_attribute(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        assert hasattr(client, "_ssh_client")
        assert client._ssh_client is None

    def test_no_transport_attribute(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        assert not hasattr(client, "_transport")


class TestSFTPClientConnect:
    @patch("paramiko.SSHClient")
    def test_connect_with_password(self, mock_cls: MagicMock, sftp_info: ConnectionInfo) -> None:
        mock_ssh = _make_mock_ssh()
        mock_cls.return_value = mock_ssh

        client = SFTPClient(sftp_info)
        client.connect()

        mock_ssh.connect.assert_called_once()
        call_kwargs = mock_ssh.connect.call_args[1]
        assert call_kwargs["hostname"] == "example.com"
        assert call_kwargs["username"] == "user"
        assert call_kwargs["password"] == "pass"
        assert call_kwargs["allow_agent"] is True
        assert call_kwargs["look_for_keys"] is True
        assert client._connected is True

    @patch("os.path.exists", return_value=True)
    @patch("paramiko.SSHClient")
    def test_connect_with_key_file(self, mock_cls: MagicMock, _mock_exists: MagicMock) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/path/to/key",
        )
        mock_ssh = _make_mock_ssh()
        mock_cls.return_value = mock_ssh

        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_ssh.connect.call_args[1]
        assert call_kwargs["key_filename"] == "/path/to/key"
        assert call_kwargs["allow_agent"] is False
        assert call_kwargs["look_for_keys"] is False

    @patch("paramiko.SSHClient")
    def test_connect_agent_only(self, mock_cls: MagicMock) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
        )
        mock_ssh = _make_mock_ssh()
        mock_cls.return_value = mock_ssh

        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_ssh.connect.call_args[1]
        assert call_kwargs["allow_agent"] is True
        assert call_kwargs["look_for_keys"] is True
        assert "password" not in call_kwargs
        assert "key_filename" not in call_kwargs

    @patch("paramiko.SSHClient")
    def test_connect_failure(self, mock_cls: MagicMock, sftp_info: ConnectionInfo) -> None:
        mock_ssh = MagicMock()
        mock_cls.return_value = mock_ssh
        mock_ssh.connect.side_effect = Exception("Auth failed")

        client = SFTPClient(sftp_info)
        with pytest.raises(ConnectionError, match="SFTP connection failed"):
            client.connect()
        assert client._connected is False

    @patch("paramiko.SSHClient")
    def test_logs_authentication_methods(
        self, mock_cls: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="pass",
        )
        mock_ssh = _make_mock_ssh()
        mock_cls.return_value = mock_ssh

        caplog.set_level(logging.DEBUG, logger="portkeydrop.protocols")

        client = SFTPClient(info)
        client.connect()

        text = caplog.text
        assert "SSH agent detection" in text
        assert "SFTP authentication methods to try: ssh-agent, default-key-files, password" in text
        assert "SSH authentication succeeded" in text

    @patch("paramiko.SSHClient")
    def test_logs_agent_unavailable_error(
        self, mock_cls: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_ssh = MagicMock()
        mock_cls.return_value = mock_ssh
        mock_ssh.connect.side_effect = paramiko.SSHException("Error connecting to agent")

        caplog.set_level(logging.DEBUG, logger="portkeydrop.protocols")

        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com", username="user")
        client = SFTPClient(info)

        with pytest.raises(ConnectionError, match="SSH agent is unavailable or inaccessible"):
            client.connect()

        assert "SSH agent appears unavailable or inaccessible" in caplog.text

    @patch("paramiko.SSHClient")
    def test_auth_failure_message_for_agent_and_password(self, mock_cls: MagicMock) -> None:
        mock_ssh = MagicMock()
        mock_cls.return_value = mock_ssh
        mock_ssh.connect.side_effect = paramiko.AuthenticationException("denied")

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="bad",
        )
        client = SFTPClient(info)

        with pytest.raises(
            ConnectionError, match="trying SSH agent, default key files, and password"
        ):
            client.connect()

    @patch("paramiko.SSHClient")
    def test_auth_failure_message_for_agent_only(self, mock_cls: MagicMock) -> None:
        mock_ssh = MagicMock()
        mock_cls.return_value = mock_ssh
        mock_ssh.connect.side_effect = paramiko.AuthenticationException("denied")

        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com", username="user")
        client = SFTPClient(info)

        with pytest.raises(ConnectionError, match="Start your SSH agent and load a key"):
            client.connect()


class TestSFTPClientHostKeyPolicy:
    @patch("paramiko.SSHClient")
    def test_auto_add_policy(self, mock_cls: MagicMock, sftp_info: ConnectionInfo) -> None:
        mock_ssh = _make_mock_ssh()
        mock_cls.return_value = mock_ssh

        sftp_info.host_key_policy = HostKeyPolicy.AUTO_ADD
        client = SFTPClient(sftp_info)
        client.connect()

        # Check that AutoAddPolicy was set
        policy_calls = mock_ssh.set_missing_host_key_policy.call_args_list
        assert len(policy_calls) == 1
        policy_arg = policy_calls[0][0][0]
        assert isinstance(policy_arg, paramiko.AutoAddPolicy)

    @patch("paramiko.SSHClient")
    def test_strict_policy(self, mock_cls: MagicMock, sftp_info: ConnectionInfo) -> None:
        mock_ssh = _make_mock_ssh()
        mock_cls.return_value = mock_ssh

        sftp_info.host_key_policy = HostKeyPolicy.STRICT
        client = SFTPClient(sftp_info)
        client.connect()

        policy_calls = mock_ssh.set_missing_host_key_policy.call_args_list
        assert len(policy_calls) == 1
        policy_arg = policy_calls[0][0][0]
        assert isinstance(policy_arg, paramiko.RejectPolicy)


class TestSFTPClientEnsureConnected:
    def test_raises_when_ssh_client_is_none(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        client._ssh_client = None
        client._sftp = MagicMock()
        with pytest.raises(ConnectionError, match="Not connected"):
            client._ensure_connected()

    def test_raises_when_sftp_is_none(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        client._ssh_client = MagicMock()
        client._sftp = None
        with pytest.raises(ConnectionError, match="Not connected"):
            client._ensure_connected()

    def test_raises_when_both_none(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        with pytest.raises(ConnectionError, match="Not connected"):
            client._ensure_connected()

    def test_returns_sftp_when_connected(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_sftp = MagicMock()
        client._ssh_client = MagicMock()
        client._sftp = mock_sftp
        result = client._ensure_connected()
        assert result is mock_sftp

    def test_methods_use_ensure_connected(self, sftp_info: ConnectionInfo) -> None:
        """Verify that SFTP methods raise ConnectionError when not connected."""
        client = SFTPClient(sftp_info)
        with pytest.raises(ConnectionError):
            client.list_dir()
        with pytest.raises(ConnectionError):
            client.chdir("/tmp")
        with pytest.raises(ConnectionError):
            client.delete("/tmp/f")
        with pytest.raises(ConnectionError):
            client.mkdir("/tmp/d")
        with pytest.raises(ConnectionError):
            client.rmdir("/tmp/d")
        with pytest.raises(ConnectionError):
            client.rename("/a", "/b")
        with pytest.raises(ConnectionError):
            client.stat("/tmp/f")


class TestSFTPClientDisconnect:
    def test_disconnect_cleans_up(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        client._ssh_client = mock_ssh
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()

        assert client._ssh_client is None
        assert client._sftp is None
        assert client._connected is False

    def test_disconnect_calls_close_on_both(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        client._ssh_client = mock_ssh
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()

        mock_sftp.close.assert_called_once()
        mock_ssh.close.assert_called_once()

    def test_disconnect_handles_sftp_close_exception(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.close.side_effect = Exception("SFTP close error")
        client._ssh_client = mock_ssh
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()  # Should not raise

        assert client._sftp is None
        assert client._ssh_client is None
        mock_ssh.close.assert_called_once()

    def test_disconnect_handles_ssh_close_exception(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_ssh = MagicMock()
        mock_ssh.close.side_effect = Exception("SSH close error")
        mock_sftp = MagicMock()
        client._ssh_client = mock_ssh
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()  # Should not raise

        assert client._sftp is None
        assert client._ssh_client is None

    def test_disconnect_handles_both_close_exceptions(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_ssh = MagicMock()
        mock_ssh.close.side_effect = Exception("SSH close error")
        mock_sftp = MagicMock()
        mock_sftp.close.side_effect = Exception("SFTP close error")
        client._ssh_client = mock_ssh
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()  # Should not raise

        assert client._sftp is None
        assert client._ssh_client is None

    def test_disconnect_when_not_connected(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        client.disconnect()  # Should not raise
        assert client._sftp is None
        assert client._ssh_client is None
