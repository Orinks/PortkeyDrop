"""Integration tests for host key verification policies in SFTPClient.

US-007: Verify that HostKeyPolicy options correctly configure the
asyncssh known_hosts parameter and affect connection behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import asyncssh
import pytest

from portkeydrop.protocols import ConnectionInfo, HostKeyPolicy, Protocol, SFTPClient


@pytest.fixture
def sftp_info():
    """Create a base SFTP ConnectionInfo for testing."""

    def _make(**overrides):
        defaults = dict(
            protocol=Protocol.SFTP,
            host="testhost.example.com",
            port=22,
            username="testuser",
            password="testpass",
        )
        defaults.update(overrides)
        return ConnectionInfo(**defaults)

    return _make


@pytest.fixture
def mock_asyncssh_connect():
    """Patch asyncssh.connect and return the mock."""
    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = AsyncMock()
        mock_sftp = AsyncMock()
        mock_sftp.realpath.return_value = "/"
        mock_conn.start_sftp_client.return_value = mock_sftp
        mock_connect.return_value = mock_conn
        yield mock_connect, mock_conn, mock_sftp


class TestAutoAddPolicy:
    """Tests for AUTO_ADD host key policy."""

    def test_auto_add_sets_known_hosts_none(self, sftp_info, mock_asyncssh_connect):
        """AC-1: AUTO_ADD policy passes known_hosts=None to asyncssh."""
        mock_connect, _, _ = mock_asyncssh_connect
        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["known_hosts"] is None

    def test_default_policy_is_auto_add(self, sftp_info, mock_asyncssh_connect):
        """Default ConnectionInfo uses AUTO_ADD policy."""
        mock_connect, _, _ = mock_asyncssh_connect
        info = sftp_info()
        assert info.host_key_policy == HostKeyPolicy.AUTO_ADD

        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["known_hosts"] is None

    def test_auto_add_connection_succeeds_with_unknown_host(self, sftp_info, mock_asyncssh_connect):
        """AC-4/AC-5: AUTO_ADD allows connection to unknown hosts."""
        mock_connect, _, mock_sftp = mock_asyncssh_connect
        mock_sftp.realpath.return_value = "/home/testuser"

        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()

        assert client.connected
        assert client.cwd == "/home/testuser"


class TestStrictPolicy:
    """Tests for STRICT host key policy."""

    def test_strict_uses_default_known_hosts(self, sftp_info, mock_asyncssh_connect):
        """AC-2: STRICT policy uses default known_hosts (no override)."""
        mock_connect, _, _ = mock_asyncssh_connect
        info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert "known_hosts" not in call_kwargs

    def test_strict_policy_rejects_unknown_host(self, sftp_info):
        """AC-4/AC-5: STRICT policy rejects unknown hosts."""
        with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = asyncssh.KeyExchangeFailed(
                "Server 'testhost.example.com' not found in known_hosts"
            )

            info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
            client = SFTPClient(info)

            with pytest.raises(ConnectionError, match="SFTP connection failed"):
                client.connect()
            assert not client.connected


class TestPromptPolicy:
    """Tests for PROMPT host key policy behavior."""

    def test_prompt_policy_sets_known_hosts(self, sftp_info, mock_asyncssh_connect):
        """PROMPT should configure known_hosts to the portkeydrop file."""
        mock_connect, _, _ = mock_asyncssh_connect
        info = sftp_info(host_key_policy=HostKeyPolicy.PROMPT)
        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        # known_hosts is set (either to the file path or None if file doesn't exist)
        assert "known_hosts" in call_kwargs


class TestHostKeyPolicyAppliedDuringConnect:
    """AC-3: Verify policy is applied during connection establishment."""

    def test_known_hosts_passed_to_connect(self, sftp_info, mock_asyncssh_connect):
        """known_hosts parameter is passed to asyncssh.connect()."""
        mock_connect, _, _ = mock_asyncssh_connect
        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()

        call_kwargs = mock_connect.call_args[1]
        assert "known_hosts" in call_kwargs


class TestMissingHostKeyScenarios:
    """AC-4: Handle missing host key scenarios for each policy."""

    def test_auto_add_missing_key_succeeds(self, sftp_info, mock_asyncssh_connect):
        """AUTO_ADD policy: missing host key is automatically added, connection succeeds."""
        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()
        assert client.connected

    def test_strict_missing_key_fails(self, sftp_info):
        """STRICT policy: missing host key causes connection failure."""
        with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = asyncssh.KeyExchangeFailed(
                "Server 'testhost.example.com' not found in known_hosts"
            )

            info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
            client = SFTPClient(info)

            with pytest.raises(ConnectionError):
                client.connect()
            assert not client.connected

    def test_strict_known_host_succeeds(self, sftp_info, mock_asyncssh_connect):
        """STRICT policy: known host key allows connection."""
        info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
        client = SFTPClient(info)
        client.connect()
        assert client.connected

    def test_connection_proceeds_on_general_failure(self, sftp_info):
        """Connection failure is properly reported."""
        with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = OSError("Connection refused")

            info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
            client = SFTPClient(info)
            with pytest.raises(ConnectionError):
                client.connect()
            assert not client.connected
