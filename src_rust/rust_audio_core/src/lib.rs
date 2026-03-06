use gst::prelude::*;
use gstreamer as gst;
use libpulse_binding as pulse;
use pipewire as pw;
use pulse::callbacks::ListResult;
use pulse::context::{Context as PaContext, FlagSet as PaContextFlagSet, State as PaContextState};
use pulse::mainloop::standard::Mainloop as PaMainloop;
use pulse::operation::State as PaOperationState;
use pulse::proplist::properties as pa_props;
use pw::{
    context::Context as PwContext, keys, main_loop::MainLoop as PwMainLoop,
    metadata::Metadata as PwMetadata, registry::GlobalObject, types::ObjectType,
};
use std::cell::{Cell, RefCell};
use std::collections::{HashMap, HashSet, VecDeque};
use std::env;
use std::ffi::{CStr, CString};
use std::io;
use std::os::raw::{c_char, c_double, c_int, c_void};
use std::path::Path;
use std::ptr;
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, Once};
use std::thread;
use std::time::Duration;

static GST_INIT: Once = Once::new();
static PW_INIT: Once = Once::new();
const SPECTRUM_BANDS_MAX: usize = 128;
const SPECTRUM_RING_CAP: usize = 512;
const PIPEWIRE_CARD_PROFILE_TARGET_PREFIX: &str = "pwcardprofile:";

// ---------------------------------------------------------------------------
// ALSA mmap support
// ---------------------------------------------------------------------------

/// Raw ALSA FFI declarations.  We link libasound via build.rs.
#[allow(non_camel_case_types, dead_code)]
mod alsa_ffi {
    use std::os::raw::{c_char, c_int, c_uint, c_void};

    pub type SndPcmUframes = std::os::raw::c_ulong;
    pub type SndPcmSframes = std::os::raw::c_long;

    // snd_pcm_stream_t
    pub const SND_PCM_STREAM_PLAYBACK: c_int = 0;
    // snd_pcm_access_t
    pub const SND_PCM_ACCESS_MMAP_INTERLEAVED: c_int = 0;
    // snd_pcm_format_t
    pub const SND_PCM_FORMAT_S16_LE: c_int = 2;
    pub const SND_PCM_FORMAT_S24_LE: c_int = 6;
    pub const SND_PCM_FORMAT_S32_LE: c_int = 10;

    #[repr(C)]
    pub struct SndPcmChannelArea {
        pub addr: *mut c_void,
        pub first: c_uint, // bit offset of first sample
        pub step: c_uint,  // distance between samples in bits
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
    }
}

/// Newtype so that a raw ALSA PCM pointer can cross thread boundaries.
struct AlsaHandle(*mut std::os::raw::c_void);
unsafe impl Send for AlsaHandle {}

type ThreadEventQueue = Arc<Mutex<VecDeque<(c_int, String)>>>;
type MmapThreadDiagnosticsHandle = Arc<Mutex<MmapThreadDiagnostics>>;

const ALSA_MMAP_RT_PRIORITY_DEFAULT: i32 = 60;
const ALSA_MMAP_MEMLOCK_MODE: &str = "current";
const ALSA_MMAP_ACCUM_RATE_BUDGET_HZ: u32 = 192_000;

#[derive(Debug, Clone, Default)]
struct MmapThreadDiagnostics {
    running: bool,
    realtime_attempted: bool,
    realtime_enabled: bool,
    realtime_policy: String,
    realtime_priority: i32,
    realtime_error: String,
    memlock_attempted: bool,
    memlock_enabled: bool,
    memlock_mode: String,
    memlock_error: String,
    negotiated_rate: u32,
    period_frames: usize,
    buffer_frames: usize,
    open_failures: u32,
    device_resets: u32,
}

fn push_thread_event(queue: &ThreadEventQueue, evt: c_int, msg: impl Into<String>) {
    if let Ok(mut pending) = queue.lock() {
        if pending.len() >= 32 {
            pending.pop_front();
        }
        pending.push_back((evt, msg.into()));
    }
}

fn update_mmap_thread_diagnostics(
    diagnostics: &MmapThreadDiagnosticsHandle,
    update: impl FnOnce(&mut MmapThreadDiagnostics),
) {
    if let Ok(mut state) = diagnostics.lock() {
        update(&mut state);
    }
}

fn format_errno(code: i32) -> String {
    format!("{code}: {}", io::Error::from_raw_os_error(code))
}

#[cfg(target_os = "linux")]
fn configure_mmap_thread_memlock(diagnostics: &MmapThreadDiagnosticsHandle) {
    update_mmap_thread_diagnostics(diagnostics, |state| {
        state.memlock_attempted = true;
        state.memlock_mode = ALSA_MMAP_MEMLOCK_MODE.to_string();
        state.memlock_enabled = false;
        state.memlock_error.clear();
    });

    let rc = unsafe { libc::mlockall(libc::MCL_CURRENT) };
    if rc == 0 {
        update_mmap_thread_diagnostics(diagnostics, |state| {
            state.memlock_enabled = true;
        });
        return;
    }

    let err = io::Error::last_os_error();
    let err_msg = err
        .raw_os_error()
        .map(format_errno)
        .unwrap_or_else(|| err.to_string());
    update_mmap_thread_diagnostics(diagnostics, |state| {
        state.memlock_error = err_msg;
    });
}

#[cfg(not(target_os = "linux"))]
fn configure_mmap_thread_memlock(diagnostics: &MmapThreadDiagnosticsHandle) {
    update_mmap_thread_diagnostics(diagnostics, |state| {
        state.memlock_attempted = false;
        state.memlock_enabled = false;
        state.memlock_mode = "unsupported".to_string();
        state.memlock_error = "unsupported-platform".to_string();
    });
}

#[cfg(target_os = "linux")]
fn clamp_mmap_thread_realtime_priority(requested_priority: i32) -> i32 {
    if requested_priority <= 0 {
        return 0;
    }
    unsafe {
        let min = libc::sched_get_priority_min(libc::SCHED_FIFO);
        let max = libc::sched_get_priority_max(libc::SCHED_FIFO);
        if min >= 0 && max >= 0 && min <= max {
            requested_priority.clamp(min, max)
        } else {
            requested_priority
        }
    }
}

#[cfg(target_os = "linux")]
fn configure_mmap_thread_realtime(
    diagnostics: &MmapThreadDiagnosticsHandle,
    requested_priority: i32,
) {
    let priority = clamp_mmap_thread_realtime_priority(requested_priority);
    if priority <= 0 {
        update_mmap_thread_diagnostics(diagnostics, |state| {
            state.realtime_attempted = false;
            state.realtime_enabled = false;
            state.realtime_policy = "SCHED_FIFO".to_string();
            state.realtime_priority = 0;
            state.realtime_error = "config".to_string();
        });
        return;
    }

    update_mmap_thread_diagnostics(diagnostics, |state| {
        state.realtime_attempted = true;
        state.realtime_enabled = false;
        state.realtime_policy = "SCHED_FIFO".to_string();
        state.realtime_priority = priority;
        state.realtime_error.clear();
    });

    let param = libc::sched_param {
        sched_priority: priority,
    };
    let rc = unsafe { libc::pthread_setschedparam(libc::pthread_self(), libc::SCHED_FIFO, &param) };
    if rc == 0 {
        update_mmap_thread_diagnostics(diagnostics, |state| {
            state.realtime_enabled = true;
        });
        return;
    }

    update_mmap_thread_diagnostics(diagnostics, |state| {
        state.realtime_error = format_errno(rc);
    });
}

#[cfg(not(target_os = "linux"))]
fn configure_mmap_thread_realtime(
    diagnostics: &MmapThreadDiagnosticsHandle,
    requested_priority: i32,
) {
    if requested_priority <= 0 {
        update_mmap_thread_diagnostics(diagnostics, |state| {
            state.realtime_attempted = false;
            state.realtime_enabled = false;
            state.realtime_policy = "SCHED_FIFO".to_string();
            state.realtime_priority = 0;
            state.realtime_error = "config".to_string();
        });
        return;
    }
    update_mmap_thread_diagnostics(diagnostics, |state| {
        state.realtime_attempted = false;
        state.realtime_enabled = false;
        state.realtime_policy = "unsupported".to_string();
        state.realtime_priority = 0;
        state.realtime_error = "unsupported-platform".to_string();
    });
}

fn format_mmap_thread_config_state(diagnostics: &MmapThreadDiagnosticsHandle) -> String {
    let state = diagnostics
        .lock()
        .map(|state| state.clone())
        .unwrap_or_default();

    let realtime = if state.realtime_enabled {
        format!("fifo:{}", state.realtime_priority)
    } else if state.realtime_attempted {
        format!(
            "off({})",
            if state.realtime_error.is_empty() {
                "unavailable"
            } else {
                state.realtime_error.as_str()
            }
        )
    } else if !state.realtime_error.is_empty() {
        format!("off({})", state.realtime_error)
    } else {
        "off".to_string()
    };

    let memlock = if state.memlock_enabled {
        state.memlock_mode.clone()
    } else if state.memlock_attempted {
        format!(
            "off({})",
            if state.memlock_error.is_empty() {
                "unavailable"
            } else {
                state.memlock_error.as_str()
            }
        )
    } else {
        "off".to_string()
    };

    format!("alsa-mmap thread-config realtime={realtime} memlock={memlock}")
}

fn configure_mmap_thread_runtime(
    diagnostics: &MmapThreadDiagnosticsHandle,
    events: &ThreadEventQueue,
    realtime_priority: i32,
) {
    configure_mmap_thread_memlock(diagnostics);
    configure_mmap_thread_realtime(diagnostics, realtime_priority);
    push_thread_event(
        events,
        EVT_STATE,
        format_mmap_thread_config_state(diagnostics),
    );
}

fn frames_for_duration_us(
    duration_us: i32,
    sample_rate: u32,
    min_frames: usize,
    max_frames: usize,
) -> usize {
    let duration_us = duration_us.max(0) as u64;
    let sample_rate = sample_rate.max(1) as u64;
    let frames = duration_us.saturating_mul(sample_rate) / 1_000_000;
    (frames as usize).clamp(min_frames, max_frames)
}

fn normalized_driver_label(driver: &str) -> String {
    driver
        .trim()
        .replace('（', "(")
        .replace('）', ")")
        .to_ascii_lowercase()
        .replace(' ', "")
}

fn driver_is_alsa_auto(driver: &str) -> bool {
    matches!(
        normalized_driver_label(driver).as_str(),
        "alsa" | "alsa(auto)"
    )
}

fn driver_is_alsa_mmap(driver: &str) -> bool {
    matches!(
        normalized_driver_label(driver).as_str(),
        "alsa_mmap" | "alsa(mmap)"
    )
}

fn driver_is_alsa_family(driver: &str) -> bool {
    driver_is_alsa_auto(driver) || driver_is_alsa_mmap(driver)
}

#[derive(Clone, Copy)]
struct MmapAudioFormat {
    gst_format: &'static str,
    alsa_format: c_int,
    frame_bytes: usize,
    log_label: &'static str,
}

