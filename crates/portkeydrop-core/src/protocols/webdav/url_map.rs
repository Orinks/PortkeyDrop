//! Translation between the app's remote paths and WebDAV URLs.
//!
//! The app shows server-absolute paths (`/docs/notes.txt`). The server's URL
//! may carry a base path of its own (`https://host/remote.php/dav/files/me`),
//! and `href` values in `PROPFIND` responses are percent-encoded and may be
//! either absolute URLs or absolute paths. Keeping every conversion in one
//! place is what stops the base path from being doubled up or dropped.

use percent_encoding::{percent_decode_str, utf8_percent_encode, AsciiSet, CONTROLS};
use url::Url;

use crate::protocols::model::ConnectionInfo;
use crate::protocols::path;

/// Characters escaped in a path segment.
///
/// `/` is deliberately absent: segments are encoded individually, and the
/// separators are added back afterwards.
const PATH_SEGMENT: &AsciiSet = &CONTROLS
    .add(b' ')
    .add(b'"')
    .add(b'#')
    .add(b'<')
    .add(b'>')
    .add(b'?')
    .add(b'`')
    .add(b'{')
    .add(b'}')
    .add(b'%')
    .add(b'/');

/// Maps between remote paths and URLs for one connection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UrlMapper {
    /// Scheme and authority, without a trailing slash: `https://host:8443`.
    origin: String,
    /// Base path from the configured URL, without a trailing slash. May be
    /// empty.
    base_path: String,
}

impl UrlMapper {
    /// Build a mapper from connection settings.
    ///
    /// The host may be a bare name (`dav.example.com`), a host with a path
    /// (`example.com/remote.php/dav`), or a full URL.
    pub fn from_connection(info: &ConnectionInfo) -> Result<Self, String> {
        let raw = info.host.trim();
        if raw.is_empty() {
            return Err("no server address was given".to_string());
        }

        let port = info.effective_port();
        let with_scheme = if raw.contains("://") {
            raw.to_string()
        } else {
            // Port 80 means plain HTTP was intended; anything else defaults to
            // HTTPS, which is the safer guess.
            let scheme = if port == 80 { "http" } else { "https" };
            format!("{scheme}://{raw}")
        };

        let mut url =
            Url::parse(&with_scheme).map_err(|err| format!("invalid server address: {err}"))?;

        // An explicit port overrides whatever the URL carried; a default one
        // is left off so the URL stays canonical.
        let default_port = if url.scheme() == "http" { 80 } else { 443 };
        if port != default_port {
            url.set_port(Some(port))
                .map_err(|_| "invalid port".to_string())?;
        }

        let origin = format!(
            "{}://{}{}",
            url.scheme(),
            url.host_str()
                .ok_or_else(|| "invalid server address".to_string())?,
            url.port()
                .map(|port| format!(":{port}"))
                .unwrap_or_default()
        );
        let base_path = url.path().trim_end_matches('/').to_string();

        Ok(Self { origin, base_path })
    }

    /// Build a mapper directly, for tests and callers that already have a URL.
    #[allow(dead_code)] // Used by tests and callers that already have a URL.
    pub fn new(origin: impl Into<String>, base_path: impl Into<String>) -> Self {
        Self {
            origin: origin.into().trim_end_matches('/').to_string(),
            base_path: base_path.into().trim_end_matches('/').to_string(),
        }
    }

    /// The URL for a remote path.
    pub fn to_url(&self, remote_path: &str) -> String {
        let normalized = path::normalize(remote_path);
        let encoded = encode_path(&normalized);
        format!("{}{}{}", self.origin, self.base_path, encoded)
    }

    /// The URL for a collection, with the trailing slash servers expect.
    ///
    /// `MKCOL` against a URL without one is rejected by some servers.
    pub fn to_collection_url(&self, remote_path: &str) -> String {
        let url = self.to_url(remote_path);
        if url.ends_with('/') {
            url
        } else {
            format!("{url}/")
        }
    }

    /// Convert an `href` from a `PROPFIND` response into a remote path.
    ///
    /// Accepts both absolute URLs and absolute paths, and strips the base path
    /// so the result is what the app displays.
    pub fn to_remote_path(&self, href: &str) -> String {
        let raw_path = if href.contains("://") {
            Url::parse(href)
                .map(|url| url.path().to_string())
                .unwrap_or_else(|_| href.to_string())
        } else {
            href.to_string()
        };

        let decoded = percent_decode_str(&raw_path)
            .decode_utf8_lossy()
            .into_owned();
        let trimmed = strip_base_path(&decoded, &self.base_path);
        path::normalize(&trimmed)
    }
}

/// Remove a leading base path, if present.
fn strip_base_path(path: &str, base_path: &str) -> String {
    if base_path.is_empty() || base_path == "/" {
        return path.to_string();
    }
    if path == base_path {
        return "/".to_string();
    }
    match path.strip_prefix(base_path) {
        // Only strip on a segment boundary: a base of `/dav` must not eat the
        // leading part of `/davos`.
        Some(rest) if rest.starts_with('/') => rest.to_string(),
        _ => path.to_string(),
    }
}

