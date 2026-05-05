//! ALSA PCM output state.
//!
//! This module owns the raw `snd_pcm_*` FFI declarations plus the
//! `AlsaMmapCtx` wrapper that opens a device for playback. It tries
//! `MMAP_INTERLEAVED` first (zero-copy ring writes) and falls back to the
//! plain `RW_INTERLEAVED` interface (`snd_pcm_writei`) when mmap isn't
//! supported by the device — common with the PipeWire ALSA bridge or
//! certain plug-chain configurations. Shared between the GStreamer-fed
//! writer thread (in `lib.rs`) and the V2 native_transport ALSA backend.

use std::os::raw::c_int;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use crate::alsa_clock::AlsaHwClockFeed;

/// Raw ALSA FFI declarations. We link libasound via build.rs.
#[allow(non_camel_case_types, dead_code)]
pub mod alsa_ffi {
    use std::os::raw::{c_char, c_int, c_uint, c_void};

    pub type SndPcmUframes = std::os::raw::c_ulong;
    pub type SndPcmSframes = std::os::raw::c_long;

    // snd_pcm_stream_t
    pub const SND_PCM_STREAM_PLAYBACK: c_int = 0;
    // snd_pcm_access_t
    pub const SND_PCM_ACCESS_MMAP_INTERLEAVED: c_int = 0;
    pub const SND_PCM_ACCESS_RW_INTERLEAVED: c_int = 3;
    // snd_pcm_format_t
    pub const SND_PCM_FORMAT_S16_LE: c_int = 2;
    pub const SND_PCM_FORMAT_S24_LE: c_int = 6;
    pub const SND_PCM_FORMAT_S32_LE: c_int = 10;

    #[repr(C)]
    pub struct SndPcmChannelArea {
        pub addr: *mut c_void,
        pub first: c_uint,
        pub step: c_uint,
    }

    extern "C" {
        pub fn snd_pcm_open(
            pcm: *mut *mut c_void,
            name: *const c_char,
            stream: c_int,
            mode: c_int,
        ) -> c_int;
        pub fn snd_pcm_close(pcm: *mut c_void) -> c_int;
        pub fn snd_pcm_drop(pcm: *mut c_void) -> c_int;
        pub fn snd_pcm_start(pcm: *mut c_void) -> c_int;
        pub fn snd_pcm_recover(pcm: *mut c_void, err: c_int, silent: c_int) -> c_int;
        pub fn snd_pcm_wait(pcm: *mut c_void, timeout: c_int) -> c_int;

        pub fn snd_pcm_hw_params_malloc(params: *mut *mut c_void) -> c_int;
        pub fn snd_pcm_hw_params_free(params: *mut c_void);
        pub fn snd_pcm_hw_params_any(pcm: *mut c_void, params: *mut c_void) -> c_int;
        pub fn snd_pcm_hw_params_set_access(
            pcm: *mut c_void,
            params: *mut c_void,
            access: c_int,
        ) -> c_int;
        pub fn snd_pcm_hw_params_set_format(
            pcm: *mut c_void,
            params: *mut c_void,
            format: c_int,
        ) -> c_int;
        pub fn snd_pcm_hw_params_set_channels(
            pcm: *mut c_void,
            params: *mut c_void,
            val: c_uint,
        ) -> c_int;
        pub fn snd_pcm_hw_params_set_rate_near(
            pcm: *mut c_void,
            params: *mut c_void,
            val: *mut c_uint,
            dir: *mut c_int,
        ) -> c_int;
        pub fn snd_pcm_hw_params_set_period_size_near(
            pcm: *mut c_void,
            params: *mut c_void,
            val: *mut SndPcmUframes,
            dir: *mut c_int,
        ) -> c_int;
        pub fn snd_pcm_hw_params_set_buffer_size_near(
            pcm: *mut c_void,
            params: *mut c_void,
            val: *mut SndPcmUframes,
        ) -> c_int;
        pub fn snd_pcm_hw_params(pcm: *mut c_void, params: *mut c_void) -> c_int;

        pub fn snd_pcm_sw_params_malloc(params: *mut *mut c_void) -> c_int;
        pub fn snd_pcm_sw_params_free(params: *mut c_void);
        pub fn snd_pcm_sw_params_current(pcm: *mut c_void, params: *mut c_void) -> c_int;
        pub fn snd_pcm_sw_params_set_start_threshold(
            pcm: *mut c_void,
            params: *mut c_void,
            val: SndPcmUframes,
        ) -> c_int;
        pub fn snd_pcm_sw_params_set_avail_min(
            pcm: *mut c_void,
            params: *mut c_void,
            val: SndPcmUframes,
        ) -> c_int;
        pub fn snd_pcm_sw_params(pcm: *mut c_void, params: *mut c_void) -> c_int;

        pub fn snd_pcm_mmap_begin(
            pcm: *mut c_void,
            areas: *mut *const SndPcmChannelArea,
            offset: *mut SndPcmUframes,
            frames: *mut SndPcmUframes,
        ) -> c_int;
        pub fn snd_pcm_mmap_commit(
            pcm: *mut c_void,
            offset: SndPcmUframes,
            frames: SndPcmUframes,
        ) -> SndPcmSframes;
        pub fn snd_pcm_writei(
            pcm: *mut c_void,
            buffer: *const c_void,
            size: SndPcmUframes,
        ) -> SndPcmSframes;
    }
}