fn mmap_audio_format_from_preference(preferred: &str) -> MmapAudioFormat {
    let norm = preferred.trim().to_ascii_uppercase();
    match norm.as_str() {
        "S16LE" | "S16_LE" => MmapAudioFormat {
            gst_format: "S16LE",
            alsa_format: alsa_ffi::SND_PCM_FORMAT_S16_LE,
            frame_bytes: 4,
            log_label: "S16_LE",
        },
        "S24LE" | "S24_LE" | "S24_32LE" | "S24_32_LE" => MmapAudioFormat {
            // ALSA mmap uses the 24-in-32 container layout here.
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

/// Open ALSA device state for mmap playback.
struct AlsaMmapCtx {
    pcm: AlsaHandle,
    period_frames: usize,
    buffer_frames: usize,
    frame_bytes: usize,
    /// Negotiated sample rate (may differ from requested)
    rate: u32,
    primed_frames: usize,
    started: bool,
    /// Consecutive snd_pcm_start failures since last successful start.
    /// Prevents the RT thread from retrying start indefinitely if the
    /// device is in a persistent error state.
    start_fail_count: u32,
    format_label: &'static str,
}

impl AlsaMmapCtx {
    /// Open `device` (e.g. `"hw:0,0"`) in MMAP_INTERLEAVED mode.
    /// `want_rate`, `want_period_frames`, and `want_buffer_frames` are hints;
    /// ALSA picks the nearest supported values.
    fn open(
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
        use std::os::raw::{c_int, c_uint, c_void};

        let dev_c = CString::new(device).map_err(|e| format!("bad device name: {e}"))?;
        let mut pcm: *mut c_void = std::ptr::null_mut();

        // --- open ---
        let rc = unsafe { snd_pcm_open(&mut pcm, dev_c.as_ptr(), SND_PCM_STREAM_PLAYBACK, 0) };
        if rc < 0 {
            return Err(format!("snd_pcm_open({device}) rc={rc}"));
        }

        // --- hw params ---
        let mut hw: *mut c_void = std::ptr::null_mut();
        let result: Result<(usize, usize, u32), String> = unsafe {
            if snd_pcm_hw_params_malloc(&mut hw) < 0 {
                snd_pcm_close(pcm);
                return Err("hw_params_malloc failed".into());
            }
            snd_pcm_hw_params_any(pcm, hw);

            macro_rules! hw_check {
                ($call:expr, $msg:literal) => {{
                    let rc: c_int = $call;
                    if rc < 0 {
                        snd_pcm_hw_params_free(hw);
                        snd_pcm_close(pcm);
                        return Err(format!("{}: rc={}", $msg, rc));
                    }
                }};
            }

            hw_check!(
                snd_pcm_hw_params_set_access(pcm, hw, SND_PCM_ACCESS_MMAP_INTERLEAVED),
                "set_access MMAP_INTERLEAVED"
            );
            hw_check!(
                snd_pcm_hw_params_set_format(pcm, hw, sample_format),
                "set_format"
            );
            hw_check!(snd_pcm_hw_params_set_channels(pcm, hw, 2), "set_channels 2");

            let mut rate: c_uint = want_rate;
            let mut dir: c_int = 0;
            hw_check!(
                snd_pcm_hw_params_set_rate_near(pcm, hw, &mut rate, &mut dir),
                "set_rate_near"
            );

            let mut period: SndPcmUframes = want_period_frames as SndPcmUframes;
            hw_check!(
                snd_pcm_hw_params_set_period_size_near(pcm, hw, &mut period, &mut dir),
                "set_period_size_near"
            );

            let min_buffer = period.saturating_mul(2);
            let want_buffer = (want_buffer_frames as SndPcmUframes).max(min_buffer);
            let mut bufsize: SndPcmUframes = want_buffer;
            hw_check!(
                snd_pcm_hw_params_set_buffer_size_near(pcm, hw, &mut bufsize),
                "set_buffer_size_near"
            );

            let rc = snd_pcm_hw_params(pcm, hw);
            snd_pcm_hw_params_free(hw);
            if rc < 0 {
                snd_pcm_close(pcm);
                return Err(format!("hw_params apply: rc={rc}"));
            }

            Ok((period as usize, bufsize as usize, rate))
        };

        let (period_frames, buffer_frames, rate) = result?;

        // --- sw params ---
        unsafe {
            let mut sw: *mut c_void = std::ptr::null_mut();
            if snd_pcm_sw_params_malloc(&mut sw) < 0 {
                snd_pcm_close(pcm);
                return Err("sw_params_malloc failed".into());
            }
            snd_pcm_sw_params_current(pcm, sw);
            // Disable auto-start and start explicitly after we have primed a
            // small amount of audio. This avoids deadlock on devices that do
            // not begin consuming frames until `snd_pcm_start()` is called.
            let start_threshold = (buffer_frames + 1) as SndPcmUframes;
            snd_pcm_sw_params_set_start_threshold(pcm, sw, start_threshold);
            // Wake the write thread when half a period of DMA space opens up,
            // rather than waiting for a full period.  This gives the thread a
            // head-start on the next write, reducing the chance of missing the
            // hardware deadline at the cost of one extra poll wakeup per period.
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
        })
    }

    /// Write exactly `frames` frames from `src` (interleaved S32_LE) via mmap.
    /// Blocks internally via snd_pcm_wait until hardware accepts each chunk.
    fn mmap_write(&mut self, src: &[u8], frames: usize, stop: &AtomicBool) -> Result<(), i32> {
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

            // Obtain pointer into the DMA ring buffer.
            let mut areas: *const SndPcmChannelArea = std::ptr::null();
            let mut offset: SndPcmUframes = 0;
            let rc = unsafe { snd_pcm_mmap_begin(pcm, &mut areas, &mut offset, &mut to_write) };
            if rc < 0 {
                let rec = unsafe { snd_pcm_recover(pcm, rc, 1) };
                if rec < 0 {
                    return Err(rec);
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
                }
                continue;
            }

            // Write directly into DMA memory.
            // snd_pcm_mmap_begin guarantees the returned chunk is contiguous
            // (to_write <= buffer_frames - offset), so no ring-wrap needed here.
            // area.first is the bit-offset of the first sample within area.addr;
            // divide by 8 to get the byte offset (always 0 on standard hardware,
            // but handle it correctly for non-standard layouts).
            unsafe {
                let area = &*areas;
                let first_byte = area.first as usize / 8;
                let dst = (area.addr as *mut u8).add(first_byte + offset as usize * frame_bytes);
                let src_ptr = src.as_ptr().add(src_offset);
                std::ptr::copy_nonoverlapping(src_ptr, dst, to_write as usize * frame_bytes);
            }

            // Advance the application pointer; this signals new data to the USB driver.
            let committed = unsafe { snd_pcm_mmap_commit(pcm, offset, to_write) };
            if committed < 0 {
                let rec = unsafe { snd_pcm_recover(pcm, committed as i32, 1) };
                if rec < 0 {
                    return Err(rec);
                }
                continue;
            }

            let committed = committed as usize;
            src_offset += committed * frame_bytes;
            remaining -= committed;
            if !self.started {
                self.primed_frames = self.primed_frames.saturating_add(committed);
                // Pre-fill 3 periods before starting.  The extra period absorbs
                // occasional decode or network jitter spikes without causing an
                // underrun; the cost is ~1 period of additional start-up latency.
                let prime_target = self.period_frames.saturating_mul(3).min(self.buffer_frames);
                if self.primed_frames >= prime_target.max(1) {
                    let start_rc = unsafe { snd_pcm_start(pcm) };
                    if start_rc < 0 {
                        let rec = unsafe { snd_pcm_recover(pcm, start_rc, 1) };
                        if rec < 0 {
                            return Err(rec);
                        }
                        // recover succeeded but start failed — count consecutive
                        // failures so the RT thread does not retry forever.
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
        if !self.pcm.0.is_null() {
            unsafe {
                // Teardown happens on track switches and app shutdown. Discard
                // pending frames immediately instead of waiting for drain.
                let _ = alsa_ffi::snd_pcm_drop(self.pcm.0);
                alsa_ffi::snd_pcm_close(self.pcm.0);
            }
            self.pcm.0 = std::ptr::null_mut();
        }
    }
}

/// Handle held by Engine to manage the mmap writer thread.
struct MmapSink {
    stop: Arc<AtomicBool>,
    events: ThreadEventQueue,
    diagnostics: MmapThreadDiagnosticsHandle,
    thread: Option<thread::JoinHandle<()>>,
}

impl std::fmt::Debug for MmapSink {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "MmapSink(running={})", self.thread.is_some())
    }
}

/// Preallocated byte window for decoded PCM.
///
/// Unlike `Vec::drain(..period_bytes)`, this keeps a read offset and only
/// compacts when the stale prefix grows large enough to matter, removing the
/// per-period memmove from the mmap writer hot path.
#[derive(Debug)]
struct AudioByteWindow {
    buf: Vec<u8>,
    start: usize,
}

impl AudioByteWindow {
    fn with_capacity(capacity: usize) -> Self {
        let cap = capacity.max(1);
        let mut buf = Vec::with_capacity(cap);
        // Pre-fault all pages so that a subsequent mlockall(MCL_CURRENT) can
        // pin them.  Vec::with_capacity only reserves virtual address space;
        // the OS does not back the pages with physical memory until they are
        // first written.
        buf.resize(cap, 0u8);
        buf.clear(); // reset len to 0, capacity is preserved
        Self { buf, start: 0 }
    }

    fn clear(&mut self) {
        self.buf.clear();
        self.start = 0;
    }

    fn len(&self) -> usize {
        self.buf.len().saturating_sub(self.start)
    }

    fn append(&mut self, src: &[u8]) {
        if src.is_empty() {
            return;
        }
        self.make_room(src.len());
        self.buf.extend_from_slice(src);
    }

    fn peek_prefix(&self, len: usize) -> Option<&[u8]> {
        if self.len() < len {
            return None;
        }
        Some(&self.buf[self.start..self.start + len])
    }

    fn consume(&mut self, len: usize) {
        if len == 0 {
            return;
        }
        self.start = self.start.saturating_add(len).min(self.buf.len());
        if self.start >= self.buf.len() {
            self.clear();
            return;
        }

        // Compact only when the stale prefix is at least as large as the live
        // tail, or it has grown to a sizeable chunk.
        let live_len = self.buf.len() - self.start;
        if self.start >= live_len || self.start >= 65_536 {
            self.compact();
        }
    }

    fn make_room(&mut self, incoming_len: usize) {
        let free_tail = self.buf.capacity().saturating_sub(self.buf.len());
        if free_tail >= incoming_len {
            return;
        }

        self.compact();
        let free_tail = self.buf.capacity().saturating_sub(self.buf.len());
        if free_tail < incoming_len {
            self.buf.reserve(incoming_len - free_tail);
        }
    }

    fn compact(&mut self) {
        if self.start == 0 {
            return;
        }
        if self.start >= self.buf.len() {
            self.clear();
            return;
        }

        self.buf.copy_within(self.start.., 0);
        let live_len = self.buf.len() - self.start;
        self.buf.truncate(live_len);
        self.start = 0;
    }
}

/// Background thread: pulls decoded PCM from appsink, writes to ALSA via mmap.
///
/// Design notes:
/// - `appsink` has caps `audio/x-raw,format=S32LE,layout=interleaved` so GStreamer
///   converts the format upstream.  Rate is left unconstrained; we derive ALSA
///   period/buffer frame counts from the actual sample rate and reopen only if
///   it changes.
/// - `snd_pcm_wait()` inside mmap_write() provides natural back-pressure: the thread
///   blocks until the hardware consumes one period, pacing the GStreamer pull rate.
/// - `try-pull-sample` keeps the thread responsive to stop/flush transitions.
///   Pipeline set_state(NULL) is treated as a transient reset unless `stop` is
///   set, so URI changes can reuse the same sink.
/// - Decoded PCM accumulates in a preallocated sliding window so appends stay
///   cheap without `Vec::drain(..)` memmoves on every period commit.
fn alsa_mmap_writer_thread(
    appsink: gst::Element,
    device: String,
    period_us: i32,
    target_buffer_us: i32,
    mut accum: AudioByteWindow,
    audio_format: MmapAudioFormat,
    stop: Arc<AtomicBool>,
    events: ThreadEventQueue,
    diagnostics: MmapThreadDiagnosticsHandle,
) {
    // Prevent the CPU from entering deep C-states (C2+) during playback.
    // Deep C-states have wakeup latencies of 100–300 µs; keeping the CPU in
    // C0/C1 ensures snd_pcm_wait() wake-ups are serviced promptly.
    // Writing 0 (latency budget = 0 µs) to /dev/cpu_dma_latency is the
    // standard mechanism used by PipeWire, JACK, and rtkit.
    // The file descriptor is held until this thread exits (drop closes it).
    let _cpu_dma_latency_guard: Option<std::fs::File> = {
        use std::io::Write;
        std::fs::OpenOptions::new()
            .write(true)
            .open("/dev/cpu_dma_latency")
            .ok()
            .and_then(|mut f| f.write_all(&0i32.to_ne_bytes()).ok().map(|_| f))
    };

    let mut ctx: Option<AlsaMmapCtx> = None;
    let mut last_rate: u32 = 0;
    let mut open_fail_count: u32 = 0;
    // Tracks idle pre-warm attempts (separate from open_fail_count which is
    // used only when samples are flowing).
    let mut idle_open_attempts: u32 = 0;
    // True once the first PCM sample has been received.  Used to decide
    // whether to release the ALSA handle on pipeline-NULL transitions: we
    // hold the pre-warmed handle until actual playback begins so the device
    // is already open when the user clicks play.
    let mut ever_playing = false;
    let mut dma_locked = false;

    loop {
        if stop.load(Ordering::Relaxed) {
            break;
        }

        // Use a timed pull so track switches and app shutdown do not strand the
        // writer thread inside an uninterruptible appsink wait.
        let sample =
            appsink.emit_by_name::<Option<gst::Sample>>("try-pull-sample", &[&100_000_000u64]);
        let sample = match sample {
            None => {
                // Release the ALSA handle only once we have been actively
                // playing.  Before the first play, keep a pre-warmed handle
                // open so the device is ready immediately when play starts.
                if ever_playing {
                    ctx = None;
                }
                accum.clear();
                if stop.load(Ordering::Relaxed) {
                    break;
                }
                // Pre-warm: while the pipeline is idle (NULL/READY), try to
                // open the ALSA device in the background.  This is especially
                // important after switching away from the PipeWire driver:
                // PipeWire releases its hold on the ALSA device asynchronously,
                // so retrying here (with backoff) ensures the device is free
                // before the user clicks play.
                if ctx.is_none() && idle_open_attempts < 20 {
                    let rate = if last_rate > 0 { last_rate } else { 44100 };
                    let pf = frames_for_duration_us(period_us, rate, 64, 4096);
                    let bf = frames_for_duration_us(
                        target_buffer_us,
                        rate,
                        pf.saturating_mul(2),
                        16_384,
                    );
                    match AlsaMmapCtx::open(
                        &device,
                        rate,
                        pf as u32,
                        bf as u32,
                        audio_format.alsa_format,
                        audio_format.frame_bytes,
                        audio_format.log_label,
                    ) {
                        Ok(c) => {
                            eprintln!(
                                "[alsa-mmap] pre-warmed {} format={} rate={}",
                                device, c.format_label, c.rate
                            );
                            update_mmap_thread_diagnostics(&diagnostics, |state| {
                                state.negotiated_rate = c.rate;
                                state.period_frames = c.period_frames;
                                state.buffer_frames = c.buffer_frames;
                            });
                            last_rate = rate;
                            idle_open_attempts = 0;
                            if !dma_locked {
                                unsafe { libc::mlockall(libc::MCL_CURRENT) };
                                dma_locked = true;
                            }
                            ctx = Some(c);
                        }
                        Err(e) => {
                            idle_open_attempts += 1;
                            eprintln!(
                                "[alsa-mmap] pre-warm attempt {}: {} \
                                 — device busy (PipeWire still releasing?)",
                                idle_open_attempts, e
                            );
                            if idle_open_attempts == 3 {
                                push_thread_event(
                                    &events,
                                    EVT_ERROR,
                                    format!(
                                        "alsa-mmap open failed after {} attempts: {}",
                                        idle_open_attempts, e
                                    ),
                                );
                            }
                            let backoff_ms = if idle_open_attempts <= 5 { 200 } else { 300 };
                            thread::sleep(Duration::from_millis(backoff_ms));
                            continue;
                        }
                    }
                }
                // In NULL/READY or during short route rebuild gaps, appsink can
                // return immediately without blocking. Back off a little here so
                // the realtime thread does not busy-spin while no PCM is flowing.
                thread::sleep(Duration::from_millis(10));
                continue;
            }
            Some(s) => s,
        };

        // First sample received — switch to active-playback mode.
        ever_playing = true;
        idle_open_attempts = 0;

        // Detect sample rate; (re)open ALSA when it changes.
        let rate = sample
            .caps()
            .and_then(|c| c.structure(0))
            .and_then(|s| s.get::<i32>("rate").ok())
            .unwrap_or(44100) as u32;

        if ctx.is_none() || rate != last_rate {
            ctx = None; // Drop old ctx → closes ALSA via Drop
            accum.clear();
            let period_frames = frames_for_duration_us(period_us, rate, 64, 4096);
            let buffer_frames = frames_for_duration_us(
                target_buffer_us,
                rate,
                period_frames.saturating_mul(2),
                16_384,
            );
            match AlsaMmapCtx::open(
                &device,
                rate,
                period_frames as u32,
                buffer_frames as u32,
                audio_format.alsa_format,
                audio_format.frame_bytes,
                audio_format.log_label,
            ) {
                Ok(c) => {
                    eprintln!(
                        "[alsa-mmap] opened {} format={} rate={} period={} buffer={} frames",
                        device, c.format_label, c.rate, c.period_frames, c.buffer_frames
                    );
                    update_mmap_thread_diagnostics(&diagnostics, |state| {
                        state.negotiated_rate = c.rate;
                        state.period_frames = c.period_frames;
                        state.buffer_frames = c.buffer_frames;
                    });
                    last_rate = rate;
                    open_fail_count = 0;
                    if !dma_locked {
                        // Re-lock now that ALSA DMA pages are mapped.
                        unsafe { libc::mlockall(libc::MCL_CURRENT) };
                        dma_locked = true;
                    }
                    ctx = Some(c);
                }
                Err(e) => {
                    update_mmap_thread_diagnostics(&diagnostics, |state| {
                        state.open_failures = state.open_failures.saturating_add(1);
                    });
                    open_fail_count += 1;
                    eprintln!(
                        "[alsa-mmap] open failed (attempt {}): {}  \
                         — is the device busy (PipeWire/PulseAudio)?  \
                         Try: systemctl --user stop pipewire pipewire-pulse",
                        open_fail_count, e
                    );
                    // Notify the UI on the first threshold so the user sees an
                    // error promptly, but keep retrying — the device may become
                    // available within a few seconds (e.g. PipeWire releasing it).
                    if open_fail_count == 3 {
                        push_thread_event(
                            &events,
                            EVT_ERROR,
                            format!(
                                "alsa-mmap open failed after {} attempts: {}",
                                open_fail_count, e
                            ),
                        );
                    }
                    // Give up only after a sustained run of failures (~20 × backoff ≈ 4 s).
                    if open_fail_count >= 20 {
                        eprintln!(
                            "[alsa-mmap] giving up after {} failures, stopping mmap thread",
                            open_fail_count
                        );
                        break;
                    }
                    // Back off between open attempts so PipeWire/WirePlumber has time
                    // to release the ALSA device after the previous driver disconnects.
                    // Early attempts: 200 ms; later attempts: 300 ms.
                    let backoff_ms = if open_fail_count <= 5 { 200 } else { 300 };
                    thread::sleep(Duration::from_millis(backoff_ms));
                    continue;
                }
            }
        }

        let period_bytes = {
            let ctx = ctx.as_ref().unwrap();
            ctx.period_frames * ctx.frame_bytes
        };

        // Accumulate incoming PCM bytes.
        if let Some(buf) = sample.buffer() {
            if let Ok(map) = buf.map_readable() {
                accum.append(map.as_slice());
            }
        }

        // Write complete periods to ALSA.
        let mut write_failed = None;
        while accum.len() >= period_bytes {
            let frames = ctx.as_ref().map(|c| c.period_frames).unwrap_or(0);
            let rc = {
                let ctx = ctx.as_mut().unwrap();
                let src = accum.peek_prefix(period_bytes).unwrap_or(&[]);
                ctx.mmap_write(src, frames, &stop)
            };
            if let Err(rc) = rc {
                write_failed = Some(rc);
                break;
            }
            accum.consume(period_bytes);
        }
        if let Some(rc) = write_failed {
            if stop.load(Ordering::Relaxed) || rc == -125 {
                break;
            }
            update_mmap_thread_diagnostics(&diagnostics, |state| {
                state.device_resets = state.device_resets.saturating_add(1);
            });
            push_thread_event(
                &events,
                EVT_ERROR,
                format!("alsa-mmap write failed rc={rc}; resetting device"),
            );
            ctx = None;
            last_rate = 0;
            accum.clear();
        }
    }
    // ctx drops here → snd_pcm_drop + snd_pcm_close via AlsaMmapCtx::drop
}

// ---------------------------------------------------------------------------

type EventCallback = extern "C" fn(c_int, *const c_char, *mut c_void);
const EVT_STATE: c_int = 1;
const EVT_ERROR: c_int = 2;
const EVT_EOS: c_int = 3;
const EVT_TAG: c_int = 4;

fn json_escape(v: &str) -> String {
    let mut out = String::with_capacity(v.len() + 8);
    for ch in v.chars() {
        match ch {
            '\"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => out.push(' '),
            c => out.push(c),
        }
    }
    out
}

fn build_pipewire_card_profile_target(card: &str, profile: &str) -> String {
    format!(
        "{PIPEWIRE_CARD_PROFILE_TARGET_PREFIX}{}|{}",
        card.trim(),
        profile.trim()
    )
}

fn parse_pipewire_card_profile_target(device_id: &str) -> Option<(String, String)> {
    let raw = device_id.trim();
    let tail = raw.strip_prefix(PIPEWIRE_CARD_PROFILE_TARGET_PREFIX)?;
    let (card, profile) = tail.split_once('|')?;
    let card = card.trim();
    let profile = profile.trim();
    if card.is_empty() || profile.is_empty() {
        return None;
    }
    Some((card.to_string(), profile.to_string()))
}

#[derive(Debug)]
pub struct Engine {
    playbin: gst::Element,
    _audio_filter_bin: Option<gst::Bin>,
    uri: String,
    last_error: Option<String>,
    event_cb: Option<EventCallback>,
    event_user_data: *mut c_void,
    playback_rate: f64,
    pitch_semitones: f64,
    spectrum_seq: u64,
    spectrum_pos_s: f64,
    spectrum_vals: [f32; SPECTRUM_BANDS_MAX],
    spectrum_len: usize,
    spectrum_ring_vals: [[f32; SPECTRUM_BANDS_MAX]; SPECTRUM_RING_CAP],
    spectrum_ring_len: [u16; SPECTRUM_RING_CAP],
    spectrum_ring_pos_s: [f64; SPECTRUM_RING_CAP],
    spectrum_ring_seq: [u64; SPECTRUM_RING_CAP],
    spectrum_ring_write: usize,
    spectrum_ring_count: usize,
    spectrum_seen_msgs: u64,
    spectrum_msg_count: u64,
    element_msg_seen: u64,
    fmt_probe_tick: u64,
    last_codec: String,
    last_bitrate: i32,
    last_rate: i32,
    last_depth: i32,
    source_rate: i32,
    source_depth: i32,
    preferred_output_format: String,
    spectrum_enabled: bool,
    mmap_sink: Option<MmapSink>,
    output_mmap_realtime_priority: i32,
    output_driver: String,
    output_device: Option<String>,
    output_buffer_us: i32,
    output_latency_us: i32,
    output_exclusive: bool,
}

impl Engine {
    fn ensure_pw_init() {
        PW_INIT.call_once(|| {
            pw::init();
        });
    }

    fn pipewire_set_settings_metadata(
        key: &str,
        value: &str,
        value_type: Option<&str>,
    ) -> Result<(), String> {
        Self::ensure_pw_init();
        let result = (|| -> Result<(), String> {
            let mainloop = PwMainLoop::new(None).map_err(|e| format!("pw mainloop: {e}"))?;
            let context = PwContext::new(&mainloop).map_err(|e| format!("pw context: {e}"))?;
            let core = context
                .connect(None)
                .map_err(|e| format!("pw connect: {e}"))?;
            let registry = core
                .get_registry()
                .map_err(|e| format!("pw registry: {e}"))?;

            use std::{cell::Cell, rc::Rc};
            let done = Rc::new(Cell::new(false));
            let found_meta_id = Rc::new(Cell::new(u32::MAX));

            let done_clone = done.clone();
            let ml_quit = mainloop.clone();
            let found_clone = found_meta_id.clone();

            let _listener_reg = registry
                .add_listener_local()
                .global(move |global| {
                    if global.type_ != ObjectType::Metadata {
                        return;
                    }
                    let Some(props) = global.props else {
                        return;
                    };
                    let name = props.get("metadata.name");
                    if name == Some("settings") {
                        found_clone.set(global.id);
                    }
                })
                .register();

            let pending = core.sync(0).map_err(|e| format!("pw sync: {e}"))?;
            let _listener_core = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending {
                        done_clone.set(true);
                        ml_quit.quit();
                    }
                })
                .register();

            while !done.get() {
                mainloop.run();
            }

            let meta_id = found_meta_id.get();
            if meta_id == u32::MAX {
                return Err("pw metadata 'settings' not found".to_string());
            }

            let obj = GlobalObject {
                id: meta_id,
                permissions: pw::permissions::PermissionFlags::all(),
                type_: ObjectType::Metadata,
                version: pw::sys::PW_VERSION_METADATA,
                props: Option::<pw::properties::Properties>::None,
            };
            let metadata: PwMetadata = registry
                .bind(&obj)
                .map_err(|e| format!("pw bind metadata: {e}"))?;
            metadata.set_property(0, key, value_type, Some(value));
            // set_property is asynchronous. Wait for a core sync round-trip so
            // subsequent readers are less likely to observe stale metadata.
            let done3 = Rc::new(Cell::new(false));
            let done3_clone = done3.clone();
            let ml_quit3 = mainloop.clone();
            let pending3 = core.sync(0).map_err(|e| format!("pw sync3: {e}"))?;
            let _listener_core3 = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending3 {
                        done3_clone.set(true);
                        ml_quit3.quit();
                    }
                })
                .register();
            while !done3.get() {
                mainloop.run();
            }
            Ok(())
        })();
        result
    }

    fn pipewire_set_clock_force_rate(rate: i32) -> Result<(), String> {
        let value = if rate <= 0 {
            "0".to_string()
        } else {
            rate.to_string()
        };
        Self::pipewire_set_settings_metadata("clock.force-rate", &value, Some("Spa:Int"))
    }

    fn pipewire_set_clock_allowed_rates_csv(csv: &str) -> Result<(), String> {
        let mut vals: Vec<i32> = Vec::new();
        for p in csv.split(',') {
            let t = p.trim();
            if t.is_empty() {
                continue;
            }
            if let Ok(v) = t.parse::<i32>() {
                if v > 0 {
                    vals.push(v);
                }
            }
        }
        if vals.is_empty() {
            return Err("empty allowed-rates".to_string());
        }
        vals.sort_unstable();
        vals.dedup();
        let arr = format!(
            "[ {} ]",
            vals.iter()
                .map(|v| v.to_string())
                .collect::<Vec<_>>()
                .join(" ")
        );
        // Keep type empty for array-like values.
        Self::pipewire_set_settings_metadata("clock.allowed-rates", &arr, None)
    }

    fn pipewire_read_settings_metadata() -> Result<(i32, String, i32, i32), String> {
        Self::ensure_pw_init();
        let result = (|| -> Result<(i32, String, i32, i32), String> {
            let mainloop = PwMainLoop::new(None).map_err(|e| format!("pw mainloop: {e}"))?;
            let context = PwContext::new(&mainloop).map_err(|e| format!("pw context: {e}"))?;
            let core = context
                .connect(None)
                .map_err(|e| format!("pw connect: {e}"))?;
            let registry = core
                .get_registry()
                .map_err(|e| format!("pw registry: {e}"))?;

            let done = Rc::new(Cell::new(false));
            let found_meta_id = Rc::new(Cell::new(u32::MAX));
            let force_rate = Rc::new(Cell::new(0i32));
            let allowed_raw = Rc::new(RefCell::new(String::new()));
            let clock_quantum = Rc::new(Cell::new(0i32));
            let clock_rate = Rc::new(Cell::new(0i32));

            let done_clone = done.clone();
            let ml_quit = mainloop.clone();
            let found_clone = found_meta_id.clone();

            let _listener_reg = registry
                .add_listener_local()
                .global(move |global| {
                    if global.type_ != ObjectType::Metadata {
                        return;
                    }
                    let Some(props) = global.props else {
                        return;
                    };
                    let name = props.get("metadata.name");
                    if name == Some("settings") {
                        found_clone.set(global.id);
                    }
                })
                .register();

            let pending = core.sync(0).map_err(|e| format!("pw sync: {e}"))?;
            let _listener_core = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending {
                        done_clone.set(true);
                        ml_quit.quit();
                    }
                })
                .register();

            while !done.get() {
                mainloop.run();
            }

            let meta_id = found_meta_id.get();
            if meta_id == u32::MAX {
                return Err("pw metadata 'settings' not found".to_string());
            }

            let obj = GlobalObject {
                id: meta_id,
                permissions: pw::permissions::PermissionFlags::all(),
                type_: ObjectType::Metadata,
                version: pw::sys::PW_VERSION_METADATA,
                props: Option::<pw::properties::Properties>::None,
            };
            let metadata: PwMetadata = registry
                .bind(&obj)
                .map_err(|e| format!("pw bind metadata: {e}"))?;

            let fr = force_rate.clone();
            let ar = allowed_raw.clone();
            let cq = clock_quantum.clone();
            let cr = clock_rate.clone();
            let _listener_meta = metadata
                .add_listener_local()
                .property(move |_subject, key, _ty, value| {
                    let Some(k) = key else {
                        return 0;
                    };
                    let v = value.unwrap_or("").trim().to_string();
                    if k == "clock.force-rate" {
                        if let Ok(parsed) = v.parse::<i32>() {
                            fr.set(parsed.max(0));
                        }
                    } else if k == "clock.allowed-rates" {
                        *ar.borrow_mut() = v;
                    } else if k == "clock.quantum" {
                        if let Ok(parsed) = v.parse::<i32>() {
                            cq.set(parsed.max(0));
                        }
                    } else if k == "clock.rate" {
                        if let Ok(parsed) = v.parse::<i32>() {
                            cr.set(parsed.max(0));
                        }
                    }
                    0
                })
                .register();

            // Trigger one more sync to flush current metadata properties into listener.
            let done2 = Rc::new(Cell::new(false));
            let done2_clone = done2.clone();
            let ml_quit2 = mainloop.clone();
            let pending2 = core.sync(0).map_err(|e| format!("pw sync2: {e}"))?;
            let _listener_core2 = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending2 {
                        done2_clone.set(true);
                        ml_quit2.quit();
                    }
                })
                .register();
            while !done2.get() {
                mainloop.run();
            }

            let allowed = allowed_raw.borrow().clone();
            Ok((
                force_rate.get(),
                allowed,
                clock_quantum.get(),
                clock_rate.get(),
            ))
        })();
        result
    }

    fn parse_fraction_ms(txt: &str) -> Option<f64> {
        let s = txt.trim();
        if s.is_empty() {
            return None;
        }
        if let Some((a, b)) = s.split_once('/') {
            let num = a.trim().parse::<f64>().ok()?;
            let den = b.trim().parse::<f64>().ok()?;
            if den > 0.0 {
                return Some((num / den) * 1000.0);
            }
            return None;
        }
        let v = s.parse::<f64>().ok()?;
        if v.is_finite() && v >= 0.0 {
            // Fallback: treat plain number as milliseconds.
            return Some(v);
        }
        None
    }

    fn pipewire_query_app_node_latency_ms() -> Option<f64> {
        Self::ensure_pw_init();
        let result = (|| -> Option<f64> {
            let mainloop = PwMainLoop::new(None).ok()?;
            let context = PwContext::new(&mainloop).ok()?;
            let core = context.connect(None).ok()?;
            let registry = core.get_registry().ok()?;

            let done = Rc::new(Cell::new(false));
            let found_ms = Rc::new(Cell::new(-1.0f64));

            let done_clone = done.clone();
            let ml_quit = mainloop.clone();
            let found_clone = found_ms.clone();

            let pid_str = std::process::id().to_string();
            let mut_fallback = Rc::new(Cell::new(-1.0f64));
            let fallback_clone = mut_fallback.clone();
            let _listener_reg = registry
                .add_listener_local()
                .global(move |global| {
                    if global.type_ != ObjectType::Node {
                        return;
                    }
                    let Some(props) = global.props else {
                        return;
                    };
                    let media = props.get(*keys::MEDIA_CLASS).unwrap_or("");
                    // App stream node usually appears as Stream/Output/Audio.
                    if !media.contains("Stream/Output/Audio") {
                        return;
                    }
                    let app_pid = props.get(*keys::APP_PROCESS_ID).unwrap_or("");
                    let app_bin = props.get(*keys::APP_PROCESS_BINARY).unwrap_or("");
                    let app_name = props.get(*keys::APP_NAME).unwrap_or("");
                    let lat = props
                        .get(*keys::NODE_LATENCY)
                        .or_else(|| props.get(*keys::NODE_MAX_LATENCY))
                        .unwrap_or("");
                    if let Some(ms) = Self::parse_fraction_ms(lat) {
                        // Exact match: current process id.
                        if app_pid == pid_str {
                            found_clone.set(ms);
                            return;
                        }
                        // Fallback heuristic for wrapped python runtimes.
                        if app_bin.contains("python")
                            || app_name.to_ascii_lowercase().contains("hiresti")
                        {
                            found_clone.set(ms);
                            return;
                        }
                        // Last fallback: keep first stream latency candidate.
                        if fallback_clone.get() < 0.0 {
                            fallback_clone.set(ms);
                        }
                    }
                })
                .register();

            let pending = core.sync(0).ok()?;
            let _listener_core = core
                .add_listener_local()
                .done(move |id, seq| {
                    if id == pw::core::PW_ID_CORE && seq == pending {
                        done_clone.set(true);
                        ml_quit.quit();
                    }
                })
                .register();

            while !done.get() {
                mainloop.run();
            }

            let v = found_ms.get();
            if v >= 0.0 {
                Some(v)
            } else {
                let fb = mut_fallback.get();
                if fb >= 0.0 {
                    Some(fb)
                } else {
                    None
                }
            }
        })();
        result
    }

    fn parse_tag_text_value(text: &str, key: &str) -> Option<String> {
        let lower = text.to_ascii_lowercase();
        let pat = format!("{key}=");
        // GStreamer serialises a TagList as "taglist, k1=(type)v1, k2=(type)v2, ...".
        // A bare find("bitrate=") would also hit "maximum-bitrate=" or
        // "nominal-bitrate=" since they contain "bitrate=" as a substring.
        // Anchor the search on the ", " field separator to match the exact key.
        let boundary = format!(", {key}=");
        let pos = lower
            .find(&boundary)
            .map(|p| p + 2) // skip leading ", "
            .or_else(|| {
                // Edge case: key is the very first field (no leading ", ").
                // GStreamer always prepends "taglist, " so the byte before
                // key= is a space; guard against substring matches anyway.
                lower
                    .find(&pat)
                    .filter(|&p| p == 0 || lower.as_bytes().get(p.wrapping_sub(1)) == Some(&b' '))
            })?;
        let rest = &text[(pos + pat.len())..];
        let mut out = String::new();
        for ch in rest.chars() {
            if ch == ',' || ch == ';' || ch == '}' || ch == '\n' {
                break;
            }
            out.push(ch);
        }
        let mut v = out.trim().to_string();
        if let Some(idx) = v.find(')') {
            v = v[(idx + 1)..].trim().to_string();
        }
        if v.starts_with('"') && v.ends_with('"') && v.len() >= 2 {
            v = v[1..(v.len() - 1)].to_string();
        }
        if v.is_empty() {
            None
        } else {
            Some(v)
        }
    }

    fn parse_depth_from_format(fmt: &str) -> Option<i32> {
        let up = fmt.to_ascii_uppercase();
        if up.contains("S24_32") {
            return Some(24);
        }
        let mut digits = String::new();
        for ch in up.chars() {
            if ch.is_ascii_digit() {
                digits.push(ch);
            } else if !digits.is_empty() {
                break;
            }
        }
        if digits.is_empty() {
            return None;
        }
        digits.parse::<i32>().ok().filter(|v| *v > 0)
    }

    fn parse_source_rate_depth_from_codec_text(codec: &str) -> (Option<i32>, Option<i32>) {
        let low = codec.to_ascii_lowercase();
        let mut rate: Option<i32> = None;
        let mut depth: Option<i32> = None;

        // Example: "FLAC, 44100 Hz, 16-bit"
        if let Some(pos) = low.find("hz") {
            let pre = &low[..pos];
            let mut digits_rev: Vec<char> = Vec::new();
            for ch in pre.chars().rev() {
                if ch.is_ascii_digit() {
                    digits_rev.push(ch);
                } else if !digits_rev.is_empty() {
                    break;
                }
            }
            if !digits_rev.is_empty() {
                let s: String = digits_rev.into_iter().rev().collect();
                if let Ok(v) = s.parse::<i32>() {
                    if v > 0 {
                        rate = Some(v);
                    }
                }
            }
        }

        if let Some(pos) = low.find("-bit").or_else(|| low.find(" bit")) {
            let pre = &low[..pos];
            let mut digits_rev: Vec<char> = Vec::new();
            for ch in pre.chars().rev() {
                if ch.is_ascii_digit() {
                    digits_rev.push(ch);
                } else if !digits_rev.is_empty() {
                    break;
                }
            }
            if !digits_rev.is_empty() {
                let s: String = digits_rev.into_iter().rev().collect();
                if let Ok(v) = s.parse::<i32>() {
                    if v > 0 {
                        depth = Some(v);
                    }
                }
            }
        }

        (rate, depth)
    }

    fn clocktime_to_s(v: gst::ClockTime) -> Option<f64> {
        let ns = v.nseconds();
        if ns == 0 {
            return None;
        }
        Some((ns as f64) / 1_000_000_000.0)
    }

    fn spectrum_time_from_structure(s: &gst::StructureRef) -> Option<(f64, &'static str)> {
        // Prefer endtime/running-time style fields carried by spectrum element
        // over pull-time query_position to avoid clock-domain skew.
        for key in ["endtime", "running-time", "stream-time", "timestamp"] {
            if let Ok(v) = s.get::<gst::ClockTime>(key) {
                if let Some(sec) = Self::clocktime_to_s(v) {
                    return Some((sec, key));
                }
            }
            if let Ok(v) = s.get::<u64>(key) {
                if v > 0 {
                    return Some(((v as f64) / 1_000_000_000.0, key));
                }
            }
            if let Ok(v) = s.get::<i64>(key) {
                if v > 0 {
                    return Some(((v as f64) / 1_000_000_000.0, key));
                }
            }
        }
        None
    }

    fn query_output_format(&self) -> (Option<i32>, Option<i32>) {
        let sink: Option<gst::Element> = self.playbin.property("audio-sink");
        let Some(sink) = sink else {
            return (None, None);
        };
        let Some(pad) = sink.static_pad("sink") else {
            return (None, None);
        };
        let caps = pad.current_caps().or_else(|| pad.allowed_caps());
        let Some(caps) = caps else {
            return (None, None);
        };
        let Some(st) = caps.structure(0) else {
            return (None, None);
        };

        let rate = st.get::<i32>("rate").ok().filter(|v| *v > 0);
        let depth = st
            .get::<String>("format")
            .ok()
            .as_deref()
            .and_then(Self::parse_depth_from_format);
        (rate, depth)
    }

    fn maybe_emit_tag_update(
        &mut self,
        codec: Option<String>,
        bitrate: Option<i32>,
        rate: Option<i32>,
        depth: Option<i32>,
    ) {
        let mut changed = false;
        if let Some(c) = codec {
            if !c.is_empty() && c != self.last_codec {
                self.last_codec = c;
                changed = true;
            }
        }
        if let Some(br) = bitrate {
            if br > 0 && br != self.last_bitrate {
                self.last_bitrate = br;
                changed = true;
            }
        }
        if let Some(r) = rate {
            if r > 0 && r != self.last_rate {
                self.last_rate = r;
                changed = true;
            }
        }
        if let Some(d) = depth {
            if d > 0 && d != self.last_depth {
                self.last_depth = d;
                changed = true;
            }
        }
        if !changed {
            return;
        }
        let mut parts: Vec<String> = Vec::new();
        if !self.last_codec.is_empty() {
            parts.push(format!("codec={}", self.last_codec));
        }
        if self.last_bitrate > 0 {
            parts.push(format!("bitrate={}", self.last_bitrate));
        }
        if self.last_rate > 0 {
            parts.push(format!("rate={}", self.last_rate));
        }
        if self.last_depth > 0 {
            parts.push(format!("depth={}", self.last_depth));
        }
        // Always include parsed source format alongside the output format so the
        // UI can display the original media resolution (e.g. 24-bit/96kHz) rather
        // than the internal pipeline container format (e.g. S32LE = 32-bit).
        if self.source_rate > 0 {
            parts.push(format!("source_rate={}", self.source_rate));
        }
        if self.source_depth > 0 {
            parts.push(format!("source_depth={}", self.source_depth));
        }
        if !parts.is_empty() {
            self.emit_event(EVT_TAG, &parts.join(";"));
        }
    }

    fn reset_spectrum_timeline(&mut self) {
        self.spectrum_pos_s = 0.0;
        self.spectrum_len = 0;
        self.spectrum_ring_write = 0;
        self.spectrum_ring_count = 0;
        self.spectrum_vals = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_ring_vals = [[0.0; SPECTRUM_BANDS_MAX]; SPECTRUM_RING_CAP];
        self.spectrum_ring_len = [0; SPECTRUM_RING_CAP];
        self.spectrum_ring_pos_s = [0.0; SPECTRUM_RING_CAP];
        self.spectrum_ring_seq = [0; SPECTRUM_RING_CAP];
    }

    fn set_spectrum_filter_enabled(&mut self, enabled: bool) {
        if enabled {
            if let Some(ref bin) = self._audio_filter_bin {
                let elem: gst::Element = bin.clone().upcast();
                self.playbin.set_property("audio-filter", &elem);
            }
        } else {
            self.playbin
                .set_property("audio-filter", Option::<gst::Element>::None);
            self.reset_spectrum_timeline();
        }
    }

    fn setup_spectrum_filter(playbin: &gst::Element) -> Option<gst::Bin> {
        let spectrum = gst::ElementFactory::make("spectrum")
            .name("rust-spectrum")
            .build()
            .ok()?;
        for p in spectrum.list_properties() {
            let pn = p.name();
            if pn == "bands" {
                // Match Python analyzer defaults for similar "liveliness".
                spectrum.set_property_from_str("bands", "64");
            } else if pn == "interval" {
                // Higher temporal density to reduce perceived frame drops.
                spectrum.set_property_from_str("interval", "16000000");
            }
        }
        let mut set_msg = false;
        for p in spectrum.list_properties() {
            let pn = p.name();
            if pn == "message" {
                let _ = spectrum.set_property("message", true);
                set_msg = true;
                break;
            }
            if pn == "post-messages" {
                let _ = spectrum.set_property("post-messages", true);
                set_msg = true;
                break;
            }
        }
        if !set_msg {
            return None;
        }
        let bin = gst::Bin::new();
        if bin.add(&spectrum).is_err() {
            return None;
        }
        let sink_pad = spectrum.static_pad("sink")?;
        let src_pad = spectrum.static_pad("src")?;
        let ghost_sink = gst::GhostPad::with_target(&sink_pad).ok()?;
        let ghost_src = gst::GhostPad::with_target(&src_pad).ok()?;
        if bin.add_pad(&ghost_sink).is_err() || bin.add_pad(&ghost_src).is_err() {
            return None;
        }
        playbin.set_property("audio-filter", &bin);
        Some(bin)
    }

    fn parse_spectrum_structure(&mut self, s: &gst::StructureRef, msg_ts_s: Option<f64>) {
        if !self.spectrum_enabled {
            return;
        }
        let sname = s.name().to_ascii_lowercase();
        if !sname.contains("spectrum") {
            return;
        }
        self.spectrum_seen_msgs = self.spectrum_seen_msgs.wrapping_add(1);
        let text = s.to_string();
        let lower = text.to_ascii_lowercase();
        let Some(kpos) = lower.find("magnitude") else {
            if self.spectrum_seen_msgs % 120 == 0 {
                self.emit_event(
                    EVT_STATE,
                    &format!(
                        "spectrum-msgs={} parsed={}",
                        self.spectrum_seen_msgs, self.spectrum_msg_count
                    ),
                );
            }
            return;
        };
        let rest = &text[kpos..];
        let mag_only = if let Some(open_pos) = rest.find('{').or_else(|| rest.find('<')) {
            let close_char = if rest.as_bytes().get(open_pos) == Some(&b'{') {
                '}'
            } else {
                '>'
            };
            if let Some(close_rel) = rest[(open_pos + 1)..].find(close_char) {
                &rest[(open_pos + 1)..(open_pos + 1 + close_rel)]
            } else {
                rest
            }
        } else {
            rest
        };
        let mut tmp = [0.0f32; SPECTRUM_BANDS_MAX];
        let mut n = 0usize;
        // Same numeric extraction contract as Python fallback parser:
        // extract only floats from magnitude payload.
        for part in mag_only
            .split(|c: char| !(c.is_ascii_digit() || matches!(c, '-' | '+' | '.' | 'e' | 'E')))
        {
            if n >= tmp.len() {
                break;
            }
            let t = part.trim();
            if t.is_empty() {
                continue;
            }
            if let Ok(v) = t.parse::<f32>() {
                if !v.is_finite() {
                    continue;
                }
                tmp[n] = v;
                n += 1;
            }
        }
        if n == 0 {
            if self.spectrum_seen_msgs % 120 == 0 {
                self.emit_event(
                    EVT_STATE,
                    &format!(
                        "spectrum-msgs={} parsed={}",
                        self.spectrum_seen_msgs, self.spectrum_msg_count
                    ),
                );
            }
            return;
        }
        // Prefer spectrum-structure carried timeline. Fallback to message ts, then
        // to pull-time query_position.
        let mut frame_pos_s = self.spectrum_pos_s;
        let mut ts_src = "last";
        if let Some((ts, src)) = Self::spectrum_time_from_structure(s) {
            frame_pos_s = ts;
            ts_src = src;
        } else if let Some(ts) = msg_ts_s {
            if ts.is_finite() && ts >= 0.0 {
                frame_pos_s = ts;
                ts_src = "msg-ts";
            }
        } else if let Some(pos) = self.playbin.query_position::<gst::ClockTime>() {
            frame_pos_s = (pos.nseconds() as f64) / 1_000_000_000.0;
            ts_src = "query-pos";
        }
        // New track / backward seek can leave a few stale spectrum messages in the
        // bus after the caller has already reset its local cursor. Drop the old
        // ring immediately so `get_spectrum_frames_since(0)` does not replay the
        // previous timeline on every recovery tick.
        if self.spectrum_len > 0 && frame_pos_s.is_finite() && frame_pos_s >= 0.0 {
            let prev_pos_s = self.spectrum_pos_s;
            if prev_pos_s.is_finite() && frame_pos_s < (prev_pos_s - 0.25) {
                self.reset_spectrum_timeline();
            }
        }
        self.spectrum_pos_s = frame_pos_s;

        self.spectrum_vals[..n].copy_from_slice(&tmp[..n]);
        self.spectrum_len = n;
        self.spectrum_seq = self.spectrum_seq.wrapping_add(1);
        let ridx = self.spectrum_ring_write;
        self.spectrum_ring_vals[ridx] = [0.0; SPECTRUM_BANDS_MAX];
        self.spectrum_ring_vals[ridx][..n].copy_from_slice(&tmp[..n]);
        self.spectrum_ring_len[ridx] = n as u16;
        self.spectrum_ring_pos_s[ridx] = frame_pos_s;
        self.spectrum_ring_seq[ridx] = self.spectrum_seq;
        self.spectrum_ring_write = (self.spectrum_ring_write + 1) % SPECTRUM_RING_CAP;
        self.spectrum_ring_count = (self.spectrum_ring_count + 1).min(SPECTRUM_RING_CAP);
        self.spectrum_msg_count = self.spectrum_msg_count.wrapping_add(1);
        if self.spectrum_msg_count % 120 == 0 {
            let q_s = self
                .playbin
                .query_position::<gst::ClockTime>()
                .map(|p| (p.nseconds() as f64) / 1_000_000_000.0)
                .unwrap_or(-1.0);
            self.emit_event(
                EVT_STATE,
                &format!(
                    "spectrum-ts src={} frame={:.3}s query={:.3}s delta={:.3}s",
                    ts_src,
                    frame_pos_s,
                    q_s,
                    if q_s >= 0.0 { q_s - frame_pos_s } else { -1.0 }
                ),
            );
        }
        if self.spectrum_msg_count % 120 == 0 {
            self.emit_event(
                EVT_STATE,
                &format!("spectrum-frames={}", self.spectrum_msg_count),
            );
        }
    }

    fn new() -> Result<Self, String> {
        GST_INIT.call_once(|| {
            let _ = gst::init();
        });

        let Some(playbin) = gst::ElementFactory::make("playbin")
            .name("rust-audio-player")
            .build()
            .ok()
        else {
            return Err("failed to create playbin".to_string());
        };

        // Test helper: bypass real audio device to make CI/sandbox verification deterministic.
        if env::var("HIRESTI_RUST_AUDIO_FAKE_SINK")
            .ok()
            .map(|v| matches!(v.as_str(), "1" | "true" | "yes" | "on"))
            .unwrap_or(false)
        {
            if let Some(fake) = gst::ElementFactory::make("fakesink")
                .name("rust-audio-fakesink")
                .build()
                .ok()
            {
                playbin.set_property("audio-sink", &fake);
            }
        }

        // Elevate GStreamer streaming thread (decode/demux) priority.
        //
        // GStreamer posts GST_MESSAGE_STREAM_STATUS with type Enter from within
        // the streaming thread just before it starts running.  A sync handler
        // is invoked in the posting thread's context, so `nice(-5)` applies to
        // the streaming thread that called gst_bus_post().  This does not
        // require elevated privileges (nice range [-20,19]; -5 is reachable by
        // any process within its default nice range of [0,19]).
        if let Some(bus) = playbin.bus() {
            bus.set_sync_handler(|_bus, msg| {
                if let gst::MessageView::StreamStatus(ss) = msg.view() {
                    if ss.get().0 == gst::StreamStatusType::Enter {
                        unsafe { libc::nice(-5) };
                    }
                }
                gst::BusSyncReply::Pass
            });
        }

        let filter_bin = Self::setup_spectrum_filter(&playbin);

        Ok(Self {
            playbin,
            _audio_filter_bin: filter_bin,
            uri: String::new(),
            last_error: None,
            event_cb: None,
            event_user_data: ptr::null_mut(),
            playback_rate: 1.0,
            pitch_semitones: 0.0,
            spectrum_seq: 0,
            spectrum_pos_s: 0.0,
            spectrum_vals: [0.0; SPECTRUM_BANDS_MAX],
            spectrum_len: 0,
            spectrum_ring_vals: [[0.0; SPECTRUM_BANDS_MAX]; SPECTRUM_RING_CAP],
            spectrum_ring_len: [0; SPECTRUM_RING_CAP],
            spectrum_ring_pos_s: [0.0; SPECTRUM_RING_CAP],
            spectrum_ring_seq: [0; SPECTRUM_RING_CAP],
            spectrum_ring_write: 0,
            spectrum_ring_count: 0,
            spectrum_seen_msgs: 0,
            spectrum_msg_count: 0,
            element_msg_seen: 0,
            fmt_probe_tick: 0,
            last_codec: String::new(),
            last_bitrate: 0,
            last_rate: 0,
            last_depth: 0,
            source_rate: 0,
            source_depth: 0,
            preferred_output_format: String::new(),
            spectrum_enabled: true,
            mmap_sink: None,
            output_mmap_realtime_priority: ALSA_MMAP_RT_PRIORITY_DEFAULT,
            output_driver: String::new(),
            output_device: None,
            output_buffer_us: 100_000,
            output_latency_us: 10_000,
            output_exclusive: false,
        })
    }

    fn set_error(&mut self, msg: impl Into<String>) {
        self.last_error = Some(msg.into());
    }

    fn output_driver_is_mmap(&self) -> bool {
        driver_is_alsa_mmap(&self.output_driver)
    }

    fn set_state(&mut self, state: gst::State) -> c_int {
        match self.playbin.set_state(state) {
            Ok(_) => {
                self.emit_event(EVT_STATE, &format!("{state:?}"));
                0
            }
            Err(e) => {
                self.set_error(format!("set_state failed: {e}"));
                self.emit_event(EVT_ERROR, &format!("set_state failed: {e}"));
                -4
            }
        }
    }

    fn emit_event(&self, evt: c_int, msg: &str) {
        if let Some(cb) = self.event_cb {
            if let Ok(cmsg) = CString::new(msg) {
                cb(evt, cmsg.as_ptr(), self.event_user_data);
            } else {
                cb(evt, ptr::null(), self.event_user_data);
            }
        }
    }

    fn drain_mmap_events(&mut self) {
        let Some(events) = self.mmap_sink.as_ref().map(|ms| ms.events.clone()) else {
            return;
        };
        let drained: Vec<(c_int, String)> = match events.lock() {
            Ok(mut pending) => pending.drain(..).collect(),
            Err(_) => return,
        };
        for (evt, msg) in drained {
            if evt == EVT_ERROR {
                self.set_error(msg.clone());
            }
            self.emit_event(evt, &msg);
        }
    }

    fn pump_events(&mut self) -> c_int {
        self.drain_mmap_events();
        let Some(bus) = self.playbin.bus() else {
            return 0;
        };
        let mut count = 0;
        let max_per_tick = 128;
        while let Some(msg) = bus.timed_pop(gst::ClockTime::from_mseconds(0)) {
            count += 1;
            match msg.view() {
                gst::MessageView::Eos(..) => {
                    self.emit_event(EVT_EOS, "eos");
                }
                gst::MessageView::Error(err) => {
                    let text = format!(
                        "{} ({:?})",
                        err.error(),
                        err.debug().unwrap_or_else(|| "no-debug".into())
                    );
                    self.set_error(text.clone());
                    self.emit_event(EVT_ERROR, &text);
                }
                gst::MessageView::StateChanged(sc) => {
                    // Keep only playbin state-change noise.
                    let is_self = msg
                        .src()
                        .map(|s| s.name() == self.playbin.name())
                        .unwrap_or(false);
                    if is_self {
                        self.emit_event(EVT_STATE, &format!("{:?}", sc.current()));
                    }
                }
                gst::MessageView::Element(elm) => {
                    if let Some(st) = elm.structure() {
                        self.element_msg_seen = self.element_msg_seen.wrapping_add(1);
                        if self.element_msg_seen <= 4 || self.element_msg_seen % 240 == 0 {
                            self.emit_event(EVT_STATE, &format!("elem-msg:{}", st.name()));
                        }
                        self.parse_spectrum_structure(st, None);
                    }
                }
                gst::MessageView::Tag(t) => {
                    let text = t.tags().to_string();
                    let codec = Self::parse_tag_text_value(&text, "audio-codec")
                        .or_else(|| Self::parse_tag_text_value(&text, "codec"));
                    let bitrate = Self::parse_tag_text_value(&text, "bitrate")
                        .and_then(|v| v.parse::<i32>().ok())
                        .filter(|v| *v > 0);
                    // Prefer extracting source format directly from full TAG payload.
                    let (tr, td) = Self::parse_source_rate_depth_from_codec_text(&text);
                    if let Some(v) = tr {
                        if v > 0 {
                            self.source_rate = v;
                        }
                    }
                    if let Some(v) = td {
                        if v > 0 {
                            self.source_depth = v;
                        }
                    }
                    if let Some(ref c) = codec {
                        let (sr, sd) = Self::parse_source_rate_depth_from_codec_text(c);
                        if let Some(v) = sr {
                            if v > 0 {
                                self.source_rate = v;
                            }
                        }
                        if let Some(v) = sd {
                            if v > 0 {
                                self.source_depth = v;
                            }
                        }
                    }
                    self.maybe_emit_tag_update(codec, bitrate, None, None);
                }
                _ => {}
            }
            if count >= max_per_tick {
                break;
            }
        }
        self.fmt_probe_tick = self.fmt_probe_tick.wrapping_add(1);
        if self.fmt_probe_tick % 10 == 0 {
            let (rate, depth) = self.query_output_format();
            self.maybe_emit_tag_update(None, None, rate, depth);
        }
        count
    }

    /// Stop the mmap writer thread (if running) and wait for it to exit.
    /// Must be called after playbin is set to NULL so the appsink sees EOS
    /// and the thread can unblock from pull-sample.
    fn stop_mmap_sink(&mut self) {
        if let Some(mut ms) = self.mmap_sink.take() {
            ms.stop.store(true, Ordering::Relaxed);
            if let Some(t) = ms.thread.take() {
                let _ = t.join();
            }
        }
    }

    /// Build an `appsink` element whose output is consumed by a background
    /// thread that writes to ALSA via mmap (zero kernel-copy path).
    ///
    /// Caps are fixed to `audio/x-raw, format=S32LE, layout=interleaved`
    /// (rate unconstrained — the thread opens ALSA with the actual source rate).
    /// GStreamer's internal `audioconvert` will handle format conversion upstream.
    ///
    /// Returns `(appsink_element, MmapSink)` on success.
    fn build_appsink_mmap(
        &self,
        device: Option<&str>,
        buffer_us: i32,
        latency_us: i32,
        preferred_output_format: &str,
        realtime_priority: i32,
    ) -> Result<(gst::Element, MmapSink), String> {
        let dev = device.unwrap_or("hw:0,0").to_string();
        let audio_format = mmap_audio_format_from_preference(preferred_output_format);

        let period_us = if latency_us > 0 { latency_us } else { 10_000 };
        let target_buffer_us = if buffer_us > 0 { buffer_us } else { 100_000 };
        let queue_buffers = if target_buffer_us <= 20_000 {
            4u32
        } else {
            8u32
        };
        let queue_time_ns =
            (u64::try_from(target_buffer_us.max(period_us * 2)).unwrap_or(20_000)) * 1_000;
        let accum_capacity_bytes = frames_for_duration_us(
            target_buffer_us.max(period_us * 2),
            ALSA_MMAP_ACCUM_RATE_BUDGET_HZ,
            64,
            192_000,
        )
        .saturating_mul(audio_format.frame_bytes)
        .saturating_mul((queue_buffers as usize).max(4))
        .saturating_mul(2)
        .clamp(256 * 1024, 2 * 1024 * 1024);

        // Build appsink — format is pinned so the mmap writer can copy frames
        // directly into the ALSA ring without an extra repack step.
        let appsink = gst::ElementFactory::make("appsink")
            .name("rust-mmap-appsink")
            .build()
            .map_err(|e| format!("appsink unavailable: {e}"))?;

        let caps = gst::Caps::builder("audio/x-raw")
            .field("format", audio_format.gst_format)
            .field("layout", "interleaved")
            .field("channels", 2i32)
            .build();
        appsink.set_property("caps", &caps);
        // The mmap writer thread already blocks on ALSA hardware pacing, so do
        // not add a second clock gate at appsink.
        appsink.set_property("sync", false);
        // Timed pull mode: the writer thread polls appsink directly so it can
        // react promptly to URI changes and shutdown.
        appsink.set_property("emit-signals", false);
        // Keep bounded headroom so short ALSA hiccups do not stall upstream
        // spectrum/filter production immediately.
        appsink.set_property("max-buffers", queue_buffers);
        appsink.set_property("max-time", queue_time_ns);
        appsink.set_property("drop", false);
        appsink.set_property("wait-on-eos", false);

        // Wrap appsink with audiobuffersplit so that large decoder buffers (e.g.
        // FLAC default block size of 4096 samples ≈ 93 ms at 44100 Hz) are split
        // into uniform ~16 ms chunks matching the spectrum element's interval.
        // Without this, spectrum messages arrive in batches separated by long gaps,
        // causing the waveform visualisation to appear over-smoothed.
        // Falls back to bare appsink when the plugin is not available.
        let sink_element: gst::Element = 'build_sink: {
            let Ok(splitter) = gst::ElementFactory::make("audiobuffersplit")
                .name("rust-mmap-bufsplit")
                .build()
            else {
                eprintln!("[alsa-mmap] audiobuffersplit unavailable; spectrum detail may be reduced");
                break 'build_sink appsink.clone();
            };
            // 16 ms matches the spectrum element's interval property.
            let _ = splitter.set_property_from_str("output-buffer-duration", "16/1000");
            let bin = gst::Bin::new();
            // add_many only fails if elements are already in another bin — safe to
            // fall back to bare appsink if so.
            if bin.add_many([&splitter, &appsink]).is_err() {
                eprintln!("[alsa-mmap] audiobuffersplit: bin.add_many failed");
                break 'build_sink appsink.clone();
            }
            // After add_many succeeds, appsink belongs to the bin; always return
            // the bin from this point to avoid orphaning the element.
            let _ = splitter.link(&appsink);
            if let Some(pad) = splitter.static_pad("sink") {
                if let Ok(ghost) = gst::GhostPad::with_target(&pad) {
                    let _ = bin.add_pad(&ghost);
                }
            }
            eprintln!("[alsa-mmap] using audiobuffersplit for uniform 16 ms buffers");
            bin.upcast::<gst::Element>()
        };

        let stop = Arc::new(AtomicBool::new(false));
        let stop_clone = stop.clone();
        let events: ThreadEventQueue = Arc::new(Mutex::new(VecDeque::new()));
        let events_clone = events.clone();
        let diagnostics: MmapThreadDiagnosticsHandle =
            Arc::new(Mutex::new(MmapThreadDiagnostics::default()));
        let diagnostics_clone = diagnostics.clone();
        let appsink_clone = appsink.clone();
        let dev_clone = dev.clone();

        let t = thread::spawn(move || {
            // Allocate the decoded PCM window before `mlockall(MCL_CURRENT)` so
            // the hot audio buffer is part of the pages we try to pin.
            let accum = AudioByteWindow::with_capacity(accum_capacity_bytes);
            update_mmap_thread_diagnostics(&diagnostics_clone, |state| {
                state.running = true;
            });
            configure_mmap_thread_runtime(&diagnostics_clone, &events_clone, realtime_priority);
            alsa_mmap_writer_thread(
                appsink_clone,
                dev_clone,
                period_us,
                target_buffer_us,
                accum,
                audio_format,
                stop_clone,
                events_clone,
                diagnostics_clone.clone(),
            );
            update_mmap_thread_diagnostics(&diagnostics_clone, |state| {
                state.running = false;
            });
        });

        Ok((
            sink_element,
            MmapSink {
                stop,
                events,
                diagnostics,
                thread: Some(t),
            },
        ))
    }

    fn set_output_tuned(
        &mut self,
        driver: &str,
        device: Option<&str>,
        buffer_us: i32,
        latency_us: i32,
        exclusive: bool,
    ) -> c_int {
        let cur_state = self.playbin.state(gst::ClockTime::from_mseconds(50)).1;
        let _ = self.playbin.set_state(gst::State::Null);
        // Stop any running mmap writer thread *after* set_state(Null) so the
        // appsink sees EOS and pull-sample unblocks cleanly.
        self.stop_mmap_sink();

        let driver_norm = normalized_driver_label(driver);
        self.set_spectrum_filter_enabled(true);
        self.emit_event(EVT_STATE, "spectrum-path=enabled");
        let original_device = device
            .map(|d| d.trim().to_string())
            .filter(|d| !d.is_empty());
        let mut resolved_device = original_device.clone();
        if driver_norm.contains("pipewire") {
            if let Some(device_id) = original_device.as_deref() {
                if let Some((card, profile)) = parse_pipewire_card_profile_target(device_id) {
                    match activate_pipewire_card_profile_target(&card, &profile) {
                        Ok(target_sink) => {
                            self.emit_event(
                                EVT_STATE,
                                &format!(
                                    "pipewire-card-profile resolved card={} profile={} sink={}",
                                    card, profile, target_sink
                                ),
                            );
                            resolved_device = Some(target_sink);
                        }
                        Err(e) => {
                            self.set_error(format!("pipewire profile activation failed: {e}"));
                            self.emit_event(
                                EVT_ERROR,
                                &format!("pipewire profile activation failed: {e}"),
                            );
                            return -16;
                        }
                    }
                }
            }
        }
        let device_norm = resolved_device.as_deref();

        let (sink, auto_caps_format) = if driver_norm.is_empty() || driver_norm.starts_with("auto")
        {
            (
                gst::ElementFactory::make("autoaudiosink")
                    .name("rust-auto-sink")
                    .build()
                    .ok(),
                None,
            )
        } else if driver_norm.contains("pipewire") {
            let s = gst::ElementFactory::make("pipewiresink")
                .name("rust-pw-sink")
                .build()
                .ok();
            match s {
                Some(ref elem) => {
                    if let Some(dev) = device_norm {
                        // Best effort: property presence varies by plugin/runtime.
                        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            elem.set_property("target-object", dev);
                        }));
                    }
                    let target_buffer_us = if buffer_us > 0 { buffer_us } else { 100_000 };
                    let base_quantum = ((target_buffer_us as f64 / 1_000_000.0) * 48_000.0) as i32;
                    let mut quantum = 1024i32;
                    for p in [256i32, 512, 1024, 2048, 4096, 8192] {
                        if (p - base_quantum).abs() < (quantum - base_quantum).abs() {
                            quantum = p;
                        }
                    }
                    quantum = quantum.clamp(512, 8192);
                    // Do not pin sample-rate in stream properties (e.g. ".../48000"),
                    // otherwise PipeWire may keep stream at 48k and defeat auto rate switching.
                    let latency_node = quantum.to_string();
                    // Keep autoconnect enabled even with explicit target-object.
                    // Some PipeWire/WirePlumber setups may not auto-link when this is false,
                    // resulting in "pipeline running + spectrum active but no audible output".
                    let auto_connect = "true";
                    let props = gst::Structure::builder("props")
                        .field("node.latency", &latency_node)
                        .field("node.autoconnect", &auto_connect)
                        .field("media.role", &"Music")
                        .field("resample.quality", &12i32)
                        .build();
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("stream-properties", &props);
                    }));
                    self.emit_event(
                        EVT_STATE,
                        &format!(
                            "pipewire-sink configured target={} autoconnect={} latency={}",
                            device_norm.unwrap_or("default"),
                            auto_connect,
                            latency_node
                        ),
                    );
                    (s, None)
                }
                None => {
                    self.set_error("pipewiresink unavailable");
                    self.emit_event(EVT_ERROR, "pipewiresink unavailable");
                    return -11;
                }
            }
        } else if driver_norm.contains("pulse") {
            let s = gst::ElementFactory::make("pulsesink")
                .name("rust-pa-sink")
                .build()
                .ok();
            match s {
                Some(ref elem) => {
                    if let Some(dev) = device_norm {
                        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            elem.set_property("device", dev);
                        }));
                    }
                    let target_buffer = if buffer_us > 0 { buffer_us } else { 100_000 };
                    let target_latency = if latency_us > 0 { latency_us } else { 10_000 };
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("buffer-time", i64::from(target_buffer));
                    }));
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("latency-time", i64::from(target_latency));
                    }));
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        elem.set_property("provide-clock", true);
                    }));
                    (s, None)
                }
                None => {
                    self.set_error("pulsesink unavailable");
                    self.emit_event(EVT_ERROR, "pulsesink unavailable");
                    return -12;
                }
            }
        } else if driver_is_alsa_mmap(driver) {
            // Zero-copy mmap path: appsink + background writer thread.
            // Caps wrapping is handled by setting caps on the appsink directly.
            match self.build_appsink_mmap(
                device_norm,
                buffer_us,
                latency_us,
                &self.preferred_output_format,
                self.output_mmap_realtime_priority,
            ) {
                Ok((elem, mmap)) => {
                    self.mmap_sink = Some(mmap);
                    let audio_format =
                        mmap_audio_format_from_preference(&self.preferred_output_format);
                    self.emit_event(
                        EVT_STATE,
                        &format!(
                            "alsa-mmap configured device={} format={}",
                            device_norm.unwrap_or("hw:0,0"),
                            audio_format.gst_format
                        ),
                    );
                    // Return None for auto_caps_format: caps are already set on
                    // the appsink element itself, so wrap_sink_with_caps must not
                    // be called (it would conflict with the element-level caps).
                    (Some(elem), None::<String>)
                }
                Err(e) => {
                    self.set_error(format!("alsa-mmap setup failed: {e}"));
                    self.emit_event(EVT_ERROR, &format!("alsa-mmap setup failed: {e}"));
                    return -17;
                }
            }
        } else if driver_norm.contains("alsa") {
            match build_alsa_sink_element(device_norm, buffer_us, latency_us, exclusive) {
                Ok((elem, forced_caps_format)) => (Some(elem), forced_caps_format),
                Err(-13) => {
                    self.set_error("alsasink unavailable");
                    self.emit_event(EVT_ERROR, "alsasink unavailable");
                    return -13;
                }
                Err(_) => {
                    self.set_error("failed to create ALSA sink bin");
                    self.emit_event(EVT_ERROR, "failed to create ALSA sink bin");
                    return -15;
                }
            }
        } else {
            self.set_error(format!("unsupported driver: {driver}"));
            self.emit_event(EVT_ERROR, &format!("unsupported driver: {driver}"));
            return -14;
        };

        let Some(sink_elem) = sink else {
            self.set_error("failed to create audio sink");
            self.emit_event(EVT_ERROR, "failed to create audio sink");
            return -15;
        };

        let preferred_caps_format = self.preferred_output_format.trim().to_string();
        // For alsa_mmap the appsink already has caps set on the element itself;
        // wrapping it inside an audioconvert+capsfilter bin would conflict.
        let is_mmap = driver_is_alsa_mmap(driver);
        let selected_caps_format = if is_mmap {
            None
        } else if !preferred_caps_format.is_empty() {
            Some(preferred_caps_format.as_str())
        } else {
            auto_caps_format.as_deref()
        };
        let final_sink = if let Some(fmt) = selected_caps_format {
            match wrap_sink_with_caps(sink_elem, fmt, "rust-output-convert", "rust-output-caps") {
                Ok(wrapped) => {
                    if preferred_caps_format.is_empty() {
                        self.emit_event(
                            EVT_STATE,
                            &format!(
                                "alsa-exclusive container-adapter format={} device={}",
                                fmt,
                                device_norm.unwrap_or("default")
                            ),
                        );
                    } else {
                        self.emit_event(
                            EVT_STATE,
                            &format!(
                                "output-format preference={} driver={} device={}",
                                fmt,
                                driver,
                                device_norm.unwrap_or("default")
                            ),
                        );
                    }
                    wrapped
                }
                Err(_) => {
                    self.set_error(format!("failed to apply output format {fmt}"));
                    self.emit_event(EVT_ERROR, &format!("failed to apply output format {fmt}"));
                    return -15;
                }
            }
        } else {
            sink_elem
        };

        self.output_driver = driver.to_string();
        self.output_device = resolved_device.clone();
        self.output_buffer_us = buffer_us;
        self.output_latency_us = latency_us;
        self.output_exclusive = exclusive;

        self.playbin.set_property("audio-sink", &final_sink);
        self.emit_event(
            EVT_STATE,
            &format!(
                "output-switched driver={driver} device={}",
                device_norm.unwrap_or("default")
            ),
        );

        // Restore runtime state.
        let target = if cur_state == gst::State::Playing {
            gst::State::Playing
        } else if cur_state == gst::State::Paused {
            gst::State::Paused
        } else {
            gst::State::Null
        };
        self.set_state(target)
    }

    fn set_output(&mut self, driver: &str, device: Option<&str>) -> c_int {
        self.set_output_tuned(driver, device, 100_000, 10_000, false)
    }

    fn set_mmap_realtime_priority(&mut self, priority: i32) -> c_int {
        self.output_mmap_realtime_priority = priority.max(0);
        0
    }

    fn apply_playback_rate(&mut self) -> c_int {
        // HiFi mode: do not alter transport rate in Rust path.
        self.emit_event(EVT_STATE, "playback-rate=1.000 (hifi-locked)");
        0
    }
}

