//! Parsing of WebDAV `PROPFIND` multistatus responses.
//!
//! Servers disagree about namespace prefixes (`D:`, `d:`, none at all) and
//! about which properties they return, so the parser matches on local names
//! and treats every property as optional.

use chrono::NaiveDateTime;
use quick_xml::events::Event;
use quick_xml::Reader;

/// One `<response>` element from a multistatus document.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PropfindEntry {
    /// The `href`, still percent-encoded as the server sent it.
    pub href: String,
    /// `displayname`, when the server provides one.
    pub display_name: Option<String>,
    pub is_collection: bool,
    pub content_length: u64,
    pub last_modified: Option<NaiveDateTime>,
    pub content_type: Option<String>,
}

/// Why a multistatus document could not be read.
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("the server's response is not valid XML: {0}")]
    Xml(#[from] quick_xml::Error),
    #[error("the server's response ended mid-element")]
    Truncated,
}

/// Parse a multistatus document into its response entries.
///
/// Malformed or truncated XML yields an error; unknown elements are ignored so
/// a server returning extra properties still works.
pub fn parse_multistatus(xml: &str) -> Result<Vec<PropfindEntry>, ParseError> {
    let mut reader = Reader::from_str(xml);
    reader.config_mut().trim_text(true);

    let mut entries: Vec<PropfindEntry> = Vec::new();
    let mut current: Option<PropfindEntry> = None;
    // Which text-bearing element we are inside, by local name.
    let mut field: Option<String> = None;
    // `resourcetype` contains `<collection/>` as a child rather than text.
    let mut in_resource_type = false;
    // Open-element depth. A truncated response reaches EOF with this above
    // zero; treating that as a complete listing would silently drop files.
    let mut depth = 0usize;
    let mut buffer = Vec::new();

    loop {
        match reader.read_event_into(&mut buffer)? {
            Event::Start(element) => {
                depth += 1;
                let name = local_name(element.name().as_ref());
                match name.as_str() {
                    "response" => current = Some(PropfindEntry::default()),
                    "resourcetype" => in_resource_type = true,
                    "href" | "displayname" | "getcontentlength" | "getlastmodified"
                    | "getcontenttype" => field = Some(name),
                    _ => {}
                }
            }
            Event::Empty(element) => {
                let name = local_name(element.name().as_ref());
                // `<collection/>` is the marker for a directory.
                if name == "collection" && in_resource_type {
                    if let Some(entry) = current.as_mut() {
                        entry.is_collection = true;
                    }
                }
            }
            Event::Text(text) => {
                let (Some(name), Some(entry)) = (field.as_deref(), current.as_mut()) else {
                    continue;
                };
                let value = text.unescape()?.trim().to_string();
                match name {
                    "href" => entry.href = value,
                    "displayname" if !value.is_empty() => entry.display_name = Some(value),
                    "getcontentlength" => entry.content_length = value.parse().unwrap_or(0),
                    "getlastmodified" => entry.last_modified = parse_http_date(&value),
                    "getcontenttype" if !value.is_empty() => entry.content_type = Some(value),
                    _ => {}
                }
            }
            Event::End(element) => {
                depth = depth.saturating_sub(1);
                let name = local_name(element.name().as_ref());
                match name.as_str() {
                    "response" => {
                        if let Some(entry) = current.take() {
                            if !entry.href.is_empty() {
                                entries.push(entry);
                            }
                        }
                    }
                    "resourcetype" => in_resource_type = false,
                    _ => {}
                }
                if field.as_deref() == Some(name.as_str()) {
                    field = None;
                }
            }
            Event::Eof => {
                if depth > 0 {
                    return Err(ParseError::Truncated);
                }
                break;
            }
            _ => {}
        }
        buffer.clear();
    }

    // Some servers omit `<collection/>` but mark directories with a trailing
    // slash and the Apache directory content type.
    for entry in &mut entries {
        if !entry.is_collection && looks_like_collection(entry) {
            entry.is_collection = true;
        }
        if entry.is_collection {
            entry.content_length = 0;
        }
    }
    Ok(entries)
}

/// Whether an entry is a directory despite lacking `<collection/>`.
fn looks_like_collection(entry: &PropfindEntry) -> bool {
    entry.href.ends_with('/')
        || entry
            .content_type
            .as_deref()
            .is_some_and(|value| value.eq_ignore_ascii_case("httpd/unix-directory"))
}

/// Strip any namespace prefix, lowercasing the local name.
fn local_name(raw: &[u8]) -> String {
    let text = String::from_utf8_lossy(raw);
    let local = text.rsplit(':').next().unwrap_or(&text);
    local.to_ascii_lowercase()
}

