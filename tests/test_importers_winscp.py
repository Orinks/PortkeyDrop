from pathlib import Path
from unittest.mock import patch

from portkeydrop.importers import (
    WINSCP_REGISTRY_SENTINEL,
    detect_default_path,
    load_from_source,
)
from portkeydrop.importers.winscp import parse_ini_file


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
    assert first.initial_dir == "/home/alice"
    assert first.key_path == "C:\\keys\\id_ed25519.ppk"

    second = sites[1]
    assert second.name == "FTP Server"
    assert second.protocol == "ftp"
    assert second.host == "ftp.example.com"
    assert second.port == 21


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
