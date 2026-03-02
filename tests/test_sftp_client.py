"""Tests for SFTPClient using asyncssh-based authentication."""

from __future__ import annotations

import logging
import stat as stat_mod
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_mock_conn() -> tuple[MagicMock, MagicMock]:
    """Create mock asyncssh connection and SFTP client."""
    mock_conn = AsyncMock()
    mock_sftp = AsyncMock()
    mock_conn.start_sftp_client.return_value = mock_sftp
    mock_sftp.realpath.return_value = "/home/user"
    return mock_conn, mock_sftp


class TestSFTPClientInit:
    def test_creates_conn_attribute(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        assert hasattr(client, "_conn")
        assert client._conn is None

    def test_has_event_loop(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        assert client._loop is not None
        assert client._loop.is_running()


class TestSFTPClientConnect:
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_with_password(
        self, mock_connect: AsyncMock, sftp_info: ConnectionInfo
    ) -> None:
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        client = SFTPClient(sftp_info)
        client.connect()

        mock_connect.assert_called_once()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["host"] == "example.com"
        assert call_kwargs["username"] == "user"
        assert call_kwargs["password"] == "pass"
        assert client._connected is True

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_with_key_file(self, mock_connect: AsyncMock, _mock_exists: MagicMock) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/path/to/key",
        )
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["client_keys"] == ["/path/to/key"]
        assert call_kwargs["agent_path"] is None
        assert "passphrase" not in call_kwargs
        assert "password" not in call_kwargs

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_with_key_and_password_fallback(
        self, mock_connect: AsyncMock, _mock_exists: MagicMock
    ) -> None:
        """When both key_path and password are set, password is passed for
        fallback auth and passphrase is omitted."""
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="secret",
            key_path="/path/to/key",
        )
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["client_keys"] == ["/path/to/key"]
        assert call_kwargs["password"] == "secret"
        assert "passphrase" not in call_kwargs
        assert client._connected is True

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_with_key_and_password_logs_both_methods(
        self, mock_connect: AsyncMock, _mock_exists: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="secret",
            key_path="/path/to/key",
        )
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        caplog.set_level(logging.DEBUG, logger="portkeydrop.protocols")

        client = SFTPClient(info)
        client.connect()

        assert "key-file:/path/to/key" in caplog.text
        assert "password" in caplog.text

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_agent_only(self, mock_connect: AsyncMock) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
        )
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert "password" not in call_kwargs
        assert "client_keys" not in call_kwargs

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_failure(self, mock_connect: AsyncMock, sftp_info: ConnectionInfo) -> None:
        mock_connect.side_effect = Exception("Auth failed")

        client = SFTPClient(sftp_info)
        with pytest.raises(ConnectionError, match="SFTP connection failed"):
            client.connect()
        assert client._connected is False

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_logs_authentication_methods(
        self, mock_connect: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="pass",
        )
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        caplog.set_level(logging.DEBUG, logger="portkeydrop.protocols")

        client = SFTPClient(info)
        client.connect()

        text = caplog.text
        assert "SFTP authentication methods to try: ssh-agent, default-key-files, password" in text
        assert "SSH authentication succeeded" in text

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_logs_agent_unavailable_error(
        self, mock_connect: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        import asyncssh

        mock_connect.side_effect = asyncssh.DisconnectError(11, "Error connecting to agent")

        caplog.set_level(logging.DEBUG, logger="portkeydrop.protocols")

        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com", username="user")
        client = SFTPClient(info)

        with pytest.raises(ConnectionError, match="SSH agent is unavailable or inaccessible"):
            client.connect()

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_auth_failure_message_for_agent_and_password(self, mock_connect: AsyncMock) -> None:
        import asyncssh

        mock_connect.side_effect = asyncssh.PermissionDenied("denied")

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

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_auth_failure_message_for_key_and_password(
        self, mock_connect: AsyncMock, _mock_exists: MagicMock
    ) -> None:
        import asyncssh

        mock_connect.side_effect = asyncssh.PermissionDenied("denied")

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="secret",
            key_path="/path/to/key",
        )
        client = SFTPClient(info)

        with pytest.raises(ConnectionError, match="and password fallback"):
            client.connect()

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_auth_failure_message_for_agent_only(self, mock_connect: AsyncMock) -> None:
        import asyncssh

        mock_connect.side_effect = asyncssh.PermissionDenied("denied")

        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com", username="user")
        client = SFTPClient(info)

        with pytest.raises(ConnectionError, match="Start your SSH agent and load a key"):
            client.connect()


