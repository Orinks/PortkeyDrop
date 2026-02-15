"""Tests for site manager."""

from __future__ import annotations


import pytest

from accessitransfer.protocols import Protocol
from accessitransfer.sites import Site, SiteManager


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
