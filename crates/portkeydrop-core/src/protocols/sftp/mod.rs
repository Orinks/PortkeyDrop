//! SFTP client built on russh.
//!
//! russh is async; the rest of the app is not. A dedicated multi-threaded
//! Tokio runtime is owned by the client and every public method blocks on it,
//! which keeps the async machinery from leaking into the UI and the transfer
//! engine.
//!
//! Host key policy is enforced in two passes rather than inside the async
//! handler: the handler records what the server offered and rejects anything
//! not already trusted, then [`SftpClient::connect`] asks the user on the
//! calling thread and retries. Prompting from inside the handler would block a
//! runtime worker while the UI thread waits, which is exactly the shape of a
//! deadlock.

pub mod known_hosts;
pub mod ppk;

use std::io::{Read, Write};
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use russh::client::{self, Handle};
use russh::keys::ssh_key;
use russh_sftp::client::SftpSession;
use russh_sftp::protocol::OpenFlags;
use tokio::io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt};

use super::model::{ConnectionInfo, HostKeyDecision, HostKeyPolicy, Protocol, RemoteFile};
use super::{path, ProgressFn, ProtocolError, Result, TransferClient};
use crate::portable;
use crate::ssh_agent;

use base64::Engine;

/// Chunk size for SFTP reads and writes.
const TRANSFER_CHUNK: usize = 32 * 1024;

/// Asks the user what to do about an untrusted host key.
///
/// Receives `(host, key algorithm, fingerprint)` and returns the decision.
pub type HostKeyPrompt = Arc<dyn Fn(&str, &str, &str) -> HostKeyDecision + Send + Sync + 'static>;

/// What the handler observed about the server's key.
#[derive(Debug, Default, Clone)]
struct OfferedKey {
    algorithm: String,
    /// Base64 key blob, in `known_hosts` form.
    blob: String,
    fingerprint: String,
    status: Option<known_hosts::HostKeyStatus>,
}

/// russh client handler enforcing the host key policy.
struct ClientHandler {
    policy: HostKeyPolicy,
    host: String,
    port: u16,
    known_hosts_path: std::path::PathBuf,
    /// Set once the user has approved this connection attempt.
    accept_any: bool,
    offered: Arc<Mutex<OfferedKey>>,
}

impl client::Handler for ClientHandler {
    type Error = russh::Error;

    async fn check_server_key(
        &mut self,
        server_public_key: &russh::keys::PublicKey,
    ) -> std::result::Result<bool, Self::Error> {
        let algorithm = server_public_key.algorithm().as_str().to_string();
        let blob = base64::engine::general_purpose::STANDARD
            .encode(server_public_key.to_bytes().unwrap_or_default());
        let fingerprint = server_public_key
            .fingerprint(ssh_key::HashAlg::Sha256)
            .to_string();

        let entries = known_hosts::load(&self.known_hosts_path);
        let status = known_hosts::status(&entries, &self.host, self.port, &algorithm, &blob);

        if let Ok(mut offered) = self.offered.lock() {
            *offered = OfferedKey {
                algorithm: algorithm.clone(),
                blob,
                fingerprint,
                status: Some(status),
            };
        }

        // A changed key is never auto-accepted, whatever the policy: that is
        // the case host key checking exists to catch.
        if status == known_hosts::HostKeyStatus::Changed && !self.accept_any {
            log::error!("host key for {} has changed", self.host);
            return Ok(false);
        }

        Ok(match self.policy {
            _ if self.accept_any => true,
            HostKeyPolicy::AutoAdd => true,
            HostKeyPolicy::Strict | HostKeyPolicy::Prompt => {
                status == known_hosts::HostKeyStatus::Known
            }
        })
    }
}

/// SFTP client.
pub struct SftpClient {
    info: ConnectionInfo,
    host_key_prompt: Option<HostKeyPrompt>,
    runtime: Option<tokio::runtime::Runtime>,
    session: Option<Arc<SftpSession>>,
    handle: Option<Handle<ClientHandler>>,
    connected: bool,
    cwd: String,
}

impl SftpClient {
    /// Build a client. No network activity happens until [`TransferClient::connect`].
    pub fn new(info: ConnectionInfo, host_key_prompt: Option<HostKeyPrompt>) -> Self {
        Self {
            info,
            host_key_prompt,
            runtime: None,
            session: None,
            handle: None,
            connected: false,
            cwd: "/".to_string(),
        }
    }

    /// The connection parameters this client was built with.
    pub fn info(&self) -> &ConnectionInfo {
        &self.info
    }

    /// Where trusted host keys are recorded.
    fn known_hosts_path(&self) -> std::path::PathBuf {
        portable::known_hosts_path(&portable::config_dir())
    }

    fn runtime(&self) -> Result<&tokio::runtime::Runtime> {
        self.runtime.as_ref().ok_or(ProtocolError::NotConnected)
    }

