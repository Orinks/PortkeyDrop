//! WebDAV client over HTTP(S).
//!
//! WebDAV paths in the UI are always server-absolute (`/docs/notes.txt`), while
//! the URL may carry a base path (`https://host/remote.php/dav`). Everything
//! crossing the boundary goes through [`UrlMapper`], which keeps the two
//! representations from leaking into each other — the source of most of the
//! path bugs this protocol invites.

pub mod propfind;
pub mod url_map;

use std::io::{Read, Write};
use std::time::Duration;

use reqwest::blocking::{Client, Response};
use reqwest::header::{HeaderMap, HeaderValue, CONTENT_LENGTH, CONTENT_TYPE, RANGE};
use reqwest::{Method, StatusCode};

use super::model::{ConnectionInfo, Protocol, RemoteFile};
use super::{path, ProgressFn, ProtocolError, Result, TransferClient};

pub use propfind::PropfindEntry;
pub use url_map::UrlMapper;

/// Chunk size for streaming transfers.
const TRANSFER_CHUNK: usize = 64 * 1024;

/// The body sent with `PROPFIND`, asking only for what the file panes show.
const PROPFIND_BODY: &str = r#"<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:displayname/>
    <D:resourcetype/>
    <D:getcontentlength/>
    <D:getlastmodified/>
    <D:getcontenttype/>
  </D:prop>
</D:propfind>"#;

/// WebDAV client.
pub struct WebdavClient {
    info: ConnectionInfo,
    mapper: Option<UrlMapper>,
    client: Option<Client>,
    connected: bool,
    cwd: String,
}

impl WebdavClient {
    /// Build a client. No network activity happens until [`TransferClient::connect`].
    pub fn new(info: ConnectionInfo) -> Self {
        Self {
            info,
            mapper: None,
            client: None,
            connected: false,
            cwd: "/".to_string(),
        }
    }

    /// The connection parameters this client was built with.
    pub fn info(&self) -> &ConnectionInfo {
        &self.info
    }

    fn client(&self) -> Result<&Client> {
        if !self.connected {
            return Err(ProtocolError::NotConnected);
        }
        self.client.as_ref().ok_or(ProtocolError::NotConnected)
    }

    fn mapper(&self) -> Result<&UrlMapper> {
        self.mapper.as_ref().ok_or(ProtocolError::NotConnected)
    }

    /// Send a request, applying credentials and the configured timeout.
    fn request(&self, method: Method, url: &str, headers: HeaderMap) -> Result<Response> {
        let client = self.client()?;
        let mut builder = client.request(method, url).headers(headers);
        if !self.info.username.is_empty() {
            builder = builder.basic_auth(&self.info.username, Some(&self.info.password));
        }
        builder.send().map_err(|err| map_transport_error(err, url))
    }

    /// Run a `PROPFIND` and parse the multistatus body.
    fn propfind(&self, remote_path: &str, depth: &str) -> Result<Vec<PropfindEntry>> {
        let mapper = self.mapper()?;
        let url = mapper.to_url(remote_path);

        let mut headers = HeaderMap::new();
        headers.insert(
            "Depth",
            HeaderValue::from_str(depth).expect("depth is ASCII"),
        );
        headers.insert(
            CONTENT_TYPE,
            HeaderValue::from_static("application/xml; charset=utf-8"),
        );

        let client = self.client()?;
        let mut builder = client
            .request(
                Method::from_bytes(b"PROPFIND").expect("PROPFIND is a valid method"),
                &url,
            )
            .headers(headers)
            .body(PROPFIND_BODY);
        if !self.info.username.is_empty() {
            builder = builder.basic_auth(&self.info.username, Some(&self.info.password));
        }

        let response = builder
            .send()
            .map_err(|err| map_transport_error(err, &url))?;
        let status = response.status();
        if !status.is_success() && status != StatusCode::MULTI_STATUS {
            return Err(map_status(status, remote_path));
        }
        let body = response
            .text()
            .map_err(|err| map_transport_error(err, &url))?;
        propfind::parse_multistatus(&body).map_err(|err| {
            ProtocolError::Other(format!(
                "could not read the server's directory listing: {err}"
            ))
        })
    }

