from __future__ import annotations

from scripts.webdav_flow_probe import DEFAULT_TARGETS, WebDAVProbeTarget, run_target
from portkeydrop.protocols import Protocol, RemoteFile


class FakeWebDAVClient:
    instances: list["FakeWebDAVClient"] = []

    def __init__(self, info) -> None:
        self.info = info
        self.connected = False
        self.cwd = "/"
        self.calls: list[tuple[str, str | None]] = []
        FakeWebDAVClient.instances.append(self)

    def connect(self) -> None:
        self.calls.append(("connect", None))
        self.connected = True

    def disconnect(self) -> None:
        self.calls.append(("disconnect", None))
        self.connected = False

    def list_dir(self, path: str = ".") -> list[RemoteFile]:
        self.calls.append(("list_dir", path))
        if self.cwd == "/docs/":
            return [RemoteFile(name="guide.txt", path="/docs/guide.txt", size=5)]
        return [
            RemoteFile(name="docs", path="/docs/", is_dir=True),
            RemoteFile(name="readme.txt", path="/readme.txt", size=12),
        ]

    def chdir(self, path: str) -> str:
        self.calls.append(("chdir", path))
        if path != "/docs/":
            raise NotADirectoryError(path)
        self.cwd = "/docs/"
        return self.cwd


def test_default_targets_cover_dlp_public_and_private() -> None:
    assert [target.name for target in DEFAULT_TARGETS] == ["dlp-public", "dlp-private"]
    assert DEFAULT_TARGETS[0].host == "https://www.dlp-test.com/webdav/"
    assert DEFAULT_TARGETS[1].host == "https://www.dlp-test.com/webdav_private/"
    assert DEFAULT_TARGETS[0].username == r"www.dlp-test.com\WebDAV"
    assert DEFAULT_TARGETS[0].password == "WebDAV"


def test_run_target_uses_portkeydrop_webdav_navigation_flow() -> None:
    FakeWebDAVClient.instances.clear()
    target = WebDAVProbeTarget(
        name="fake",
        host="https://dav.example.test/root/",
        username="alice",
        password="secret",
        port=443,
        paths=("/docs/",),
    )

    result = run_target(target, client_factory=FakeWebDAVClient)

    client = FakeWebDAVClient.instances[0]
    assert client.info.protocol is Protocol.WEBDAV
    assert client.info.host == "https://dav.example.test/root/"
    assert client.info.username == "alice"
    assert client.info.password == "secret"
    assert client.calls == [
        ("connect", None),
        ("list_dir", "."),
        ("chdir", "/docs/"),
        ("list_dir", "."),
        ("disconnect", None),
    ]
    assert result.ok
    assert [step.label for step in result.steps] == [
        "connect",
        "refresh /",
        "open /docs/",
        "refresh /docs/",
    ]


def test_run_target_reports_directory_navigation_failures() -> None:
    FakeWebDAVClient.instances.clear()
    target = WebDAVProbeTarget(
        name="fake",
        host="https://dav.example.test/",
        username="alice",
        password="secret",
        paths=("/missing/",),
    )

    result = run_target(target, client_factory=FakeWebDAVClient)

    assert not result.ok
    assert result.steps[-1].label == "open /missing/"
    assert "NotADirectoryError" in result.steps[-1].message
