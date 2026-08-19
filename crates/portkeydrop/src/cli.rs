//! Command line handling.
//!
//! Deliberately small: this is a GUI app, and the flags exist for getting a log
//! out of a user who has hit a problem.

/// What the command line asked for.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Options {
    /// Log everything, not just warnings.
    pub debug: bool,
    /// Also write the log to this file.
    pub log_file: Option<String>,
    /// Print the version and exit.
    pub show_version: bool,
    /// Print usage and exit.
    pub show_help: bool,
    /// An unrecognised argument, if any.
    pub unknown: Option<String>,
}

/// Usage text.
pub const USAGE: &str = "\
Portkey Drop — a keyboard-first file transfer client.

Usage: portkeydrop [options]

Options:
  --debug            Log everything, not just warnings
  --log=<file>       Also write the log to <file>
  --version          Print the version and exit
  --help             Print this message and exit
";

/// Parse arguments, excluding the program name.
pub fn parse<I, S>(arguments: I) -> Options
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut options = Options::default();
    for argument in arguments {
        let argument = argument.as_ref();
        match argument {
            "--debug" | "-d" => options.debug = true,
            "--version" | "-V" => options.show_version = true,
            "--help" | "-h" | "-?" => options.show_help = true,
            _ if argument.starts_with("--log=") => {
                let path = argument.trim_start_matches("--log=").trim();
                if !path.is_empty() {
                    options.log_file = Some(path.to_string());
                }
            }
            // An unknown flag is worth reporting; a bare word is not, since it
            // is most likely a file association or a shell artefact.
            _ if argument.starts_with('-') && options.unknown.is_none() => {
                options.unknown = Some(argument.to_string());
            }
            _ => {}
        }
    }
    options
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_arguments_yields_the_defaults() {
        let options = parse(Vec::<String>::new());
        assert_eq!(options, Options::default());
        assert!(!options.debug);
        assert!(options.log_file.is_none());
    }

    #[test]
    fn the_debug_flag_is_recognised_in_both_spellings() {
        assert!(parse(["--debug"]).debug);
        assert!(parse(["-d"]).debug);
    }

    #[test]
    fn a_log_file_is_taken_from_the_flag() {
        assert_eq!(
            parse(["--log=run.txt"]).log_file.as_deref(),
            Some("run.txt")
        );
    }

    #[test]
    fn an_empty_log_path_is_ignored() {
        // `--log=` with nothing after it would otherwise try to open "".
        assert_eq!(parse(["--log="]).log_file, None);
        assert_eq!(parse(["--log=   "]).log_file, None);
    }

    #[test]
    fn version_and_help_are_recognised() {
        assert!(parse(["--version"]).show_version);
        assert!(parse(["-V"]).show_version);
        assert!(parse(["--help"]).show_help);
        assert!(parse(["-h"]).show_help);
    }

    #[test]
    fn flags_can_be_combined() {
        let options = parse(["--debug", "--log=run.txt"]);
        assert!(options.debug);
        assert_eq!(options.log_file.as_deref(), Some("run.txt"));
    }

    #[test]
    fn an_unknown_flag_is_reported() {
        assert_eq!(parse(["--wat"]).unknown.as_deref(), Some("--wat"));
    }

    #[test]
    fn a_bare_word_is_not_treated_as_an_error() {
        // File associations and shell artefacts arrive this way; refusing to
        // start over one would be worse than ignoring it.
        assert_eq!(parse(["somefile.txt"]).unknown, None);
    }

    #[test]
    fn only_the_first_unknown_flag_is_reported() {
        assert_eq!(parse(["--wat", "--eh"]).unknown.as_deref(), Some("--wat"));
    }

    #[test]
    fn the_usage_text_lists_every_flag() {
        for flag in ["--debug", "--log=", "--version", "--help"] {
            assert!(USAGE.contains(flag), "usage does not mention {flag}");
        }
    }
}