    /// Turn a `PROPFIND` entry into a file row.
    fn to_remote_file(&self, entry: &PropfindEntry) -> Result<RemoteFile> {
        let mapper = self.mapper()?;
        let remote_path = mapper.to_remote_path(&entry.href);
        let name = entry
            .display_name
            .clone()
            .filter(|name| !name.is_empty())
            .unwrap_or_else(|| path::file_name(&remote_path).to_string());
        Ok(RemoteFile {
            name,
            path: remote_path,
            size: entry.content_length,
            is_dir: entry.is_collection,
            modified: entry.last_modified,
            permissions: String::new(),
            owner: String::new(),
            group: String::new(),
        })
    }
}

/// Turn a transport failure into a user-facing error.
fn map_transport_error(err: reqwest::Error, url: &str) -> ProtocolError {
    if err.is_timeout() {
        return ProtocolError::Connection(format!("timed out talking to {url}"));
    }
    if err.is_connect() {
        return ProtocolError::Connection(format!("could not connect to {url}: {err}"));
    }
    ProtocolError::Other(format!("{url}: {err}"))
}

/// Map an HTTP status onto a protocol error.
fn map_status(status: StatusCode, target: &str) -> ProtocolError {
    match status {
        StatusCode::UNAUTHORIZED => ProtocolError::Connection(
            "WebDAV connection failed: the server rejected these credentials.".to_string(),
        ),
        StatusCode::FORBIDDEN => ProtocolError::PermissionDenied(target.to_string()),
        StatusCode::NOT_FOUND => ProtocolError::NotFound(target.to_string()),
        StatusCode::CONFLICT => {
            ProtocolError::NotFound(format!("{target} (the parent collection does not exist)"))
        }
        StatusCode::METHOD_NOT_ALLOWED => ProtocolError::AlreadyExists(target.to_string()),
        StatusCode::PRECONDITION_FAILED => ProtocolError::AlreadyExists(target.to_string()),
        other => ProtocolError::Other(format!("{target}: server replied {other}")),
    }
}

impl TransferClient for WebdavClient {
    fn protocol(&self) -> Protocol {
        Protocol::Webdav
    }

    fn is_connected(&self) -> bool {
        self.connected
    }

    fn cwd(&self) -> &str {
        &self.cwd
    }

    fn connect(&mut self) -> Result<()> {
        let mapper = UrlMapper::from_connection(&self.info)
            .map_err(|err| ProtocolError::connection(Protocol::Webdav, err))?;

        let client = Client::builder()
            .timeout(Duration::from_secs(self.info.timeout.max(1)))
            .user_agent(concat!("PortkeyDrop/", env!("CARGO_PKG_VERSION")))
            .build()
            .map_err(|err| ProtocolError::connection(Protocol::Webdav, err))?;

        self.mapper = Some(mapper);
        self.client = Some(client);
        self.connected = true;
        self.cwd = "/".to_string();

        // A PROPFIND on the root both proves the credentials work and confirms
        // the URL actually speaks WebDAV, rather than deferring that to the
        // first directory listing.
        if let Err(err) = self.propfind("/", "0") {
            self.disconnect();
            return Err(match err {
                ProtocolError::Connection(message) => {
                    ProtocolError::connection(Protocol::Webdav, message)
                }
                other => ProtocolError::connection(Protocol::Webdav, other),
            });
        }
        Ok(())
    }

    fn disconnect(&mut self) {
        self.client = None;
        self.mapper = None;
        self.connected = false;
    }

    fn list_dir(&mut self, remote_path: &str) -> Result<Vec<RemoteFile>> {
        let target = path::resolve(&self.cwd, remote_path);
        let entries = self.propfind(&target, "1")?;

        let mut files = Vec::new();
        for entry in &entries {
            let file = self.to_remote_file(entry)?;
            // Depth 1 includes the collection itself; that is the pane's
            // current directory, not one of its children.
            if same_collection(&file.path, &target) {
                continue;
            }
            files.push(file);
        }
        Ok(files)
    }