fn read_running_alsa_hw_params() -> (Option<i32>, Option<i32>) {
    let mut out_rate: Option<i32> = None;
    let mut out_depth: Option<i32> = None;
    let Ok(cards) = std::fs::read_dir("/proc/asound") else {
        return (None, None);
    };
    for c in cards.flatten() {
        let card_name = c.file_name().to_string_lossy().to_string();
        if !card_name.starts_with("card") {
            continue;
        }
        let card_path = c.path();
        let Ok(pcms) = std::fs::read_dir(&card_path) else {
            continue;
        };
        for p in pcms.flatten() {
            let pcm_name = p.file_name().to_string_lossy().to_string();
            if !(pcm_name.starts_with("pcm") && pcm_name.contains('p')) {
                continue;
            }
            let pcm_path = p.path();
            let Ok(subs) = std::fs::read_dir(&pcm_path) else {
                continue;
            };
            for s in subs.flatten() {
                let sub_name = s.file_name().to_string_lossy().to_string();
                if !sub_name.starts_with("sub") {
                    continue;
                }
                let status_path = s.path().join("status");
                let hw_path = s.path().join("hw_params");
                let Ok(status_txt) = std::fs::read_to_string(&status_path) else {
                    continue;
                };
                if !status_txt.to_ascii_uppercase().contains("RUNNING") {
                    continue;
                }
                let Ok(hw_txt) = std::fs::read_to_string(&hw_path) else {
                    continue;
                };
                for ln in hw_txt.lines() {
                    let t = ln.trim();
                    if let Some(rest) = t.strip_prefix("format:") {
                        if let Some(d) = Engine::parse_depth_from_format(rest.trim()) {
                            out_depth = Some(d);
                        }
                    } else if let Some(rest) = t.strip_prefix("rate:") {
                        let tok = rest.trim().split_whitespace().next().unwrap_or("");
                        if let Ok(r) = tok.parse::<i32>() {
                            if r > 0 {
                                out_rate = Some(r);
                            }
                        }
                    }
                }
                if out_rate.is_some() || out_depth.is_some() {
                    return (out_rate, out_depth);
                }
            }
        }
    }
    (out_rate, out_depth)
}

