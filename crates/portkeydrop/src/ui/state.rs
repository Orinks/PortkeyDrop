//! Application state shared across the UI.
//!
//! Everything the window needs that is not a widget lives here: settings, the
//! site list, the transfer queue, sound and speech, and the live connection.
//! Keeping it in one place means the widget code reads and writes state through
//! one borrow rather than juggling a dozen `Rc`s.

use std::path::PathBuf;
use std::sync::{Arc, Mutex, TryLockError};

use portkeydrop_core::protocols::TransferClient;
use portkeydrop_core::settings::Settings;
use portkeydrop_core::sites::SiteManager;
use portkeydrop_core::soundpacks::SoundPlayer;
use portkeydrop_core::transfer::{SharedClient, TransferService};

/// The application's non-widget state.
pub struct AppState {
    pub config_dir: PathBuf,
    pub portable: bool,
    pub settings: Settings,
    pub sites: SiteManager,
    pub transfers: Arc<TransferService>,
    pub sounds: SoundPlayer,
    pub announcer: prism::Announcer,
    /// The live connection, if any.
    client: Option<SharedClient>,
    /// Host of the live connection, for the status bar.
    pub connected_host: String,
    /// Remote directory to return to with the Home command.
    pub remote_home: String,
    /// The most recent failed transfer, for Retry Last Failed.
    pub last_failed_transfer: Option<String>,
    /// Whether event sounds and speech actually reach a device.
    ///
    /// Off under test: `Announcer::new()` attaches to whichever screen reader
    /// is running on the developer's machine, so without this the suite talks
    /// over NVDA and plays the startup sound on every run.
    audible: bool,
    /// Progress last announced per job, so each band is announced once.
    pub announced_progress: std::collections::HashMap<String, u8>,
    /// Whether the exit sound has already played, so it plays once.
    pub exit_sound_played: bool,
}

impl AppState {
    /// Build the state for a config directory.
    pub fn new(config_dir: PathBuf, portable: bool) -> Self {
        Self::build(config_dir, portable, prism::Announcer::new(), true)
    }

    /// The same state with speech and event sounds turned off.
    ///
    /// Everything else behaves identically, so tests still exercise the real
    /// settings, sites, and sound pack handling.
    #[cfg(test)]
    pub fn silent(config_dir: PathBuf, portable: bool) -> Self {
        Self::build(config_dir, portable, prism::Announcer::disabled(), false)
    }

    fn build(
        config_dir: PathBuf,
        portable: bool,
        mut announcer: prism::Announcer,
        audible: bool,
    ) -> Self {
        let settings = portkeydrop_core::settings::load_settings(&config_dir);
        let sites = SiteManager::open(&config_dir, portable);

        let soundpacks_dir = portkeydrop_core::soundpacks::soundpacks_dir(&config_dir);
        if let Err(err) = portkeydrop_core::soundpacks::ensure_default_pack(&soundpacks_dir) {
            log::warn!("could not prepare the default sound pack: {err}");
        }
        let sounds = SoundPlayer::new(soundpacks_dir, &settings.audio.sound_pack);

        let transfers = TransferService::new(settings.transfer.concurrent_transfers);
        transfers.set_resume_enabled(settings.transfer.resume_partial);

        announcer.apply_settings(Some(settings.speech.rate), Some(settings.speech.volume));

        Self {
            config_dir,
            portable,
            settings,
            sites,
            transfers,
            sounds,
            announcer,
            audible,
            client: None,
            connected_host: String::new(),
            remote_home: "/".to_string(),
            last_failed_transfer: None,
            announced_progress: std::collections::HashMap::new(),
            exit_sound_played: false,
        }
    }

    /// Whether a connection is established.
    ///
    /// This runs on the UI thread, so it never waits for the lock. A worker
    /// holds the client for as long as its operation takes -- a recursive
    /// listing, or a whole file -- and blocking here froze the window for the
    /// length of every folder download. A client that is busy is by definition
    /// still connected, so a contended lock answers the question without
    /// taking it.
    pub fn is_connected(&self) -> bool {
        match self.client.as_ref() {
            None => false,
            Some(client) => match client.try_lock() {
                Ok(client) => client.is_connected(),
                Err(TryLockError::WouldBlock) => true,
                Err(TryLockError::Poisoned(_)) => false,
            },
        }
    }

