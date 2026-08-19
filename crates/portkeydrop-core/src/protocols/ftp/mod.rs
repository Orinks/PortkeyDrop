//! FTP, FTPS, and FTP-with-explicit-SSL client.
//!
//! One client covers all three because they differ only in when and how TLS is
//! negotiated:
//!
//! * plain FTP — no TLS at all;
//! * explicit FTPS — `AUTH TLS` (or the legacy `AUTH SSL`) upgrades an
//!   already-open control connection;
//! * implicit FTPS — the socket is TLS from the first byte, conventionally on
//!   port 990.
//!
//! Some servers only accept the legacy `AUTH SSL` spelling, which is why the
//! command is configurable rather than fixed.

pub mod listing;
pub mod reply;
mod stream;

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

use chrono::Datelike;
use native_tls::TlsConnector;

use super::model::{ConnectionInfo, Protocol, RemoteFile};
use super::{path, ProgressFn, ProtocolError, Result, TransferClient};
use stream::Stream;

pub use reply::Reply;

/// Chunk size for data-channel transfers.
const TRANSFER_CHUNK: usize = 64 * 1024;

/// Which spelling of the TLS upgrade command to send.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuthCommand {
    /// `AUTH TLS` — RFC 4217, what modern servers expect.
    Tls,
    /// `AUTH SSL` — the legacy spelling some servers still require.
    Ssl,
}

impl AuthCommand {
    fn as_command(self) -> &'static str {
        match self {
            AuthCommand::Tls => "AUTH TLS",
            AuthCommand::Ssl => "AUTH SSL",
        }
    }
}

/// How TLS is applied to a connection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TlsMode {
    /// No encryption.
    None,
    /// Upgrade after connecting, via `AUTH TLS`/`AUTH SSL`.
    Explicit(AuthCommand),
    /// Encrypted from the first byte.
    Implicit,
}

impl TlsMode {
    /// Decide the TLS mode for a connection.
    ///
    /// `ftps` means implicit TLS on the dedicated port, unless the site opted
    /// into the explicit upgrade. Plain `ftp` is unencrypted unless the site
    /// asked for the legacy `AUTH SSL` upgrade.
    pub fn for_connection(info: &ConnectionInfo) -> Self {
        match (info.protocol, info.ftp_explicit_ssl) {
            (Protocol::Ftp, true) => TlsMode::Explicit(AuthCommand::Ssl),
            (Protocol::Ftp, false) => TlsMode::None,
            (Protocol::Ftps, true) => TlsMode::Explicit(AuthCommand::Tls),
            (Protocol::Ftps, false) => TlsMode::Implicit,
            _ => TlsMode::None,
        }
    }
}

/// FTP-family client.
pub struct FtpClient {
    info: ConnectionInfo,
    control: Option<BufReader<Stream>>,
    /// Whether the data channel must also be encrypted (`PROT P` was accepted).
    protect_data: bool,
    connected: bool,
    cwd: String,
    /// Set once the server has proven it understands `MLSD`, so a fallback to
    /// `LIST` is not retried on every listing.
    supports_mlsd: Option<bool>,
}

impl FtpClient {
    /// Build a client. No network activity happens until [`TransferClient::connect`].
    pub fn new(info: ConnectionInfo) -> Self {
        Self {
            info,
            control: None,
            protect_data: false,
            connected: false,
            cwd: "/".to_string(),
            supports_mlsd: None,
        }
    }

    /// The connection parameters this client was built with.
    pub fn info(&self) -> &ConnectionInfo {
        &self.info
    }

    fn control_mut(&mut self) -> Result<&mut BufReader<Stream>> {
        if !self.connected {
            return Err(ProtocolError::NotConnected);
        }
        self.control.as_mut().ok_or(ProtocolError::NotConnected)
    }

