"""Protocol abstraction for file transfer clients."""

from __future__ import annotations

import ftplib
import logging
import ssl
import stat
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import BinaryIO, Callable

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]  # (bytes_transferred, total_bytes)


class Protocol(Enum):
    FTP = "ftp"
    FTPS = "ftps"
    SFTP = "sftp"
    SCP = "scp"
    WEBDAV = "webdav"


@dataclass
class RemoteFile:
    """Represents a file or directory on the remote server."""

    name: str
    path: str
    size: int = 0
    is_dir: bool = False
    modified: datetime | None = None
    permissions: str = ""
    owner: str = ""
    group: str = ""

    @property
    def display_size(self) -> str:
        if self.is_dir:
            return "<DIR>"
        if self.size < 1024:
            return f"{self.size} B"
        if self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        if self.size < 1024 * 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f} MB"
        return f"{self.size / (1024 * 1024 * 1024):.1f} GB"

    @property
    def display_modified(self) -> str:
        if self.modified is None:
            return ""
        return self.modified.strftime("%Y-%m-%d %H:%M")


@dataclass
class ConnectionInfo:
    """Connection parameters for a remote server."""

    protocol: Protocol = Protocol.SFTP
    host: str = ""
    port: int = 0  # 0 means use protocol default
    username: str = ""
    password: str = ""
    key_path: str = ""
    timeout: int = 30
    passive_mode: bool = True  # FTP only

    @property
    def effective_port(self) -> int:
        if self.port > 0:
            return self.port
        defaults = {
            Protocol.FTP: 21,
            Protocol.FTPS: 990,
            Protocol.SFTP: 22,
            Protocol.SCP: 22,
            Protocol.WEBDAV: 443,
        }
        return defaults.get(self.protocol, 22)


class TransferClient(ABC):
    """Abstract base class for file transfer protocol clients."""

    def __init__(self, info: ConnectionInfo) -> None:
        self._info = info
        self._connected = False
        self._cwd = "/"

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def cwd(self) -> str:
        return self._cwd

    @abstractmethod
    def connect(self) -> None:
        """Connect to the remote server. Raises ConnectionError on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the remote server."""

    @abstractmethod
    def list_dir(self, path: str = ".") -> list[RemoteFile]:
        """List files in the given directory."""

    @abstractmethod
    def chdir(self, path: str) -> str:
        """Change working directory. Returns the new absolute path."""

    @abstractmethod
    def download(
        self, remote_path: str, local_file: BinaryIO, callback: ProgressCallback | None = None
    ) -> None:
        """Download a remote file to a local file object."""

    @abstractmethod
    def upload(
        self, local_file: BinaryIO, remote_path: str, callback: ProgressCallback | None = None
    ) -> None:
        """Upload a local file to the remote server."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete a remote file."""

    @abstractmethod
    def rmdir(self, path: str) -> None:
        """Remove a remote directory."""

    @abstractmethod
    def mkdir(self, path: str) -> None:
        """Create a remote directory."""

    @abstractmethod
    def rename(self, old_path: str, new_path: str) -> None:
        """Rename a remote file or directory."""

    @abstractmethod
    def stat(self, path: str) -> RemoteFile:
        """Get file info for a remote path."""

    def parent_dir(self) -> str:
        """Navigate to parent directory. Returns the new path."""
        parent = str(PurePosixPath(self._cwd).parent)
        return self.chdir(parent)


