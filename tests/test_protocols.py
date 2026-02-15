"""Tests for protocol abstraction and client implementations."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from accessitransfer.protocols import (
    ConnectionInfo,
    FTPClient,
    FTPSClient,
    Protocol,
    RemoteFile,
    SFTPClient,
    TransferClient,
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

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com", username="user", password="pass")
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
