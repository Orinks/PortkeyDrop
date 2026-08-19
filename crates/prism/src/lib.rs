//! Safe wrapper over the Prism speech library.
//!
//! Prism talks to whichever screen reader or TTS engine is present (NVDA,
//! JAWS, SAPI, VoiceOver, Speech Dispatcher, Orca...). Portkey Drop needs a
//! small slice of that: pick the best available backend, speak a string, and
//! nudge rate/volume when the backend accepts them.
//!
//! Every operation degrades gracefully. If Prism is missing, no backend is
//! available, or a backend rejects a property, callers get `false`/`Err`
//! rather than a panic — announcements are an enhancement, never a hard
//! dependency.

use std::ffi::{CStr, CString};
use std::fmt;
use std::ptr;
use std::sync::{Mutex, OnceLock};

use prism_sys::Api;

/// Errors surfaced by the safe wrapper.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// The Prism shared library could not be loaded or initialised.
    #[error("Prism is not available on this system")]
    Unavailable,
    /// Prism is already running in this process.
    ///
    /// Its Linux build allows one context at a time; a second alive alongside
    /// the first crashes the process rather than failing, so it is refused
    /// here instead.
    #[error("Prism is already running in this process")]
    AlreadyRunning,
    /// No speech backend is usable right now (no screen reader, no TTS).
    #[error("no speech backend is available")]
    NoBackend,
    /// Text contained an interior NUL and cannot cross the C boundary.
    #[error("text contains an interior NUL byte")]
    InteriorNul,
    /// The native call returned a non-zero `PrismError`.
    #[error("prism error {code}: {message}")]
    Native { code: i32, message: String },
}

/// Whether the native Prism library was found and loaded.
pub fn native_available() -> bool {
    Api::get().is_some()
}

/// Turn a native return code into a `Result`, resolving its message text.
fn check(api: &Api, code: i32) -> Result<(), Error> {
    if code == prism_sys::PRISM_OK {
        return Ok(());
    }
    // SAFETY: `error_string` returns a static NUL-terminated string owned by
    // the library, valid for any code value.
    let message = unsafe {
        let text = (api.error_string)(code);
        if text.is_null() {
            String::from("unknown error")
        } else {
            CStr::from_ptr(text).to_string_lossy().into_owned()
        }
    };
    Err(Error::Native { code, message })
}

/// Read a `const char *` returned by Prism into an owned `String`.
///
/// # Safety
/// `text` must be NUL-terminated or null.
unsafe fn owned_string(text: *const std::os::raw::c_char, fallback: &str) -> String {
    if text.is_null() {
        fallback.to_string()
    } else {
        CStr::from_ptr(text).to_string_lossy().into_owned()
    }
}

/// Whether a [`Context`] is currently live, and the lock guarding that.
///
/// Prism's Linux build allows one context per process. A second one alive at
/// the same time segfaults, and start-up of two at once also races the GObject
/// type registration in the glib it carries with it: glib reports "cannot
/// register existing type" for everything registered twice and the process can
/// abort on a double free.
///
/// Both were found by running this crate's tests on Linux. The harness runs
/// tests in parallel threads within one process, so two tests each building an
/// `Announcer` overlap; individually every one of them passes.
///
/// `Context::new` is safe Rust, so it must not be able to crash the process no
/// matter how it is called. It refuses rather than starting a second context,
/// and `Announcer` treats that refusal the same as Prism being absent: silent,
/// and honest about being unavailable.
fn context_live() -> &'static Mutex<bool> {
    static LIVE: OnceLock<Mutex<bool>> = OnceLock::new();
    LIVE.get_or_init(|| Mutex::new(false))
}

/// Take the lock, ignoring poisoning.
///
/// A panic elsewhere leaves it poisoned, but refusing all speech from then on
/// would be a worse outcome than continuing with the flag as it stands.
fn lock_live() -> std::sync::MutexGuard<'static, bool> {
    context_live().lock().unwrap_or_else(|err| err.into_inner())
}