/// Newtype so a raw ALSA PCM pointer can cross thread boundaries safely.
pub struct AlsaHandle(pub *mut std::os::raw::c_void);
unsafe impl Send for AlsaHandle {}

/// How `AlsaMmapCtx` writes frames to the device. `Mmap` uses the zero-copy
/// `snd_pcm_mmap_begin`/`commit` ring; `Interleaved` falls back to a plain
/// `snd_pcm_writei` blocking copy. The mode is selected by `open()` based on
/// what the device's hw_params will actually accept.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AlsaAccessMode {
    Mmap,
    Interleaved,
}

/// Resolved ALSA mmap output format (negotiated bit depth + frame stride).
#[derive(Clone, Copy)]
pub struct MmapAudioFormat {
    pub gst_format: &'static str,
    pub alsa_format: c_int,
    pub frame_bytes: usize,
    pub log_label: &'static str,
}

/// Map a user-facing format preference (`"S16LE"` / `"S24LE"` / `"S32LE"`) to
/// the corresponding ALSA mmap format descriptor. Unknown values fall back to
/// `S32LE`.
pub fn mmap_audio_format_from_preference(preferred: &str) -> MmapAudioFormat {
    let norm = preferred.trim().to_ascii_uppercase();
    match norm.as_str() {
        "S16LE" | "S16_LE" => MmapAudioFormat {
            gst_format: "S16LE",
            alsa_format: alsa_ffi::SND_PCM_FORMAT_S16_LE,
            frame_bytes: 4,
            log_label: "S16_LE",
        },
        "S24LE" | "S24_LE" | "S24_32LE" | "S24_32_LE" => MmapAudioFormat {
            gst_format: "S24_32LE",
            alsa_format: alsa_ffi::SND_PCM_FORMAT_S24_LE,
            frame_bytes: 8,
            log_label: "S24_LE",
        },
        _ => MmapAudioFormat {
            gst_format: "S32LE",
            alsa_format: alsa_ffi::SND_PCM_FORMAT_S32_LE,
            frame_bytes: 8,
            log_label: "S32_LE",
        },
    }
}

