"""Tests for HostKeyPolicy enum and ConnectionInfo.host_key_policy field."""

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
