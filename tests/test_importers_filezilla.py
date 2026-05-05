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
    assert first.key_path == "/home/alice/.ssh/id_ed25519"
    assert first.initial_dir == "/home/alice"
    assert first.notes == "Main production host"

    second = sites[1]
    assert second.protocol == "ftp"
    assert second.password == "plaintext"
    assert second.key_path == ""
    assert second.initial_dir == "/incoming"


def test_detect_path_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    from portkeydrop.importers.filezilla import detect_path

    assert "sitemanager.xml" in str(detect_path())


def test_detect_path_no_appdata(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    from portkeydrop.importers.filezilla import detect_path

    assert detect_path().name == "sitemanager.xml"


def test_parse_file_skips_no_host(tmp_path):
    from portkeydrop.importers.filezilla import parse_file

    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host></Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>X</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f) == []


def test_parse_file_ftps_protocol(tmp_path):
    from portkeydrop.importers.filezilla import parse_file

    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>h.com</Host><Protocol>3</Protocol><Port>21</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>X</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    site = parse_file(f)[0]
    assert site.protocol == "ftp"
    assert site.ftp_explicit_ssl is True


def test_parse_file_invalid_port(tmp_path):
    from portkeydrop.importers.filezilla import parse_file

    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>h.com</Host><Protocol>1</Protocol><Port>notanumber</Port><User>u</User><Pass></Pass><RemoteDir></RemoteDir><Name>X</Name><Comments></Comments></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f)[0].port == 0


def test_parse_file_keyfile_casing_variant(tmp_path):
    from portkeydrop.importers.filezilla import parse_file

    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>sftp.example.com</Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><KeyFile>/tmp/id_rsa</KeyFile><RemoteDir>/</RemoteDir><Name>X</Name></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f)[0].key_path == "/tmp/id_rsa"


def test_parse_file_keyfile_file_url_windows_drive(tmp_path):
    from portkeydrop.importers.filezilla import parse_file

    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>sftp.example.com</Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><Keyfile>file:///C:/Users/Alice/.ssh/id_ed25519%20prod.ppk</Keyfile><RemoteDir>/</RemoteDir><Name>X</Name></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f)[0].key_path == "C:\\Users\\Alice\\.ssh\\id_ed25519 prod.ppk"


def test_parse_file_keyfile_file_url_unc(tmp_path):
    from portkeydrop.importers.filezilla import parse_file

    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>sftp.example.com</Host><Protocol>1</Protocol><Port>22</Port><User>u</User><Pass></Pass><Keyfile>file://fileserver/keys/id_ed25519.ppk</Keyfile><RemoteDir>/</RemoteDir><Name>X</Name></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f)[0].key_path == "\\\\fileserver\\keys\\id_ed25519.ppk"


def test_parse_file_keyfile_not_mapped_for_non_sftp(tmp_path):
    from portkeydrop.importers.filezilla import parse_file

    xml = '<?xml version="1.0"?><FileZilla3><Servers><Server><Host>ftp.example.com</Host><Protocol>0</Protocol><Port>21</Port><User>u</User><Pass></Pass><Keyfile>/should/not/import</Keyfile><RemoteDir>/incoming</RemoteDir><Name>X</Name></Server></Servers></FileZilla3>'
    f = tmp_path / "sm.xml"
    f.write_text(xml)
    assert parse_file(f)[0].key_path == ""


def test_decode_password_base64_invalid():
    import xml.etree.ElementTree as ET
    from portkeydrop.importers.filezilla import _decode_password

    elem = ET.fromstring('<Pass encoding="base64">!!!notbase64!!!</Pass>')
    server = ET.Element("Server")
    server.append(elem)
    assert _decode_password(server) == ""


def test_decode_password_plaintext():
    import xml.etree.ElementTree as ET
    from portkeydrop.importers.filezilla import _decode_password

    elem = ET.fromstring("<Pass>mypassword</Pass>")
    server = ET.Element("Server")
    server.append(elem)
    assert _decode_password(server) == "mypassword"


def test_decode_password_empty():
    import xml.etree.ElementTree as ET
    from portkeydrop.importers.filezilla import _decode_password

    assert _decode_password(ET.Element("Server")) == ""


def test_parse_remote_dir_absolute():
    from portkeydrop.importers.filezilla import _parse_remote_dir

    assert _parse_remote_dir("/home/user") == "/home/user"


def test_parse_remote_dir_relative():
    from portkeydrop.importers.filezilla import _parse_remote_dir

    assert _parse_remote_dir("uploads") == "/uploads"


def test_parse_remote_dir_empty():
    from portkeydrop.importers.filezilla import _parse_remote_dir

    assert _parse_remote_dir("") == "/"


def test_parse_remote_dir_filezilla_format():
    from portkeydrop.importers.filezilla import _parse_remote_dir

    assert _parse_remote_dir("1 0 4 home 4 user") == "/home/user"
