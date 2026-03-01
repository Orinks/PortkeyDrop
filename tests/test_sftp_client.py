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


class TestSFTPClientSftpCall:
    def test_sftp_call_returns_result(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        client._ssh_client = MagicMock()
        client._sftp = MagicMock()

        result = client._sftp_call(lambda: 42)
        assert result == 42

    def test_sftp_call_passes_args(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        client._ssh_client = MagicMock()
        client._sftp = MagicMock()

        result = client._sftp_call(lambda a, b: a + b, 3, 4)
        assert result == 7

    def test_sftp_call_timeout_raises(self, sftp_info: ConnectionInfo) -> None:
        import socket

        sftp_info.timeout = 1
        client = SFTPClient(sftp_info)
        client._ssh_client = MagicMock()
        client._sftp = MagicMock()

        # socket.timeout should propagate as-is (no longer converted here)
        def raises_socket_timeout():
            raise socket.timeout("timed out")

        with pytest.raises(socket.timeout):
            client._sftp_call(raises_socket_timeout)

    def test_sftp_call_uses_fallback_timeout_when_none(self, sftp_info: ConnectionInfo) -> None:
        """If timeout is None, should use 30s fallback (not hang forever)."""
        sftp_info.timeout = None  # type: ignore[assignment]
        client = SFTPClient(sftp_info)
        client._ssh_client = MagicMock()
        client._sftp = MagicMock()

        # Just verify it doesn't error on None timeout — we can't wait 30s in tests,
        # so confirm it runs a fast fn successfully with None timeout.
        result = client._sftp_call(lambda: "ok")
        assert result == "ok"


class TestSFTPClientListDir:
    def _make_connected(self, sftp_info: ConnectionInfo) -> tuple[SFTPClient, MagicMock]:
        client = SFTPClient(sftp_info)
        mock_sftp = MagicMock()
        mock_sftp.normalize.return_value = "/home/user"
        client._ssh_client = MagicMock()
        client._sftp = mock_sftp
        client._cwd = "/home/user"
        return client, mock_sftp

    def test_list_dir_returns_files(self, sftp_info: ConnectionInfo) -> None:
        import stat as stat_mod

        client, mock_sftp = self._make_connected(sftp_info)
        attr = MagicMock()
        attr.filename = "file.txt"
        attr.st_mode = stat_mod.S_IFREG | 0o644
        attr.st_size = 100
        attr.st_mtime = 0
        attr.st_uid = 1000
        attr.st_gid = 1000
        attr.longname = "-rw-r--r-- 1 user group 100 Jan 1 file.txt"
        mock_sftp.listdir_attr.return_value = [attr]

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].name == "file.txt"
        assert files[0].is_dir is False

    def test_list_dir_permission_error(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.EACCES
        mock_sftp.listdir_attr.side_effect = err

        with pytest.raises(PermissionError, match="Permission denied"):
            client.list_dir("/restricted")

    def test_list_dir_reraises_other_oserror(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.ENOENT
        mock_sftp.listdir_attr.side_effect = err

        with pytest.raises(IOError):
            client.list_dir("/gone")


class TestSFTPClientChdir:
    def _make_connected(self, sftp_info: ConnectionInfo) -> tuple[SFTPClient, MagicMock]:
        client = SFTPClient(sftp_info)
        mock_sftp = MagicMock()
        mock_sftp.normalize.return_value = "/home/user/subdir"
        client._ssh_client = MagicMock()
        client._sftp = mock_sftp
        client._cwd = "/home/user"
        return client, mock_sftp

    def test_chdir_updates_cwd(self, sftp_info: ConnectionInfo) -> None:
        client, mock_sftp = self._make_connected(sftp_info)
        result = client.chdir("/home/user/subdir")
        assert result == "/home/user/subdir"
        assert client._cwd == "/home/user/subdir"

    def test_chdir_permission_error(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.EPERM
        mock_sftp.chdir.side_effect = err

        with pytest.raises(PermissionError, match="Permission denied"):
            client.chdir("/restricted")


class TestSFTPClientListDirSpecialFiles:
    def _make_connected(self, sftp_info: ConnectionInfo) -> tuple[SFTPClient, MagicMock]:
        client = SFTPClient(sftp_info)
        mock_sftp = MagicMock()
        mock_sftp.normalize.return_value = "/home/user"
        client._ssh_client = MagicMock()
        client._sftp = mock_sftp
        client._cwd = "/home/user"
        return client, mock_sftp

    def test_socket_file_skipped(self, sftp_info: ConnectionInfo) -> None:
        import stat as stat_mod

        client, mock_sftp = self._make_connected(sftp_info)
        attr = MagicMock()
        attr.filename = "agent.sock"
        attr.st_mode = stat_mod.S_IFSOCK | 0o600
        attr.longname = "srw------- 1 user group 0 Jan 1 agent.sock"
        mock_sftp.listdir_attr.return_value = [attr]

        files = client.list_dir()
        assert files == []

    def test_fifo_file_skipped(self, sftp_info: ConnectionInfo) -> None:
        import stat as stat_mod

        client, mock_sftp = self._make_connected(sftp_info)
        attr = MagicMock()
        attr.filename = "mypipe"
        attr.st_mode = stat_mod.S_IFIFO | 0o644
        attr.longname = "prw-r--r-- 1 user group 0 Jan 1 mypipe"
        mock_sftp.listdir_attr.return_value = [attr]

        files = client.list_dir()
        assert files == []

    def test_oserror_reraises(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.ENOENT
        mock_sftp.listdir_attr.side_effect = err

        with pytest.raises(IOError):
            client.list_dir("/gone")
