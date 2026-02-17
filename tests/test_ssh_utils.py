"""Tests for the ssh_utils module."""

from __future__ import annotations

from unittest import mock

import paramiko
import pytest

from portkeydrop.ssh_utils import check_ssh_agent_available, create_ssh_client


class TestCheckSshAgentAvailable:
    """Tests for check_ssh_agent_available()."""

    def test_returns_true_when_ssh_auth_sock_set(self, tmp_path):
        sock = tmp_path / "agent.sock"
        sock.touch()
        with mock.patch.dict("os.environ", {"SSH_AUTH_SOCK": str(sock)}):
            assert check_ssh_agent_available() is True

    def test_returns_false_when_ssh_auth_sock_missing(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("platform.system", return_value="Linux"):
                assert check_ssh_agent_available() is False

    def test_returns_false_when_ssh_auth_sock_points_to_nonexistent(self):
        with mock.patch.dict("os.environ", {"SSH_AUTH_SOCK": "/no/such/path"}):
            with mock.patch("platform.system", return_value="Linux"):
                assert check_ssh_agent_available() is False

    def test_windows_named_pipe_detected(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("platform.system", return_value="Windows"):
                with mock.patch("os.path.exists") as mock_exists:
                    mock_exists.side_effect = lambda p: p == r"\\.\pipe\openssh-ssh-agent"
                    assert check_ssh_agent_available() is True

    def test_windows_pageant_detected(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("platform.system", return_value="Windows"):
                with mock.patch("os.path.exists", return_value=False):
                    mock_agent = mock.MagicMock()
                    mock_agent.get_keys.return_value = [mock.MagicMock()]
                    with mock.patch("paramiko.Agent", return_value=mock_agent):
                        assert check_ssh_agent_available() is True

    def test_windows_no_agent(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("platform.system", return_value="Windows"):
                with mock.patch("os.path.exists", return_value=False):
                    mock_agent = mock.MagicMock()
                    mock_agent.get_keys.return_value = []
                    with mock.patch("paramiko.Agent", return_value=mock_agent):
                        assert check_ssh_agent_available() is False


class TestCreateSshClient:
    """Tests for create_ssh_client()."""

    def test_returns_ssh_client(self):
        client = create_ssh_client()
        assert isinstance(client, paramiko.SSHClient)

    def test_auto_add_policy_by_default(self):
        client = create_ssh_client()
        assert isinstance(client._policy, paramiko.AutoAddPolicy)

    def test_reject_policy_when_auto_add_disabled(self):
        client = create_ssh_client(auto_add_host_key=False)
        assert isinstance(client._policy, paramiko.RejectPolicy)

    def test_allow_agent_stored(self):
        client = create_ssh_client(allow_agent=False)
        assert client._allow_agent is False  # type: ignore[attr-defined]

    def test_look_for_keys_stored(self):
        client = create_ssh_client(look_for_keys=False)
        assert client._look_for_keys is False  # type: ignore[attr-defined]

    def test_default_settings(self):
        client = create_ssh_client()
        assert client._allow_agent is True  # type: ignore[attr-defined]
        assert client._look_for_keys is True  # type: ignore[attr-defined]