    fn session(&self) -> Result<Arc<SftpSession>> {
        if !self.connected {
            return Err(ProtocolError::NotConnected);
        }
        self.session.clone().ok_or(ProtocolError::NotConnected)
    }

    /// Run a future on the client's runtime, blocking the calling thread.
    fn block_on<F: std::future::Future>(&self, future: F) -> Result<F::Output> {
        Ok(self.runtime()?.block_on(future))
    }

    /// Establish the SSH transport and SFTP subsystem.
    ///
    /// `accept_any` skips host key checking for a retry the user has approved.
    ///
    /// The offered key is returned alongside the outcome even on failure, so
    /// the caller can tell an untrusted-key rejection apart from a bad
    /// password and only prompt for the former.
    fn establish(&mut self, accept_any: bool) -> (Result<()>, OfferedKey) {
        let offered = Arc::new(Mutex::new(OfferedKey::default()));
        let runtime = match tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .thread_name("portkeydrop-sftp")
            .build()
        {
            Ok(runtime) => runtime,
            Err(err) => {
                return (
                    Err(ProtocolError::connection(Protocol::Sftp, err)),
                    OfferedKey::default(),
                )
            }
        };

        let handler = ClientHandler {
            policy: self.info.host_key_policy,
            host: self.info.host.clone(),
            port: self.info.effective_port(),
            known_hosts_path: self.known_hosts_path(),
            accept_any,
            offered: Arc::clone(&offered),
        };

        // Without a keepalive an idle session is dropped silently by
        // firewalls and by servers running a `ClientAliveInterval`, and the
        // user only finds out when their next command fails.
        let keepalive = (self.info.keepalive > 0).then(|| Duration::from_secs(self.info.keepalive));
        let config = Arc::new(client::Config {
            inactivity_timeout: Some(Duration::from_secs(3600)),
            keepalive_interval: keepalive,
            keepalive_max: 3,
            ..Default::default()
        });
        let endpoint = (self.info.host.clone(), self.info.effective_port());
        let timeout = Duration::from_secs(self.info.timeout.max(1));

        let info = self.info.clone();
        let prompt_used = self.host_key_prompt.is_some();
        let connect_result: Result<(Handle<ClientHandler>, Arc<SftpSession>, String)> = runtime
            .block_on(async move {
                let handle =
                    tokio::time::timeout(timeout, client::connect(config, endpoint, handler))
                        .await
                        .map_err(|_| {
                            ProtocolError::Connection(format!(
                                "timed out connecting to {}",
                                info.endpoint()
                            ))
                        })?
                        .map_err(map_ssh_error)?;

                authenticate(handle, &info, prompt_used).await
            });

        let observed = offered
            .lock()
            .map(|offered| offered.clone())
            .unwrap_or_default();

        match connect_result {
            Ok((handle, session, cwd)) => {
                self.runtime = Some(runtime);
                self.handle = Some(handle);
                self.session = Some(session);
                self.cwd = cwd;
                self.connected = true;
                (Ok(()), observed)
            }
            Err(err) => {
                // Shut the runtime down here; keeping it would leak two worker
                // threads for every failed attempt.
                runtime.shutdown_timeout(Duration::from_millis(200));
                (Err(self.explain_failure(&observed, err)), observed)
            }
        }
    }

    /// Replace a bare transport error with host key context when that is what
    /// actually went wrong.
    fn explain_failure(&self, observed: &OfferedKey, err: ProtocolError) -> ProtocolError {
        match observed.status {
            Some(known_hosts::HostKeyStatus::Changed) => ProtocolError::Connection(format!(
                "SFTP connection failed: the host key for {} has changed. This may be a \
                 man-in-the-middle attack. Remove the old entry from {} only if you know the \
                 server's key was legitimately replaced.",
                self.info.host,
                self.known_hosts_path().display()
            )),
            Some(known_hosts::HostKeyStatus::Unknown)
                if self.info.host_key_policy == HostKeyPolicy::Strict =>
            {
                ProtocolError::Connection(format!(
                    "SFTP connection failed: the host key for {} is not in {}. \
                     Add it there, or set host key verification to Ask.",
                    self.info.host,
                    self.known_hosts_path().display()
                ))
            }
            _ => err,
        }
    }
}