    fn chdir(&mut self, remote_path: &str) -> Result<String> {
        let target = path::resolve(&self.cwd, remote_path);
        if same_collection(&target, "/") {
            self.cwd = "/".to_string();
            return Ok(self.cwd.clone());
        }

        let entries = self.propfind(&target, "0")?;
        let entry = entries
            .first()
            .ok_or_else(|| ProtocolError::NotFound(target.clone()))?;
        if !entry.is_collection {
            return Err(ProtocolError::NotADirectory(target));
        }
        self.cwd = path::normalize(&target);
        Ok(self.cwd.clone())
    }

    fn download(
        &mut self,
        remote_path: &str,
        sink: &mut dyn Write,
        mut progress: Option<ProgressFn<'_>>,
        offset: u64,
    ) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        let url = self.mapper()?.to_url(&target);

        let mut headers = HeaderMap::new();
        if offset > 0 {
            let range = format!("bytes={offset}-");
            headers.insert(
                RANGE,
                HeaderValue::from_str(&range)
                    .map_err(|err| ProtocolError::Other(err.to_string()))?,
            );
        }

        let mut response = self.request(Method::GET, &url, headers)?;
        let status = response.status();
        if !status.is_success() {
            return Err(map_status(status, &target));
        }
        // A server that ignores Range answers 200 with the whole file; writing
        // that after a partial file would corrupt the result.
        if offset > 0 && status != StatusCode::PARTIAL_CONTENT {
            return Err(ProtocolError::Unsupported(
                "This server does not support resuming downloads; retry from the start."
                    .to_string(),
            ));
        }

        let total = response
            .headers()
            .get(CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(0);

        let mut buffer = vec![0u8; TRANSFER_CHUNK];
        let mut transferred = 0u64;
        loop {
            let read = response.read(&mut buffer)?;
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
        Ok(())
    }

    fn upload(
        &mut self,
        source: &mut dyn Read,
        total_bytes: u64,
        remote_path: &str,
        mut progress: Option<ProgressFn<'_>>,
    ) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        let url = self.mapper()?.to_url(&target);

        // reqwest's blocking body cannot report progress mid-stream, so the
        // content is staged and progress is reported as it is read.
        let mut body = Vec::with_capacity(total_bytes as usize);
        let mut buffer = vec![0u8; TRANSFER_CHUNK];
        let mut staged = 0u64;
        loop {
            let read = source.read(&mut buffer)?;
            if read == 0 {
                break;
            }
            body.extend_from_slice(&buffer[..read]);
            staged += read as u64;
            if let Some(report) = progress.as_deref_mut() {
                report(staged, total_bytes)?;
            }
        }

        let client = self.client()?;
        let mut builder = client.put(&url).body(body);
        if !self.info.username.is_empty() {
            builder = builder.basic_auth(&self.info.username, Some(&self.info.password));
        }
        let response = builder
            .send()
            .map_err(|err| map_transport_error(err, &url))?;
        let status = response.status();
        if !status.is_success() {
            return Err(map_status(status, &target));
        }

        // Confirm the stored size, so a server that truncated the body is not
        // reported as a successful upload.
        let entries = self.propfind(&target, "0")?;
        match entries.first() {
            Some(entry) if entry.content_length == staged => Ok(()),
            Some(entry) if entry.content_length == 0 && staged == 0 => Ok(()),
            Some(entry) => Err(ProtocolError::Verification(format!(
                "Remote upload verification failed for {target}: expected {staged} bytes, got {}.",
                entry.content_length
            ))),
            None => Err(ProtocolError::Verification(format!(
                "Remote upload verification failed for {target}: the server does not report it as stored."
            ))),
        }
    }

