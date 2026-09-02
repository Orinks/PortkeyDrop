//! Sound playback.
//!
//! Sounds are feedback, never a gate on anything: if the audio device is
//! missing, busy, or the file will not decode, playback reports `false` and the
//! app carries on. Nothing here blocks the caller — a transfer must not wait on
//! a chime. The exception is [`wait_for_playback`], used on exit so the closing
//! sound is not cut off when the process dies.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use rodio::buffer::SamplesBuffer;
use rodio::source::Done;
use rodio::{Decoder, OutputStream, OutputStreamHandle, Source};

/// Longest closing will wait for the exit sound before giving up.
///
/// Playback is otherwise fire-and-forget; this cap is so a hung audio
/// device cannot trap the process.
pub const EXIT_SOUND_TIMEOUT: Duration = Duration::from_secs(8);

use super::{resolve_sound, DEFAULT_PACK};

/// The process-wide audio output.
///
/// Held in a `OnceLock` because opening the device is expensive and some
/// backends allow only one stream per process. Each sound is mixed in through
/// the shared handle.
struct AudioOutput {
    // The stream must stay alive for the handle to work, even though nothing
    // reads it directly.
    _stream: OutputStream,
    handle: OutputStreamHandle,
}

// `OutputStream` is not `Send` on every backend, so the whole output lives
// behind a mutex and is only touched while holding it.
unsafe impl Send for AudioOutput {}

fn audio_output() -> Option<&'static Mutex<AudioOutput>> {
    static OUTPUT: OnceLock<Option<Mutex<AudioOutput>>> = OnceLock::new();
    OUTPUT
        .get_or_init(|| match OutputStream::try_default() {
            Ok((stream, handle)) => Some(Mutex::new(AudioOutput {
                _stream: stream,
                handle,
            })),
            Err(err) => {
                log::info!("no audio output is available ({err}); sounds are disabled");
                None
            }
        })
        .as_ref()
}

/// How many sounds are still playing.
///
/// [`play_sound_file`] bumps this and hands the source to rodio wrapped in
/// [`Done`], which drops it back to zero when the sound ends.
/// [`wait_for_playback`] polls it so the exit sound is not cut off.
fn active_sounds() -> &'static Arc<AtomicUsize> {
    static COUNT: OnceLock<Arc<AtomicUsize>> = OnceLock::new();
    COUNT.get_or_init(|| Arc::new(AtomicUsize::new(0)))
}

/// Whether the audio backend can actually decode a file.
///
/// Needs no audio device, so it works on a headless machine and in tests. Used
/// to check a sound pack at install time: a manifest naming a file only proves
/// the file exists, and a pack full of the wrong format would otherwise install
/// cleanly and then play nothing, with no clue as to why.
pub fn can_decode(path: &Path) -> bool {
    let Ok(file) = std::fs::File::open(path) else {
        return false;
    };
    Decoder::new(std::io::BufReader::new(file)).is_ok()
}

/// Decode a whole sound file into an in-memory buffer, scaled by `volume`.
///
/// Playing from one `SamplesBuffer` is deliberate. A rodio `Sink` wraps its
/// queue in a channel converter the moment it is built, while the queue is
/// still empty, and an empty queue reports a single channel. The first ~11 ms
/// of whatever plays next is then folded to mono and slightly time-stretched
/// before the converter re-reads the real channel count. These cues are short
/// and their stereo image lives in the opening transient, so that is exactly
/// where the fold is audible. A `SamplesBuffer` carries its true channel count
/// from the first sample, so nothing is folded.
///
/// Returns `None` if the file will not open, will not decode, or holds no
/// samples.
fn decode_to_buffer(path: &Path, volume: f32) -> Option<SamplesBuffer<f32>> {
    let file = std::fs::File::open(path).ok()?;
    let decoder = match Decoder::new(std::io::BufReader::new(file)) {
        Ok(decoder) => decoder,
        Err(err) => {
            log::warn!("could not decode {}: {err}", path.display());
            return None;
        }
    };

    let channels = decoder.channels();
    let sample_rate = decoder.sample_rate();
    if channels == 0 || sample_rate == 0 {
        return None;
    }
    let samples: Vec<f32> = decoder
        .convert_samples::<f32>()
        .map(|sample| sample * volume)
        .collect();
    if samples.is_empty() {
        return None;
    }
    Some(SamplesBuffer::new(channels, sample_rate, samples))
}

