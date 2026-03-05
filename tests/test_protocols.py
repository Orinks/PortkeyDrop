"""Tests for protocol abstraction and client implementations."""

from __future__ import annotations

import io
import base64
import hashlib
import hmac
import sys
import stat as stat_mod
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

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


def _pack_ppk_string(value: bytes) -> bytes:
    return len(value).to_bytes(4, "big") + value


def _pack_ppk_mpint(value: int) -> bytes:
    if value == 0:
        return _pack_ppk_string(b"")
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return _pack_ppk_string(raw)


def _build_native_converter_input(
    *,
    key_type: str = "ssh-ed25519",
    encryption: str = "none",
    comment: str = "native",
    public_blob: bytes | None = None,
    private_blob: bytes | None = None,
) -> tuple[int, str, str, str, bytes, bytes, str]:
    pub_blob = public_blob or (_pack_ppk_string(b"ssh-ed25519") + _pack_ppk_string(b"P" * 32))
    priv_blob = private_blob or _pack_ppk_string(b"S" * 32)
    payload = b"".join(
        _pack_ppk_string(part)
        for part in (
            key_type.encode("utf-8"),
            encryption.encode("utf-8"),
            comment.encode("utf-8"),
            pub_blob,
            priv_blob,
        )
    )
    private_mac = hmac.new(b"", payload, hashlib.sha256).hexdigest()
    return (3, key_type, encryption, comment, pub_blob, priv_blob, private_mac)


