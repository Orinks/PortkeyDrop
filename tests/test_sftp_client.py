"""Tests for SFTPClient using SSHClient-based authentication."""

from __future__ import annotations

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

    @patch("paramiko.RSAKey.from_private_key_file")
    @patch("paramiko.SSHClient")
    def test_connect_with_key_file(self, mock_cls: MagicMock, mock_key_load: MagicMock) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/path/to/key",
        )
        mock_ssh = _make_mock_ssh()
        mock_cls.return_value = mock_ssh
        mock_key = MagicMock()
        mock_key_load.return_value = mock_key

        client = SFTPClient(info)
        client.connect()

        mock_key_load.assert_called_once_with("/path/to/key")
        call_kwargs = mock_ssh.connect.call_args[1]
        assert call_kwargs["pkey"] == mock_key
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
        assert "pkey" not in call_kwargs

    @patch("paramiko.SSHClient")
    def test_connect_failure(self, mock_cls: MagicMock, sftp_info: ConnectionInfo) -> None:
        mock_ssh = MagicMock()
        mock_cls.return_value = mock_ssh
        mock_ssh.connect.side_effect = Exception("Auth failed")

        client = SFTPClient(sftp_info)
        with pytest.raises(ConnectionError, match="SFTP connection failed"):
            client.connect()
        assert client._connected is False


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