    /// Send a command and read its reply.
    fn command(&mut self, command: &str) -> Result<Reply> {
        // A newline inside a command would let a second command be smuggled
        // onto the control channel.
        if command.contains(['\r', '\n']) {
            return Err(ProtocolError::Other(
                "FTP command may not contain a line break".to_string(),
            ));
        }
        let control = self.control_mut()?;
        log::debug!("ftp > {}", redact(command));
        control
            .get_mut()
            .write_all(format!("{command}\r\n").as_bytes())?;
        control.get_mut().flush()?;
        read_reply(control)
    }

    /// Send a command and require a positive reply.
    fn command_ok(&mut self, command: &str) -> Result<Reply> {
        let reply = self.command(command)?;
        if reply.is_positive() {
            return Ok(reply);
        }
        Err(map_reply_error(&reply, command))
    }

    /// Open a data connection using passive mode.
    ///
    /// `EPSV` is tried first because it works over IPv6 and behind NAT; servers
    /// that reject it fall back to `PASV`.
    fn open_data_connection(&mut self) -> Result<Stream> {
        let (host, port) = match self.command("EPSV") {
            Ok(reply) if reply.is_positive() => match reply::parse_epsv(&reply.text) {
                // EPSV returns only a port: reuse the control connection's host.
                Some(port) => (self.control_host()?, port),
                None => self.passive_endpoint()?,
            },
            _ => self.passive_endpoint()?,
        };

        let socket = connect_timeout(&host, port, self.info.timeout)?;
        if self.protect_data {
            let session = tls_connector()?
                .connect(&self.info.host, socket)
                .map_err(|err| {
                    ProtocolError::Connection(format!("data channel TLS failed: {err}"))
                })?;
            Ok(Stream::Tls(Box::new(session)))
        } else {
            Ok(Stream::Plain(socket))
        }
    }

    /// Fall back to `PASV` for the data endpoint.
    fn passive_endpoint(&mut self) -> Result<(String, u16)> {
        let reply = self.command_ok("PASV")?;
        let (host, port) = reply::parse_pasv(&reply.text).ok_or_else(|| {
            ProtocolError::Other(format!(
                "could not parse passive reply: {}",
                reply.summary()
            ))
        })?;
        // A server behind NAT may advertise a private address; the control
        // connection's peer is the address that actually works.
        let control_host = self.control_host()?;
        if is_private_or_unroutable(&host) && !is_private_or_unroutable(&control_host) {
            log::debug!("ftp: PASV advertised {host}; using control host {control_host}");
            return Ok((control_host, port));
        }
        Ok((host, port))
    }

    /// The address the control connection is talking to.
    fn control_host(&mut self) -> Result<String> {
        let control = self.control_mut()?;
        let peer = control.get_ref().socket().peer_addr()?;
        Ok(peer.ip().to_string())
    }

    /// Read a whole data-channel response as text (used by `LIST` and `MLSD`).
    fn read_data_text(&mut self, command: &str) -> Result<String> {
        let mut data = self.open_data_connection()?;
        let reply = self.command(command)?;
        if !reply.is_positive() && !reply.is_preliminary() {
            return Err(map_reply_error(&reply, command));
        }

        let mut body = Vec::new();
        data.read_to_end(&mut body)?;
        drop(data);

        // The server sends a completion reply once the data channel closes.
        self.read_transfer_completion(command)?;
        Ok(String::from_utf8_lossy(&body).into_owned())
    }

    /// Consume the `226`/`250` reply that follows a completed transfer.
    fn read_transfer_completion(&mut self, command: &str) -> Result<()> {
        let control = self.control_mut()?;
        let reply = read_reply(control)?;
        if reply.is_positive() {
            return Ok(());
        }
        Err(map_reply_error(&reply, command))
    }

