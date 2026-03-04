"""Protocol abstraction for file transfer clients."""

from __future__ import annotations

import asyncio
import base64
import binascii
import ftplib
import hashlib
import hmac
import logging
import os
import ssl
import stat
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Callable

if TYPE_CHECKING:
    import asyncssh

logger = logging.getLogger(__name__)

# asyncssh SFTP v4+ file type constants (avoids import at module level)
_SFTP_TYPE_DIRECTORY = 2
_SFTP_TYPE_SYMLINK = 3

ProgressCallback = Callable[[int, int], None]  # (bytes_transferred, total_bytes)


class Protocol(Enum):
    FTP = "ftp"
    FTPS = "ftps"
    SFTP = "sftp"
    SCP = "scp"
    WEBDAV = "webdav"


class HostKeyPolicy(Enum):
    """SSH host key verification policy."""

    AUTO_ADD = "auto_add"
    STRICT = "strict"
    PROMPT = "prompt"


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
    host_key_policy: HostKeyPolicy = HostKeyPolicy.AUTO_ADD

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

    def _path_exists(self, path: str) -> bool:
        ftp = self._ensure_connected()
        try:
            ftp.sendcmd(f"MLST {path}")
            return True
        except Exception:
            return False

    def _is_directory(self, path: str) -> bool:
        ftp = self._ensure_connected()
        try:
            response = ftp.sendcmd(f"MLST {path}")
            return "type=dir" in response.lower()
        except Exception:
            return False

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
        remote_size = ftp.size(remote_path)
        if remote_size is None or remote_size != total:
            raise RuntimeError(
                f"Remote upload verification failed for {remote_path}: expected {total} bytes, "
                f"got {remote_size if remote_size is not None else 'unknown'}."
            )

    def delete(self, path: str) -> None:
        ftp = self._ensure_connected()
        ftp.delete(path)
        if self._path_exists(path):
            raise RuntimeError(f"Remote delete verification failed for {path}.")

    def rmdir(self, path: str) -> None:
        ftp = self._ensure_connected()
        ftp.rmd(path)
        if self._path_exists(path):
            raise RuntimeError(f"Remote directory delete verification failed for {path}.")

    def mkdir(self, path: str) -> None:
        ftp = self._ensure_connected()
        ftp.mkd(path)
        if not self._is_directory(path):
            raise RuntimeError(f"Remote mkdir verification failed for {path}.")

    def rename(self, old_path: str, new_path: str) -> None:
        ftp = self._ensure_connected()
        ftp.rename(old_path, new_path)
        if not self._path_exists(new_path):
            raise RuntimeError(f"Remote rename verification failed for {new_path}.")

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
    """SFTP protocol client using asyncssh.

    Runs asyncssh in a dedicated event loop on a background thread so the
    wx UI thread is never blocked.  Every public method dispatches work to
    that loop via ``_run``.
    """

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__(info)
        self._conn: asyncssh.SSHClientConnection | None = None
        self._sftp: asyncssh.SFTPClient | None = None
        # Dedicated event loop running on a daemon thread
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run(self, coro):
        """Submit a coroutine to the background loop and block until done."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def _ensure_connected(self) -> asyncssh.SFTPClient:
        if not self._conn or not self._sftp:
            raise ConnectionError("Not connected")
        return self._sftp

    @staticmethod
    def _read_private_key_file(path: str) -> bytes:
        return Path(path).read_bytes()

    @staticmethod
    def _parse_ppk_header(key_data: bytes) -> tuple[bool, str]:
        first_line = key_data.splitlines()[0] if key_data else b""
        if not first_line.startswith(b"PuTTY-User-Key-File-"):
            return False, ""

        try:
            header = first_line.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return True, "PPK"

        version, _, key_type = header.partition(":")
        version_label = version.replace("PuTTY-User-Key-File-", "PPK v").strip()
        key_type_label = key_type.strip() or "unknown-key-type"

        encryption_label = "unknown-encryption"
        for line in key_data.splitlines()[1:12]:
            if line.startswith(b"Encryption:"):
                try:
                    encryption_label = (
                        line.decode("ascii", errors="strict").split(":", 1)[1].strip()
                    )
                except UnicodeDecodeError:
                    encryption_label = "unknown-encryption"
                break

        return True, f"{version_label} ({key_type_label}, encryption={encryption_label})"

    @staticmethod
    def _read_ppk_string(blob: bytes, offset: int) -> tuple[bytes, int]:
        if offset + 4 > len(blob):
            raise ValueError("truncated PPK binary data")
        length = int.from_bytes(blob[offset : offset + 4], "big")
        offset += 4
        if offset + length > len(blob):
            raise ValueError("truncated PPK binary data")
        value = blob[offset : offset + length]
        offset += length
        return value, offset

    @staticmethod
    def _read_ppk_mpint(blob: bytes, offset: int) -> tuple[int, int]:
        value, offset = SFTPClient._read_ppk_string(blob, offset)
        if not value:
            return 0, offset
        return int.from_bytes(value, "big", signed=False), offset

    @staticmethod
    def _decode_ppk_text(key_data: bytes) -> tuple[int, str, str, str, bytes, bytes, str]:
        try:
            ppk_text = key_data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("PPK data is not valid UTF-8 text") from exc

        lines = [line.strip() for line in ppk_text.splitlines()]
        if not lines:
            raise ValueError("empty PPK file")

        first = lines[0]
        if not first.startswith("PuTTY-User-Key-File-"):
            raise ValueError("not a PuTTY PPK file")

        prefix, _, key_type = first.partition(":")
        if not key_type.strip():
            raise ValueError("missing key type in PPK header")

        try:
            version = int(prefix.replace("PuTTY-User-Key-File-", "", 1).strip())
        except ValueError as exc:
            raise ValueError("invalid PPK version header") from exc

        fields: dict[str, str] = {}
        i = 1
        while i < len(lines):
            line = lines[i]
            if ":" not in line:
                i += 1
                continue

            name, value = line.split(":", 1)
            name = name.strip()
            value = value.strip()

            if name in {"Public-Lines", "Private-Lines"}:
                try:
                    count = int(value)
                except ValueError as exc:
                    raise ValueError(f"invalid {name} value in PPK") from exc
                start = i + 1
                end = start + count
                if end > len(lines):
                    raise ValueError(f"truncated {name} data in PPK")
                fields[name] = "".join(lines[start:end])
                i = end
                continue

            fields[name] = value
            i += 1

        if "Encryption" not in fields:
            raise ValueError("missing Encryption field in PPK")
        if "Comment" not in fields:
            raise ValueError("missing Comment field in PPK")
        if "Public-Lines" not in fields or "Private-Lines" not in fields:
            raise ValueError("PPK missing either Public-Lines or Private-Lines")
        if "Private-MAC" not in fields:
            raise ValueError("missing Private-MAC field in PPK")

        try:
            public_blob = base64.b64decode(fields["Public-Lines"], validate=True)
            private_blob = base64.b64decode(fields["Private-Lines"], validate=True)
        except binascii.Error as exc:
            raise ValueError("invalid base64 data in PPK") from exc

        return (
            version,
            key_type.strip(),
            fields["Encryption"],
            fields["Comment"],
            public_blob,
            private_blob,
            fields["Private-MAC"],
        )

    @staticmethod
    def _convert_ppk_rsa_unencrypted(key_data: bytes) -> tuple[bytes | None, str]:
        try:
            (
                _version,
                header_key_type,
                encryption,
                _comment,
                public_blob,
                private_blob,
                _private_mac,
            ) = SFTPClient._decode_ppk_text(key_data)
        except ValueError as exc:
            return None, str(exc)

        if header_key_type != "ssh-rsa":
            return None, f"unsupported PPK key type '{header_key_type}' for RSA native converter"
        if encryption.lower() != "none":
            return None, f"unsupported PPK encryption '{encryption}' for RSA native converter"

        try:
            key_type, offset = SFTPClient._read_ppk_string(public_blob, 0)
            if key_type != b"ssh-rsa":
                decoded_type = key_type.decode("utf-8", errors="ignore")
                return (
                    None,
                    f"unsupported public key type '{decoded_type}' for RSA native converter",
                )
            e, offset = SFTPClient._read_ppk_mpint(public_blob, offset)
            n, offset = SFTPClient._read_ppk_mpint(public_blob, offset)
            if offset != len(public_blob):
                return None, "unexpected trailing data in PPK public blob"

            d, priv_offset = SFTPClient._read_ppk_mpint(private_blob, 0)
            p, priv_offset = SFTPClient._read_ppk_mpint(private_blob, priv_offset)
            q, priv_offset = SFTPClient._read_ppk_mpint(private_blob, priv_offset)
            if priv_offset != len(private_blob):
                return None, "unexpected trailing data in PPK private blob"
        except ValueError as exc:
            return None, str(exc)

        if any(v <= 0 for v in (e, n, d, p, q)):
            return None, "PPK RSA parameters must be positive integers"
        if n != p * q:
            return None, "PPK RSA parameters are inconsistent (n != p*q)"

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa

            private_key = rsa.RSAPrivateNumbers(
                p=p,
                q=q,
                d=d,
                dmp1=d % (p - 1),
                dmq1=d % (q - 1),
                iqmp=pow(q, -1, p),
                public_numbers=rsa.RSAPublicNumbers(e=e, n=n),
            ).private_key()
        except Exception as exc:
            return None, str(exc).strip() or exc.__class__.__name__

        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return pem, ""

    @staticmethod
    def _convert_ppk_v3_ed25519_unencrypted(key_data: bytes) -> tuple[bytes | None, str]:
        try:
            (
                version,
                header_key_type,
                encryption,
                comment,
                public_blob,
                private_blob,
                private_mac,
            ) = SFTPClient._decode_ppk_text(key_data)
        except ValueError as exc:
            return None, str(exc)

        if version != 3:
            return None, "unsupported PPK version for native converter"
        if header_key_type != "ssh-ed25519":
            return None, f"unsupported PPK key type '{header_key_type}' for native converter"
        if encryption.lower() != "none":
            return None, f"unsupported PPK encryption '{encryption}' for native converter"

        comment_bytes = comment.encode("utf-8")
        mac_payload = b"".join(
            len(part).to_bytes(4, "big") + part
            for part in (
                header_key_type.encode("utf-8"),
                encryption.encode("utf-8"),
                comment_bytes,
                public_blob,
                private_blob,
            )
        )
        expected_mac = hmac.new(b"", mac_payload, hashlib.sha256).hexdigest()
        if expected_mac.lower() != private_mac.lower():
            return None, "PPK v3 private MAC mismatch (file is corrupted or malformed)"

        try:
            pub_key_type, pub_offset = SFTPClient._read_ppk_string(public_blob, 0)
            if pub_key_type != b"ssh-ed25519":
                decoded_type = pub_key_type.decode("utf-8", errors="ignore")
                return None, f"unsupported public key type '{decoded_type}'"
            pub_value, pub_offset = SFTPClient._read_ppk_string(public_blob, pub_offset)
            if pub_offset != len(public_blob):
                return None, "unexpected trailing data in PPK public blob"

            priv_value, priv_offset = SFTPClient._read_ppk_string(private_blob, 0)
            if priv_offset != len(private_blob):
                return None, "unexpected trailing data in PPK private blob"
        except ValueError as exc:
            return None, str(exc)

        pub_part = (
            len(b"ssh-ed25519").to_bytes(4, "big")
            + b"ssh-ed25519"
            + len(pub_value).to_bytes(4, "big")
            + pub_value
        )
        private_part = (
            (1).to_bytes(4, "big")
            + (1).to_bytes(4, "big")
            + pub_part
            + (len(priv_value) + len(pub_value)).to_bytes(4, "big")
            + priv_value
            + pub_value
            + len(comment_bytes).to_bytes(4, "big")
            + comment_bytes
        )
        pad_len = 8 - (len(private_part) % 8)
        if pad_len == 0:
            pad_len = 8
        private_part += bytes(range(1, pad_len + 1))

        openssh_blob = (
            b"openssh-key-v1\x00"
            + len(b"none").to_bytes(4, "big")
            + b"none"
            + len(b"none").to_bytes(4, "big")
            + b"none"
            + (0).to_bytes(4, "big")
            + (1).to_bytes(4, "big")
            + len(pub_part).to_bytes(4, "big")
            + pub_part
            + len(private_part).to_bytes(4, "big")
            + private_part
        )
        openssh_b64 = base64.b64encode(openssh_blob).decode("ascii")
        lines = [openssh_b64[i : i + 70] for i in range(0, len(openssh_b64), 70)]
        pem = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            + "\n".join(lines)
            + "\n-----END OPENSSH PRIVATE KEY-----\n"
        )
        return pem.encode("utf-8"), ""

    @staticmethod
    def _convert_ppk_with_pure_python(
        key_data: bytes,
        passphrase: str | None,
        ppk_variant: str,
    ) -> tuple[bytes | None, str]:
        is_ppk, parsed_variant = SFTPClient._parse_ppk_header(key_data)
        normalized_variant = parsed_variant if is_ppk else ppk_variant

        decoded_ppk: tuple[int, str, str, str, bytes, bytes, str] | None = None
        try:
            decoded_ppk = SFTPClient._decode_ppk_text(key_data)
        except ValueError:
            decoded_ppk = None

        if decoded_ppk:
            version, key_type, encryption, *_ = decoded_ppk
            normalized_key_type = key_type.strip().lower()
            normalized_encryption = encryption.strip().lower()

            if normalized_key_type == "ssh-rsa" and normalized_encryption == "none":
                # Avoid trusting third-party converter CRT values for RSA PPK:
                # rebuild from validated RSA components and serialize deterministically.
                converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(key_data)
                if converted:
                    return converted, ""
                return None, reason

            if (
                version == 3
                and normalized_key_type == "ssh-ed25519"
                and normalized_encryption == "none"
            ):
                converted, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(key_data)
                if converted:
                    return converted, ""

        if normalized_variant == "PPK v3 (ssh-ed25519, encryption=none)":
            converted, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(key_data)
            if converted:
                return converted, ""
        if normalized_variant in {
            "PPK v2 (ssh-rsa, encryption=none)",
            "PPK v3 (ssh-rsa, encryption=none)",
        }:
            converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(key_data)
            if converted:
                return converted, ""

        try:
            from puttykeys import ppkraw_to_openssh
        except Exception:
            if normalized_variant == "PPK v3 (ssh-ed25519, encryption=none)":
                converted, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(key_data)
                if converted:
                    return converted, ""
                return None, reason or "required dependency 'puttykeys' is not installed"
            if normalized_variant in {
                "PPK v2 (ssh-rsa, encryption=none)",
                "PPK v3 (ssh-rsa, encryption=none)",
            }:
                converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(key_data)
                if converted:
                    return converted, ""
                return None, reason or "required dependency 'puttykeys' is not installed"
            return None, "required dependency 'puttykeys' is not installed"

        try:
            ppk_text = key_data.decode("utf-8")
        except UnicodeDecodeError:
            return None, "PPK data is not valid UTF-8 text"

        try:
            converted_text = ppkraw_to_openssh(ppk_text, passphrase or "")
        except Exception as exc:
            if decoded_ppk:
                version, key_type, encryption, *_ = decoded_ppk
                normalized_key_type = key_type.strip().lower()
                normalized_encryption = encryption.strip().lower()
                if normalized_key_type == "ssh-rsa" and normalized_encryption == "none":
                    converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(key_data)
                    if converted:
                        return converted, ""
                    return None, reason or (str(exc).strip() or exc.__class__.__name__)
                if (
                    version == 3
                    and normalized_key_type == "ssh-ed25519"
                    and normalized_encryption == "none"
                ):
                    converted, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(key_data)
                    if converted:
                        return converted, ""
                    return None, reason or (str(exc).strip() or exc.__class__.__name__)
            if normalized_variant == "PPK v3 (ssh-ed25519, encryption=none)":
                converted, reason = SFTPClient._convert_ppk_v3_ed25519_unencrypted(key_data)
                if converted:
                    return converted, ""
                return None, reason or (str(exc).strip() or exc.__class__.__name__)
            if normalized_variant in {
                "PPK v2 (ssh-rsa, encryption=none)",
                "PPK v3 (ssh-rsa, encryption=none)",
            }:
                converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(key_data)
                if converted:
                    return converted, ""
                return None, reason or (str(exc).strip() or exc.__class__.__name__)
            return None, str(exc).strip() or exc.__class__.__name__

        if not converted_text:
            return None, f"unsupported PPK variant for {ppk_variant}"

        if decoded_ppk:
            _version, key_type, encryption, *_ = decoded_ppk
            normalized_key_type = key_type.strip().lower()
            normalized_encryption = encryption.strip().lower()
            if normalized_key_type == "ssh-rsa" and normalized_encryption == "none":
                converted, reason = SFTPClient._convert_ppk_rsa_unencrypted(key_data)
                if converted:
                    return converted, ""
                return None, reason

        if isinstance(converted_text, bytes):
            return converted_text, ""

        return converted_text.encode("utf-8"), ""

    def _load_client_key(
        self,
        key_path: str,
        passphrase: str | None,
    ) -> tuple[object, str]:
        import asyncssh

        if Path(key_path).suffix.lower() == ".ppk":
            key_data = self._read_private_key_file(key_path)
            is_ppk_header, parsed_variant = self._parse_ppk_header(key_data)
            ppk_variant = parsed_variant if is_ppk_header else "PPK (.ppk)"

            converted_key_data, convert_reason = self._convert_ppk_with_pure_python(
                key_data, passphrase, ppk_variant
            )
            if not converted_key_data:
                raise ConnectionError(
                    "SFTP connection failed: "
                    + self._format_key_import_error(
                        convert_reason,
                        is_ppk=True,
                        ppk_variant=ppk_variant,
                    )
                )

            try:
                converted_key = asyncssh.import_private_key(converted_key_data)
            except Exception as exc:
                import_failure_detail = str(exc)
                if (
                    "dmp1 must be odd" in import_failure_detail.lower()
                    and "ssh-rsa" in ppk_variant.lower()
                    and "encryption=none" in ppk_variant.lower()
                ):
                    repaired_key_data, repair_reason = self._convert_ppk_rsa_unencrypted(key_data)
                    if repaired_key_data:
                        try:
                            repaired_key = asyncssh.import_private_key(repaired_key_data)
                            return (
                                repaired_key,
                                f"key-file:{self._info.key_path} ({ppk_variant}, repaired RSA conversion)",
                            )
                        except Exception as repair_exc:
                            import_failure_detail = (
                                f"{exc}; native RSA repair import failed: {repair_exc}"
                            )
                    elif repair_reason:
                        import_failure_detail = f"{exc}; native RSA repair failed: {repair_reason}"
                raise ConnectionError(
                    "SFTP connection failed: "
                    + self._format_key_import_error(
                        f"converted OpenSSH key import failed: {import_failure_detail}",
                        is_ppk=True,
                        ppk_variant=ppk_variant,
                    )
                ) from exc

            return (
                converted_key,
                f"key-file:{self._info.key_path} ({ppk_variant}, converted via puttykeys)",
            )

        try:
            key = asyncssh.read_private_key(key_path, passphrase=passphrase)
            return key, f"key-file:{self._info.key_path}"
        except asyncssh.KeyImportError as exc:
            raise ConnectionError(
                "SFTP connection failed: " + self._format_key_import_error(str(exc), is_ppk=False)
            ) from exc

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        import asyncssh

        self._connected = False
        self._conn = None
        self._sftp = None

        try:
            connect_kwargs: dict[str, object] = {
                "host": self._info.host,
                "port": self._info.effective_port,
                "username": self._info.username,
                "login_timeout": self._info.timeout,
            }

            # --- Host key policy ---
            if self._info.host_key_policy == HostKeyPolicy.AUTO_ADD:
                connect_kwargs["known_hosts"] = None
                logger.debug("SFTP host key policy: auto-add (known_hosts=None)")
            elif self._info.host_key_policy == HostKeyPolicy.STRICT:
                # Use default known_hosts (system files)
                logger.debug("SFTP host key policy: strict (system known_hosts)")
            elif self._info.host_key_policy == HostKeyPolicy.PROMPT:
                from portkeydrop.portable import get_config_dir

                known_hosts = get_config_dir() / "known_hosts"
                known_hosts.parent.mkdir(parents=True, exist_ok=True)
                if known_hosts.exists():
                    connect_kwargs["known_hosts"] = str(known_hosts)
                else:
                    connect_kwargs["known_hosts"] = None
                logger.debug("SFTP host key policy: prompt (known_hosts=%s)", known_hosts)
            else:
                raise ConnectionError(
                    f"SFTP connection failed: unknown host key policy "
                    f"'{self._info.host_key_policy}'."
                )

            # --- Authentication ---
            auth_methods: list[str] = ["ssh-agent", "default-key-files"]
            if self._info.key_path:
                key_path = os.path.expanduser(self._info.key_path)
                if not os.path.exists(key_path):
                    raise ConnectionError(
                        f"SFTP connection failed: key file not found: {self._info.key_path}"
                    )
                passphrase = self._info.password if self._info.password else None
                key_obj, auth_label = self._load_client_key(key_path, passphrase)
                connect_kwargs["client_keys"] = [key_obj]
                connect_kwargs["agent_path"] = None  # disable agent
                auth_methods = [auth_label]
            elif self._info.password:
                connect_kwargs["password"] = self._info.password
                auth_methods.append("password")

            logger.debug("SFTP authentication methods to try: %s", ", ".join(auth_methods))

            async def _connect():
                conn = await asyncssh.connect(**connect_kwargs)
                sftp = await conn.start_sftp_client()
                return conn, sftp

            self._conn, self._sftp = self._run(_connect())
            if self._sftp is None:
                raise ConnectionError("Failed to create SFTP session after SSH authentication")

            self._cwd = self._run(self._sftp.realpath("."))
            self._connected = True
            logger.debug("SSH authentication succeeded using one of: %s", ", ".join(auth_methods))

        except ConnectionError:
            raise
        except asyncssh.KeyExchangeFailed as e:
            logger.error("Host key verification failed for %s: %s", self._info.host, e)
            raise ConnectionError(
                f"SFTP connection failed: host key verification failed for {self._info.host}. "
                "Verify the server host key or adjust host key policy."
            ) from e
        except asyncssh.KeyImportError as e:
            error_text = str(e)
            key_import_message = self._format_key_import_error(error_text)
            logger.error("Failed to import private key: %s", e)
            raise ConnectionError(f"SFTP connection failed: {key_import_message}") from e
        except asyncssh.PermissionDenied as e:
            logger.error(
                "SFTP authentication failed for %s. Methods attempted: %s",
                self._info.host,
                auth_methods,
            )
            if self._info.key_path:
                message = (
                    f"Authentication failed with key file '{self._info.key_path}'. "
                    "Check key permissions, passphrase, and server authorized_keys."
                )
            elif self._info.password:
                message = (
                    "Authentication failed after trying SSH agent, default key files, "
                    "and password. "
                    "Ensure your agent has the right key loaded or verify username/password."
                )
            else:
                message = (
                    "Authentication failed using SSH agent/default key files. "
                    "Start your SSH agent and load a key, or provide a password/private "
                    "key path."
                )
            raise ConnectionError(f"SFTP connection failed: {message}") from e
        except asyncssh.ConnectionLost as e:
            logger.error(
                "Could not reach SSH service at %s:%s: %s",
                self._info.host,
                self._info.effective_port,
                e,
            )
            raise ConnectionError(
                f"SFTP connection failed: could not connect to "
                f"{self._info.host}:{self._info.effective_port}. "
                "Verify host/port and that the SSH service is running."
            ) from e
        except asyncssh.DisconnectError as e:
            error_text = str(e)
            if "agent" in error_text.lower():
                logger.warning("SSH agent appears unavailable or inaccessible: %s", e)
                raise ConnectionError(
                    "SFTP connection failed: SSH agent is unavailable or inaccessible. "
                    "Start the agent (or 1Password/Bitwarden integration), then retry; "
                    "or use password/private key file authentication."
                ) from e
            logger.error("SSH protocol error during SFTP connect: %s", e)
            raise ConnectionError(f"SFTP connection failed: SSH negotiation failed: {e}") from e
        except OSError as e:
            logger.error(
                "Could not reach SSH service at %s:%s: %s",
                self._info.host,
                self._info.effective_port,
                e,
            )
            raise ConnectionError(
                f"SFTP connection failed: could not connect to "
                f"{self._info.host}:{self._info.effective_port}. "
                "Verify host/port and that the SSH service is running."
            ) from e
        except Exception as e:
            logger.error("Unexpected SFTP connection failure: %s", e)
            raise ConnectionError(f"SFTP connection failed: {e}") from e

    @staticmethod
    def _format_key_import_error(
        error_text: str,
        *,
        is_ppk: bool,
        ppk_variant: str = "PPK",
    ) -> str:
        reason = error_text.strip() or "unknown parse error"
        text = error_text.lower()
        if is_ppk:
            if "dmp1 must be odd" in text or "dmq1 must be odd" in text:
                return (
                    f"could not import {ppk_variant} private key. "
                    "Converted RSA key material is malformed (invalid CRT parameters). "
                    "Re-export this key in PuTTYgen as OpenSSH private key "
                    "(Conversions -> Export OpenSSH key), or regenerate the RSA key pair."
                )
            if "hmac mismatch" in text:
                return (
                    f"could not import {ppk_variant} private key ({reason}). "
                    "The supplied passphrase is incorrect for this PPK. Enter the correct "
                    "passphrase, or re-export as OpenSSH private key."
                )
            if any(token in text for token in ("passphrase", "decrypt", "wrong", "unable to load")):
                return (
                    f"could not import {ppk_variant} private key ({reason}). "
                    "The key is likely encrypted or the passphrase is incorrect. "
                    "Enter the key passphrase, or re-export as OpenSSH private key."
                )
            if "not installed" in text and "puttykeys" in text:
                return (
                    f"could not import {ppk_variant} private key ({reason}). "
                    "Install the required `puttykeys` package in this runtime environment, "
                    "or re-export this key in PuTTYgen as OpenSSH private key "
                    "(Conversions -> Export OpenSSH key)."
                )
            if "unsupported ppk variant" in text:
                return (
                    f"could not import {ppk_variant} private key ({reason}). "
                    "This PPK variant is not supported by puttykeys. "
                    "Re-export this exact key in PuTTYgen as OpenSSH private key "
                    "(Conversions -> Export OpenSSH key), then use that file."
                )
            return (
                f"could not import {ppk_variant} private key ({reason}). "
                "Direct parsing failed. Re-export this exact key in PuTTYgen as OpenSSH "
                "private key (Conversions -> Export OpenSSH key) and retry."
            )

        if any(token in text for token in ("passphrase", "encrypted", "decrypt", "incorrect")):
            return (
                f"the private key requires a passphrase ({reason}). "
                "Provide the key passphrase or use an SSH agent/password."
            )
        if any(token in text for token in ("invalid", "unsupported", "format", "malformed")):
            return (
                f"the private key format is invalid or unsupported ({reason}). "
                "Use a valid OpenSSH/PKCS#8/PPK key file."
            )
        return (
            f"could not import the private key ({reason}). "
            "Verify the key file, passphrase, and key format."
        )

    def disconnect(self) -> None:
        if self._sftp:
            try:
                self._sftp.exit()
            except Exception:
                pass
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._sftp = None
        self._conn = None
        self._connected = False

    # ------------------------------------------------------------------
    # Directory operations
    # ------------------------------------------------------------------

    def list_dir(self, path: str = ".") -> list[RemoteFile]:
        sftp = self._ensure_connected()
        target = (path if path != "." else self._cwd).rstrip("/") or "/"
        files: list[RemoteFile] = []
        logger.debug("list_dir: requesting entries for '%s'", target)

        async def _readdir_safe():
            """Readdir loop that treats consecutive empty responses as EOF.

            Some SFTP servers (e.g. Bitvise on the .ssh directory) return
            FXP_NAME with count=0 indefinitely instead of FX_EOF. asyncssh
            loops forever in this case; we break after 3 consecutive empty
            batches — matching WinSCP behaviour.
            """
            import asyncssh as _asyncssh

            _MAX_EMPTY = 3
            dirpath = sftp.compose_path(target)
            handle = await sftp._handler.opendir(dirpath)
            result = []
            consecutive_empty = 0
            at_end = False
            try:
                while not at_end:
                    names, at_end = await sftp._handler.readdir(handle)
                    if not names:
                        consecutive_empty += 1
                        logger.debug(
                            "_readdir_safe: empty batch %d for '%s'", consecutive_empty, target
                        )
                        if consecutive_empty >= _MAX_EMPTY:
                            logger.warning(
                                "_readdir_safe: treating %d consecutive empty batches as EOF for '%s'",
                                _MAX_EMPTY,
                                target,
                            )
                            break
                    else:
                        consecutive_empty = 0
                        # Decode filenames from bytes → str (same as asyncssh scandir does
                        # internally when called with a str path).
                        for entry in names:
                            if entry.filename and isinstance(entry.filename, (bytes, bytearray)):
                                entry.filename = sftp.decode(entry.filename)
                            if entry.longname and isinstance(entry.longname, (bytes, bytearray)):
                                entry.longname = sftp.decode(entry.longname)
                        result.extend(names)
            except _asyncssh.SFTPEOFError:
                pass
            finally:
                await sftp._handler.close(handle)
            return result

        try:
            entries = self._run(_readdir_safe())
            logger.debug(
                "list_dir: readdir returned %d raw entries for '%s'",
                len(entries) if entries is not None else -1,
                target,
            )
        except PermissionError:
            raise
        except OSError as e:
            import errno as _errno

            if e.errno in (_errno.EACCES, _errno.EPERM):
                raise PermissionError(f"Permission denied: cannot list '{target}'") from e
            raise
        except Exception as e:
            # asyncssh raises SFTPError (not OSError) for server-side errors.
            # Map permission errors; surface everything else.
            import asyncssh as _asyncssh

            if isinstance(e, _asyncssh.SFTPError):
                logger.warning(
                    "list_dir: SFTPError for '%s': code=%s msg=%s",
                    target,
                    getattr(e, "code", "?"),
                    e,
                )
                if getattr(e, "code", None) in (3, 4):  # FX_PERMISSION_DENIED=3, FX_FAILURE=4
                    raise PermissionError(f"Permission denied: cannot list '{target}'") from e
            raise
        logger.debug("list_dir: got %d entries for '%s'", len(entries), target)
        for entry in entries:
            name = entry.filename
            if name in (".", ".."):
                continue
            attrs = entry.attrs
            mode = attrs.permissions
            # Skip special files (sockets, FIFOs, devices)
            if mode is not None and (
                stat.S_ISSOCK(mode)
                or stat.S_ISFIFO(mode)
                or stat.S_ISBLK(mode)
                or stat.S_ISCHR(mode)
            ):
                logger.debug("Skipping special file: %s (mode=%s)", name, oct(mode))
                continue
            is_dir = bool(mode is not None and stat.S_ISDIR(mode))
            full_path = f"{target.rstrip('/')}/{name}"
            # SFTP v4+ file type field (separate from permissions) — used by
            # strict servers like Bitvise that may not embed the type in the
            # permission bits.
            sftp_type = getattr(attrs, "type", None)
            is_link = bool(mode is not None and stat.S_ISLNK(mode))
            if not is_link and sftp_type == _SFTP_TYPE_SYMLINK:
                is_link = True
            if is_link:
                try:
                    target_attrs = self._run(sftp.stat(full_path))
                    if target_attrs.permissions is not None and stat.S_ISDIR(
                        target_attrs.permissions
                    ):
                        is_dir = True
                    elif getattr(target_attrs, "type", None) == _SFTP_TYPE_DIRECTORY:
                        is_dir = True
                except Exception:
                    pass
            # Fallback: use SFTP v4+ type field when permissions lack type bits
            if not is_dir and sftp_type == _SFTP_TYPE_DIRECTORY:
                is_dir = True
            longname = getattr(entry, "longname", "")
            if not is_dir and longname and longname.startswith("d"):
                is_dir = True
            logger.debug(
                "listdir entry: %s mode=%s is_link=%s is_dir=%s longname=%r",
                name,
                oct(mode) if mode is not None else None,
                is_link,
                is_dir,
                longname,
            )
            mtime = attrs.mtime
            modified = datetime.fromtimestamp(mtime) if mtime else None
            perms = stat.filemode(mode) if mode else ""
            files.append(
                RemoteFile(
                    name=name,
                    path=full_path,
                    size=attrs.size or 0,
                    is_dir=is_dir,
                    modified=modified,
                    permissions=perms,
                    owner=str(attrs.uid or ""),
                    group=str(attrs.gid or ""),
                )
            )
        return files

    def chdir(self, path: str) -> str:
        logger.debug("chdir: '%s'", path)
        sftp = self._ensure_connected()
        try:
            resolved = self._run(sftp.realpath(path))
            # Validate the target is a directory (strict servers like Bitvise
            # require an explicit stat check — realpath only canonicalises).
            attrs = self._run(sftp.stat(resolved))
            logger.debug(
                "chdir stat: path='%s' permissions=%s type=%s",
                resolved,
                attrs.permissions,
                getattr(attrs, "type", None),
            )
            is_dir = False
            if attrs.permissions is not None and stat.S_ISDIR(attrs.permissions):
                is_dir = True
            elif getattr(attrs, "type", None) == _SFTP_TYPE_DIRECTORY:
                is_dir = True
            elif attrs.permissions is None and getattr(attrs, "type", None) is None:
                # Server returned no type info (e.g. Bitvise on .ssh) —
                # assume directory and let the server reject if wrong.
                logger.debug(
                    "chdir: no type info from server, assuming directory for '%s'", resolved
                )
                is_dir = True
            if not is_dir:
                raise NotADirectoryError(f"Not a directory: '{path}'")
            self._cwd = resolved
            logger.debug("chdir: done, cwd='%s'", self._cwd)
        except (NotADirectoryError, PermissionError):
            raise
        except OSError as e:
            import errno as _errno

            if e.errno in (_errno.EACCES, _errno.EPERM):
                raise PermissionError(f"Permission denied: cannot access '{path}'") from e
            raise
        return self._cwd

    # ------------------------------------------------------------------
    # Transfer operations
    # ------------------------------------------------------------------

    def download(
        self, remote_path: str, local_file: BinaryIO, callback: ProgressCallback | None = None
    ) -> None:
        sftp = self._ensure_connected()
        local_path = getattr(local_file, "name", None)

        # Resolve symlinks so stat() returns the real file size
        try:
            resolved = self._run(sftp.realpath(remote_path))
        except Exception:
            resolved = remote_path

        if isinstance(local_path, str) and os.path.isabs(local_path):
            # asyncssh native get() — pipelined reads with progress reporting
            local_file.close()

            async def _download():
                handler = None
                if callback:

                    def handler(srcpath, dstpath, copied, total):
                        callback(copied, total)

                await sftp.get(resolved, local_path, progress_handler=handler)

            self._run(_download())
        else:
            # Fallback for in-memory streams (BytesIO, etc.)
            async def _download():
                async with sftp.open(resolved, "rb") as rf:
                    total = (await sftp.stat(resolved)).size or 0
                    transferred = 0
                    while True:
                        chunk = await rf.read(8192)
                        if not chunk:
                            break
                        local_file.write(chunk)
                        transferred += len(chunk)
                        if callback:
                            callback(transferred, total)

            self._run(_download())

    def upload(
        self, local_file: BinaryIO, remote_path: str, callback: ProgressCallback | None = None
    ) -> None:
        sftp = self._ensure_connected()
        local_path = getattr(local_file, "name", None)

        if isinstance(local_path, str) and os.path.isabs(local_path):
            # asyncssh native put() — pipelined writes with progress reporting
            total = os.path.getsize(local_path)
            local_file.close()

            async def _upload():
                handler = None
                if callback:

                    def handler(srcpath, dstpath, copied, total_bytes):
                        callback(copied, total_bytes)

                await sftp.put(local_path, remote_path, progress_handler=handler)

            self._run(_upload())
        else:
            # Fallback for in-memory streams (BytesIO, etc.)
            local_file.seek(0, 2)
            total = local_file.tell()
            local_file.seek(0)

            async def _upload():
                async with sftp.open(remote_path, "wb") as wf:
                    transferred = 0
                    while True:
                        chunk = local_file.read(8192)
                        if not chunk:
                            break
                        await wf.write(chunk)
                        transferred += len(chunk)
                        if callback:
                            callback(transferred, total)

            self._run(_upload())

        remote_attrs = self._run(sftp.stat(remote_path))
        remote_size = remote_attrs.size or 0
        if remote_size != total:
            raise RuntimeError(
                f"Remote upload verification failed for {remote_path}: expected {total} bytes, "
                f"got {remote_size}."
            )

    # ------------------------------------------------------------------
    # File/dir management
    # ------------------------------------------------------------------

    def delete(self, path: str) -> None:
        sftp = self._ensure_connected()
        self._run(sftp.remove(path))
        try:
            self._run(sftp.stat(path))
        except FileNotFoundError:
            return
        except OSError as exc:
            if getattr(exc, "errno", None) == 2:
                return
            raise
        raise RuntimeError(f"Remote delete verification failed for {path}.")

    def rmdir(self, path: str) -> None:
        sftp = self._ensure_connected()
        self._run(sftp.rmdir(path))
        try:
            self._run(sftp.stat(path))
        except FileNotFoundError:
            return
        except OSError as exc:
            if getattr(exc, "errno", None) == 2:
                return
            raise
        raise RuntimeError(f"Remote directory delete verification failed for {path}.")

    def mkdir(self, path: str) -> None:
        sftp = self._ensure_connected()
        self._run(sftp.mkdir(path))
        attrs = self._run(sftp.stat(path))
        if not attrs.permissions or not stat.S_ISDIR(attrs.permissions):
            raise RuntimeError(f"Remote mkdir verification failed for {path}.")

    def rename(self, old_path: str, new_path: str) -> None:
        sftp = self._ensure_connected()
        self._run(sftp.rename(old_path, new_path))
        self._run(sftp.stat(new_path))

    def stat(self, path: str) -> RemoteFile:
        sftp = self._ensure_connected()
        attrs = self._run(sftp.stat(path))
        mode = attrs.permissions
        is_dir = stat.S_ISDIR(mode) if mode else False
        if not is_dir and getattr(attrs, "type", None) == _SFTP_TYPE_DIRECTORY:
            is_dir = True
        modified = datetime.fromtimestamp(attrs.mtime) if attrs.mtime else None
        perms = stat.filemode(mode) if mode else ""
        name = PurePosixPath(path).name
        return RemoteFile(
            name=name,
            path=path,
            size=attrs.size or 0,
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