/// Authenticate and open the SFTP subsystem.
async fn authenticate(
    mut handle: Handle<ClientHandler>,
    info: &ConnectionInfo,
    _prompt_used: bool,
) -> Result<(Handle<ClientHandler>, Arc<SftpSession>, String)> {
    let username = if info.username.is_empty() {
        whoami::username()
    } else {
        info.username.clone()
    };

    let mut attempted: Vec<String> = Vec::new();
    let mut authenticated = false;

    // An explicit key file is a deliberate choice, so it is tried alone: a
    // silent fallback to the agent would hide a broken key path.
    if !info.key_path.is_empty() {
        let key = load_private_key(&info.key_path, &info.password)?;
        attempted.push(format!("key file {}", info.key_path));
        let hash_alg = best_hash_alg(&key);
        let result = handle
            .authenticate_publickey(
                &username,
                russh::keys::PrivateKeyWithHashAlg::new(Arc::new(key), hash_alg),
            )
            .await
            .map_err(map_ssh_error)?;
        authenticated = result.success();
    } else {
        // Agent first: it is the common case for people who have one running,
        // and it never prompts.
        if ssh_agent::is_agent_available() || cfg!(windows) {
            attempted.push("SSH agent".to_string());
            match authenticate_with_agent(&mut handle, &username).await {
                Ok(true) => authenticated = true,
                Ok(false) => {}
                Err(err) => log::debug!("SSH agent authentication unavailable: {err}"),
            }
        }

        if !authenticated {
            for key_path in default_key_paths() {
                let Ok(key) = load_private_key_quiet(&key_path, &info.password) else {
                    continue;
                };
                attempted.push(format!("default key {}", key_path.display()));
                let hash_alg = best_hash_alg(&key);
                let result = handle
                    .authenticate_publickey(
                        &username,
                        russh::keys::PrivateKeyWithHashAlg::new(Arc::new(key), hash_alg),
                    )
                    .await
                    .map_err(map_ssh_error)?;
                if result.success() {
                    authenticated = true;
                    break;
                }
            }
        }

        if !authenticated && !info.password.is_empty() {
            attempted.push("password".to_string());
            let result = handle
                .authenticate_password(&username, &info.password)
                .await
                .map_err(map_ssh_error)?;
            authenticated = result.success();
        }
    }

    if !authenticated {
        return Err(ProtocolError::Connection(authentication_advice(
            info, &attempted,
        )));
    }

    let channel = handle.channel_open_session().await.map_err(map_ssh_error)?;
    channel
        .request_subsystem(true, "sftp")
        .await
        .map_err(map_ssh_error)?;
    let session = SftpSession::new(channel.into_stream())
        .await
        .map_err(|err| ProtocolError::Connection(format!("could not start SFTP session: {err}")))?;

    let cwd = session
        .canonicalize(".")
        .await
        .unwrap_or_else(|_| "/".to_string());
    Ok((handle, Arc::new(session), cwd))
}

/// Try every identity the SSH agent holds.
async fn authenticate_with_agent(
    handle: &mut Handle<ClientHandler>,
    username: &str,
) -> Result<bool> {
    #[cfg(unix)]
    let mut agent = russh::keys::agent::client::AgentClient::connect_env()
        .await
        .map_err(|err| ProtocolError::Other(err.to_string()))?;
    #[cfg(windows)]
    let mut agent = russh::keys::agent::client::AgentClient::connect_named_pipe(
        ssh_agent::WINDOWS_OPENSSH_PIPE,
    )
    .await
    .map_err(|err| ProtocolError::Other(err.to_string()))?;

    let identities = agent
        .request_identities()
        .await
        .map_err(|err| ProtocolError::Other(err.to_string()))?;

    for identity in identities {
        let russh::keys::agent::AgentIdentity::PublicKey { key, .. } = identity else {
            continue;
        };
        let hash_alg = hash_alg_for_algorithm(key.algorithm().as_str());
        match handle
            .authenticate_publickey_with(username, key, hash_alg, &mut agent)
            .await
        {
            Ok(result) if result.success() => return Ok(true),
            Ok(_) => continue,
            Err(err) => {
                log::debug!("agent identity rejected: {err}");
                continue;
            }
        }
    }
    Ok(false)
}

/// Prefer SHA-2 signatures for RSA keys; SHA-1 is refused by modern servers.
fn best_hash_alg(key: &ssh_key::PrivateKey) -> Option<russh::keys::HashAlg> {
    hash_alg_for_algorithm(key.algorithm().as_str())
}

fn hash_alg_for_algorithm(algorithm: &str) -> Option<russh::keys::HashAlg> {
    if algorithm == "ssh-rsa" {
        Some(russh::keys::HashAlg::Sha512)
    } else {
        None
    }
}

/// Key files OpenSSH would try automatically.
fn default_key_paths() -> Vec<std::path::PathBuf> {
    let ssh_dir = portable::home_dir().join(".ssh");
    ["id_ed25519", "id_ecdsa", "id_rsa", "id_dsa"]
        .iter()
        .map(|name| ssh_dir.join(name))
        .filter(|path| path.is_file())
        .collect()
}