/// Open ALSA device state for playback.
pub struct AlsaMmapCtx {
    pub(crate) pcm: AlsaHandle,
    pub(crate) period_frames: usize,
    pub(crate) buffer_frames: usize,
    pub(crate) frame_bytes: usize,
    /// Negotiated sample rate (may differ from requested).
    pub(crate) rate: u32,
    pub(crate) primed_frames: usize,
    pub(crate) started: bool,
    /// Consecutive snd_pcm_start failures since last successful start.
    pub(crate) start_fail_count: u32,
    #[allow(dead_code)]
    pub(crate) format_label: &'static str,
    /// True once `feed.anchor()` has been called for this playback session.
    pub(crate) anchored: bool,
    /// Clock feed updated after each commit; shared with the pipeline clock.
    pub(crate) feed: Option<Arc<AlsaHwClockFeed>>,
    /// Negotiated access mode. Mmap when the device accepted MMAP_INTERLEAVED;
    /// Interleaved when we had to fall back to `snd_pcm_writei`.
    pub(crate) access_mode: AlsaAccessMode,
}

impl AlsaMmapCtx {
    pub fn reset_start_sequence(&mut self) {
        self.primed_frames = 0;
        self.started = false;
        self.start_fail_count = 0;
        self.anchored = false;
        if let Some(ref feed) = self.feed {
            feed.invalidate();
        }
    }

    pub fn recover_requires_restart(rc: i32) -> bool {
        rc == -libc::EPIPE || rc == -libc::ESTRPIPE
    }

