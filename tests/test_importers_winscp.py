from pathlib import Path
from unittest.mock import patch

from portkeydrop.importers import (
    WINSCP_REGISTRY_SENTINEL,
    detect_default_path,
    load_from_source,
)
from portkeydrop.importers.winscp import (
    _decrypt_winscp_password,
    _safe_decrypt,
    parse_ini_file,
)


_MAGIC = 0xA3  # Same magic as production code


def _encrypt_winscp_password(
    username: str,
    hostname: str,
    password: str,
    *,
    version: int = 0,
    shift: int = 0,
    key_prefix_override: str | None = None,
) -> str:
    """Build a WinSCP simple-encrypted payload for tests."""
    key = key_prefix_override if key_prefix_override is not None else (username + hostname)
    data = (key + password).encode("utf-8")

    def enc(v: int) -> str:
        """Encode one WinSCP-obfuscated byte as two hex chars."""
        x = (~v & 0xFF) ^ _MAGIC
        return f"{x:02X}"

    parts = [enc(0xFF), enc(version)]
    if version == 0:
        parts.append(enc(len(data)))
    elif version == 2:
        parts.extend([enc(len(data) >> 8), enc(len(data) & 0xFF)])
    else:
        raise ValueError("Unsupported test version")
    parts.append(enc(shift))
    parts.extend(enc(0) for _ in range(shift))
    parts.extend(enc(b) for b in data)
    return "".join(parts)


def test_parse_winscp_ini_fixture(tmp_path):
    """Parse a WinSCP INI file with encrypted passwords."""
    # Generate encrypted passwords at test time (no hardcoded hex)
    pw1_enc = _encrypt_winscp_password("testuser", "testhost.test", "testpass")
    pw2_enc = _encrypt_winscp_password("user", "host.test", "mypassword")

    ini_content = f"""[Configuration\\Interface]
RandomValue=1

[Sessions\\Prod%20Server]
HostName=testhost.test
PortNumber=22
FSProtocol=0
UserName=testuser
Password={pw1_enc}
RemoteDirectory=/home/alice
PublicKeyFile=C:\\keys\\id_ed25519.ppk

[Sessions\\FTP%20Server]
HostName=host.test
PortNumber=21
FileProtocol=ftp
UserName=user
Password={pw2_enc}
RemoteDirectory=/incoming
"""
    fixture = tmp_path / "winscp_sessions.ini"
    fixture.write_text(ini_content)
    sites = parse_ini_file(fixture)

    assert len(sites) == 2

    first = sites[0]
    assert first.name == "Prod Server"
    assert first.protocol == "sftp"
    assert first.host == "testhost.test"
    assert first.port == 22
    assert first.username == "testuser"
    assert first.password == "testpass"
    assert first.initial_dir == "/home/alice"
    assert first.key_path == "C:\\keys\\id_ed25519.ppk"

    second = sites[1]
    assert second.name == "FTP Server"
    assert second.protocol == "ftp"
    assert second.host == "host.test"
    assert second.port == 21
    assert second.password == "mypassword"


def test_parse_winscp_realistic_sanitized_export_fixture(tmp_path):
    fixture = Path("tests/fixtures/importers/winscp_real_export_sanitized.ini")
    content = fixture.read_text(encoding="utf-8")
    content = content.replace(
        "__PASSWORD_LINE_1__",
        "Password=" + _encrypt_winscp_password("ops", "sftp-edge.example.net", "Tr!cky#Pass1"),
    )
    content = content.replace(
        "__PASSWORD_LINE_2__",
        "Password="
        + _encrypt_winscp_password("ops", "sftp-backend.internal.example.net", "sshSecret!2"),
    )
    ini = tmp_path / "winscp_real_export_sanitized.ini"
    ini.write_text(content, encoding="utf-8")

    sites = parse_ini_file(ini)

    assert len(sites) == 3

    first = sites[0]
    assert first.name == "ops@sftp-edge.example.net"
    assert first.host == "sftp-edge.example.net"
    assert first.protocol == "sftp"
    assert first.port == 0
    assert first.username == "ops"
    assert first.password == "Tr!cky#Pass1"
    assert first.initial_dir == "/home/ops"

    second = sites[1]
    assert second.name == "ops@legacy-name.example.net"
    assert second.host == "sftp-backend.internal.example.net"
    assert second.protocol == "sftp"
    assert second.password == "sshSecret!2"
    assert second.initial_dir == "/.ssh"
    assert second.key_path == r"C:\Users\sanitized\Keys\id_ed25519 prod.ppk"

    third = sites[2]
    assert third.name == "readonly@no-password.example.net"
    assert third.password == ""
    assert third.initial_dir == "/archive"