/// Load a private key, detecting PuTTY's format by content rather than by
/// extension so a renamed `.ppk` still works.
pub fn load_private_key(key_path: &str, passphrase: &str) -> Result<ssh_key::PrivateKey> {
    let expanded = crate::settings::expand_user(key_path);
    if !expanded.is_file() {
        return Err(ProtocolError::Connection(format!(
            "SFTP connection failed: key file not found: {key_path}"
        )));
    }
    let data = std::fs::read(&expanded)?;
    let passphrase = Some(passphrase).filter(|value| !value.is_empty());

    if ppk::is_ppk(&data) {
        return ppk::load(&data, passphrase).map_err(|err| {
            ProtocolError::Connection(format!(
                "SFTP connection failed: could not import {}: {err}",
                ppk::describe(&data)
            ))
        });
    }

    let text = String::from_utf8_lossy(&data);
    let key = ssh_key::PrivateKey::from_openssh(text.as_ref())
        .map_err(|err| ProtocolError::Connection(key_import_advice(key_path, &err.to_string())))?;

    if !key.is_encrypted() {
        return Ok(key);
    }
    let passphrase = passphrase.ok_or_else(|| {
        ProtocolError::Connection(format!(
            "SFTP connection failed: the private key {key_path} needs a passphrase. \
             Enter it in the password field, or use an SSH agent."
        ))
    })?;
    key.decrypt(passphrase).map_err(|_| {
        ProtocolError::Connection(format!(
            "SFTP connection failed: the passphrase for {key_path} is incorrect."
        ))
    })
}

/// Load a key without reporting failures; used when probing default key paths.
fn load_private_key_quiet(path: &Path, passphrase: &str) -> Result<ssh_key::PrivateKey> {
    load_private_key(&path.to_string_lossy(), passphrase)
}

/// Explain an authentication failure in terms of what was actually tried.
fn authentication_advice(info: &ConnectionInfo, attempted: &[String]) -> String {
    let tried = if attempted.is_empty() {
        "no authentication methods were available".to_string()
    } else {
        format!("tried {}", attempted.join(", "))
    };

    if !info.key_path.is_empty() {
        format!(
            "SFTP connection failed: authentication failed with key file '{}' ({tried}). \
             Check the key's passphrase and that its public key is in the server's \
             authorized_keys.",
            info.key_path
        )
    } else if !info.password.is_empty() {
        format!(
            "SFTP connection failed: authentication failed ({tried}). \
             Verify the username and password, or load a key into your SSH agent."
        )
    } else {
        format!(
            "SFTP connection failed: authentication failed ({tried}). \
             Start your SSH agent and load a key, or supply a password or private key path."
        )
    }
}

/// Turn a key parse failure into advice the user can act on.
fn key_import_advice(key_path: &str, detail: &str) -> String {
    let lowered = detail.to_ascii_lowercase();
    if lowered.contains("passphrase") || lowered.contains("encrypted") {
        return format!(
            "SFTP connection failed: the private key {key_path} needs a passphrase ({detail}). \
             Enter it in the password field, or use an SSH agent."
        );
    }
    format!(
        "SFTP connection failed: the private key {key_path} could not be read ({detail}). \
         Use an OpenSSH, PKCS#8, or PuTTY (.ppk) key file."
    )
}

/// Map a russh transport error onto a protocol error with usable wording.
fn map_ssh_error(err: russh::Error) -> ProtocolError {
    let text = err.to_string();
    let lowered = text.to_ascii_lowercase();
    if lowered.contains("no common") || lowered.contains("kex") {
        return ProtocolError::Connection(format!(
            "SFTP connection failed: could not agree on encryption settings with the server ({text})."
        ));
    }
    if lowered.contains("unknown key") || lowered.contains("key exchange") {
        return ProtocolError::Connection(format!(
            "SFTP connection failed: host key verification failed ({text})."
        ));
    }
    ProtocolError::Connection(format!("SFTP connection failed: {text}"))
}

/// Map an SFTP status error onto a protocol error.
fn map_sftp_error(err: russh_sftp::client::error::Error, target: &str) -> ProtocolError {
    use russh_sftp::protocol::StatusCode;
    match &err {
        russh_sftp::client::error::Error::Status(status) => match status.status_code {
            StatusCode::NoSuchFile => ProtocolError::NotFound(target.to_string()),
            StatusCode::PermissionDenied => ProtocolError::PermissionDenied(target.to_string()),
            _ => ProtocolError::Other(format!("{target}: {err}")),
        },
        _ => ProtocolError::Other(format!("{target}: {err}")),
    }
}

/// Build a [`RemoteFile`] from SFTP attributes.
fn remote_file_from_metadata(
    name: &str,
    full_path: &str,
    metadata: &russh_sftp::protocol::FileAttributes,
) -> RemoteFile {
    let permissions = metadata
        .permissions
        .map(crate::local_files::format_mode)
        .unwrap_or_default();
    let modified = metadata.mtime.and_then(|mtime| {
        chrono::DateTime::from_timestamp(i64::from(mtime), 0).map(|utc| utc.naive_local())
    });
    RemoteFile {
        name: name.to_string(),
        path: full_path.to_string(),
        size: if metadata.file_type().is_dir() {
            0
        } else {
            metadata.len()
        },
        is_dir: metadata.file_type().is_dir(),
        modified,
        permissions,
        owner: metadata.uid.map(|uid| uid.to_string()).unwrap_or_default(),
        group: metadata.gid.map(|gid| gid.to_string()).unwrap_or_default(),
    }
}