    /// Open `device` (e.g. `"hw:0,0"`) in MMAP_INTERLEAVED mode.
    /// `want_rate`, `want_period_frames`, and `want_buffer_frames` are hints;
    /// ALSA picks the nearest supported values.
    pub fn open(
        device: &str,
        want_rate: u32,
        want_period_frames: u32,
        want_buffer_frames: u32,
        sample_format: c_int,
        frame_bytes: usize,
        format_label: &'static str,
    ) -> Result<Self, String> {
        use alsa_ffi::*;
        use std::ffi::CString;
        use std::os::raw::c_void;

        let dev_c = CString::new(device).map_err(|e| format!("bad device name: {e}"))?;
        let mut pcm: *mut c_void = std::ptr::null_mut();

        let rc = unsafe { snd_pcm_open(&mut pcm, dev_c.as_ptr(), SND_PCM_STREAM_PLAYBACK, 0) };
        if rc < 0 {
            return Err(format!("snd_pcm_open({device}) rc={rc}"));
        }

        // Try MMAP_INTERLEAVED first; if hw_params won't accept it (common with
        // the PipeWire ALSA bridge or `plug:` chains), retry the whole hw_params
        // negotiation with RW_INTERLEAVED so we still get sound out.
        unsafe fn negotiate_hw_params(
            pcm: *mut std::os::raw::c_void,
            access: std::os::raw::c_int,
            sample_format: std::os::raw::c_int,
            want_rate: u32,
            want_period_frames: u32,
            want_buffer_frames: u32,
        ) -> Result<(usize, usize, u32), String> {
            use crate::alsa_pcm::alsa_ffi::*;
            use std::os::raw::{c_int, c_uint, c_void};

            let mut hw: *mut c_void = std::ptr::null_mut();
            if snd_pcm_hw_params_malloc(&mut hw) < 0 {
                return Err("hw_params_malloc failed".into());
            }
            snd_pcm_hw_params_any(pcm, hw);

            macro_rules! hw_try {
                ($call:expr, $msg:literal) => {{
                    let rc: c_int = $call;
                    if rc < 0 {
                        snd_pcm_hw_params_free(hw);
                        return Err(format!("{}: rc={}", $msg, rc));
                    }
                }};
            }

            hw_try!(
                snd_pcm_hw_params_set_access(pcm, hw, access),
                "set_access"
            );
            hw_try!(
                snd_pcm_hw_params_set_format(pcm, hw, sample_format),
                "set_format"
            );
            hw_try!(snd_pcm_hw_params_set_channels(pcm, hw, 2), "set_channels 2");

            let mut rate: c_uint = want_rate;
            let mut dir: c_int = 0;
            hw_try!(
                snd_pcm_hw_params_set_rate_near(pcm, hw, &mut rate, &mut dir),
                "set_rate_near"
            );

            let mut period: SndPcmUframes = want_period_frames as SndPcmUframes;
            hw_try!(
                snd_pcm_hw_params_set_period_size_near(pcm, hw, &mut period, &mut dir),
                "set_period_size_near"
            );

            let min_buffer = period.saturating_mul(2);
            let want_buffer = (want_buffer_frames as SndPcmUframes).max(min_buffer);
            let mut bufsize: SndPcmUframes = want_buffer;
            hw_try!(
                snd_pcm_hw_params_set_buffer_size_near(pcm, hw, &mut bufsize),
                "set_buffer_size_near"
            );

            let rc = snd_pcm_hw_params(pcm, hw);
            snd_pcm_hw_params_free(hw);
            if rc < 0 {
                return Err(format!("hw_params apply: rc={rc}"));
            }
            Ok((period as usize, bufsize as usize, rate))
        }

        let (access_mode, period_frames, buffer_frames, rate) = unsafe {
            match negotiate_hw_params(
                pcm,
                SND_PCM_ACCESS_MMAP_INTERLEAVED,
                sample_format,
                want_rate,
                want_period_frames,
                want_buffer_frames,
            ) {
                Ok((p, b, r)) => (AlsaAccessMode::Mmap, p, b, r),
                Err(mmap_err) => match negotiate_hw_params(
                    pcm,
                    SND_PCM_ACCESS_RW_INTERLEAVED,
                    sample_format,
                    want_rate,
                    want_period_frames,
                    want_buffer_frames,
                ) {
                    Ok((p, b, r)) => (AlsaAccessMode::Interleaved, p, b, r),
                    Err(rw_err) => {
                        snd_pcm_close(pcm);
                        return Err(format!(
                            "hw_params: mmap failed ({mmap_err}); interleaved failed ({rw_err})"
                        ));
                    }
                },
            }
        };

        unsafe {
            let mut sw: *mut c_void = std::ptr::null_mut();
            if snd_pcm_sw_params_malloc(&mut sw) < 0 {
                snd_pcm_close(pcm);
                return Err("sw_params_malloc failed".into());
            }
            snd_pcm_sw_params_current(pcm, sw);
            let start_threshold = (buffer_frames + 1) as SndPcmUframes;
            snd_pcm_sw_params_set_start_threshold(pcm, sw, start_threshold);
            let avail_min = (period_frames / 2).max(1);
            snd_pcm_sw_params_set_avail_min(pcm, sw, avail_min as SndPcmUframes);
            let rc = snd_pcm_sw_params(pcm, sw);
            snd_pcm_sw_params_free(sw);
            if rc < 0 {
                snd_pcm_close(pcm);
                return Err(format!("sw_params apply: rc={rc}"));
            }
        }

        Ok(AlsaMmapCtx {
            pcm: AlsaHandle(pcm),
            period_frames,
            buffer_frames,
            frame_bytes,
            rate,
            primed_frames: 0,
            started: false,
            start_fail_count: 0,
            format_label,
            anchored: false,
            feed: None,
            access_mode,
        })
    }

    #[allow(dead_code)]
    pub fn access_mode(&self) -> AlsaAccessMode {
        self.access_mode
    }

    /// Write exactly `frames` frames from `src` (interleaved, stride
    /// `frame_bytes`) using whichever access mode `open()` negotiated. Blocks
    /// internally until the hardware accepts each chunk or `stop` is set.
    pub fn write(&mut self, src: &[u8], frames: usize, stop: &AtomicBool) -> Result<(), i32> {
        match self.access_mode {
            AlsaAccessMode::Mmap => self.mmap_write(src, frames, stop),
            AlsaAccessMode::Interleaved => self.interleaved_write(src, frames, stop),
        }
    }

