"""Integration tests for host key verification policies in SFTPClient.

US-007: Verify that HostKeyPolicy options correctly configure the
SSHClient's missing host key policy and affect connection behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import paramiko
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
def mock_ssh_client():
    """Patch paramiko.SSHClient and return (mock_class, mock_instance)."""
    with patch("paramiko.SSHClient") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_sftp = MagicMock()
        mock_instance.open_sftp.return_value = mock_sftp
        mock_sftp.normalize.return_value = "/"
        yield mock_cls, mock_instance


class TestAutoAddPolicy:
    """Tests for AUTO_ADD host key policy."""

    def test_auto_add_uses_auto_add_policy(self, sftp_info, mock_ssh_client):
        """AC-1: AUTO_ADD policy uses paramiko.AutoAddPolicy."""
        _, mock_ssh = mock_ssh_client
        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()

        mock_ssh.set_missing_host_key_policy.assert_called_once()
        policy_arg = mock_ssh.set_missing_host_key_policy.call_args[0][0]
        assert isinstance(policy_arg, paramiko.AutoAddPolicy)

    def test_default_policy_is_auto_add(self, sftp_info, mock_ssh_client):
        """Default ConnectionInfo uses AUTO_ADD policy."""
        _, mock_ssh = mock_ssh_client
        info = sftp_info()
        assert info.host_key_policy == HostKeyPolicy.AUTO_ADD

        client = SFTPClient(info)
        client.connect()

        policy_arg = mock_ssh.set_missing_host_key_policy.call_args[0][0]
        assert isinstance(policy_arg, paramiko.AutoAddPolicy)

    def test_auto_add_connection_succeeds_with_unknown_host(self, sftp_info, mock_ssh_client):
        """AC-4/AC-5: AUTO_ADD allows connection to unknown hosts."""
        _, mock_ssh = mock_ssh_client
        mock_ssh.open_sftp.return_value.normalize.return_value = "/home/testuser"

        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()

        assert client.connected
        assert client.cwd == "/home/testuser"


class TestStrictPolicy:
    """Tests for STRICT host key policy."""

    def test_strict_uses_reject_policy(self, sftp_info, mock_ssh_client):
        """AC-2: STRICT policy uses paramiko.RejectPolicy."""
        _, mock_ssh = mock_ssh_client
        info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
        client = SFTPClient(info)
        client.connect()

        mock_ssh.set_missing_host_key_policy.assert_called_once()
        policy_arg = mock_ssh.set_missing_host_key_policy.call_args[0][0]
        assert isinstance(policy_arg, paramiko.RejectPolicy)

    def test_strict_policy_rejects_unknown_host(self, sftp_info, mock_ssh_client):
        """AC-4/AC-5: STRICT policy rejects unknown hosts."""
        _, mock_ssh = mock_ssh_client
        mock_ssh.connect.side_effect = paramiko.ssh_exception.SSHException(
            "Server 'testhost.example.com' not found in known_hosts"
        )

        info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
        client = SFTPClient(info)

        with pytest.raises(ConnectionError, match="SFTP connection failed"):
            client.connect()
        assert not client.connected


class TestHostKeyPolicyAppliedDuringConnect:
    """AC-3: Verify policy is applied during connection establishment."""

    def test_policy_set_before_connect_call(self, sftp_info, mock_ssh_client):
        """Host key policy must be set before SSHClient.connect() is called."""
        _, mock_ssh = mock_ssh_client
        call_order: list[str] = []

        mock_ssh.set_missing_host_key_policy.side_effect = (
            lambda p: call_order.append("set_policy")
        )
        mock_ssh.load_system_host_keys.side_effect = (
            lambda: call_order.append("load_keys")
        )
        mock_ssh.connect.side_effect = lambda **kw: call_order.append("connect")

        info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
        client = SFTPClient(info)
        client.connect()

        assert "set_policy" in call_order
        assert "connect" in call_order
        assert call_order.index("set_policy") < call_order.index("connect")

    def test_system_host_keys_loaded(self, sftp_info, mock_ssh_client):
        """System host keys are loaded during connection."""
        _, mock_ssh = mock_ssh_client
        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()

        mock_ssh.load_system_host_keys.assert_called_once()


class TestMissingHostKeyScenarios:
    """AC-4: Handle missing host key scenarios for each policy."""

    def test_auto_add_missing_key_succeeds(self, sftp_info, mock_ssh_client):
        """AUTO_ADD policy: missing host key is automatically added, connection succeeds."""
        _, mock_ssh = mock_ssh_client
        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()
        assert client.connected

    def test_strict_missing_key_fails(self, sftp_info, mock_ssh_client):
        """STRICT policy: missing host key causes connection failure."""
        _, mock_ssh = mock_ssh_client
        mock_ssh.connect.side_effect = paramiko.ssh_exception.SSHException(
            "Server 'testhost.example.com' not found in known_hosts"
        )

        info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
        client = SFTPClient(info)

        with pytest.raises(ConnectionError):
            client.connect()
        assert not client.connected

    def test_strict_known_host_succeeds(self, sftp_info, mock_ssh_client):
        """STRICT policy: known host key allows connection."""
        _, mock_ssh = mock_ssh_client
        info = sftp_info(host_key_policy=HostKeyPolicy.STRICT)
        client = SFTPClient(info)
        client.connect()
        assert client.connected

    def test_load_system_keys_failure_handled(self, sftp_info, mock_ssh_client):
        """Connection proceeds even if loading system host keys fails."""
        _, mock_ssh = mock_ssh_client
        mock_ssh.load_system_host_keys.side_effect = IOError("No such file")

        info = sftp_info(host_key_policy=HostKeyPolicy.AUTO_ADD)
        client = SFTPClient(info)
        client.connect()
        assert client.connected
