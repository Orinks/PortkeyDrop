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


def test_detect_bookmarks_dir_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    from portkeydrop.importers.cyberduck import detect_bookmarks_dir

    assert "Cyberduck" in str(detect_bookmarks_dir())


def test_detect_bookmarks_dir_no_appdata(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    from portkeydrop.importers.cyberduck import detect_bookmarks_dir

    assert "Cyberduck" in str(detect_bookmarks_dir())


def test_parse_bookmark_ssh_protocol(tmp_path):
    import plistlib
    from portkeydrop.importers.cyberduck import parse_bookmark_file

    duck = tmp_path / "x.duck"
    duck.write_bytes(
        plistlib.dumps(
            {
                "Hostname": "h.com",
                "Protocol": "ssh",
                "Port": 22,
                "Username": "u",
                "Path": "/",
                "Nickname": "X",
            }
        )
    )
    assert parse_bookmark_file(duck).protocol == "sftp"


def test_parse_bookmark_invalid_port(tmp_path):
    import plistlib
    from portkeydrop.importers.cyberduck import parse_bookmark_file

    duck = tmp_path / "x.duck"
    duck.write_bytes(
        plistlib.dumps(
            {
                "Hostname": "h.com",
                "Protocol": "sftp",
                "Port": "bad",
                "Username": "u",
                "Path": "/",
                "Nickname": "X",
            }
        )
    )
    assert parse_bookmark_file(duck).port == 0


def test_parse_bookmark_no_nickname_user_at_host(tmp_path):
    import plistlib
    from portkeydrop.importers.cyberduck import parse_bookmark_file

    duck = tmp_path / "x.duck"
    duck.write_bytes(
        plistlib.dumps(
            {"Hostname": "h.com", "Protocol": "sftp", "Port": 22, "Username": "alice", "Path": "/"}
        )
    )
    assert parse_bookmark_file(duck).name == "alice@h.com"


def test_parse_bookmark_no_nickname_no_user(tmp_path):
    import plistlib
    from portkeydrop.importers.cyberduck import parse_bookmark_file

    duck = tmp_path / "x.duck"
    duck.write_bytes(
        plistlib.dumps({"Hostname": "h.com", "Protocol": "sftp", "Port": 22, "Path": "/"})
    )
    assert parse_bookmark_file(duck).name == "h.com"


def test_parse_bookmarks_dir_skips_bad_files(tmp_path):
    from portkeydrop.importers.cyberduck import parse_bookmarks_dir

    (tmp_path / "bad.duck").write_text("not a plist")
    assert parse_bookmarks_dir(tmp_path) == []


def test_parse_bookmarks_dir_nonexistent(tmp_path):
    from portkeydrop.importers.cyberduck import parse_bookmarks_dir

    assert parse_bookmarks_dir(tmp_path / "nonexistent") == []


def test_map_protocol_unknown():
    from portkeydrop.importers.cyberduck import _map_protocol

    assert _map_protocol("unknown") == "sftp"


def test_map_protocol_ftps():
    from portkeydrop.importers.cyberduck import _map_protocol

    assert _map_protocol("ftps") == "ftps"