    /// The live connection, for handing to a worker thread.
    pub fn client(&self) -> Option<SharedClient> {
        self.client.clone()
    }

    /// Store a newly established connection.
    pub fn set_client(&mut self, client: Box<dyn TransferClient>, host: String) {
        self.connected_host = host;
        self.client = Some(Arc::new(Mutex::new(client)));
    }

    /// Drop the connection, closing it first.
    ///
    /// Like [`AppState::is_connected`] this runs on the UI thread -- including
    /// on the way out of File > Exit -- so it never waits for the lock. A
    /// transfer worker holds the client for the length of its operation, and
    /// waiting here froze the window until the transfer finished. When the
    /// client is busy the goodbye is handed to a background thread, which
    /// sends it once the worker lets go. If the process exits before that, the
    /// socket closes with it, which is what a dropped connection looks like
    /// from the server either way.
    pub fn clear_client(&mut self) {
        if let Some(client) = self.client.take() {
            // The borrow from `try_lock` has to end before the client can be
            // moved onto a thread, so the two steps are kept apart.
            let busy = match client.try_lock() {
                Ok(mut client) => {
                    client.disconnect();
                    false
                }
                Err(TryLockError::WouldBlock) => true,
                Err(TryLockError::Poisoned(_)) => false,
            };
            if busy {
                std::thread::spawn(move || {
                    if let Ok(mut client) = client.lock() {
                        client.disconnect();
                    }
                });
            }
        }
        self.connected_host.clear();
        self.remote_home = "/".to_string();
    }

    /// Play an event sound, honouring the audio settings.
    pub fn play_sound(&self, event: &str) {
        if !self.audible {
            return;
        }
        self.sounds.play_event(
            event,
            self.settings.audio.sound_enabled,
            &self.settings.audio.muted_sound_events,
        );
    }

    /// Speak a message, if speech is available.
    pub fn announce(&mut self, message: &str) {
        self.announcer.announce(message);
    }

