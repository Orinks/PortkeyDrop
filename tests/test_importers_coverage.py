"""Additional tests to hit coverage gaps in importers."""

from __future__ import annotations

import os
import plistlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from portkeydrop.importers import (
    WINSCP_REGISTRY_SENTINEL,
    _load_from_unknown_path,
    _winscp_registry_available,
    detect_default_path,
    load_from_source,
)
from portkeydrop.importers.cyberduck import (
    _map_protocol,
    detect_bookmarks_dir,
    parse_bookmark_file,
    parse_bookmarks_dir,
)
from portkeydrop.importers.filezilla import (
    _decode_password,
    _parse_remote_dir,
    detect_path,
    parse_file,
)
from portkeydrop.importers.winscp import (
    _decode_name,
    _detect_protocol,
    detect_ini_path,
    parse_ini_file,
    parse_registry_sessions,
)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

def test_winscp_registry_available_non_windows():
    with patch.object(sys, "platform", "linux"):
        assert _winscp_registry_available() is False

def test_detect_default_path_filezilla():
    result = detect_default_path("filezilla")
    assert "sitemanager.xml" in str(result)

def test_detect_default_path_cyberduck():
    result = detect_default_path("cyberduck")
    assert "Cyberduck" in str(result) or "cyberduck" in str(result).lower()

def test_detect_default_path_unknown():
    assert detect_default_path("unknown_client") is None