def _build_rsa_ppk_fixture(
    *,
    n: int,
    e: int,
    d: int,
    p: int,
    q: int,
    iqmp: int | None = None,
    trailing_padding: bytes = b"",
    version: int = 2,
) -> bytes:
    public_blob = _pack_ppk_string(b"ssh-rsa") + _pack_ppk_mpint(e) + _pack_ppk_mpint(n)
    private_blob = _pack_ppk_mpint(d) + _pack_ppk_mpint(p) + _pack_ppk_mpint(q)
    if iqmp is not None:
        private_blob += _pack_ppk_mpint(iqmp)
    private_blob += trailing_padding
    return (
        f"PuTTY-User-Key-File-{version}: ssh-rsa\n"
        "Encryption: none\n"
        "Comment: rsa-fixture\n"
        "Public-Lines: 1\n"
        f"{base64.b64encode(public_blob).decode()}\n"
        "Private-Lines: 1\n"
        f"{base64.b64encode(private_blob).decode()}\n"
        "Private-MAC: deadbeef\n"
    ).encode("utf-8")


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
        mock_ftp.sendcmd.return_value = "250-Listing\r\n type=dir; /new_dir\r\n250 End"
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
        mock_ftp.sendcmd.side_effect = Exception("not found")
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
        mock_ftp.sendcmd.return_value = "250-Listing\r\n type=file; /new.txt\r\n250 End"
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()
        client.rename("/old.txt", "/new.txt")

        mock_ftp.rename.assert_called_with("/old.txt", "/new.txt")

    @patch("ftplib.FTP")
    def test_is_directory_returns_false_on_exception(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/"
        mock_ftp.sendcmd.side_effect = Exception("failure")
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()

        assert not client._is_directory("/remote")

    @patch("ftplib.FTP")
    def test_upload_raises_when_remote_size_mismatch(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.size.return_value = 5

        def fake_storbinary(cmd, file_obj, block_size, callback):
            callback(file_obj.read())

        mock_ftp.storbinary.side_effect = fake_storbinary
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()

        with pytest.raises(RuntimeError, match="Remote upload verification failed"):
            client.upload(io.BytesIO(b"data"), "/remote.bin")

    def test_delete_raises_when_verification_fails(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client._ftp = MagicMock()
        client._connected = True
        client._path_exists = MagicMock(return_value=True)

        with pytest.raises(RuntimeError, match="verification failed"):
            client.delete("/file.txt")

    def test_rmdir_raises_when_verification_fails(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client._ftp = MagicMock()
        client._connected = True
        client._path_exists = MagicMock(return_value=True)

        with pytest.raises(RuntimeError, match="verification failed"):
            client.rmdir("/dir")

    def test_mkdir_raises_when_verification_fails(self):
        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client._ftp = MagicMock()
        client._connected = True
        client._is_directory = MagicMock(return_value=False)

        with pytest.raises(RuntimeError, match="verification failed"):
            client.mkdir("/dir")


class TestSFTPClient:
    def test_not_connected_initially(self):
        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = SFTPClient(info)
        assert not client.connected

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_success(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            password="pass",
        )
        client = SFTPClient(info)
        client.connect()

        assert client.connected
        mock_connect.assert_called_once()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["host"] == "example.com"
        assert call_kwargs["port"] == 22
        assert call_kwargs["username"] == "user"
        assert call_kwargs["password"] == "pass"

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_failure(self, mock_connect):
        mock_connect.side_effect = Exception("Connection refused")

        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = SFTPClient(info)

        with pytest.raises(ConnectionError, match="SFTP connection failed"):
            client.connect()
        assert not client.connected

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.read_private_key")
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_key_import_error_requires_passphrase(
        self, mock_connect, mock_read_private_key, _mock_exists
    ):
        import asyncssh

        mock_read_private_key.side_effect = asyncssh.KeyImportError(
            "Key is encrypted and requires passphrase"
        )
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/id_rsa",
        )
        client = SFTPClient(info)

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"-----BEGIN OPENSSH PRIVATE KEY-----\n",
            ),
            pytest.raises(ConnectionError) as exc,
        ):
            client.connect()

        assert "requires a passphrase" in str(exc.value)
        assert "Provide the key passphrase" in str(exc.value)
        mock_connect.assert_not_called()

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.read_private_key")
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_key_import_error_invalid_format(
        self, mock_connect, mock_read_private_key, _mock_exists
    ):
        import asyncssh

        mock_read_private_key.side_effect = asyncssh.KeyImportError("Invalid private key format")
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/bad_key",
        )
        client = SFTPClient(info)

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"-----BEGIN OPENSSH PRIVATE KEY-----\n",
            ),
            pytest.raises(ConnectionError) as exc,
        ):
            client.connect()

        assert "invalid or unsupported" in str(exc.value)
        assert "OpenSSH/PKCS#8/PPK" in str(exc.value)
        mock_connect.assert_not_called()

    def test_parse_ppk_header_v2_includes_variant_and_subtype(self):
        is_ppk, variant = SFTPClient._parse_ppk_header(
            b"PuTTY-User-Key-File-2: ssh-rsa\nEncryption: none\n"
        )

        assert is_ppk is True
        assert variant == "PPK v2 (ssh-rsa, encryption=none)"

    def test_parse_ppk_header_v3_includes_variant_and_subtype(self):
        is_ppk, variant = SFTPClient._parse_ppk_header(
            b"PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: aes256-cbc\n"
        )

        assert is_ppk is True
        assert variant == "PPK v3 (ssh-ed25519, encryption=aes256-cbc)"

    @staticmethod
    def _make_minimal_ppk_fixture(version: int, key_type: str, encryption: str) -> bytes:
        return (
            f"PuTTY-User-Key-File-{version}: {key_type}\n"
            f"Encryption: {encryption}\n"
            "Comment: fixture\n"
            "Public-Lines: 1\n"
            "AQIDBA==\n"
            "Private-Lines: 1\n"
            "AQIDBA==\n"
            "Private-MAC: deadbeef\n"
        ).encode("utf-8")

    @pytest.mark.parametrize(
        ("version", "key_type", "encryption", "passphrase"),
        [
            (2, "ssh-rsa", "none", None),
            (2, "ssh-rsa", "aes256-cbc", "v2-secret"),
            (3, "ssh-rsa", "none", None),
            (3, "ssh-ed25519", "aes256-cbc", "v3-secret"),
        ],
    )
    def test_convert_ppk_with_puttykeys_matrix_success(
        self,
        version: int,
        key_type: str,
        encryption: str,
        passphrase: str | None,
    ):
        key_data = self._make_minimal_ppk_fixture(version, key_type, encryption)
        ppkraw_to_openssh = MagicMock(
            return_value="-----BEGIN OPENSSH PRIVATE KEY-----\nstub\n-----END OPENSSH PRIVATE KEY-----\n"
        )
        puttykeys_module = types.ModuleType("puttykeys")
        puttykeys_module.ppkraw_to_openssh = ppkraw_to_openssh

        with patch.dict(sys.modules, {"puttykeys": puttykeys_module}):
            converted, reason = SFTPClient._convert_ppk_with_pure_python(
                key_data,
                passphrase=passphrase,
                ppk_variant="PPK (.ppk)",
            )

        assert reason == ""
        assert converted is not None
        assert converted.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----")
        ppkraw_to_openssh.assert_called_once_with(key_data.decode("utf-8"), passphrase or "")

    @pytest.mark.parametrize(
        ("version", "key_type"),
        [
            (2, "ssh-rsa"),
            (3, "ssh-ed25519"),
        ],
    )
    def test_convert_ppk_encrypted_wrong_passphrase_emits_actionable_message(
        self, version: int, key_type: str
    ):
        key_data = self._make_minimal_ppk_fixture(version, key_type, "aes256-cbc")
        is_ppk, ppk_variant = SFTPClient._parse_ppk_header(key_data)
        assert is_ppk is True

        ppkraw_to_openssh = MagicMock(side_effect=Exception("HMAC mismatch (bad passphrase?)"))
        puttykeys_module = types.ModuleType("puttykeys")
        puttykeys_module.ppkraw_to_openssh = ppkraw_to_openssh

        with patch.dict(sys.modules, {"puttykeys": puttykeys_module}):
            converted, reason = SFTPClient._convert_ppk_with_pure_python(
                key_data,
                passphrase="wrong-passphrase",
                ppk_variant="PPK (.ppk)",
            )

        assert converted is None
        assert reason == "HMAC mismatch (bad passphrase?)"
        formatted = SFTPClient._format_key_import_error(
            reason,
            is_ppk=True,
            ppk_variant=ppk_variant,
        ).lower()
        assert ppk_variant.lower() in formatted
        assert "supplied passphrase is incorrect" in formatted
        assert "enter the correct passphrase" in formatted
        assert "re-export as openssh private key" in formatted

    def test_convert_ppk_v3_ed25519_unencrypted_uses_native_path(self):
        import asyncssh
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        seed = bytes(range(1, 33))
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        public_value = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        key_type = b"ssh-ed25519"
        comment = b"native-v3-ed25519"

        public_blob = (
            len(key_type).to_bytes(4, "big")
            + key_type
            + len(public_value).to_bytes(4, "big")
            + public_value
        )
        private_blob = len(seed).to_bytes(4, "big") + seed

        mac_payload = b"".join(
            len(part).to_bytes(4, "big") + part
            for part in (key_type, b"none", comment, public_blob, private_blob)
        )
        private_mac = hmac.new(b"", mac_payload, hashlib.sha256).hexdigest()

        ppk_text = (
            "PuTTY-User-Key-File-3: ssh-ed25519\n"
            "Encryption: none\n"
            f"Comment: {comment.decode()}\n"
            "Public-Lines: 1\n"
            f"{base64.b64encode(public_blob).decode()}\n"
            "Private-Lines: 1\n"
            f"{base64.b64encode(private_blob).decode()}\n"
            f"Private-MAC: {private_mac}\n"
        )

        converted, reason = SFTPClient._convert_ppk_with_pure_python(
            ppk_text.encode("utf-8"),
            passphrase=None,
            ppk_variant="PPK v3 (ssh-ed25519, encryption=none)",
        )

        assert reason == ""
        assert converted is not None
        imported = asyncssh.import_private_key(converted)
        assert imported is not None

    def test_convert_ppk_rsa_unencrypted_native_success(self):
        import asyncssh
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        numbers = private_key.private_numbers()

        public_blob = (
            _pack_ppk_string(b"ssh-rsa")
            + _pack_ppk_mpint(numbers.public_numbers.e)
            + _pack_ppk_mpint(numbers.public_numbers.n)
        )
        private_blob = (
            _pack_ppk_mpint(numbers.d) + _pack_ppk_mpint(numbers.p) + _pack_ppk_mpint(numbers.q)
        )
        ppk_text = (
            "PuTTY-User-Key-File-2: ssh-rsa\n"
            "Encryption: none\n"
            "Comment: native-rsa\n"
            "Public-Lines: 1\n"
            f"{base64.b64encode(public_blob).decode()}\n"
            "Private-Lines: 1\n"
            f"{base64.b64encode(private_blob).decode()}\n"
            "Private-MAC: deadbeef\n"
        )

        converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(ppk_text.encode("utf-8"))

        assert reason == ""
        assert converted is not None
        imported = asyncssh.import_private_key(converted)
        assert imported is not None

    def test_convert_ppk_rsa_unencrypted_rejects_inconsistent_modulus(self):
        malformed_ppk = _build_rsa_ppk_fixture(n=144, e=65537, d=17, p=11, q=13, version=3)
        converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(malformed_ppk)

        assert converted is None
        assert "n != p*q" in reason

    def test_convert_ppk_rsa_unencrypted_accepts_iqmp_and_padding(self):
        import asyncssh
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        numbers = private_key.private_numbers()
        ppk_data = _build_rsa_ppk_fixture(
            n=numbers.public_numbers.n,
            e=numbers.public_numbers.e,
            d=numbers.d,
            p=numbers.p,
            q=numbers.q,
            iqmp=numbers.iqmp,
            trailing_padding=b"\x01\x02\x03",
            version=2,
        )

        converted, reason = SFTPClient._convert_ppk_with_pure_python(
            ppk_data,
            passphrase=None,
            ppk_variant="PPK v2 (ssh-rsa, encryption=none)",
        )

        assert reason == ""
        assert converted is not None
        imported = asyncssh.import_private_key(converted)
        assert imported is not None

    def test_convert_ppk_rsa_unencrypted_rejects_non_padding_trailing_bytes(self):
        malformed_ppk = _build_rsa_ppk_fixture(
            n=143,
            e=65537,
            d=17,
            p=11,
            q=13,
            iqmp=6,
            trailing_padding=b"\xff",
            version=2,
        )
        converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(malformed_ppk)

        assert converted is None
        assert "trailing data in PPK private blob" in reason

    def test_convert_ppk_with_pure_python_rsa_uses_native_rebuild_not_converter_output(
        self, monkeypatch
    ):
        import asyncssh
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        numbers = private_key.private_numbers()
        ppk_data = _build_rsa_ppk_fixture(
            n=numbers.public_numbers.n,
            e=numbers.public_numbers.e,
            d=numbers.d,
            p=numbers.p,
            q=numbers.q,
            version=2,
        )

        fake_puttykeys = types.ModuleType("puttykeys")
        fake_puttykeys.ppkraw_to_openssh = lambda _text, _pass: b"MALFORMED-CONVERTER-OUTPUT"
        monkeypatch.setitem(sys.modules, "puttykeys", fake_puttykeys)

        converted, reason = SFTPClient._convert_ppk_with_pure_python(
            ppk_data,
            passphrase=None,
            ppk_variant="PPK (.ppk)",
        )

        assert reason == ""
        assert converted is not None
        assert converted != b"MALFORMED-CONVERTER-OUTPUT"
        imported = asyncssh.import_private_key(converted)
        assert imported is not None

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.import_private_key")
    @patch("asyncssh.read_private_key")
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_ppk_v3_uses_conversion_first_path_without_native_parse(
        self,
        mock_connect,
        mock_read_private_key,
        mock_import_private_key,
        _mock_exists,
    ):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        converted_key_obj = object()
        mock_import_private_key.return_value = converted_key_obj

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
        )
        client = SFTPClient(info)

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\n",
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_with_pure_python",
                return_value=(b"-----BEGIN OPENSSH PRIVATE KEY-----\n", ""),
            ),
            patch("subprocess.run") as mock_subprocess_run,
        ):
            client.connect()
            mock_subprocess_run.assert_not_called()

        mock_read_private_key.assert_not_called()
        mock_import_private_key.assert_called_once_with(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
        kwargs = mock_connect.call_args[1]
        assert kwargs["client_keys"] == [converted_key_obj]
        assert kwargs["agent_path"] is None

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.import_private_key")
    @patch("asyncssh.read_private_key")
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_ppk_v3_unsupported_subtype_has_actionable_error(
        self, mock_connect, mock_read_private_key, mock_import_private_key, _mock_exists
    ):
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
        )
        client = SFTPClient(info)

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: aes256-cbc\n",
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_with_pure_python",
                return_value=(
                    None,
                    "unsupported PPK variant for PPK v3 (ssh-ed25519, encryption=aes256-cbc)",
                ),
            ),
            pytest.raises(ConnectionError) as exc,
        ):
            client.connect()

        msg = str(exc.value)
        assert "PPK v3 (ssh-ed25519, encryption=aes256-cbc)" in msg
        assert "not supported by puttykeys" in msg
        assert "Export OpenSSH key" in msg
        mock_read_private_key.assert_not_called()
        mock_import_private_key.assert_not_called()
        mock_connect.assert_not_called()

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.import_private_key")
    @patch("asyncssh.read_private_key")
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_ppk_wrong_passphrase_has_hint(
        self, mock_connect, mock_read_private_key, mock_import_private_key, _
    ):
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
            password="wrong",
        )
        client = SFTPClient(info)

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"PuTTY-User-Key-File-3: ssh-ed25519\n",
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_with_pure_python",
                return_value=(None, "HMAC mismatch (bad passphrase?)"),
            ),
            pytest.raises(ConnectionError) as exc,
        ):
            client.connect()

        msg = str(exc.value).lower()
        assert "passphrase" in msg
        assert "re-export as openssh" in msg
        mock_read_private_key.assert_not_called()
        mock_import_private_key.assert_not_called()
        mock_connect.assert_not_called()

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.import_private_key")
    @patch("asyncssh.read_private_key")
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_ppk_missing_puttykeys_has_clear_error(
        self, mock_connect, mock_read_private_key, mock_import_private_key, _
    ):
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
        )
        client = SFTPClient(info)

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\n",
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_with_pure_python",
                return_value=(None, "required dependency 'puttykeys' is not installed"),
            ),
            pytest.raises(ConnectionError) as exc,
        ):
            client.connect()

        msg = str(exc.value).lower()
        assert "puttykeys" in msg
        assert "required" in msg
        mock_read_private_key.assert_not_called()
        mock_import_private_key.assert_not_called()
        mock_connect.assert_not_called()

    def test_read_private_key_file_reads_bytes(self, tmp_path):
        key_file = tmp_path / "id_test.ppk"
        key_file.write_bytes(b"abc123")

        assert SFTPClient._read_private_key_file(str(key_file)) == b"abc123"

    def test_parse_ppk_header_non_ppk_and_invalid_ascii(self):
        is_ppk, variant = SFTPClient._parse_ppk_header(b"OPENSSH PRIVATE KEY\n")
        assert is_ppk is False
        assert variant == ""

        is_ppk, variant = SFTPClient._parse_ppk_header(b"PuTTY-User-Key-File-\xff: ssh-ed25519\n")
        assert is_ppk is True
        assert variant == "PPK"

    def test_parse_ppk_header_handles_non_ascii_encryption_line(self):
        is_ppk, variant = SFTPClient._parse_ppk_header(
            b"PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: \xff\n"
        )

        assert is_ppk is True
        assert variant == "PPK v3 (ssh-ed25519, encryption=unknown-encryption)"

    @pytest.mark.parametrize(
        ("blob", "offset", "message"),
        [
            (b"\x00\x00\x00", 0, "truncated PPK binary data"),
            (b"\x00\x00\x00\x05ab", 0, "truncated PPK binary data"),
        ],
    )
    def test_read_ppk_string_rejects_truncated_data(self, blob, offset, message):
        with pytest.raises(ValueError, match=message):
            SFTPClient._read_ppk_string(blob, offset)

    @pytest.mark.parametrize(
        ("key_data", "message"),
        [
            (b"\xff", "PPK data is not valid UTF-8 text"),
            (b"", "empty PPK file"),
            (b"not-a-ppk\n", "not a PuTTY PPK file"),
            (b"PuTTY-User-Key-File-3:\n", "missing key type in PPK header"),
            (b"PuTTY-User-Key-File-x: ssh-ed25519\n", "invalid PPK version header"),
        ],
    )
    def test_decode_ppk_text_rejects_invalid_headers(self, key_data, message):
        with pytest.raises(ValueError, match=message):
            SFTPClient._decode_ppk_text(key_data)

    @pytest.mark.parametrize(
        ("key_data", "message"),
        [
            (
                (
                    "PuTTY-User-Key-File-3: ssh-ed25519\n"
                    "Encryption: none\n"
                    "Comment: test\n"
                    "Public-Lines: not-a-number\n"
                    "AA==\n"
                    "Private-Lines: 1\n"
                    "AA==\n"
                    "Private-MAC: 00\n"
                ).encode("utf-8"),
                "invalid Public-Lines value in PPK",
            ),
            (
                (
                    "PuTTY-User-Key-File-3: ssh-ed25519\n"
                    "Encryption: none\n"
                    "Comment: test\n"
                    "Public-Lines: 2\n"
                    "AA==\n"
                ).encode("utf-8"),
                "truncated Public-Lines data in PPK",
            ),
            (
                (
                    "PuTTY-User-Key-File-3: ssh-ed25519\n"
                    "Comment: test\n"
                    "Public-Lines: 1\n"
                    "AA==\n"
                    "Private-Lines: 1\n"
                    "AA==\n"
                    "Private-MAC: 00\n"
                ).encode("utf-8"),
                "missing Encryption field in PPK",
            ),
            (
                (
                    "PuTTY-User-Key-File-3: ssh-ed25519\n"
                    "Encryption: none\n"
                    "Public-Lines: 1\n"
                    "AA==\n"
                    "Private-Lines: 1\n"
                    "AA==\n"
                    "Private-MAC: 00\n"
                ).encode("utf-8"),
                "missing Comment field in PPK",
            ),
            (
                (
                    "PuTTY-User-Key-File-3: ssh-ed25519\n"
                    "Encryption: none\n"
                    "Comment: test\n"
                    "Private-Lines: 1\n"
                    "AA==\n"
                    "Private-MAC: 00\n"
                ).encode("utf-8"),
                "PPK missing either Public-Lines or Private-Lines",
            ),
            (
                (
                    "PuTTY-User-Key-File-3: ssh-ed25519\n"
                    "Encryption: none\n"
                    "Comment: test\n"
                    "Public-Lines: 1\n"
                    "AA==\n"
                    "Private-Lines: 1\n"
                    "AA==\n"
                ).encode("utf-8"),
                "missing Private-MAC field in PPK",
            ),
            (
                (
                    "PuTTY-User-Key-File-3: ssh-ed25519\n"
                    "Encryption: none\n"
                    "Comment: test\n"
                    "Public-Lines: 1\n"
                    "@@@@\n"
                    "Private-Lines: 1\n"
                    "AA==\n"
                    "Private-MAC: 00\n"
                ).encode("utf-8"),
                "invalid base64 data in PPK",
            ),
        ],
    )
    def test_decode_ppk_text_rejects_invalid_fields(self, key_data, message):
        with pytest.raises(ValueError, match=message):
            SFTPClient._decode_ppk_text(key_data)

    def test_convert_ppk_v3_native_rejects_version_keytype_encryption_and_mac(self):
        with patch("portkeydrop.protocols.SFTPClient._decode_ppk_text") as mock_decode:
            mock_decode.return_value = _build_native_converter_input()
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is not None
            assert reason == ""

            mock_decode.return_value = (
                2,
                "ssh-ed25519",
                "none",
                "native",
                _pack_ppk_string(b"ssh-ed25519") + _pack_ppk_string(b"P" * 32),
                _pack_ppk_string(b"S" * 32),
                "00",
            )
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is None
            assert "unsupported PPK version" in reason

            mock_decode.return_value = _build_native_converter_input(key_type="ssh-rsa")
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is None
            assert "unsupported PPK key type" in reason

            mock_decode.return_value = _build_native_converter_input(encryption="aes256-cbc")
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is None
            assert "unsupported PPK encryption" in reason

            tuple_with_bad_mac = _build_native_converter_input()
            mock_decode.return_value = (*tuple_with_bad_mac[:-1], "deadbeef")
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is None
            assert "private MAC mismatch" in reason

    def test_convert_ppk_v3_native_rejects_public_private_blob_edge_cases(self):
        with patch("portkeydrop.protocols.SFTPClient._decode_ppk_text") as mock_decode:
            bad_public_type = _pack_ppk_string(b"ssh-rsa") + _pack_ppk_string(b"P" * 32)
            mock_decode.return_value = _build_native_converter_input(public_blob=bad_public_type)
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is None
            assert "unsupported public key type" in reason

            trailing_public = (
                _pack_ppk_string(b"ssh-ed25519") + _pack_ppk_string(b"P" * 32) + b"extra"
            )
            mock_decode.return_value = _build_native_converter_input(public_blob=trailing_public)
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is None
            assert "trailing data in PPK public blob" in reason

            trailing_private = _pack_ppk_string(b"S" * 32) + b"extra"
            mock_decode.return_value = _build_native_converter_input(private_blob=trailing_private)
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is None
            assert "trailing data in PPK private blob" in reason

            mock_decode.return_value = _build_native_converter_input(private_blob=b"\x00\x00")
            result, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(b"unused")
            assert result is None
            assert reason == "truncated PPK binary data"

    def test_convert_ppk_with_pure_python_branches(self, monkeypatch):
        fake_puttykeys = types.ModuleType("puttykeys")
        fake_puttykeys.ppkraw_to_openssh = lambda _text, _pass: b"converted-key"
        monkeypatch.setitem(sys.modules, "puttykeys", fake_puttykeys)

        converted, reason = SFTPClient._convert_ppk_with_pure_python(
            b"not-ppk", passphrase=None, ppk_variant="PPK (.ppk)"
        )
        assert reason == ""
        assert converted == b"converted-key"

        fake_puttykeys.ppkraw_to_openssh = lambda _text, _pass: ""
        converted, reason = SFTPClient._convert_ppk_with_pure_python(
            b"not-ppk", passphrase=None, ppk_variant="PPK v3 (ssh-ed25519, encryption=aes256-cbc)"
        )
        assert converted is None
        assert "unsupported PPK variant" in reason

        fake_puttykeys.ppkraw_to_openssh = lambda _text, _pass: "converted-text"
        converted, reason = SFTPClient._convert_ppk_with_pure_python(
            b"not-ppk", passphrase=None, ppk_variant="PPK (.ppk)"
        )
        assert reason == ""
        assert converted == b"converted-text"

        fake_puttykeys.ppkraw_to_openssh = lambda _text, _pass: (_ for _ in ()).throw(
            RuntimeError("conversion boom")
        )
        converted, reason = SFTPClient._convert_ppk_with_pure_python(
            b"not-ppk", passphrase=None, ppk_variant="PPK (.ppk)"
        )
        assert converted is None
        assert reason == "conversion boom"

        converted, reason = SFTPClient._convert_ppk_with_pure_python(
            b"\xff", passphrase=None, ppk_variant="PPK (.ppk)"
        )
        assert converted is None
        assert reason == "PPK data is not valid UTF-8 text"

    def test_convert_ppk_with_pure_python_handles_missing_puttykeys(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "puttykeys", raising=False)

        original_import = __import__

        def fail_puttykeys_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "puttykeys":
                raise ImportError("no puttykeys")
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fail_puttykeys_import):
            converted, reason = SFTPClient._convert_ppk_with_pure_python(
                b"not-ppk",
                passphrase=None,
                ppk_variant="PPK (.ppk)",
            )

        assert converted is None
        assert reason == "required dependency 'puttykeys' is not installed"

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.import_private_key")
    def test_load_client_key_ppk_import_private_key_error(self, mock_import_private_key, _exists):
        import asyncssh

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
        )
        client = SFTPClient(info)
        mock_import_private_key.side_effect = asyncssh.KeyImportError("bad converted key")

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\n",
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_with_pure_python",
                return_value=(b"-----BEGIN OPENSSH PRIVATE KEY-----\n", ""),
            ),
            pytest.raises(ConnectionError, match="converted OpenSSH key import failed"),
        ):
            client._load_client_key("/tmp/key.ppk", None)

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.import_private_key")
    def test_load_client_key_ppk_dmp1_odd_uses_native_rsa_repair(self, mock_import_private_key, _):
        import asyncssh

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
        )
        client = SFTPClient(info)
        repaired_key = object()
        mock_import_private_key.side_effect = [
            asyncssh.KeyImportError("dmp1 must be odd"),
            repaired_key,
        ]

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"PuTTY-User-Key-File-2: ssh-rsa\nEncryption: none\n",
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_with_pure_python",
                return_value=(b"-----BEGIN OPENSSH PRIVATE KEY-----\n", ""),
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_rsa_unencrypted",
                return_value=(b"-----BEGIN RSA PRIVATE KEY-----\n", ""),
            ) as mock_rsa_repair,
        ):
            key_obj, auth_label = client._load_client_key("/tmp/key.ppk", None)

        assert key_obj is repaired_key
        assert "repaired RSA conversion" in auth_label
        assert mock_import_private_key.call_count == 2
        mock_rsa_repair.assert_called_once()

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.import_private_key")
    def test_load_client_key_ppk_dmp1_odd_reports_actionable_reason(
        self, mock_import_private_key, _
    ):
        import asyncssh

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
        )
        client = SFTPClient(info)
        mock_import_private_key.side_effect = asyncssh.KeyImportError("dmp1 must be odd")

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"PuTTY-User-Key-File-3: ssh-rsa\nEncryption: none\n",
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_with_pure_python",
                return_value=(b"-----BEGIN OPENSSH PRIVATE KEY-----\n", ""),
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_rsa_unencrypted",
                return_value=(None, "PPK RSA parameters are inconsistent (n != p*q)"),
            ),
            pytest.raises(ConnectionError) as exc,
        ):
            client._load_client_key("/tmp/key.ppk", None)

        msg = str(exc.value).lower()
        assert "converted rsa key material is malformed" in msg
        assert "export openssh key" in msg
        assert "dmp1 must be odd" not in msg

    @patch("os.path.exists", return_value=True)
    def test_load_client_key_ppk_rsa_malformed_fixture_has_actionable_message(self, _):
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
        )
        client = SFTPClient(info)
        malformed_ppk = _build_rsa_ppk_fixture(n=144, e=65537, d=17, p=11, q=13, version=2)

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=malformed_ppk,
            ),
            pytest.raises(ConnectionError) as exc,
        ):
            client._load_client_key("/tmp/key.ppk", None)

        msg = str(exc.value).lower()
        assert "n != p*q" in msg
        assert "direct parsing failed" in msg

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.import_private_key")
    def test_load_client_key_ppk_dmp1_value_error_is_mapped(self, mock_import_private_key, _):
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/key.ppk",
        )
        client = SFTPClient(info)
        mock_import_private_key.side_effect = ValueError("dmp1 must be odd")

        with (
            patch(
                "portkeydrop.protocols.SFTPClient._read_private_key_file",
                return_value=b"PuTTY-User-Key-File-2: ssh-rsa\nEncryption: none\n",
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_with_pure_python",
                return_value=(b"-----BEGIN OPENSSH PRIVATE KEY-----\n", ""),
            ),
            patch(
                "portkeydrop.protocols.SFTPClient._convert_ppk_rsa_unencrypted",
                return_value=(None, "PPK RSA parameters are inconsistent (n != p*q)"),
            ),
            pytest.raises(ConnectionError) as exc,
        ):
            client._load_client_key("/tmp/key.ppk", None)

        msg = str(exc.value).lower()
        assert "converted rsa key material is malformed" in msg
        assert "export openssh key" in msg
        assert "dmp1 must be odd" not in msg

    def test_format_key_import_error_covers_fallback_paths(self):
        ppk_passphrase_msg = SFTPClient._format_key_import_error(
            "wrong passphrase", is_ppk=True, ppk_variant="PPK v3 (ssh-ed25519, encryption=none)"
        )
        assert (
            "key is likely encrypted or the passphrase is incorrect" in ppk_passphrase_msg.lower()
        )

        ppk_generic_msg = SFTPClient._format_key_import_error(
            "unexpected parser failure", is_ppk=True, ppk_variant="PPK"
        )
        assert "direct parsing failed" in ppk_generic_msg.lower()

        ppk_invalid_rsa_msg = SFTPClient._format_key_import_error(
            "converted OpenSSH key import failed: dmp1 must be odd",
            is_ppk=True,
            ppk_variant="PPK v2 (ssh-rsa, encryption=none)",
        )
        assert "converted rsa key material is malformed" in ppk_invalid_rsa_msg.lower()

        generic_non_ppk_msg = SFTPClient._format_key_import_error("totally unknown", is_ppk=False)
        assert "could not import the private key" in generic_non_ppk_msg.lower()

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_disconnect(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        info = ConnectionInfo(protocol=Protocol.SFTP, host="example.com")
        client = SFTPClient(info)
        client.connect()
        client.disconnect()

        assert not client.connected
        mock_sftp.exit.assert_called_once()
        mock_conn.close.assert_called_once()

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

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_list_dir_maps_file_attributes(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/home/user"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        file_entry = MagicMock()
        file_entry.filename = "file.txt"
        file_entry.attrs = MagicMock()
        file_entry.attrs.permissions = stat_mod.S_IFREG | 0o644
        file_entry.attrs.size = 123
        file_entry.attrs.mtime = 1700000000
        file_entry.attrs.uid = 1000
        file_entry.attrs.gid = 1000
        file_entry.longname = "-rw-r--r--"

        dir_entry = MagicMock()
        dir_entry.filename = "docs"
        dir_entry.attrs = MagicMock()
        dir_entry.attrs.permissions = stat_mod.S_IFDIR | 0o755
        dir_entry.attrs.size = 0
        dir_entry.attrs.mtime = 1700000000
        dir_entry.attrs.uid = 1000
        dir_entry.attrs.gid = 1000
        dir_entry.longname = "drwxr-xr-x"

        dot_entry = MagicMock()
        dot_entry.filename = "."

        # list_dir uses _readdir_safe which calls sftp._handler.opendir/readdir directly.
        mock_handler = AsyncMock()
        mock_sftp._handler = mock_handler
        mock_sftp.compose_path.return_value = b"/home/user"
        # First call returns entries, second call returns empty (EOF signal)
        mock_handler.readdir.side_effect = [
            ([dot_entry, file_entry, dir_entry], True),
        ]

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()
        files = client.list_dir(".")

        assert len(files) == 2
        assert files[0].name == "file.txt"
        assert files[0].is_dir is False
        assert files[0].size == 123
        assert files[1].name == "docs"
        assert files[1].is_dir is True

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_chdir_download_upload_and_file_ops(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.side_effect = ["/", "/uploads", "/remote.bin"]
        # chdir now validates with stat — return directory attributes
        chdir_stat_attrs = MagicMock()
        chdir_stat_attrs.permissions = stat_mod.S_IFDIR | 0o755
        chdir_stat_attrs.type = None
        mock_sftp.stat.return_value = chdir_stat_attrs
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        assert client.chdir("/uploads") == "/uploads"

        # Download
        download_calls: list[tuple[int, int]] = []
        mock_remote_file = AsyncMock()
        mock_remote_file.read.side_effect = [b"0123456789", b""]
        mock_open_cm = MagicMock()
        mock_open_cm.__aenter__ = AsyncMock(return_value=mock_remote_file)
        mock_open_cm.__aexit__ = AsyncMock(return_value=False)
        mock_sftp.open = MagicMock(return_value=mock_open_cm)
        stat_attrs = MagicMock()
        stat_attrs.size = 10
        stat_attrs.permissions = stat_mod.S_IFREG | 0o644
        mock_sftp.stat.return_value = stat_attrs

        client.download(
            "/remote.bin", MagicMock(), callback=lambda t, n: download_calls.append((t, n))
        )
        assert download_calls == [(10, 10)]

        # Upload
        upload_calls: list[tuple[int, int]] = []
        mock_write_file = AsyncMock()
        mock_open_cm.__aenter__ = AsyncMock(return_value=mock_write_file)

        upload_stat_attrs = MagicMock()
        upload_stat_attrs.size = 4
        upload_stat_attrs.permissions = stat_mod.S_IFREG | 0o644

        mkdir_stat_attrs = MagicMock()
        mkdir_stat_attrs.permissions = stat_mod.S_IFDIR | 0o755

        rename_stat_attrs = MagicMock()
        rename_stat_attrs.permissions = stat_mod.S_IFREG | 0o644

        async def stat_side_effect(path: str):
            if path == "/remote.txt":
                return upload_stat_attrs
            if path == "/a":
                raise FileNotFoundError(path)
            if path == "/b":
                if mock_sftp.rmdir.await_count > 0:
                    raise FileNotFoundError(path)
                return mkdir_stat_attrs
            if path == "/new":
                return rename_stat_attrs
            raise FileNotFoundError(path)

        mock_sftp.stat.side_effect = stat_side_effect

        client.upload(
            io.BytesIO(b"data"),
            "/remote.txt",
            callback=lambda t, n: upload_calls.append((t, n)),
        )
        assert upload_calls == [(4, 4)]

        client.delete("/a")
        client.mkdir("/b")
        client.rmdir("/b")
        client.rename("/old", "/new")
        mock_sftp.remove.assert_awaited_once_with("/a")
        mock_sftp.mkdir.assert_awaited_once_with("/b")
        mock_sftp.rmdir.assert_awaited_once_with("/b")
        mock_sftp.rename.assert_awaited_once_with("/old", "/new")

    @patch("ftplib.FTP")
    def test_ftp_rename_raises_when_target_not_found_after_rename(self, mock_ftp_class):
        mock_ftp = MagicMock()
        mock_ftp.pwd.return_value = "/"
        mock_ftp.sendcmd.side_effect = Exception("550 not found")
        mock_ftp_class.return_value = mock_ftp

        info = ConnectionInfo(protocol=Protocol.FTP, host="example.com")
        client = FTPClient(info)
        client.connect()

        with pytest.raises(RuntimeError, match="verification failed"):
            client.rename("/old.txt", "/new.txt")

    @patch("os.path.exists", return_value=True)
    @patch("asyncssh.read_private_key", return_value=object())
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_connect_with_key_and_stat(self, mock_connect, mock_read_private_key, _mock_exists):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            username="user",
            key_path="/tmp/id_rsa",
        )
        client = SFTPClient(info)
        with patch(
            "portkeydrop.protocols.SFTPClient._read_private_key_file",
            return_value=b"-----BEGIN OPENSSH PRIVATE KEY-----\n",
        ):
            client.connect()

        kwargs = mock_connect.call_args[1]
        assert kwargs["agent_path"] is None
        assert kwargs["client_keys"] == [mock_read_private_key.return_value]

        stat_attrs = MagicMock()
        stat_attrs.permissions = stat_mod.S_IFREG | 0o644
        stat_attrs.size = 42
        stat_attrs.mtime = 1700000000
        mock_sftp.stat.return_value = stat_attrs
        remote = client.stat("/remote/file.txt")
        assert remote.name == "file.txt"
        assert remote.path == "/remote/file.txt"
        assert remote.size == 42
        assert remote.is_dir is False

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_upload_raises_when_remote_size_mismatch(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        mock_write_file = AsyncMock()
        mock_open_cm = MagicMock()
        mock_open_cm.__aenter__ = AsyncMock(return_value=mock_write_file)
        mock_open_cm.__aexit__ = AsyncMock(return_value=False)
        mock_sftp.open = MagicMock(return_value=mock_open_cm)

        stat_attrs = MagicMock()
        stat_attrs.size = 3
        stat_attrs.permissions = stat_mod.S_IFREG | 0o644
        mock_sftp.stat.return_value = stat_attrs

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        with pytest.raises(RuntimeError, match="verification failed"):
            client.upload(io.BytesIO(b"data"), "/remote.txt")

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_mkdir_raises_when_created_path_is_not_directory(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        stat_attrs = MagicMock()
        stat_attrs.permissions = stat_mod.S_IFREG | 0o644
        stat_attrs.size = 10
        mock_sftp.stat.return_value = stat_attrs

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        with pytest.raises(RuntimeError, match="verification failed"):
            client.mkdir("/not-a-dir")

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_delete_raises_when_remote_stat_succeeds(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        mock_sftp.stat.return_value = MagicMock()

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        with pytest.raises(RuntimeError, match="verification failed"):
            client.delete("/file")

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_rmdir_raises_when_remote_stat_succeeds(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        mock_sftp.stat.return_value = MagicMock()

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        with pytest.raises(RuntimeError, match="verification failed"):
            client.rmdir("/dir")


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


class TestSFTPClientNativeTransfer:
    """Tests for asyncssh sftp.get()/put() with progress_handler."""

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_download_uses_native_get_with_progress(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.side_effect = lambda p: "/" if p == "." else p
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        progress_calls: list[tuple[int, int]] = []

        async def fake_get(remotepath, localpath, *, progress_handler=None, **kwargs):
            if progress_handler:
                progress_handler(remotepath, localpath, 0, 1000)
                progress_handler(remotepath, localpath, 500, 1000)
                progress_handler(remotepath, localpath, 1000, 1000)

        mock_sftp.get = AsyncMock(side_effect=fake_get)

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        close_mock = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "/tmp/downloaded.bin"
        mock_file.close = close_mock

        client.download(
            "/remote/file.bin",
            mock_file,
            callback=lambda t, n: progress_calls.append((t, n)),
        )

        mock_sftp.get.assert_awaited_once()
        call_kwargs = mock_sftp.get.call_args
        assert call_kwargs[0][0] == "/remote/file.bin"
        assert call_kwargs[0][1] == "/tmp/downloaded.bin"
        assert call_kwargs[1]["progress_handler"] is not None
        assert progress_calls == [(0, 1000), (500, 1000), (1000, 1000)]
        close_mock.assert_called_once()

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_download_no_callback_still_uses_native_get(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.side_effect = lambda p: "/" if p == "." else p
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        close_mock = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "/tmp/downloaded.bin"
        mock_file.close = close_mock

        client.download("/remote/file.bin", mock_file)

        mock_sftp.get.assert_awaited_once()
        call_kwargs = mock_sftp.get.call_args
        assert call_kwargs[1]["progress_handler"] is None
        close_mock.assert_called_once()

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_download_bytesio_uses_chunked_fallback(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.side_effect = lambda p: "/" if p == "." else p
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        mock_remote_file = AsyncMock()
        mock_remote_file.read.side_effect = [b"hello", b""]
        mock_open_cm = MagicMock()
        mock_open_cm.__aenter__ = AsyncMock(return_value=mock_remote_file)
        mock_open_cm.__aexit__ = AsyncMock(return_value=False)
        mock_sftp.open = MagicMock(return_value=mock_open_cm)
        stat_attrs = MagicMock()
        stat_attrs.size = 5
        mock_sftp.stat.return_value = stat_attrs

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        buf = io.BytesIO()
        progress_calls: list[tuple[int, int]] = []
        client.download(
            "/remote.txt",
            buf,
            callback=lambda t, n: progress_calls.append((t, n)),
        )

        assert buf.getvalue() == b"hello"
        assert progress_calls == [(5, 5)]
        mock_sftp.get.assert_not_awaited()

    @patch("os.path.getsize", return_value=4)
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_upload_uses_native_put_with_progress(self, mock_connect, _mock_getsize):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        progress_calls: list[tuple[int, int]] = []

        async def fake_put(localpath, remotepath, *, progress_handler=None, **kwargs):
            if progress_handler:
                progress_handler(localpath, remotepath, 0, 4)
                progress_handler(localpath, remotepath, 4, 4)

        mock_sftp.put = AsyncMock(side_effect=fake_put)

        stat_attrs = MagicMock()
        stat_attrs.size = 4
        mock_sftp.stat.return_value = stat_attrs

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        close_mock = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "/tmp/upload.bin"
        mock_file.close = close_mock

        client.upload(
            mock_file,
            "/remote/file.bin",
            callback=lambda t, n: progress_calls.append((t, n)),
        )

        mock_sftp.put.assert_awaited_once()
        call_kwargs = mock_sftp.put.call_args
        assert call_kwargs[0][0] == "/tmp/upload.bin"
        assert call_kwargs[0][1] == "/remote/file.bin"
        assert call_kwargs[1]["progress_handler"] is not None
        assert progress_calls == [(0, 4), (4, 4)]
        close_mock.assert_called_once()

    @patch("os.path.getsize", return_value=4)
    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_upload_verifies_remote_size(self, mock_connect, _mock_getsize):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        stat_attrs = MagicMock()
        stat_attrs.size = 2  # Mismatch: expected 4
        mock_sftp.stat.return_value = stat_attrs

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        mock_file = MagicMock()
        mock_file.name = "/tmp/upload.bin"

        with pytest.raises(RuntimeError, match="verification failed"):
            client.upload(mock_file, "/remote.bin")

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_upload_bytesio_uses_chunked_fallback(self, mock_connect):
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        mock_write_file = AsyncMock()
        mock_open_cm = MagicMock()
        mock_open_cm.__aenter__ = AsyncMock(return_value=mock_write_file)
        mock_open_cm.__aexit__ = AsyncMock(return_value=False)
        mock_sftp.open = MagicMock(return_value=mock_open_cm)

        stat_attrs = MagicMock()
        stat_attrs.size = 4
        mock_sftp.stat.return_value = stat_attrs

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        progress_calls: list[tuple[int, int]] = []
        client.upload(
            io.BytesIO(b"data"),
            "/remote.txt",
            callback=lambda t, n: progress_calls.append((t, n)),
        )

        assert progress_calls == [(4, 4)]
        mock_sftp.put.assert_not_awaited()


class TestSFTPDownloadSymlinkResolution:
    """Tests that SFTPClient.download() resolves symlinks via realpath."""

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_download_resolves_symlink_via_realpath(self, mock_connect):
        """Native get() path uses the resolved path for symlinked files."""
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.side_effect = [
            "/",  # connect
            "/real/file.bin",  # download resolves symlink
        ]
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        progress_calls: list[tuple[int, int]] = []

        async def fake_get(remotepath, localpath, *, progress_handler=None, **kwargs):
            if progress_handler:
                progress_handler(remotepath, localpath, 500, 1000)
                progress_handler(remotepath, localpath, 1000, 1000)

        mock_sftp.get = AsyncMock(side_effect=fake_get)

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        mock_file = MagicMock()
        mock_file.name = "/tmp/downloaded.bin"
        mock_file.close = MagicMock()

        client.download(
            "/symlink/file.bin",
            mock_file,
            callback=lambda t, n: progress_calls.append((t, n)),
        )

        # Verify get() was called with the resolved path
        call_args = mock_sftp.get.call_args
        assert call_args[0][0] == "/real/file.bin"
        assert progress_calls == [(500, 1000), (1000, 1000)]

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_download_fallback_resolves_symlink_via_realpath(self, mock_connect):
        """BytesIO fallback path uses the resolved path for symlinked files."""
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.side_effect = [
            "/",  # connect
            "/real/file.txt",  # download resolves symlink
        ]
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        mock_remote_file = AsyncMock()
        mock_remote_file.read.side_effect = [b"hello", b""]
        mock_open_cm = MagicMock()
        mock_open_cm.__aenter__ = AsyncMock(return_value=mock_remote_file)
        mock_open_cm.__aexit__ = AsyncMock(return_value=False)
        mock_sftp.open = MagicMock(return_value=mock_open_cm)
        stat_attrs = MagicMock()
        stat_attrs.size = 5
        mock_sftp.stat.return_value = stat_attrs

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        buf = io.BytesIO()
        progress_calls: list[tuple[int, int]] = []
        client.download(
            "/symlink/file.txt",
            buf,
            callback=lambda t, n: progress_calls.append((t, n)),
        )

        # Verify open() and stat() were called with the resolved path
        mock_sftp.open.assert_called_once_with("/real/file.txt", "rb")
        mock_sftp.stat.assert_called_once_with("/real/file.txt")
        assert buf.getvalue() == b"hello"
        assert progress_calls == [(5, 5)]

    @patch("asyncssh.connect", new_callable=AsyncMock)
    def test_download_falls_back_to_original_path_when_realpath_fails(self, mock_connect):
        """If realpath fails, download uses the original path."""
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.side_effect = [
            "/",  # connect
            OSError("realpath failed"),  # download fallback
        ]
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn

        progress_calls: list[tuple[int, int]] = []

        async def fake_get(remotepath, localpath, *, progress_handler=None, **kwargs):
            if progress_handler:
                progress_handler(remotepath, localpath, 100, 100)

        mock_sftp.get = AsyncMock(side_effect=fake_get)

        client = SFTPClient(ConnectionInfo(protocol=Protocol.SFTP, host="example.com"))
        client.connect()

        mock_file = MagicMock()
        mock_file.name = "/tmp/downloaded.bin"
        mock_file.close = MagicMock()

        client.download(
            "/original/path.bin",
            mock_file,
            callback=lambda t, n: progress_calls.append((t, n)),
        )

        # Verify get() was called with the original path (fallback)
        call_args = mock_sftp.get.call_args
        assert call_args[0][0] == "/original/path.bin"
        assert progress_calls == [(100, 100)]


class TestProtocolEnum:
    def test_all_protocols(self):
        assert Protocol.FTP.value == "ftp"
        assert Protocol.FTPS.value == "ftps"
        assert Protocol.SFTP.value == "sftp"
        assert Protocol.SCP.value == "scp"
        assert Protocol.WEBDAV.value == "webdav"