#[no_mangle]
pub extern "C" fn rac_get_spectrum_frame(
    ptr: *const Engine,
    out_vals: *mut f32,
    max_len: c_int,
    out_len: *mut c_int,
    out_pos_s: *mut c_double,
    out_seq: *mut u64,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if out_vals.is_null() || out_len.is_null() || out_pos_s.is_null() || out_seq.is_null() {
        return -2;
    }
    let max_n = if max_len <= 0 {
        0usize
    } else {
        max_len as usize
    };
    let n = engine
        .spectrum_len
        .min(max_n)
        .min(engine.spectrum_vals.len());
    if n == 0 {
        unsafe {
            *out_len = 0;
            *out_pos_s = engine.spectrum_pos_s;
            *out_seq = engine.spectrum_seq;
        }
        return 0;
    }
    unsafe {
        ptr::copy_nonoverlapping(engine.spectrum_vals.as_ptr(), out_vals, n);
        *out_len = n as c_int;
        *out_pos_s = engine.spectrum_pos_s;
        *out_seq = engine.spectrum_seq;
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_get_spectrum_frames_since(
    ptr: *const Engine,
    since_seq: u64,
    out_vals: *mut f32,
    max_frames: c_int,
    max_bands: c_int,
    out_frames: *mut c_int,
    out_lens: *mut c_int,
    out_pos_s: *mut c_double,
    out_seq: *mut u64,
) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if out_vals.is_null()
        || out_frames.is_null()
        || out_lens.is_null()
        || out_pos_s.is_null()
        || out_seq.is_null()
    {
        return -2;
    }
    let max_f = if max_frames <= 0 {
        0usize
    } else {
        max_frames as usize
    };
    let max_b = if max_bands <= 0 {
        0usize
    } else {
        max_bands as usize
    };
    if max_f == 0 || max_b == 0 {
        unsafe {
            *out_frames = 0;
        }
        return 0;
    }

    let oldest = if engine.spectrum_ring_count < SPECTRUM_RING_CAP {
        0usize
    } else {
        engine.spectrum_ring_write
    };

    let mut written = 0usize;
    for j in 0..engine.spectrum_ring_count {
        let idx = (oldest + j) % SPECTRUM_RING_CAP;
        let seq = engine.spectrum_ring_seq[idx];
        if seq <= since_seq {
            continue;
        }
        if written >= max_f {
            break;
        }
        let len = (engine.spectrum_ring_len[idx] as usize)
            .min(max_b)
            .min(SPECTRUM_BANDS_MAX);
        let base = written * max_b;
        unsafe {
            ptr::copy_nonoverlapping(
                engine.spectrum_ring_vals[idx].as_ptr(),
                out_vals.add(base),
                len,
            );
            *out_lens.add(written) = len as c_int;
            *out_pos_s.add(written) = engine.spectrum_ring_pos_s[idx];
            *out_seq.add(written) = seq;
        }
        written += 1;
    }

    unsafe {
        *out_frames = written as c_int;
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_set_spectrum_enabled(ptr: *mut Engine, enabled: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.spectrum_enabled = enabled != 0;
    if !engine.spectrum_enabled {
        engine.spectrum_len = 0;
        engine.spectrum_ring_count = 0;
    }
    0
}

fn list_pulseaudio_sinks_detailed() -> Vec<(String, Option<String>, Option<u32>)> {
    fn str_opt_to_string(v: Option<std::borrow::Cow<'_, str>>) -> String {
        v.map(|x| x.into_owned()).unwrap_or_default()
    }

    let Ok((mut mainloop, context)) = pa_connect() else {
        return Vec::new();
    };

    let mut out: Vec<(String, Option<String>, Option<u32>)> = Vec::new();
    let shared: Rc<RefCell<Vec<(String, Option<String>, Option<u32>)>>> =
        Rc::new(RefCell::new(Vec::new()));
    let done = Rc::new(Cell::new(false));

    let shared_cb = Rc::clone(&shared);
    let done_cb = Rc::clone(&done);
    let mut op = context
        .introspect()
        .get_sink_info_list(move |res| match res {
            ListResult::Item(info) => {
                let dev = str_opt_to_string(info.name.as_ref().cloned());
                if dev.is_empty() || dev.ends_with(".monitor") {
                    return;
                }
                let desc = str_opt_to_string(info.description.as_ref().cloned());
                let name = if desc.is_empty() { dev.clone() } else { desc };
                shared_cb.borrow_mut().push((name, Some(dev), info.card));
            }
            ListResult::End | ListResult::Error => {
                done_cb.set(true);
            }
        });

    pa_wait_for_list(&mut mainloop, &context, &done, &mut op);
    out.extend(shared.borrow().iter().cloned());
    out
}

fn list_pulseaudio_sinks() -> Vec<(String, Option<String>)> {
    list_pulseaudio_sinks_detailed()
        .into_iter()
        .map(|(name, dev_id, _card)| (name, dev_id))
        .collect()
}

fn pulseaudio_alsa_card_index_from_sink_name(sink_name: &str) -> Option<String> {
    fn str_opt_to_string(v: Option<std::borrow::Cow<'_, str>>) -> String {
        v.map(|x| x.into_owned()).unwrap_or_default()
    }

    let Ok((mut mainloop, context)) = pa_connect() else {
        return None;
    };
    let target = sink_name.trim().to_string();
    if target.is_empty() {
        return None;
    }

    let found = Rc::new(RefCell::new(String::new()));
    let done = Rc::new(Cell::new(false));

    let found_cb = Rc::clone(&found);
    let done_cb = Rc::clone(&done);
    let mut op = context
        .introspect()
        .get_sink_info_list(move |res| match res {
            ListResult::Item(info) => {
                let name = str_opt_to_string(info.name.as_ref().cloned());
                if name != target {
                    return;
                }
                let alsa_card = info.proplist.get_str("alsa.card").unwrap_or_default();
                let alsa_card = alsa_card.trim();
                if !alsa_card.is_empty() {
                    *found_cb.borrow_mut() = alsa_card.to_string();
                }
            }
            ListResult::End | ListResult::Error => {
                done_cb.set(true);
            }
        });
    pa_wait_for_list(&mut mainloop, &context, &done, &mut op);
    let out = found.borrow().clone();
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn pulseaudio_alsa_card_index_from_card_name(card: &str) -> Option<String> {
    fn str_opt_to_string(v: Option<std::borrow::Cow<'_, str>>) -> String {
        v.map(|x| x.into_owned()).unwrap_or_default()
    }

    let Ok((mut mainloop, context)) = pa_connect() else {
        return None;
    };
    let target = card.trim().to_string();
    if target.is_empty() {
        return None;
    }

    let found = Rc::new(RefCell::new(String::new()));
    let done = Rc::new(Cell::new(false));

    let found_cb = Rc::clone(&found);
    let done_cb = Rc::clone(&done);
    let mut op = context
        .introspect()
        .get_card_info_list(move |res| match res {
            ListResult::Item(info) => {
                let name = str_opt_to_string(info.name.as_ref().cloned());
                if name != target {
                    return;
                }
                let alsa_card = info.proplist.get_str("alsa.card").unwrap_or_default();
                let alsa_card = alsa_card.trim();
                if !alsa_card.is_empty() {
                    *found_cb.borrow_mut() = alsa_card.to_string();
                }
            }
            ListResult::End | ListResult::Error => {
                done_cb.set(true);
            }
        });
    pa_wait_for_list(&mut mainloop, &context, &done, &mut op);
    let out = found.borrow().clone();
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn pa_connect() -> Result<(PaMainloop, PaContext), String> {
    let mut mainloop =
        PaMainloop::new().ok_or_else(|| "pulseaudio mainloop init failed".to_string())?;
    let mut context = PaContext::new(&mainloop, "hiresTI")
        .ok_or_else(|| "pulseaudio context init failed".to_string())?;
    context
        .connect(None, PaContextFlagSet::NOFLAGS, None)
        .map_err(|e| format!("pulseaudio connect failed: {e}"))?;
    loop {
        match context.get_state() {
            PaContextState::Ready => return Ok((mainloop, context)),
            PaContextState::Failed | PaContextState::Terminated => {
                return Err(format!(
                    "pulseaudio context state: {:?}",
                    context.get_state()
                ));
            }
            _ => {
                let _ = mainloop.iterate(false);
            }
        }
    }
}

fn pa_wait_for_list<T: ?Sized>(
    mainloop: &mut PaMainloop,
    context: &PaContext,
    done: &Rc<Cell<bool>>,
    op: &mut pulse::operation::Operation<T>,
) {
    while !done.get() {
        match context.get_state() {
            PaContextState::Failed | PaContextState::Terminated => break,
            _ => {}
        }
        if op.get_state() != PaOperationState::Running {
            break;
        }
        let _ = mainloop.iterate(false);
    }
}

fn list_pipewire_sinks() -> Vec<(String, Option<String>)> {
    Engine::ensure_pw_init();
    let result = (|| -> Result<Vec<(String, Option<String>)>, String> {
        let mainloop = PwMainLoop::new(None).map_err(|e| format!("pw mainloop: {e}"))?;
        let context = PwContext::new(&mainloop).map_err(|e| format!("pw context: {e}"))?;
        let core = context
            .connect(None)
            .map_err(|e| format!("pw connect: {e}"))?;
        let registry = core
            .get_registry()
            .map_err(|e| format!("pw registry: {e}"))?;

        let done = Rc::new(Cell::new(false));
        let sinks: Rc<RefCell<Vec<(String, Option<String>)>>> = Rc::new(RefCell::new(Vec::new()));

        let done_clone = done.clone();
        let loop_clone = mainloop.clone();
        let sinks_clone = sinks.clone();

        let _listener_reg = registry
            .add_listener_local()
            .global(move |global| {
                if global.type_ != ObjectType::Node {
                    return;
                }
                let Some(props) = global.props else {
                    return;
                };
                let media_class = props.get("media.class").unwrap_or("");
                // Only output sink nodes are valid target-object candidates.
                if !media_class.starts_with("Audio/Sink") {
                    return;
                }
                let node_name = props.get("node.name").unwrap_or("");
                // Skip monitor endpoints from sink list.
                if !node_name.is_empty() && node_name.contains(".monitor") {
                    return;
                }
                let object_serial = props.get("object.serial").unwrap_or("");
                let Some(target_id) = pipewire_target_id_from_props(node_name, object_serial)
                else {
                    return;
                };
                let name = pipewire_display_name_from_strings(
                    props
                        .get("node.description")
                        .or_else(|| props.get("device.description"))
                        .unwrap_or(""),
                    props.get("node.nick").unwrap_or(""),
                    props
                        .get("node.name")
                        .or_else(|| props.get("object.serial"))
                        .unwrap_or("Audio Sink"),
                );
                let dev_id = Some(target_id);
                sinks_clone.borrow_mut().push((name, dev_id));
            })
            .register();

        let pending = core.sync(0).map_err(|e| format!("pw sync: {e}"))?;
        let _listener_core = core
            .add_listener_local()
            .done(move |id, seq| {
                if id == pw::core::PW_ID_CORE && seq == pending {
                    done_clone.set(true);
                    loop_clone.quit();
                }
            })
            .register();

        while !done.get() {
            mainloop.run();
        }

        let mut out = sinks.borrow().clone();
        out.sort_by_key(|(n, dev)| {
            let hay = format!(
                "{} {}",
                n.to_ascii_uppercase(),
                dev.clone().unwrap_or_default().to_ascii_uppercase()
            );
            if hay.contains("USB") {
                0
            } else {
                1
            }
        });
        out.dedup_by(|a, b| a.1 == b.1 && a.0 == b.0);
        Ok(out)
    })();
    result.unwrap_or_default()
}

fn pipewire_target_id_from_props(node_name: &str, object_serial: &str) -> Option<String> {
    let node = node_name.trim();
    if !node.is_empty() {
        if node.contains(".monitor") {
            return None;
        }
        return Some(node.to_string());
    }
    let serial = object_serial.trim();
    if serial.is_empty() {
        return None;
    }
    Some(serial.to_string())
}

fn merge_output_device_lists(
    primary: Vec<(String, Option<String>)>,
    extras: Vec<(String, Option<String>)>,
) -> Vec<(String, Option<String>)> {
    let mut out: Vec<(String, Option<String>)> = Vec::new();
    let mut seen_ids: HashSet<String> = HashSet::new();
    let mut seen_names_without_id: HashSet<String> = HashSet::new();

    for (name, dev_id) in primary.into_iter().chain(extras.into_iter()) {
        let clean_name = name.trim().to_string();
        if clean_name.is_empty() {
            continue;
        }
        let clean_id = dev_id.and_then(|v| {
            let s = v.trim().to_string();
            if s.is_empty() {
                None
            } else {
                Some(s)
            }
        });
        if let Some(ref id) = clean_id {
            if !seen_ids.insert(id.clone()) {
                continue;
            }
        } else {
            let key = clean_name.to_ascii_uppercase();
            if !seen_names_without_id.insert(key) {
                continue;
            }
        }
        out.push((clean_name, clean_id));
    }

    out
}

fn pulseaudio_sink_card_indices() -> HashSet<u32> {
    list_pulseaudio_sinks_detailed()
        .into_iter()
        .filter_map(|(_name, _dev_id, card)| card)
        .collect()
}

fn pipewire_display_name_from_strings(description: &str, nick: &str, fallback: &str) -> String {
    fn normalize_ws(text: &str) -> String {
        text.split_whitespace().collect::<Vec<_>>().join(" ")
    }

    fn is_generic_pipewire_name(text: &str) -> bool {
        let clean = normalize_ws(text);
        if clean.is_empty() {
            return true;
        }
        let lower = clean.to_ascii_lowercase();
        if lower == "analog stereo" || lower == "digital stereo" {
            return true;
        }
        if lower == "built-in audio" || lower == "built-in pro audio" || lower == "built-in audio pro" {
            return true;
        }
        if let Some(rest) = lower.strip_prefix("built-in audio pro ") {
            return !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit());
        }
        false
    }

    fn profile_label_from_node_name(node_name: &str) -> Option<String> {
        let node = node_name.trim();
        if !node.starts_with("alsa_output.") {
            return None;
        }
        let (_base, profile) = node["alsa_output.".len()..].rsplit_once('.')?;
        let label = match profile {
            "analog-stereo" => "Analog",
            "iec958-stereo" => "Digital",
            "hdmi-stereo" => "HDMI 0",
            p if p.starts_with("hdmi-stereo-extra") => {
                let idx = p["hdmi-stereo-extra".len()..].trim();
                if idx.is_empty() || !idx.chars().all(|c| c.is_ascii_digit()) {
                    return None;
                }
                return Some(format!("HDMI {idx}"));
            }
            p if p.starts_with("pro-output-") => {
                let idx = p["pro-output-".len()..].trim();
                if idx == "0" {
                    "Analog"
                } else if !idx.is_empty() && idx.chars().all(|c| c.is_ascii_digit()) {
                    return Some(format!("Output {idx}"));
                } else {
                    return None;
                }
            }
            _ => return None,
        };
        Some(label.to_string())
    }

    fn card_label_from_node_name(node_name: &str) -> Option<String> {
        let node = node_name.trim();
        let Some(rest) = node.strip_prefix("alsa_output.") else {
            return None;
        };
        let (base, _profile) = rest.rsplit_once('.')?;
        let usb = base.strip_prefix("usb-")?;
        // Strip only the trailing USB bus index "-NN" (last hyphen + all-digit suffix).
        let usb = if let Some(pos) = usb.rfind('-') {
            let suffix = &usb[pos + 1..];
            if !suffix.is_empty() && suffix.chars().all(|c: char| c.is_ascii_digit()) {
                &usb[..pos]
            } else {
                usb
            }
        } else {
            usb
        };
        if usb.is_empty() {
            return None;
        }
        let spaced = usb.replace(['_', '.'], " ");
        let clean = normalize_ws(&spaced);
        if clean.is_empty() {
            return None;
        }
        if let Some(prefix) = clean.strip_suffix(" USB Audio") {
            let prefix = prefix.trim();
            if !prefix.is_empty() {
                return Some(format!("{prefix} / USB Audio"));
            }
        }
        Some(clean)
    }

    let desc = normalize_ws(description.trim());
    let nick = normalize_ws(nick.trim());
    let fallback = fallback.trim();
    let fallback_card = card_label_from_node_name(fallback);
    let fallback_profile = profile_label_from_node_name(fallback);

    if let Some(card) = fallback_card.as_ref() {
        if desc.to_ascii_lowercase().ends_with("analog stereo") || is_generic_pipewire_name(&desc) {
            // Prefer nick when it carries the real model name (e.g. "Monitor 09"),
            // rather than returning a fallback derived from the node path.
            if desc.to_ascii_lowercase().ends_with("analog stereo")
                && !nick.is_empty()
                && !is_generic_pipewire_name(&nick)
            {
                return nick.clone();
            }
            return card.clone();
        }
    }

    if !desc.is_empty() && !nick.is_empty() {
        if desc.eq_ignore_ascii_case(&nick) {
            if is_generic_pipewire_name(&desc) {
                if let Some(card) = fallback_card {
                    return card;
                }
                if let Some(profile) = fallback_profile {
                    return format!("Built-in Audio / {profile}");
                }
            }
            return desc;
        }
        if is_generic_pipewire_name(&desc) && !is_generic_pipewire_name(&nick) {
            let base = fallback_card.unwrap_or_else(|| "Built-in Audio".to_string());
            return format!("{base} / {nick}");
        }
        return format!("{desc} / {nick}");
    }
    if !desc.is_empty() {
        if is_generic_pipewire_name(&desc) {
            if let Some(card) = fallback_card {
                return card;
            }
            if let Some(profile) = fallback_profile {
                return format!("Built-in Audio / {profile}");
            }
        }
        return desc;
    }
    if !nick.is_empty() {
        if let Some(card) = fallback_card {
            if !is_generic_pipewire_name(&nick) {
                return format!("{card} / {nick}");
            }
            return card;
        }
        return nick;
    }
    if let Some(card) = fallback_card {
        return card;
    }
    if let Some(profile) = fallback_profile {
        return format!("Built-in Audio / {profile}");
    }
    fallback.to_string()
}

fn choose_pipewire_output_profile_from_entries(
    active_profile: Option<&str>,
    profiles: &[(String, u32, u32, bool)],
) -> Option<String> {
    if let Some(active) = active_profile {
        let active_trim = active.trim();
        if !active_trim.is_empty()
            && profiles
                .iter()
                .any(|(name, sinks, _priority, _available)| *sinks > 0 && name == active_trim)
        {
            return Some(active_trim.to_string());
        }
    }

    let mut best_available: Option<(String, u32)> = None;
    let mut best_any: Option<(String, u32)> = None;
    for (name, sinks, priority, available) in profiles {
        let profile_name = name.trim();
        if *sinks == 0 || profile_name.is_empty() {
            continue;
        }
        if *available {
            let replace = best_available
                .as_ref()
                .map(|(_, prio)| *prio < *priority)
                .unwrap_or(true);
            if replace {
                best_available = Some((profile_name.to_string(), *priority));
            }
        }
        let replace_any = best_any
            .as_ref()
            .map(|(_, prio)| *prio < *priority)
            .unwrap_or(true);
        if replace_any {
            best_any = Some((profile_name.to_string(), *priority));
        }
    }

    best_available.or(best_any).map(|(name, _)| name)
}

fn list_pipewire_card_fallbacks() -> Vec<(String, Option<String>)> {
    let active_cards = pulseaudio_sink_card_indices();
    let Ok((mut mainloop, context)) = pa_connect() else {
        return Vec::new();
    };

    let shared: Rc<RefCell<Vec<(String, Option<String>)>>> = Rc::new(RefCell::new(Vec::new()));
    let done = Rc::new(Cell::new(false));

    let shared_cb = Rc::clone(&shared);
    let done_cb = Rc::clone(&done);
    let mut op = context
        .introspect()
        .get_card_info_list(move |res| match res {
            ListResult::Item(info) => {
                if active_cards.contains(&info.index) {
                    return;
                }
                let card_name = info
                    .name
                    .as_ref()
                    .map(|v| v.to_string())
                    .unwrap_or_default();
                if card_name.trim().is_empty() {
                    return;
                }
                let active_profile = info
                    .active_profile
                    .as_ref()
                    .and_then(|p| p.name.as_ref().map(|v| v.to_string()));
                let profiles: Vec<(String, u32, u32, bool)> = info
                    .profiles
                    .iter()
                    .filter_map(|p| {
                        let name = p.name.as_ref()?.to_string();
                        Some((name, p.n_sinks, p.priority, p.available))
                    })
                    .collect();
                let Some(profile_name) = choose_pipewire_output_profile_from_entries(
                    active_profile.as_deref(),
                    &profiles,
                ) else {
                    return;
                };
                let label = pipewire_display_name_from_strings(
                    &info
                        .proplist
                        .get_str(pa_props::DEVICE_DESCRIPTION)
                        .unwrap_or_default(),
                    &info.proplist.get_str("device.nick").unwrap_or_default(),
                    &card_name,
                );
                if label.trim().is_empty() {
                    return;
                }
                shared_cb.borrow_mut().push((
                    label,
                    Some(build_pipewire_card_profile_target(
                        &card_name,
                        &profile_name,
                    )),
                ));
            }
            ListResult::End | ListResult::Error => {
                done_cb.set(true);
            }
        });

    pa_wait_for_list(&mut mainloop, &context, &done, &mut op);
    let mut out = shared.borrow().clone();
    out.sort_by_key(|(name, dev)| {
        let hay = format!(
            "{} {}",
            name.to_ascii_uppercase(),
            dev.clone().unwrap_or_default().to_ascii_uppercase()
        );
        (
            if hay.contains("USB") { 0 } else { 1 },
            name.to_ascii_uppercase(),
            dev.clone().unwrap_or_default(),
        )
    });
    out.dedup_by(|a, b| a.1 == b.1);
    out
}

fn pulseaudio_card_index(card: &str) -> Option<u32> {
    let Ok((mut mainloop, context)) = pa_connect() else {
        return None;
    };
    let target = card.trim().to_string();
    if target.is_empty() {
        return None;
    }

    let found = Rc::new(Cell::new(u32::MAX));
    let done = Rc::new(Cell::new(false));

    let found_cb = Rc::clone(&found);
    let done_cb = Rc::clone(&done);
    let mut op = context
        .introspect()
        .get_card_info_list(move |res| match res {
            ListResult::Item(info) => {
                let name = info
                    .name
                    .as_ref()
                    .map(|v| v.to_string())
                    .unwrap_or_default();
                if name == target {
                    found_cb.set(info.index);
                }
            }
            ListResult::End | ListResult::Error => {
                done_cb.set(true);
            }
        });
    pa_wait_for_list(&mut mainloop, &context, &done, &mut op);
    match found.get() {
        u32::MAX => None,
        idx => Some(idx),
    }
}

fn pulseaudio_resolve_sink_name_for_card(
    card: &str,
    prefer_profile: Option<&str>,
) -> Option<String> {
    let card_index = pulseaudio_card_index(card)?;
    let Ok((mut mainloop, context)) = pa_connect() else {
        return None;
    };
    let preferred = prefer_profile.unwrap_or("").trim().to_string();
    let matches: Rc<RefCell<Vec<(u8, String)>>> = Rc::new(RefCell::new(Vec::new()));
    let done = Rc::new(Cell::new(false));

    let matches_cb = Rc::clone(&matches);
    let done_cb = Rc::clone(&done);
    let mut op = context
        .introspect()
        .get_sink_info_list(move |res| match res {
            ListResult::Item(info) => {
                if info.card != Some(card_index) {
                    return;
                }
                let sink_name = info
                    .name
                    .as_ref()
                    .map(|v| v.to_string())
                    .unwrap_or_default();
                if sink_name.trim().is_empty() || sink_name.ends_with(".monitor") {
                    return;
                }
                let sink_profile = info
                    .proplist
                    .get_str(pa_props::DEVICE_PROFILE_NAME)
                    .unwrap_or_default();
                let score = if !preferred.is_empty() && sink_profile == preferred {
                    2
                } else if preferred.is_empty() || sink_profile.is_empty() {
                    1
                } else {
                    0
                };
                matches_cb.borrow_mut().push((score, sink_name));
            }
            ListResult::End | ListResult::Error => {
                done_cb.set(true);
            }
        });
    pa_wait_for_list(&mut mainloop, &context, &done, &mut op);
    let mut found = matches.borrow().clone();
    found.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    found.into_iter().next().map(|(_, sink_name)| sink_name)
}

fn activate_pipewire_card_profile_target(card: &str, profile: &str) -> Result<String, String> {
    let card_name = card.trim();
    let profile_name = profile.trim();
    if card_name.is_empty() || profile_name.is_empty() {
        return Err("invalid PipeWire card/profile target".to_string());
    }

    let active = pulseaudio_card_active_profile(card_name).unwrap_or_default();
    if active != profile_name {
        pulseaudio_set_card_profile(card_name, profile_name)?;
        thread::sleep(Duration::from_millis(120));
    }

    for _attempt in 0..8 {
        if let Some(sink_name) =
            pulseaudio_resolve_sink_name_for_card(card_name, Some(profile_name))
        {
            return Ok(sink_name);
        }
        thread::sleep(Duration::from_millis(80));
    }

    Err(format!(
        "no sink node became available for card={} profile={}",
        card_name, profile_name
    ))
}

fn parse_alsa_card_labels(content: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for raw in content.lines() {
        let line = raw.trim_start();
        if line.is_empty() {
            continue;
        }
        let first = line.split_whitespace().next().unwrap_or("");
        if !first.chars().all(|c| c.is_ascii_digit()) {
            continue;
        }
        let idx = first.to_string();
        let dash_pos = match line.rfind(" - ") {
            Some(v) => v,
            None => continue,
        };
        let label = line[(dash_pos + 3)..].trim();
        if label.is_empty() {
            continue;
        }
        out.insert(idx, label.to_string());
    }
    out
}

fn parse_alsa_playback_pcm_index(entry_name: &str) -> Option<String> {
    if !(entry_name.starts_with("pcm") && entry_name.ends_with('p')) {
        return None;
    }
    let middle = &entry_name[3..(entry_name.len() - 1)];
    if middle.is_empty() || !middle.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some(middle.to_string())
}

fn parse_alsa_hw_device_id(device_id: &str) -> Option<(String, Option<String>)> {
    let trimmed = device_id.trim();
    let rest = trimmed.strip_prefix("hw:")?;
    let mut parts = rest.split(',');
    let card_idx = parts.next()?.trim();
    if card_idx.is_empty() || !card_idx.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let pcm_idx = parts
        .next()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty() && v.chars().all(|c| c.is_ascii_digit()));
    Some((card_idx.to_string(), pcm_idx))
}

fn parse_alsa_playback_formats_from_stream_text(content: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut in_playback = false;
    for raw in content.lines() {
        let line = raw.trim();
        if line.eq_ignore_ascii_case("Playback:") {
            in_playback = true;
            continue;
        }
        if line.eq_ignore_ascii_case("Capture:") {
            in_playback = false;
            continue;
        }
        if !in_playback {
            continue;
        }
        if let Some(rest) = line.strip_prefix("Format:") {
            let fmt = rest.trim().to_ascii_uppercase();
            if !fmt.is_empty() {
                out.push(fmt);
            }
        }
    }
    out.sort();
    out.dedup();
    out
}

fn read_alsa_card_playback_formats_from_proc_root(proc_root: &Path, card_idx: &str) -> Vec<String> {
    let mut out = Vec::new();
    let card_path = proc_root.join(format!("card{card_idx}"));
    let Ok(entries) = std::fs::read_dir(card_path) else {
        return out;
    };
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_string();
        if !(name.starts_with("stream") && name[6..].chars().all(|c| c.is_ascii_digit())) {
            continue;
        }
        let Ok(content) = std::fs::read_to_string(entry.path()) else {
            continue;
        };
        out.extend(parse_alsa_playback_formats_from_stream_text(&content));
    }
    out.sort();
    out.dedup();
    out
}

fn normalize_alsa_caps_container_format(playback_format: &str) -> Option<&'static str> {
    match playback_format.trim().to_ascii_uppercase().as_str() {
        "S32_LE" => Some("S32LE"),
        "S24_32_LE" => Some("S24_32LE"),
        _ => None,
    }
}

fn detect_alsa_exclusive_caps_format_from_proc_root(
    proc_root: &Path,
    device_id: &str,
) -> Option<String> {
    let (card_idx, _pcm_idx) = parse_alsa_hw_device_id(device_id)?;
    let formats = read_alsa_card_playback_formats_from_proc_root(proc_root, &card_idx);
    if formats.is_empty() {
        return None;
    }
    let mut forced: Option<&'static str> = None;
    for fmt in formats {
        let normalized = normalize_alsa_caps_container_format(&fmt)?;
        match forced {
            Some(cur) if cur != normalized => return None,
            Some(_) => {}
            None => forced = Some(normalized),
        }
    }
    forced.map(str::to_string)
}

fn gst_output_format_from_playback_format(playback_format: &str) -> Option<&'static str> {
    match playback_format.trim().to_ascii_uppercase().as_str() {
        "S16_LE" | "S16LE" => Some("S16LE"),
        "S24_LE" | "S24LE" | "S24_3LE" => Some("S24LE"),
        "S24_32_LE" | "S24_32LE" => Some("S24_32LE"),
        "S32_LE" | "S32LE" => Some("S32LE"),
        _ => None,
    }
}