class FTPClient(TransferClient):
    """FTP protocol client using ftplib."""

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__(info)
        self._ftp: ftplib.FTP | None = None

    def connect(self) -> None:
        try:
            self._ftp = ftplib.FTP()
            self._ftp.connect(self._info.host, self._info.effective_port, self._info.timeout)
            self._ftp.login(self._info.username, self._info.password)
            if self._info.passive_mode:
                self._ftp.set_pasv(True)
            self._cwd = self._ftp.pwd()
            self._connected = True
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"FTP connection failed: {e}") from e

    def disconnect(self) -> None:
        if self._ftp:
            try:
                self._ftp.quit()
            except Exception:
                try:
                    self._ftp.close()
                except Exception:
                    pass
        self._ftp = None
        self._connected = False

    def _ensure_connected(self) -> ftplib.FTP:
        if not self._ftp or not self._connected:
            raise ConnectionError("Not connected")
        return self._ftp

    def list_dir(self, path: str = ".") -> list[RemoteFile]:
        ftp = self._ensure_connected()
        files: list[RemoteFile] = []
        lines: list[str] = []
        ftp.retrlines(f"MLSD {path}", lines.append)
        for line in lines:
            facts_str, _, name = line.partition("; ")
            if not name or name in (".", ".."):
                continue
            name = name.strip()
            facts: dict[str, str] = {}
            for fact in facts_str.split(";"):
                if "=" in fact:
                    k, v = fact.split("=", 1)
                    facts[k.strip().lower()] = v.strip()
            is_dir = facts.get("type", "").lower() in ("dir", "cdir", "pdir")
            size = int(facts.get("size", "0")) if not is_dir else 0
            modified = None
            if "modify" in facts:
                try:
                    modified = datetime.strptime(facts["modify"][:14], "%Y%m%d%H%M%S")
                except ValueError:
                    pass
            full_path = (
                f"{self._cwd.rstrip('/')}/{name}" if path == "." else f"{path.rstrip('/')}/{name}"
            )
            files.append(
                RemoteFile(
                    name=name,
                    path=full_path,
                    size=size,
                    is_dir=is_dir,
                    modified=modified,
                    permissions=facts.get("perm", ""),
                )
            )
        return files

    def chdir(self, path: str) -> str:
        ftp = self._ensure_connected()
        ftp.cwd(path)
        self._cwd = ftp.pwd()
        return self._cwd

    def download(
        self, remote_path: str, local_file: BinaryIO, callback: ProgressCallback | None = None
    ) -> None:
        ftp = self._ensure_connected()
        total = ftp.size(remote_path) or 0
        transferred = 0
        block_size = 8192

        def write_block(data: bytes) -> None:
            nonlocal transferred
            local_file.write(data)
            transferred += len(data)
            if callback:
                callback(transferred, total)

        ftp.retrbinary(f"RETR {remote_path}", write_block, block_size)

    def upload(
        self, local_file: BinaryIO, remote_path: str, callback: ProgressCallback | None = None
    ) -> None:
        ftp = self._ensure_connected()
        local_file.seek(0, 2)
        total = local_file.tell()
        local_file.seek(0)
        transferred = 0
        block_size = 8192

        def read_callback(data: bytes) -> None:
            nonlocal transferred
            transferred += len(data)
            if callback:
                callback(transferred, total)

        ftp.storbinary(f"STOR {remote_path}", local_file, block_size, read_callback)

    def delete(self, path: str) -> None:
        ftp = self._ensure_connected()
        ftp.delete(path)

    def rmdir(self, path: str) -> None:
        ftp = self._ensure_connected()
        ftp.rmd(path)

    def mkdir(self, path: str) -> None:
        ftp = self._ensure_connected()
        ftp.mkd(path)

    def rename(self, old_path: str, new_path: str) -> None:
        ftp = self._ensure_connected()
        ftp.rename(old_path, new_path)

    def stat(self, path: str) -> RemoteFile:
        ftp = self._ensure_connected()
        size = ftp.size(path) or 0
        modified = None
        try:
            mdtm = ftp.sendcmd(f"MDTM {path}")
            if mdtm.startswith("213 "):
                modified = datetime.strptime(mdtm[4:18], "%Y%m%d%H%M%S")
        except Exception:
            pass
        name = PurePosixPath(path).name
        return RemoteFile(name=name, path=path, size=size, modified=modified)


class FTPSClient(FTPClient):
    """FTPS (FTP over SSL/TLS) client."""

    def connect(self) -> None:
        try:
            ctx = ssl.create_default_context()
            self._ftp = ftplib.FTP_TLS(context=ctx)
            self._ftp.connect(self._info.host, self._info.effective_port, self._info.timeout)
            self._ftp.login(self._info.username, self._info.password)
            self._ftp.prot_p()  # Switch to protected/encrypted data connection
            if self._info.passive_mode:
                self._ftp.set_pasv(True)
            self._cwd = self._ftp.pwd()
            self._connected = True
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"FTPS connection failed: {e}") from e


