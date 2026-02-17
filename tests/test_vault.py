"""Tests for the encrypted vault password storage."""

from __future__ import annotations

from portkeydrop.sites import _VaultStore


class TestVaultStore:
    """Test the Fernet-encrypted vault directly."""

    def test_store_and_retrieve(self, tmp_path):
        vault = _VaultStore(tmp_path / "vault.enc")
        vault.set("site1", "mypassword")
        assert vault.get("site1") == "mypassword"

    def test_retrieve_missing_key(self, tmp_path):
        vault = _VaultStore(tmp_path / "vault.enc")
        assert vault.get("nonexistent") == ""

    def test_delete_key(self, tmp_path):
        vault = _VaultStore(tmp_path / "vault.enc")
        vault.set("site1", "pw")
        vault.delete("site1")
        assert vault.get("site1") == ""

    def test_delete_nonexistent_key(self, tmp_path):
        vault = _VaultStore(tmp_path / "vault.enc")
        vault.delete("nope")  # should not raise

    def test_persistence_across_instances(self, tmp_path):
        vault_path = tmp_path / "vault.enc"
        v1 = _VaultStore(vault_path)
        v1.set("key1", "val1")
        v1.set("key2", "val2")

        v2 = _VaultStore(vault_path)
        assert v2.get("key1") == "val1"
        assert v2.get("key2") == "val2"

    def test_multiple_keys(self, tmp_path):
        vault = _VaultStore(tmp_path / "vault.enc")
        for i in range(10):
            vault.set(f"site-{i}", f"password-{i}")

        for i in range(10):
            assert vault.get(f"site-{i}") == f"password-{i}"

    def test_overwrite_value(self, tmp_path):
        vault = _VaultStore(tmp_path / "vault.enc")
        vault.set("site1", "old")
        vault.set("site1", "new")
        assert vault.get("site1") == "new"

    def test_empty_vault_file(self, tmp_path):
        vault_path = tmp_path / "vault.enc"
        # File doesn't exist yet
        vault = _VaultStore(vault_path)
        assert vault.get("anything") == ""
        assert not vault_path.exists()

    def test_corrupt_vault_file(self, tmp_path):
        vault_path = tmp_path / "vault.enc"
        vault_path.write_bytes(b"garbage data that is not fernet")

        # Should handle gracefully, start with empty data
        vault = _VaultStore(vault_path)
        assert vault.get("anything") == ""

    def test_vault_file_created_on_first_write(self, tmp_path):
        vault_path = tmp_path / "vault.enc"
        assert not vault_path.exists()

        vault = _VaultStore(vault_path)
        vault.set("key", "value")
        assert vault_path.exists()

    def test_vault_in_nested_directory(self, tmp_path):
        vault_path = tmp_path / "deep" / "nested" / "vault.enc"
        vault = _VaultStore(vault_path)
        vault.set("key", "value")
        assert vault_path.exists()
        assert vault.get("key") == "value"

    def test_empty_password_not_stored(self, tmp_path):
        """Empty strings shouldn't pollute the vault."""
        vault = _VaultStore(tmp_path / "vault.enc")
        vault.set("site1", "real")
        vault.set("site2", "")
        assert vault.get("site1") == "real"
        assert vault.get("site2") == ""
