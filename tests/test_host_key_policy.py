"""Tests for host key policies."""

from unittest.mock import MagicMock

import paramiko
import pytest

from portkeydrop.host_key_policy import InteractiveHostKeyPolicy
from portkeydrop.protocols import ConnectionInfo, HostKeyPolicy, Protocol


class TestHostKeyPolicy:
    def test_enum_values(self):
        assert HostKeyPolicy.AUTO_ADD.value == "auto_add"
        assert HostKeyPolicy.STRICT.value == "strict"
        assert HostKeyPolicy.PROMPT.value == "prompt"

    def test_enum_has_three_members(self):
        assert len(HostKeyPolicy) == 3

    def test_enum_from_value(self):
        assert HostKeyPolicy("auto_add") is HostKeyPolicy.AUTO_ADD
        assert HostKeyPolicy("strict") is HostKeyPolicy.STRICT
        assert HostKeyPolicy("prompt") is HostKeyPolicy.PROMPT


class TestConnectionInfoHostKeyPolicy:
    def test_default_is_auto_add(self):
        info = ConnectionInfo()
        assert info.host_key_policy is HostKeyPolicy.AUTO_ADD

    def test_accepts_host_key_policy_parameter(self):
        info = ConnectionInfo(host_key_policy=HostKeyPolicy.STRICT)
        assert info.host_key_policy is HostKeyPolicy.STRICT

    def test_prompt_policy(self):
        info = ConnectionInfo(host_key_policy=HostKeyPolicy.PROMPT)
        assert info.host_key_policy is HostKeyPolicy.PROMPT

    def test_with_other_fields(self):
        info = ConnectionInfo(
            protocol=Protocol.SFTP,
            host="example.com",
            host_key_policy=HostKeyPolicy.STRICT,
        )
        assert info.host == "example.com"
        assert info.host_key_policy is HostKeyPolicy.STRICT


class TestInteractiveHostKeyPolicy:
    def test_accept_once_adds_key_without_saving(self, monkeypatch):
        class AcceptOnceDialog:
            REJECT = 0
            ACCEPT_ONCE = 1
            ACCEPT_PERMANENT = 2

            def __init__(self, *_args, **_kwargs):
                pass

            def ShowModal(self):
                return self.ACCEPT_ONCE

            def Destroy(self):
                pass

        import portkeydrop.host_key_policy as host_key_policy

        monkeypatch.setattr(host_key_policy, "HostKeyDialog", AcceptOnceDialog)
        monkeypatch.setattr(
            host_key_policy.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw)
        )

        policy = InteractiveHostKeyPolicy(None, "/tmp/known_hosts")
        key = MagicMock()
        key.get_name.return_value = "ssh-ed25519"
        key.get_fingerprint.return_value = b"\x00\x01\x02"
        client = MagicMock()
        host_keys = MagicMock()
        client.get_host_keys.return_value = host_keys

        policy.missing_host_key(client, "example.com", key)

        host_keys.add.assert_called_once_with("example.com", "ssh-ed25519", key)
        client.save_host_keys.assert_not_called()

    def test_accept_permanent_adds_and_saves(self, monkeypatch):
        class AcceptPermanentDialog:
            REJECT = 0
            ACCEPT_ONCE = 1
            ACCEPT_PERMANENT = 2

            def __init__(self, *_args, **_kwargs):
                pass

            def ShowModal(self):
                return self.ACCEPT_PERMANENT

            def Destroy(self):
                pass

        import portkeydrop.host_key_policy as host_key_policy

        monkeypatch.setattr(host_key_policy, "HostKeyDialog", AcceptPermanentDialog)
        monkeypatch.setattr(
            host_key_policy.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw)
        )

        policy = InteractiveHostKeyPolicy(None, "/tmp/known_hosts")
        key = MagicMock()
        key.get_name.return_value = "ssh-rsa"
        key.get_fingerprint.return_value = b"\xaa\xbb\xcc"
        client = MagicMock()
        host_keys = MagicMock()
        client.get_host_keys.return_value = host_keys

        policy.missing_host_key(client, "example.com", key)

        host_keys.add.assert_called_once_with("example.com", "ssh-rsa", key)
        client.save_host_keys.assert_called_once_with("/tmp/known_hosts")

    def test_reject_raises_ssh_exception(self, monkeypatch):
        class RejectDialog:
            REJECT = 0
            ACCEPT_ONCE = 1
            ACCEPT_PERMANENT = 2

            def __init__(self, *_args, **_kwargs):
                pass

            def ShowModal(self):
                return self.REJECT

            def Destroy(self):
                pass

        import portkeydrop.host_key_policy as host_key_policy

        monkeypatch.setattr(host_key_policy, "HostKeyDialog", RejectDialog)
        monkeypatch.setattr(
            host_key_policy.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw)
        )

        policy = InteractiveHostKeyPolicy(None, "/tmp/known_hosts")
        key = MagicMock()
        key.get_name.return_value = "ssh-rsa"
        key.get_fingerprint.return_value = b"\xaa\xbb\xcc"
        client = MagicMock()
        host_keys = MagicMock()
        client.get_host_keys.return_value = host_keys

        with pytest.raises(paramiko.SSHException, match="rejected by the user"):
            policy.missing_host_key(client, "example.com", key)