    fn delete(&mut self, remote_path: &str) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        let url = self.mapper()?.to_url(&target);
        let response = self.request(Method::DELETE, &url, HeaderMap::new())?;
        let status = response.status();
        if status.is_success() || status == StatusCode::NOT_FOUND {
            return Ok(());
        }
        Err(map_status(status, &target))
    }

    fn rmdir(&mut self, remote_path: &str) -> Result<()> {
        // DELETE on a collection removes it and its contents.
        self.delete(remote_path)
    }

    fn mkdir(&mut self, remote_path: &str) -> Result<()> {
        let target = path::resolve(&self.cwd, remote_path);
        let url = self.mapper()?.to_collection_url(&target);
        let method = Method::from_bytes(b"MKCOL").expect("MKCOL is a valid method");
        let response = self.request(method, &url, HeaderMap::new())?;
        let status = response.status();
        if status.is_success() {
            return Ok(());
        }
        Err(map_status(status, &target))
    }

    fn rename(&mut self, old_path: &str, new_path: &str) -> Result<()> {
        let from = path::resolve(&self.cwd, old_path);
        let to = path::resolve(&self.cwd, new_path);
        let mapper = self.mapper()?;
        let from_url = mapper.to_url(&from);
        let to_url = mapper.to_url(&to);

        let mut headers = HeaderMap::new();
        headers.insert(
            "Destination",
            HeaderValue::from_str(&to_url).map_err(|err| ProtocolError::Other(err.to_string()))?,
        );
        // Refuse to clobber an existing entry; the caller resolves conflicts.
        headers.insert("Overwrite", HeaderValue::from_static("F"));

        let method = Method::from_bytes(b"MOVE").expect("MOVE is a valid method");
        let response = self.request(method, &from_url, headers)?;
        let status = response.status();
        if status.is_success() {
            return Ok(());
        }
        Err(map_status(status, &to))
    }

    fn stat(&mut self, remote_path: &str) -> Result<RemoteFile> {
        let target = path::resolve(&self.cwd, remote_path);
        let entries = self.propfind(&target, "0")?;
        let entry = entries.first().ok_or(ProtocolError::NotFound(target))?;
        self.to_remote_file(entry)
    }
}

/// Whether two paths name the same collection, ignoring a trailing slash.
fn same_collection(left: &str, right: &str) -> bool {
    let normalize = |value: &str| {
        let trimmed = value.trim_end_matches('/');
        if trimmed.is_empty() {
            "/".to_string()
        } else {
            trimmed.to_string()
        }
    };
    normalize(left) == normalize(right)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn info() -> ConnectionInfo {
        ConnectionInfo {
            protocol: Protocol::Webdav,
            host: "dav.example.com".into(),
            username: "alice".into(),
            password: "hunter2".into(),
            ..Default::default()
        }
    }

    #[test]
    fn a_new_client_is_disconnected_at_the_root() {
        let client = WebdavClient::new(info());
        assert!(!client.is_connected());
        assert_eq!(client.cwd(), "/");
        assert_eq!(client.protocol(), Protocol::Webdav);
    }

    #[test]
    fn operations_before_connecting_are_rejected() {
        let mut client = WebdavClient::new(info());
        assert!(matches!(
            client.list_dir("."),
            Err(ProtocolError::NotConnected)
        ));
        assert!(matches!(
            client.stat("/x"),
            Err(ProtocolError::NotConnected)
        ));
    }

    #[test]
    fn paths_differing_only_by_a_trailing_slash_are_the_same_collection() {
        assert!(same_collection("/dav/docs", "/dav/docs/"));
        assert!(same_collection("/", ""));
        assert!(same_collection("/", "/"));
        assert!(!same_collection("/dav/docs", "/dav/other"));
    }

    #[test]
    fn unauthorized_is_reported_as_a_credentials_problem() {
        let error = map_status(StatusCode::UNAUTHORIZED, "/dav/x");
        assert!(error.to_string().contains("credentials"));
    }

    #[test]
    fn forbidden_and_not_found_map_to_distinct_errors() {
        assert!(matches!(
            map_status(StatusCode::FORBIDDEN, "/dav/x"),
            ProtocolError::PermissionDenied(_)
        ));
        assert!(matches!(
            map_status(StatusCode::NOT_FOUND, "/dav/x"),
            ProtocolError::NotFound(_)
        ));
    }

    #[test]
    fn a_conflict_explains_that_the_parent_is_missing() {
        // 409 from WebDAV means the parent collection does not exist, which is
        // otherwise a baffling thing for a user to be told.
        let error = map_status(StatusCode::CONFLICT, "/dav/a/b.txt");
        assert!(error.to_string().contains("parent collection"));
    }

    #[test]
    fn an_existing_target_is_reported_as_already_existing() {
        assert!(matches!(
            map_status(StatusCode::PRECONDITION_FAILED, "/dav/x"),
            ProtocolError::AlreadyExists(_)
        ));
    }
}
