from __future__ import annotations

import zipfile

from scripts.verify_portable_zip import verify_portable_zip


def test_verify_portable_zip_accepts_nested_portable_data_dir(tmp_path) -> None:
    zip_path = tmp_path / "PortkeyDrop_Portable_v0.3.0.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("PortkeyDrop_portable/PortkeyDrop.exe", b"fake")
        archive.writestr("PortkeyDrop_portable/data/", b"")

    ok, errors = verify_portable_zip(zip_path)

    assert ok is True
    assert errors == []