def test_load_from_source_filezilla(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>example.com</Host><Protocol>1</Protocol><Port>22</Port><User>bob</User><Pass encoding="base64">c2VjcmV0</Pass><RemoteDir></RemoteDir><Name>Test</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sitemanager.xml"
    f.write_text(xml)
    sites = load_from_source("filezilla", f)
    assert len(sites) == 1

def test_load_from_source_filezilla_auto_detect(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>auto.com</Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>Auto</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sitemanager.xml"
    f.write_text(xml)
    with patch("portkeydrop.importers.filezilla.detect_path", return_value=f):
        sites = load_from_source("filezilla", None)
    assert len(sites) == 1

def test_load_from_source_winscp_with_path(tmp_path):
    ini = tmp_path / "WinSCP.ini"
    ini.write_text("[Sessions\\MyServer]\nHostName=sftp.example.com\nPortNumber=22\nUserName=alice\n")
    sites = load_from_source("winscp", ini)
    assert len(sites) == 1

def test_load_from_source_winscp_ini_exists(tmp_path):
    ini = tmp_path / "WinSCP.ini"
    ini.write_text("[Sessions\\Server1]\nHostName=host1.com\nPortNumber=22\nUserName=user\n")
    with patch("portkeydrop.importers.winscp.detect_ini_path", return_value=ini):
        sites = load_from_source("winscp", None)
    assert len(sites) >= 1

def test_load_from_source_winscp_registry_fallback(tmp_path):
    ini = tmp_path / "WinSCP.ini"  # doesn't exist
    with patch("portkeydrop.importers.winscp.detect_ini_path", return_value=ini):
        with patch("portkeydrop.importers.winscp.parse_registry_sessions", return_value=[]) as mock_reg:
            load_from_source("winscp", None)
            mock_reg.assert_called_once()

def test_load_from_source_cyberduck_dir(tmp_path):
    duck = tmp_path / "test.duck"
    data = {"Hostname": "sftp.example.com", "Protocol": "sftp", "Port": 22, "Username": "alice", "Path": "/uploads", "Nickname": "Test"}
    duck.write_bytes(plistlib.dumps(data))
    sites = load_from_source("cyberduck", tmp_path)
    assert len(sites) == 1

def test_load_from_source_cyberduck_single_file(tmp_path):
    duck = tmp_path / "test.duck"
    data = {"Hostname": "host.com", "Protocol": "sftp", "Port": 22, "Username": "u", "Path": "/", "Nickname": "X"}
    duck.write_bytes(plistlib.dumps(data))
    sites = load_from_source("cyberduck", duck)
    assert len(sites) == 1

def test_load_from_source_cyberduck_auto_detect(tmp_path):
    duck = tmp_path / "b.duck"
    data = {"Hostname": "cd.com", "Protocol": "sftp", "Port": 22, "Username": "u", "Path": "/", "Nickname": "B"}
    duck.write_bytes(plistlib.dumps(data))
    with patch("portkeydrop.importers.cyberduck.detect_bookmarks_dir", return_value=tmp_path):
        sites = load_from_source("cyberduck", None)
    assert len(sites) >= 1

def test_load_from_source_from_file_no_path():
    with pytest.raises(ValueError, match="Path is required"):
        load_from_source("from_file", None)

def test_load_from_source_unknown_source():
    with pytest.raises(ValueError, match="Unknown import source"):
        load_from_source("bogus", None)

def test_load_from_unknown_path_ini(tmp_path):
    ini = tmp_path / "WinSCP.ini"
    ini.write_text("[Sessions\\S]\nHostName=h.com\nPortNumber=22\nUserName=u\n")
    sites = _load_from_unknown_path(ini)
    assert len(sites) >= 1

def test_load_from_unknown_path_duck(tmp_path):
    duck = tmp_path / "x.duck"
    data = {"Hostname": "h.com", "Protocol": "sftp", "Port": 22, "Username": "u", "Path": "/", "Nickname": "X"}
    duck.write_bytes(plistlib.dumps(data))
    sites = _load_from_unknown_path(duck)
    assert len(sites) == 1

def test_load_from_unknown_path_xml(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>h.com</Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>X</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sites.xml"
    f.write_text(xml)
    sites = _load_from_unknown_path(f)
    assert len(sites) >= 1

def test_load_from_unknown_path_dir_cyberduck(tmp_path):
    duck = tmp_path / "x.duck"
    data = {"Hostname": "h.com", "Protocol": "sftp", "Port": 22, "Username": "u", "Path": "/", "Nickname": "X"}
    duck.write_bytes(plistlib.dumps(data))
    sites = _load_from_unknown_path(tmp_path)
    assert len(sites) == 1

def test_load_from_unknown_path_empty_dir(tmp_path):
    assert _load_from_unknown_path(tmp_path) == []


# ---------------------------------------------------------------------------
# winscp
# ---------------------------------------------------------------------------

def test_detect_ini_path_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    assert str(detect_ini_path()) == "/fake/appdata/WinSCP.ini"

def test_detect_ini_path_no_appdata(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    assert detect_ini_path().name == "WinSCP.ini"

def test_parse_ini_skips_non_session_sections(tmp_path):
    ini = tmp_path / "w.ini"
    ini.write_text("[Configuration]\nKey=Value\n[Sessions\\MyHost]\nHostName=h.com\nPortNumber=22\nUserName=u\n")
    assert len(parse_ini_file(ini)) == 1

def test_parse_ini_skips_missing_hostname(tmp_path):
    ini = tmp_path / "w.ini"
    ini.write_text("[Sessions\\NoHost]\nPortNumber=22\nUserName=u\n")
    assert parse_ini_file(ini) == []

def test_parse_ini_scp_mapped_to_sftp(tmp_path):
    ini = tmp_path / "w.ini"
    ini.write_text("[Sessions\\H]\nHostName=scp.example.com\nPortNumber=22\nUserName=u\nFSProtocol=1\n")
    assert parse_ini_file(ini)[0].protocol == "sftp"

def test_parse_ini_invalid_port(tmp_path):
    ini = tmp_path / "w.ini"
    ini.write_text("[Sessions\\H]\nHostName=h.com\nPortNumber=notanumber\nUserName=u\n")
    assert parse_ini_file(ini)[0].port == 0

def test_parse_registry_sessions_non_windows():
    with patch.object(sys, "platform", "linux"):
        assert parse_registry_sessions() == []

def test_parse_registry_sessions_key_missing():
    winreg_mock = MagicMock()
    winreg_mock.OpenKey.side_effect = OSError
    winreg_mock.HKEY_CURRENT_USER = 0
    with patch.dict("sys.modules", {"winreg": winreg_mock}):
        with patch.object(sys, "platform", "win32"):
            result = parse_registry_sessions()
    assert result == []

def test_detect_protocol_ftps_flag():
    assert _detect_protocol({"Ftps": "1", "FSProtocol": "", "FileProtocol": ""}) == "ftps"

def test_detect_protocol_file_protocol_ftp():
    assert _detect_protocol({"FileProtocol": "ftp", "FSProtocol": "", "Ftps": ""}) == "ftp"

def test_detect_protocol_default_sftp():
    assert _detect_protocol({"FSProtocol": "", "FileProtocol": "", "Ftps": ""}) == "sftp"

def test_detect_protocol_numeric_ftp():
    assert _detect_protocol({"FSProtocol": "5", "FileProtocol": "", "Ftps": ""}) == "ftp"

def test_decode_name_url_encoded():
    assert _decode_name("My%20Server") == "My Server"

def test_decode_name_backslash():
    assert _decode_name("path%5Cto") == "path\\to"


# ---------------------------------------------------------------------------
# cyberduck
# ---------------------------------------------------------------------------

def test_detect_bookmarks_dir_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    assert "Cyberduck" in str(detect_bookmarks_dir())

def test_detect_bookmarks_dir_no_appdata(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    assert "Cyberduck" in str(detect_bookmarks_dir())

def test_parse_bookmark_ssh_protocol(tmp_path):
    duck = tmp_path / "x.duck"
    duck.write_bytes(plistlib.dumps({"Hostname": "h.com", "Protocol": "ssh", "Port": 22, "Username": "u", "Path": "/", "Nickname": "X"}))
    assert parse_bookmark_file(duck).protocol == "sftp"

def test_parse_bookmark_invalid_port(tmp_path):
    duck = tmp_path / "x.duck"
    duck.write_bytes(plistlib.dumps({"Hostname": "h.com", "Protocol": "sftp", "Port": "bad", "Username": "u", "Path": "/", "Nickname": "X"}))
    assert parse_bookmark_file(duck).port == 0

def test_parse_bookmark_no_nickname_user_at_host(tmp_path):
    duck = tmp_path / "x.duck"
    duck.write_bytes(plistlib.dumps({"Hostname": "h.com", "Protocol": "sftp", "Port": 22, "Username": "alice", "Path": "/"}))
    assert parse_bookmark_file(duck).name == "alice@h.com"

def test_parse_bookmark_no_nickname_no_user(tmp_path):
    duck = tmp_path / "x.duck"
    duck.write_bytes(plistlib.dumps({"Hostname": "h.com", "Protocol": "sftp", "Port": 22, "Path": "/"}))
    assert parse_bookmark_file(duck).name == "h.com"

def test_parse_bookmarks_dir_skips_bad_files(tmp_path):
    (tmp_path / "bad.duck").write_text("not a plist")
    assert parse_bookmarks_dir(tmp_path) == []

def test_parse_bookmarks_dir_nonexistent(tmp_path):
    assert parse_bookmarks_dir(tmp_path / "nonexistent") == []

def test_map_protocol_unknown():
    assert _map_protocol("unknown") == "sftp"

def test_map_protocol_ftps():
    assert _map_protocol("ftps") == "ftps"


# ---------------------------------------------------------------------------
# filezilla
# ---------------------------------------------------------------------------

def test_detect_path_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    assert "sitemanager.xml" in str(detect_path())

def test_detect_path_no_appdata(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    assert detect_path().name == "sitemanager.xml"

def test_parse_file_skips_no_host(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host></Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>X</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f) == []

def test_parse_file_ftps_protocol(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>h.com</Host><Protocol>3</Protocol><Port>21</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>X</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f)[0].protocol == "ftps"

def test_parse_file_invalid_port(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>h.com</Host><Protocol>1</Protocol><Port>notanumber</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>X</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f)[0].port == 0

def test_decode_password_base64_invalid():
    elem = ET.fromstring('<Pass encoding="base64">!!!notbase64!!!</Pass>')
    server = ET.Element("Server")
    server.append(elem)
    assert _decode_password(server) == ""

def test_decode_password_plaintext():
    elem = ET.fromstring("<Pass>mypassword</Pass>")
    server = ET.Element("Server")
    server.append(elem)
    assert _decode_password(server) == "mypassword"

def test_decode_password_empty():
    assert _decode_password(ET.Element("Server")) == ""

def test_parse_remote_dir_absolute():
    assert _parse_remote_dir("/home/user") == "/home/user"

def test_parse_remote_dir_relative():
    assert _parse_remote_dir("uploads") == "/uploads"

def test_parse_remote_dir_empty():
    assert _parse_remote_dir("") == "/"

def test_parse_remote_dir_filezilla_format():
    assert _parse_remote_dir("1 0 4 home 4 user") == "/home/user"