    /// Whether a path exists, using `MLST` and falling back to `SIZE`/`CWD`.
    fn path_exists(&mut self, remote_path: &str) -> bool {
        if self
            .command(&format!("MLST {remote_path}"))
            .is_ok_and(|reply| reply.is_positive())
        {
            return true;
        }
        if self
            .command(&format!("SIZE {remote_path}"))
            .is_ok_and(|reply| reply.is_positive())
        {
            return true;
        }
        // A directory has no size; probing with CWD covers that case. The
        // current directory is restored afterwards so this stays side-effect
        // free.
        let saved = self.cwd.clone();
        let exists = self
            .command(&format!("CWD {remote_path}"))
            .is_ok_and(|reply| reply.is_positive());
        if exists {
            let _ = self.command(&format!("CWD {saved}"));
        }
        exists
    }

    /// Whether a path is a directory.
    fn is_directory(&mut self, remote_path: &str) -> bool {
        if let Ok(reply) = self.command(&format!("MLST {remote_path}")) {
            if reply.is_positive() {
                return reply.text.to_ascii_lowercase().contains("type=dir");
            }
        }
        let saved = self.cwd.clone();
        let is_dir = self
            .command(&format!("CWD {remote_path}"))
            .is_ok_and(|reply| reply.is_positive());
        if is_dir {
            let _ = self.command(&format!("CWD {saved}"));
        }
        is_dir
    }

    /// Negotiate TLS on the control channel and require protected data.
    fn upgrade_to_tls(&mut self, auth: AuthCommand) -> Result<()> {
        let reply = self.command(auth.as_command())?;
        if !reply.is_positive() {
            return Err(ProtocolError::Connection(format!(
                "server rejected {}: {}",
                auth.as_command(),
                reply.summary()
            )));
        }

        // Swap the plaintext socket for a TLS session over the same socket.
        let control = self.control.take().ok_or(ProtocolError::NotConnected)?;
        let socket = match control.into_inner() {
            Stream::Plain(socket) => socket,
            // Already encrypted: nothing further to do.
            already @ Stream::Tls(_) => {
                self.control = Some(BufReader::new(already));
                return Ok(());
            }
        };
        let session = tls_connector()?
            .connect(&self.info.host, socket)
            .map_err(|err| ProtocolError::Connection(format!("TLS handshake failed: {err}")))?;
        self.control = Some(BufReader::new(Stream::Tls(Box::new(session))));

        // Protect the data channel too. Without PROT P the control channel is
        // encrypted but file contents travel in the clear.
        self.command_ok("PBSZ 0")?;
        self.command_ok("PROT P")?;
        self.protect_data = true;
        Ok(())
    }
}

/// Build a TLS connector for the control and data channels.
fn tls_connector() -> Result<TlsConnector> {
    TlsConnector::new()
        .map_err(|err| ProtocolError::Connection(format!("could not initialise TLS: {err}")))
}

/// Connect with a timeout, trying every address the host resolves to.
fn connect_timeout(host: &str, port: u16, timeout_secs: u64) -> Result<TcpStream> {
    let timeout = Duration::from_secs(timeout_secs.max(1));
    let addresses: Vec<_> = (host, port)
        .to_socket_addrs()
        .map_err(|err| ProtocolError::Connection(format!("could not resolve {host}: {err}")))?
        .collect();
    if addresses.is_empty() {
        return Err(ProtocolError::Connection(format!(
            "{host} resolved to no addresses"
        )));
    }

    let mut last_error = None;
    for address in addresses {
        match TcpStream::connect_timeout(&address, timeout) {
            Ok(socket) => {
                socket.set_read_timeout(Some(timeout)).ok();
                socket.set_write_timeout(Some(timeout)).ok();
                socket.set_nodelay(true).ok();
                return Ok(socket);
            }
            Err(err) => last_error = Some(err),
        }
    }
    Err(ProtocolError::Connection(format!(
        "could not connect to {host}:{port}: {}",
        last_error.map(|err| err.to_string()).unwrap_or_default()
    )))
}