fn supported_output_formats_from_playback_formats(formats: &[String]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for fmt in formats {
        let Some(mapped) = gst_output_format_from_playback_format(fmt) else {
            continue;
        };
        if !out.iter().any(|v| v == mapped) {
            out.push(mapped.to_string());
        }
    }
    out
}

fn supported_output_depths_from_formats(formats: &[String]) -> Vec<i32> {
    let mut out: Vec<i32> = Vec::new();
    for fmt in formats {
        let Some(depth) = Engine::parse_depth_from_format(fmt) else {
            continue;
        };
        if !out.iter().any(|v| *v == depth) {
            out.push(depth);
        }
    }
    out.sort_unstable();
    out
}

fn wrap_sink_with_caps(
    sink_elem: gst::Element,
    format_name: &str,
    convert_name: &str,
    caps_name: &str,
) -> Result<gst::Element, c_int> {
    let convert = gst::ElementFactory::make("audioconvert")
        .name(convert_name)
        .build()
        .map_err(|_| -15)?;
    let capsfilter = gst::ElementFactory::make("capsfilter")
        .name(caps_name)
        .build()
        .map_err(|_| -15)?;
    let caps = gst::Caps::builder("audio/x-raw")
        .field("format", format_name)
        .field("layout", "interleaved")
        .build();
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        capsfilter.set_property("caps", &caps);
    }));

    let bin = gst::Bin::new();
    if bin.add(&convert).is_err() || bin.add(&capsfilter).is_err() || bin.add(&sink_elem).is_err() {
        return Err(-15);
    }
    if convert.link(&capsfilter).is_err() || capsfilter.link(&sink_elem).is_err() {
        return Err(-15);
    }
    let sink_pad = convert.static_pad("sink").ok_or(-15)?;
    let ghost_sink = gst::GhostPad::with_target(&sink_pad).map_err(|_| -15)?;
    if bin.add_pad(&ghost_sink).is_err() {
        return Err(-15);
    }
    Ok(bin.upcast::<gst::Element>())
}

