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
        stat_attrs = MagicMock()
        stat_attrs.permissions = stat_mod.S_IFDIR | 0o755
        stat_attrs.type = None
        mock_sftp.stat.return_value = stat_attrs
        client._conn = AsyncMock()
        client._sftp = mock_sftp
        client._cwd = "/home/user"
        return client, mock_sftp

    def test_chdir_updates_cwd(self, sftp_info: ConnectionInfo) -> None:
        client, mock_sftp = self._make_connected(sftp_info)
        result = client.chdir("/home/user/subdir")
        assert result == "/home/user/subdir"
        assert client._cwd == "/home/user/subdir"

    def test_chdir_validates_directory_with_stat(self, sftp_info: ConnectionInfo) -> None:
        client, mock_sftp = self._make_connected(sftp_info)
        client.chdir("/home/user/subdir")
        mock_sftp.stat.assert_awaited_once_with("/home/user/subdir")

    def test_chdir_rejects_non_directory(self, sftp_info: ConnectionInfo) -> None:
        client, mock_sftp = self._make_connected(sftp_info)
        stat_attrs = MagicMock()
        stat_attrs.permissions = stat_mod.S_IFREG | 0o644
        stat_attrs.type = None
        mock_sftp.stat.return_value = stat_attrs

        with pytest.raises(NotADirectoryError, match="Not a directory"):
            client.chdir("/home/user/file.txt")
        assert client._cwd == "/home/user"  # unchanged

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


# SFTP v4+ file type constant (matches protocols._SFTP_TYPE_DIRECTORY)
_SFTP_TYPE_DIRECTORY = 2
_SFTP_TYPE_SYMLINK = 3
_SFTP_TYPE_REGULAR = 1
_SFTP_TYPE_UNKNOWN = 5


