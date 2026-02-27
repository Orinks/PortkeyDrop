from pathlib import Path

from portkeydrop.importers.cyberduck import parse_bookmark_file


def test_parse_cyberduck_bookmark_fixture():
    fixture = Path("tests/fixtures/importers/cyberduck_bookmark.duck")
    site = parse_bookmark_file(fixture)

    assert site.name == "My SFTP"
    assert site.protocol == "sftp"
    assert site.host == "sftp.example.com"
    assert site.port == 22
    assert site.username == "alice"
    assert site.initial_dir == "/uploads"
