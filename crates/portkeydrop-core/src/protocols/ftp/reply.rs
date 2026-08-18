//! Parsing of FTP control-channel replies.
//!
//! A reply is either a single `NNN text` line or a multi-line block that opens
//! with `NNN-text` and closes with a line starting `NNN ` (same code, space).
//! Intermediate lines may look like anything at all, including other three
//! digit numbers, so the terminator has to match the opening code exactly.

/// A parsed control-channel reply.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Reply {
    /// Three-digit status code.
    pub code: u16,
    /// Full reply text, newline-separated for multi-line replies.
    pub text: String,
}

impl Reply {
    /// Whether the code indicates success (2xx) or an accepted intermediate
    /// step (3xx, e.g. `USER` awaiting `PASS`).
    pub fn is_positive(&self) -> bool {
        (200..400).contains(&self.code)
    }

    /// Whether the server signalled a preliminary reply (1xx), meaning the
    /// real outcome arrives in a later reply.
    pub fn is_preliminary(&self) -> bool {
        (100..200).contains(&self.code)
    }

    /// A single-line summary for error messages.
    pub fn summary(&self) -> String {
        let first_line = self.text.lines().next().unwrap_or("").trim();
        if first_line.is_empty() {
            format!("server replied {}", self.code)
        } else {
            first_line.to_string()
        }
    }
}

/// How a single raw line contributes to the reply being assembled.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LineKind {
    /// `NNN text` — a complete single-line reply, or the terminator of a block.
    Final(u16),
    /// `NNN-text` — opens a multi-line block.
    BlockStart(u16),
    /// Anything else: continuation text inside a block.
    Continuation,
}

/// Classify one raw reply line.
pub fn classify_line(line: &str) -> LineKind {
    let bytes = line.as_bytes();
    if bytes.len() < 4 || !bytes[..3].iter().all(u8::is_ascii_digit) {
        return LineKind::Continuation;
    }
    // A three digit prefix only counts when followed by a space or hyphen.
    let code: u16 = line[..3].parse().unwrap_or(0);
    match bytes[3] {
        b' ' => LineKind::Final(code),
        b'-' => LineKind::BlockStart(code),
        _ => LineKind::Continuation,
    }
}

/// Incremental assembler for a control reply.
///
/// Feeding lines one at a time keeps the socket read loop simple and makes the
/// multi-line rules directly testable without a server.
#[derive(Debug, Default)]
pub struct ReplyBuilder {
    /// Code that opened a multi-line block, if one is open.
    block_code: Option<u16>,
    lines: Vec<String>,
}

impl ReplyBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    /// Add one line, returning the reply once it is complete.
    pub fn push(&mut self, line: &str) -> Option<Reply> {
        let line = line.trim_end_matches(['\r', '\n']);
        let kind = classify_line(line);
        self.lines.push(line.to_string());

        match (self.block_code, kind) {
            // Not in a block: a final line completes the reply immediately.
            (None, LineKind::Final(code)) => Some(self.finish(code)),
            (None, LineKind::BlockStart(code)) => {
                self.block_code = Some(code);
                None
            }
            // In a block: only a final line with the opening code closes it.
            (Some(open), LineKind::Final(code)) if open == code => Some(self.finish(code)),
            _ => None,
        }
    }

    fn finish(&mut self, code: u16) -> Reply {
        let text = self.lines.join("\n");
        self.lines.clear();
        self.block_code = None;
        Reply { code, text }
    }
}

/// Extract the path from a `257 "/path" created` style reply.
///
/// Doubled quotes inside the path are an escaped literal quote, per RFC 959.
pub fn parse_pathname(text: &str) -> Option<String> {
    let start = text.find('"')? + 1;
    let rest = &text[start..];

    let mut path = String::new();
    let mut chars = rest.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch != '"' {
            path.push(ch);
            continue;
        }
        // A doubled quote is a literal quote; a lone quote ends the path.
        if chars.peek() == Some(&'"') {
            chars.next();
            path.push('"');
        } else {
            return Some(path);
        }
    }
    None
}

