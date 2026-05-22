//! ALSA output backend for V2 native_transport.
//!
//! Wraps [`AlsaCtx`] in a synchronous "push slab → write" interface that the
//! V2 decode worker drives directly. No separate writer thread is needed:
//! V2's worker already runs at audio cadence and calls `push_bytes` once per
//! decoded packet. `AlsaCtx` picks `MMAP_INTERLEAVED` or `RW_INTERLEAVED`
//! automatically based on what the device accepts.

use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use crate::alsa_clock::AlsaHwClockFeed;
use crate::alsa_pcm::{
    alsa_wire_format_from_preference, AlsaAccessMode, AlsaCtx, AlsaWireFormat,
};

use super::output::AlsaOutputConfig;

const MIN_PERIOD_FRAMES: u32 = 64;
const MAX_PERIOD_FRAMES: u32 = 4096;
const MIN_BUFFER_FRAMES: u32 = 256;
const MAX_BUFFER_FRAMES: u32 = 65_536;
const DEFAULT_BUFFER_US: u32 = 100_000;
const DEFAULT_PERIOD_US: u32 = 10_000;

fn frames_for_duration_us(duration_us: u32, sample_rate: u32, min: u32, max: u32) -> u32 {
    let duration_us = duration_us.max(0) as u64;
    let sample_rate = sample_rate.max(1) as u64;
    let frames = duration_us.saturating_mul(sample_rate) / 1_000_000;
    (frames as u32).clamp(min, max)
}

/// Live ALSA output session. Owned by the V2 controller's decode worker;
/// constructed when the first decoded slab arrives so the actual negotiated
/// sample rate drives `snd_pcm_hw_params_set_rate_near`.
pub struct AlsaSession {
    ctx: AlsaCtx,
    audio_format: AlsaWireFormat,
    /// Caller-provided clock feed; anchored on the first commit and
    /// advanced after every successful commit.
    pub feed: Arc<AlsaHwClockFeed>,
    /// Stop flag the controller can flip during shutdown so blocking
    /// `snd_pcm_wait` calls return immediately.
    stop: Arc<AtomicBool>,
}

impl AlsaSession {
    pub fn open(
        cfg: &AlsaOutputConfig,
        sample_rate: u32,
        feed: Arc<AlsaHwClockFeed>,
        stop: Arc<AtomicBool>,
    ) -> Result<Self, String> {
        let audio_format = alsa_wire_format_from_preference(&cfg.preferred_format);
        let buffer_us = if cfg.buffer_us > 0 {
            cfg.buffer_us
        } else {
            DEFAULT_BUFFER_US
        };
        let latency_us = if cfg.latency_us > 0 {
            cfg.latency_us
        } else {
            DEFAULT_PERIOD_US
        };
        let period_frames = frames_for_duration_us(
            latency_us,
            sample_rate,
            MIN_PERIOD_FRAMES,
            MAX_PERIOD_FRAMES,
        );
        let buffer_frames = frames_for_duration_us(
            buffer_us,
            sample_rate,
            period_frames.saturating_mul(2).max(MIN_BUFFER_FRAMES),
            MAX_BUFFER_FRAMES,
        );

        let mut ctx = AlsaCtx::open(
            &cfg.device,
            sample_rate,
            period_frames,
            buffer_frames,
            audio_format.alsa_format,
            audio_format.frame_bytes,
            audio_format.log_label,
        )?;
        ctx.feed = Some(Arc::clone(&feed));

        Ok(Self {
            ctx,
            audio_format,
            feed,
            stop,
        })
    }

    /// PCM format string that matches what `AlsaCtx::open` configured on
    /// the device. The V2 controller uses this to decide whether incoming
    /// slabs need a format conversion before push.
    pub fn gst_format(&self) -> &'static str {
        self.audio_format.gst_format
    }

    pub fn frame_bytes(&self) -> usize {
        self.audio_format.frame_bytes
    }

    /// Negotiated hardware sample rate. May differ from the requested rate
    /// when the device only supports a discrete set.
    pub fn actual_rate(&self) -> u32 {
        self.ctx.rate
    }

    pub fn access_mode(&self) -> AlsaAccessMode {
        self.ctx.access_mode()
    }

    /// Push `data` (interleaved samples in this session's wire format) to the
    /// ALSA mmap ring. Returns once every byte is consumed or `stop` is
    /// signalled. `data.len()` must be a multiple of `frame_bytes()`.
    pub fn push_bytes(&mut self, data: &[u8]) -> Result<(), String> {
        if data.is_empty() {
            return Ok(());
        }
        let frame_bytes = self.audio_format.frame_bytes.max(1);
        if data.len() % frame_bytes != 0 {
            return Err(format!(
                "alsa push: data len {} not aligned to frame_bytes {}",
                data.len(),
                frame_bytes
            ));
        }
        let frames = data.len() / frame_bytes;
        self.ctx
            .write(data, frames, &self.stop)
            .map_err(|rc| format!("alsa write rc={rc}"))
    }
}
