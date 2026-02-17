"""Tests for site manager."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from portkeydrop.protocols import Protocol
from portkeydrop.sites import Site, SiteManager


# In-memory keyring for tests
_fake_store: dict[str, str] = {}


def _fake_set(service: str, key: str, value: str) -> None:
    _fake_store[f"{service}/{key}"] = value


def _fake_get(service: str, key: str) -> str | None:
    return _fake_store.get(f"{service}/{key}")


def _fake_delete(service: str, key: str) -> None:
    _fake_store.pop(f"{service}/{key}", None)


@pytest.fixture(autouse=True)
def _mock_keyring(monkeypatch):
    """Provide an in-memory keyring for all site tests."""
    _fake_store.clear()
    import portkeydrop.sites as sites_mod

    monkeypatch.setattr(sites_mod, "_has_keyring", True)
    with (
        patch("portkeydrop.sites.keyring.set_password", _fake_set),
        patch("portkeydrop.sites.keyring.get_password", _fake_get),
        patch("portkeydrop.sites.keyring.delete_password", _fake_delete),
    ):
        yield


class TestSite:
    def test_defaults(self):
        site = Site()
        assert site.protocol == "sftp"
        assert site.port == 0
        assert site.id  # should have a uuid

    def test_to_connection_info(self):
        site = Site(
            name="My Server",
            protocol="sftp",
            host="example.com",
            port=2222,
            username="user",
            password="pass",
        )
        info = site.to_connection_info()
        assert info.protocol == Protocol.SFTP
        assert info.host == "example.com"
        assert info.port == 2222
        assert info.username == "user"
        assert info.password == "pass"

    def test_to_connection_info_ftp(self):
        site = Site(protocol="ftp", host="ftp.example.com")
        info = site.to_connection_info()
        assert info.protocol == Protocol.FTP

    def test_unique_ids(self):
        s1 = Site()
        s2 = Site()
        assert s1.id != s2.id


class TestSiteManager:
    def test_empty_initially(self, tmp_path):
        mgr = SiteManager(tmp_path)
        assert mgr.sites == []

    def test_add_site(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Test", host="example.com")
        mgr.add(site)
        assert len(mgr.sites) == 1
        assert mgr.sites[0].name == "Test"

    def test_add_persists(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Test", host="example.com")
        mgr.add(site)

        mgr2 = SiteManager(tmp_path)
        assert len(mgr2.sites) == 1
        assert mgr2.sites[0].name == "Test"

    def test_remove_site(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Test", host="example.com")
        mgr.add(site)
        mgr.remove(site.id)
        assert len(mgr.sites) == 0

    def test_update_site(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Test", host="example.com")
        mgr.add(site)

        site.name = "Updated"
        site.host = "new.example.com"
        mgr.update(site)

        assert mgr.sites[0].name == "Updated"
        assert mgr.sites[0].host == "new.example.com"

    def test_update_missing_raises(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Ghost")
        with pytest.raises(ValueError, match="not found"):
            mgr.update(site)

    def test_get_by_id(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Test", host="example.com")
        mgr.add(site)
        found = mgr.get(site.id)
        assert found is not None
        assert found.name == "Test"

    def test_get_missing_returns_none(self, tmp_path):
        mgr = SiteManager(tmp_path)
        assert mgr.get("nonexistent") is None

    def test_find_by_name(self, tmp_path):
        mgr = SiteManager(tmp_path)
        mgr.add(Site(name="Production", host="prod.example.com"))
        mgr.add(Site(name="Staging", host="staging.example.com"))

        found = mgr.find_by_name("staging")
        assert found is not None
        assert found.host == "staging.example.com"

    def test_find_by_name_missing(self, tmp_path):
        mgr = SiteManager(tmp_path)
        assert mgr.find_by_name("nonexistent") is None

    def test_multiple_sites(self, tmp_path):
        mgr = SiteManager(tmp_path)
        mgr.add(Site(name="Server 1", host="s1.example.com"))
        mgr.add(Site(name="Server 2", host="s2.example.com"))
        mgr.add(Site(name="Server 3", host="s3.example.com"))
        assert len(mgr.sites) == 3

    def test_load_corrupt_file(self, tmp_path):
        (tmp_path / "sites.json").write_text("not json", encoding="utf-8")
        mgr = SiteManager(tmp_path)
        assert mgr.sites == []

    def test_sites_returns_copy(self, tmp_path):
        mgr = SiteManager(tmp_path)
        mgr.add(Site(name="Test"))
        sites = mgr.sites
        sites.clear()
        assert len(mgr.sites) == 1  # original unchanged

    def test_password_stored_in_keyring_not_json(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Secure", host="example.com", password="s3cret")
        mgr.add(site)

        # Password should be in fake keyring
        assert _fake_store.get(f"portkeydrop/{site.id}") == "s3cret"

        # Password should NOT be in the JSON file
        import json

        data = json.loads((tmp_path / "sites.json").read_text())
        assert "password" not in data[0]

    def test_password_retrieved_from_keyring_on_load(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Secure", host="example.com", password="s3cret")
        mgr.add(site)

        # Reload from disk
        mgr2 = SiteManager(tmp_path)
        assert mgr2.sites[0].password == "s3cret"

    def test_password_deleted_on_site_remove(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Secure", host="example.com", password="s3cret")
        mgr.add(site)
        key = f"portkeydrop/{site.id}"
        assert key in _fake_store

        mgr.remove(site.id)
        assert key not in _fake_store

    def test_plaintext_password_migrated_to_keyring(self, tmp_path):
        """If sites.json has a plaintext password (pre-keyring), migrate it."""
        import json

        site_id = "legacy-site-id"
        data = [{"id": site_id, "name": "Old", "host": "old.com", "password": "oldpass",
                 "protocol": "sftp", "port": 22, "username": "user", "key_path": "",
                 "initial_dir": "/", "notes": ""}]
        (tmp_path / "sites.json").write_text(json.dumps(data))

        mgr = SiteManager(tmp_path)
        assert mgr.sites[0].password == "oldpass"
        assert _fake_store.get(f"portkeydrop/{site_id}") == "oldpass"