class TestSFTPClientHostKeyPolicy:
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_auto_add_policy(self, mock_connect: AsyncMock, sftp_info: ConnectionInfo) -> None:
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        sftp_info.host_key_policy = HostKeyPolicy.AUTO_ADD
        client = SFTPClient(sftp_info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["known_hosts"] is None

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_strict_policy(self, mock_connect: AsyncMock, sftp_info: ConnectionInfo) -> None:
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        sftp_info.host_key_policy = HostKeyPolicy.STRICT
        client = SFTPClient(sftp_info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        # Strict uses default known_hosts (no explicit override)
        assert "known_hosts" not in call_kwargs


class TestSFTPClientEnsureConnected:
    def test_raises_when_conn_is_none(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        client._conn = None
        client._sftp = MagicMock()
        with pytest.raises(ConnectionError, match="Not connected"):
            client._ensure_connected()

    def test_raises_when_sftp_is_none(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        client._conn = MagicMock()
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
        client._conn = MagicMock()
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
        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        client._conn = mock_conn
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()

        assert client._conn is None
        assert client._sftp is None
        assert client._connected is False

    def test_disconnect_calls_close_on_both(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        client._conn = mock_conn
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()

        mock_sftp.exit.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_disconnect_handles_sftp_close_exception(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_conn = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.exit.side_effect = Exception("SFTP close error")
        client._conn = mock_conn
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()  # Should not raise

        assert client._sftp is None
        assert client._conn is None
        mock_conn.close.assert_called_once()

    def test_disconnect_handles_conn_close_exception(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("SSH close error")
        mock_sftp = MagicMock()
        client._conn = mock_conn
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()  # Should not raise

        assert client._sftp is None
        assert client._conn is None

    def test_disconnect_handles_both_close_exceptions(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("SSH close error")
        mock_sftp = MagicMock()
        mock_sftp.exit.side_effect = Exception("SFTP close error")
        client._conn = mock_conn
        client._sftp = mock_sftp
        client._connected = True

        client.disconnect()  # Should not raise

        assert client._sftp is None
        assert client._conn is None

    def test_disconnect_when_not_connected(self, sftp_info: ConnectionInfo) -> None:
        client = SFTPClient(sftp_info)
        client.disconnect()  # Should not raise
        assert client._sftp is None
        assert client._conn is None


class TestSFTPClientListDir:
    def _make_connected(self, sftp_info: ConnectionInfo) -> tuple[SFTPClient, AsyncMock]:
        client = SFTPClient(sftp_info)
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/home/user"
        client._conn = AsyncMock()
        client._sftp = mock_sftp
        client._cwd = "/home/user"
        return client, mock_sftp

    def test_list_dir_returns_files(self, sftp_info: ConnectionInfo) -> None:
        client, mock_sftp = self._make_connected(sftp_info)
        entry = MagicMock()
        entry.filename = "file.txt"
        entry.attrs = MagicMock()
        entry.attrs.permissions = stat_mod.S_IFREG | 0o644
        entry.attrs.size = 100
        entry.attrs.mtime = 0
        entry.attrs.uid = 1000
        entry.attrs.gid = 1000
        entry.longname = "-rw-r--r-- 1 user group 100 Jan 1 file.txt"
        mock_sftp.readdir.return_value = [entry]

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].name == "file.txt"
        assert files[0].is_dir is False

    def test_list_dir_permission_error(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.EACCES
        mock_sftp.readdir.side_effect = err

        with pytest.raises(PermissionError, match="Permission denied"):
            client.list_dir("/restricted")

    def test_list_dir_reraises_other_oserror(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.ENOENT
        mock_sftp.readdir.side_effect = err

        with pytest.raises(IOError):
            client.list_dir("/gone")


class TestSFTPClientChdir:
    def _make_connected(self, sftp_info: ConnectionInfo) -> tuple[SFTPClient, AsyncMock]:
        client = SFTPClient(sftp_info)
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/home/user/subdir"
        client._conn = AsyncMock()
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
        mock_sftp.realpath.side_effect = err

        with pytest.raises(PermissionError, match="Permission denied"):
            client.chdir("/restricted")


class TestSFTPClientListDirSpecialFiles:
    def _make_connected(self, sftp_info: ConnectionInfo) -> tuple[SFTPClient, AsyncMock]:
        client = SFTPClient(sftp_info)
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/home/user"
        client._conn = AsyncMock()
        client._sftp = mock_sftp
        client._cwd = "/home/user"
        return client, mock_sftp

    def test_socket_file_skipped(self, sftp_info: ConnectionInfo) -> None:
        client, mock_sftp = self._make_connected(sftp_info)
        entry = MagicMock()
        entry.filename = "agent.sock"
        entry.attrs = MagicMock()
        entry.attrs.permissions = stat_mod.S_IFSOCK | 0o600
        entry.longname = "srw------- 1 user group 0 Jan 1 agent.sock"
        mock_sftp.readdir.return_value = [entry]

        files = client.list_dir()
        assert files == []

    def test_fifo_file_skipped(self, sftp_info: ConnectionInfo) -> None:
        client, mock_sftp = self._make_connected(sftp_info)
        entry = MagicMock()
        entry.filename = "mypipe"
        entry.attrs = MagicMock()
        entry.attrs.permissions = stat_mod.S_IFIFO | 0o644
        entry.longname = "prw-r--r-- 1 user group 0 Jan 1 mypipe"
        mock_sftp.readdir.return_value = [entry]

        files = client.list_dir()
        assert files == []

    def test_oserror_reraises(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.ENOENT
        mock_sftp.readdir.side_effect = err

        with pytest.raises(IOError):
            client.list_dir("/gone")