impl TransferClient for SftpClient {
    fn protocol(&self) -> Protocol {
        Protocol::Sftp
    }

    fn is_connected(&self) -> bool {
        self.connected
    }

    fn cwd(&self) -> &str {
        &self.cwd
    }

    fn connect(&mut self) -> Result<()> {
        self.disconnect();

        let (outcome, offered) = self.establish(false);
        let error = match outcome {
            Ok(()) => return Ok(()),
            Err(error) => error,
        };

        // Only an unknown key under the prompt policy is worth asking about.
        // Anything else — a wrong password, an unreachable host, a *changed*
        // key — must surface as-is rather than as a trust dialog.
        if !should_prompt_for_host_key(self.info.host_key_policy, &offered) {
            return Err(error);
        }
        let Some(prompt) = self.host_key_prompt.clone() else {
            return Err(error);
        };

        match prompt(&self.info.host, &offered.algorithm, &offered.fingerprint) {
            HostKeyDecision::Reject => Err(ProtocolError::Connection(format!(
                "SFTP connection failed: the host key for {} was rejected.",
                self.info.host
            ))),
            HostKeyDecision::AcceptOnce => {
                log::info!("host key for {} accepted for this session", self.info.host);
                self.establish(true).0
            }
            HostKeyDecision::AcceptPermanent => {
                known_hosts::append(
                    &self.known_hosts_path(),
                    &self.info.host,
                    self.info.effective_port(),
                    &offered.algorithm,
                    &offered.blob,
                )?;
                log::info!("host key for {} accepted permanently", self.info.host);
                self.establish(true).0
            }
        }
    }

    fn disconnect(&mut self) {
        if let (Some(runtime), Some(session)) = (self.runtime.as_ref(), self.session.take()) {
            runtime.block_on(async {
                let _ = session.close().await;
            });
        }
        if let (Some(runtime), Some(handle)) = (self.runtime.as_ref(), self.handle.take()) {
            runtime.block_on(async {
                let _ = handle
                    .disconnect(russh::Disconnect::ByApplication, "", "en")
                    .await;
            });
        }
        // Shutting the runtime down without waiting avoids blocking the UI on
        // a server that has stopped responding.
        if let Some(runtime) = self.runtime.take() {
            runtime.shutdown_timeout(Duration::from_millis(500));
        }
        self.connected = false;
    }

    fn list_dir(&mut self, remote_path: &str) -> Result<Vec<RemoteFile>> {
        let session = self.session()?;
        let target = path::resolve(&self.cwd, remote_path);
        let target_for_async = target.clone();

        let entries = self.block_on(async move {
            session
                .read_dir(target_for_async.clone())
                .await
                .map_err(|err| map_sftp_error(err, &target_for_async))
        })??;

        let mut files = Vec::new();
        for entry in entries {
            let name = entry.file_name();
            if name == "." || name == ".." {
                continue;
            }
            let metadata = entry.metadata();
            // Sockets, FIFOs, and device nodes cannot be transferred and only
            // clutter the pane.
            if metadata.file_type().is_other() {
                log::debug!("skipping special file: {name}");
                continue;
            }
            let full_path = path::join(&target, &name);
            let mut file = remote_file_from_metadata(&name, &full_path, &metadata);

            // A symlink to a directory should behave like a directory, which
            // means following it: the listing only describes the link itself.
            if metadata.file_type().is_symlink() {
                if let Ok(Ok(target_metadata)) = {
                    let session = self.session()?;
                    let probe = full_path.clone();
                    self.block_on(async move { session.metadata(probe).await })
                } {
                    file.is_dir = target_metadata.file_type().is_dir();
                    if file.is_dir {
                        file.size = 0;
                    }
                }
            }
            files.push(file);
        }
        Ok(files)
    }

    fn chdir(&mut self, remote_path: &str) -> Result<String> {
        let session = self.session()?;
        let target = path::resolve(&self.cwd, remote_path);
        let probe = target.clone();

        let resolved = self.block_on(async move {
            let resolved = session
                .canonicalize(probe.clone())
                .await
                .map_err(|err| map_sftp_error(err, &probe))?;
            let metadata = session
                .metadata(resolved.clone())
                .await
                .map_err(|err| map_sftp_error(err, &resolved))?;
            if !metadata.file_type().is_dir() {
                return Err(ProtocolError::NotADirectory(resolved));
            }
            Ok(resolved)
        })??;

        self.cwd = resolved.clone();
        Ok(resolved)
    }

