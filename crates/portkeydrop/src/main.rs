//! Portkey Drop's entry point.

use portkeydrop_app::cli;
use portkeydrop_app::single_instance::{InstanceCheck, SingleInstance};
use portkeydrop_app::ui::state::AppState;
use portkeydrop_app::ui::MainFrame;

fn main() {
    let options = cli::parse(std::env::args().skip(1));

    if options.show_help {
        println!("{}", cli::USAGE);
        return;
    }
    if options.show_version {
        println!(
            "{} {}",
            portkeydrop_core::APP_NAME,
            portkeydrop_core::VERSION
        );
        return;
    }
    if let Some(unknown) = options.unknown.as_deref() {
        eprintln!("Unrecognised option: {unknown}\n");
        eprintln!("{}", cli::USAGE);
        std::process::exit(2);
    }

    init_logging(&options);

    // A second launch brings the running window forward rather than opening a
    // rival window: two instances sharing one queue file would lose transfers.
    let (_instance, check) = SingleInstance::acquire();
    if check == InstanceCheck::AlreadyRunning {
        log::info!("another instance is already running; bringing it to the front");
        return;
    }

    let portable = portkeydrop_core::portable::is_portable_mode();
    let config_dir = portkeydrop_core::portable::config_dir();
    if let Err(err) = std::fs::create_dir_all(&config_dir) {
        eprintln!(
            "Could not create the configuration folder {}: {err}",
            config_dir.display()
        );
        std::process::exit(1);
    }
    log::info!(
        "starting {} {} ({} mode), configuration in {}",
        portkeydrop_core::APP_NAME,
        portkeydrop_core::VERSION,
        if portable { "portable" } else { "installed" },
        config_dir.display()
    );

    let _ = wxdragon::main(move |_| {
        let state = AppState::new(config_dir.clone(), portable);
        let frame = MainFrame::create(state);
        wxdragon::set_top_window(&frame.frame);
    });
}

/// Set up logging from the command line options.
///
/// Warnings and errors go to stderr by default; `--debug` widens that, and
/// `--log=` adds a file, which is what a user can be asked for when something
/// goes wrong.
fn init_logging(options: &cli::Options) {
    let level = if options.debug {
        log::LevelFilter::Debug
    } else {
        log::LevelFilter::Warn
    };

    let mut builder = env_logger::Builder::new();
    builder.filter_level(level);
    // RUST_LOG still wins, so a user can be given a more targeted filter.
    builder.parse_default_env();

    if let Some(path) = options.log_file.as_deref() {
        match std::fs::File::create(path) {
            Ok(file) => {
                builder.target(env_logger::Target::Pipe(Box::new(file)));
            }
            Err(err) => eprintln!("Could not open the log file {path}: {err}"),
        }
    }

    // A second initialisation only happens in tests; ignoring it keeps the
    // failure from being fatal.
    let _ = builder.try_init();
}