/// Parse the host and port from a `227 Entering Passive Mode (h1,h2,h3,h4,p1,p2)` reply.
pub fn parse_pasv(text: &str) -> Option<(String, u16)> {
    let open = text.rfind('(')?;
    let close = text[open..].find(')')? + open;
    let numbers: Vec<u8> = text[open + 1..close]
        .split(',')
        .map(|part| part.trim().parse::<u8>())
        .collect::<Result<_, _>>()
        .ok()?;
    if numbers.len() != 6 {
        return None;
    }
    let host = format!(
        "{}.{}.{}.{}",
        numbers[0], numbers[1], numbers[2], numbers[3]
    );
    let port = (u16::from(numbers[4]) << 8) | u16::from(numbers[5]);
    Some((host, port))
}

/// Parse the port from a `229 Entering Extended Passive Mode (|||port|)` reply.
///
/// The delimiter is whatever character sits in the first position, so it is
/// read from the reply rather than assumed to be `|`.
pub fn parse_epsv(text: &str) -> Option<u16> {
    let open = text.rfind('(')?;
    let close = text[open..].find(')')? + open;
    let body = &text[open + 1..close];
    let delimiter = body.chars().next()?;
    let fields: Vec<&str> = body.split(delimiter).collect();
    // Fields are ["", net-prt, net-addr, tcp-port, ""].
    if fields.len() != 5 {
        return None;
    }
    fields[3].trim().parse().ok()
}

/// Parse a `213 YYYYMMDDHHMMSS` modification-time reply.
pub fn parse_mdtm(text: &str) -> Option<chrono::NaiveDateTime> {
    let stamp: String = text
        .chars()
        .filter(|c| c.is_ascii_digit())
        .skip_while(|_| false)
        .collect();
    // The status code contributes its own three digits; drop them, then take
    // the 14-digit timestamp.
    let stamp = stamp.strip_prefix("213").unwrap_or(&stamp);
    if stamp.len() < 14 {
        return None;
    }
    chrono::NaiveDateTime::parse_from_str(&stamp[..14], "%Y%m%d%H%M%S").ok()
}