    fn download(
        &mut self,
        remote_path: &str,
        sink: &mut dyn Write,
        mut progress: Option<ProgressFn<'_>>,
        offset: u64,
    ) -> Result<()> {
        let session = self.session()?;
        let target = path::resolve(&self.cwd, remote_path);
        let runtime = self.runtime()?;

        // Resolve symlinks so the size used for progress is the real file's.
        let resolved = runtime
            .block_on({
                let session = Arc::clone(&session);
                let target = target.clone();
                async move { session.canonicalize(target).await }
            })
            .unwrap_or_else(|_| target.clone());

        let total = runtime
            .block_on({
                let session = Arc::clone(&session);
                let resolved = resolved.clone();
                async move { session.metadata(resolved).await }
            })
            .map(|metadata| metadata.len())
            .unwrap_or(0);
        let remaining = total.saturating_sub(offset);

        let mut file = runtime
            .block_on({
                let session = Arc::clone(&session);
                let resolved = resolved.clone();
                async move { session.open(resolved).await }
            })
            .map_err(|err| map_sftp_error(err, &resolved))?;

        if offset > 0 {
            runtime
                .block_on(file.seek(std::io::SeekFrom::Start(offset)))
                .map_err(ProtocolError::Io)?;
        }

        let mut buffer = vec![0u8; TRANSFER_CHUNK];
        let mut transferred = 0u64;
        loop {
            let read = runtime
                .block_on(file.read(&mut buffer))
                .map_err(ProtocolError::Io)?;
            if read == 0 {
                break;
            }
            sink.write_all(&buffer[..read])?;
            transferred += read as u64;
            if let Some(report) = progress.as_deref_mut() {
                report(transferred, remaining)?;
            }
        }
        sink.flush()?;
        Ok(())
    }

    fn upload(
        &mut self,
        source: &mut dyn Read,
        total_bytes: u64,
        remote_path: &str,
        mut progress: Option<ProgressFn<'_>>,
    ) -> Result<()> {
        let session = self.session()?;
        let target = path::resolve(&self.cwd, remote_path);
        let runtime = self.runtime()?;

        let open = |session: Arc<SftpSession>, target: String| async move {
            session
                .open_with_flags(
                    target,
                    OpenFlags::CREATE | OpenFlags::WRITE | OpenFlags::TRUNCATE,
                )
                .await
        };

        let mut file = match runtime.block_on(open(Arc::clone(&session), target.clone())) {
            Ok(file) => file,
            Err(err) => {
                // A missing parent is the common cause; create it and retry
                // rather than making the user pre-create every folder.
                let parent = path::parent(&target);
                log::debug!("remote parent {parent} may not exist; creating it");
                runtime
                    .block_on({
                        let session = Arc::clone(&session);
                        async move { create_dir_all(&session, &parent).await }
                    })
                    .map_err(|_| map_sftp_error(err, &target))?;
                runtime
                    .block_on(open(Arc::clone(&session), target.clone()))
                    .map_err(|err| map_sftp_error(err, &target))?
            }
        };

        let mut buffer = vec![0u8; TRANSFER_CHUNK];
        let mut transferred = 0u64;
        loop {
            let read = source.read(&mut buffer)?;
            if read == 0 {
                break;
            }
            runtime
                .block_on(file.write_all(&buffer[..read]))
                .map_err(ProtocolError::Io)?;
            transferred += read as u64;
            if let Some(report) = progress.as_deref_mut() {
                report(transferred, total_bytes)?;
            }
        }
        runtime.block_on(file.flush()).map_err(ProtocolError::Io)?;
        runtime
            .block_on(file.shutdown())
            .map_err(ProtocolError::Io)?;
        drop(file);

        // Confirm every byte landed; a truncated upload reported as success
        // would be silent data loss.
        let remote_size = runtime
            .block_on({
                let session = Arc::clone(&session);
                let target = target.clone();
                async move { session.metadata(target).await }
            })
            .map(|metadata| metadata.len())
            .map_err(|err| map_sftp_error(err, &target))?;

        if remote_size != transferred {
            return Err(ProtocolError::Verification(format!(
                "Remote upload verification failed for {target}: expected {transferred} bytes, \
                 got {remote_size}."
            )));
        }
        Ok(())
    }

    fn delete(&mut self, remote_path: &str) -> Result<()> {
        let session = self.session()?;
        let target = path::resolve(&self.cwd, remote_path);
        let probe = target.clone();
        self.block_on(async move {
            session
                .remove_file(probe.clone())
                .await
                .map_err(|err| map_sftp_error(err, &probe))?;
            match session.try_exists(probe.clone()).await {
                Ok(true) => Err(ProtocolError::Verification(format!(
                    "Remote delete verification failed for {probe}."
                ))),
                _ => Ok(()),
            }
        })?
    }

