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


def test_parse_winscp_ini_fixture():
    fixture = Path("tests/fixtures/importers/winscp_sessions.ini")
    sites = parse_ini_file(fixture)

    assert len(sites) == 2

    first = sites[0]
    assert first.name == "Prod Server"
    assert first.protocol == "sftp"
    assert first.host == "sftp.example.com"
    assert first.port == 22
    assert first.username == "alice"
    assert first.password == "s3cr3t"
    assert first.initial_dir == "/home/alice"
    assert first.key_path == "C:\\keys\\id_ed25519.ppk"

    second = sites[1]
    assert second.name == "FTP Server"
    assert second.protocol == "ftp"
    assert second.host == "ftp.example.com"
    assert second.port == 21
    assert second.password == "hunter2"


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
    """Decrypt a known WinSCP-encrypted password."""
    encrypted = (
        "00000A030B080601060C0609060306050703060607040700"
        "020E060507080601060D0700060C0605020E0603060F060D"
        "070303030603070203030704"
    )
    assert _decrypt_winscp_password("alice", "sftp.example.com", encrypted) == "s3cr3t"


def test_decrypt_winscp_password_different_credentials():
    encrypted = (
        "00000A030B0A0602060F0602060607040700020E06050708"
        "0601060D0700060C0605020E0603060F060D0608070506"
        "0E0704060507020302"
    )
    assert _decrypt_winscp_password("bob", "ftp.example.com", encrypted) == "hunter2"


def test_safe_decrypt_empty_password():
    """Empty encrypted string returns empty password."""
    assert _safe_decrypt("", "alice", "host.com") == ""


def test_safe_decrypt_invalid_hex():
    """Malformed encrypted string returns empty password instead of crashing."""
    assert _safe_decrypt("ZZZZ", "alice", "host.com") == ""


def test_safe_decrypt_truncated():
    """Truncated encrypted data returns empty password instead of crashing."""
    assert _safe_decrypt("0000", "alice", "host.com") == ""


def test_parse_ini_missing_password_field(tmp_path):
    """Sessions without a Password field get empty password."""
    ini = tmp_path / "w.ini"
    ini.write_text("[Sessions\\H]\nHostName=h.com\nPortNumber=22\nUserName=u\n")
    assert parse_ini_file(ini)[0].password == ""