/// Read one complete reply from the control channel.
fn read_reply(control: &mut BufReader<Stream>) -> Result<Reply> {
    let mut builder = reply::ReplyBuilder::new();
    loop {
        let mut line = Vec::new();
        let read = control.read_until(b'\n', &mut line)?;
        if read == 0 {
            return Err(ProtocolError::Connection(
                "the server closed the connection unexpectedly".to_string(),
            ));
        }
        let text = String::from_utf8_lossy(&line);
        log::debug!("ftp < {}", text.trim_end());
        if let Some(reply) = builder.push(&text) {
            return Ok(reply);
        }
    }
}

/// Hide the argument of a `PASS` command in logs.
fn redact(command: &str) -> String {
    if command.len() >= 4 && command[..4].eq_ignore_ascii_case("PASS") {
        "PASS ******".to_string()
    } else {
        command.to_string()
    }
}

/// Map an FTP failure reply onto a protocol error.
///
/// 550 covers both "no such file" and "permission denied", so the reply text
/// decides which one the user is told about.
fn map_reply_error(reply: &Reply, command: &str) -> ProtocolError {
    let text = reply.text.to_ascii_lowercase();
    let target = command
        .split_once(' ')
        .map(|(_, rest)| rest)
        .unwrap_or(command);
    match reply.code {
        530 => ProtocolError::Connection(format!("authentication failed: {}", reply.summary())),
        550 if text.contains("permission")
            || text.contains("denied")
            || text.contains("access") =>
        {
            ProtocolError::PermissionDenied(target.to_string())
        }
        550 if text.contains("not a directory") => ProtocolError::NotADirectory(target.to_string()),
        550 | 450 => ProtocolError::NotFound(target.to_string()),
        _ => ProtocolError::Other(reply.summary()),
    }
}

/// Whether an address is one the server cannot have meant for us to dial.
///
/// Used to spot NAT-mangled `PASV` replies.
fn is_private_or_unroutable(host: &str) -> bool {
    let Ok(ip) = host.parse::<std::net::IpAddr>() else {
        return false;
    };
    match ip {
        std::net::IpAddr::V4(v4) => {
            v4.is_private() || v4.is_loopback() || v4.is_link_local() || v4.is_unspecified()
        }
        std::net::IpAddr::V6(v6) => v6.is_loopback() || v6.is_unspecified(),
    }
}

/// Copy bytes between channels, reporting progress and honouring cancellation.
fn pump(
    source: &mut dyn Read,
    sink: &mut dyn Write,
    total: u64,
    mut progress: Option<ProgressFn<'_>>,
) -> Result<u64> {
    let mut buffer = vec![0u8; TRANSFER_CHUNK];
    let mut transferred = 0u64;
    loop {
        let read = source.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        sink.write_all(&buffer[..read])?;
        transferred += read as u64;
        if let Some(report) = progress.as_deref_mut() {
            report(transferred, total)?;
        }
    }
    sink.flush()?;
    Ok(transferred)
}

impl TransferClient for FtpClient {
    fn protocol(&self) -> Protocol {
        self.info.protocol
    }

    fn is_connected(&self) -> bool {
        self.connected
    }

    fn cwd(&self) -> &str {
        &self.cwd
    }