    /// `snd_pcm_writei` blocking fallback for devices that don't expose mmap
    /// (PipeWire ALSA bridge `default`, some `plug:` chains, soft-DSP virtual
    /// devices). Mirrors the priming + `snd_pcm_start` semantics of the mmap
    /// path so the rest of the writer thread can stay mode-agnostic.
    pub fn interleaved_write(
        &mut self,
        src: &[u8],
        frames: usize,
        stop: &AtomicBool,
    ) -> Result<(), i32> {
        use alsa_ffi::*;
        let pcm = self.pcm.0;
        let frame_bytes = self.frame_bytes;
        let mut remaining = frames;
        let mut src_offset = 0usize;

        while remaining > 0 {
            if stop.load(Ordering::Relaxed) {
                return Err(-125);
            }
            let chunk = remaining as SndPcmUframes;
            let buf_ptr = unsafe { src.as_ptr().add(src_offset) } as *const std::os::raw::c_void;
            let written = unsafe { snd_pcm_writei(pcm, buf_ptr, chunk) };
            if written < 0 {
                let rec = unsafe { snd_pcm_recover(pcm, written as i32, 1) };
                if rec < 0 {
                    return Err(rec);
                }
                if Self::recover_requires_restart(written as i32) {
                    self.reset_start_sequence();
                }
                continue;
            }
            let written = written as usize;
            if written == 0 {
                if stop.load(Ordering::Relaxed) {
                    return Err(-125);
                }
                let wait_rc = unsafe { snd_pcm_wait(pcm, 100) };
                if wait_rc < 0 {
                    let wait_rec = unsafe { snd_pcm_recover(pcm, wait_rc, 1) };
                    if wait_rec < 0 {
                        return Err(wait_rec);
                    }
                    if Self::recover_requires_restart(wait_rc) {
                        self.reset_start_sequence();
                    }
                }
                continue;
            }

            src_offset += written * frame_bytes;
            remaining -= written;

            if let Some(ref feed) = self.feed {
                if !self.anchored {
                    let now_ns = {
                        let mut ts = libc::timespec {
                            tv_sec: 0,
                            tv_nsec: 0,
                        };
                        unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
                        ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
                    };
                    feed.anchor(now_ns, self.rate);
                    self.anchored = true;
                }
                feed.advance(written as u64);
            }

            // sw_params puts start_threshold above the buffer, so writei alone
            // never auto-starts. Match the mmap path: prime ~3 periods, then
            // explicitly snd_pcm_start.
            if !self.started {
                self.primed_frames = self.primed_frames.saturating_add(written);
                let prime_target = self.period_frames.saturating_mul(3).min(self.buffer_frames);
                if self.primed_frames >= prime_target.max(1) {
                    let start_rc = unsafe { snd_pcm_start(pcm) };
                    if start_rc < 0 {
                        let rec = unsafe { snd_pcm_recover(pcm, start_rc, 1) };
                        if rec < 0 {
                            return Err(rec);
                        }
                        self.start_fail_count = self.start_fail_count.saturating_add(1);
                        if self.start_fail_count >= 5 {
                            return Err(start_rc);
                        }
                    } else {
                        self.started = true;
                        self.start_fail_count = 0;
                    }
                }
            }
        }
        Ok(())
    }