/// A live Prism library context.
///
/// Dropping the context shuts Prism down, so it must outlive every [`Backend`]
/// taken from it. [`Announcer`] owns both together and drops them in order.
pub struct Context {
    api: &'static Api,
    raw: *mut prism_sys::PrismContext,
}

// The wrapper requires `&mut` for every mutating call, so a context may move
// between threads. Only one may exist at a time -- see [`context_live`] --
// which `Context::new` enforces rather than trusting callers with.
unsafe impl Send for Context {}

impl Context {
    /// Initialise Prism.
    ///
    /// Returns [`Error::Unavailable`] when the native library is absent or
    /// refuses to start.
    pub fn new() -> Result<Self, Error> {
        let api = Api::get().ok_or(Error::Unavailable)?;
        let mut live = lock_live();
        if *live {
            return Err(Error::AlreadyRunning);
        }
        // SAFETY: `config_init` fills a plain struct; `init` accepts a pointer
        // to it and copies what it needs. The lock is held across this so two
        // threads cannot register Prism's types at the same time.
        let raw = unsafe {
            let mut config = (api.config_init)();
            (api.init)(&mut config)
        };
        if raw.is_null() {
            return Err(Error::Unavailable);
        }
        *live = true;
        Ok(Self { api, raw })
    }

    /// Number of backends registered in this build of Prism.
    pub fn backend_count(&self) -> usize {
        unsafe { (self.api.registry_count)(self.raw) }
    }

    /// Names of all registered backends, in registry order.
    pub fn backend_names(&self) -> Vec<String> {
        (0..self.backend_count())
            .map(|index| unsafe {
                let id = (self.api.registry_id_at)(self.raw, index);
                owned_string((self.api.registry_name)(self.raw, id), "unknown")
            })
            .collect()
    }

    /// Acquire the highest-priority backend usable right now.
    pub fn acquire_best(&self) -> Result<Backend, Error> {
        let raw = unsafe { (self.api.registry_acquire_best)(self.raw) };
        self.wrap_backend(raw)
    }

    /// Acquire a specific backend by id; see [`prism_sys::backend_id`].
    pub fn acquire(&self, id: prism_sys::PrismBackendId) -> Result<Backend, Error> {
        let raw = unsafe { (self.api.registry_acquire)(self.raw, id) };
        self.wrap_backend(raw)
    }

    fn wrap_backend(&self, raw: *mut prism_sys::PrismBackend) -> Result<Backend, Error> {
        if raw.is_null() {
            return Err(Error::NoBackend);
        }
        let backend = Backend { api: self.api, raw };
        // Some backends (SAPI) need an explicit initialise before the first
        // speak; those that do not report an "already initialised" error,
        // which is not fatal.
        if let Err(err) = check(self.api, unsafe { (self.api.backend_initialize)(raw) }) {
            log::debug!("prism backend initialize returned {err}");
        }
        Ok(backend)
    }
}

impl Drop for Context {
    fn drop(&mut self) {
        if !self.raw.is_null() {
            let mut live = lock_live();
            unsafe { (self.api.shutdown)(self.raw) };
            self.raw = ptr::null_mut();
            *live = false;
        }
    }
}

/// A speech backend acquired from a [`Context`].
pub struct Backend {
    api: &'static Api,
    raw: *mut prism_sys::PrismBackend,
}

unsafe impl Send for Backend {}

impl Backend {
    /// The backend's human-readable name (`"NVDA"`, `"SAPI"`, ...).
    pub fn name(&self) -> String {
        unsafe { owned_string((self.api.backend_name)(self.raw), "unknown") }
    }

    /// Raw feature bitmask; see [`prism_sys::features`].
    pub fn features(&self) -> u64 {
        unsafe { (self.api.backend_get_features)(self.raw) }
    }

    /// Whether this backend can speak at all.
    pub fn supports_speak(&self) -> bool {
        self.features() & prism_sys::features::SUPPORTS_SPEAK != 0
    }