/// Parse a `213 <size>` reply.
pub fn parse_size(text: &str) -> Option<u64> {
    text.split_whitespace().nth(1)?.trim().parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assemble(lines: &[&str]) -> Option<Reply> {
        let mut builder = ReplyBuilder::new();
        let mut result = None;
        for line in lines {
            result = builder.push(line);
            if result.is_some() {
                break;
            }
        }
        result
    }

    #[test]
    fn a_single_line_reply_completes_immediately() {
        let reply = assemble(&["200 Command okay"]).unwrap();
        assert_eq!(reply.code, 200);
        assert_eq!(reply.text, "200 Command okay");
        assert!(reply.is_positive());
    }

    #[test]
    fn trailing_crlf_is_stripped() {
        let reply = assemble(&["220 Ready\r\n"]).unwrap();
        assert_eq!(reply.text, "220 Ready");
    }

    #[test]
    fn a_multi_line_block_needs_its_matching_terminator() {
        let reply = assemble(&["211-Features:", " MLST", " UTF8", "211 End"]).unwrap();
        assert_eq!(reply.code, 211);
        assert_eq!(reply.text, "211-Features:\n MLST\n UTF8\n211 End");
    }

    #[test]
    fn a_different_code_does_not_close_an_open_block() {
        // A line like "230 ..." inside a 211 block is continuation text, not
        // the end of the reply.
        let mut builder = ReplyBuilder::new();
        assert!(builder.push("211-Features:").is_none());
        assert!(builder.push("230 This is just text").is_none());
        let reply = builder.push("211 End").unwrap();
        assert_eq!(reply.code, 211);
    }

    #[test]
    fn digits_not_followed_by_space_or_hyphen_are_continuation() {
        assert_eq!(classify_line("200 OK"), LineKind::Final(200));
        assert_eq!(classify_line("200-Start"), LineKind::BlockStart(200));
        assert_eq!(classify_line("200OK"), LineKind::Continuation);
        assert_eq!(classify_line(" 200 OK"), LineKind::Continuation);
        assert_eq!(classify_line("ab1 OK"), LineKind::Continuation);
        assert_eq!(classify_line("20 OK"), LineKind::Continuation);
    }

    #[test]
    fn reply_classes_are_distinguished() {
        let preliminary = Reply {
            code: 150,
            text: "150 Opening".into(),
        };
        assert!(preliminary.is_preliminary());
        assert!(!preliminary.is_positive());

        let failure = Reply {
            code: 550,
            text: "550 Not found".into(),
        };
        assert!(!failure.is_positive());
        assert!(!failure.is_preliminary());

        let intermediate = Reply {
            code: 331,
            text: "331 Need password".into(),
        };
        assert!(intermediate.is_positive());
    }

    #[test]
    fn a_summary_uses_the_first_line() {
        let reply = Reply {
            code: 550,
            text: "550 Permission denied\nmore".into(),
        };
        assert_eq!(reply.summary(), "550 Permission denied");
    }

    #[test]
    fn quoted_pathnames_are_extracted() {
        assert_eq!(
            parse_pathname(r#"257 "/home/user" is the current directory"#).as_deref(),
            Some("/home/user")
        );
        assert_eq!(parse_pathname(r#"257 "/" created"#).as_deref(), Some("/"));
    }

    #[test]
    fn doubled_quotes_inside_a_pathname_are_unescaped() {
        assert_eq!(
            parse_pathname(r#"257 "/od""d" created"#).as_deref(),
            Some(r#"/od"d"#)
        );
    }

    #[test]
    fn an_unquoted_pathname_reply_yields_nothing() {
        assert_eq!(parse_pathname("257 no quotes here"), None);
    }

    #[test]
    fn passive_replies_yield_host_and_port() {
        let (host, port) = parse_pasv("227 Entering Passive Mode (192,168,1,5,19,138)").unwrap();
        assert_eq!(host, "192.168.1.5");
        assert_eq!(port, 19 * 256 + 138);
    }

    #[test]
    fn passive_parsing_uses_the_last_parenthesised_group() {
        // Some servers put a hint in parentheses before the real tuple.
        let (host, port) =
            parse_pasv("227 (this server) Entering Passive Mode (10,0,0,1,4,1)").unwrap();
        assert_eq!(host, "10.0.0.1");
        assert_eq!(port, 1025);
    }

    #[test]
    fn malformed_passive_replies_are_rejected() {
        assert_eq!(parse_pasv("227 Entering Passive Mode (1,2,3)"), None);
        assert_eq!(
            parse_pasv("227 Entering Passive Mode (1,2,3,4,5,999)"),
            None
        );
        assert_eq!(parse_pasv("227 no parens"), None);
    }

    #[test]
    fn extended_passive_replies_yield_a_port() {
        assert_eq!(
            parse_epsv("229 Entering Extended Passive Mode (|||49153|)"),
            Some(49153)
        );
    }

    #[test]
    fn extended_passive_parsing_reads_the_delimiter_from_the_reply() {
        // RFC 2428 allows any printable delimiter, not just '|'.
        assert_eq!(
            parse_epsv("229 Entering Extended Passive Mode (!!!50000!)"),
            Some(50000)
        );
    }

    #[test]
    fn malformed_extended_passive_replies_are_rejected() {
        assert_eq!(parse_epsv("229 Entering Extended Passive Mode (|||)"), None);
        assert_eq!(parse_epsv("229 nothing here"), None);
    }

    #[test]
    fn modification_times_parse_from_the_213_reply() {
        let parsed = parse_mdtm("213 20260304090500").unwrap();
        assert_eq!(
            parsed.format("%Y-%m-%d %H:%M:%S").to_string(),
            "2026-03-04 09:05:00"
        );
    }

    #[test]
    fn modification_times_ignore_fractional_seconds() {
        let parsed = parse_mdtm("213 20260304090500.123").unwrap();
        assert_eq!(
            parsed.format("%Y-%m-%d %H:%M:%S").to_string(),
            "2026-03-04 09:05:00"
        );
    }

    #[test]
    fn a_short_modification_time_is_rejected() {
        assert_eq!(parse_mdtm("213 2026"), None);
    }

    #[test]
    fn sizes_parse_from_the_213_reply() {
        assert_eq!(parse_size("213 4096"), Some(4096));
        assert_eq!(parse_size("213 not-a-number"), None);
        assert_eq!(parse_size("213"), None);
    }
}
