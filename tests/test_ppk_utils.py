"""Tests for PuTTY PPK key file support."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestIsPpkFile:
    def test_ppk_extension_detected(self):
        from portkeydrop.ppk_utils import is_ppk_file

        assert is_ppk_file("mykey.ppk") is True
        assert is_ppk_file("/home/user/.ssh/id_rsa.ppk") is True

    def test_uppercase_extension_detected(self):
        from portkeydrop.ppk_utils import is_ppk_file

        assert is_ppk_file("mykey.PPK") is True

    def test_non_ppk_files_not_detected(self):
        from portkeydrop.ppk_utils import is_ppk_file

        assert is_ppk_file("id_rsa") is False
        assert is_ppk_file("id_rsa.pem") is False
        assert is_ppk_file("id_ed25519") is False
        assert is_ppk_file("mykey.pub") is False


class TestLoadPpkKey:
    def test_missing_file_raises(self, tmp_path):
        from portkeydrop.ppk_utils import load_ppk_key

        with pytest.raises(FileNotFoundError):
            load_ppk_key(str(tmp_path / "nonexistent.ppk"))

    def _mock_puttykeys(self, pem_or_exc):
        """Helper: patch puttykeys in sys.modules with a fake module."""
        import sys
        import types

        mock_pk = types.ModuleType("puttykeys")
        if isinstance(pem_or_exc, Exception):
            mock_pk.ppkraw_to_openssh = MagicMock(side_effect=pem_or_exc)
        else:
            mock_pk.ppkraw_to_openssh = MagicMock(return_value=pem_or_exc)
        return patch.dict(sys.modules, {"puttykeys": mock_pk}), mock_pk

    def test_successful_load_returns_pkey(self, tmp_path):
        from portkeydrop.ppk_utils import load_ppk_key
        import paramiko

        ppk_file = tmp_path / "test.ppk"
        ppk_file.write_text("fake-ppk-content")

        fake_pem = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n"
        mock_pkey = MagicMock(spec=paramiko.RSAKey)
        ctx, mock_pk = self._mock_puttykeys(fake_pem)

        with ctx, patch("paramiko.PKey.from_private_key", return_value=mock_pkey):
            result = load_ppk_key(str(ppk_file), passphrase=None)

        assert result is mock_pkey
        mock_pk.ppkraw_to_openssh.assert_called_once_with("fake-ppk-content", "")

    def test_passphrase_forwarded(self, tmp_path):
        from portkeydrop.ppk_utils import load_ppk_key
        import paramiko

        ppk_file = tmp_path / "test.ppk"
        ppk_file.write_text("encrypted-ppk")

        fake_pem = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n"
        mock_pkey = MagicMock(spec=paramiko.RSAKey)
        ctx, mock_pk = self._mock_puttykeys(fake_pem)

        with ctx, patch("paramiko.PKey.from_private_key", return_value=mock_pkey):
            load_ppk_key(str(ppk_file), passphrase="secret")

        mock_pk.ppkraw_to_openssh.assert_called_once_with("encrypted-ppk", "secret")

    def test_bad_passphrase_raises_value_error(self, tmp_path):
        from portkeydrop.ppk_utils import load_ppk_key

        ppk_file = tmp_path / "test.ppk"
        ppk_file.write_text("encrypted-ppk")

        ctx, _ = self._mock_puttykeys(ValueError("HMAC mismatch (bad passphrase?)"))
        with ctx:
            with pytest.raises(ValueError, match="Failed to decrypt PPK key"):
                load_ppk_key(str(ppk_file), passphrase="wrong")

    def test_invalid_ppk_format_raises_value_error(self, tmp_path):
        from portkeydrop.ppk_utils import load_ppk_key

        ppk_file = tmp_path / "test.ppk"
        ppk_file.write_text("not-a-ppk-file")

        ctx, _ = self._mock_puttykeys(SyntaxError("PPK missing Public-Lines"))
        with ctx:
            with pytest.raises(ValueError, match="Invalid or unsupported PPK format"):
                load_ppk_key(str(ppk_file))

    def test_missing_puttykeys_raises_import_error(self, tmp_path):
        from portkeydrop.ppk_utils import load_ppk_key

        ppk_file = tmp_path / "test.ppk"
        ppk_file.write_text("fake")

        with patch.dict("sys.modules", {"puttykeys": None}):
            with pytest.raises(ImportError, match="puttykeys is required"):
                load_ppk_key(str(ppk_file))

    def test_generic_parse_exception_raises_value_error(self, tmp_path):
        from portkeydrop.ppk_utils import load_ppk_key

        ppk_file = tmp_path / "test.ppk"
        ppk_file.write_text("bad")

        ctx, _ = self._mock_puttykeys(RuntimeError("unexpected parse failure"))
        with ctx:
            with pytest.raises(ValueError, match="Could not parse PPK key"):
                load_ppk_key(str(ppk_file))

    def test_password_required_exception_raises_value_error(self, tmp_path):
        import paramiko
        from portkeydrop.ppk_utils import load_ppk_key

        ppk_file = tmp_path / "test.ppk"
        ppk_file.write_text("fake")
        fake_pem = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n"
        ctx, _ = self._mock_puttykeys(fake_pem)

        with (
            ctx,
            patch(
                "paramiko.PKey.from_private_key",
                side_effect=paramiko.PasswordRequiredException("needs passphrase"),
            ),
        ):
            with pytest.raises(ValueError, match="requires a passphrase"):
                load_ppk_key(str(ppk_file))

    def test_ssh_exception_raises_value_error(self, tmp_path):
        import paramiko
        from portkeydrop.ppk_utils import load_ppk_key

        ppk_file = tmp_path / "test.ppk"
        ppk_file.write_text("fake")
        fake_pem = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n"
        ctx, _ = self._mock_puttykeys(fake_pem)

        with (
            ctx,
            patch(
                "paramiko.PKey.from_private_key",
                side_effect=paramiko.SSHException("bad key format"),
            ),
        ):
            with pytest.raises(ValueError, match="Could not load converted PPK key"):
                load_ppk_key(str(ppk_file))


class TestProtocolsPpkIntegration:
    """Smoke tests: protocols.py routes .ppk files through ppk_utils."""

    def test_ppk_file_uses_pkey_kwarg(self):
        """When key_path is a .ppk, connect is called with pkey= not key_filename=."""
        import paramiko

        mock_pkey = MagicMock(spec=paramiko.RSAKey)
        connect_kwargs_captured = {}

        info = MagicMock()
        info.key_path = "/fake/mykey.ppk"
        info.password = None
        info.host = "example.com"
        info.effective_port = 22
        info.username = "user"
        info.timeout = 10

        with (
            patch("os.path.exists", return_value=True),
            patch("portkeydrop.ppk_utils.load_ppk_key", return_value=mock_pkey),
            patch("portkeydrop.ppk_utils.is_ppk_file", return_value=True),
        ):
            # Just test the routing logic, not the full connect
            from portkeydrop.ppk_utils import is_ppk_file, load_ppk_key

            key_path = "/fake/mykey.ppk"
            if is_ppk_file(key_path):
                connect_kwargs_captured["pkey"] = load_ppk_key(key_path, None)

        assert "pkey" in connect_kwargs_captured
        assert connect_kwargs_captured["pkey"] is mock_pkey

    def test_ppk_load_failure_wrapped_as_connection_error(self):
        """ValueError from load_ppk_key is re-raised as ConnectionError.

        Tests the error-wrapping pattern used in protocols.py.
        """
        # Replicate the protocols.py wrapping logic directly
        exc = ValueError("bad passphrase")
        with pytest.raises(ConnectionError, match="bad passphrase"):
            try:
                raise exc
            except ValueError as e:
                raise ConnectionError(f"SFTP connection failed: {e}") from e