fn read_alsa_pcm_label(info_path: &Path) -> Option<String> {
    let Ok(content) = std::fs::read_to_string(info_path) else {
        return None;
    };
    for raw in content.lines() {
        let line = raw.trim();
        if let Some(rest) = line.strip_prefix("name:") {
            let label = rest.trim();
            if !label.is_empty() {
                return Some(label.to_string());
            }
        }
    }
    None
}

fn format_alsa_playback_label(
    card_label: &str,
    card_idx: &str,
    pcm_idx: &str,
    pcm_label: Option<&str>,
) -> String {
    match pcm_label.map(|v| v.trim()).filter(|v| !v.is_empty()) {
        Some(label) if !label.eq_ignore_ascii_case(card_label) => {
            format!("{card_label} / {label} (hw:{card_idx},{pcm_idx})")
        }
        _ => format!("{card_label} (PCM {pcm_idx}, Card {card_idx})"),
    }
}

fn list_alsa_cards_from_proc_root(proc_root: &Path) -> Vec<(String, Option<String>)> {
    let card_labels = std::fs::read_to_string(proc_root.join("cards"))
        .ok()
        .map(|v| parse_alsa_card_labels(&v))
        .unwrap_or_default();
    let mut out: Vec<(String, Option<String>)> = Vec::new();
    let Ok(entries) = std::fs::read_dir(proc_root) else {
        return out;
    };
    for entry in entries.flatten() {
        let entry_name = entry.file_name().to_string_lossy().to_string();
        let Some(card_idx) = entry_name
            .strip_prefix("card")
            .filter(|v| !v.is_empty() && v.chars().all(|c| c.is_ascii_digit()))
        else {
            continue;
        };
        let card_idx = card_idx.to_string();
        let card_label = card_labels
            .get(&card_idx)
            .cloned()
            .unwrap_or_else(|| format!("ALSA Card {card_idx}"));
        let mut saw_playback_pcm = false;
        let Ok(pcms) = std::fs::read_dir(entry.path()) else {
            continue;
        };
        for pcm in pcms.flatten() {
            let pcm_entry = pcm.file_name().to_string_lossy().to_string();
            let Some(pcm_idx) = parse_alsa_playback_pcm_index(&pcm_entry) else {
                continue;
            };
            let pcm_info_path = pcm.path().join("info");
            let pcm_label = read_alsa_pcm_label(&pcm_info_path);
            let friendly =
                format_alsa_playback_label(&card_label, &card_idx, &pcm_idx, pcm_label.as_deref());
            let hw_id = format!("hw:{card_idx},{pcm_idx}");
            out.push((friendly, Some(hw_id)));
            saw_playback_pcm = true;
        }
        if !saw_playback_pcm {
            let friendly = format!("{card_label} (Card {card_idx})");
            let hw_id = format!("hw:{card_idx},0");
            out.push((friendly, Some(hw_id)));
        }
    }
    if out.is_empty() {
        for (idx, label) in card_labels {
            let friendly = format!("{label} (Card {idx})");
            let hw_id = format!("hw:{idx},0");
            out.push((friendly, Some(hw_id)));
        }
    }
    out.sort_by_key(|(name, dev)| {
        let hay = format!(
            "{} {}",
            name.to_ascii_uppercase(),
            dev.clone().unwrap_or_default().to_ascii_uppercase()
        );
        (
            if hay.contains("USB") { 0 } else { 1 },
            name.to_ascii_uppercase(),
            dev.clone().unwrap_or_default(),
        )
    });
    out.dedup_by(|a, b| a.1 == b.1);
    out
}

