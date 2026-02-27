from pathlib import Path

from portkeydrop.importers.filezilla import parse_file


def test_parse_filezilla_sites_fixture():
    fixture = Path("tests/fixtures/importers/filezilla_sitemanager.xml")
    sites = parse_file(fixture)

    assert len(sites) == 2

    first = sites[0]
    assert first.name == "Prod SFTP"
    assert first.protocol == "sftp"
    assert first.host == "sftp.example.com"
    assert first.port == 2222
    assert first.username == "alice"
    assert first.password == "secret"
    assert first.initial_dir == "/home/alice"
    assert first.notes == "Main production host"

    second = sites[1]
    assert second.protocol == "ftp"
    assert second.password == "plaintext"
    assert second.initial_dir == "/incoming"
