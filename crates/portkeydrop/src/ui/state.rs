//! Application state shared across the UI.
//!
//! Everything the window needs that is not a widget lives here: settings, the
//! site list, the transfer queue, sound and speech, and the live connection.
//! Keeping it in one place means the widget code reads and writes state through
//! one borrow rather than juggling a dozen `Rc`s.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

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
    pub fn is_connected(&self) -> bool {
        self.client
            .as_ref()
            .and_then(|client| client.lock().ok().map(|client| client.is_connected()))
            .unwrap_or(false)
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
    pub fn clear_client(&mut self) {
        if let Some(client) = self.client.take() {
            if let Ok(mut client) = client.lock() {
                client.disconnect();
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