/// Play a sound file, returning whether playback started.
///
/// A volume of zero returns `true` without touching the audio device: the
/// caller asked for silence and got it.
pub fn play_sound_file(path: &Path, volume: f32) -> bool {
    if !path.is_file() {
        return false;
    }
    let volume = volume.clamp(0.0, 1.0);
    if volume <= 0.0 {
        return true;
    }

    let Some(output) = audio_output() else {
        return false;
    };
    let Some(source) = decode_to_buffer(path, volume) else {
        return false;
    };

    // Count this sound as playing until rodio drains it. `Done` decrements the
    // counter when the buffer ends; the manual paths below cover the cases
    // where playback never starts.
    let playing = active_sounds().clone();
    playing.fetch_add(1, Ordering::SeqCst);
    let source = Done::new(source, playing.clone());

    let play_result = match output.lock() {
        Ok(output) => output.handle.play_raw(source),
        Err(_) => {
            playing.fetch_sub(1, Ordering::SeqCst);
            return false;
        }
    };
    if let Err(err) = play_result {
        log::warn!("could not start audio playback: {err}");
        playing.fetch_sub(1, Ordering::SeqCst);
        return false;
    }
    true
}

/// A running looping sound. Playback stops when this is dropped, or when
/// [`LoopHandle::stop`] is called.
///
/// Looping cues (the "waiting to connect" sound) are deliberately not tracked
/// by [`wait_for_playback`]: they end only when the app asks them to, so the
/// exit wait must not block on one.
pub struct LoopHandle {
    stop: Arc<AtomicBool>,
}

