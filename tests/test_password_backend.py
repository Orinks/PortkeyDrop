"""Tests for password backend tier selection."""

from __future__ import annotations

import portkeydrop.sites as sites_mod
from portkeydrop.sites import _PasswordBackend


class TestPasswordBackendTiers:
    """Verify the correct storage tier is selected."""

    def test_keyring_tier_selected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sites_mod, "_has_keyring", True)
        monkeypatch.setattr(sites_mod, "_has_fernet", True)
        backend = _PasswordBackend(tmp_path)
        assert backend._tier == "keyring"
        assert backend.can_store is True

    def test_vault_tier_when_no_keyring(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sites_mod, "_has_keyring", False)
        monkeypatch.setattr(sites_mod, "_has_fernet", True)
        backend = _PasswordBackend(tmp_path)
        assert backend._tier == "vault"
        assert backend.can_store is True

    def test_no_storage_tier(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sites_mod, "_has_keyring", False)
        monkeypatch.setattr(sites_mod, "_has_fernet", False)
        backend = _PasswordBackend(tmp_path)
        assert backend._tier == "none"
        assert backend.can_store is False

    def test_no_storage_store_is_noop(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sites_mod, "_has_keyring", False)
        monkeypatch.setattr(sites_mod, "_has_fernet", False)
        backend = _PasswordBackend(tmp_path)
        backend.store("site1", "pw")  # should not raise
        assert backend.retrieve("site1") == ""

    def test_no_storage_delete_is_noop(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sites_mod, "_has_keyring", False)
        monkeypatch.setattr(sites_mod, "_has_fernet", False)
        backend = _PasswordBackend(tmp_path)
        backend.delete("site1")  # should not raise

    def test_vault_tier_round_trip(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sites_mod, "_has_keyring", False)
        monkeypatch.setattr(sites_mod, "_has_fernet", True)
        backend = _PasswordBackend(tmp_path)
        backend.store("mysite", "s3cret")
        assert backend.retrieve("mysite") == "s3cret"
        backend.delete("mysite")
        assert backend.retrieve("mysite") == ""