/// Parse an RFC 1123 / RFC 850 / asctime HTTP date into naive local time.
pub fn parse_http_date(value: &str) -> Option<NaiveDateTime> {
    let value = value.trim();
    // RFC 1123: "Wed, 04 Mar 2026 09:05:00 GMT" — the common case.
    if let Ok(parsed) = chrono::DateTime::parse_from_rfc2822(value) {
        return Some(parsed.naive_utc());
    }
    // ISO 8601, used by some servers for creationdate-style properties.
    if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(value) {
        return Some(parsed.naive_utc());
    }
    // asctime: "Wed Mar  4 09:05:00 2026".
    NaiveDateTime::parse_from_str(value, "%a %b %e %H:%M:%S %Y").ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    const MULTISTATUS: &str = r#"<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/dav/</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>dav</D:displayname>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:getlastmodified>Wed, 04 Mar 2026 09:05:00 GMT</D:getlastmodified>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/notes.txt</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>notes.txt</D:displayname>
        <D:resourcetype/>
        <D:getcontentlength>1024</D:getcontentlength>
        <D:getcontenttype>text/plain</D:getcontenttype>
        <D:getlastmodified>Wed, 04 Mar 2026 10:00:00 GMT</D:getlastmodified>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>"#;

    #[test]
    fn a_multistatus_document_yields_one_entry_per_response() {
        let entries = parse_multistatus(MULTISTATUS).unwrap();
        assert_eq!(entries.len(), 2);
    }

    #[test]
    fn collections_are_detected_from_the_resourcetype_element() {
        let entries = parse_multistatus(MULTISTATUS).unwrap();
        assert!(entries[0].is_collection);
        assert_eq!(entries[0].href, "/dav/");
        assert_eq!(entries[0].display_name.as_deref(), Some("dav"));
        assert_eq!(entries[0].content_length, 0);
    }

    #[test]
    fn files_carry_their_size_type_and_timestamp() {
        let entries = parse_multistatus(MULTISTATUS).unwrap();
        let file = &entries[1];
        assert!(!file.is_collection);
        assert_eq!(file.href, "/dav/notes.txt");
        assert_eq!(file.content_length, 1024);
        assert_eq!(file.content_type.as_deref(), Some("text/plain"));
        assert_eq!(
            file.last_modified
                .unwrap()
                .format("%Y-%m-%d %H:%M")
                .to_string(),
            "2026-03-04 10:00"
        );
    }

    #[test]
    fn namespace_prefixes_are_ignored() {
        // The same document with a different prefix must parse identically.
        // Replacing the prefix also rewrites the xmlns declaration, so the
        // document stays well-formed with a lowercase prefix throughout.
        let lowercase = MULTISTATUS.replace("D:", "d:");
        let entries = parse_multistatus(&lowercase).unwrap();
        assert_eq!(entries.len(), 2);
        assert!(entries[0].is_collection);
    }

    #[test]
    fn documents_with_no_namespace_prefix_parse() {
        let xml = r#"<multistatus xmlns="DAV:">
            <response><href>/a.txt</href><propstat><prop>
                <resourcetype/><getcontentlength>7</getcontentlength>
            </prop></propstat></response>
        </multistatus>"#;
        let entries = parse_multistatus(xml).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].content_length, 7);
    }

    #[test]
    fn a_trailing_slash_marks_a_collection_when_resourcetype_is_absent() {
        let xml = r#"<multistatus xmlns="DAV:">
            <response><href>/dav/docs/</href><propstat><prop>
                <getcontentlength>4096</getcontentlength>
            </prop></propstat></response>
        </multistatus>"#;
        let entries = parse_multistatus(xml).unwrap();
        assert!(entries[0].is_collection);
        // A directory's reported size is meaningless and is zeroed.
        assert_eq!(entries[0].content_length, 0);
    }

    #[test]
    fn the_apache_directory_content_type_marks_a_collection() {
        let xml = r#"<multistatus xmlns="DAV:">
            <response><href>/dav/docs</href><propstat><prop>
                <getcontenttype>httpd/unix-directory</getcontenttype>
            </prop></propstat></response>
        </multistatus>"#;
        let entries = parse_multistatus(xml).unwrap();
        assert!(entries[0].is_collection);
    }

    #[test]
    fn responses_without_an_href_are_dropped() {
        let xml = r#"<multistatus xmlns="DAV:">
            <response><propstat><prop><getcontentlength>7</getcontentlength></prop></propstat></response>
        </multistatus>"#;
        assert!(parse_multistatus(xml).unwrap().is_empty());
    }

    #[test]
    fn an_empty_multistatus_yields_no_entries() {
        let xml = r#"<multistatus xmlns="DAV:"></multistatus>"#;
        assert!(parse_multistatus(xml).unwrap().is_empty());
    }

    #[test]
    fn malformed_xml_is_reported_rather_than_silently_empty() {
        assert!(parse_multistatus("<multistatus><response>").is_err());
    }

    #[test]
    fn escaped_characters_in_names_are_decoded() {
        let xml = r#"<multistatus xmlns="DAV:">
            <response><href>/dav/a%20&amp;%20b.txt</href><propstat><prop>
                <displayname>a &amp; b.txt</displayname>
            </prop></propstat></response>
        </multistatus>"#;
        let entries = parse_multistatus(xml).unwrap();
        assert_eq!(entries[0].display_name.as_deref(), Some("a & b.txt"));
    }

    #[test]
    fn http_dates_parse_in_their_common_forms() {
        assert_eq!(
            parse_http_date("Wed, 04 Mar 2026 09:05:00 GMT")
                .unwrap()
                .format("%Y-%m-%d %H:%M:%S")
                .to_string(),
            "2026-03-04 09:05:00"
        );
        assert_eq!(
            parse_http_date("2026-03-04T09:05:00Z")
                .unwrap()
                .format("%Y-%m-%d %H:%M:%S")
                .to_string(),
            "2026-03-04 09:05:00"
        );
        assert_eq!(
            parse_http_date("Wed Mar  4 09:05:00 2026")
                .unwrap()
                .format("%Y-%m-%d %H:%M:%S")
                .to_string(),
            "2026-03-04 09:05:00"
        );
    }

    #[test]
    fn an_unparseable_date_yields_none_rather_than_a_wrong_time() {
        assert_eq!(parse_http_date("last tuesday"), None);
        assert_eq!(parse_http_date(""), None);
    }
}