class TestSFTPBitviseCompliance:
    """Tests for strict SFTP servers (Bitvise) that send file type in the
    SFTP v4+ ``type`` field rather than (or in addition to) permission bits."""

    def _make_connected(self, sftp_info: ConnectionInfo) -> tuple[SFTPClient, AsyncMock]:
        client = SFTPClient(sftp_info)
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/home/user"
        client._conn = AsyncMock()
        client._sftp = mock_sftp
        client._cwd = "/home/user"
        return client, mock_sftp

    # ---- list_dir: type field fallback ----

    def test_list_dir_detects_dir_via_sftp_type_when_permissions_none(
        self, sftp_info: ConnectionInfo
    ) -> None:
        """Bitvise may return type=DIRECTORY with permissions=None."""
        client, mock_sftp = self._make_connected(sftp_info)
        entry = MagicMock()
        entry.filename = ".ssh"
        entry.attrs = MagicMock()
        entry.attrs.permissions = None
        entry.attrs.type = _SFTP_TYPE_DIRECTORY
        entry.attrs.size = 0
        entry.attrs.mtime = 0
        entry.attrs.uid = 1000
        entry.attrs.gid = 1000
        entry.longname = ""
        mock_sftp.readdir.return_value = [entry]

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].name == ".ssh"
        assert files[0].is_dir is True

    def test_list_dir_detects_dir_via_sftp_type_when_permissions_lack_type_bits(
        self, sftp_info: ConnectionInfo
    ) -> None:
        """Bitvise may return permissions=0o700 without S_IFDIR bits + type=DIRECTORY."""
        client, mock_sftp = self._make_connected(sftp_info)
        entry = MagicMock()
        entry.filename = ".ssh"
        entry.attrs = MagicMock()
        entry.attrs.permissions = 0o700  # No S_IFDIR prefix
        entry.attrs.type = _SFTP_TYPE_DIRECTORY
        entry.attrs.size = 0
        entry.attrs.mtime = 0
        entry.attrs.uid = 1000
        entry.attrs.gid = 1000
        entry.longname = ""
        mock_sftp.readdir.return_value = [entry]

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].name == ".ssh"
        assert files[0].is_dir is True

    def test_list_dir_file_with_type_regular_stays_file(self, sftp_info: ConnectionInfo) -> None:
        """File with type=REGULAR and no permission type bits stays a file."""
        client, mock_sftp = self._make_connected(sftp_info)
        entry = MagicMock()
        entry.filename = "readme.txt"
        entry.attrs = MagicMock()
        entry.attrs.permissions = 0o644
        entry.attrs.type = _SFTP_TYPE_REGULAR
        entry.attrs.size = 100
        entry.attrs.mtime = 0
        entry.attrs.uid = 1000
        entry.attrs.gid = 1000
        entry.longname = ""
        mock_sftp.readdir.return_value = [entry]

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].is_dir is False

    def test_list_dir_symlink_to_dir_via_sftp_type(self, sftp_info: ConnectionInfo) -> None:
        """Symlink with type=SYMLINK that resolves to a dir via stat type field."""
        client, mock_sftp = self._make_connected(sftp_info)
        entry = MagicMock()
        entry.filename = "link-to-dir"
        entry.attrs = MagicMock()
        entry.attrs.permissions = None
        entry.attrs.type = _SFTP_TYPE_SYMLINK
        entry.attrs.size = 0
        entry.attrs.mtime = 0
        entry.attrs.uid = 1000
        entry.attrs.gid = 1000
        entry.longname = ""

        target_attrs = MagicMock()
        target_attrs.permissions = None
        target_attrs.type = _SFTP_TYPE_DIRECTORY
        mock_sftp.stat.return_value = target_attrs
        mock_sftp.readdir.return_value = [entry]

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].is_dir is True

    # ---- chdir: directory validation ----

    def test_chdir_accepts_dir_via_sftp_type(self, sftp_info: ConnectionInfo) -> None:
        """chdir succeeds when stat returns type=DIRECTORY with permissions=None."""
        client, mock_sftp = self._make_connected(sftp_info)
        mock_sftp.realpath.return_value = "/home/user/.ssh"
        stat_attrs = MagicMock()
        stat_attrs.permissions = None
        stat_attrs.type = _SFTP_TYPE_DIRECTORY
        mock_sftp.stat.return_value = stat_attrs

        result = client.chdir("/home/user/.ssh")
        assert result == "/home/user/.ssh"
        assert client._cwd == "/home/user/.ssh"

    def test_chdir_accepts_dir_with_permissions_only(self, sftp_info: ConnectionInfo) -> None:
        """chdir succeeds when stat returns S_IFDIR in permissions (standard Linux)."""
        client, mock_sftp = self._make_connected(sftp_info)
        mock_sftp.realpath.return_value = "/home/user/docs"
        stat_attrs = MagicMock()
        stat_attrs.permissions = stat_mod.S_IFDIR | 0o755
        stat_attrs.type = _SFTP_TYPE_UNKNOWN
        mock_sftp.stat.return_value = stat_attrs

        result = client.chdir("/home/user/docs")
        assert result == "/home/user/docs"

    def test_chdir_stat_permission_error_surfaces(self, sftp_info: ConnectionInfo) -> None:
        """chdir raises PermissionError when stat fails with EACCES."""
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        mock_sftp.realpath.return_value = "/home/user/.ssh"
        err = IOError()
        err.errno = errno.EACCES
        mock_sftp.stat.side_effect = err

        with pytest.raises(PermissionError, match="Permission denied"):
            client.chdir("/home/user/.ssh")
        assert client._cwd == "/home/user"  # unchanged

    # ---- stat: type field fallback ----

    def test_stat_detects_dir_via_sftp_type(self, sftp_info: ConnectionInfo) -> None:
        """stat() returns is_dir=True when type=DIRECTORY and permissions=None."""
        client, mock_sftp = self._make_connected(sftp_info)
        stat_attrs = MagicMock()
        stat_attrs.permissions = None
        stat_attrs.type = _SFTP_TYPE_DIRECTORY
        stat_attrs.size = 0
        stat_attrs.mtime = 0
        mock_sftp.stat.return_value = stat_attrs

        remote = client.stat("/home/user/.ssh")
        assert remote.is_dir is True
        assert remote.name == ".ssh"
