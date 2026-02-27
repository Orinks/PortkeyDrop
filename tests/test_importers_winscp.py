from pathlib import Path

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
