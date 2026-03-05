"""Tests for SFTPClient using asyncssh-based authentication."""

from __future__ import annotations

import base64
import functools
import hashlib
import logging
import math
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


def _setup_readdir(mock_sftp: AsyncMock, entries: list) -> None:
    """Wire up _handler mocks so _readdir_safe returns *entries* in one batch.

    _readdir_safe uses sftp._handler.opendir / readdir / close instead of the
    high-level sftp.readdir wrapper.
    """
    mock_sftp.compose_path.side_effect = lambda p: p
    mock_handler = AsyncMock()
    mock_handler.opendir.return_value = "fake-handle"
    mock_handler.readdir.return_value = (entries, True)  # (names, at_end)
    mock_handler.close.return_value = None
    mock_sftp._handler = mock_handler


def _setup_readdir_error(mock_sftp: AsyncMock, error: Exception) -> None:
    """Wire up _handler mocks so _readdir_safe raises *error* on opendir."""
    mock_sftp.compose_path.side_effect = lambda p: p
    mock_handler = AsyncMock()
    mock_handler.opendir.side_effect = error
    mock_sftp._handler = mock_handler


def _encode_ppk_string(data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + data


def _encode_ppk_mpint(value: int) -> bytes:
    if value == 0:
        return _encode_ppk_string(b"")
    return _encode_ppk_string(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def _is_probable_prime(candidate: int) -> bool:
    if candidate < 2:
        return False
    for small in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29):
        if candidate == small:
            return True
        if candidate % small == 0:
            return False

    d = candidate - 1
    s = 0
    while d % 2 == 0:
        d //= 2
        s += 1

    for base in (2, 3, 5, 7, 11, 13, 17):
        if base >= candidate:
            continue
        x = pow(base, d, candidate)
        if x in (1, candidate - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, candidate)
            if x == candidate - 1:
                break
        else:
            return False
    return True


def _deterministic_prime(seed: bytes, bits: int) -> int:
    digest = hashlib.shake_256(seed).digest((bits + 7) // 8)
    candidate = int.from_bytes(digest, "big")
    candidate |= (1 << (bits - 1)) | 1
    while not _is_probable_prime(candidate):
        candidate += 2
    return candidate


@functools.lru_cache(maxsize=1)
def _synthetic_rsa_ppk_bytes() -> bytes:
    e = 65537
    p = _deterministic_prime(b"portkeydrop-test-ppk-rsa-p", bits=256)
    q = _deterministic_prime(b"portkeydrop-test-ppk-rsa-q", bits=256)
    if p == q:
        q = _deterministic_prime(b"portkeydrop-test-ppk-rsa-q-2", bits=256)

    phi = (p - 1) * (q - 1)
    if math.gcd(e, phi) != 1:
        e = 17
    d = pow(e, -1, phi)
    n = p * q

    public_blob = b"".join(
        (_encode_ppk_string(b"ssh-rsa"), _encode_ppk_mpint(e), _encode_ppk_mpint(n))
    )
    private_blob = b"".join((_encode_ppk_mpint(d), _encode_ppk_mpint(p), _encode_ppk_mpint(q)))

    public_b64 = base64.b64encode(public_blob).decode("ascii")
    private_b64 = base64.b64encode(private_blob).decode("ascii")
    public_lines = [public_b64[i : i + 64] for i in range(0, len(public_b64), 64)]
    private_lines = [private_b64[i : i + 64] for i in range(0, len(private_b64), 64)]

    lines = [
        "PuTTY-User-Key-File-3: ssh-rsa",
        "Encryption: none",
        "Comment: synthetic-portkeydrop-rsa-regression",
        f"Public-Lines: {len(public_lines)}",
        *public_lines,
        f"Private-Lines: {len(private_lines)}",
        *private_lines,
        "Private-MAC: 0000000000000000000000000000000000000000000000000000000000000000",
        "",
    ]
    return "\n".join(lines).encode("ascii")


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
    @patch("asyncssh.read_private_key", return_value=object())
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_with_key_file(
        self, mock_connect: AsyncMock, mock_read_private_key: MagicMock, _mock_exists: MagicMock
    ) -> None:
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/path/to/key",
        )
        mock_conn, mock_sftp = _make_mock_conn()
        mock_connect.return_value = mock_conn

        client = SFTPClient(info)
        with patch(
            "portkeydrop.protocols.SFTPClient._read_private_key_file",
            return_value=b"-----BEGIN OPENSSH PRIVATE KEY-----\n",
        ):
            client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["client_keys"] == [mock_read_private_key.return_value]
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

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_with_synthetic_valid_rsa_ppk_maps_wrong_credentials_to_auth_error(
        self, mock_connect: AsyncMock, _mock_exists: MagicMock
    ) -> None:
        import asyncssh

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="wrong-passphrase-or-password",
            key_path="/tmp/synthetic.ppk",
        )
        mock_connect.side_effect = asyncssh.PermissionDenied("denied")

        client = SFTPClient(info)
        with patch(
            "portkeydrop.protocols.SFTPClient._read_private_key_file",
            return_value=_synthetic_rsa_ppk_bytes(),
        ):
            with pytest.raises(ConnectionError) as exc:
                client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["agent_path"] is None
        assert len(call_kwargs["client_keys"]) == 1
        assert "Authentication failed with key file '/tmp/synthetic.ppk'" in str(exc.value)
        assert "could not import" not in str(exc.value).lower()


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
        _setup_readdir(mock_sftp, [entry])

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].name == "file.txt"
        assert files[0].is_dir is False

    def test_list_dir_permission_error(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.EACCES
        _setup_readdir_error(mock_sftp, err)

        with pytest.raises(PermissionError, match="Permission denied"):
            client.list_dir("/restricted")

    def test_list_dir_reraises_other_oserror(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.ENOENT
        _setup_readdir_error(mock_sftp, err)

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
        _setup_readdir(mock_sftp, [entry])

        files = client.list_dir()
        assert files == []

    def test_fifo_file_skipped(self, sftp_info: ConnectionInfo) -> None:
        client, mock_sftp = self._make_connected(sftp_info)
        entry = MagicMock()
        entry.filename = "mypipe"
        entry.attrs = MagicMock()
        entry.attrs.permissions = stat_mod.S_IFIFO | 0o644
        entry.longname = "prw-r--r-- 1 user group 0 Jan 1 mypipe"
        _setup_readdir(mock_sftp, [entry])

        files = client.list_dir()
        assert files == []

    def test_oserror_reraises(self, sftp_info: ConnectionInfo) -> None:
        import errno

        client, mock_sftp = self._make_connected(sftp_info)
        err = IOError()
        err.errno = errno.ENOENT
        _setup_readdir_error(mock_sftp, err)

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
        _setup_readdir(mock_sftp, [entry])

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
        _setup_readdir(mock_sftp, [entry])

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
        _setup_readdir(mock_sftp, [entry])

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
        _setup_readdir(mock_sftp, [entry])

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

    # ---- _readdir_safe: Bitvise count=0 EOF quirk ----

    def test_readdir_safe_treats_consecutive_empty_batches_as_eof(
        self, sftp_info: ConnectionInfo
    ) -> None:
        """_readdir_safe stops after 3 consecutive empty readdir responses.

        Bitvise may return FXP_NAME with count=0 (empty list, at_end=False)
        indefinitely instead of FX_EOF.  _readdir_safe must break out after
        _MAX_EMPTY (3) consecutive empty batches — matching WinSCP behaviour.
        """
        client, mock_sftp = self._make_connected(sftp_info)

        entry = MagicMock()
        entry.filename = "hello.txt"
        entry.attrs = MagicMock()
        entry.attrs.permissions = stat_mod.S_IFREG | 0o644
        entry.attrs.type = _SFTP_TYPE_REGULAR
        entry.attrs.size = 42
        entry.attrs.mtime = 0
        entry.attrs.uid = 1000
        entry.attrs.gid = 1000
        entry.longname = ""

        mock_sftp.compose_path.side_effect = lambda p: p
        mock_handler = AsyncMock()
        mock_handler.opendir.return_value = "fake-handle"
        # Batch 1: real entry, at_end=False
        # Batches 2-4: empty, at_end=False  (Bitvise quirk — never sends EOF)
        mock_handler.readdir.side_effect = [
            ([entry], False),
            ([], False),
            ([], False),
            ([], False),
        ]
        mock_handler.close.return_value = None
        mock_sftp._handler = mock_handler

        files = client.list_dir()

        assert len(files) == 1
        assert files[0].name == "hello.txt"
        # 1 real batch + 3 empty batches = 4 readdir calls
        assert mock_handler.readdir.call_count == 4
        mock_handler.close.assert_awaited_once()

    # ---- _readdir_safe: SFTPEOFError handling ----

    def test_readdir_safe_handles_sftp_eof_error(self, sftp_info: ConnectionInfo) -> None:
        """_readdir_safe catches SFTPEOFError and returns collected results."""
        import asyncssh

        client, mock_sftp = self._make_connected(sftp_info)

        entry = MagicMock()
        entry.filename = "data.csv"
        entry.longname = ""
        entry.attrs = MagicMock()
        entry.attrs.permissions = stat_mod.S_IFREG | 0o644
        entry.attrs.type = _SFTP_TYPE_REGULAR
        entry.attrs.size = 99
        entry.attrs.mtime = 0
        entry.attrs.uid = 1000
        entry.attrs.gid = 1000

        mock_sftp.compose_path.side_effect = lambda p: p
        mock_handler = AsyncMock()
        mock_handler.opendir.return_value = "fake-handle"
        # First call returns an entry; second raises SFTPEOFError
        mock_handler.readdir.side_effect = [
            ([entry], False),
            asyncssh.SFTPEOFError(),
        ]
        mock_handler.close.return_value = None
        mock_sftp._handler = mock_handler

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].name == "data.csv"
        mock_handler.close.assert_awaited_once()

    # ---- _readdir_safe: bytes filename decode ----

    def test_readdir_safe_decodes_bytes_filenames(self, sftp_info: ConnectionInfo) -> None:
        """_readdir_safe decodes bytes filenames/longnames via sftp.decode."""
        client, mock_sftp = self._make_connected(sftp_info)

        entry = MagicMock()
        entry.filename = b"report.txt"
        entry.longname = b"-rw-r--r-- 1 user user 42 Jan 1 00:00 report.txt"
        entry.attrs = MagicMock()
        entry.attrs.permissions = stat_mod.S_IFREG | 0o644
        entry.attrs.type = _SFTP_TYPE_REGULAR
        entry.attrs.size = 42
        entry.attrs.mtime = 0
        entry.attrs.uid = 1000
        entry.attrs.gid = 1000

        mock_sftp.decode = MagicMock(side_effect=lambda b: b.decode("utf-8"))
        mock_sftp.compose_path.side_effect = lambda p: p
        mock_handler = AsyncMock()
        mock_handler.opendir.return_value = "fake-handle"
        mock_handler.readdir.return_value = ([entry], True)
        mock_handler.close.return_value = None
        mock_sftp._handler = mock_handler

        files = client.list_dir()
        assert len(files) == 1
        assert files[0].name == "report.txt"
        assert mock_sftp.decode.call_count == 2

    # ---- list_dir: SFTPError exception mapping ----

    def test_list_dir_sftp_error_permission_denied(self, sftp_info: ConnectionInfo) -> None:
        """list_dir maps SFTPError code=3 (FX_PERMISSION_DENIED) to PermissionError."""
        import asyncssh

        client, mock_sftp = self._make_connected(sftp_info)
        _setup_readdir_error(mock_sftp, asyncssh.SFTPError(3, "Permission denied"))

        with pytest.raises(PermissionError, match="Permission denied"):
            client.list_dir("/secret")

    def test_list_dir_sftp_error_failure_mapped_to_permission(
        self, sftp_info: ConnectionInfo
    ) -> None:
        """list_dir maps SFTPError code=4 (FX_FAILURE) to PermissionError."""
        import asyncssh

        client, mock_sftp = self._make_connected(sftp_info)
        _setup_readdir_error(mock_sftp, asyncssh.SFTPError(4, "Failure"))

        with pytest.raises(PermissionError, match="Permission denied"):
            client.list_dir("/secret")

    def test_list_dir_sftp_error_non_permission_reraises(self, sftp_info: ConnectionInfo) -> None:
        """list_dir re-raises SFTPError with non-permission code unchanged."""
        import asyncssh

        client, mock_sftp = self._make_connected(sftp_info)
        _setup_readdir_error(mock_sftp, asyncssh.SFTPError(7, "Connection lost"))

        with pytest.raises(asyncssh.SFTPError):
            client.list_dir("/data")

    # ---- chdir: no type info fallback ----

    def test_chdir_assumes_dir_when_no_type_info(self, sftp_info: ConnectionInfo) -> None:
        """chdir assumes directory when stat returns permissions=None and type=None."""
        client, mock_sftp = self._make_connected(sftp_info)
        mock_sftp.realpath.return_value = "/home/user/.ssh"
        stat_attrs = MagicMock()
        stat_attrs.permissions = None
        stat_attrs.type = None
        mock_sftp.stat.return_value = stat_attrs

        result = client.chdir("/home/user/.ssh")
        assert result == "/home/user/.ssh"
        assert client._cwd == "/home/user/.ssh"
