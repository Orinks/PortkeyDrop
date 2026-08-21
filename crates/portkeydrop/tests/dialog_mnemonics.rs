//! Every Alt+letter in a dialog must reach one control.
//!
//! Two controls sharing a letter is not a cosmetic problem: Alt+L cycles
//! between them instead of activating either, so a keyboard user cannot reach
//! the control they meant. The Python release fixed a batch of these and the
//! port reintroduced them, which is what this exists to stop.
//!
//! Read from the source rather than the built dialog, because building one
//! needs a display and this has to run in CI.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

fn dialog_source(name: &str) -> String {
    let path: PathBuf = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("src")
        .join("ui")
        .join("dialogs")
        .join(name);
    std::fs::read_to_string(&path).unwrap_or_else(|err| panic!("reading {path:?}: {err}"))
}

/// Every `&x` mnemonic in a quoted label, lowercased, with its label.
///
/// `&&` is an escaped ampersand rather than a mnemonic, so it is skipped.
fn mnemonics(source: &str) -> Vec<(char, String)> {
    let mut found = Vec::new();
    for literal in quoted_literals(source) {
        let bytes: Vec<char> = literal.chars().collect();
        let mut index = 0;
        while index + 1 < bytes.len() {
            if bytes[index] == '&' {
                if bytes[index + 1] == '&' {
                    index += 2;
                    continue;
                }
                if bytes[index + 1].is_ascii_alphanumeric() {
                    found.push((bytes[index + 1].to_ascii_lowercase(), literal.clone()));
                }
            }
            index += 1;
        }
    }
    found
}

/// The contents of every double-quoted string literal in the source.
fn quoted_literals(source: &str) -> Vec<String> {
    let mut literals = Vec::new();
    let mut chars = source.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '"' {
            continue;
        }
        let mut literal = String::new();
        while let Some(c) = chars.next() {
            match c {
                '\\' => {
                    chars.next();
                }
                '"' => break,
                _ => literal.push(c),
            }
        }
        literals.push(literal);
    }
    literals
}

fn assert_unique(name: &str) {
    let source = dialog_source(name);
    let mut by_letter: BTreeMap<char, Vec<String>> = BTreeMap::new();
    for (letter, label) in mnemonics(&source) {
        by_letter.entry(letter).or_default().push(label);
    }

    let clashes: Vec<String> = by_letter
        .iter()
        .filter(|(_, labels)| {
            // The same label appearing twice is one control referred to in two
            // places, not two controls competing.
            let mut unique: Vec<String> = (*labels).clone();
            unique.sort();
            unique.dedup();
            unique.len() > 1
        })
        .map(|(letter, labels)| format!("Alt+{letter} -> {labels:?}"))
        .collect();

    assert!(
        clashes.is_empty(),
        "{name} has access keys reaching more than one control: {}",
        clashes.join("; ")
    );
}

#[test]
fn the_site_manager_access_keys_are_unique() {
    assert_unique("site_manager.rs");
}

#[test]
fn the_settings_access_keys_are_unique_within_each_page() {
    // Settings is a notebook. Only one page shows at a time, so two pages may
    // reuse a letter without competing -- checking the file as a whole would
    // report clashes that a user can never encounter. Each page is its own
    // namespace; the tab titles are checked together, since they are all
    // reachable at once.
    let source = dialog_source("settings.rs");
    let mut pages: Vec<(String, String)> = Vec::new();

    let mut remaining = source.as_str();
    while let Some(start) = remaining.find("fn build_") {
        let after = &remaining[start..];
        let name_end = after.find('(').unwrap_or(after.len());
        let name = after[..name_end].trim_start_matches("fn ").to_string();
        let body = match after[name_end..].find("\nfn ") {
            Some(end) => &after[name_end..name_end + end],
            None => &after[name_end..],
        };
        pages.push((name, body.to_string()));
        remaining = &after[name_end..];
    }

    assert!(
        pages.len() >= 5,
        "expected a page per settings tab, found {}",
        pages.len()
    );

    for (name, body) in pages {
        let mut by_letter: BTreeMap<char, Vec<String>> = BTreeMap::new();
        for (letter, label) in mnemonics(&body) {
            by_letter.entry(letter).or_default().push(label);
        }
        let clashes: Vec<String> = by_letter
            .iter()
            .filter(|(_, labels)| {
                let mut unique: Vec<String> = (*labels).clone();
                unique.sort();
                unique.dedup();
                unique.len() > 1
            })
            .map(|(letter, labels)| format!("Alt+{letter} -> {labels:?}"))
            .collect();
        assert!(
            clashes.is_empty(),
            "{name} has access keys reaching more than one control: {}",
            clashes.join("; ")
        );
    }
}

#[test]
fn the_import_access_keys_are_unique() {
    assert_unique("import.rs");
}

#[test]
fn the_transfer_queue_access_keys_are_unique() {
    assert_unique("transfer_queue.rs");
}

#[test]
fn the_sound_pack_access_keys_are_unique() {
    assert_unique("soundpacks.rs");
}

#[test]
fn the_host_key_access_keys_are_unique() {
    assert_unique("host_key.rs");
}

#[test]
fn the_scanner_finds_the_mnemonics_it_should_and_ignores_the_rest() {
    // Guards the test itself: a scanner that quietly found nothing would make
    // every dialog above pass.
    let source = r#"
        let a = "&Save";
        let b = "Cance&l";
        let c = "Fish && Chips";
        let d = "no mnemonic here";
    "#;
    let found: Vec<char> = mnemonics(source).into_iter().map(|(c, _)| c).collect();
    assert_eq!(found, vec!['s', 'l']);
}