fn list_alsa_cards() -> Vec<(String, Option<String>)> {
    list_alsa_cards_from_proc_root(Path::new("/proc/asound"))
}

fn build_alsa_sink_element(
    device: Option<&str>,
    buffer_us: i32,
    latency_us: i32,
    exclusive: bool,
) -> Result<(gst::Element, Option<String>), c_int> {
    let alsa_sink = gst::ElementFactory::make("alsasink")
        .name("rust-alsa-sink")
        .build()
        .map_err(|_| -13)?;

    if let Some(dev) = device {
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            alsa_sink.set_property("device", dev);
        }));
    }
    let target_buffer = if buffer_us > 0 { buffer_us } else { 100_000 };
    let target_latency = if latency_us > 0 { latency_us } else { 10_000 };
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        alsa_sink.set_property("buffer-time", i64::from(target_buffer));
    }));
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        alsa_sink.set_property("latency-time", i64::from(target_latency));
    }));
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        alsa_sink.set_property("provide-clock", true);
    }));
    if exclusive {
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            // `slave-method` is an enum property on GstAlsaSink.
            // Setting it as integer can panic in Rust bindings
            // (type mismatch). Use enum nick string instead.
            if alsa_sink.find_property("slave-method").is_some() {
                alsa_sink.set_property_from_str("slave-method", "none");
            }
        }));
    }

    let forced_caps_format = if exclusive {
        device.and_then(|dev| {
            detect_alsa_exclusive_caps_format_from_proc_root(Path::new("/proc/asound"), dev)
        })
    } else {
        None
    };
    Ok((alsa_sink, forced_caps_format))
}

fn devices_for_driver(driver: &str) -> Vec<(String, Option<String>)> {
    let d = normalized_driver_label(driver);
    if d == "auto(default)" || d == "auto" {
        return vec![("Default Output".to_string(), None)];
    }
    if d == "pipewire" {
        let mut out = vec![("Default System Output".to_string(), None)];
        // Merge raw PipeWire sink nodes with the PulseAudio-compat compatibility
        // view. Some WirePlumber/PipeWire setups expose a fuller sink list via the
        // pulse server even though the selectable target remains the same node name.
        let merged = merge_output_device_lists(
            merge_output_device_lists(list_pipewire_sinks(), list_pulseaudio_sinks()),
            list_pipewire_card_fallbacks(),
        );
        out.extend(merged);
        return out;
    }
    if d == "pulseaudio" {
        let mut out = vec![("Default System Output".to_string(), None)];
        out.extend(list_pulseaudio_sinks());
        return out;
    }
    if driver_is_alsa_family(driver) {
        return list_alsa_cards();
    }
    Vec::new()
}

fn card_from_pipewire_output_node(device_id: &str) -> Option<String> {
    let dev = device_id.trim();
    if !dev.starts_with("alsa_output.") {
        return None;
    }
    let mut core = dev["alsa_output.".len()..].to_string();
    let suffixes = [
        ".analog-stereo",
        ".multichannel-output",
        ".iec958-stereo",
    ];
    for sx in suffixes {
        if core.ends_with(sx) {
            let len = core.len() - sx.len();
            core.truncate(len);
            break;
        }
    }
    // Strip .pro-output-N or .pro-output-N.M (e.g. .pro-output-0.2)
    if let Some(pos) = core.rfind(".pro-output-") {
        let rest = &core[pos + ".pro-output-".len()..];
        let valid = !rest.is_empty()
            && rest
                .split('.')
                .all(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()));
        if valid {
            core.truncate(pos);
        }
    }
    if core.is_empty() {
        return None;
    }
    Some(format!("alsa_card.{core}"))
}

fn supported_output_formats_for_driver_device(
    driver: &str,
    device_id: Option<&str>,
) -> Vec<String> {
    let drv = normalized_driver_label(driver);
    let dev = device_id.unwrap_or("").trim();
    if dev.is_empty() {
        return Vec::new();
    }

    let alsa_card_idx = if driver_is_alsa_family(driver) {
        parse_alsa_hw_device_id(dev).map(|(card_idx, _)| card_idx)
    } else if drv == "pipewire" {
        parse_pipewire_card_profile_target(dev)
            .and_then(|(card, _)| pulseaudio_alsa_card_index_from_card_name(&card))
            .or_else(|| {
                card_from_pipewire_output_node(dev)
                    .and_then(|card| pulseaudio_alsa_card_index_from_card_name(&card))
            })
            .or_else(|| pulseaudio_alsa_card_index_from_sink_name(dev))
    } else if drv == "pulseaudio" {
        pulseaudio_alsa_card_index_from_sink_name(dev)
    } else {
        None
    };

    let Some(card_idx) = alsa_card_idx else {
        return Vec::new();
    };
    let playback_formats =
        read_alsa_card_playback_formats_from_proc_root(Path::new("/proc/asound"), &card_idx);
    supported_output_formats_from_playback_formats(&playback_formats)
}

fn pulseaudio_card_active_profile(card: &str) -> Option<String> {
    fn str_opt_to_string(v: Option<std::borrow::Cow<'_, str>>) -> String {
        v.map(|x| x.into_owned()).unwrap_or_default()
    }

    let Ok((mut mainloop, context)) = pa_connect() else {
        return None;
    };

    let target = card.trim().to_string();
    if target.is_empty() {
        return None;
    }

    let found = Rc::new(RefCell::new(None::<String>));
    let done = Rc::new(Cell::new(false));

    let found_cb = Rc::clone(&found);
    let done_cb = Rc::clone(&done);
    let mut op = context
        .introspect()
        .get_card_info_list(move |res| match res {
            ListResult::Item(info) => {
                let name = str_opt_to_string(info.name.as_ref().cloned());
                if name != target {
                    return;
                }
                let profile = info
                    .active_profile
                    .as_ref()
                    .map(|p| str_opt_to_string(p.name.as_ref().cloned()))
                    .unwrap_or_default();
                if !profile.is_empty() {
                    *found_cb.borrow_mut() = Some(profile);
                }
            }
            ListResult::End | ListResult::Error => {
                done_cb.set(true);
            }
        });
    pa_wait_for_list(&mut mainloop, &context, &done, &mut op);
    let result = found.borrow().clone();
    result
}

fn pulseaudio_set_card_profile(card: &str, profile: &str) -> Result<(), String> {
    let (mut mainloop, context) = pa_connect()?;
    let done = Rc::new(Cell::new(false));
    let ok = Rc::new(Cell::new(false));

    let done_cb = Rc::clone(&done);
    let ok_cb = Rc::clone(&ok);
    let op = context.introspect().set_card_profile_by_name(
        card,
        profile,
        Some(Box::new(move |success| {
            ok_cb.set(success);
            done_cb.set(true);
        })),
    );

    while !done.get() {
        match context.get_state() {
            PaContextState::Failed | PaContextState::Terminated => break,
            _ => {}
        }
        if op.get_state() != PaOperationState::Running {
            break;
        }
        let _ = mainloop.iterate(false);
    }

    if ok.get() {
        return Ok(());
    }
    Err(format!(
        "set card profile failed for card={} profile={}",
        card, profile
    ))
}

fn ensure_pipewire_pro_audio_for_device(device_id: &str) -> Result<String, String> {
    let card = card_from_pipewire_output_node(device_id)
        .or_else(|| parse_pipewire_card_profile_target(device_id).map(|(card, _)| card))
        .ok_or_else(|| "unsupported or empty device id".to_string())?;
    if let Some(active) = pulseaudio_card_active_profile(&card) {
        if active == "pro-audio" {
            return Ok(card);
        }
    }
    let mut last_err = String::new();
    for _ in 0..3 {
        if let Err(e) = pulseaudio_set_card_profile(&card, "pro-audio") {
            last_err = e;
        }
        thread::sleep(Duration::from_millis(120));
        if let Some(active) = pulseaudio_card_active_profile(&card) {
            if active == "pro-audio" {
                return Ok(card);
            }
        }
    }
    Err(format!("failed to switch {card} to pro-audio: {last_err}"))
}

fn as_mut_engine<'a>(ptr: *mut Engine) -> Option<&'a mut Engine> {
    if ptr.is_null() {
        None
    } else {
        // SAFETY: Caller owns pointer returned by rac_new.
        Some(unsafe { &mut *ptr })
    }
}

fn as_engine<'a>(ptr: *const Engine) -> Option<&'a Engine> {
    if ptr.is_null() {
        None
    } else {
        // SAFETY: Caller owns pointer returned by rac_new.
        Some(unsafe { &*ptr })
    }
}

#[no_mangle]
pub extern "C" fn rac_new() -> *mut Engine {
    match Engine::new() {
        Ok(e) => Box::into_raw(Box::new(e)),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_free(ptr: *mut Engine) {
    if ptr.is_null() {
        return;
    }
    // SAFETY: Pointer was allocated by Box::into_raw in rac_new.
    unsafe {
        let mut boxed = Box::from_raw(ptr);
        let _ = boxed.playbin.set_state(gst::State::Null);
        boxed.stop_mmap_sink();
    }
}

#[no_mangle]
pub extern "C" fn rac_set_uri(ptr: *mut Engine, uri: *const c_char) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if uri.is_null() {
        engine.set_error("rac_set_uri: null uri");
        return -2;
    }

    // SAFETY: uri is expected to be valid nul-terminated string from caller.
    let c_uri = unsafe { CStr::from_ptr(uri) };
    let s = match c_uri.to_str() {
        Ok(v) => v,
        Err(_) => {
            engine.set_error("rac_set_uri: invalid utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_uri: invalid utf-8");
            return -3;
        }
    };

    if engine.output_driver_is_mmap() {
        let driver = engine.output_driver.clone();
        let device = engine.output_device.clone();
        let buffer_us = engine.output_buffer_us;
        let latency_us = engine.output_latency_us;
        let exclusive = engine.output_exclusive;
        engine.emit_event(EVT_STATE, "alsa-mmap set_uri: rebuilding output");
        let rc =
            engine.set_output_tuned(&driver, device.as_deref(), buffer_us, latency_us, exclusive);
        if rc != 0 {
            engine.set_error(format!("alsa-mmap set_uri rebind failed rc={rc}"));
            engine.emit_event(
                EVT_ERROR,
                &format!("alsa-mmap set_uri rebind failed rc={rc}"),
            );
            return rc;
        }
        let _ = engine.playbin.set_state(gst::State::Null);
    } else {
        let _ = engine.playbin.set_state(gst::State::Null);
    }
    engine.reset_spectrum_timeline();
    engine.playbin.set_property("uri", s);
    engine.uri = s.to_string();
    engine.last_codec.clear();
    engine.last_bitrate = 0;
    engine.last_rate = 0;
    engine.last_depth = 0;
    engine.source_rate = 0;
    engine.source_depth = 0;
    0
}

#[no_mangle]
pub extern "C" fn rac_play(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if engine.uri.is_empty() {
        engine.set_error("rac_play: empty uri");
        engine.emit_event(EVT_ERROR, "rac_play: empty uri");
        return -2;
    }
    let rc = engine.set_state(gst::State::Playing);
    if rc == 0 && (engine.playback_rate - 1.0).abs() > f64::EPSILON {
        let _ = engine.apply_playback_rate();
    }
    rc
}

#[no_mangle]
pub extern "C" fn rac_pause(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_state(gst::State::Paused)
}

#[no_mangle]
pub extern "C" fn rac_stop(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.reset_spectrum_timeline();
    engine.set_state(gst::State::Null)
}

#[no_mangle]
pub extern "C" fn rac_seek(ptr: *mut Engine, pos_s: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let clamped = if pos_s.is_finite() {
        pos_s.max(0.0)
    } else {
        0.0
    };
    let rc = engine.playbin.seek_simple(
        // Keep FLUSH for responsiveness/stability across sinks; UI side handles
        // brief position rebound after flush-seek.
        gst::SeekFlags::FLUSH | gst::SeekFlags::KEY_UNIT,
        gst::ClockTime::from_nseconds((clamped * 1_000_000_000.0) as u64),
    );
    if rc.is_ok() {
        engine.reset_spectrum_timeline();
        0
    } else {
        engine.set_error("seek failed");
        engine.emit_event(EVT_ERROR, "seek failed");
        -3
    }
}

#[no_mangle]
pub extern "C" fn rac_set_volume(ptr: *mut Engine, vol: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    let v = if vol.is_finite() {
        vol.clamp(0.0, 1.5)
    } else {
        1.0
    };
    engine.playbin.set_property("volume", v);
    0
}

#[no_mangle]
pub extern "C" fn rac_get_position(ptr: *const Engine, pos_out: *mut c_double) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if pos_out.is_null() {
        return -2;
    }

    let pos = match engine.playbin.query_position::<gst::ClockTime>() {
        Some(p) => (p.nseconds() as f64) / 1_000_000_000.0,
        None => 0.0,
    };

    // SAFETY: pos_out is a valid output pointer from caller.
    unsafe {
        *pos_out = pos;
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_get_duration(ptr: *const Engine, dur_out: *mut c_double) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if dur_out.is_null() {
        return -2;
    }

    let dur = match engine.playbin.query_duration::<gst::ClockTime>() {
        Some(d) => (d.nseconds() as f64) / 1_000_000_000.0,
        None => 0.0,
    };

    // SAFETY: dur_out is a valid output pointer from caller.
    unsafe {
        *dur_out = dur;
    }
    0
}

fn probe_latency(engine: &Engine) -> (f64, &'static str) {
    // Primary path: standard GStreamer latency query.
    let mut q = gst::query::Latency::new();
    if engine.playbin.query(&mut q) {
        let (_live, min_lat, max_lat) = q.result();
        let min_ns = min_lat.nseconds();
        let max_ns = max_lat.map(|v| v.nseconds()).unwrap_or(0);
        // For A/V sync, prefer the effective upper bound when available.
        // Many pipelines (network + decode + queue + sink) report a much more
        // realistic playout delay in max-latency than in min-latency.
        if max_ns > 0 && max_ns < 5_000_000_000 {
            return ((max_ns as f64) / 1_000_000_000.0, "gst-query-max");
        }
        if min_ns > 0 && min_ns < 5_000_000_000 {
            return ((min_ns as f64) / 1_000_000_000.0, "gst-query-min");
        }
    }

    // Fallback: read sink latency/buffer properties when query reports 0.
    let sink: Option<gst::Element> = engine.playbin.property("audio-sink");
    if let Some(sink) = sink {
        if sink.find_property("latency-time").is_some() {
            let v: i64 = sink.property("latency-time");
            if v > 0 {
                return ((v as f64) / 1_000_000.0, "sink-latency-time");
            }
        }
        if sink.find_property("buffer-time").is_some() {
            let v: i64 = sink.property("buffer-time");
            if v > 0 {
                return ((v as f64) / 1_000_000.0, "sink-buffer-time");
            }
        }
    }
    (0.0, "none")
}

#[no_mangle]
pub extern "C" fn rac_get_latency(ptr: *const Engine, lat_out: *mut c_double) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return -1;
    };
    if lat_out.is_null() {
        return -2;
    }
    let (latency_s, _src) = probe_latency(engine);

    unsafe {
        *lat_out = if latency_s.is_finite() && latency_s > 0.0 {
            latency_s
        } else {
            0.0
        };
    }
    0
}

