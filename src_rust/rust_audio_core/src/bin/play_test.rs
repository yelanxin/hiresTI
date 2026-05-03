//! Headless CLI playback test for the V2 native_transport USB path.
//!
//! Bypasses Python / GTK / GLib / MPRIS / spectrum / lyrics / MQTT so the
//! FiiO click investigation can isolate whether any of those workloads is
//! disturbing the libusb event thread or the USB bus.
//!
//! Usage:
//!   cargo run --release --bin play_test -- <file-or-uri> [opts]
//!
//! Options:
//!   --device <usb:VID:PID>   pick a specific DAC (default: first detected)
//!   --seconds <N>            stop after N seconds (default: play to EOS)
//!   --clock <push|pull>      USB rawlink clock mode (default: push)
//!
//! Example:
//!   cargo run --release --bin play_test -- \
//!       "file:///home/eason/Music/Bandari/Moonlight Bay/01 - Caribbean Blue [24bit-96kHz].flac"

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_void};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use rust_audio_core::{
    rac_free, rac_list_usb_audio_devices, rac_new, rac_play, rac_pump_events,
    rac_set_event_callback, rac_set_output, rac_set_uri, rac_set_usb_clock_mode, rac_stop,
    Engine,
};

const EVT_STATE: c_int = 1;
const EVT_ERROR: c_int = 2;
const EVT_EOS: c_int = 3;
const EVT_TAG: c_int = 4;

const RAC_USB_CLOCK_PUSH: c_int = 0;
const RAC_USB_CLOCK_PULL: c_int = 1;

static EOS_FIRED: AtomicBool = AtomicBool::new(false);
static FATAL_ERROR: AtomicBool = AtomicBool::new(false);

extern "C" fn event_cb(kind: c_int, msg: *const c_char, _user: *mut c_void) {
    let text = if msg.is_null() {
        ""
    } else {
        unsafe { CStr::from_ptr(msg) }.to_str().unwrap_or("(invalid utf-8)")
    };
    let label = match kind {
        EVT_STATE => "STATE",
        EVT_ERROR => "ERROR",
        EVT_EOS => "EOS",
        EVT_TAG => "TAG",
        _ => "?",
    };
    eprintln!("[event] {label}: {text}");
    if kind == EVT_EOS {
        EOS_FIRED.store(true, Ordering::Release);
    } else if kind == EVT_ERROR {
        FATAL_ERROR.store(true, Ordering::Release);
    }
}

struct Args {
    uri: String,
    device: Option<String>,
    seconds: Option<u64>,
    clock_mode: c_int,
}

fn parse_args() -> Args {
    let mut uri: Option<String> = None;
    let mut device: Option<String> = None;
    let mut seconds: Option<u64> = None;
    let mut clock_mode = RAC_USB_CLOCK_PUSH;

    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--device" => device = it.next(),
            "--seconds" => {
                seconds = it.next().and_then(|s| s.parse().ok());
            }
            "--clock" => match it.next().as_deref() {
                Some("pull") => clock_mode = RAC_USB_CLOCK_PULL,
                Some("push") | None => clock_mode = RAC_USB_CLOCK_PUSH,
                Some(other) => {
                    eprintln!("unknown --clock value: {other}");
                    std::process::exit(2);
                }
            },
            "-h" | "--help" => {
                print_usage();
                std::process::exit(0);
            }
            _ if arg.starts_with("--") => {
                eprintln!("unknown option: {arg}");
                print_usage();
                std::process::exit(2);
            }
            _ => {
                if uri.is_some() {
                    eprintln!("multiple file arguments not supported");
                    std::process::exit(2);
                }
                uri = Some(arg);
            }
        }
    }

    let raw = match uri {
        Some(u) => u,
        None => {
            print_usage();
            std::process::exit(2);
        }
    };
    let uri = if raw.starts_with("file://")
        || raw.starts_with("http://")
        || raw.starts_with("https://")
    {
        raw
    } else {
        let abs = std::path::PathBuf::from(&raw)
            .canonicalize()
            .unwrap_or_else(|_| std::path::PathBuf::from(&raw));
        format!("file://{}", abs.display())
    };

    Args {
        uri,
        device,
        seconds,
        clock_mode,
    }
}