    fn rmdir(&mut self, remote_path: &str) -> Result<()> {
        let session = self.session()?;
        let target = path::resolve(&self.cwd, remote_path);
        let probe = target.clone();
        self.block_on(async move {
            session
                .remove_dir(probe.clone())
                .await
                .map_err(|err| map_sftp_error(err, &probe))?;
            match session.try_exists(probe.clone()).await {
                Ok(true) => Err(ProtocolError::Verification(format!(
                    "Remote directory delete verification failed for {probe}."
                ))),
                _ => Ok(()),
            }
        })?
    }

    fn mkdir(&mut self, remote_path: &str) -> Result<()> {
        let session = self.session()?;
        let target = path::resolve(&self.cwd, remote_path);
        let probe = target.clone();
        self.block_on(async move {
            session
                .create_dir(probe.clone())
                .await
                .map_err(|err| map_sftp_error(err, &probe))?;
            let metadata = session
                .metadata(probe.clone())
                .await
                .map_err(|err| map_sftp_error(err, &probe))?;
            if metadata.file_type().is_dir() {
                Ok(())
            } else {
                Err(ProtocolError::Verification(format!(
                    "Remote mkdir verification failed for {probe}."
                )))
            }
        })?
    }

    fn rename(&mut self, old_path: &str, new_path: &str) -> Result<()> {
        let session = self.session()?;
        let from = path::resolve(&self.cwd, old_path);
        let to = path::resolve(&self.cwd, new_path);
        self.block_on(async move {
            session
                .rename(from.clone(), to.clone())
                .await
                .map_err(|err| map_sftp_error(err, &from))?;
            session
                .metadata(to.clone())
                .await
                .map_err(|err| map_sftp_error(err, &to))?;
            Ok(())
        })?
    }

    fn stat(&mut self, remote_path: &str) -> Result<RemoteFile> {
        let session = self.session()?;
        let target = path::resolve(&self.cwd, remote_path);
        let probe = target.clone();
        let metadata = self.block_on(async move {
            session
                .metadata(probe.clone())
                .await
                .map_err(|err| map_sftp_error(err, &probe))
        })??;
        Ok(remote_file_from_metadata(
            path::file_name(&target),
            &target,
            &metadata,
        ))
    }
}

/// Create a remote directory and any missing parents.
async fn create_dir_all(session: &SftpSession, target: &str) -> std::result::Result<(), ()> {
    let mut current = String::new();
    for segment in target.split('/').filter(|segment| !segment.is_empty()) {
        current.push('/');
        current.push_str(segment);
        // An "already exists" failure is the expected case for every parent
        // above the one actually missing.
        let _ = session.create_dir(current.clone()).await;
    }
    match session.metadata(target.to_string()).await {
        Ok(metadata) if metadata.file_type().is_dir() => Ok(()),
        _ => Err(()),
    }
}

/// Whether a failed attempt should lead to a host key prompt.
///
/// Only an unknown key under the prompt policy qualifies. A *changed* key is
/// deliberately excluded: presenting that as a routine "do you trust this?"
/// dialog is how a man-in-the-middle gets clicked through.
fn should_prompt_for_host_key(policy: HostKeyPolicy, offered: &OfferedKey) -> bool {
    policy == HostKeyPolicy::Prompt
        && offered.status == Some(known_hosts::HostKeyStatus::Unknown)
        && !offered.algorithm.is_empty()
}