    /// Write exactly `frames` frames from `src` (interleaved, stride
    /// `frame_bytes`) via mmap. Blocks internally via `snd_pcm_wait` until the
    /// hardware accepts each chunk.
    pub fn mmap_write(&mut self, src: &[u8], frames: usize, stop: &AtomicBool) -> Result<(), i32> {
        use alsa_ffi::*;
        let pcm = self.pcm.0;
        let frame_bytes = self.frame_bytes;
        let mut remaining = frames;
        let mut src_offset = 0usize;

        while remaining > 0 {
            if stop.load(Ordering::Relaxed) {
                return Err(-125);
            }
            let mut to_write = remaining as SndPcmUframes;

            let mut areas: *const SndPcmChannelArea = std::ptr::null();
            let mut offset: SndPcmUframes = 0;
            let rc = unsafe { snd_pcm_mmap_begin(pcm, &mut areas, &mut offset, &mut to_write) };
            if rc < 0 {
                let rec = unsafe { snd_pcm_recover(pcm, rc, 1) };
                if rec < 0 {
                    return Err(rec);
                }
                if Self::recover_requires_restart(rc) {
                    self.reset_start_sequence();
                }
                if stop.load(Ordering::Relaxed) {
                    return Err(-125);
                }
                let wait_rc = unsafe { snd_pcm_wait(pcm, 100) };
                if wait_rc < 0 {
                    let wait_rec = unsafe { snd_pcm_recover(pcm, wait_rc, 1) };
                    if wait_rec < 0 {
                        return Err(wait_rec);
                    }
                    if Self::recover_requires_restart(wait_rc) {
                        self.reset_start_sequence();
                    }
                }
                continue;
            }
            if to_write == 0 {
                if stop.load(Ordering::Relaxed) {
                    return Err(-125);
                }
                let wait_rc = unsafe { snd_pcm_wait(pcm, 100) };
                if wait_rc < 0 {
                    let wait_rec = unsafe { snd_pcm_recover(pcm, wait_rc, 1) };
                    if wait_rec < 0 {
                        return Err(wait_rec);
                    }
                    if Self::recover_requires_restart(wait_rc) {
                        self.reset_start_sequence();
                    }
                }
                continue;
            }

            unsafe {
                let area = &*areas;
                let first_byte = area.first as usize / 8;
                let dst = (area.addr as *mut u8).add(first_byte + offset as usize * frame_bytes);
                let src_ptr = src.as_ptr().add(src_offset);
                std::ptr::copy_nonoverlapping(src_ptr, dst, to_write as usize * frame_bytes);
            }

            let committed = unsafe { snd_pcm_mmap_commit(pcm, offset, to_write) };
            if committed < 0 {
                let rec = unsafe { snd_pcm_recover(pcm, committed as i32, 1) };
                if rec < 0 {
                    return Err(rec);
                }
                if Self::recover_requires_restart(committed as i32) {
                    self.reset_start_sequence();
                }
                continue;
            }

            let committed = committed as usize;
            src_offset += committed * frame_bytes;
            remaining -= committed;

            if let Some(ref feed) = self.feed {
                if !self.anchored {
                    let now_ns = {
                        let mut ts = libc::timespec {
                            tv_sec: 0,
                            tv_nsec: 0,
                        };
                        unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
                        ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
                    };
                    feed.anchor(now_ns, self.rate);
                    self.anchored = true;
                }
                feed.advance(committed as u64);
            }

            if !self.started {
                self.primed_frames = self.primed_frames.saturating_add(committed);
                let prime_target = self.period_frames.saturating_mul(3).min(self.buffer_frames);
                if self.primed_frames >= prime_target.max(1) {
                    let start_rc = unsafe { snd_pcm_start(pcm) };
                    if start_rc < 0 {
                        let rec = unsafe { snd_pcm_recover(pcm, start_rc, 1) };
                        if rec < 0 {
                            return Err(rec);
                        }
                        self.start_fail_count = self.start_fail_count.saturating_add(1);
                        if self.start_fail_count >= 5 {
                            return Err(start_rc);
                        }
                    } else {
                        self.started = true;
                        self.start_fail_count = 0;
                    }
                }
            }
        }
        Ok(())
    }
}

impl Drop for AlsaMmapCtx {
    fn drop(&mut self) {
        if let Some(ref feed) = self.feed {
            feed.invalidate();
        }
        if !self.pcm.0.is_null() {
            unsafe {
                let _ = alsa_ffi::snd_pcm_drop(self.pcm.0);
                alsa_ffi::snd_pcm_close(self.pcm.0);
            }
            self.pcm.0 = std::ptr::null_mut();
        }
    }
}
