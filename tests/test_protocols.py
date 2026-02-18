"""Tests for protocol abstraction and client implementations."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from portkeydrop.protocols import (
    ConnectionInfo,
    FTPClient,
    FTPSClient,
    HostKeyPolicy,
    Protocol,
    RemoteFile,
    SFTPClient,
    create_client,
)


class TestRemoteFile:
    def test_display_size_dir(self):
        f = RemoteFile(name="docs", path="/docs", is_dir=True)
        assert f.display_size == "<DIR>"

    def test_display_size_bytes(self):
        f = RemoteFile(name="a.txt", path="/a.txt", size=500)
        assert f.display_size == "500 B"

    def test_display_size_kb(self):
        f = RemoteFile(name="a.txt", path="/a.txt", size=2048)
        assert f.display_size == "2.0 KB"

    def test_display_size_mb(self):
        f = RemoteFile(name="a.zip", path="/a.zip", size=5 * 1024 * 1024)
        assert f.display_size == "5.0 MB"

    def test_display_size_gb(self):
        f = RemoteFile(name="big.iso", path="/big.iso", size=3 * 1024 * 1024 * 1024)
        assert f.display_size == "3.0 GB"

    def test_display_modified_none(self):
        f = RemoteFile(name="a.txt", path="/a.txt")
        assert f.display_modified == ""

    def test_display_modified_with_date(self):
        dt = datetime(2026, 2, 14, 15, 30)
        f = RemoteFile(name="a.txt", path="/a.txt", modified=dt)
        assert f.display_modified == "2026-02-14 15:30"


class TestConnectionInfo:
    def test_default_protocol(self):
        info = ConnectionInfo()
        assert info.protocol == Protocol.SFTP

    def test_effective_port_default_sftp(self):
        info = ConnectionInfo(protocol=Protocol.SFTP)
        assert info.effective_port == 22

    def test_effective_port_default_ftp(self):
        info = ConnectionInfo(protocol=Protocol.FTP)
        assert info.effective_port == 21

    def test_effective_port_default_ftps(self):
        info = ConnectionInfo(protocol=Protocol.FTPS)
        assert info.effective_port == 990

    def test_effective_port_default_webdav(self):
        info = ConnectionInfo(protocol=Protocol.WEBDAV)
        assert info.effective_port == 443

    def test_effective_port_custom(self):
        info = ConnectionInfo(protocol=Protocol.SFTP, port=2222)
        assert info.effective_port == 2222

    def test_effective_port_scp(self):
        info = ConnectionInfo(protocol=Protocol.SCP)
        assert info.effective_port == 22


class TestCreateClient:
    def test_create_ftp_client(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = create_client(info)
        assert isinstance(client, FTPClient)

    def test_create_ftps_client(self):
        info = ConnectionInfo(protocol=Protocol.FTPS, host="example.com")
        client = create_client(info)
        assert isinstance(client, FTPSClient)

    def test_create_sftp_client(self):
        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = create_client(info)
        assert isinstance(client, SFTPClient)

    @patch("portkeydrop.protocols.SFTPClient")
    def test_create_sftp_client_passes_connection_info_with_host_key_policy(self, mock_sftp_class):
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="alice",
            timeout=15,
            host_key_policy=HostKeyPolicy.STRICT,
        )

        created_client = MagicMock()
        mock_sftp_class.return_value = created_client

        client = create_client(info)

        mock_sftp_class.assert_called_once_with(info)
        assert client is created_client

    def test_create_client_keeps_backward_compatible_default_host_key_policy(self):
        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")

        client = create_client(info)

        assert isinstance(client, SFTPClient)
        assert client._info.host_key_policy is HostKeyPolicy.AUTO_ADD

    def test_create_client_keeps_other_protocols_working_with_new_connectioninfo_field(self):
        ftp_info = ConnectionInfo(
            protocol=Protocol.FTP,
            host="ftp.example.com",
            host_key_policy=HostKeyPolicy.STRICT,
        )
        ftps_info = ConnectionInfo(
            protocol=Protocol.FTPS,
            host="ftps.example.com",
            host_key_policy=HostKeyPolicy.STRICT,
        )

        ftp_client = create_client(ftp_info)
        ftps_client = create_client(ftps_info)

        assert isinstance(ftp_client, FTPClient)
        assert isinstance(ftps_client, FTPSClient)

    def test_create_unsupported_raises(self):
        info = ConnectionInfo(protocol=Protocol.WEBDAV, host="example.com")
        with pytest.raises(ValueError, match="not yet supported"):
            create_client(info)


class TestFTPClient:
    def test_not_connected_initially(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        assert not client.connected

    def test_cwd_default(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        assert client.cwd == "/"

    @patch("ftplib.FTP")
    def test_connect_success(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/"
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(
            protocol=Protocol.FTP, host="example.com", username="user", password="pass"
        )
        client = FTPClient(info)
        client.connect()

        assert client.connected
        mock_ftp.connect.assert_called_once_with("example.com", 21, 30)
        mock_ftp.login.assert_called_once_with("user", "pass")

    @patch("ftplib.FTP")
    def test_connect_failure(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.connect.side_effect = Exception("Connection refused")
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)

        with pytest.raises(ConnectionError, match="FTP connection failed"):
            client.connect()
        assert not client.connected

    @patch("ftplib.FTP")
    def test_disconnect(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/"
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()
        client.disconnect()

        assert not client.connected
        mock_ftp.quit.assert_called_once()

    def test_list_dir_not_connected(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        with pytest.raises(ConnectionError, match="Not connected"):
            client.list_dir()

    @patch("ftplib.FTP")
    def test_chdir(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.pwd.side_effect = ["/", "/uploads"]
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()
        result = client.chdir("/uploads")

        assert result == "/uploads"
        mock_ftp.cwd.assert_called_with("/uploads")

    @patch("ftplib.FTP")
    def test_mkdir(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/"
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()
        client.mkdir("/new_dir")

        mock_ftp.mkd.assert_called_with("/new_dir")

    @patch("ftplib.FTP")
    def test_delete(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/"
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()
        client.delete("/old_file.txt")

        mock_ftp.delete.assert_called_with("/old_file.txt")

    @patch("ftplib.FTP")
    def test_rename(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/"
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()
        client.rename("/old.txt", "/new.txt")

        mock_ftp.rename.assert_called_with("/old.txt", "/new.txt")


class TestSFTPClient:
    def test_not_connected_initially(self):
        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = SFTPClient(info)
        assert not client.connected

    @patch("paramiko.SSHClient")
    def test_connect_success(self, mock_ssh_class):
        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.normalize.return_value = "/"
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="pass",
        )
        client = SFTPClient(info)
        client.connect()

        assert client.connected
        mock_ssh.connect.assert_called_once_with(
            hostname="example.com",
            port=22,
            username="user",
            timeout=30,
            allow_agent=True,
            look_for_keys=True,
            password="pass",
        )

    @patch("paramiko.SSHClient")
    def test_connect_failure(self, mock_ssh_class):
        mock_ssh = MagicMock()
        mock_ssh.connect.side_effect = Exception("Connection refused")
        mock_ssh_class.return_value = mock_ssh

        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = SFTPClient(info)

        with pytest.raises(ConnectionError, match="SFTP connection failed"):
            client.connect()
        assert not client.connected

    @patch("paramiko.SSHClient")
    def test_disconnect(self, mock_ssh_class):
        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.normalize.return_value = "/"
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = SFTPClient(info)
        client.connect()
        client.disconnect()

        assert not client.connected
        mock_sftp.close.assert_called_once()
        mock_ssh.close.assert_called_once()

    def test_list_dir_not_connected(self):
        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = SFTPClient(info)
        with pytest.raises(ConnectionError, match="Not connected"):
            client.list_dir()

    def test_disconnect_when_not_connected(self):
        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = SFTPClient(info)
        client.disconnect()  # Should not raise
        assert not client.connected


    @patch("paramiko.SSHClient")
    def test_list_dir_maps_file_attributes(self, mock_ssh_class):
        import stat as stat_mod

        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.normalize.return_value = "/home/user"
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        file_attr = MagicMock(
            filename="file.txt",
            st_mode=stat_mod.S_IFREG | 0o644,
            st_size=123,
            st_mtime=1700000000,
            st_uid=1000,
            st_gid=1000,
            longname="-rw-r--r--",
        )
        dir_attr = MagicMock(
            filename="docs",
            st_mode=stat_mod.S_IFDIR | 0o755,
            st_size=0,
            st_mtime=1700000000,
            st_uid=1000,
            st_gid=1000,
            longname="drwxr-xr-x",
        )
        dot_attr = MagicMock(filename=".")
        mock_sftp.listdir_attr.return_value = [dot_attr, file_attr, dir_attr]

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()
        files = client.list_dir(".")

        assert len(files) == 2
        assert files[0].name == "file.txt"
        assert files[0].is_dir is False
        assert files[0].size == 123
        assert files[1].name == "docs"
        assert files[1].is_dir is True

    @patch("paramiko.SSHClient")
    def test_chdir_download_upload_and_file_ops(self, mock_ssh_class):
        import io

        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.normalize.side_effect = ["/", "/uploads"]
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        assert client.chdir("/uploads") == "/uploads"
        mock_sftp.chdir.assert_called_once_with("/uploads")

        download_calls: list[tuple[int, int]] = []

        def fake_getfo(_path, _file, callback):
            callback(10, 100)

        mock_sftp.getfo.side_effect = fake_getfo
        client.download("/remote.bin", MagicMock(), callback=lambda t, n: download_calls.append((t, n)))
        assert download_calls == [(10, 100)]

        upload_calls: list[tuple[int, int]] = []

        def fake_putfo(_file, _path, file_size, callback):
            assert file_size == 4
            callback(4, file_size)

        mock_sftp.putfo.side_effect = fake_putfo
        client.upload(io.BytesIO(b"data"), "/remote.txt", callback=lambda t, n: upload_calls.append((t, n)))
        assert upload_calls == [(4, 4)]

        client.delete("/a")
        client.mkdir("/b")
        client.rmdir("/b")
        client.rename("/old", "/new")
        mock_sftp.remove.assert_called_once_with("/a")
        mock_sftp.mkdir.assert_called_once_with("/b")
        mock_sftp.rmdir.assert_called_once_with("/b")
        mock_sftp.rename.assert_called_once_with("/old", "/new")

    @patch("paramiko.SSHClient")
    @patch("paramiko.RSAKey.from_private_key_file")
    def test_connect_with_key_and_stat(self, mock_key_loader, mock_ssh_class):
        import stat as stat_mod

        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        mock_sftp.normalize.return_value = "/"
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh
        mock_key = MagicMock()
        mock_key_loader.return_value = mock_key

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/id_rsa",
        )
        client = SFTPClient(info)
        client.connect()

        mock_key_loader.assert_called_once_with("/tmp/id_rsa")
        kwargs = mock_ssh.connect.call_args.kwargs
        assert kwargs["allow_agent"] is False
        assert kwargs["look_for_keys"] is False
        assert kwargs["pkey"] is mock_key

        attr = MagicMock(st_mode=stat_mod.S_IFREG | 0o644, st_size=42, st_mtime=1700000000)
        mock_sftp.stat.return_value = attr
        remote = client.stat("/remote/file.txt")
        assert remote.name == "file.txt"
        assert remote.path == "/remote/file.txt"
        assert remote.size == 42
        assert remote.is_dir is False


class TestParentDir:
    def test_parent_from_subdir(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client._connected = True
        client._cwd = "/home/user/docs"
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/home/user"
        client._ftp = mock_ftp

        result = client.parent_dir()
        assert result == "/home/user"
        mock_ftp.cwd.assert_called_with("/home/user")

    def test_parent_from_root(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client._connected = True
        client._cwd = "/"
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/"
        client._ftp = mock_ftp

        result = client.parent_dir()
        assert result == "/"


class TestProtocolEnum:
    def test_all_protocols(self):
        assert Protocol.FTP.value == "ftp"
        assert Protocol.FTPS.value == "ftps"
        assert Protocol.SFTP.value == "sftp"
        assert Protocol.SCP.value == "scp"
        assert Protocol.WEBDAV.value == "webdav"
