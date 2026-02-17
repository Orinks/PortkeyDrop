"""Tests for site manager."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from portkeydrop.protocols import Protocol
from portkeydrop.sites import Site, SiteManager, _VaultStore


# In-memory keyring for tests
_fake_store: dict[str, str] = {}


def _fake_set(service: str, key: str, value: str) -> None:
    _fake_store[f"{service}/{key}"] = value


def _fake_get(service: str, key: str) -> str | None:
    return _fake_store.get(f"{service}/{key}")


def _fake_delete(service: str, key: str) -> None:
    _fake_store.pop(f"{service}/{key}", None)


@pytest.fixture()
def mock_keyring(monkeypatch):
    """Provide an in-memory keyring backend."""
    _fake_store.clear()
    import portkeydrop.sites as sites_mod

    monkeypatch.setattr(sites_mod, "_has_keyring", True)
    monkeypatch.setattr(sites_mod, "_has_fernet", True)
    with (
        patch("portkeydrop.sites._keyring_mod.set_password", _fake_set),
        patch("portkeydrop.sites._keyring_mod.get_password", _fake_get),
        patch("portkeydrop.sites._keyring_mod.delete_password", _fake_delete),
    ):
        yield


@pytest.fixture()
def vault_only(monkeypatch):
    """Disable keyring, use encrypted vault only."""
    import portkeydrop.sites as sites_mod

    monkeypatch.setattr(sites_mod, "_has_keyring", False)
    monkeypatch.setattr(sites_mod, "_has_fernet", True)


@pytest.fixture()
def no_storage(monkeypatch):
    """Disable both keyring and vault."""
    import portkeydrop.sites as sites_mod

    monkeypatch.setattr(sites_mod, "_has_keyring", False)
    monkeypatch.setattr(sites_mod, "_has_fernet", False)


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
    """Core site manager tests (keyring backend)."""

    @pytest.fixture(autouse=True)
    def _use_keyring(self, mock_keyring):
        pass

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


class TestKeyringBackend:
    """Tests specific to keyring password storage."""

    @pytest.fixture(autouse=True)
    def _use_keyring(self, mock_keyring):
        pass

    def test_password_stored_in_keyring_not_json(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Secure", host="example.com", password="s3cret")
        mgr.add(site)

        assert _fake_store.get(f"portkeydrop/{site.id}") == "s3cret"

        import json

        data = json.loads((tmp_path / "sites.json").read_text())
        assert "password" not in data[0]

    def test_password_retrieved_from_keyring_on_load(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="Secure", host="example.com", password="s3cret")
        mgr.add(site)

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
        import json

        site_id = "legacy-site-id"
        data = [{"id": site_id, "name": "Old", "host": "old.com", "password": "oldpass",
                 "protocol": "sftp", "port": 22, "username": "user", "key_path": "",
                 "initial_dir": "/", "notes": ""}]
        (tmp_path / "sites.json").write_text(json.dumps(data))

        mgr = SiteManager(tmp_path)
        assert mgr.sites[0].password == "oldpass"
        assert _fake_store.get(f"portkeydrop/{site_id}") == "oldpass"


class TestVaultBackend:
    """Tests for encrypted vault fallback (no keyring)."""

    @pytest.fixture(autouse=True)
    def _use_vault(self, vault_only):
        pass

    def test_vault_stores_and_retrieves(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="VaultTest", host="example.com", password="vault_secret")
        mgr.add(site)

        import json

        data = json.loads((tmp_path / "sites.json").read_text())
        assert "password" not in data[0]

        assert (tmp_path / "vault.enc").exists()

        mgr2 = SiteManager(tmp_path)
        assert mgr2.sites[0].password == "vault_secret"

    def test_vault_deletes_on_remove(self, tmp_path):
        mgr = SiteManager(tmp_path)
        site = Site(name="VaultDel", host="example.com", password="delsecret")
        mgr.add(site)

        mgr.remove(site.id)

        vault = _VaultStore(tmp_path / "vault.enc")
        assert vault.get(site.id) == ""

    def test_vault_multiple_passwords(self, tmp_path):
        mgr = SiteManager(tmp_path)
        s1 = Site(name="S1", host="s1.com", password="pw1")
        s2 = Site(name="S2", host="s2.com", password="pw2")
        mgr.add(s1)
        mgr.add(s2)

        mgr2 = SiteManager(tmp_path)
        assert mgr2.sites[0].password == "pw1"
        assert mgr2.sites[1].password == "pw2"

    def test_plaintext_migrated_to_vault(self, tmp_path):
        import json

        site_id = "legacy-vault"
        data = [{"id": site_id, "name": "Old", "host": "old.com", "password": "oldpw",
                 "protocol": "sftp", "port": 22, "username": "user", "key_path": "",
                 "initial_dir": "/", "notes": ""}]
        (tmp_path / "sites.json").write_text(json.dumps(data))

        mgr = SiteManager(tmp_path)
        assert mgr.sites[0].password == "oldpw"

        vault = _VaultStore(tmp_path / "vault.enc")
        assert vault.get(site_id) == "oldpw"


class TestNoStorage:
    """Tests when neither keyring nor cryptography is available."""

    @pytest.fixture(autouse=True)
    def _use_none(self, no_storage):
        pass

    def test_password_not_saved_to_json(self, tmp_path):
        """Passwords must never be written to disk without encryption."""
        mgr = SiteManager(tmp_path)
        site = Site(name="Unsaved", host="example.com", password="ephemeral")
        mgr.add(site)

        import json

        data = json.loads((tmp_path / "sites.json").read_text())
        assert "password" not in data[0]

    def test_password_lost_on_reload(self, tmp_path):
        """Without secure storage, passwords don't survive a reload."""
        mgr = SiteManager(tmp_path)
        site = Site(name="Ephemeral", host="example.com", password="gone")
        mgr.add(site)

        mgr2 = SiteManager(tmp_path)
        assert mgr2.sites[0].password == ""