impl Drop for SftpClient {
    fn drop(&mut self) {
        self.disconnect();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn info() -> ConnectionInfo {
        ConnectionInfo {
            protocol: Protocol::Sftp,
            host: "example.com".into(),
            username: "alice".into(),
            ..Default::default()
        }
    }

    #[test]
    fn a_new_client_is_disconnected_at_the_root() {
        let client = SftpClient::new(info(), None);
        assert!(!client.is_connected());
        assert_eq!(client.cwd(), "/");
        assert_eq!(client.protocol(), Protocol::Sftp);
    }

    #[test]
    fn operations_before_connecting_are_rejected() {
        let mut client = SftpClient::new(info(), None);
        assert!(matches!(
            client.list_dir("."),
            Err(ProtocolError::NotConnected)
        ));
        assert!(matches!(
            client.stat("/x"),
            Err(ProtocolError::NotConnected)
        ));
        assert!(matches!(
            client.mkdir("/x"),
            Err(ProtocolError::NotConnected)
        ));
    }

    #[test]
    fn disconnecting_an_unconnected_client_is_harmless() {
        let mut client = SftpClient::new(info(), None);
        client.disconnect();
        assert!(!client.is_connected());
    }

    #[test]
    fn rsa_keys_are_signed_with_sha2() {
        // Servers have been refusing ssh-rsa/SHA-1 signatures for years; a
        // None here would silently fail against modern OpenSSH.
        assert!(matches!(
            hash_alg_for_algorithm("ssh-rsa"),
            Some(russh::keys::HashAlg::Sha512)
        ));
    }

    #[test]
    fn other_key_types_use_their_native_signature() {
        assert!(hash_alg_for_algorithm("ssh-ed25519").is_none());
        assert!(hash_alg_for_algorithm("ecdsa-sha2-nistp256").is_none());
    }

    #[test]
    fn a_missing_key_file_is_reported_before_connecting() {
        let error = load_private_key("/definitely/not/a/key", "").unwrap_err();
        assert!(error.to_string().contains("key file not found"));
    }

    #[test]
    fn authentication_advice_names_the_key_file_when_one_was_given() {
        let info = ConnectionInfo {
            key_path: "/home/a/id_rsa".into(),
            ..info()
        };
        let advice = authentication_advice(&info, &["key file /home/a/id_rsa".into()]);
        assert!(advice.contains("/home/a/id_rsa"));
        assert!(advice.contains("authorized_keys"));
    }

    #[test]
    fn authentication_advice_mentions_the_agent_when_nothing_was_supplied() {
        let advice = authentication_advice(&info(), &["SSH agent".into()]);
        assert!(advice.contains("SSH agent"));
    }

    #[test]
    fn authentication_advice_points_at_credentials_when_a_password_was_given() {
        let info = ConnectionInfo {
            password: "hunter2".into(),
            ..info()
        };
        let advice = authentication_advice(&info, &["password".into()]);
        assert!(advice.contains("username and password"));
        // The password itself must never appear in a message shown to users.
        assert!(!advice.contains("hunter2"));
    }

    #[test]
    fn encrypted_key_errors_tell_the_user_to_supply_a_passphrase() {
        let advice = key_import_advice("/home/a/id_rsa", "key is encrypted");
        assert!(advice.contains("passphrase"));
    }

    #[test]
    fn unreadable_key_errors_list_the_accepted_formats() {
        let advice = key_import_advice("/home/a/id_rsa", "unsupported format");
        assert!(advice.contains("OpenSSH"));
        assert!(advice.contains(".ppk"));
    }

    fn offered(status: Option<known_hosts::HostKeyStatus>) -> OfferedKey {
        OfferedKey {
            algorithm: "ssh-ed25519".into(),
            blob: "AAAA".into(),
            fingerprint: "SHA256:abc".into(),
            status,
        }
    }

    #[test]
    fn an_unknown_key_under_the_prompt_policy_asks_the_user() {
        assert!(should_prompt_for_host_key(
            HostKeyPolicy::Prompt,
            &offered(Some(known_hosts::HostKeyStatus::Unknown))
        ));
    }

    #[test]
    fn a_changed_key_never_asks_the_user() {
        // A trust dialog here is how a man-in-the-middle gets approved.
        assert!(!should_prompt_for_host_key(
            HostKeyPolicy::Prompt,
            &offered(Some(known_hosts::HostKeyStatus::Changed))
        ));
    }

    #[test]
    fn a_known_key_needs_no_prompt() {
        assert!(!should_prompt_for_host_key(
            HostKeyPolicy::Prompt,
            &offered(Some(known_hosts::HostKeyStatus::Known))
        ));
    }

    #[test]
    fn other_policies_never_prompt() {
        for policy in [HostKeyPolicy::AutoAdd, HostKeyPolicy::Strict] {
            assert!(!should_prompt_for_host_key(
                policy,
                &offered(Some(known_hosts::HostKeyStatus::Unknown))
            ));
        }
    }

    #[test]
    fn a_failure_before_any_key_was_offered_never_prompts() {
        // An unreachable host or a refused TCP connection must surface as
        // itself, not as a spurious host key dialog.
        assert!(!should_prompt_for_host_key(
            HostKeyPolicy::Prompt,
            &OfferedKey::default()
        ));
        assert!(!should_prompt_for_host_key(
            HostKeyPolicy::Prompt,
            &offered(None)
        ));
    }

    #[test]
    fn a_changed_key_failure_is_explained_as_a_possible_attack() {
        let client = SftpClient::new(info(), None);
        let error = client.explain_failure(
            &offered(Some(known_hosts::HostKeyStatus::Changed)),
            ProtocolError::Connection("generic".into()),
        );
        let text = error.to_string();
        assert!(text.contains("has changed"));
        assert!(text.contains("man-in-the-middle"));
    }

    #[test]
    fn a_strict_policy_failure_points_at_the_known_hosts_file() {
        let info = ConnectionInfo {
            host_key_policy: HostKeyPolicy::Strict,
            ..info()
        };
        let client = SftpClient::new(info, None);
        let error = client.explain_failure(
            &offered(Some(known_hosts::HostKeyStatus::Unknown)),
            ProtocolError::Connection("generic".into()),
        );
        assert!(error.to_string().contains("known_hosts"));
    }

    #[test]
    fn an_unrelated_failure_keeps_its_original_message() {
        let client = SftpClient::new(info(), None);
        let error = client.explain_failure(
            &offered(Some(known_hosts::HostKeyStatus::Known)),
            ProtocolError::Connection("connection refused".into()),
        );
        assert_eq!(error.to_string(), "connection refused");
    }
}