impl LoopHandle {
    /// Stop the loop. Idempotent, and also happens on drop.
    pub fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

impl Drop for LoopHandle {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

/// Wraps a source and ends it once a shared flag is set, so a looping sound
/// can be stopped from another thread. The flag is checked per sample, so a
/// stop takes effect within one audio buffer.
struct StopFlag<S> {
    inner: S,
    stop: Arc<AtomicBool>,
}

impl<S> Iterator for StopFlag<S>
where
    S: Iterator<Item = f32>,
{
    type Item = f32;

    #[inline]
    fn next(&mut self) -> Option<f32> {
        if self.stop.load(Ordering::Relaxed) {
            return None;
        }
        self.inner.next()
    }
}

impl<S> Source for StopFlag<S>
where
    S: Source<Item = f32>,
{
    #[inline]
    fn current_frame_len(&self) -> Option<usize> {
        self.inner.current_frame_len()
    }

    #[inline]
    fn channels(&self) -> u16 {
        self.inner.channels()
    }

    #[inline]
    fn sample_rate(&self) -> u32 {
        self.inner.sample_rate()
    }

    #[inline]
    fn total_duration(&self) -> Option<Duration> {
        None
    }
}

/// Start playing a sound file on a loop, returning a handle that stops it.
///
/// Fire-and-forget like [`play_sound_file`]: a missing device or an
/// undecodable file yields `None` and the caller carries on. A volume of zero
/// yields a handle that controls nothing.
pub fn play_looping_sound_file(path: &Path, volume: f32) -> Option<LoopHandle> {
    if !path.is_file() {
        return None;
    }
    let volume = volume.clamp(0.0, 1.0);
    if volume <= 0.0 {
        return Some(LoopHandle {
            stop: Arc::new(AtomicBool::new(true)),
        });
    }

    let output = audio_output()?;
    // Decode once into memory; the loop repeats the buffer rather than
    // re-reading the file every pass.
    let buffer = decode_to_buffer(path, volume)?;

    let stop = Arc::new(AtomicBool::new(false));
    let source = StopFlag {
        inner: buffer.repeat_infinite(),
        stop: Arc::clone(&stop),
    };

    let Ok(output) = output.lock() else {
        return None;
    };
    if let Err(err) = output.handle.play_raw(source) {
        log::warn!("could not start looping audio playback: {err}");
        return None;
    }
    Some(LoopHandle { stop })
}

/// Wait until every started sound has finished, or `timeout` elapses.
///
/// Used on exit so the closing chime is not cut off when the process dies.
/// Other playback stays fire-and-forget: a transfer must not wait on a chime.
pub fn wait_for_playback(timeout: Duration) {
    let started = Instant::now();
    let playing = active_sounds();
    while started.elapsed() < timeout {
        if playing.load(Ordering::SeqCst) == 0 {
            return;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Plays event sounds from the active pack.
#[derive(Debug, Clone)]
pub struct SoundPlayer {
    soundpacks_dir: PathBuf,
    pack: String,
}

impl SoundPlayer {
    /// Build a player for a pack directory.
    pub fn new(soundpacks_dir: PathBuf, pack: &str) -> Self {
        let pack = if pack.trim().is_empty() {
            DEFAULT_PACK
        } else {
            pack
        };
        Self {
            soundpacks_dir,
            pack: pack.to_string(),
        }
    }

    /// The pack currently in use.
    pub fn pack(&self) -> &str {
        &self.pack
    }

    /// Switch to a different pack.
    pub fn set_pack(&mut self, pack: &str) {
        self.pack = if pack.trim().is_empty() {
            DEFAULT_PACK.to_string()
        } else {
            pack.to_string()
        };
    }

    /// Whether an event would play, given the current settings.
    ///
    /// Separated from playing so the decision is testable without an audio
    /// device.
    pub fn would_play(&self, event: &str, enabled: bool, muted: &[String]) -> bool {
        enabled && !muted.iter().any(|item| item == event)
    }

    /// Play an event sound, returning whether playback started.
    pub fn play_event(&self, event: &str, enabled: bool, muted: &[String]) -> bool {
        if !self.would_play(event, enabled, muted) {
            return false;
        }
        let Some((file, volume)) = resolve_sound(event, &self.pack, &self.soundpacks_dir) else {
            return false;
        };
        play_sound_file(&file, volume)
    }

    /// Start an event sound playing on a loop, returning a handle that stops it.
    ///
    /// Returns `None` when the event would not play (audio off or the event
    /// muted) or the active pack has no sound for it.
    pub fn play_event_looping(
        &self,
        event: &str,
        enabled: bool,
        muted: &[String],
    ) -> Option<LoopHandle> {
        if !self.would_play(event, enabled, muted) {
            return None;
        }
        let (file, volume) = resolve_sound(event, &self.pack, &self.soundpacks_dir)?;
        play_looping_sound_file(&file, volume)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn player(dir: &TempDir) -> SoundPlayer {
        SoundPlayer::new(dir.path().to_path_buf(), "test")
    }

    #[test]
    fn an_empty_pack_name_falls_back_to_the_default() {
        let dir = TempDir::new().unwrap();
        assert_eq!(SoundPlayer::new(dir.path().into(), "").pack(), DEFAULT_PACK);
        assert_eq!(
            SoundPlayer::new(dir.path().into(), "  ").pack(),
            DEFAULT_PACK
        );
    }

    #[test]
    fn the_pack_can_be_switched() {
        let dir = TempDir::new().unwrap();
        let mut player = player(&dir);
        player.set_pack("retro");
        assert_eq!(player.pack(), "retro");
        // Switching to nothing returns to the default rather than breaking.
        player.set_pack("");
        assert_eq!(player.pack(), DEFAULT_PACK);
    }

    #[test]
    fn sounds_are_skipped_when_audio_is_off() {
        let dir = TempDir::new().unwrap();
        let player = player(&dir);
        assert!(!player.would_play("error", false, &[]));
        assert!(!player.play_event("error", false, &[]));
    }

    #[test]
    fn a_muted_event_is_skipped() {
        let dir = TempDir::new().unwrap();
        let player = player(&dir);
        let muted = vec!["error".to_string()];
        assert!(!player.would_play("error", true, &muted));
        // Other events still play.
        assert!(player.would_play("success", true, &muted));
    }

    #[test]
    fn an_event_with_no_sound_reports_that_nothing_played() {
        let dir = TempDir::new().unwrap();
        assert!(!player(&dir).play_event("error", true, &[]));
    }

    #[test]
    fn a_missing_file_reports_that_nothing_played() {
        let dir = TempDir::new().unwrap();
        assert!(!play_sound_file(&dir.path().join("nope.ogg"), 1.0));
    }

    #[test]
    fn silence_is_treated_as_played_without_touching_the_device() {
        // The caller asked for no sound and got exactly that, so reporting a
        // failure would be misleading.
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("quiet.ogg");
        std::fs::write(&path, b"not really audio").unwrap();
        assert!(play_sound_file(&path, 0.0));
        assert!(play_sound_file(&path, -1.0));
    }

    #[test]
    fn a_file_that_is_not_audio_cannot_be_decoded() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("bogus.ogg");
        std::fs::write(&path, b"definitely not audio").unwrap();
        assert!(!can_decode(&path));
    }

    #[test]
    fn a_missing_file_cannot_be_decoded() {
        let dir = TempDir::new().unwrap();
        assert!(!can_decode(&dir.path().join("nope.ogg")));
    }

    #[test]
    fn a_wav_file_decodes() {
        // Built here rather than shipped as a fixture, so the check does not
        // depend on a binary blob in the repo. A minimal 8-bit mono WAV.
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("tone.wav");
        std::fs::write(&path, minimal_wav()).unwrap();
        assert!(can_decode(&path), "the backend should decode WAV");
    }

    /// A minimal, valid 8 kHz 8-bit mono WAV holding a few samples.
    fn minimal_wav() -> Vec<u8> {
        let samples: Vec<u8> = (0..800u32).map(|i| (i % 256) as u8).collect();
        let data_len = samples.len() as u32;
        let mut wav = Vec::new();
        wav.extend_from_slice(b"RIFF");
        wav.extend_from_slice(&(36 + data_len).to_le_bytes());
        wav.extend_from_slice(b"WAVEfmt ");
        wav.extend_from_slice(&16u32.to_le_bytes()); // fmt chunk size
        wav.extend_from_slice(&1u16.to_le_bytes()); // PCM
        wav.extend_from_slice(&1u16.to_le_bytes()); // mono
        wav.extend_from_slice(&8000u32.to_le_bytes()); // sample rate
        wav.extend_from_slice(&8000u32.to_le_bytes()); // byte rate
        wav.extend_from_slice(&1u16.to_le_bytes()); // block align
        wav.extend_from_slice(&8u16.to_le_bytes()); // bits per sample
        wav.extend_from_slice(b"data");
        wav.extend_from_slice(&data_len.to_le_bytes());
        wav.extend_from_slice(&samples);
        wav
    }

    /// A 48 kHz 16-bit *stereo* WAV whose two channels never match: left ramps
    /// up, right ramps down. Folding it to mono would leave the two channels
    /// equal, which is what the regression tests below check for.
    fn stereo_wav(frames: u32) -> Vec<u8> {
        let mut data = Vec::with_capacity(frames as usize * 4);
        for i in 0..frames {
            let left = ((i % 2000) as i16).wrapping_sub(1000) * 16;
            let right = -left;
            data.extend_from_slice(&left.to_le_bytes());
            data.extend_from_slice(&right.to_le_bytes());
        }
        let data_len = data.len() as u32;
        let mut wav = Vec::new();
        wav.extend_from_slice(b"RIFF");
        wav.extend_from_slice(&(36 + data_len).to_le_bytes());
        wav.extend_from_slice(b"WAVEfmt ");
        wav.extend_from_slice(&16u32.to_le_bytes()); // fmt chunk size
        wav.extend_from_slice(&1u16.to_le_bytes()); // PCM
        wav.extend_from_slice(&2u16.to_le_bytes()); // stereo
        wav.extend_from_slice(&48_000u32.to_le_bytes()); // sample rate
        wav.extend_from_slice(&(48_000u32 * 4).to_le_bytes()); // byte rate
        wav.extend_from_slice(&4u16.to_le_bytes()); // block align
        wav.extend_from_slice(&16u16.to_le_bytes()); // bits per sample
        wav.extend_from_slice(b"data");
        wav.extend_from_slice(&data_len.to_le_bytes());
        wav.extend_from_slice(&data);
        wav
    }

    #[test]
    fn a_stereo_sound_is_buffered_without_being_folded_to_mono() {
        // Guards the connect-sound regression: the decode step must hand rodio a
        // buffer that still knows it has two channels and still has distinct
        // left/right samples. The old `Sink` path collapsed the opening frames.
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("stereo.wav");
        std::fs::write(&path, stereo_wav(24_000)).unwrap();

        let buffer = decode_to_buffer(&path, 1.0).expect("stereo WAV should decode");
        assert_eq!(buffer.channels(), 2, "channel count must survive decoding");
        assert_eq!(buffer.sample_rate(), 48_000);

        let samples: Vec<f32> = buffer.collect();
        assert_eq!(samples.len(), 24_000 * 2, "every frame should be present");
        // Left and right must still differ - a mono fold would make them equal.
        let stereo_frames = samples
            .chunks_exact(2)
            .filter(|frame| (frame[0] - frame[1]).abs() > f32::EPSILON)
            .count();
        assert!(
            stereo_frames > 20_000,
            "expected a wide stereo image, only {stereo_frames} frames differ"
        );
    }

    #[test]
    fn volume_scales_the_buffered_samples() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("stereo.wav");
        std::fs::write(&path, stereo_wav(4_000)).unwrap();

        let full: Vec<f32> = decode_to_buffer(&path, 1.0).unwrap().collect();
        let half: Vec<f32> = decode_to_buffer(&path, 0.5).unwrap().collect();
        assert_eq!(full.len(), half.len());
        let loudest = full.iter().fold(0.0f32, |m, s| m.max(s.abs()));
        assert!(loudest > 0.1, "test signal should be audible");
        for (f, h) in full.iter().zip(&half) {
            assert!(
                (f * 0.5 - h).abs() < 1e-6,
                "half volume should be half amplitude"
            );
        }
    }

    #[test]
    fn a_zero_length_sound_is_not_played() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("empty.wav");
        std::fs::write(&path, stereo_wav(0)).unwrap();
        assert!(decode_to_buffer(&path, 1.0).is_none());
        assert!(!play_sound_file(&path, 1.0));
    }

    #[test]
    fn an_undecodable_file_reports_failure_rather_than_panicking() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("bogus.ogg");
        std::fs::write(&path, b"definitely not audio").unwrap();
        assert!(!play_sound_file(&path, 1.0));
    }

    #[test]
    fn the_stop_flag_ends_the_source_when_set() {
        let stop = Arc::new(AtomicBool::new(false));
        let mut source = StopFlag {
            inner: SamplesBuffer::new(1, 8000, vec![0.5f32; 100]).repeat_infinite(),
            stop: Arc::clone(&stop),
        };
        // The buffer repeats forever, so without the flag this never ends.
        assert_eq!(source.next(), Some(0.5));
        assert_eq!(source.by_ref().take(1000).count(), 1000);
        stop.store(true, Ordering::SeqCst);
        assert_eq!(source.next(), None);
        // Reports its channel layout straight through, so playback is not
        // folded to mono.
        assert_eq!(source.channels(), 1);
        assert_eq!(source.sample_rate(), 8000);
    }

    #[test]
    fn a_loop_handle_sets_the_flag_on_stop_and_on_drop() {
        let stop = Arc::new(AtomicBool::new(false));
        let handle = LoopHandle {
            stop: Arc::clone(&stop),
        };
        assert!(!stop.load(Ordering::SeqCst));
        handle.stop();
        assert!(stop.load(Ordering::SeqCst));

        let stop = Arc::new(AtomicBool::new(false));
        drop(LoopHandle {
            stop: Arc::clone(&stop),
        });
        assert!(
            stop.load(Ordering::SeqCst),
            "drop should also stop the loop"
        );
    }

    #[test]
    fn a_looping_sound_from_a_missing_or_undecodable_file_yields_no_handle() {
        let dir = TempDir::new().unwrap();
        assert!(play_looping_sound_file(&dir.path().join("nope.ogg"), 1.0).is_none());

        let bogus = dir.path().join("bogus.ogg");
        std::fs::write(&bogus, b"definitely not audio").unwrap();
        assert!(play_looping_sound_file(&bogus, 1.0).is_none());
    }

    #[test]
    fn a_silent_looping_sound_yields_an_inert_handle_without_touching_the_device() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("quiet.ogg");
        std::fs::write(&path, b"not really audio").unwrap();
        let handle = play_looping_sound_file(&path, 0.0).expect("silence still returns a handle");
        handle.stop();
    }

    #[test]
    fn waiting_with_nothing_playing_returns_immediately() {
        let start = Instant::now();
        wait_for_playback(Duration::from_secs(5));
        assert!(
            start.elapsed() < Duration::from_millis(500),
            "idle wait took {:?}",
            start.elapsed()
        );
    }

    #[test]
    fn the_exit_wait_is_long_enough_for_a_chime_and_short_enough_not_to_trap() {
        assert!(EXIT_SOUND_TIMEOUT >= Duration::from_secs(2));
        assert!(EXIT_SOUND_TIMEOUT <= Duration::from_secs(10));
    }
}