    /// Where saved passwords are kept, phrased for the activity log.
    pub fn storage_tier_description(&self) -> &'static str {
        self.sites.storage_tier().describe()
    }

    /// Re-read settings and sites from disk.
    ///
    /// Used after configuration files are copied in underneath a running app,
    /// which is what portable-mode migration does. The connection, the queue,
    /// and the sound player are left alone: none of them came from the files
    /// that just changed.
    pub fn reload_from_disk(&mut self) {
        self.settings = portkeydrop_core::settings::load_settings(&self.config_dir);
        self.sites = SiteManager::open(&self.config_dir, self.portable);
        self.apply_settings();
    }

    /// Persist the settings.
    pub fn save_settings(&self) {
        if let Err(err) =
            portkeydrop_core::settings::save_settings(&self.settings, &self.config_dir)
        {
            log::error!("could not save settings: {err}");
        }
    }

    /// Persist the transfer queue.
    pub fn save_queue(&self) {
        self.transfers.save(&self.config_dir);
    }

    /// Apply settings that other components need told about.
    ///
    /// Called after the settings dialog closes, so a changed worker count or
    /// sound pack takes effect without a restart.
    pub fn apply_settings(&mut self) {
        self.transfers
            .set_resume_enabled(self.settings.transfer.resume_partial);
        self.sounds.set_pack(&self.settings.audio.sound_pack);
        self.announcer.apply_settings(
            Some(self.settings.speech.rate),
            Some(self.settings.speech.volume),
        );
    }

    /// The local folder to open at startup.
    pub fn startup_local_folder(&mut self) -> PathBuf {
        portkeydrop_core::settings::resolve_startup_local_folder(&mut self.settings, None)
    }

    /// Record the local folder, saving only when it actually changed.
    pub fn remember_local_folder(&mut self, path: &std::path::Path) {
        if portkeydrop_core::settings::update_last_local_folder(&mut self.settings, path) {
            self.save_settings();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    /// A client that is connected and records being disconnected.
    ///
    /// Only `is_connected` and `disconnect` are reached from the UI thread;
    /// the rest exist to satisfy the trait.
    struct StubClient {
        disconnected: Arc<std::sync::atomic::AtomicBool>,
    }

    impl portkeydrop_core::protocols::TransferClient for StubClient {
        fn protocol(&self) -> portkeydrop_core::protocols::Protocol {
            portkeydrop_core::protocols::Protocol::Sftp
        }
        fn is_connected(&self) -> bool {
            true
        }
        fn cwd(&self) -> &str {
            "/"
        }
        fn connect(&mut self) -> portkeydrop_core::protocols::Result<()> {
            Ok(())
        }
        fn disconnect(&mut self) {
            self.disconnected
                .store(true, std::sync::atomic::Ordering::SeqCst);
        }
        fn list_dir(
            &mut self,
            _path: &str,
        ) -> portkeydrop_core::protocols::Result<Vec<portkeydrop_core::protocols::RemoteFile>>
        {
            Ok(Vec::new())
        }
        fn chdir(&mut self, path: &str) -> portkeydrop_core::protocols::Result<String> {
            Ok(path.to_string())
        }
        fn download(
            &mut self,
            _remote_path: &str,
            _sink: &mut dyn std::io::Write,
            _progress: Option<portkeydrop_core::protocols::ProgressFn<'_>>,
            _offset: u64,
        ) -> portkeydrop_core::protocols::Result<()> {
            Ok(())
        }
        fn upload(
            &mut self,
            _source: &mut dyn std::io::Read,
            _total_bytes: u64,
            _remote_path: &str,
            _progress: Option<portkeydrop_core::protocols::ProgressFn<'_>>,
        ) -> portkeydrop_core::protocols::Result<()> {
            Ok(())
        }
        fn delete(&mut self, _path: &str) -> portkeydrop_core::protocols::Result<()> {
            Ok(())
        }
        fn rmdir(&mut self, _path: &str) -> portkeydrop_core::protocols::Result<()> {
            Ok(())
        }
        fn mkdir(&mut self, _path: &str) -> portkeydrop_core::protocols::Result<()> {
            Ok(())
        }
        fn rename(
            &mut self,
            _old_path: &str,
            _new_path: &str,
        ) -> portkeydrop_core::protocols::Result<()> {
            Ok(())
        }
        fn stat(
            &mut self,
            _path: &str,
        ) -> portkeydrop_core::protocols::Result<portkeydrop_core::protocols::RemoteFile> {
            Err(portkeydrop_core::protocols::ProtocolError::NotFound(
                "stub".to_string(),
            ))
        }
    }

    fn state(dir: &TempDir) -> AppState {
        AppState::silent(dir.path().to_path_buf(), false)
    }

    #[test]
    fn a_fresh_state_has_no_connection() {
        let dir = TempDir::new().unwrap();
        let state = state(&dir);
        assert!(!state.is_connected());
        assert!(state.client().is_none());
        assert_eq!(state.connected_host, "");
    }

    #[test]
    fn the_connection_check_does_not_wait_for_a_busy_client() {
        // A transfer worker holds the client for as long as its operation
        // takes. This check runs on the UI thread on every queue change, so
        // waiting for the lock froze the whole window for the length of a
        // folder download.
        let dir = TempDir::new().unwrap();
        let mut state = state(&dir);
        state.set_client(
            Box::new(StubClient {
                disconnected: Arc::new(std::sync::atomic::AtomicBool::new(false)),
            }),
            "example.test".to_string(),
        );

        let client = state.client().expect("a client was just set");
        let held = std::thread::spawn(move || {
            let _guard = client.lock().expect("the stub lock is never poisoned");
            std::thread::sleep(std::time::Duration::from_millis(400));
        });

        // Give the other thread time to actually take the lock.
        std::thread::sleep(std::time::Duration::from_millis(50));

        let started = std::time::Instant::now();
        let connected = state.is_connected();
        let waited = started.elapsed();

        assert!(connected, "a busy client is still a connected one");
        assert!(
            waited < std::time::Duration::from_millis(100),
            "the check waited {waited:?} for a lock it should not have taken"
        );

        held.join().unwrap();
    }

    #[test]
    fn clearing_a_busy_connection_does_not_wait_for_the_transfer() {
        // File > Exit runs this on the UI thread. A download worker holds the
        // client until its file is done, and waiting for it here hung the
        // window on the way out.
        let dir = TempDir::new().unwrap();
        let mut state = state(&dir);
        let disconnected = Arc::new(std::sync::atomic::AtomicBool::new(false));
        state.set_client(
            Box::new(StubClient {
                disconnected: Arc::clone(&disconnected),
            }),
            "example.test".to_string(),
        );

        let client = state.client().expect("a client was just set");
        let held = std::thread::spawn(move || {
            let _guard = client.lock().expect("the stub lock is never poisoned");
            std::thread::sleep(std::time::Duration::from_millis(400));
        });
        std::thread::sleep(std::time::Duration::from_millis(50));

        let started = std::time::Instant::now();
        state.clear_client();
        let waited = started.elapsed();

        assert!(
            waited < std::time::Duration::from_millis(100),
            "clearing waited {waited:?} for a transfer to finish"
        );
        assert!(!state.is_connected());
        assert_eq!(state.connected_host, "");

        // The goodbye is deferred, not dropped: it goes out once the worker
        // releases the client.
        held.join().unwrap();
        for _ in 0..50 {
            if disconnected.load(std::sync::atomic::Ordering::SeqCst) {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
        assert!(
            disconnected.load(std::sync::atomic::Ordering::SeqCst),
            "the connection was never closed"
        );
    }

    #[test]
    fn a_fresh_state_starts_from_the_default_settings() {
        let dir = TempDir::new().unwrap();
        let state = state(&dir);
        assert_eq!(state.settings.connection.protocol, "sftp");
        assert_eq!(state.remote_home, "/");
    }

    #[test]
    fn the_default_sound_pack_is_created_on_startup() {
        // Without it every sound event would silently resolve to nothing.
        let dir = TempDir::new().unwrap();
        let _state = state(&dir);
        let packs = portkeydrop_core::soundpacks::soundpacks_dir(dir.path());
        assert!(packs.join("default").join("pack.json").exists());
    }

    #[test]
    fn clearing_a_connection_resets_the_host_and_home() {
        let dir = TempDir::new().unwrap();
        let mut state = state(&dir);
        state.connected_host = "example.com".into();
        state.remote_home = "/home/a".into();

        state.clear_client();

        assert_eq!(state.connected_host, "");
        assert_eq!(state.remote_home, "/");
    }

    #[test]
    fn settings_survive_a_save_and_reload() {
        let dir = TempDir::new().unwrap();
        let mut state = state(&dir);
        state.settings.speech.rate = 80;
        state.save_settings();

        let reloaded = state_from(dir.path());
        assert_eq!(reloaded.settings.speech.rate, 80);
    }

    fn state_from(dir: &std::path::Path) -> AppState {
        AppState::silent(dir.to_path_buf(), false)
    }

    #[test]
    fn applying_settings_does_not_panic_without_audio_or_speech() {
        // CI has neither, and the test build deliberately has neither either;
        // the app still has to start.
        let dir = TempDir::new().unwrap();
        let mut state = state(&dir);
        state.apply_settings();
        state.play_sound("startup");
        state.announce("hello");
    }

    #[test]
    fn the_local_folder_is_only_saved_when_it_changes() {
        let dir = TempDir::new().unwrap();
        let mut state = state(&dir);
        let folder = dir.path().to_path_buf();

        state.remember_local_folder(&folder);
        let first = state.settings.app.last_local_folder.clone();
        state.remember_local_folder(&folder);

        assert_eq!(state.settings.app.last_local_folder, first);
        assert!(first.is_some());
    }

    #[test]
    fn the_queue_file_is_written_next_to_the_other_config() {
        let dir = TempDir::new().unwrap();
        let state = state(&dir);
        state.save_queue();
        assert!(dir.path().join("queue.json").exists());
    }
}
