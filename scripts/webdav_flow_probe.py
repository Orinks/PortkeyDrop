from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from portkeydrop.protocols import ConnectionInfo, Protocol, RemoteFile, WebDAVClient


@dataclass(frozen=True)
class WebDAVProbeTarget:
    name: str
    host: str
    username: str
    password: str
    port: int = 443
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeStep:
    label: str
    ok: bool
    message: str


@dataclass(frozen=True)
class ProbeResult:
    target: WebDAVProbeTarget
    steps: tuple[ProbeStep, ...]

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.steps)


ClientFactory = Callable[[ConnectionInfo], WebDAVClient]


DEFAULT_TARGETS: tuple[WebDAVProbeTarget, ...] = (
    WebDAVProbeTarget(
        name="dlp-public",
        host="https://www.dlp-test.com/webdav/",
        username=r"www.dlp-test.com\WebDAV",
        password="WebDAV",
    ),
    WebDAVProbeTarget(
        name="dlp-private",
        host="https://www.dlp-test.com/webdav_private/",
        username=r"www.dlp-test.com\WebDAV",
        password="WebDAV",
    ),
)


def _format_listing(files: list[RemoteFile]) -> str:
    if not files:
        return "0 items"
    dirs = sum(1 for item in files if item.is_dir)
    file_count = len(files) - dirs
    sample = ", ".join(item.name for item in files[:5])
    return f"{len(files)} items ({dirs} dirs, {file_count} files): {sample}"


def _error_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def run_target(
    target: WebDAVProbeTarget,
    *,
    client_factory: ClientFactory = WebDAVClient,
) -> ProbeResult:
    info = ConnectionInfo(
        protocol=Protocol.WEBDAV,
        host=target.host,
        port=target.port,
        username=target.username,
        password=target.password,
        timeout=30,
    )
    client = client_factory(info)
    steps: list[ProbeStep] = []

    try:
        client.connect()
        steps.append(ProbeStep("connect", True, "connected"))

        files = client.list_dir()
        steps.append(ProbeStep("refresh /", True, _format_listing(files)))

        for path in _unique_paths(target.paths):
            try:
                client.chdir(path)
                steps.append(ProbeStep(f"open {path}", True, f"cwd={client.cwd}"))
            except Exception as exc:
                steps.append(ProbeStep(f"open {path}", False, _error_message(exc)))
                continue

            try:
                files = client.list_dir()
                steps.append(ProbeStep(f"refresh {client.cwd}", True, _format_listing(files)))
            except Exception as exc:
                steps.append(ProbeStep(f"refresh {client.cwd}", False, _error_message(exc)))
    except Exception as exc:
        steps.append(ProbeStep("connect", False, _error_message(exc)))
        steps.append(ProbeStep("traceback", False, traceback.format_exc().strip()))
    finally:
        try:
            client.disconnect()
        except Exception as exc:
            steps.append(ProbeStep("disconnect", False, _error_message(exc)))

    return ProbeResult(target=target, steps=tuple(steps))


def _unique_paths(paths: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        normalized = path.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return tuple(unique)


def _select_targets(
    names: Iterable[str], extra_paths: tuple[str, ...]
) -> tuple[WebDAVProbeTarget, ...]:
    requested = set(names)
    if not requested or "all" in requested:
        selected = DEFAULT_TARGETS
    else:
        by_name = {target.name: target for target in DEFAULT_TARGETS}
        unknown = requested - set(by_name)
        if unknown:
            raise SystemExit(f"Unknown target(s): {', '.join(sorted(unknown))}")
        selected = tuple(by_name[name] for name in requested)
    if not extra_paths:
        return selected
    return tuple(
        WebDAVProbeTarget(
            name=target.name,
            host=target.host,
            username=target.username,
            password=target.password,
            port=target.port,
            paths=(*target.paths, *extra_paths),
        )
        for target in selected
    )


def format_result(result: ProbeResult) -> str:
    lines = [f"{result.target.name} {result.target.host}"]
    for step in result.steps:
        marker = "PASS" if step.ok else "FAIL"
        lines.append(f"  [{marker}] {step.label}: {step.message}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe public WebDAV servers through PortkeyDrop's WebDAVClient navigation flow."
        )
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Target name to probe: dlp-public, dlp-private, or all. May be repeated.",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Extra remote directory path to open with the same chdir/list flow PKD uses.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    targets = _select_targets(args.target, tuple(args.path))
    results = [run_target(target) for target in targets]
    for index, result in enumerate(results):
        if index:
            print()
        print(format_result(result))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