    /// Whether this backend can drive a braille display.
    pub fn supports_braille(&self) -> bool {
        self.features() & prism_sys::features::SUPPORTS_BRAILLE != 0
    }

    /// Speak `text`, optionally interrupting the current utterance.
    ///
    /// Routes through Prism's `output` entry point, which reaches speech and
    /// braille together on backends that support both.
    pub fn speak(&mut self, text: &str, interrupt: bool) -> Result<(), Error> {
        let text = CString::new(text).map_err(|_| Error::InteriorNul)?;
        check(self.api, unsafe {
            (self.api.backend_output)(self.raw, text.as_ptr(), interrupt)
        })
    }

    /// Stop any in-progress speech.
    pub fn stop(&mut self) -> Result<(), Error> {
        check(self.api, unsafe { (self.api.backend_stop)(self.raw) })
    }

    /// Whether the backend is currently speaking.
    pub fn is_speaking(&self) -> Result<bool, Error> {
        let mut speaking = false;
        check(self.api, unsafe {
            (self.api.backend_is_speaking)(self.raw, &mut speaking)
        })?;
        Ok(speaking)
    }

    /// Set speech rate as a 0.0–1.0 fraction; values outside are clamped.
    pub fn set_rate(&mut self, rate: f32) -> Result<(), Error> {
        check(self.api, unsafe {
            (self.api.backend_set_rate)(self.raw, rate.clamp(0.0, 1.0))
        })
    }

    /// Current speech rate as a 0.0–1.0 fraction.
    pub fn rate(&self) -> Result<f32, Error> {
        let mut rate = 0.0;
        check(self.api, unsafe {
            (self.api.backend_get_rate)(self.raw, &mut rate)
        })?;
        Ok(rate)
    }

    /// Set output volume as a 0.0–1.0 fraction; values outside are clamped.
    pub fn set_volume(&mut self, volume: f32) -> Result<(), Error> {
        check(self.api, unsafe {
            (self.api.backend_set_volume)(self.raw, volume.clamp(0.0, 1.0))
        })
    }

    /// Current output volume as a 0.0–1.0 fraction.
    pub fn volume(&self) -> Result<f32, Error> {
        let mut volume = 0.0;
        check(self.api, unsafe {
            (self.api.backend_get_volume)(self.raw, &mut volume)
        })?;
        Ok(volume)
    }
}

impl fmt::Debug for Backend {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Backend")
            .field("name", &self.name())
            .finish()
    }
}

impl Drop for Backend {
    fn drop(&mut self) {
        if !self.raw.is_null() {
            unsafe { (self.api.backend_free)(self.raw) };
            self.raw = ptr::null_mut();
        }
    }
}

/// Screen-reader announcement helper with graceful fallback.
///
/// Construction never fails. When no backend is available every announcement
/// is a silent no-op, so callers can fall back to the status bar and activity
/// log without special-casing.
pub struct Announcer {
    // Declaration order is the drop order: the backend must be released
    // before the context that produced it.
    backend: Option<Backend>,
    context: Option<Context>,
}

impl Announcer {
    /// Build an announcer, acquiring the best backend if one exists.
    pub fn new() -> Self {
        match Context::new() {
            Ok(context) => match context.acquire_best() {
                Ok(backend) => {
                    log::info!("prism backend active: {}", backend.name());
                    Self {
                        backend: Some(backend),
                        context: Some(context),
                    }
                }
                Err(err) => {
                    log::debug!("no prism backend available: {err}");
                    Self {
                        backend: None,
                        context: Some(context),
                    }
                }
            },
            Err(err) => {
                log::debug!("prism unavailable: {err}");
                Self {
                    backend: None,
                    context: None,
                }
            }
        }
    }

    /// An announcer that never speaks. Used in tests and headless runs.
    pub fn disabled() -> Self {
        Self {
            backend: None,
            context: None,
        }
    }