class SFTPClient(TransferClient):
    """SFTP protocol client using paramiko."""

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__(info)
        self._transport = None
        self._sftp = None

    def connect(self) -> None:
        try:
            import paramiko

            self._transport = paramiko.Transport((self._info.host, self._info.effective_port))
            connect_kwargs: dict = {}
            if self._info.key_path:
                key = paramiko.RSAKey.from_private_key_file(self._info.key_path)
                connect_kwargs["pkey"] = key
            else:
                connect_kwargs["password"] = self._info.password
            self._transport.connect(username=self._info.username, **connect_kwargs)
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
            if self._sftp is None:
                raise ConnectionError("Failed to create SFTP session")
            self._cwd = self._sftp.normalize(".")
            self._connected = True
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"SFTP connection failed: {e}") from e

    def disconnect(self) -> None:
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
        self._sftp = None
        self._transport = None
        self._connected = False

    def _ensure_connected(self):
        if not self._sftp or not self._connected:
            raise ConnectionError("Not connected")
        return self._sftp

    def list_dir(self, path: str = ".") -> list[RemoteFile]:
        sftp = self._ensure_connected()
        target = path if path != "." else self._cwd
        files: list[RemoteFile] = []
        for attr in sftp.listdir_attr(target):
            if attr.filename in (".", ".."):
                continue
            is_dir = bool(attr.st_mode is not None and stat.S_ISDIR(attr.st_mode))
            if not is_dir and hasattr(attr, "longname") and attr.longname.startswith("d"):
                is_dir = True
            modified = datetime.fromtimestamp(attr.st_mtime) if attr.st_mtime else None
            perms = stat.filemode(attr.st_mode) if attr.st_mode else ""
            full_path = f"{target.rstrip('/')}/{attr.filename}"
            files.append(
                RemoteFile(
                    name=attr.filename,
                    path=full_path,
                    size=attr.st_size or 0,
                    is_dir=is_dir,
                    modified=modified,
                    permissions=perms,
                    owner=str(attr.st_uid or ""),
                    group=str(attr.st_gid or ""),
                )
            )
        return files

    def chdir(self, path: str) -> str:
        sftp = self._ensure_connected()
        sftp.chdir(path)
        self._cwd = sftp.normalize(".")
        return self._cwd

    def download(
        self, remote_path: str, local_file: BinaryIO, callback: ProgressCallback | None = None
    ) -> None:
        sftp = self._ensure_connected()

        def progress(transferred: int, total_bytes: int) -> None:
            if callback:
                callback(transferred, total_bytes)

        sftp.getfo(remote_path, local_file, callback=progress)

    def upload(
        self, local_file: BinaryIO, remote_path: str, callback: ProgressCallback | None = None
    ) -> None:
        sftp = self._ensure_connected()
        local_file.seek(0, 2)
        total = local_file.tell()
        local_file.seek(0)

        def progress(transferred: int, total_bytes: int) -> None:
            if callback:
                callback(transferred, total_bytes)

        sftp.putfo(local_file, remote_path, file_size=total, callback=progress)

    def delete(self, path: str) -> None:
        sftp = self._ensure_connected()
        sftp.remove(path)

    def rmdir(self, path: str) -> None:
        sftp = self._ensure_connected()
        sftp.rmdir(path)

    def mkdir(self, path: str) -> None:
        sftp = self._ensure_connected()
        sftp.mkdir(path)

    def rename(self, old_path: str, new_path: str) -> None:
        sftp = self._ensure_connected()
        sftp.rename(old_path, new_path)

    def stat(self, path: str) -> RemoteFile:
        sftp = self._ensure_connected()
        attr = sftp.stat(path)
        is_dir = stat.S_ISDIR(attr.st_mode) if attr.st_mode else False
        modified = datetime.fromtimestamp(attr.st_mtime) if attr.st_mtime else None
        perms = stat.filemode(attr.st_mode) if attr.st_mode else ""
        name = PurePosixPath(path).name
        return RemoteFile(
            name=name,
            path=path,
            size=attr.st_size or 0,
            is_dir=is_dir,
            modified=modified,
            permissions=perms,
        )


def create_client(info: ConnectionInfo) -> TransferClient:
    """Factory function to create the appropriate protocol client."""
    clients = {
        Protocol.FTP: FTPClient,
        Protocol.FTPS: FTPSClient,
        Protocol.SFTP: SFTPClient,
    }
    client_class = clients.get(info.protocol)
    if client_class is None:
        raise ValueError(f"Protocol {info.protocol.value} is not yet supported")
    return client_class(info)
