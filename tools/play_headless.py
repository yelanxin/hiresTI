#!/usr/bin/env python3
"""Headless click-isolation test.

Runs the Rust audio engine from a plain Python process — no GTK, no GLib,
no Adw, no MPRIS, no tidalapi. If this still clicks on the FiiO DAC, the
cause is in the Python interpreter / libusb co-residency, not the GTK
widget tree.

Usage:
    python3 tools/play_headless.py <file-or-uri> [--device usb:VID:PID]
                                   [--seconds N] [--clock push|pull]

Example:
    python3 tools/play_headless.py \\
        "/home/eason/Music/Bandari/Moonlight Bay/01 - Caribbean Blue [24bit-96kHz].wav"
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import sys
import time
from pathlib import Path

EVT_LABELS = {1: "STATE", 2: "ERROR", 3: "EOS", 4: "TAG"}

EOS_FIRED = False
FATAL = False


def _find_lib() -> Path:
    here = Path(__file__).resolve().parent.parent
    candidates = [
        here / "src_rust" / "rust_audio_core" / "target" / "release" / "librust_audio_core.so",
        here / "src_rust" / "rust_audio_core" / "target" / "debug" / "librust_audio_core.so",
        Path("/usr/share/hiresti/src_rust/rust_audio_core/target/release/librust_audio_core.so"),
    ]
    for c in candidates:
        if c.exists():
            return c
    sys.exit(f"librust_audio_core.so not found; tried: {[str(c) for c in candidates]}")


def main() -> None:
    p = argparse.ArgumentParser(description="Headless audio playback test.")
    p.add_argument("uri", help="file path or file:// / http(s):// URI")
    p.add_argument("--device", default=None, help="USB device id (usb:VID:PID)")
    p.add_argument("--seconds", type=int, default=None, help="stop after N seconds")
    p.add_argument("--clock", choices=["push", "pull"], default="push")
    args = p.parse_args()

    raw = args.uri
    if raw.startswith(("file://", "http://", "https://")):
        uri = raw
    else:
        uri = "file://" + str(Path(raw).expanduser().resolve())

    lib_path = _find_lib()
    print(f"[headless] loading {lib_path}", file=sys.stderr)
    lib = ctypes.CDLL(str(lib_path))

    # Function signatures
    lib.rac_new.restype = ctypes.c_void_p
    lib.rac_free.argtypes = [ctypes.c_void_p]
    lib.rac_set_output.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.rac_set_output.restype = ctypes.c_int
    lib.rac_set_uri.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.rac_set_uri.restype = ctypes.c_int
    lib.rac_play.argtypes = [ctypes.c_void_p]
    lib.rac_play.restype = ctypes.c_int
    lib.rac_stop.argtypes = [ctypes.c_void_p]
    lib.rac_stop.restype = ctypes.c_int
    lib.rac_pump_events.argtypes = [ctypes.c_void_p]
    lib.rac_pump_events.restype = ctypes.c_int
    lib.rac_set_usb_clock_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.rac_set_usb_clock_mode.restype = ctypes.c_int
    lib.rac_list_usb_audio_devices.restype = ctypes.c_char_p
    lib.rac_free_string.argtypes = [ctypes.c_char_p]

    EventCB = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
    lib.rac_set_event_callback.argtypes = [ctypes.c_void_p, EventCB, ctypes.c_void_p]
    lib.rac_set_event_callback.restype = ctypes.c_int

    # Pick device
    device = args.device
    if device is None:
        json_blob = lib.rac_list_usb_audio_devices()
        if not json_blob:
            sys.exit("no USB audio devices found")
        try:
            data = json.loads(json_blob.decode("utf-8", "ignore"))
            ids = [d.get("id") for d in data if d.get("id", "").startswith("usb:")]
        except Exception as e:
            sys.exit(f"failed to parse device list: {e}")
        if not ids:
            sys.exit("no USB devices in list")
        if len(ids) > 1:
            sys.exit("multiple USB devices found, pass --device:\n  " + "\n  ".join(ids))
        device = ids[0]

    print(f"[headless] device={device} uri={uri} clock={args.clock}", file=sys.stderr)

    @EventCB
    def on_event(kind, msg, _user):
        global EOS_FIRED, FATAL
        text = msg.decode("utf-8", "ignore") if msg else ""
        label = EVT_LABELS.get(kind, "?")
        print(f"[event] {label}: {text}", file=sys.stderr)
        if kind == 3:  # EOS
            EOS_FIRED = True
        elif kind == 2:  # ERROR
            FATAL = True

    engine = lib.rac_new()
    if not engine:
        sys.exit("rac_new failed")

    try:
        rc = lib.rac_set_event_callback(engine, on_event, None)
        rc = lib.rac_set_output(engine, b"USB Rawlink v2", device.encode())
        if rc != 0:
            sys.exit(f"rac_set_output rc={rc}")
        lib.rac_set_usb_clock_mode(engine, 1 if args.clock == "pull" else 0)
        rc = lib.rac_set_uri(engine, uri.encode())
        if rc != 0:
            sys.exit(f"rac_set_uri rc={rc}")
        rc = lib.rac_play(engine)
        if rc != 0:
            sys.exit(f"rac_play rc={rc}")

        stop_at = (time.monotonic() + args.seconds) if args.seconds else None

        def handle_signal(_sig, _frm):
            global FATAL
            FATAL = True

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        # Tight pump loop — same cadence the GTK app uses (200ms when idle/no
        # spectrum stream).  Plain Python `time.sleep` only, no GLib.
        while True:
            lib.rac_pump_events(engine)
            if EOS_FIRED:
                print("[headless] EOS — exiting", file=sys.stderr)
                break
            if FATAL:
                print("[headless] fatal/interrupt — exiting", file=sys.stderr)
                break
            if stop_at is not None and time.monotonic() >= stop_at:
                print("[headless] reached --seconds deadline", file=sys.stderr)
                break
            time.sleep(0.2)
    finally:
        try:
            lib.rac_stop(engine)
        except Exception:
            pass
        lib.rac_free(engine)


if __name__ == "__main__":
    main()