    /// Whether speech output is actually wired up.
    pub fn is_available(&self) -> bool {
        self.backend.as_ref().is_some_and(Backend::supports_speak)
    }

    /// Name of the active backend, if any.
    pub fn backend_name(&self) -> Option<String> {
        self.backend.as_ref().map(Backend::name)
    }

    /// Names of every backend Prism knows about, for diagnostics.
    pub fn known_backends(&self) -> Vec<String> {
        self.context
            .as_ref()
            .map(Context::backend_names)
            .unwrap_or_default()
    }

    /// Speak `text`, interrupting the current utterance.
    ///
    /// Returns whether the text actually reached a backend.
    pub fn announce(&mut self, text: &str) -> bool {
        let Some(backend) = self.backend.as_mut() else {
            return false;
        };
        match backend.speak(text, true) {
            Ok(()) => true,
            Err(err) => {
                log::warn!("failed to announce text via prism: {err}");
                false
            }
        }
    }

    /// Apply the app's 0–100 speech settings.
    ///
    /// Backends that follow the screen reader's own configuration (NVDA, JAWS)
    /// reject these; that is expected and left alone rather than reported.
    pub fn apply_settings(&mut self, rate: Option<i32>, volume: Option<i32>) {
        let Some(backend) = self.backend.as_mut() else {
            return;
        };
        if let Some(rate) = rate {
            if let Err(err) = backend.set_rate(percent_to_fraction(rate)) {
                log::debug!("backend does not accept a speech rate: {err}");
            }
        }
        if let Some(volume) = volume {
            if let Err(err) = backend.set_volume(percent_to_fraction(volume)) {
                log::debug!("backend does not accept a speech volume: {err}");
            }
        }
    }
}

impl Default for Announcer {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Debug for Announcer {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Announcer")
            .field("available", &self.is_available())
            .field("backend", &self.backend_name())
            .finish()
    }
}

/// Convert a 0–100 setting into the 0.0–1.0 fraction Prism expects.
pub fn percent_to_fraction(percent: i32) -> f32 {
    percent.clamp(0, 100) as f32 / 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percent_to_fraction_clamps_and_scales() {
        assert_eq!(percent_to_fraction(0), 0.0);
        assert_eq!(percent_to_fraction(50), 0.5);
        assert_eq!(percent_to_fraction(100), 1.0);
        assert_eq!(percent_to_fraction(-20), 0.0);
        assert_eq!(percent_to_fraction(250), 1.0);
    }

    #[test]
    fn disabled_announcer_is_silent_and_reports_unavailable() {
        let mut announcer = Announcer::disabled();
        assert!(!announcer.is_available());
        assert!(!announcer.announce("hello"));
        assert_eq!(announcer.backend_name(), None);
        assert!(announcer.known_backends().is_empty());
        // Applying settings without a backend must not panic.
        announcer.apply_settings(Some(70), Some(90));
    }

    #[test]
    fn announcer_construction_never_panics() {
        // CI has no screen reader; this must still yield a usable (silent)
        // announcer rather than failing.
        let announcer = Announcer::new();
        let _ = announcer.is_available();
        let _ = announcer.backend_name();
    }

    #[test]
    fn announcing_with_an_interior_nul_is_reported_not_panicked() {
        // Exercised through Backend when one exists; otherwise the announcer
        // short-circuits. Either way, no panic.
        let mut announcer = Announcer::new();
        let _ = announcer.announce("bad\0text");
    }
}

// Tests that start Prism more than once per process live here in principle
// and are absent in practice. On the vendored Linux build, a second start --
// even after the first is dropped, even single-threaded -- segfaults the
// process. The guard in `Context::new` stops a second *live* context, and the
// lock stops two starting at once, but neither makes repeated start/stop
// cycles safe, because the library does not support them.
//
// The app starts Prism once and shuts down at exit, which is the shape the
// library supports. Anything that constructs an `Announcer` per operation
// would crash on Linux, so it must not.