    fn connect(&mut self) -> Result<()> {
        self.connected = false;
        self.protect_data = false;
        self.supports_mlsd = None;

        let tls_mode = TlsMode::for_connection(&self.info);
        let socket = connect_timeout(
            &self.info.host,
            self.info.effective_port(),
            self.info.timeout,
        )
        .map_err(|err| ProtocolError::connection(self.info.protocol, err))?;

        let stream = if tls_mode == TlsMode::Implicit {
            let session = tls_connector()?
                .connect(&self.info.host, socket)
                .map_err(|err| {
                    ProtocolError::connection(
                        self.info.protocol,
                        format!("TLS handshake failed: {err}"),
                    )
                })?;
            self.protect_data = true;
            Stream::Tls(Box::new(session))
        } else {
            Stream::Plain(socket)
        };

        self.control = Some(BufReader::new(stream));
        // The client counts as connected from here so `command` will run; a
        // failure below resets it.
        self.connected = true;

        let result = (|| -> Result<()> {
            let greeting = {
                let control = self.control_mut()?;
                read_reply(control)?
            };
            if !greeting.is_positive() {
                return Err(ProtocolError::Connection(format!(
                    "server refused the connection: {}",
                    greeting.summary()
                )));
            }

            if let TlsMode::Explicit(auth) = tls_mode {
                self.upgrade_to_tls(auth)?;
            }

            let user = if self.info.username.is_empty() {
                "anonymous"
            } else {
                &self.info.username
            };
            let reply = self.command(&format!("USER {user}"))?;
            if !reply.is_positive() {
                return Err(map_reply_error(&reply, "USER"));
            }
            // 331 means the server wants a password next; 230 means it does not.
            if reply.code == 331 {
                let password = if self.info.password.is_empty() {
                    "anonymous@"
                } else {
                    &self.info.password
                };
                let reply = self.command(&format!("PASS {password}"))?;
                if !reply.is_positive() {
                    return Err(map_reply_error(&reply, "PASS"));
                }
            }

            // Implicit FTPS is already encrypted end to end, but the data
            // channel still needs PROT P to be requested explicitly.
            if tls_mode == TlsMode::Implicit {
                let _ = self.command("PBSZ 0");
                if self
                    .command("PROT P")
                    .is_ok_and(|reply| reply.is_positive())
                {
                    self.protect_data = true;
                }
            }

            // Binary transfers: text mode would corrupt every non-text file.
            self.command_ok("TYPE I")?;

            let reply = self.command_ok("PWD")?;
            self.cwd = reply::parse_pathname(&reply.text).unwrap_or_else(|| "/".to_string());
            Ok(())
        })();

        if let Err(err) = result {
            self.disconnect();
            return Err(match err {
                ProtocolError::Connection(message) => {
                    ProtocolError::connection(self.info.protocol, message)
                }
                other => ProtocolError::connection(self.info.protocol, other),
            });
        }
        Ok(())
    }

    fn disconnect(&mut self) {
        if self.connected {
            let _ = self.command("QUIT");
        }
        if let Some(control) = self.control.take() {
            let _ = control
                .get_ref()
                .socket()
                .shutdown(std::net::Shutdown::Both);
        }
        self.connected = false;
        self.protect_data = false;
    }

    fn list_dir(&mut self, remote_path: &str) -> Result<Vec<RemoteFile>> {
        let target = path::resolve(&self.cwd, remote_path);

        if self.supports_mlsd != Some(false) {
            match self.read_data_text(&format!("MLSD {target}")) {
                Ok(body) => {
                    self.supports_mlsd = Some(true);
                    return Ok(listing::parse_mlsd(&body, &target));
                }
                Err(err) if self.supports_mlsd.is_none() => {
                    log::debug!("ftp: MLSD unavailable ({err}); falling back to LIST");
                    self.supports_mlsd = Some(false);
                }
                Err(err) => return Err(err),
            }
        }

        let body = self.read_data_text(&format!("LIST {target}"))?;
        let year = chrono::Local::now().year();
        Ok(listing::parse_list(&body, &target, year))
    }

    fn chdir(&mut self, remote_path: &str) -> Result<String> {
        let target = path::resolve(&self.cwd, remote_path);
        self.command_ok(&format!("CWD {target}"))?;
        let reply = self.command_ok("PWD")?;
        self.cwd = reply::parse_pathname(&reply.text).unwrap_or(target);
        Ok(self.cwd.clone())
    }

    fn download(
        &mut self,
        remote_path: &str,
        sink: &mut dyn Write,
        progress: Option<ProgressFn<'_>>,
        offset: u64,
    ) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        let total = self
            .command(&format!("SIZE {target}"))
            .ok()
            .filter(|reply| reply.is_positive())
            .and_then(|reply| reply::parse_size(&reply.text))
            .unwrap_or(0);

