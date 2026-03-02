"""Tests for the ssh_utils module."""

from __future__ import annotations

from unittest import mock

from portkeydrop.ssh_utils import check_ssh_agent_available


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

    def test_windows_no_agent(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("platform.system", return_value="Windows"):
                with mock.patch("os.path.exists", return_value=False):
                    assert check_ssh_agent_available() is False
