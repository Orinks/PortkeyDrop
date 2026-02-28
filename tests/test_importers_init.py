"""Tests for portkeydrop.importers __init__ — source dispatch and path detection."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from portkeydrop.importers import (
    _load_from_unknown_path,
    _winscp_registry_available,
    detect_default_path,
    load_from_source,
)


def test_winscp_registry_available_non_windows():
    with patch.object(sys, "platform", "linux"):
        assert _winscp_registry_available() is False


def test_detect_default_path_filezilla():
    assert "sitemanager.xml" in str(detect_default_path("filezilla"))


def test_detect_default_path_cyberduck():
    result = str(detect_default_path("cyberduck"))
    assert "Cyberduck" in result or "cyberduck" in result.lower()


def test_detect_default_path_winscp_no_registry():
    with patch("portkeydrop.importers._winscp_registry_available", return_value=False):
        result = detect_default_path("winscp")
    assert isinstance(result, Path)
    assert result.name == "WinSCP.ini"


def test_detect_default_path_unknown_returns_none():
    assert detect_default_path("unknown_client") is None


def test_load_from_source_filezilla(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>example.com</Host><Protocol>1</Protocol><Port>22</Port><User>bob</User><Pass encoding="base64">c2VjcmV0</Pass><RemoteDir></RemoteDir><Name>Test</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sitemanager.xml"
    f.write_text(xml)
    sites = load_from_source("filezilla", f)
    assert len(sites) == 1
    assert sites[0].host == "example.com"


def test_load_from_source_filezilla_auto_detect(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>auto.com</Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>Auto</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sitemanager.xml"
    f.write_text(xml)
    with patch("portkeydrop.importers.filezilla.detect_path", return_value=f):
        sites = load_from_source("filezilla", None)
    assert len(sites) == 1


def test_load_from_source_winscp_with_explicit_path(tmp_path):
    ini = tmp_path / "WinSCP.ini"
    ini.write_text(
        "[Sessions\\MyServer]\nHostName=sftp.example.com\nPortNumber=22\nUserName=alice\n"
    )
    sites = load_from_source("winscp", ini)
    assert len(sites) == 1
    assert sites[0].host == "sftp.example.com"


def test_load_from_source_winscp_auto_detect_ini(tmp_path):
    ini = tmp_path / "WinSCP.ini"
    ini.write_text("[Sessions\\Server1]\nHostName=host1.com\nPortNumber=22\nUserName=user\n")
    with patch("portkeydrop.importers.winscp.detect_ini_path", return_value=ini):
        sites = load_from_source("winscp", None)
    assert any(s.host == "host1.com" for s in sites)


def test_load_from_source_winscp_falls_back_to_registry(tmp_path):
    ini = tmp_path / "WinSCP.ini"  # does not exist
    with patch("portkeydrop.importers.winscp.detect_ini_path", return_value=ini):
        with patch(
            "portkeydrop.importers.winscp.parse_registry_sessions", return_value=[]
        ) as mock_reg:
            load_from_source("winscp", None)
            mock_reg.assert_called_once()


def test_load_from_source_cyberduck_directory(tmp_path):
    duck = tmp_path / "test.duck"
    duck.write_bytes(
        plistlib.dumps(
            {
                "Hostname": "sftp.example.com",
                "Protocol": "sftp",
                "Port": 22,
                "Username": "alice",
                "Path": "/uploads",
                "Nickname": "Test",
            }
        )
    )
    sites = load_from_source("cyberduck", tmp_path)
    assert len(sites) == 1


def test_load_from_source_cyberduck_single_file(tmp_path):
    duck = tmp_path / "test.duck"
    duck.write_bytes(
        plistlib.dumps(
            {
                "Hostname": "host.com",
                "Protocol": "sftp",
                "Port": 22,
                "Username": "u",
                "Path": "/",
                "Nickname": "X",
            }
        )
    )
    sites = load_from_source("cyberduck", duck)
    assert len(sites) == 1


def test_load_from_source_cyberduck_auto_detect(tmp_path):
    duck = tmp_path / "b.duck"
    duck.write_bytes(
        plistlib.dumps(
            {
                "Hostname": "cd.com",
                "Protocol": "sftp",
                "Port": 22,
                "Username": "u",
                "Path": "/",
                "Nickname": "B",
            }
        )
    )
    with patch("portkeydrop.importers.cyberduck.detect_bookmarks_dir", return_value=tmp_path):
        sites = load_from_source("cyberduck", None)
    assert len(sites) >= 1


def test_load_from_source_from_file_requires_path():
    with pytest.raises(ValueError, match="Path is required"):
        load_from_source("from_file", None)


def test_load_from_source_unknown_source_raises():
    with pytest.raises(ValueError, match="Unknown import source"):
        load_from_source("bogus", None)


def test_load_from_unknown_path_winscp_ini(tmp_path):
    ini = tmp_path / "WinSCP.ini"
    ini.write_text("[Sessions\\S]\nHostName=h.com\nPortNumber=22\nUserName=u\n")
    sites = _load_from_unknown_path(ini)
    assert len(sites) >= 1


def test_load_from_unknown_path_duck_file(tmp_path):
    duck = tmp_path / "x.duck"
    duck.write_bytes(
        plistlib.dumps(
            {
                "Hostname": "h.com",
                "Protocol": "sftp",
                "Port": 22,
                "Username": "u",
                "Path": "/",
                "Nickname": "X",
            }
        )
    )
    assert len(_load_from_unknown_path(duck)) == 1


def test_load_from_unknown_path_xml_file(tmp_path):
    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>h.com</Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>X</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sites.xml"
    f.write_text(xml)
    assert len(_load_from_unknown_path(f)) >= 1


def test_load_from_unknown_path_directory_with_ducks(tmp_path):
    duck = tmp_path / "x.duck"
    duck.write_bytes(
        plistlib.dumps(
            {
                "Hostname": "h.com",
                "Protocol": "sftp",
                "Port": 22,
                "Username": "u",
                "Path": "/",
                "Nickname": "X",
            }
        )
    )
    assert len(_load_from_unknown_path(tmp_path)) == 1


def test_load_from_unknown_path_empty_directory(tmp_path):
    assert _load_from_unknown_path(tmp_path) == []