/// Percent-encode each segment of a path, keeping the separators intact.
fn encode_path(path: &str) -> String {
    let trailing_slash = path.len() > 1 && path.ends_with('/');
    let encoded: Vec<String> = path
        .split('/')
        .filter(|segment| !segment.is_empty())
        .map(|segment| utf8_percent_encode(segment, PATH_SEGMENT).to_string())
        .collect();

    if encoded.is_empty() {
        return "/".to_string();
    }
    let joined = format!("/{}", encoded.join("/"));
    if trailing_slash {
        format!("{joined}/")
    } else {
        joined
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocols::model::Protocol;

    fn info(host: &str, port: u16) -> ConnectionInfo {
        ConnectionInfo {
            protocol: Protocol::Webdav,
            host: host.into(),
            port,
            ..Default::default()
        }
    }

    #[test]
    fn a_bare_host_defaults_to_https() {
        let mapper = UrlMapper::from_connection(&info("dav.example.com", 0)).unwrap();
        assert_eq!(
            mapper.to_url("/notes.txt"),
            "https://dav.example.com/notes.txt"
        );
    }

    #[test]
    fn port_80_selects_plain_http() {
        let mapper = UrlMapper::from_connection(&info("dav.example.com", 80)).unwrap();
        assert_eq!(
            mapper.to_url("/notes.txt"),
            "http://dav.example.com/notes.txt"
        );
    }

    #[test]
    fn a_non_default_port_appears_in_the_url() {
        let mapper = UrlMapper::from_connection(&info("dav.example.com", 8443)).unwrap();
        assert_eq!(
            mapper.to_url("/notes.txt"),
            "https://dav.example.com:8443/notes.txt"
        );
    }

    #[test]
    fn the_default_https_port_is_left_out_of_the_url() {
        let mapper = UrlMapper::from_connection(&info("dav.example.com", 443)).unwrap();
        assert_eq!(
            mapper.to_url("/notes.txt"),
            "https://dav.example.com/notes.txt"
        );
    }

    #[test]
    fn an_explicit_scheme_in_the_host_is_honoured() {
        let mapper = UrlMapper::from_connection(&info("http://dav.example.com", 0)).unwrap();
        assert!(mapper.to_url("/a").starts_with("http://"));
    }

    #[test]
    fn a_base_path_is_prefixed_onto_every_url() {
        let mapper =
            UrlMapper::from_connection(&info("https://cloud.example.com/remote.php/dav", 0))
                .unwrap();
        assert_eq!(
            mapper.to_url("/docs/notes.txt"),
            "https://cloud.example.com/remote.php/dav/docs/notes.txt"
        );
    }

    #[test]
    fn an_empty_host_is_rejected() {
        assert!(UrlMapper::from_connection(&info("   ", 0)).is_err());
    }

    #[test]
    fn the_root_path_maps_to_the_base_url() {
        let mapper = UrlMapper::new("https://host", "/dav");
        assert_eq!(mapper.to_url("/"), "https://host/dav/");
    }

    #[test]
    fn collection_urls_always_end_with_a_slash() {
        // MKCOL against a slash-less URL is rejected by some servers.
        let mapper = UrlMapper::new("https://host", "");
        assert_eq!(mapper.to_collection_url("/docs"), "https://host/docs/");
        assert_eq!(mapper.to_collection_url("/docs/"), "https://host/docs/");
    }

    #[test]
    fn spaces_and_reserved_characters_are_percent_encoded() {
        let mapper = UrlMapper::new("https://host", "");
        assert_eq!(
            mapper.to_url("/my docs/a#b.txt"),
            "https://host/my%20docs/a%23b.txt"
        );
    }

    #[test]
    fn separators_are_not_encoded_away() {
        let mapper = UrlMapper::new("https://host", "");
        assert_eq!(mapper.to_url("/a/b/c.txt"), "https://host/a/b/c.txt");
    }

    #[test]
    fn non_ascii_names_are_encoded_as_utf8() {
        let mapper = UrlMapper::new("https://host", "");
        assert_eq!(mapper.to_url("/café.txt"), "https://host/caf%C3%A9.txt");
    }

    #[test]
    fn hrefs_that_are_absolute_urls_become_remote_paths() {
        let mapper = UrlMapper::new("https://host", "/dav");
        assert_eq!(
            mapper.to_remote_path("https://host/dav/docs/notes.txt"),
            "/docs/notes.txt"
        );
    }

    #[test]
    fn hrefs_that_are_absolute_paths_become_remote_paths() {
        let mapper = UrlMapper::new("https://host", "/dav");
        assert_eq!(
            mapper.to_remote_path("/dav/docs/notes.txt"),
            "/docs/notes.txt"
        );
    }

    #[test]
    fn percent_encoding_in_hrefs_is_decoded() {
        let mapper = UrlMapper::new("https://host", "");
        assert_eq!(
            mapper.to_remote_path("/my%20docs/a%23b.txt"),
            "/my docs/a#b.txt"
        );
        assert_eq!(mapper.to_remote_path("/caf%C3%A9.txt"), "/café.txt");
    }

    #[test]
    fn the_base_path_itself_maps_to_the_root() {
        let mapper = UrlMapper::new("https://host", "/dav");
        assert_eq!(mapper.to_remote_path("/dav"), "/");
        assert_eq!(mapper.to_remote_path("/dav/"), "/");
    }

    #[test]
    fn a_base_path_is_only_stripped_on_a_segment_boundary() {
        // A base of `/dav` must not turn `/davos/x` into `os/x`.
        let mapper = UrlMapper::new("https://host", "/dav");
        assert_eq!(mapper.to_remote_path("/davos/x"), "/davos/x");
    }

    #[test]
    fn trailing_slashes_are_normalised_away_from_remote_paths() {
        let mapper = UrlMapper::new("https://host", "");
        assert_eq!(mapper.to_remote_path("/docs/"), "/docs");
    }

    #[test]
    fn remote_paths_round_trip_through_a_url() {
        let mapper = UrlMapper::new("https://host", "/remote.php/dav");
        for original in [
            "/docs/notes.txt",
            "/my docs/a b.txt",
            "/café/naïve.txt",
            "/",
        ] {
            let url = mapper.to_url(original);
            assert_eq!(mapper.to_remote_path(&url), path::normalize(original));
        }
    }
}