        let mut data = self.open_data_connection()?;

        // REST must immediately precede RETR, after the data connection exists.
        if offset > 0 {
            let reply = self.command(&format!("REST {offset}"))?;
            if !reply.is_positive() {
                return Err(ProtocolError::Unsupported(format!(
                    "the server refused to resume this download: {}",
                    reply.summary()
                )));
            }
        }

        let reply = self.command(&format!("RETR {target}"))?;
        if !reply.is_positive() && !reply.is_preliminary() {
            return Err(map_reply_error(&reply, &format!("RETR {target}")));
        }

        // Progress counts the resumed portion only, so subtract the offset.
        let remaining = total.saturating_sub(offset);
        let result = pump(&mut data, sink, remaining, progress);
        drop(data);

        match result {
            Ok(_) => self.read_transfer_completion(&format!("RETR {target}")),
            Err(err) => {
                // Tell the server to stop before surfacing a cancellation, so
                // the control channel is left usable.
                if err.is_cancelled() {
                    let _ = self.command("ABOR");
                    let _ = self.read_transfer_completion("ABOR");
                }
                Err(err)
            }
        }
    }

    fn upload(
        &mut self,
        source: &mut dyn Read,
        total_bytes: u64,
        remote_path: &str,
        progress: Option<ProgressFn<'_>>,
    ) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        let mut data = self.open_data_connection()?;

        let reply = self.command(&format!("STOR {target}"))?;
        if !reply.is_positive() && !reply.is_preliminary() {
            return Err(map_reply_error(&reply, &format!("STOR {target}")));
        }

        let result = pump(source, &mut data, total_bytes, progress);
        // Closing the data channel is what signals end-of-file to the server.
        let _ = data.shutdown_write();
        drop(data);

        let written = match result {
            Ok(written) => written,
            Err(err) => {
                if err.is_cancelled() {
                    let _ = self.command("ABOR");
                    let _ = self.read_transfer_completion("ABOR");
                }
                return Err(err);
            }
        };
        self.read_transfer_completion(&format!("STOR {target}"))?;

        // Confirm the server actually stored every byte. A silently truncated
        // upload would otherwise be reported as a success.
        let remote_size = self
            .command(&format!("SIZE {target}"))
            .ok()
            .filter(|reply| reply.is_positive())
            .and_then(|reply| reply::parse_size(&reply.text));
        match remote_size {
            Some(size) if size == written => Ok(()),
            Some(size) => Err(ProtocolError::Verification(format!(
                "Remote upload verification failed for {target}: expected {written} bytes, got {size}."
            ))),
            // A server without SIZE support cannot be checked; the transfer
            // completed cleanly, so accept it.
            None => Ok(()),
        }
    }

    fn delete(&mut self, remote_path: &str) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        self.command_ok(&format!("DELE {target}"))?;
        if self.path_exists(&target) {
            return Err(ProtocolError::Verification(format!(
                "Remote delete verification failed for {target}."
            )));
        }
        Ok(())
    }

    fn rmdir(&mut self, remote_path: &str) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        self.command_ok(&format!("RMD {target}"))?;
        if self.path_exists(&target) {
            return Err(ProtocolError::Verification(format!(
                "Remote directory delete verification failed for {target}."
            )));
        }
        Ok(())
    }

    fn mkdir(&mut self, remote_path: &str) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        self.command_ok(&format!("MKD {target}"))?;
        if !self.is_directory(&target) {
            return Err(ProtocolError::Verification(format!(
                "Remote mkdir verification failed for {target}."
            )));
        }
        Ok(())
    }

    fn rename(&mut self, old_path: &str, new_path: &str) -> Result<()> {
        let from = path::resolve(&self.cwd, old_path);
        let to = path::resolve(&self.cwd, new_path);
        // RNFR must be answered with 350 before RNTO is accepted.
        let reply = self.command(&format!("RNFR {from}"))?;
        if !reply.is_positive() {
            return Err(map_reply_error(&reply, &format!("RNFR {from}")));
        }
        self.command_ok(&format!("RNTO {to}"))?;
        if !self.path_exists(&to) {
            return Err(ProtocolError::Verification(format!(
                "Remote rename verification failed for {to}."
            )));
        }
        Ok(())
    }

    fn stat(&mut self, remote_path: &str) -> Result<RemoteFile> {
        let target = path::resolve(&self.cwd, remote_path);

        // MLST gives type, size, and time in one round trip when available.
        if let Ok(reply) = self.command(&format!("MLST {target}")) {
            if reply.is_positive() {
                // The fact line is the indented middle line of the reply.
                if let Some(fact_line) = reply.text.lines().nth(1) {
                    if let Some(entry) =
                        listing::parse_mlsd_line(fact_line.trim_start(), &path::parent(&target))
                    {
                        return Ok(entry);
                    }
                }
            }
        }

        let size = self
            .command(&format!("SIZE {target}"))
            .ok()
            .filter(|reply| reply.is_positive())
            .and_then(|reply| reply::parse_size(&reply.text))
            .unwrap_or(0);
        let modified = self
            .command(&format!("MDTM {target}"))
            .ok()
            .filter(|reply| reply.is_positive())
            .and_then(|reply| reply::parse_mdtm(&reply.text));

        Ok(RemoteFile {
            name: path::file_name(&target).to_string(),
            path: target.clone(),
            size,
            is_dir: self.is_directory(&target),
            modified,
            permissions: String::new(),
            owner: String::new(),
            group: String::new(),
        })
    }
}