#[no_mangle]
pub extern "C" fn rac_get_latency_probe_json(ptr: *const Engine) -> *mut c_char {
    let Some(engine) = as_engine(ptr) else {
        return ptr::null_mut();
    };
    let (latency_s, src) = probe_latency(engine);
    let s = format!(
        "{{\"latency_s\":{},\"source\":\"{}\"}}",
        if latency_s.is_finite() && latency_s > 0.0 {
            latency_s
        } else {
            0.0
        },
        src
    );
    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_is_playing(ptr: *const Engine) -> c_int {
    let Some(engine) = as_engine(ptr) else {
        return 0;
    };
    let (_, state, _) = engine.playbin.state(gst::ClockTime::from_mseconds(50));
    if state == gst::State::Playing {
        1
    } else {
        0
    }
}

#[no_mangle]
pub extern "C" fn rac_get_last_error(ptr: *const Engine) -> *mut c_char {
    let Some(engine) = as_engine(ptr) else {
        return ptr::null_mut();
    };
    let msg = engine.last_error.as_deref().unwrap_or("");
    match CString::new(msg) {
        Ok(s) => s.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_free_string(s: *mut c_char) {
    if s.is_null() {
        return;
    }
    // SAFETY: s was allocated by CString::into_raw in this library.
    unsafe {
        let _ = CString::from_raw(s);
    }
}

#[no_mangle]
pub extern "C" fn rac_set_event_callback(
    ptr: *mut Engine,
    cb: Option<EventCallback>,
    user_data: *mut c_void,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.event_cb = cb;
    engine.event_user_data = user_data;
    0
}

#[no_mangle]
pub extern "C" fn rac_pump_events(ptr: *mut Engine) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.pump_events()
}

#[no_mangle]
pub extern "C" fn rac_set_output(
    ptr: *mut Engine,
    driver: *const c_char,
    device: *const c_char,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if driver.is_null() {
        engine.set_error("rac_set_output: null driver");
        engine.emit_event(EVT_ERROR, "rac_set_output: null driver");
        return -2;
    }

    // SAFETY: caller provides nul-terminated strings.
    let drv = unsafe { CStr::from_ptr(driver) };
    let drv_str = match drv.to_str() {
        Ok(s) => s,
        Err(_) => {
            engine.set_error("rac_set_output: invalid driver utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_output: invalid driver utf-8");
            return -3;
        }
    };

    let dev_opt = if device.is_null() {
        None
    } else {
        // SAFETY: caller provides nul-terminated strings.
        let d = unsafe { CStr::from_ptr(device) };
        d.to_str().ok()
    };

    engine.set_output(drv_str, dev_opt)
}

#[no_mangle]
pub extern "C" fn rac_set_output_tuned(
    ptr: *mut Engine,
    driver: *const c_char,
    device: *const c_char,
    buffer_us: c_int,
    latency_us: c_int,
    exclusive: c_int,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if driver.is_null() {
        engine.set_error("rac_set_output_tuned: null driver");
        engine.emit_event(EVT_ERROR, "rac_set_output_tuned: null driver");
        return -2;
    }

    let drv = unsafe { CStr::from_ptr(driver) };
    let drv_str = match drv.to_str() {
        Ok(s) => s,
        Err(_) => {
            engine.set_error("rac_set_output_tuned: invalid driver utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_output_tuned: invalid driver utf-8");
            return -3;
        }
    };

    let dev_opt = if device.is_null() {
        None
    } else {
        let d = unsafe { CStr::from_ptr(device) };
        d.to_str().ok()
    };

    engine.set_output_tuned(drv_str, dev_opt, buffer_us, latency_us, exclusive != 0)
}

#[no_mangle]
pub extern "C" fn rac_set_mmap_realtime_priority(ptr: *mut Engine, priority: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    engine.set_mmap_realtime_priority(priority)
}

#[no_mangle]
pub extern "C" fn rac_set_preferred_output_format(
    ptr: *mut Engine,
    format_name: *const c_char,
) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if format_name.is_null() {
        engine.preferred_output_format.clear();
        return 0;
    }
    let fmt = unsafe { CStr::from_ptr(format_name) };
    match fmt.to_str() {
        Ok(s) => {
            engine.preferred_output_format = s.trim().to_ascii_uppercase();
            0
        }
        Err(_) => {
            engine.set_error("rac_set_preferred_output_format: invalid utf-8");
            engine.emit_event(EVT_ERROR, "rac_set_preferred_output_format: invalid utf-8");
            -2
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_set_speed(ptr: *mut Engine, speed: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !speed.is_finite() {
        engine.set_error("rac_set_speed: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_speed: non-finite value");
        return -2;
    }
    engine.playback_rate = 1.0;
    let _ = speed; // API kept for compatibility; disabled in HiFi mode.
    engine.emit_event(EVT_STATE, "playback-rate request ignored (hifi-locked)");
    0
}

#[no_mangle]
pub extern "C" fn rac_set_pitch(ptr: *mut Engine, semitones: c_double) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if !semitones.is_finite() {
        engine.set_error("rac_set_pitch: non-finite value");
        engine.emit_event(EVT_ERROR, "rac_set_pitch: non-finite value");
        return -2;
    }
    engine.pitch_semitones = 0.0;
    let _ = semitones; // API kept for compatibility; disabled in HiFi mode.
    engine.emit_event(EVT_STATE, "pitch request ignored (hifi-locked)");
    0
}

#[no_mangle]
pub extern "C" fn rac_set_pipewire_clock_rate(ptr: *mut Engine, rate: c_int) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    match Engine::pipewire_set_clock_force_rate(rate) {
        Ok(()) => {
            engine.emit_event(EVT_STATE, &format!("pipewire clock.force-rate={}", rate));
            0
        }
        Err(e) => {
            engine.set_error(format!("pipewire clock.force-rate failed: {e}"));
            engine.emit_event(EVT_ERROR, &format!("pipewire clock.force-rate failed: {e}"));
            -2
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_set_pipewire_allowed_rates(ptr: *mut Engine, csv: *const c_char) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if csv.is_null() {
        engine.set_error("null allowed-rates csv");
        return -2;
    }
    let csv_s = unsafe { CStr::from_ptr(csv) }.to_string_lossy().to_string();
    match Engine::pipewire_set_clock_allowed_rates_csv(&csv_s) {
        Ok(_) => {
            engine.emit_event(
                EVT_STATE,
                &format!("pipewire clock.allowed-rates={}", csv_s),
            );
            0
        }
        Err(e) => {
            engine.set_error(format!("pipewire clock.allowed-rates failed: {e}"));
            engine.emit_event(
                EVT_ERROR,
                &format!("pipewire clock.allowed-rates failed: {e}"),
            );
            -3
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_set_pipewire_pro_audio(ptr: *mut Engine, device: *const c_char) -> c_int {
    let Some(engine) = as_mut_engine(ptr) else {
        return -1;
    };
    if device.is_null() {
        engine.set_error("null device for pro-audio switch");
        return -2;
    }
    let dev_s = unsafe { CStr::from_ptr(device) }
        .to_string_lossy()
        .to_string();
    match ensure_pipewire_pro_audio_for_device(&dev_s) {
        Ok(card) => {
            engine.emit_event(
                EVT_STATE,
                &format!("pipewire card profile=pro-audio card={card}"),
            );
            0
        }
        Err(e) => {
            engine.set_error(format!("pipewire pro-audio switch failed: {e}"));
            engine.emit_event(EVT_ERROR, &format!("pipewire pro-audio switch failed: {e}"));
            -3
        }
    }
}

#[no_mangle]
pub extern "C" fn rac_list_devices(ptr: *mut Engine, driver: *const c_char) -> *mut c_char {
    let Some(engine) = as_mut_engine(ptr) else {
        return ptr::null_mut();
    };
    if driver.is_null() {
        engine.set_error("rac_list_devices: null driver");
        return ptr::null_mut();
    }
    // SAFETY: caller provides nul-terminated string.
    let drv_c = unsafe { CStr::from_ptr(driver) };
    let drv_str = match drv_c.to_str() {
        Ok(s) => s,
        Err(_) => {
            engine.set_error("rac_list_devices: invalid driver utf-8");
            return ptr::null_mut();
        }
    };

    let devices = devices_for_driver(drv_str);
    let mut s = String::from("[");
    for (i, (name, dev_id)) in devices.into_iter().enumerate() {
        if i > 0 {
            s.push(',');
        }
        let supported_formats =
            supported_output_formats_for_driver_device(drv_str, dev_id.as_deref());
        let supported_bit_depths = supported_output_depths_from_formats(&supported_formats);
        s.push_str("{\"name\":\"");
        s.push_str(&json_escape(&name));
        s.push_str("\",\"device_id\":");
        match dev_id {
            Some(v) => {
                s.push('"');
                s.push_str(&json_escape(&v));
                s.push('"');
            }
            None => s.push_str("null"),
        }
        s.push_str(",\"supported_formats\":[");
        for (fmt_idx, fmt) in supported_formats.iter().enumerate() {
            if fmt_idx > 0 {
                s.push(',');
            }
            s.push('"');
            s.push_str(&json_escape(fmt));
            s.push('"');
        }
        s.push(']');
        s.push_str(",\"supported_bit_depths\":[");
        for (depth_idx, depth) in supported_bit_depths.iter().enumerate() {
            if depth_idx > 0 {
                s.push(',');
            }
            s.push_str(&depth.to_string());
        }
        s.push(']');
        s.push('}');
    }
    s.push(']');

    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn rac_get_runtime_snapshot(ptr: *const Engine) -> *mut c_char {
    let Some(engine) = as_engine(ptr) else {
        return ptr::null_mut();
    };
    let (session_rate, session_depth) = engine.query_output_format();
    let (hw_rate, hw_depth) = read_running_alsa_hw_params();
    let (pw_force_rate, pw_allowed_raw, pw_quantum, pw_rate) =
        Engine::pipewire_read_settings_metadata().unwrap_or((0, String::new(), 0, 0));
    let mut pw_latency_ms = Engine::pipewire_query_app_node_latency_ms().unwrap_or(-1.0);
    if pw_latency_ms < 0.0 && pw_quantum > 0 && pw_rate > 0 {
        pw_latency_ms = (pw_quantum as f64 / pw_rate as f64) * 1000.0;
    }
    let mmap_diag = engine
        .mmap_sink
        .as_ref()
        .and_then(|sink| sink.diagnostics.lock().ok().map(|state| state.clone()));

    let mut s = String::from("{");
    s.push_str("\"pipewire\":{");
    s.push_str(&format!("\"force_rate\":{},", pw_force_rate.max(0)));
    s.push_str(&format!(
        "\"quantum\":{},\"rate\":{},",
        pw_quantum.max(0),
        pw_rate.max(0)
    ));
    s.push_str(&format!(
        "\"latency_ms\":{},",
        if pw_latency_ms >= 0.0 {
            pw_latency_ms
        } else {
            -1.0
        }
    ));
    s.push_str("\"allowed_rates_raw\":\"");
    s.push_str(&json_escape(&pw_allowed_raw));
    s.push_str("\"},");

    s.push_str("\"output\":{");
    s.push_str(&format!(
        "\"session_rate\":{},\"session_depth\":{},\"hardware_rate\":{},\"hardware_depth\":{}",
        session_rate.unwrap_or(0),
        session_depth.unwrap_or(0),
        hw_rate.unwrap_or(0),
        hw_depth.unwrap_or(0),
    ));
    s.push_str("},");
    s.push_str("\"mmap_thread\":");
    match mmap_diag {
        Some(diag) => {
            s.push('{');
            s.push_str(&format!(
                "\"running\":{},\"realtime_attempted\":{},\"realtime_enabled\":{},\"realtime_policy\":\"{}\",\"realtime_priority\":{},\"realtime_error\":\"{}\",\
                 \"memlock_attempted\":{},\"memlock_enabled\":{},\"memlock_mode\":\"{}\",\"memlock_error\":\"{}\",\
                 \"negotiated_rate\":{},\"period_frames\":{},\"buffer_frames\":{},\"open_failures\":{},\"device_resets\":{}",
                diag.running,
                diag.realtime_attempted,
                diag.realtime_enabled,
                json_escape(&diag.realtime_policy),
                diag.realtime_priority,
                json_escape(&diag.realtime_error),
                diag.memlock_attempted,
                diag.memlock_enabled,
                json_escape(&diag.memlock_mode),
                json_escape(&diag.memlock_error),
                diag.negotiated_rate,
                diag.period_frames,
                diag.buffer_frames,
                diag.open_failures,
                diag.device_resets,
            ));
            s.push('}');
        }
        None => s.push_str("null"),
    }
    s.push(',');
    s.push_str("\"source\":{");
    let source_rate = if engine.source_rate > 0 {
        engine.source_rate
    } else if engine.last_rate > 0 {
        engine.last_rate
    } else if session_rate.unwrap_or(0) > 0 {
        session_rate.unwrap_or(0)
    } else {
        0
    };
    let source_depth = if engine.source_depth > 0 {
        engine.source_depth
    } else if engine.last_depth > 0 {
        engine.last_depth
    } else if session_depth.unwrap_or(0) > 0 {
        session_depth.unwrap_or(0)
    } else {
        0
    };
    s.push_str("\"codec\":\"");
    s.push_str(&json_escape(&engine.last_codec));
    s.push_str("\",");
    s.push_str(&format!(
        "\"bitrate\":{},\"rate\":{},\"depth\":{}",
        engine.last_bitrate.max(0),
        source_rate.max(0),
        source_depth.max(0),
    ));
    s.push_str("}}");

    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(_) => ptr::null_mut(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TempProcRoot {
        path: PathBuf,
    }

    impl TempProcRoot {
        fn new(name: &str) -> Self {
            let unique = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0);
            let path = std::env::temp_dir().join(format!(
                "rust_audio_core_{name}_{}_{}",
                std::process::id(),
                unique
            ));
            fs::create_dir_all(&path).expect("create temp proc root");
            Self { path }
        }

        fn path(&self) -> &Path {
            &self.path
        }

        fn write(&self, rel: &str, content: &str) {
            let path = self.path.join(rel);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).expect("create temp proc parent");
            }
            fs::write(path, content).expect("write temp proc file");
        }
    }

    impl Drop for TempProcRoot {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }

    #[test]
    fn audio_byte_window_reuses_stale_prefix_before_growing() {
        let mut window = AudioByteWindow::with_capacity(16);
        window.append(&[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
        window.consume(8);

        let cap_before = window.buf.capacity();
        window.append(&[13, 14, 15, 16, 17, 18]);

        assert_eq!(window.buf.capacity(), cap_before);
        assert_eq!(window.len(), 10);
        assert_eq!(
            window.peek_prefix(10),
            Some(&[9, 10, 11, 12, 13, 14, 15, 16, 17, 18][..])
        );
    }

    #[test]
    fn audio_byte_window_resets_offsets_when_fully_consumed() {
        let mut window = AudioByteWindow::with_capacity(8);
        window.append(&[1, 2, 3, 4]);
        window.consume(4);

        assert_eq!(window.start, 0);
        assert_eq!(window.len(), 0);

        window.append(&[5, 6, 7]);
        assert_eq!(window.peek_prefix(3), Some(&[5, 6, 7][..]));
    }

    #[test]
    fn frames_for_duration_us_tracks_stream_rate() {
        assert_eq!(frames_for_duration_us(10_000, 44_100, 64, 4096), 441);
        assert_eq!(frames_for_duration_us(10_000, 48_000, 64, 4096), 480);
        assert_eq!(frames_for_duration_us(10_000, 96_000, 64, 4096), 960);
    }

    #[test]
    fn frames_for_duration_us_respects_clamps() {
        assert_eq!(frames_for_duration_us(2_000, 44_100, 128, 4096), 128);
        assert_eq!(frames_for_duration_us(500_000, 192_000, 64, 4096), 4096);
    }

    #[test]
    fn alsa_enum_uses_real_playback_pcm_indices() {
        let proc_root = TempProcRoot::new("alsa_pcm_enum");
        proc_root.write("cards", " 2 [USB            ]: USB-Audio - Fancy DAC\n");
        proc_root.write(
            "card2/pcm7p/info",
            "card: 2\ndevice: 7\nname: USB Audio Output\nsubdevices_count: 1\n",
        );

        let devices = list_alsa_cards_from_proc_root(proc_root.path());

        assert_eq!(
            devices,
            vec![(
                "Fancy DAC / USB Audio Output (hw:2,7)".to_string(),
                Some("hw:2,7".to_string()),
            )]
        );
    }

    #[test]
    fn alsa_enum_falls_back_to_card_zero_when_pcm_dirs_missing() {
        let proc_root = TempProcRoot::new("alsa_card_fallback");
        proc_root.write("cards", " 1 [PCH            ]: HDA-Intel - HDA Intel PCH\n");
        fs::create_dir_all(proc_root.path().join("card1")).expect("create fallback card dir");

        let devices = list_alsa_cards_from_proc_root(proc_root.path());

        assert_eq!(
            devices,
            vec![(
                "HDA Intel PCH (Card 1)".to_string(),
                Some("hw:1,0".to_string()),
            )]
        );
    }

    #[test]
    fn alsa_stream_parser_reads_playback_formats_only() {
        let text = r#"MUSILAND Monitor 09 at usb-0000:00:14.0-2, high speed : USB Audio

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S32_LE
    Channels: 2

Capture:
  Status: Stop
  Interface 2
    Altset 1
    Format: S16_LE
"#;

        let formats = parse_alsa_playback_formats_from_stream_text(text);

        assert_eq!(formats, vec!["S32_LE".to_string()]);
    }

    #[test]
    fn alsa_exclusive_caps_format_detects_s32_only_device() {
        let proc_root = TempProcRoot::new("alsa_stream_caps_s32");
        proc_root.write(
            "card2/stream0",
            r#"USB DAC at usb-1, high speed : USB Audio

Playback:
  Interface 1
    Altset 1
    Format: S32_LE
    Channels: 2
    Rates: 44100, 48000
"#,
        );

        let fmt = detect_alsa_exclusive_caps_format_from_proc_root(proc_root.path(), "hw:2,0");

        assert_eq!(fmt, Some("S32LE".to_string()));
    }

    #[test]
    fn alsa_exclusive_caps_format_skips_mixed_format_device() {
        let proc_root = TempProcRoot::new("alsa_stream_caps_mixed");
        proc_root.write(
            "card2/stream0",
            r#"USB DAC at usb-1, high speed : USB Audio

Playback:
  Interface 1
    Altset 1
    Format: S16_LE
    Channels: 2
  Interface 1
    Altset 2
    Format: S32_LE
    Channels: 2
"#,
        );

        let fmt = detect_alsa_exclusive_caps_format_from_proc_root(proc_root.path(), "hw:2,0");

        assert_eq!(fmt, None);
    }

    #[test]
    fn supported_output_formats_map_known_alsa_formats() {
        let formats = supported_output_formats_from_playback_formats(&vec![
            "S16_LE".to_string(),
            "S24_3LE".to_string(),
            "S24_32_LE".to_string(),
            "S32_LE".to_string(),
        ]);

        assert_eq!(
            formats,
            vec![
                "S16LE".to_string(),
                "S24LE".to_string(),
                "S24_32LE".to_string(),
                "S32LE".to_string(),
            ]
        );
    }

    #[test]
    fn supported_output_depths_dedupe_container_formats() {
        let depths = supported_output_depths_from_formats(&vec![
            "S24LE".to_string(),
            "S24_32LE".to_string(),
            "S16LE".to_string(),
            "S32LE".to_string(),
        ]);

        assert_eq!(depths, vec![16, 24, 32]);
    }

    #[test]
    fn pipewire_target_id_prefers_node_name_and_falls_back_to_serial() {
        assert_eq!(
            pipewire_target_id_from_props("alsa_output.usb-DAC.pro-output-0", "701"),
            Some("alsa_output.usb-DAC.pro-output-0".to_string())
        );
        assert_eq!(
            pipewire_target_id_from_props("", "701"),
            Some("701".to_string())
        );
        assert_eq!(pipewire_target_id_from_props("", ""), None);
        assert_eq!(
            pipewire_target_id_from_props("alsa_output.usb-DAC.monitor", "701"),
            None
        );
    }

    #[test]
    fn merge_output_device_lists_prefers_primary_and_adds_missing_entries() {
        let merged = merge_output_device_lists(
            vec![
                (
                    "USB DAC".to_string(),
                    Some("alsa_output.usb-DAC.pro-output-0".to_string()),
                ),
                ("Serial Only Sink".to_string(), Some("701".to_string())),
            ],
            vec![
                (
                    "USB DAC via Pulse".to_string(),
                    Some("alsa_output.usb-DAC.pro-output-0".to_string()),
                ),
                (
                    "HDMI Sink".to_string(),
                    Some("alsa_output.pci-HDMI.iec958-stereo".to_string()),
                ),
                ("Serial Only Duplicate".to_string(), Some("701".to_string())),
                ("Fallback Sink".to_string(), None),
                ("Fallback Sink".to_string(), None),
            ],
        );

        assert_eq!(
            merged,
            vec![
                (
                    "USB DAC".to_string(),
                    Some("alsa_output.usb-DAC.pro-output-0".to_string())
                ),
                ("Serial Only Sink".to_string(), Some("701".to_string())),
                (
                    "HDMI Sink".to_string(),
                    Some("alsa_output.pci-HDMI.iec958-stereo".to_string())
                ),
                ("Fallback Sink".to_string(), None),
            ]
        );
    }

    #[test]
    fn pipewire_card_profile_target_round_trips() {
        let built = build_pipewire_card_profile_target("alsa_card.pci-0000_00_03.0", "pro-audio");
        assert_eq!(
            built,
            "pwcardprofile:alsa_card.pci-0000_00_03.0|pro-audio".to_string()
        );
        assert_eq!(
            parse_pipewire_card_profile_target(&built),
            Some((
                "alsa_card.pci-0000_00_03.0".to_string(),
                "pro-audio".to_string()
            ))
        );
        assert_eq!(
            parse_pipewire_card_profile_target("pwcardprofile:bad"),
            None
        );
    }

    #[test]
    fn pipewire_display_name_combines_description_and_nick() {
        assert_eq!(
            pipewire_display_name_from_strings(
                "Built-in Audio Pro 1",
                "CS4208 Digital",
                "alsa_output.pci-0000_00_1b.0.pro-output-1",
            ),
            "Built-in Audio / CS4208 Digital".to_string()
        );
        assert_eq!(
            pipewire_display_name_from_strings(
                "Built-in Audio Pro",
                "Built-in Audio Pro",
                "alsa_output.pci-0000_00_1b.0.analog-stereo"
            ),
            "Built-in Audio / Analog".to_string()
        );
        assert_eq!(
            pipewire_display_name_from_strings("", "CS4208 Digital", "fallback"),
            "CS4208 Digital".to_string()
        );
        assert_eq!(
            pipewire_display_name_from_strings(
                "Monitor 09 Analog Stereo",
                "",
                "alsa_output.usb-Monitor_09_USB_Audio-00.analog-stereo",
            ),
            "Monitor 09 / USB Audio".to_string()
        );
        assert_eq!(
            pipewire_display_name_from_strings(
                "Built-in Audio Pro 7",
                "",
                "alsa_output.pci-0000_00_03.0.hdmi-stereo-extra1",
            ),
            "Built-in Audio / HDMI 1".to_string()
        );
        // Actual MUSILAND Monitor 09: nick carries the real model name, desc adds
        // "Analog Stereo" suffix — should return nick directly, not the fallback
        // card label derived from the node path.
        assert_eq!(
            pipewire_display_name_from_strings(
                "Monitor 09 Analog Stereo",
                "Monitor 09",
                "alsa_output.usb-MUSILAND_Monitor_09-00.analog-stereo",
            ),
            "Monitor 09".to_string()
        );
    }

    #[test]
    fn choose_pipewire_output_profile_prefers_active_then_available() {
        let profiles = vec![
            ("output:hdmi-stereo".to_string(), 1, 5900, false),
            ("pro-audio".to_string(), 3, 1, true),
        ];
        assert_eq!(
            choose_pipewire_output_profile_from_entries(Some("output:hdmi-stereo"), &profiles),
            Some("output:hdmi-stereo".to_string())
        );
        assert_eq!(
            choose_pipewire_output_profile_from_entries(Some("off"), &profiles),
            Some("pro-audio".to_string())
        );
    }

}