fn print_usage() {
    eprintln!(
        "Usage: play_test <file-or-uri> [--device usb:VID:PID] [--seconds N] [--clock push|pull]"
    );
}

fn list_usb_devices() -> Vec<String> {
    unsafe {
        let raw = rac_list_usb_audio_devices();
        if raw.is_null() {
            return Vec::new();
        }
        let json = CStr::from_ptr(raw).to_str().unwrap_or("").to_owned();
        rust_audio_core::rac_free_string(raw);

        let needle = "\"id\":\"";
        let mut out = Vec::new();
        let mut cursor = 0usize;
        while let Some(found) = json[cursor..].find(needle) {
            let start = cursor + found + needle.len();
            if let Some(rel_end) = json[start..].find('"') {
                let end = start + rel_end;
                out.push(json[start..end].to_owned());
                cursor = end + 1;
            } else {
                break;
            }
        }
        out
    }
}

fn main() {
    let args = parse_args();

    let device = match args.device.clone() {
        Some(d) => d,
        None => {
            let devices = list_usb_devices();
            match devices.len() {
                0 => {
                    eprintln!(
                        "no USB audio device found — run usb_enum to inspect what's attached"
                    );
                    std::process::exit(1);
                }
                1 => devices.into_iter().next().unwrap(),
                _ => {
                    eprintln!("multiple USB audio devices found — pass --device to disambiguate:");
                    for id in &devices {
                        eprintln!("  {id}");
                    }
                    std::process::exit(1);
                }
            }
        }
    };
    eprintln!("[play_test] device={device} uri={} clock={}", args.uri,
        if args.clock_mode == RAC_USB_CLOCK_PULL { "pull" } else { "push" });

    let engine: *mut Engine = unsafe { rac_new() };
    if engine.is_null() {
        eprintln!("rac_new returned null");
        std::process::exit(1);
    }

    unsafe {
        rac_set_event_callback(engine, Some(event_cb), std::ptr::null_mut());

        let driver = CString::new("USB Rawlink v2").unwrap();
        let dev_c = CString::new(device.as_str()).unwrap();
        let rc = rac_set_output(engine, driver.as_ptr(), dev_c.as_ptr());
        if rc != 0 {
            eprintln!("rac_set_output failed rc={rc}");
            rac_free(engine);
            std::process::exit(1);
        }

        let _ = rac_set_usb_clock_mode(engine, args.clock_mode);

        let uri_c = CString::new(args.uri.as_str()).unwrap();
        let rc = rac_set_uri(engine, uri_c.as_ptr());
        if rc != 0 {
            eprintln!("rac_set_uri failed rc={rc}");
            rac_free(engine);
            std::process::exit(1);
        }

        let rc = rac_play(engine);
        if rc != 0 {
            eprintln!("rac_play failed rc={rc}");
            rac_free(engine);
            std::process::exit(1);
        }
    }

    // Tight pump loop — no GLib timers, no GTK, no MPRIS, no spectrum.
    let started = Instant::now();
    let deadline = args.seconds.map(|s| started + Duration::from_secs(s));
    loop {
        unsafe {
            rac_pump_events(engine);
        }
        if EOS_FIRED.load(Ordering::Acquire) {
            eprintln!("[play_test] EOS — exiting");
            break;
        }
        if FATAL_ERROR.load(Ordering::Acquire) {
            eprintln!("[play_test] fatal error — exiting");
            break;
        }
        if let Some(d) = deadline {
            if Instant::now() >= d {
                eprintln!("[play_test] reached --seconds deadline");
                break;
            }
        }
        std::thread::sleep(Duration::from_millis(50));
    }

    unsafe {
        rac_stop(engine);
        rac_free(engine);
    }
}