def test_detect_default_path_returns_sentinel_when_registry_available():
    """detect_default_path should return the registry sentinel when the registry is available."""
    with patch("portkeydrop.importers._winscp_registry_available", return_value=True):
        result = detect_default_path("winscp")
    assert result == WINSCP_REGISTRY_SENTINEL


def test_detect_default_path_falls_back_to_ini_when_no_registry():
    """detect_default_path should return the INI path when registry is not available."""
    with patch("portkeydrop.importers._winscp_registry_available", return_value=False):
        result = detect_default_path("winscp")
    assert isinstance(result, Path)
    assert result.name == "WinSCP.ini"


def test_load_from_source_winscp_none_path_tries_registry():
    """load_from_source with path=None should try INI then fall back to registry."""
    with patch("portkeydrop.importers.winscp.detect_ini_path") as mock_ini:
        mock_ini.return_value = Path("/nonexistent/WinSCP.ini")
        with patch("portkeydrop.importers.winscp.parse_registry_sessions") as mock_reg:
            mock_reg.return_value = []
            load_from_source("winscp", None)
            mock_reg.assert_called_once()


def test_detect_ini_path_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    from portkeydrop.importers.winscp import detect_ini_path

    assert str(detect_ini_path()) == "/fake/appdata/WinSCP.ini"