impl Drop for FtpClient {
    fn drop(&mut self) {
        self.disconnect();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn info(protocol: Protocol, explicit_ssl: bool) -> ConnectionInfo {
        ConnectionInfo {
            protocol,
            host: "example.com".into(),
            ftp_explicit_ssl: explicit_ssl,
            ..Default::default()
        }
    }

    #[test]
    fn plain_ftp_uses_no_tls() {
        assert_eq!(
            TlsMode::for_connection(&info(Protocol::Ftp, false)),
            TlsMode::None
        );
    }

    #[test]
    fn ftp_with_explicit_ssl_uses_the_legacy_auth_command() {
        // This is the whole reason the command is configurable: some servers
        // only accept the AUTH SSL spelling.
        assert_eq!(
            TlsMode::for_connection(&info(Protocol::Ftp, true)),
            TlsMode::Explicit(AuthCommand::Ssl)
        );
    }

    #[test]
    fn ftps_defaults_to_implicit_tls() {
        assert_eq!(
            TlsMode::for_connection(&info(Protocol::Ftps, false)),
            TlsMode::Implicit
        );
    }

    #[test]
    fn ftps_with_the_explicit_flag_upgrades_with_auth_tls() {
        assert_eq!(
            TlsMode::for_connection(&info(Protocol::Ftps, true)),
            TlsMode::Explicit(AuthCommand::Tls)
        );
    }

    #[test]
    fn auth_commands_use_their_wire_spelling() {
        assert_eq!(AuthCommand::Tls.as_command(), "AUTH TLS");
        assert_eq!(AuthCommand::Ssl.as_command(), "AUTH SSL");
    }

    #[test]
    fn a_new_client_is_disconnected_at_the_root() {
        let client = FtpClient::new(info(Protocol::Ftp, false));
        assert!(!client.is_connected());
        assert_eq!(client.cwd(), "/");
        assert_eq!(client.protocol(), Protocol::Ftp);
    }

    #[test]
    fn commands_before_connecting_are_rejected() {
        let mut client = FtpClient::new(info(Protocol::Ftp, false));
        assert!(matches!(
            client.command("NOOP"),
            Err(ProtocolError::NotConnected)
        ));
    }

    #[test]
    fn commands_containing_line_breaks_are_refused() {
        // Guards against a path or file name smuggling a second command.
        let mut client = FtpClient::new(info(Protocol::Ftp, false));
        client.connected = true;
        let error = client.command("DELE a.txt\r\nQUIT").unwrap_err();
        assert!(error.to_string().contains("line break"));
    }

    #[test]
    fn passwords_are_redacted_from_logs() {
        assert_eq!(redact("PASS hunter2"), "PASS ******");
        assert_eq!(redact("pass hunter2"), "PASS ******");
        assert_eq!(redact("USER alice"), "USER alice");
    }

    #[test]
    fn a_permission_reply_maps_to_a_permission_error() {
        let reply = Reply {
            code: 550,
            text: "550 Permission denied".into(),
        };
        assert!(matches!(
            map_reply_error(&reply, "RETR /etc/shadow"),
            ProtocolError::PermissionDenied(path) if path == "/etc/shadow"
        ));
    }

    #[test]
    fn a_missing_file_reply_maps_to_a_not_found_error() {
        let reply = Reply {
            code: 550,
            text: "550 No such file or directory".into(),
        };
        assert!(matches!(
            map_reply_error(&reply, "RETR /missing.txt"),
            ProtocolError::NotFound(path) if path == "/missing.txt"
        ));
    }

    #[test]
    fn a_login_failure_maps_to_a_connection_error() {
        let reply = Reply {
            code: 530,
            text: "530 Login incorrect".into(),
        };
        assert!(matches!(
            map_reply_error(&reply, "PASS"),
            ProtocolError::Connection(_)
        ));
    }

    #[test]
    fn private_addresses_are_recognised_as_nat_mangled() {
        assert!(is_private_or_unroutable("192.168.1.5"));
        assert!(is_private_or_unroutable("10.0.0.1"));
        assert!(is_private_or_unroutable("172.16.0.1"));
        assert!(is_private_or_unroutable("127.0.0.1"));
        assert!(is_private_or_unroutable("0.0.0.0"));
        assert!(!is_private_or_unroutable("203.0.113.5"));
        // A hostname is not an address and is left alone.
        assert!(!is_private_or_unroutable("ftp.example.com"));
    }

    #[test]
    fn pumping_reports_progress_and_totals() {
        let source_bytes = vec![7u8; 200_000];
        let mut source = std::io::Cursor::new(source_bytes.clone());
        let mut sink: Vec<u8> = Vec::new();
        let mut seen: Vec<(u64, u64)> = Vec::new();
        let mut report = |transferred: u64, total: u64| {
            seen.push((transferred, total));
            Ok(())
        };

        let written = pump(
            &mut source,
            &mut sink,
            source_bytes.len() as u64,
            Some(&mut report),
        )
        .unwrap();

        assert_eq!(written, source_bytes.len() as u64);
        assert_eq!(sink, source_bytes);
        assert_eq!(seen.last().unwrap().0, source_bytes.len() as u64);
        assert!(seen
            .iter()
            .all(|(_, total)| *total == source_bytes.len() as u64));
    }

    #[test]
    fn pumping_stops_when_the_progress_callback_cancels() {
        let mut source = std::io::Cursor::new(vec![0u8; 500_000]);
        let mut sink: Vec<u8> = Vec::new();
        let mut report = |_: u64, _: u64| Err(ProtocolError::Cancelled);

        let error = pump(&mut source, &mut sink, 500_000, Some(&mut report)).unwrap_err();

        assert!(error.is_cancelled());
        // Only the first chunk made it through before the cancel took effect.
        assert_eq!(sink.len(), TRANSFER_CHUNK);
    }

    #[test]
    fn pumping_without_a_callback_still_copies_everything() {
        let mut source = std::io::Cursor::new(b"hello world".to_vec());
        let mut sink: Vec<u8> = Vec::new();
        let written = pump(&mut source, &mut sink, 11, None).unwrap();
        assert_eq!(written, 11);
        assert_eq!(sink, b"hello world");
    }
}