def test_detect_ini_path_no_appdata(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    from portkeydrop.importers.winscp import detect_ini_path

    assert detect_ini_path().name == "WinSCP.ini"


def test_parse_ini_skips_non_session_sections(tmp_path):
    from portkeydrop.importers.winscp import parse_ini_file

    ini = tmp_path / "w.ini"
    ini.write_text(
        "[Configuration]\nKey=Value\n[Sessions\\MyHost]\nHostName=h.com\nPortNumber=22\nUserName=u\n"
    )
    assert len(parse_ini_file(ini)) == 1


def test_parse_ini_skips_missing_hostname(tmp_path):
    from portkeydrop.importers.winscp import parse_ini_file

    ini = tmp_path / "w.ini"
    ini.write_text("[Sessions\\NoHost]\nPortNumber=22\nUserName=u\n")
    assert parse_ini_file(ini) == []


def test_parse_ini_scp_mapped_to_sftp(tmp_path):
    from portkeydrop.importers.winscp import parse_ini_file

    ini = tmp_path / "w.ini"
    ini.write_text(
        "[Sessions\\H]\nHostName=scp.example.com\nPortNumber=22\nUserName=u\nFSProtocol=1\n"
    )
    assert parse_ini_file(ini)[0].protocol == "sftp"


def test_parse_ini_invalid_port(tmp_path):
    from portkeydrop.importers.winscp import parse_ini_file

    ini = tmp_path / "w.ini"
    ini.write_text("[Sessions\\H]\nHostName=h.com\nPortNumber=notanumber\nUserName=u\n")
    assert parse_ini_file(ini)[0].port == 0


def test_parse_registry_sessions_non_windows():
    import sys
    from unittest.mock import patch
    from portkeydrop.importers.winscp import parse_registry_sessions

    with patch.object(sys, "platform", "linux"):
        assert parse_registry_sessions() == []


def test_parse_registry_sessions_key_missing():
    import sys
    from unittest.mock import MagicMock, patch
    from portkeydrop.importers.winscp import parse_registry_sessions

    winreg_mock = MagicMock()
    winreg_mock.OpenKey.side_effect = OSError
    winreg_mock.HKEY_CURRENT_USER = 0
    with patch.dict("sys.modules", {"winreg": winreg_mock}):
        with patch.object(sys, "platform", "win32"):
            assert parse_registry_sessions() == []


def test_detect_protocol_ftps_flag():
    from portkeydrop.importers.winscp import _detect_protocol

    assert _detect_protocol({"Ftps": "1", "FSProtocol": "", "FileProtocol": ""}) == "ftps"


def test_detect_protocol_file_protocol_ftp():
    from portkeydrop.importers.winscp import _detect_protocol

    assert _detect_protocol({"FileProtocol": "ftp", "FSProtocol": "", "Ftps": ""}) == "ftp"


def test_detect_protocol_default_sftp():
    from portkeydrop.importers.winscp import _detect_protocol

    assert _detect_protocol({"FSProtocol": "", "FileProtocol": "", "Ftps": ""}) == "sftp"


def test_detect_protocol_numeric_ftp():
    from portkeydrop.importers.winscp import _detect_protocol

    assert _detect_protocol({"FSProtocol": "5", "FileProtocol": "", "Ftps": ""}) == "ftp"


def test_decode_name_url_encoded():
    from portkeydrop.importers.winscp import _decode_name

    assert _decode_name("My%20Server") == "My Server"


def test_decode_name_backslash():
    from portkeydrop.importers.winscp import _decode_name

    assert _decode_name("path%5Cto") == "path\\to"


def test_decrypt_winscp_password_known_value():
    """Decrypt a WinSCP-encrypted password generated from known inputs."""
    encrypted = _encrypt_winscp_password("testuser", "testhost.test", "testpass")
    assert _decrypt_winscp_password("testuser", "testhost.test", encrypted) == "testpass"


def test_decrypt_winscp_password_different_credentials():
    encrypted = _encrypt_winscp_password("user", "host.test", "mypassword")
    assert _decrypt_winscp_password("user", "host.test", encrypted) == "mypassword"


def test_safe_decrypt_empty_password():
    """Empty encrypted string returns empty password."""
    assert _safe_decrypt("", "alice", "host.com") == ""


def test_safe_decrypt_invalid_hex():
    """Malformed encrypted string returns empty password instead of crashing."""
    assert _safe_decrypt("ZZZZ", "alice", "host.com") == ""


def test_safe_decrypt_truncated():
    """Truncated encrypted data returns empty password instead of crashing."""
    assert _safe_decrypt("0000", "alice", "host.com") == ""


def test_safe_decrypt_key_prefix_mismatch_returns_empty():
    """Mismatched key-prefix payload is treated as untrusted and discarded."""
    encrypted = _encrypt_winscp_password(
        "user",
        "host.test",
        "mypassword",
        key_prefix_override="host.test",
    )
    assert _safe_decrypt(encrypted, "user", "host.test") == ""


def test_safe_decrypt_odd_length_hex_returns_empty():
    """Odd-length hex payload is malformed and returns empty."""
    assert _safe_decrypt("ABC", "alice", "host.com") == ""


def test_safe_decrypt_master_password_external_returns_empty():
    """Externally encrypted (master-password) payload is unsupported and ignored."""
    # FF + version 01 is an external-encrypted wrapper in WinSCP format.
    assert _safe_decrypt("A35D", "alice", "host.com") == ""


def test_decrypt_winscp_password_internal2_long_payload():
    """Version 2 uses a 2-byte payload length for longer data."""
    password = "p" * 300
    encrypted = _encrypt_winscp_password("alice", "host.test", password, version=2)
    assert _decrypt_winscp_password("alice", "host.test", encrypted) == password


def test_decrypt_winscp_password_with_shift():
    """Shift bytes should be skipped before payload bytes."""
    encrypted = _encrypt_winscp_password("alice", "host.test", "pass123", shift=7)
    assert _decrypt_winscp_password("alice", "host.test", encrypted) == "pass123"


def test_parse_ini_missing_password_field(tmp_path):
    """Sessions without a Password field get empty password."""
    ini = tmp_path / "w.ini"
    ini.write_text("[Sessions\\H]\nHostName=h.com\nPortNumber=22\nUserName=u\n")
    assert parse_ini_file(ini)[0].password == ""


def test_parse_ini_utf16_export(tmp_path):
    """UTF-16 exports should parse without manual recoding."""
    encrypted = _encrypt_winscp_password("alice", "host.test", "secret")
    ini = tmp_path / "w.ini"
    ini.write_text(
        "[Sessions\\UTF16]\n"
        "HostName=host.test\n"
        "PortNumber=22\n"
        "UserName=alice\n"
        f"Password={encrypted}\n",
        encoding="utf-16",
    )
    sites = parse_ini_file(ini)
    assert len(sites) == 1
    assert sites[0].password == "secret"


def test_parse_ini_decodes_url_encoded_fields(tmp_path):
    ini = tmp_path / "w.ini"
    ini.write_text(
        "[Sessions\\My%20Site]\n"
        "HostName=host.test\n"
        "PortNumber=22\n"
        "UserName=alice\n"
        "PublicKeyFile=C%3A%5Ckeys%5Cid_ed25519.ppk\n"
        "RemoteDirectory=%2Fvar%2Fwww%2Fhtml\n"
    )
    sites = parse_ini_file(ini)
    assert len(sites) == 1
    assert sites[0].name == "My Site"
    assert sites[0].key_path == "C:\\keys\\id_ed25519.ppk"
    assert sites[0].initial_dir == "/var/www/html"
