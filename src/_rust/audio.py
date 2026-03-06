import ctypes
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from collections import deque

from gi.repository import GLib
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Gst, GstPbutils

logger = logging.getLogger(__name__)

DRIVER_ALSA_AUTO = "ALSA（auto）"
DRIVER_ALSA_MMAP = "ALSA（mmap）"


def _driver_key(driver_name):
    text = str(driver_name or "").strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    compact = text.replace(" ", "")
    if compact in ("alsa_mmap", "alsa(mmap)"):
        return "alsa_mmap"
    if compact in ("alsa", "alsa(auto)"):
        return "alsa_auto"
    if compact in ("pipewire",):
        return "pipewire"
    if compact in ("auto", "auto(default)"):
        return "auto"
    return compact


class _RustAudioCore:
    EVENT_STATE = 1
    EVENT_ERROR = 2
    EVENT_EOS = 3
    EVENT_TAG = 4

    def __init__(self):
        self.lib = None
        self.handle = None
        self.available = False
        self._closed = False
        self._call_lock = threading.RLock()
        self._event_cb_fn = None
        self._event_py_cb = None
        self._spectrum_batch_cache = {}

        so_paths = [
            # Development: src/_rust/audio.py -> project_root/src_rust/
            Path(__file__).resolve().parent.parent / "src_rust" / "rust_audio_core" / "target" / "release" / "librust_audio_core.so",
            # Installed: usr/share/hiresti/_rust/audio.py -> usr/share/hiresti/src_rust/
            Path(__file__).resolve().parent.parent.parent / "src_rust" / "rust_audio_core" / "target" / "release" / "librust_audio_core.so",
            # Flatpak: /app/share/hiresti/src_rust/
            Path("/app/share/hiresti/src_rust/rust_audio_core/target/release/librust_audio_core.so"),
            # System install
            Path("/usr/share/hiresti/src_rust/rust_audio_core/target/release/librust_audio_core.so"),
        ]
        so_path = next((p for p in so_paths if p.exists()), None)
        if so_path is None:
            logger.info("Rust audio core library not found; path tried=%s", [str(p) for p in so_paths])
            return

        try:
            lib = ctypes.CDLL(str(so_path))

            lib.rac_new.restype = ctypes.c_void_p
            lib.rac_new.argtypes = []

            lib.rac_free.restype = None
            lib.rac_free.argtypes = [ctypes.c_void_p]

            lib.rac_set_uri.restype = ctypes.c_int
            lib.rac_set_uri.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

            lib.rac_play.restype = ctypes.c_int
            lib.rac_play.argtypes = [ctypes.c_void_p]

            lib.rac_pause.restype = ctypes.c_int
            lib.rac_pause.argtypes = [ctypes.c_void_p]

            lib.rac_stop.restype = ctypes.c_int
            lib.rac_stop.argtypes = [ctypes.c_void_p]

            lib.rac_seek.restype = ctypes.c_int
            lib.rac_seek.argtypes = [ctypes.c_void_p, ctypes.c_double]

            lib.rac_set_volume.restype = ctypes.c_int
            lib.rac_set_volume.argtypes = [ctypes.c_void_p, ctypes.c_double]

            lib.rac_get_position.restype = ctypes.c_int
            lib.rac_get_position.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)]

            lib.rac_get_duration.restype = ctypes.c_int
            lib.rac_get_duration.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)]

            if hasattr(lib, "rac_get_latency"):
                lib.rac_get_latency.restype = ctypes.c_int
                lib.rac_get_latency.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)]
            if hasattr(lib, "rac_get_latency_probe_json"):
                lib.rac_get_latency_probe_json.restype = ctypes.c_void_p
                lib.rac_get_latency_probe_json.argtypes = [ctypes.c_void_p]

            lib.rac_is_playing.restype = ctypes.c_int
            lib.rac_is_playing.argtypes = [ctypes.c_void_p]

            lib.rac_set_event_callback.restype = ctypes.c_int
            lib.rac_set_event_callback.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

            lib.rac_pump_events.restype = ctypes.c_int
            lib.rac_pump_events.argtypes = [ctypes.c_void_p]

            lib.rac_set_output.restype = ctypes.c_int
            lib.rac_set_output.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
            if hasattr(lib, "rac_set_output_tuned"):
                lib.rac_set_output_tuned.restype = ctypes.c_int
                lib.rac_set_output_tuned.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_char_p,
                    ctypes.c_char_p,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                ]
            if hasattr(lib, "rac_set_mmap_realtime_priority"):
                lib.rac_set_mmap_realtime_priority.restype = ctypes.c_int
                lib.rac_set_mmap_realtime_priority.argtypes = [ctypes.c_void_p, ctypes.c_int]
            if hasattr(lib, "rac_set_preferred_output_format"):
                lib.rac_set_preferred_output_format.restype = ctypes.c_int
                lib.rac_set_preferred_output_format.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

            lib.rac_set_speed.restype = ctypes.c_int
            lib.rac_set_speed.argtypes = [ctypes.c_void_p, ctypes.c_double]

            lib.rac_set_pitch.restype = ctypes.c_int
            lib.rac_set_pitch.argtypes = [ctypes.c_void_p, ctypes.c_double]
            if hasattr(lib, "rac_set_pipewire_clock_rate"):
                lib.rac_set_pipewire_clock_rate.restype = ctypes.c_int
                lib.rac_set_pipewire_clock_rate.argtypes = [ctypes.c_void_p, ctypes.c_int]
            if hasattr(lib, "rac_set_pipewire_allowed_rates"):
                lib.rac_set_pipewire_allowed_rates.restype = ctypes.c_int
                lib.rac_set_pipewire_allowed_rates.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            if hasattr(lib, "rac_set_pipewire_pro_audio"):
                lib.rac_set_pipewire_pro_audio.restype = ctypes.c_int
                lib.rac_set_pipewire_pro_audio.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            if hasattr(lib, "rac_get_runtime_snapshot"):
                lib.rac_get_runtime_snapshot.restype = ctypes.c_void_p
                lib.rac_get_runtime_snapshot.argtypes = [ctypes.c_void_p]

            lib.rac_list_devices.restype = ctypes.c_void_p
            lib.rac_list_devices.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

            lib.rac_free_string.restype = None
            lib.rac_free_string.argtypes = [ctypes.c_void_p]

            if hasattr(lib, "rac_get_last_error"):
                lib.rac_get_last_error.restype = ctypes.c_void_p
                lib.rac_get_last_error.argtypes = [ctypes.c_void_p]

            lib.rac_get_spectrum_frame.restype = ctypes.c_int
            lib.rac_get_spectrum_frame.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_float),
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_uint64),
            ]
            lib.rac_get_spectrum_frames_since.restype = ctypes.c_int
            lib.rac_get_spectrum_frames_since.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint64,
                ctypes.POINTER(ctypes.c_float),
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_uint64),
            ]
            lib.rac_set_spectrum_enabled.restype = ctypes.c_int
            lib.rac_set_spectrum_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]

            self.lib = lib
            self.handle = ctypes.c_void_p(lib.rac_new())
            self.available = bool(self.handle)
            if self.available:
                logger.info("Rust audio core initialized: %s", so_path)
        except Exception:
            self.lib = None
            self.handle = None
            self.available = False
            logger.exception("Failed to initialize Rust audio core")

    def close(self):
        with self._call_lock:
            if self._closed:
                return
            self._closed = True
            if self.lib is not None and self.handle:
                try:
                    if self._event_cb_fn is not None:
                        self.lib.rac_set_event_callback(self.handle, ctypes.c_void_p(), ctypes.c_void_p())
                    self.lib.rac_free(self.handle)
                except Exception:
                    pass
            self.handle = None

    def _call_int(self, fn_name, *args, default_rc=-99):
        if (not self.available) or self._closed:
            return -1
        with self._call_lock:
            if self._closed or not self.handle:
                return -1
            try:
                fn = getattr(self.lib, fn_name, None)
                if fn is None:
                    return -2
                return int(fn(self.handle, *args))
            except Exception:
                logger.exception("Rust audio core call failed: %s", fn_name)
                return default_rc

    def set_event_callback(self, py_callback):
        if (not self.available) or self._closed:
            return
        self._event_py_cb = py_callback
        cb_type = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)

        @cb_type
        def _trampoline(evt, msg_ptr, _user_data):
            if self._event_py_cb is None:
                return
            msg = ""
            if msg_ptr:
                try:
                    msg = ctypes.cast(msg_ptr, ctypes.c_char_p).value.decode("utf-8", "ignore")
                except Exception:
                    msg = ""
            try:
                self._event_py_cb(int(evt), msg)
            except Exception:
                logger.exception("Rust audio event callback failed")

        self._event_cb_fn = _trampoline
        with self._call_lock:
            if self._closed or not self.handle:
                return
            self.lib.rac_set_event_callback(self.handle, ctypes.cast(self._event_cb_fn, ctypes.c_void_p), ctypes.c_void_p())

    def pump_events(self):
        if (not self.available) or self._closed:
            return 0
        with self._call_lock:
            if self._closed or not self.handle:
                return 0
            try:
                return int(self.lib.rac_pump_events(self.handle))
            except Exception:
                return 0

    def set_uri(self, uri):
        data = str(uri or "").encode("utf-8", "ignore")
        return self._call_int("rac_set_uri", data, default_rc=-3)

    def play(self):
        return self._call_int("rac_play", default_rc=-3)

    def pause(self):
        return self._call_int("rac_pause", default_rc=-3)

    def stop(self):
        return self._call_int("rac_stop", default_rc=-3)

    def seek(self, seconds):
        return self._call_int("rac_seek", ctypes.c_double(float(seconds or 0.0)), default_rc=-3)

    def set_volume(self, vol):
        return self._call_int("rac_set_volume", ctypes.c_double(float(vol or 0.0)), default_rc=-3)

    def set_output(self, driver, device_id=None, buffer_us=100000, latency_us=10000, exclusive=False):
        if not self.available:
            return -1
        drv = str(driver or "").strip()
        if not drv:
            drv = "auto"
        dev = str(device_id or "").strip()
        drv_b = drv.encode("utf-8", "ignore")
        dev_b = dev.encode("utf-8", "ignore") if dev else None
        if hasattr(self.lib, "rac_set_output_tuned"):
            rc = self._call_int(
                "rac_set_output_tuned",
                drv_b,
                dev_b,
                ctypes.c_int(int(buffer_us or 0)),
                ctypes.c_int(int(latency_us or 0)),
                ctypes.c_int(1 if exclusive else 0),
                default_rc=-2,
            )
        else:
            rc = self._call_int("rac_set_output", drv_b, dev_b, default_rc=-2)
        if rc == 0:
            logger.info(
                "Rust output route applied: driver=%s device=%s buffer_us=%s latency_us=%s exclusive=%s",
                drv,
                dev or "default",
                int(buffer_us or 0),
                int(latency_us or 0),
                bool(exclusive),
            )
        else:
            logger.warning("Rust output route failed rc=%s driver=%s device=%s", rc, drv, dev or "default")
        return rc

    def set_mmap_realtime_priority(self, priority):
        if not self.available:
            return -1
        if not hasattr(self.lib, "rac_set_mmap_realtime_priority"):
            return -2
        return self._call_int(
            "rac_set_mmap_realtime_priority",
            ctypes.c_int(int(priority or 0)),
            default_rc=-3,
        )

    def set_preferred_output_format(self, format_name=None):
        if (not self.available) or self._closed:
            return -1
        if not hasattr(self.lib, "rac_set_preferred_output_format"):
            return -3
        fmt = str(format_name or "").strip()
        fmt_b = fmt.encode("utf-8", "ignore") if fmt else None
        return self._call_int("rac_set_preferred_output_format", fmt_b, default_rc=-2)

    def set_speed(self, speed):
        rc = self._call_int("rac_set_speed", ctypes.c_double(float(speed or 1.0)), default_rc=-2)
        if rc == 0:
            logger.info("Rust playback speed applied: %.3fx", float(speed or 1.0))
        else:
            logger.warning("Rust playback speed failed rc=%s speed=%s", rc, speed)
        return rc

    def set_pitch(self, semitones):
        rc = self._call_int("rac_set_pitch", ctypes.c_double(float(semitones or 0.0)), default_rc=-2)
        if rc == 0:
            logger.info("Rust playback pitch accepted: %.2f semitones", float(semitones or 0.0))
        else:
            logger.warning("Rust playback pitch failed rc=%s semitones=%s", rc, semitones)
        return rc

    def set_pipewire_clock_rate(self, rate_hz):
        if not self.available:
            return -1
        if not hasattr(self.lib, "rac_set_pipewire_clock_rate"):
            return -2
        return self._call_int("rac_set_pipewire_clock_rate", ctypes.c_int(int(rate_hz or 0)), default_rc=-3)

    def set_pipewire_allowed_rates(self, rates_csv):
        if not self.available:
            return -1
        if not hasattr(self.lib, "rac_set_pipewire_allowed_rates"):
            return -2
        data = str(rates_csv or "").encode("utf-8", "ignore")
        return self._call_int("rac_set_pipewire_allowed_rates", data, default_rc=-3)

    def set_pipewire_pro_audio(self, device_id):
        if not self.available:
            return -1
        if not hasattr(self.lib, "rac_set_pipewire_pro_audio"):
            return -2
        data = str(device_id or "").encode("utf-8", "ignore")
        return self._call_int("rac_set_pipewire_pro_audio", data, default_rc=-3)

    def get_runtime_snapshot(self):
        if (not self.available) or self._closed:
            return None
        raw_ptr = None
        try:
            with self._call_lock:
                if self._closed or not self.handle or (not hasattr(self.lib, "rac_get_runtime_snapshot")):
                    return None
                raw_ptr = self.lib.rac_get_runtime_snapshot(self.handle)
            if not raw_ptr:
                return None
            raw = ctypes.cast(raw_ptr, ctypes.c_char_p).value
            if not raw:
                return None
            data = json.loads(raw.decode("utf-8", "ignore"))
            if isinstance(data, dict):
                return data
            return None
        except Exception:
            logger.exception("Rust audio core get_runtime_snapshot failed")
            return None
        finally:
            if raw_ptr:
                try:
                    with self._call_lock:
                        if not self._closed:
                            self.lib.rac_free_string(raw_ptr)
                except Exception:
                    pass

    def is_playing(self):
        if (not self.available) or self._closed:
            return False
        with self._call_lock:
            if self._closed or not self.handle:
                return False
            try:
                return bool(self.lib.rac_is_playing(self.handle))
            except Exception:
                return False

    def get_position(self):
        if (not self.available) or self._closed:
            return 0.0
        with self._call_lock:
            if self._closed or not self.handle:
                return 0.0
            try:
                out = ctypes.c_double(0.0)
                rc = int(self.lib.rac_get_position(self.handle, ctypes.byref(out)))
                if rc == 0:
                    return float(out.value)
            except Exception:
                pass
        return 0.0

    def get_duration(self):
        if (not self.available) or self._closed:
            return 0.0
        with self._call_lock:
            if self._closed or not self.handle:
                return 0.0
            try:
                out = ctypes.c_double(0.0)
                rc = int(self.lib.rac_get_duration(self.handle, ctypes.byref(out)))
                if rc == 0:
                    return float(out.value)
            except Exception:
                pass
        return 0.0

    def get_latency(self):
        if (not self.available) or self._closed:
            return 0.0
        if not hasattr(self.lib, "rac_get_latency"):
            return 0.0
        with self._call_lock:
            if self._closed or not self.handle:
                return 0.0
            try:
                out = ctypes.c_double(0.0)
                rc = int(self.lib.rac_get_latency(self.handle, ctypes.byref(out)))
                if rc == 0:
                    return max(0.0, float(out.value))
            except Exception:
                pass
        return 0.0

    def get_latency_probe(self):
        if (not self.available) or self._closed:
            return None
        if not hasattr(self.lib, "rac_get_latency_probe_json"):
            return None
        raw_ptr = None
        try:
            with self._call_lock:
                if self._closed or not self.handle:
                    return None
                raw_ptr = self.lib.rac_get_latency_probe_json(self.handle)
            if not raw_ptr:
                return None
            raw = ctypes.cast(raw_ptr, ctypes.c_char_p).value
            if not raw:
                return None
            data = json.loads(raw.decode("utf-8", "ignore"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None
        finally:
            if raw_ptr:
                try:
                    with self._call_lock:
                        if not self._closed:
                            self.lib.rac_free_string(raw_ptr)
                except Exception:
                    pass

    def list_devices(self, driver):
        if (not self.available) or self._closed:
            return None
        drv = str(driver or "").encode("utf-8", "ignore")
        raw_ptr = None
        try:
            with self._call_lock:
                if self._closed or not self.handle:
                    return None
                raw_ptr = self.lib.rac_list_devices(self.handle, drv)
            if not raw_ptr:
                return None
            raw = ctypes.cast(raw_ptr, ctypes.c_char_p).value
            if not raw:
                return []
            data = json.loads(raw.decode("utf-8", "ignore"))
            if not isinstance(data, list):
                return None
            out = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                dev_id = item.get("device_id", None)
                if dev_id is not None:
                    dev_id = str(dev_id)
                supported_formats = []
                for raw_fmt in list(item.get("supported_formats") or []):
                    fmt = str(raw_fmt or "").strip()
                    if fmt:
                        supported_formats.append(fmt)
                supported_bit_depths = []
                for raw_depth in list(item.get("supported_bit_depths") or []):
                    try:
                        depth = int(raw_depth or 0)
                    except Exception:
                        depth = 0
                    if depth > 0:
                        supported_bit_depths.append(depth)
                out.append(
                    {
                        "name": name,
                        "device_id": dev_id,
                        "supported_formats": supported_formats,
                        "supported_bit_depths": supported_bit_depths,
                    }
                )
            return out
        except Exception:
            logger.exception("Rust audio core list_devices failed")
            return None
        finally:
            if raw_ptr:
                try:
                    with self._call_lock:
                        if not self._closed:
                            self.lib.rac_free_string(raw_ptr)
                except Exception:
                    pass

    def get_last_error(self):
        """Return the last GStreamer error string from the Rust engine, or empty string."""
        if (not self.available) or self._closed:
            return ""
        fn = getattr(self.lib, "rac_get_last_error", None)
        if fn is None:
            return ""
        raw_ptr = None
        try:
            with self._call_lock:
                if self._closed or not self.handle:
                    return ""
                raw_ptr = fn(self.handle)
            if not raw_ptr:
                return ""
            raw = ctypes.cast(raw_ptr, ctypes.c_char_p).value
            return (raw or b"").decode("utf-8", "replace")
        except Exception:
            return ""
        finally:
            if raw_ptr:
                try:
                    with self._call_lock:
                        if not self._closed:
                            self.lib.rac_free_string(ctypes.c_void_p(raw_ptr))
                except Exception:
                    pass

    def get_spectrum_frame(self):
        if (not self.available) or self._closed:
            return None
        with self._call_lock:
            if self._closed or not self.handle:
                return None
            try:
                max_bands = 128
                buf = (ctypes.c_float * max_bands)()
                out_len = ctypes.c_int(0)
                out_pos = ctypes.c_double(0.0)
                out_seq = ctypes.c_uint64(0)
                rc = int(
                    self.lib.rac_get_spectrum_frame(
                        self.handle,
                        buf,
                        max_bands,
                        ctypes.byref(out_len),
                        ctypes.byref(out_pos),
                        ctypes.byref(out_seq),
                    )
                )
                if rc != 0:
                    return None
                n = max(0, int(out_len.value))
                if n <= 0:
                    return (int(out_seq.value), float(out_pos.value), [])
                vals = [float(buf[i]) for i in range(n)]
                return (int(out_seq.value), float(out_pos.value), vals)
            except Exception:
                return None

    def get_spectrum_frames_since(self, since_seq, max_frames=12, max_bands=128):
        if (not self.available) or self._closed:
            return []
        with self._call_lock:
            if self._closed or not self.handle:
                return []
            try:
                mf = max(1, min(int(max_frames), 256))
                mb = max(1, min(int(max_bands), 128))
                cache_key = (mf, mb)
                cache = self._spectrum_batch_cache.get(cache_key)
                if cache is None:
                    cache = {
                        "vals": (ctypes.c_float * (mf * mb))(),
                        "out_frames": ctypes.c_int(0),
                        "out_lens": (ctypes.c_int * mf)(),
                        "out_pos": (ctypes.c_double * mf)(),
                        "out_seq": (ctypes.c_uint64 * mf)(),
                    }
                    self._spectrum_batch_cache[cache_key] = cache
                vals = cache["vals"]
                out_frames = cache["out_frames"]
                out_lens = cache["out_lens"]
                out_pos = cache["out_pos"]
                out_seq = cache["out_seq"]
                out_frames.value = 0
                rc = int(
                    self.lib.rac_get_spectrum_frames_since(
                        self.handle,
                        ctypes.c_uint64(max(0, int(since_seq))),
                        vals,
                        mf,
                        mb,
                        ctypes.byref(out_frames),
                        out_lens,
                        out_pos,
                        out_seq,
                    )
                )
                if rc != 0:
                    return []
                nframes = max(0, min(int(out_frames.value), mf))
                frames = []
                for i in range(nframes):
                    ln = max(0, min(int(out_lens[i]), mb))
                    base = i * mb
                    frames.append(
                        (
                            int(out_seq[i]),
                            float(out_pos[i]),
                            [float(vals[base + j]) for j in range(ln)],
                        )
                    )
                return frames
            except Exception:
                return []

    def set_spectrum_enabled(self, enabled):
        if (not self.available) or self.handle is None or self.lib is None:
            return False
        try:
            fn = getattr(self.lib, "rac_set_spectrum_enabled", None)
            if fn is None:
                return False
            rc = int(fn(self.handle, 1 if enabled else 0))
            return rc == 0
        except Exception:
            return False


class RustAudioPlayerAdapter:
    """
    Phase-1 adapter: keeps existing Python AudioPlayer behavior, while
    mirroring core transport state into Rust audio core for progressive migration.
    """
    # Keywords that unambiguously indicate a physical device disconnect.
    # Note: "alsa" is intentionally NOT here — the GStreamer element name
    # "rust-alsa-sink" contains "alsa" and would cause false positives.
    # ALSA-specific disconnect detection is handled in _classify_rust_error.
    _ERR_DEVICE_KEYS = (
        "disconnected",
        "no such device",
        "device has been disconnected",
        "pulseaudio",
        "pipewire",
        "outputting to audio device",
    )
    # Additional ALSA-specific keywords that, combined with "alsa" in the
    # error text, indicate a real hardware problem (not just a sink name).
    _ERR_ALSA_FAULT_KEYS = (
        "cannot open",
        "no such device",
        "device or resource busy",
        "input/output error",
        "broken pipe",
        "not available",
        "unavailable",
    )
    _ERR_NETWORK_KEYS = ("timeout", "timed out", "network", "connection", "dns", "tls", "ssl")
    _ERR_CODEC_KEYS = ("decode", "decoder", "codec", "not-negotiated", "caps", "demux", "parser")

    def _ensure_pipewire_pro_audio_profile(self, device_id):
        """
        Ask Rust core to switch matching card profile to pro-audio.
        Keep retries to absorb transient session-manager delays.
        """
        try:
            dev = str(device_id or "").strip()
            if not dev:
                return False
            last_rc = -1
            for attempt in range(1, 4):
                rc_rust = int(self._rust.set_pipewire_pro_audio(dev))
                last_rc = rc_rust
                if rc_rust == 0:
                    logger.info(
                        "PipeWire pro-audio profile set via Rust API: device=%s attempt=%d",
                        dev,
                        attempt,
                    )
                    return True
                time.sleep(0.12)
            logger.warning(
                "Failed to set PipeWire pro-audio profile via Rust API: device=%s rc=%s",
                dev,
                last_rc,
            )
            return False
        except Exception:
            logger.debug("PipeWire pro-audio profile apply failed", exc_info=True)
            return False

    def ensure_pipewire_pro_audio(self):
        drv, dev = self._effective_output_selection()
        if str(drv or "") != "PipeWire":
            return False
        return self._ensure_pipewire_pro_audio_profile(dev)

    @staticmethod
    def _runtime_snapshot_log_signature(snap):
        pw = snap.get("pipewire", {}) if isinstance(snap, dict) else {}
        out = snap.get("output", {}) if isinstance(snap, dict) else {}
        mmap = snap.get("mmap_thread", {}) if isinstance(snap, dict) else {}
        src = snap.get("source", {}) if isinstance(snap, dict) else {}

        def _rounded_ms(value):
            try:
                return round(float(value), 3)
            except Exception:
                return None

        return (
            (pw.get("force_rate") if isinstance(pw, dict) else None),
            _rounded_ms(pw.get("latency_ms") if isinstance(pw, dict) else None),
            (out.get("session_rate") if isinstance(out, dict) else None),
            (out.get("session_depth") if isinstance(out, dict) else None),
            (out.get("hardware_rate") if isinstance(out, dict) else None),
            (out.get("hardware_depth") if isinstance(out, dict) else None),
            (mmap.get("running") if isinstance(mmap, dict) else None),
            (mmap.get("realtime_enabled") if isinstance(mmap, dict) else None),
            (mmap.get("realtime_priority") if isinstance(mmap, dict) else None),
            (mmap.get("memlock_enabled") if isinstance(mmap, dict) else None),
            (mmap.get("memlock_mode") if isinstance(mmap, dict) else None),
            (mmap.get("device_resets") if isinstance(mmap, dict) else None),
            (src.get("rate") if isinstance(src, dict) else None),
            (src.get("depth") if isinstance(src, dict) else None),
            (src.get("codec") if isinstance(src, dict) else None),
        )

    def _read_runtime_snapshot(self):
        try:
            snap = self._rust.get_runtime_snapshot()
            if isinstance(snap, dict):
                try:
                    if logger.isEnabledFor(logging.DEBUG):
                        sig = self._runtime_snapshot_log_signature(snap)
                        if sig != getattr(self, "_runtime_snapshot_log_sig", None):
                            self._runtime_snapshot_log_sig = sig
                            pw = snap.get("pipewire", {}) if isinstance(snap, dict) else {}
                            out = snap.get("output", {}) if isinstance(snap, dict) else {}
                            mmap = snap.get("mmap_thread", {}) if isinstance(snap, dict) else {}
                            src = snap.get("source", {}) if isinstance(snap, dict) else {}
                            logger.debug(
                                "Rust runtime snapshot: pw(force=%s latency_ms=%s) out(session=%s/%s hw=%s/%s) mmap(rt=%s/%s memlock=%s/%s resets=%s) src(rate=%s depth=%s codec=%s)",
                                (pw.get("force_rate") if isinstance(pw, dict) else None),
                                (pw.get("latency_ms") if isinstance(pw, dict) else None),
                                (out.get("session_rate") if isinstance(out, dict) else None),
                                (out.get("session_depth") if isinstance(out, dict) else None),
                                (out.get("hardware_rate") if isinstance(out, dict) else None),
                                (out.get("hardware_depth") if isinstance(out, dict) else None),
                                (mmap.get("realtime_enabled") if isinstance(mmap, dict) else None),
                                (mmap.get("realtime_priority") if isinstance(mmap, dict) else None),
                                (mmap.get("memlock_enabled") if isinstance(mmap, dict) else None),
                                (mmap.get("memlock_mode") if isinstance(mmap, dict) else None),
                                (mmap.get("device_resets") if isinstance(mmap, dict) else None),
                                (src.get("rate") if isinstance(src, dict) else None),
                                (src.get("depth") if isinstance(src, dict) else None),
                                (src.get("codec") if isinstance(src, dict) else None),
                            )
                except Exception:
                    pass
                return snap
        except Exception:
            pass
        return {}

    def _read_pipewire_clock_metadata(self):
        # Use Rust C API snapshot only (no command-line dependency).
        snap = self._read_runtime_snapshot()
        try:
            pw = snap.get("pipewire", {}) if isinstance(snap, dict) else {}
            if isinstance(pw, dict) and (pw.get("force_rate") is not None or pw.get("allowed_rates_raw")):
                return {
                    "force_rate": int(pw.get("force_rate", 0) or 0),
                    "allowed_rates_raw": str(pw.get("allowed_rates_raw", "") or ""),
                }
        except Exception:
            pass
        return {}

    @staticmethod
    def _parse_allowed_rates(raw):
        text = str(raw or "")
        if not text:
            return set()
        nums = set()
        for m in re.findall(r"\d+", text):
            try:
                nums.add(int(m))
            except Exception:
                pass
        return nums

    def _wait_pipewire_metadata(self, check_fn, timeout_s=0.45, interval_s=0.05):
        deadline = time.monotonic() + max(0.05, float(timeout_s or 0.45))
        while True:
            meta = self._read_pipewire_clock_metadata()
            ok = False
            try:
                ok = bool(check_fn(meta))
            except Exception:
                ok = False
            if ok:
                return meta, True
            if time.monotonic() >= deadline:
                return meta, False
            time.sleep(max(0.01, float(interval_s or 0.05)))

    def _release_pipewire_clock_override(self, reason="idle"):
        """
        Release global PipeWire force-rate so other apps can negotiate freely.
        """
        try:
            driver = str(getattr(self, "current_driver", "") or "")
            if driver != "PipeWire":
                return
            if bool(getattr(self, "exclusive_lock_mode", False)):
                return
            # Keep allowed-rates but release force-rate lock.
            rc = self._rust.set_pipewire_clock_rate(0)
            if rc != 0:
                logger.warning("PipeWire force-rate release failed rc=%s (reason=%s)", rc, reason)
            meta, released_ok = self._wait_pipewire_metadata(
                lambda m: int(m.get("force_rate", 0) or 0) == 0,
                timeout_s=1.4,
                interval_s=0.06,
            )
            if not released_ok:
                effective = int(meta.get("force_rate", 0) or 0)
                logger.warning(
                    "PipeWire force-rate release verify failed (reason=%s): c_api_rc=%s observed=%s",
                    reason,
                    rc,
                    effective,
                )
                return
            self._pw_target_rate_hz = 0
            logger.info("PipeWire force-rate released (reason=%s)", reason)
        except Exception:
            logger.debug("PipeWire force-rate release skipped", exc_info=True)

    def _resolve_pipewire_target_after_profile_switch(self, device_id):
        """
        After profile switch (e.g. analog-stereo -> pro-audio), node names may change.
        Resolve a fresh, existing target-object for the same card base.
        """
        try:
            dev = str(device_id or "").strip()
            devices = self._rust.list_devices("PipeWire") or []
            ids = [str(d.get("device_id") or "").strip() for d in devices]

            # Handle pwcardprofile: format (e.g. pwcardprofile:alsa_card.usb-FOO|analog-stereo)
            if dev.startswith("pwcardprofile:"):
                card_part = dev[len("pwcardprofile:"):]
                card_name = card_part.split("|")[0]  # e.g. alsa_card.usb-MUSILAND_Monitor_09-00
                alsa_base = card_name.replace("alsa_card.", "")  # e.g. usb-MUSILAND_Monitor_09-00
                node_prefix = "alsa_output." + alsa_base + "."
                matching = [i for i in ids if i.startswith(node_prefix)]
                if not matching:
                    return device_id
                for cand in matching:
                    if ".pro-" in cand:
                        return cand
                return matching[0]

            if not dev.startswith("alsa_output.") or "." not in dev:
                return device_id
            base, _old_profile = dev.rsplit(".", 1)
            same_base = [i for i in ids if i.startswith(base + ".")]
            if not same_base:
                return device_id
            # Prefer pro-* nodes after profile change.
            for cand in same_base:
                if ".pro-" in cand:
                    return cand
            # Else keep exact if still present.
            if dev in same_base:
                return dev
            # Fallback to first node for the same card base.
            return same_base[0]
        except Exception:
            logger.debug("PipeWire target resolve after profile switch failed", exc_info=True)
            return device_id

    def _should_manage_pipewire_rate(self):
        if not self._rust.available:
            return False
        driver = str(getattr(self, "current_driver", "") or "")
        if driver != "PipeWire":
            return False
        if not bool(getattr(self, "active_rate_switch", False)):
            return False
        if bool(getattr(self, "exclusive_lock_mode", False)):
            return False
        return True

    def _maybe_enforce_pipewire_rate(self, current_rate_hz=0, reason="periodic"):
        if not self._should_manage_pipewire_rate():
            return
        target = int(self._pw_target_rate_hz or 0)
        if target <= 0:
            return
        now = time.monotonic()
        min_interval = max(1.0, float(self._pw_retry_backoff_s or 0.0))
        if (now - float(self._pw_last_enforce_ts or 0.0)) < min_interval:
            return
        cur = int(current_rate_hz or 0)
        if cur > 0 and abs(cur - target) <= 1:
            self._pw_retry_backoff_s = 0.0
            return
        rc = self._rust.set_pipewire_clock_rate(target)
        self._pw_last_enforce_ts = now
        if rc == 0:
            self._pw_retry_backoff_s = 0.0
            logger.info(
                "Rust PipeWire auto-correct applied (%s): target=%s current=%s",
                reason,
                target,
                cur or "unknown",
            )
        else:
            self._pw_retry_backoff_s = min(10.0, 2.0 if self._pw_retry_backoff_s <= 0 else (self._pw_retry_backoff_s * 1.7))
            logger.warning(
                "Rust PipeWire auto-correct failed rc=%s (%s): target=%s current=%s backoff=%.1fs",
                rc,
                reason,
                target,
                cur or "unknown",
                self._pw_retry_backoff_s,
            )

    def _effective_output_selection(self):
        driver = (
            getattr(self, "current_driver", None)
            or getattr(self, "requested_driver", None)
        )
        device_id = (
            getattr(self, "current_device_id", None)
            or getattr(self, "requested_device_id", None)
        )
        return driver, device_id

    @staticmethod
    def _normalize_codec_label(raw):
        text = str(raw or "").strip()
        if not text:
            return ""
        # GStreamer tag strings may contain escaped separators/spaces.
        cleaned = text.replace("\\", " ").replace("_", " ")
        lowered = cleaned.lower()
        if "flac" in lowered:
            return "FLAC"
        if "aac" in lowered:
            return "AAC"
        if "alac" in lowered:
            return "ALAC"
        if "mp3" in lowered or "mpeg" in lowered:
            return "MP3"
        if "opus" in lowered:
            return "Opus"
        if "vorbis" in lowered:
            return "Vorbis"
        return cleaned

    def __init__(self, on_eos_callback=None, on_tag_callback=None, on_spectrum_callback=None, on_viz_sync_offset_update=None):
        self._on_eos_callback = on_eos_callback
        self._on_tag_callback = on_tag_callback
        self._on_spectrum_callback = on_spectrum_callback
        self._rust = _RustAudioCore()
        # Rust-only transport policy.
        self.stream_info = {
            "codec": "-",
            "bitrate": 0,
            "rate": 0,
            "depth": 0,
            "fmt_str": "",
            "source_rate": 0,
            "source_depth": 0,
            "source_fmt_str": "",
            "output_rate": 0,
            "output_depth": 0,
            "output_fmt_str": "",
        }
        self.event_log = []
        self.bit_perfect_mode = False
        self.visual_sync_offset_ms = 0
        self.visual_sync_base_ms = 0
        self.visual_sync_lead_ms = 0
        self.visual_sync_auto_offset_ms = 0.0
        self.active_rate_switch = False
        self.exclusive_lock_mode = False
        self._alsa_reservation = None  # AlsaDeviceReservation when held
        self.alsa_buffer_time = 100000
        self.alsa_latency_time = 10000
        self.alsa_mmap_realtime_priority = 60
        self.output_state = "idle"
        self.output_error = None
        self.preferred_output_format = ""
        self.requested_driver = None
        self.requested_device_id = None
        self.current_driver = "Auto (Default)"
        self.current_device_id = None
        self._seek_hold_until = 0.0
        self._seek_target_s = None
        self._last_seek_issue_ts = 0.0
        self._last_seek_issue_target = None
        self._seek_flush_source = 0
        self._seek_coalesce_target = None
        self._last_seek_dispatch_ts = 0.0
        self._last_seek_dispatched_target = None
        self._seek_dispatch_lock = threading.RLock()
        self._cached_is_playing = False
        self._cached_pos_s = 0.0
        self._cached_dur_s = 0.0
        self._last_loaded_uri = ""
        self._last_cache_poll_ts = 0.0
        self._last_rust_error_msg = ""
        self._last_rust_error_ts = 0.0
        self._rust_error_repeat = 0
        self._rust_disconnect_recovering = False
        self._rust_pump_source = 0
        self._last_enum_signature_by_driver = {}
        self._last_rust_spectrum_seq = 0
        self._rust_spectrum_frames_seen = 0
        self._rust_last_play_ts = 0.0
        self._rust_last_spectrum_seen_ts = 0.0
        self._rust_last_spectrum_recover_ts = 0.0
        self._rust_spectrum_requested = False
        self._rust_spectrum_forced_off = False
        self._rust_spectrum_enabled = False
        self._viz_latency_cached_ms = 0.0
        self._viz_latency_smooth_ms = 0.0
        self._viz_msg_age_smooth_ms = 0.0
        self._viz_latency_last_probe_ts = 0.0
        self._viz_debug_last_ts = 0.0
        self._viz_epoch = 0
        self._viz_trace_enabled = str(os.getenv("HIRESTI_VIZ_TRACE", "0")).strip().lower() in ("1", "true", "yes", "on")
        self._viz_trace_enable_ts = 0.0
        self._viz_trace_last_tick_ts = 0.0
        self._viz_trace_last_frame_ts = 0.0
        self._viz_trace_tick_count = 0
        self._viz_diag_last_ts = 0.0
        self._viz_render_source = 0
        self._viz_spectrum_queue = deque(maxlen=1024)
        self._viz_last_render_frame = None
        self._rust_last_pump_ts = 0.0
        # When spectrum is disabled, keep Rust event polling lower to reduce CPU.
        # UI progress remains smooth due cached position refresh gate.
        self._rust_pump_idle_interval_playing_s = 0.08
        self._rust_pump_idle_interval_paused_s = 0.25
        # Extra lookback to ensure interpolation has both neighbors even when
        # spectrum frames arrive in coarse bursts.
        self._viz_interp_lookback_s = 0.06
        self._output_switch_lock = threading.RLock()
        self._output_switch_inflight = False
        self._output_switch_pending = None
        self._last_output_switch_sig = None
        self._last_output_switch_ts = 0.0
        self._output_switch_restore = None
        self._alsa_container_adapter_active = False
        self._alsa_container_adapter_format = ""
        self._alsa_container_adapter_diag_sig = ""
        self._pw_target_rate_hz = 0
        self._pw_allowed_rates_applied = False
        self._pw_last_enforce_ts = 0.0
        self._pw_last_probe_ts = 0.0
        self._pw_retry_backoff_s = 0.0
        self._pipewire_rate_blocked = False
        self._discoverer = None
        try:
            self._discoverer = GstPbutils.Discoverer.new(1 * Gst.SECOND)
        except Exception:
            self._discoverer = None
            logger.warning("Rust discoverer init failed; source pre-detect disabled")
        if self._rust.available:
            self._rust.set_event_callback(self._on_rust_event)
            try:
                # Start with spectrum processing disabled; UI tabs control it.
                self._rust.set_spectrum_enabled(False)
            except Exception:
                pass
            # Start with low-frequency pump while spectrum is disabled.
            self._restart_rust_pump_timer(120)
            # Render timer is enabled only when spectrum is on.
            self._viz_render_source = 0
        else:
            raise RuntimeError("Rust audio core is required but unavailable.")
        logger.info(
            "Audio engine path: RustAdapter (rust_core=%s, rust_transport=on, rust_single=on)",
            "on" if self._rust.available else "off",
        )
        logger.info("Rust single transport is enabled")

    def _restart_rust_pump_timer(self, interval_ms):
        try:
            target = max(8, int(interval_ms or 16))
        except Exception:
            target = 16
        if int(getattr(self, "_rust_pump_interval_ms", 0) or 0) == target and int(getattr(self, "_rust_pump_source", 0) or 0) != 0:
            return
        if int(getattr(self, "_rust_pump_source", 0) or 0):
            try:
                GLib.source_remove(self._rust_pump_source)
            except Exception:
                pass
            self._rust_pump_source = 0
        self._rust_pump_interval_ms = target
        self._rust_pump_source = GLib.timeout_add(target, self._pump_rust_events_tick)

    def _retune_idle_timers(self):
        if bool(getattr(self, "_rust_spectrum_enabled", False)):
            self._restart_rust_pump_timer(16)
            if int(getattr(self, "_viz_render_source", 0) or 0) == 0:
                self._viz_render_source = GLib.timeout_add(16, self._viz_render_tick)
            return
        # No spectrum: keep pump low-frequency and stop render loop completely.
        is_playing_cached = bool(getattr(self, "_cached_is_playing", False))
        self._restart_rust_pump_timer(200 if is_playing_cached else 400)
        if int(getattr(self, "_viz_render_source", 0) or 0):
            try:
                GLib.source_remove(self._viz_render_source)
            except Exception:
                pass
            self._viz_render_source = 0

    def _parse_rust_tag_event(self, msg):
        text = str(msg or "").strip()
        if not text:
            return {}
        fields = {}
        for token in text.split(";"):
            if "=" not in token:
                continue
            k, v = token.split("=", 1)
            key = str(k or "").strip().lower()
            val = str(v or "").strip()
            if key and val:
                fields[key] = val
        return fields

    def _apply_rust_stream_fields(self, fields):
        if not isinstance(fields, dict) or not fields:
            return
        info = dict(getattr(self, "stream_info", {}) or {})
        changed = False

        codec = self._normalize_codec_label(fields.get("codec", ""))
        if codec and info.get("codec") != codec:
            info["codec"] = codec
            changed = True

        bitrate = fields.get("bitrate")
        if bitrate is not None:
            try:
                br = int(float(bitrate))
            except Exception:
                br = 0
            if br >= 0 and int(info.get("bitrate", 0) or 0) != br:
                info["bitrate"] = br
                changed = True

        rate = fields.get("rate")
        if rate is not None:
            try:
                rv = int(float(rate))
            except Exception:
                rv = 0
            # Rust TAG rate/depth represent negotiated output/session format.
            # Keep source media fields (rate/depth/fmt_str) owned by stream metadata.
            if rv > 0 and int(info.get("output_rate", 0) or 0) != rv:
                info["output_rate"] = rv
                changed = True
            if rv > 0 and int(info.get("rate", 0) or 0) <= 0:
                info["rate"] = rv
                changed = True
            if rv > 0:
                # Event-driven correction: if output/sample rate drifts during playback.
                self._maybe_enforce_pipewire_rate(rv, reason="tag")

        depth = fields.get("depth")
        if depth is not None:
            try:
                dv = int(float(depth))
            except Exception:
                dv = 0
            if dv > 0 and int(info.get("output_depth", 0) or 0) != dv:
                info["output_depth"] = dv
                changed = True
            if dv > 0 and int(info.get("depth", 0) or 0) <= 0:
                info["depth"] = dv
                changed = True

        # source_rate / source_depth: parsed by Rust from the GStreamer TAG codec
        # text (e.g. "FLAC, 192000 Hz, 24-bit").  These reflect the original media
        # resolution and take precedence over the output container format (S32LE)
        # for display purposes.
        src_rate = fields.get("source_rate")
        if src_rate is not None:
            try:
                srv = int(float(src_rate))
            except Exception:
                srv = 0
            if srv > 0 and int(info.get("source_rate", 0) or 0) != srv:
                info["source_rate"] = srv
                if int(info.get("rate", 0) or 0) <= 0:
                    info["rate"] = srv
                changed = True

        src_depth = fields.get("source_depth")
        if src_depth is not None:
            try:
                sdv = int(float(src_depth))
            except Exception:
                sdv = 0
            if sdv > 0 and int(info.get("source_depth", 0) or 0) != sdv:
                info["source_depth"] = sdv
                if int(info.get("depth", 0) or 0) <= 0:
                    info["depth"] = sdv
                changed = True

        out_rate_v = int(info.get("output_rate", 0) or 0)
        out_depth_v = int(info.get("output_depth", 0) or 0)
        if out_rate_v > 0 and out_depth_v > 0:
            out_khz = f"{(out_rate_v / 1000.0):g}kHz"
            out_fmt = f"{out_khz} | {out_depth_v}-bit"
            if info.get("output_fmt_str") != out_fmt:
                info["output_fmt_str"] = out_fmt
                changed = True

        if not changed:
            return

        self.stream_info = info
        self._maybe_log_alsa_container_adapter_runtime()
        cb = getattr(self, "_on_tag_callback", None)
        if callable(cb):
            try:
                GLib.idle_add(cb, self.stream_info)
            except Exception:
                pass

    def _read_active_alsa_hw_details(self):
        device_id = str(getattr(self, "current_device_id", "") or "").strip()
        m = re.match(r"hw:(\d+)(?:,(\d+))?$", device_id)
        if not m:
            return {}
        card_idx = str(m.group(1))
        pcm_idx = str(m.group(2) or "0")
        proc_root = Path(getattr(self, "_alsa_proc_root", "/proc/asound"))
        pcm_dir = proc_root / f"card{card_idx}" / f"pcm{pcm_idx}p"
        if not pcm_dir.exists():
            return {}

        subdirs = sorted(pcm_dir.glob("sub*"))
        if not subdirs:
            return {}

        for subdir in subdirs:
            status_path = subdir / "status"
            hw_path = subdir / "hw_params"
            try:
                status_text = status_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                status_text = ""
            if status_text and ("RUNNING" not in status_text.upper()) and ("PREPARED" not in status_text.upper()):
                continue
            try:
                hw_text = hw_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            details = {}
            for raw in hw_text.splitlines():
                line = str(raw or "").strip()
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip().lower()
                val = val.strip()
                if key and val:
                    details[key] = val
            if details:
                return details
        return {}

    def _maybe_log_alsa_container_adapter_runtime(self):
        if not bool(getattr(self, "_alsa_container_adapter_active", False)):
            return
        if _driver_key(getattr(self, "current_driver", "")) != "alsa_auto":
            return
        if not bool(getattr(self, "exclusive_lock_mode", False)):
            return
        info = dict(getattr(self, "stream_info", {}) or {})
        source_depth = int(info.get("source_depth", 0) or info.get("depth", 0) or 0)
        hw = self._read_active_alsa_hw_details()
        hw_format = str(hw.get("format", "") or "").strip()
        hw_rate = str(hw.get("rate", "") or "").strip()
        access = str(hw.get("access", "") or "").strip()
        period_size = str(hw.get("period_size", "") or "").strip()
        buffer_size = str(hw.get("buffer_size", "") or "").strip()
        if source_depth <= 0 and not hw_format:
            return
        sig = "|".join([
            str(getattr(self, "_alsa_container_adapter_format", "") or ""),
            str(source_depth or 0),
            hw_format,
            hw_rate,
            access,
            period_size,
            buffer_size,
            str(getattr(self, "current_device_id", "") or ""),
        ])
        if sig == str(getattr(self, "_alsa_container_adapter_diag_sig", "") or ""):
            return
        self._alsa_container_adapter_diag_sig = sig
        logger.info(
            "ALSA exclusive container adapter runtime: device=%s adapter_format=%s source_depth=%s hw_format=%s hw_rate=%s access=%s period_size=%s buffer_size=%s",
            str(getattr(self, "current_device_id", "") or "default"),
            str(getattr(self, "_alsa_container_adapter_format", "") or "unknown"),
            source_depth if source_depth > 0 else "unknown",
            hw_format or "unknown",
            hw_rate or "unknown",
            access or "unknown",
            period_size or "unknown",
            buffer_size or "unknown",
        )

    def _maybe_pre_adjust_pipewire_rate(self, uri):
        """
        Keep parity with Python engine behavior:
        when bit-perfect is enabled without exclusive mode on PipeWire,
        request server clock rate to follow source sample-rate before playback.
        """
        self._pipewire_rate_blocked = False
        try:
            driver = str(getattr(self, "current_driver", "") or "")
            if driver != "PipeWire":
                logger.info("Rust transport: pre-adjust skipped (driver=%s)", driver or "unknown")
                return True
            if not bool(getattr(self, "active_rate_switch", False)):
                logger.info("Rust transport: pre-adjust skipped (active_rate_switch=off)")
                return True
            if bool(getattr(self, "exclusive_lock_mode", False)):
                logger.info("Rust transport: pre-adjust skipped (exclusive_lock=on)")
                return True
            if self._discoverer is None:
                return True
            target_rate = 0
            info = self._discoverer.discover_uri(uri)
            audio_streams = info.get_audio_streams() if info else []
            if audio_streams:
                a0 = audio_streams[0]
                target_rate = int(a0.get_sample_rate() or 0)
                src_depth = 0
                try:
                    get_depth = getattr(a0, "get_depth", None)
                    if callable(get_depth):
                        src_depth = int(get_depth() or 0)
                except Exception:
                    src_depth = 0
                try:
                    sinfo = dict(getattr(self, "stream_info", {}) or {})
                    changed = False
                    if target_rate > 0 and int(sinfo.get("source_rate", 0) or 0) != target_rate:
                        sinfo["source_rate"] = target_rate
                        changed = True
                    if src_depth > 0 and int(sinfo.get("source_depth", 0) or 0) != src_depth:
                        sinfo["source_depth"] = src_depth
                        changed = True
                    if target_rate > 0:
                        # Keep base fields as source metadata (UI compatibility).
                        if int(sinfo.get("rate", 0) or 0) != target_rate:
                            sinfo["rate"] = target_rate
                            changed = True
                    if src_depth > 0:
                        if int(sinfo.get("depth", 0) or 0) != src_depth:
                            sinfo["depth"] = src_depth
                            changed = True
                    if target_rate > 0 and src_depth > 0:
                        src_fmt = f"{(target_rate / 1000.0):g}kHz | {src_depth}-bit"
                        if sinfo.get("source_fmt_str") != src_fmt:
                            sinfo["source_fmt_str"] = src_fmt
                            changed = True
                        if sinfo.get("fmt_str") != src_fmt:
                            sinfo["fmt_str"] = src_fmt
                            changed = True
                    if changed:
                        self.stream_info = sinfo
                        cb = getattr(self, "_on_tag_callback", None)
                        if callable(cb):
                            try:
                                GLib.idle_add(cb, self.stream_info)
                            except Exception:
                                pass
                except Exception:
                    pass
            if target_rate > 0:
                allow_csv = "44100,48000,88200,96000,176400,192000"
                allow_required = {44100, 48000, 88200, 96000, 176400, 192000}
                rc_clear = self._rust.set_pipewire_clock_rate(0)
                logger.info("Rust transport: PipeWire clock.force-rate clear via C API rc=%s", rc_clear)
                if rc_clear != 0:
                    logger.warning("Rust transport: PipeWire clock.force-rate clear failed rc=%s", rc_clear)
                rc_allow = self._rust.set_pipewire_allowed_rates(allow_csv)
                if rc_allow != 0:
                    logger.warning("Rust transport: PipeWire clock.allowed-rates set failed rc=%s", rc_allow)
                else:
                    logger.info("Rust transport: PipeWire clock.allowed-rates set via C API: %s", allow_csv)
                meta_allow, allow_ok = self._wait_pipewire_metadata(
                    lambda m: allow_required.issubset(self._parse_allowed_rates(m.get("allowed_rates_raw"))),
                    timeout_s=1.2,
                    interval_s=0.06,
                )
                allowed_now = self._parse_allowed_rates(meta_allow.get("allowed_rates_raw"))
                if not allow_required.issubset(allowed_now):
                    logger.warning(
                        "PipeWire allowed-rates mismatch after C API write: got=%s",
                        meta_allow.get("allowed_rates_raw", "unknown"),
                    )
                self._pw_allowed_rates_applied = allow_required.issubset(allowed_now)
                logger.info(
                    "PipeWire allowed-rates verify: ok=%s values=%s waited=%s",
                    self._pw_allowed_rates_applied,
                    meta_allow.get("allowed_rates_raw", "unknown"),
                    allow_ok,
                )
                self._pw_target_rate_hz = target_rate
                rc = self._rust.set_pipewire_clock_rate(target_rate)
                if rc == 0:
                    self._pw_last_enforce_ts = time.monotonic()
                    self._pw_retry_backoff_s = 0.0
                    logger.info("Rust transport: PipeWire clock.force-rate set via C API: %s", target_rate)
                    # Verify effective settings via Rust C API runtime snapshot.
                    # Metadata updates can lag slightly under load, so retry C API
                    # writes/reads for a short window before declaring mismatch.
                    meta = {}
                    effective = 0
                    force_ok = False
                    for attempt in range(1, 6):
                        meta, force_ok = self._wait_pipewire_metadata(
                            lambda m: int(m.get("force_rate", 0) or 0) == int(target_rate),
                            timeout_s=1.0 if attempt == 1 else 0.6,
                            interval_s=0.06,
                        )
                        effective = int(meta.get("force_rate", 0) or 0)
                        if effective == int(target_rate):
                            break
                        rc_retry = self._rust.set_pipewire_clock_rate(target_rate)
                        logger.warning(
                            "PipeWire force-rate not visible yet (attempt=%s/5 want=%s got=%s), retry C API rc=%s",
                            attempt,
                            int(target_rate),
                            effective,
                            rc_retry,
                        )
                        time.sleep(0.08)
                    if effective != int(target_rate):
                        self._pipewire_rate_blocked = True
                        self.output_state = "error"
                        self.output_error = (
                            f"PipeWire sample-rate is locked at {effective} Hz, requested {int(target_rate)} Hz. "
                            "Stop other audio apps and retry."
                        )
                        logger.error(
                            "Rust transport: blocking playback due to PipeWire rate mismatch (effective=%s target=%s)",
                            effective,
                            int(target_rate),
                        )
                        return False
                    else:
                        logger.info(
                            "PipeWire metadata verified: force_rate=%s allowed=%s waited=%s",
                            meta.get("force_rate", "unknown"),
                            meta.get("allowed_rates_raw", "unknown"),
                            force_ok,
                        )
                    # Force renegotiation of sink/graph so new clock target can take effect
                    # before playback starts.
                    try:
                        cur_driver, cur_device = self._effective_output_selection()
                        cur_driver = str(cur_driver or "")
                        if cur_driver == "PipeWire":
                            target_buffer = int(getattr(self, "alsa_buffer_time", 100000) or 100000)
                            target_latency = int(getattr(self, "alsa_latency_time", 10000) or 10000)
                            exclusive = bool(getattr(self, "exclusive_lock_mode", False))
                            rc_rebind = self._rust.set_output(
                                cur_driver,
                                cur_device,
                                buffer_us=target_buffer,
                                latency_us=target_latency,
                                exclusive=exclusive,
                            )
                            logger.info(
                                "Rust transport: PipeWire sink rebind after rate set rc=%s driver=%s device=%s",
                                rc_rebind,
                                cur_driver,
                                str(cur_device or "default"),
                            )
                    except Exception:
                        logger.debug("Rust transport: PipeWire sink rebind after rate set failed", exc_info=True)
                else:
                    logger.warning("Rust transport: PipeWire C API clock set failed rc=%s rate=%s", rc, target_rate)
                    self._pipewire_rate_blocked = True
                    self.output_state = "error"
                    self.output_error = (
                        f"Unable to switch PipeWire sample-rate to {int(target_rate)} Hz. "
                        "Stop other audio apps and retry."
                    )
                    return False
            else:
                self._pw_target_rate_hz = 0
            return True
        except Exception:
            logger.debug("Rust transport: pre-adjust PipeWire rate skipped", exc_info=True)
            return True

    def set_spectrum_enabled(self, enabled):
        self._rust_spectrum_requested = bool(enabled)
        effective_enabled = bool(enabled)
        prev_enabled = bool(getattr(self, "_rust_spectrum_enabled", False))
        self._rust_spectrum_enabled = effective_enabled
        if self._rust.available:
            try:
                self._rust.set_spectrum_enabled(self._rust_spectrum_enabled)
            except Exception:
                pass
        if prev_enabled != self._rust_spectrum_enabled:
            logger.info("Rust spectrum processing: %s", "ON" if self._rust_spectrum_enabled else "OFF")
            self._retune_idle_timers()
        if not self._rust_spectrum_enabled:
            self._viz_spectrum_queue.clear()
            self._viz_last_render_frame = None
        if self._viz_trace_enabled:
            self._viz_trace_enable_ts = time.monotonic()
            logger.info("VIZ TRACE rust-set-spectrum-enabled: %s", bool(self._rust_spectrum_enabled))
        logger.info(
            "Spectrum path: rust=%s python=%s (rust-only)",
            bool(self._rust_spectrum_enabled),
            False,
        )
        return True

    def _apply_driver_spectrum_policy(self, driver):
        if bool(getattr(self, "_rust_spectrum_forced_off", False)):
            self._rust_spectrum_forced_off = False
            logger.info("Rust spectrum driver policy: restored")
        self.set_spectrum_enabled(bool(getattr(self, "_rust_spectrum_requested", False)))

    def _classify_rust_error(self, text):
        t = str(text or "").lower()
        if any(k in t for k in self._ERR_DEVICE_KEYS):
            return "device"
        # "alsa" alone matches the GStreamer element name "rust-alsa-sink" and
        # produces false positives.  Only classify as device error when the
        # message also contains a specific hardware fault keyword.
        if "alsa" in t and any(k in t for k in self._ERR_ALSA_FAULT_KEYS):
            return "device"
        if any(k in t for k in self._ERR_NETWORK_KEYS):
            return "network"
        if any(k in t for k in self._ERR_CODEC_KEYS):
            return "codec"
        return "unknown"

    def _apply_rust_error_policy(self, category, err_text):
        if category == "device":
            # In exclusive ALSA mode, errors from the sink (clock drift, underruns,
            # slave-method=none conflicts) must NOT trigger the reconnect recovery
            # loop — that would call set_output repeatedly, creating an infinite cycle.
            # Release the reservation and show the error; user can recover manually.
            if bool(getattr(self, "exclusive_lock_mode", False)) and \
                    _driver_key(getattr(self, "current_driver", "")) == "alsa_auto":
                self._release_alsa_reservation()
                self.output_state = "error"
                self.output_error = str(err_text or "ALSA exclusive mode error")
                return
            self.output_state = "fallback"
            self.output_error = "USB audio device disconnected; switching output"
            if not self._rust_disconnect_recovering:
                self._rust_disconnect_recovering = True
                GLib.idle_add(self._recover_after_disconnect)
            return
        if category == "network":
            self.output_state = "error"
            self.output_error = "Network stream error"
            return
        if category == "codec":
            self.output_state = "error"
            self.output_error = "Decoder/codec error"
            self._cached_is_playing = False
            try:
                self._rust.stop()
            except Exception:
                pass
            return
        self.output_state = "error"
        self.output_error = str(err_text or "rust-audio-error")

    def _mark_transport_error(self, op, rc):
        self.output_state = "error"
        detail = ""
        try:
            detail = (self._rust.get_last_error() or "").strip()
        except Exception:
            pass
        self.output_error = f"rust {op} rc={rc}" + (f": {detail}" if detail else "")
        try:
            self.event_log.append(f"Rust transport failure: op={op} rc={rc}" + (f": {detail}" if detail else ""))
            if len(self.event_log) > 50:
                self.event_log[:] = self.event_log[-50:]
        except Exception:
            pass
        logger.warning("Rust transport failure: op=%s rc=%s", op, rc)

    def set_alsa_latency(self, buffer_ms, latency_ms):
        self.alsa_buffer_time = int(float(buffer_ms or 0.0) * 1000.0)
        self.alsa_latency_time = int(float(latency_ms or 0.0) * 1000.0)
        return True

    def set_alsa_mmap_realtime_priority(self, priority):
        try:
            target_priority = int(priority or 0)
        except Exception:
            target_priority = 0
        target_priority = max(0, target_priority)
        self.alsa_mmap_realtime_priority = target_priority
        rc = -2
        try:
            rc = int(self._rust.set_mmap_realtime_priority(target_priority))
        except Exception:
            logger.debug("Rust ALSA mmap realtime priority setter failed", exc_info=True)
        if rc == 0:
            logger.info(
                "ALSA mmap realtime priority set: %s",
                target_priority if target_priority > 0 else "off",
            )
        elif rc == -2:
            logger.debug("Rust ALSA mmap realtime priority setter unavailable")
        elif rc < 0:
            logger.warning(
                "Rust ALSA mmap realtime priority apply failed rc=%s priority=%s",
                rc,
                target_priority,
            )
        return True

    def toggle_bit_perfect(self, enabled, exclusive_lock=False):
        old_exclusive = bool(getattr(self, "exclusive_lock_mode", False))
        self.bit_perfect_mode = bool(enabled)
        self.exclusive_lock_mode = bool(exclusive_lock)
        self.active_rate_switch = bool(enabled) and (not bool(exclusive_lock))
        if old_exclusive and not exclusive_lock:
            self._release_alsa_reservation()
        return True

    def _release_alsa_reservation(self):
        res = getattr(self, "_alsa_reservation", None)
        if res is None:
            return
        self._alsa_reservation = None
        threading.Thread(target=res.release, daemon=True).start()

    def _start_alsa_reservation_async(self, driver, device_id, card_num):
        """Acquire D-Bus device reservation in background, then retry set_output."""
        from services.alsa_reserve import AlsaDeviceReservation

        res = AlsaDeviceReservation(card_num)
        self._alsa_reservation = res

        def _thread():
            ok = res.acquire()
            logger.info(
                "AlsaReserve: async acquisition result=%s card=%d", ok, card_num
            )
            if not ok:
                self._alsa_reservation = None
            def _retry_set_output_once():
                try:
                    self.set_output(driver, device_id)
                except Exception:
                    logger.exception(
                        "AlsaReserve: deferred output retry failed: driver=%s device=%s",
                        driver,
                        device_id,
                    )
                return False

            GLib.idle_add(_retry_set_output_once)

        threading.Thread(target=_thread, daemon=True).start()

    def set_eq_band(self, band_index, gain):
        # Rust engine path has no Python equalizer chain.
        return False

    def reset_eq(self):
        # Rust engine path has no Python equalizer chain.
        return False

    def get_drivers(self):
        return ["Auto (Default)", "PipeWire", DRIVER_ALSA_AUTO, DRIVER_ALSA_MMAP]

    def _on_rust_event(self, evt, msg):
        if evt == _RustAudioCore.EVENT_EOS:
            self._cached_is_playing = False
            self._release_pipewire_clock_override(reason="eos")
            if self._on_eos_callback is not None:
                GLib.idle_add(self._on_eos_callback)
        elif evt == _RustAudioCore.EVENT_ERROR:
            err_text = str(msg or "rust-audio-error")
            category = self._classify_rust_error(err_text)
            self._apply_rust_error_policy(category, err_text)
            now = time.monotonic()
            same = err_text == self._last_rust_error_msg
            if same and (now - self._last_rust_error_ts) < 1.0:
                self._rust_error_repeat += 1
            else:
                if self._rust_error_repeat > 0 and self._last_rust_error_msg:
                    logger.warning(
                        "Rust audio event error suppressed x%d: %s",
                        self._rust_error_repeat,
                        self._last_rust_error_msg,
                    )
                self._rust_error_repeat = 0
                logger.warning("Rust audio event error: %s", err_text)
                self._last_rust_error_msg = err_text
                self._last_rust_error_ts = now
            try:
                if not (same and (now - self._last_rust_error_ts) < 1.0):
                    self.event_log.append(f"Rust audio error [{category}]: {err_text}")
                if len(self.event_log) > 50:
                    self.event_log[:] = self.event_log[-50:]
            except Exception:
                pass
        elif evt == _RustAudioCore.EVENT_STATE:
            if msg and "output-switched" in msg:
                self.output_state = "active"
                self.output_error = None
            if msg:
                lmsg = msg.lower()
                if "container-adapter" in lmsg:
                    m = re.search(r"format=([A-Za-z0-9_]+)", str(msg or ""))
                    self._alsa_container_adapter_active = True
                    self._alsa_container_adapter_format = str(m.group(1) if m else "")
                    self._alsa_container_adapter_diag_sig = ""
                    self._maybe_log_alsa_container_adapter_runtime()
                if "playing" in lmsg:
                    self._cached_is_playing = True
                elif "paused" in lmsg or "null" in lmsg or "ready" in lmsg:
                    self._cached_is_playing = False
                if (
                    ("output-switched" in lmsg)
                    or ("pipewire-sink" in lmsg)
                    or ("alsa-mmap thread-config" in lmsg)
                    or ("container-adapter" in lmsg)
                    or ("playing" in lmsg)
                    or ("paused" in lmsg)
                    or ("null" == lmsg)
                ):
                    logger.info("Rust audio event state: %s", msg or "(empty)")
                else:
                    logger.debug("Rust audio event state: %s", msg or "(empty)")
                try:
                    self._retune_idle_timers()
                except Exception:
                    pass
            else:
                logger.debug("Rust audio event state: %s", msg or "(empty)")
        elif evt == _RustAudioCore.EVENT_TAG:
            fields = self._parse_rust_tag_event(msg)
            if fields:
                self._apply_rust_stream_fields(fields)

    def _recover_after_disconnect(self):
        try:
            logger.warning("Rust audio disconnected detected")
            self.event_log.append("Rust audio disconnected: waiting for UI device refresh/rebind")
            if len(self.event_log) > 50:
                self.event_log[:] = self.event_log[-50:]
            try:
                self._rust.stop()
            except Exception:
                pass
            # Keep current driver selection; UI layer will refresh device list and
            # rebind to the first available device for that same driver.
            self.output_state = "fallback"
            if not self.output_error:
                self.output_error = "USB audio device disconnected"
        finally:
            self._rust_disconnect_recovering = False
        return False

    def _refresh_rust_cache(self, force=False):
        if not self._rust.available:
            return
        now = time.monotonic()
        if (not force) and (now - self._last_cache_poll_ts) < 0.10:
            return
        self._last_cache_poll_ts = now
        try:
            self._cached_is_playing = bool(self._rust.is_playing())
        except Exception:
            pass
        # Keep position/duration cache fresh for UI progress updates.
        try:
            p = float(self._rust.get_position() or 0.0)
            d = float(self._rust.get_duration() or 0.0)
            if p >= 0.0:
                self._cached_pos_s = p
            if d >= 0.0:
                self._cached_dur_s = d
        except Exception:
            pass

    def _reset_rust_visual_sync_state(self):
        self._viz_latency_cached_ms = 0.0
        self._viz_latency_smooth_ms = 0.0
        self._viz_msg_age_smooth_ms = 0.0
        self._viz_latency_last_probe_ts = 0.0
        # New track/seek route can restart spectrum sequence from 0.
        # Reset local cursor + queue so we don't stall on stale high seq.
        self._last_rust_spectrum_seq = 0
        try:
            self._viz_spectrum_queue.clear()
        except Exception:
            pass
        self._viz_last_render_frame = None
        self._rust_last_spectrum_seen_ts = 0.0
        self._viz_epoch += 1

    def _dispatch_rust_spectrum(self, magnitudes, pos_s, epoch):
        if int(epoch) != int(self._viz_epoch):
            return False
        try:
            if self._on_spectrum_callback is not None:
                self._on_spectrum_callback(magnitudes, pos_s)
        except Exception:
            pass
        return False

    def _enqueue_rust_spectrum(self, pos_s, vals):
        try:
            p = float(pos_s if pos_s is not None else -1.0)
        except Exception:
            p = -1.0
        if p < 0.0:
            return
        # Root-cause fix:
        # Render path assumes queue is monotonic by frame position.
        # After seek/track switch, Rust spectrum position can jump backward.
        # If old high-position frames stay at queue head, renderer keeps sampling
        # stale frames and appears "frozen". Reset queue on backward jumps.
        if self._viz_spectrum_queue:
            try:
                last_p = float(self._viz_spectrum_queue[-1][0])
            except Exception:
                last_p = p
            if p < (last_p - 0.08):
                self._viz_spectrum_queue.clear()
                self._last_rust_spectrum_seq = 0
                self._viz_last_render_frame = None
                logger.info(
                    "Rust spectrum timeline reset: backward jump detected (last=%.3fs new=%.3fs)",
                    last_p,
                    p,
                )
        self._viz_spectrum_queue.append((p, vals))
        # Keep only a few seconds of history.
        cur = float(self._cached_pos_s or 0.0)
        floor = max(0.0, cur - 4.0)
        while len(self._viz_spectrum_queue) > 4 and self._viz_spectrum_queue[0][0] < floor:
            self._viz_spectrum_queue.popleft()
        if self._viz_trace_enabled:
            now = time.monotonic()
            last = float(getattr(self, "_viz_diag_last_ts", 0.0) or 0.0)
            if (now - last) >= 1.0:
                cur_pos = float(self._cached_pos_s or 0.0)
                logger.info(
                    "VIZ TRACE enqueue: frame=%.3fs cur=%.3fs delta(cur-frame)=%.3fs q=%d",
                    p,
                    cur_pos,
                    cur_pos - p,
                    len(self._viz_spectrum_queue),
                )

    def _sample_spectrum_at_pos(self, target_pos_s):
        q = self._viz_spectrum_queue
        if not q:
            return None
        prev_item = None
        next_item = None
        for item in q:
            p = item[0]
            if p <= target_pos_s:
                prev_item = item
            elif p > target_pos_s:
                next_item = item
                break

        if prev_item is None:
            return list(q[0][1])
        if next_item is None:
            return list(prev_item[1])

        p0, f0 = prev_item
        p1, f1 = next_item
        if p1 <= p0:
            return list(f0)
        t = max(0.0, min(1.0, (target_pos_s - p0) / (p1 - p0)))
        n = min(len(f0), len(f1))
        if n <= 0:
            return None
        return [(f0[i] * (1.0 - t)) + (f1[i] * t) for i in range(n)]

    def _viz_render_tick(self):
        if not self._rust.available:
            self._viz_render_source = 0
            return False
        if self._on_spectrum_callback is None or (not bool(self._rust_spectrum_enabled)):
            return True
        try:
            self._refresh_rust_cache(force=True)
            cur_pos = float(self._cached_pos_s or 0.0)
            delay_ms = self._estimate_rust_visual_delay_ms(current_pos_s=cur_pos, msg_pos_s=None)
            target_pos = max(
                0.0,
                cur_pos - (float(delay_ms) / 1000.0) - float(getattr(self, "_viz_interp_lookback_s", 0.12)),
            )
            frame = self._sample_spectrum_at_pos(target_pos)
            if frame is None:
                return True
            if self._viz_trace_enabled:
                now = time.monotonic()
                if (now - float(getattr(self, "_viz_diag_last_ts", 0.0) or 0.0)) >= 1.0:
                    self._viz_diag_last_ts = now
                    latest_pos = -1.0
                    try:
                        if self._viz_spectrum_queue:
                            latest_pos = float(self._viz_spectrum_queue[-1][0])
                    except Exception:
                        latest_pos = -1.0
                    logger.info(
                        "VIZ TRACE align: cur=%.3fs target=%.3fs latest=%.3fs delta(cur-latest)=%.3fs delay=%.1fms q=%d",
                        cur_pos,
                        target_pos,
                        latest_pos,
                        (cur_pos - latest_pos) if latest_pos >= 0.0 else -1.0,
                        float(delay_ms),
                        len(self._viz_spectrum_queue),
                    )
            self._viz_last_render_frame = frame
            self._on_spectrum_callback(frame, target_pos)
        except Exception:
            pass
        return True

    def _estimate_rust_visual_delay_ms(self, current_pos_s=None, msg_pos_s=None):
        now = time.monotonic()
        if (now - self._viz_latency_last_probe_ts) >= 0.12:
            self._viz_latency_last_probe_ts = now
            try:
                lat_s = float(self.get_latency() or 0.0)
            except Exception:
                lat_s = 0.0
            self._viz_latency_cached_ms = max(0.0, min(lat_s * 1000.0, 1500.0))

        if self._viz_latency_smooth_ms <= 0.0:
            self._viz_latency_smooth_ms = self._viz_latency_cached_ms
        else:
            self._viz_latency_smooth_ms = (self._viz_latency_smooth_ms * 0.80) + (self._viz_latency_cached_ms * 0.20)

        if (
            msg_pos_s is not None
            and current_pos_s is not None
            and float(msg_pos_s) >= 0.0
            and float(current_pos_s) >= 0.0
        ):
            msg_age_ms = max(0.0, (float(current_pos_s) - float(msg_pos_s)) * 1000.0)
            if self._viz_msg_age_smooth_ms <= 0.0:
                self._viz_msg_age_smooth_ms = msg_age_ms
            else:
                self._viz_msg_age_smooth_ms = (self._viz_msg_age_smooth_ms * 0.85) + (msg_age_ms * 0.15)
            target_ms = ((float(msg_pos_s) + (self._viz_latency_smooth_ms / 1000.0) - float(current_pos_s)) * 1000.0)
        else:
            target_ms = max(0.0, self._viz_latency_smooth_ms - self._viz_msg_age_smooth_ms)

        learned_offset_ms = float(self.visual_sync_offset_ms or 0)
        base_ms = float(getattr(self, "visual_sync_base_ms", 0) or 0)
        lead_ms = float(getattr(self, "visual_sync_lead_ms", 0) or 0)
        total_ms = target_ms + base_ms + learned_offset_ms - lead_ms

        if logger.isEnabledFor(logging.DEBUG) and (now - self._viz_debug_last_ts) >= 1.0:
            self._viz_debug_last_ts = now
            logger.debug(
                "rust-viz-sync delay=%.1fms target=%.1fms lat=%.1fms msg_age=%.1fms off=%d cur=%.3fs msg=%.3fs",
                total_ms,
                target_ms,
                self._viz_latency_smooth_ms,
                self._viz_msg_age_smooth_ms,
                int(round(learned_offset_ms)),
                float(current_pos_s or 0.0),
                float(msg_pos_s or -1.0),
            )
        if self._viz_trace_enabled and (now - self._viz_debug_last_ts) >= 1.0:
            self._viz_debug_last_ts = now
            logger.info(
                "VIZ TRACE sync-delay: total=%.1fms target=%.1fms lat=%.1fms off=%.1fms(setting) lead=%.1f",
                total_ms,
                target_ms,
                self._viz_latency_smooth_ms,
                learned_offset_ms,
                lead_ms,
            )
        return int(max(0.0, min(total_ms, 2000.0)))

    def _pump_rust_events_tick(self):
        if not self._rust.available:
            self._rust_pump_source = 0
            return False
        now_tick = time.monotonic()
        if not bool(self._rust_spectrum_enabled):
            is_playing_cached = bool(getattr(self, "_cached_is_playing", False))
            min_interval = self._rust_pump_idle_interval_playing_s if is_playing_cached else self._rust_pump_idle_interval_paused_s
            last_pump = float(getattr(self, "_rust_last_pump_ts", 0.0) or 0.0)
            if last_pump > 0.0 and (now_tick - last_pump) < float(min_interval):
                return True
        self._rust_last_pump_ts = now_tick
        if self._viz_trace_enabled:
            if self._viz_trace_last_tick_ts > 0.0:
                tick_gap_ms = (now_tick - self._viz_trace_last_tick_ts) * 1000.0
                if tick_gap_ms >= 45.0:
                    logger.info("VIZ TRACE rust-pump-gap: %.1fms", tick_gap_ms)
            self._viz_trace_last_tick_ts = now_tick
        self._rust.pump_events()
        try:
            # Refresh position/duration cache first so visual delay estimate
            # doesn't start from stale position on first frames after open.
            self._refresh_rust_cache(force=False)

            frames = []
            if bool(self._rust_spectrum_enabled):
                frames = self._rust.get_spectrum_frames_since(self._last_rust_spectrum_seq, max_frames=48, max_bands=128)
            if self._viz_trace_enabled and bool(self._rust_spectrum_enabled):
                self._viz_trace_tick_count += 1
                # Log densely only right after enabling, then sparse.
                age_s = now_tick - float(self._viz_trace_enable_ts or 0.0)
                if (age_s <= 3.0 and self._viz_trace_tick_count <= 120) or (self._viz_trace_tick_count % 60 == 0):
                    logger.info(
                        "VIZ TRACE rust-batch: frames=%d enabled=%s age=%.2fs",
                        len(frames),
                        bool(self._rust_spectrum_enabled),
                        age_s,
                    )
            for seq, pos_s, vals in frames:
                if not vals:
                    continue
                # Pipeline restart / seek can reset spectrum sequence in Rust core.
                # Detect rollback and realign local cursor + queue to avoid stall.
                if int(seq) < int(self._last_rust_spectrum_seq):
                    self._last_rust_spectrum_seq = 0
                    try:
                        self._viz_spectrum_queue.clear()
                    except Exception:
                        pass
                self._last_rust_spectrum_seq = max(self._last_rust_spectrum_seq, seq)
                self._rust_spectrum_frames_seen += 1
                self._rust_last_spectrum_seen_ts = time.monotonic()
                if self._viz_trace_enabled and bool(self._rust_spectrum_enabled):
                    now_f = time.monotonic()
                    if self._viz_trace_last_frame_ts > 0.0:
                        fgap_ms = (now_f - self._viz_trace_last_frame_ts) * 1000.0
                        if fgap_ms >= 60.0:
                            logger.info("VIZ TRACE rust-frame-gap: %.1fms", fgap_ms)
                    self._viz_trace_last_frame_ts = now_f
                if self._rust_spectrum_frames_seen % 1800 == 0:
                    logger.debug("Rust spectrum frames delivered: %d", self._rust_spectrum_frames_seen)
                if bool(self._rust_spectrum_enabled):
                    self._enqueue_rust_spectrum(pos_s, vals)
            # Self-heal: if spectrum is enabled/playing but no frames arrive for a while
            # (often after seek/reset), re-sync from seq=0 once with cooldown.
            if bool(self._rust_spectrum_enabled) and (not frames):
                now_s = time.monotonic()
                last_seen = float(getattr(self, "_rust_last_spectrum_seen_ts", 0.0) or 0.0)
                last_recover = float(getattr(self, "_rust_last_spectrum_recover_ts", 0.0) or 0.0)
                playing = bool(getattr(self, "_cached_is_playing", False))
                if (
                    playing
                    and (now_s - last_seen) > 0.75
                    and (now_s - last_recover) > 1.5
                ):
                    self._rust_last_spectrum_recover_ts = now_s
                    self._last_rust_spectrum_seq = 0
                    try:
                        self._viz_spectrum_queue.clear()
                    except Exception:
                        pass
                    logger.info("Rust spectrum auto-resync: reset cursor after stall")
        except Exception:
            pass
        try:
            now = time.monotonic()
            if (now - float(self._pw_last_probe_ts or 0.0)) >= 3.0:
                self._pw_last_probe_ts = now
                if self.is_playing():
                    current_rate = int((getattr(self, "stream_info", {}) or {}).get("rate", 0) or 0)
                    self._maybe_enforce_pipewire_rate(current_rate, reason="periodic")
        except Exception:
            pass
        return True

    def cleanup(self):
        if self._rust_pump_source:
            GLib.source_remove(self._rust_pump_source)
            self._rust_pump_source = 0
        if self._viz_render_source:
            GLib.source_remove(self._viz_render_source)
            self._viz_render_source = 0
        if self._seek_flush_source:
            GLib.source_remove(self._seek_flush_source)
            self._seek_flush_source = 0
        try:
            self._release_pipewire_clock_override(reason="cleanup")
            self._release_alsa_reservation()
        finally:
            self._rust.close()

    def hint_source_format(self, bit_depth, sample_rate):
        """Store source format from the TIDAL API to inject on next load().

        GStreamer TAG messages for FLAC do not carry Hz/-bit info, so the
        values must be supplied externally before load() is called.
        """
        self._pending_source_depth = int(bit_depth or 0)
        self._pending_source_rate = int(sample_rate or 0)

    def load(self, uri):
        try:
            self._last_loaded_uri = str(uri or "")
        except Exception:
            self._last_loaded_uri = ""
        logger.info(
            "RustAdapter.load: transport_active=%s driver=%s device=%s uri=%s",
            bool(self._rust.available),
            self._effective_output_selection()[0],
            self._effective_output_selection()[1],
            (str(uri or "")[:120] + "...") if len(str(uri or "")) > 120 else str(uri or ""),
        )
        self._reset_rust_visual_sync_state()
        ok = self._maybe_pre_adjust_pipewire_rate(uri)
        if ok is False:
            logger.warning("RustAdapter.load blocked: PipeWire rate pre-adjust failed")
            return
        prev = dict(getattr(self, "stream_info", {}) or {})
        pending_sr = int(getattr(self, "_pending_source_rate", 0) or 0)
        pending_sd = int(getattr(self, "_pending_source_depth", 0) or 0)
        self._pending_source_rate = 0
        self._pending_source_depth = 0
        self.stream_info = {
            "codec": "Loading...",
            "bitrate": 0,
            "rate": pending_sr or int(prev.get("rate", 0) or 0),
            "depth": pending_sd or int(prev.get("depth", 0) or 0),
            "fmt_str": prev.get("fmt_str", ""),
            "source_rate": pending_sr or 0,
            "source_depth": pending_sd or 0,
            "source_fmt_str": "",
            "output_rate": 0,
            "output_depth": 0,
            "output_fmt_str": "",
        }
        if callable(getattr(self, "_on_tag_callback", None)):
            try:
                GLib.idle_add(self._on_tag_callback, self.stream_info)
            except Exception:
                pass
        rc = self._rust.set_uri(uri)
        logger.info("RustAdapter.load: rust set_uri rc=%s", rc)
        if rc != 0:
            self._mark_transport_error("set_uri", rc)
        else:
            self.output_error = None
            self._cached_pos_s = 0.0
            self._cached_dur_s = 0.0
            self._cached_is_playing = False
    def set_uri(self, uri):
        try:
            self._last_loaded_uri = str(uri or "")
        except Exception:
            self._last_loaded_uri = ""
        logger.info(
            "RustAdapter.set_uri: transport_active=%s driver=%s device=%s uri=%s",
            bool(self._rust.available),
            self._effective_output_selection()[0],
            self._effective_output_selection()[1],
            (str(uri or "")[:120] + "...") if len(str(uri or "")) > 120 else str(uri or ""),
        )
        self._reset_rust_visual_sync_state()
        ok = self._maybe_pre_adjust_pipewire_rate(uri)
        if ok is False:
            logger.warning("RustAdapter.set_uri blocked: PipeWire rate pre-adjust failed")
            return
        prev = dict(getattr(self, "stream_info", {}) or {})
        self.stream_info = {
            "codec": "Loading...",
            "bitrate": 0,
            "rate": int(prev.get("rate", 0) or 0),
            "depth": int(prev.get("depth", 0) or 0),
            "fmt_str": prev.get("fmt_str", ""),
            "source_rate": int(prev.get("source_rate", 0) or 0),
            "source_depth": int(prev.get("source_depth", 0) or 0),
            "source_fmt_str": prev.get("source_fmt_str", ""),
            "output_rate": 0,
            "output_depth": 0,
            "output_fmt_str": "",
        }
        if callable(getattr(self, "_on_tag_callback", None)):
            try:
                GLib.idle_add(self._on_tag_callback, self.stream_info)
            except Exception:
                pass
        rc = self._rust.set_uri(uri)
        logger.info("RustAdapter.set_uri: rust set_uri rc=%s", rc)
        if rc != 0:
            self._mark_transport_error("set_uri", rc)
        else:
            self.output_error = None
            self._cached_pos_s = 0.0
            self._cached_dur_s = 0.0
            self._cached_is_playing = False
    def play(self):
        self._reset_rust_visual_sync_state()
        if bool(getattr(self, "_pipewire_rate_blocked", False)):
            try:
                logger.warning("RustAdapter.play: retrying PipeWire rate recovery from blocked state")
                self._release_pipewire_clock_override(reason="play-retry")
                uri = str(getattr(self, "_last_loaded_uri", "") or "")
                if not uri:
                    logger.warning("RustAdapter.play blocked: no cached URI to retry PipeWire pre-adjust")
                    return
                ok = self._maybe_pre_adjust_pipewire_rate(uri)
                if ok is False or bool(getattr(self, "_pipewire_rate_blocked", False)):
                    logger.warning("RustAdapter.play blocked: unresolved PipeWire sample-rate mismatch (retry failed)")
                    return
            except Exception:
                logger.debug("RustAdapter.play: PipeWire retry path failed", exc_info=True)
                return
        rc = self._rust.play()
        logger.info(
            "RustAdapter.play: rust play rc=%s driver=%s device=%s",
            rc,
            self._effective_output_selection()[0],
            self._effective_output_selection()[1],
        )
        if rc != 0:
            self._mark_transport_error("play", rc)
        else:
            self.output_state = "active"
            self.output_error = None
            self._cached_is_playing = True
            self._rust_last_play_ts = time.monotonic()
            self._refresh_rust_cache(force=True)
            self._retune_idle_timers()
    def pause(self):
        rc = self._rust.pause()
        logger.info("RustAdapter.pause: rust pause rc=%s", rc)
        if rc != 0:
            self._mark_transport_error("pause", rc)
        else:
            self.output_error = None
            self._cached_is_playing = False
            self._release_pipewire_clock_override(reason="pause")
            self._refresh_rust_cache(force=True)
            self._retune_idle_timers()
    def stop(self):
        self._reset_rust_visual_sync_state()
        rc = self._rust.stop()
        logger.info("RustAdapter.stop: rust stop rc=%s", rc)
        if rc != 0:
            self._mark_transport_error("stop", rc)
        else:
            self.output_error = None
            self._cached_is_playing = False
            self._cached_pos_s = 0.0
            self._release_pipewire_clock_override(reason="stop")
            self._refresh_rust_cache(force=True)
            self._retune_idle_timers()
    def seek(self, position_seconds):
        try:
            target_s = float(position_seconds or 0.0)
        except Exception:
            target_s = 0.0
        self._seek_target_s = max(0.0, target_s)
        now = time.monotonic()
        # Rust single path can be too sensitive to tiny cursor jitter near target.
        # Ignore rapid micro-seeks to avoid audible "tick" jumps while preserving
        # normal large scrubs.
        if self._last_seek_issue_target is not None:
            if (now - self._last_seek_issue_ts) < 1.0 and abs(self._seek_target_s - self._last_seek_issue_target) < 0.20:
                return
        self._last_seek_issue_ts = now
        self._last_seek_issue_target = self._seek_target_s
        self._seek_hold_until = time.monotonic() + 0.35
        self._cached_pos_s = self._seek_target_s
        # Seek can restart/rewire spectrum stream; reset visual cursor defensively.
        self._reset_rust_visual_sync_state()
        with self._seek_dispatch_lock:
            delta = now - float(self._last_seek_dispatch_ts or 0.0)
            if delta < 0.08:
                self._seek_coalesce_target = self._seek_target_s
                if self._seek_flush_source == 0:
                    wait_ms = max(1, int((0.08 - delta) * 1000))
                    self._seek_flush_source = GLib.timeout_add(wait_ms, self._flush_coalesced_seek)
                return

        self._dispatch_seek(self._seek_target_s)

    def _flush_coalesced_seek(self):
        target = None
        with self._seek_dispatch_lock:
            self._seek_flush_source = 0
            target = self._seek_coalesce_target
            self._seek_coalesce_target = None
        if target is None:
            return False
        self._dispatch_seek(target)
        return False

    def _dispatch_seek(self, target_seconds):
        try:
            target = float(target_seconds or 0.0)
        except Exception:
            target = 0.0
        now = time.monotonic()
        with self._seek_dispatch_lock:
            last_target = self._last_seek_dispatched_target
            if last_target is not None and abs(target - last_target) < 0.05 and (now - self._last_seek_dispatch_ts) < 0.25:
                return
            self._last_seek_dispatched_target = target
            self._last_seek_dispatch_ts = now

        rc = self._rust.seek(target)
        if rc != 0:
            self._mark_transport_error("seek", rc)
        else:
            self.output_error = None
            self._refresh_rust_cache(force=True)
    def set_volume(self, vol):
        rc = self._rust.set_volume(vol)
        if rc != 0:
            self._mark_transport_error("set_volume", rc)
        else:
            self.output_error = None

    def set_output(self, driver, device_id=None):
        req_driver = driver
        req_device = device_id
        now = time.monotonic()
        req_sig = (str(req_driver or ""), str(req_device or ""))
        with self._output_switch_lock:
            if (
                self._last_output_switch_sig == req_sig
                and (now - float(self._last_output_switch_ts or 0.0)) < 0.8
            ):
                return True
            if self._output_switch_inflight:
                self._output_switch_pending = (req_driver, req_device)
                return True
            self._output_switch_inflight = True

        ok = True
        current_driver = req_driver
        current_device = req_device
        while True:
            switched = self._apply_output_switch_once(current_driver, current_device)
            ok = bool(ok and switched)
            with self._output_switch_lock:
                self._last_output_switch_sig = (str(current_driver or ""), str(current_device or ""))
                self._last_output_switch_ts = time.monotonic()
                pending = self._output_switch_pending
                self._output_switch_pending = None
                if pending is None or (
                    str(pending[0] or "") == str(current_driver or "")
                    and str(pending[1] or "") == str(current_device or "")
                ):
                    self._output_switch_inflight = False
                    break
                current_driver, current_device = pending
        return ok

    def _apply_output_switch_once(self, driver, device_id=None):
        resolved_device_id = device_id
        if resolved_device_id is None:
            same_driver = str(driver or "") == str(getattr(self, "current_driver", "") or "")
            if same_driver:
                resolved_device_id = (
                    getattr(self, "current_device_id", None)
                    or getattr(self, "requested_device_id", None)
                )
        restore = getattr(self, "_output_switch_restore", None)
        if restore is None:
            restore = {
                "requested_driver": getattr(self, "requested_driver", None),
                "requested_device_id": getattr(self, "requested_device_id", None),
                "current_driver": getattr(self, "current_driver", None),
                "current_device_id": getattr(self, "current_device_id", None),
                "output_state": getattr(self, "output_state", "idle"),
                "output_error": getattr(self, "output_error", None),
            }
            self._output_switch_restore = restore
        self.requested_driver = driver
        self.requested_device_id = resolved_device_id
        self._alsa_container_adapter_active = False
        self._alsa_container_adapter_format = ""
        self._alsa_container_adapter_diag_sig = ""
        self.output_state = "switching"
        self.output_error = None
        if str(driver or "") == "PipeWire":
            try:
                cur = self._rust.list_devices("PipeWire") or []
                visible_ids = [str(d.get("device_id") or "") for d in cur]
                logger.info(
                    "PipeWire switch target: device_id=%s visible=%s",
                    str(resolved_device_id or "default"),
                    visible_ids,
                )
            except Exception:
                logger.debug("PipeWire switch pre-check failed", exc_info=True)
        if str(driver or "") == "PipeWire" and bool(getattr(self, "active_rate_switch", False)):
            if self._ensure_pipewire_pro_audio_profile(resolved_device_id):
                new_target = self._resolve_pipewire_target_after_profile_switch(resolved_device_id)
                if str(new_target or "") != str(resolved_device_id or ""):
                    logger.info(
                        "PipeWire target remapped after profile switch: %s -> %s",
                        str(resolved_device_id or "default"),
                        str(new_target or "default"),
                    )
                    resolved_device_id = new_target
                    self.requested_device_id = resolved_device_id
        target_buffer = int(getattr(self, "alsa_buffer_time", 100000) or 100000)
        target_latency = int(getattr(self, "alsa_latency_time", 10000) or 10000)
        exclusive = bool(getattr(self, "exclusive_lock_mode", False))

        driver_norm = _driver_key(driver)
        is_alsa_exclusive = exclusive and driver_norm in ("alsa_auto", "alsa_mmap")
        cur_res = getattr(self, "_alsa_reservation", None) if is_alsa_exclusive else None

        if is_alsa_exclusive and cur_res is not None and not cur_res.acquired:
            # Reservation is being acquired in background; retry will happen from
            # the async callback once D-Bus ownership is established.
            return True
        if not is_alsa_exclusive:
            # Leaving ALSA exclusive mode or switching drivers — release reservation.
            self._release_alsa_reservation()

        preferred_format = str(getattr(self, "preferred_output_format", "") or "").strip()
        try:
            self._rust.set_preferred_output_format(preferred_format or None)
        except Exception:
            logger.debug("Rust preferred output format update skipped", exc_info=True)

        rc = self._rust.set_output(
            driver,
            resolved_device_id,
            buffer_us=target_buffer,
            latency_us=target_latency,
            exclusive=exclusive,
        )
        if rc == 0:
            if str(driver or "") == "PipeWire":
                logger.info("PipeWire switch applied by Rust: target=%s", str(resolved_device_id or "default"))
            self.current_driver = driver
            self.current_device_id = resolved_device_id
            self._apply_driver_spectrum_policy(driver)
            self.output_state = "active"
            self.output_error = None
            self._output_switch_restore = None
            return True

        detail = ""
        try:
            detail = (self._rust.get_last_error() or "").strip()
        except Exception:
            detail = ""

        if is_alsa_exclusive and cur_res is None:
            from services.alsa_reserve import parse_alsa_card_num

            card_num = parse_alsa_card_num(str(resolved_device_id or ""))
            if card_num is not None:
                logger.info(
                    "ALSA exclusive direct open failed; acquiring D-Bus reservation and retrying once: "
                    "driver=%s device=%s rc=%s detail=%s",
                    driver,
                    resolved_device_id or "default",
                    rc,
                    detail or "n/a",
                )
                self._start_alsa_reservation_async(driver, resolved_device_id, card_num)
                return True

        msg = (
            f"Output switch failed (rc={rc}) for {driver}/{resolved_device_id or 'default'}"
            + (f": {detail}" if detail else "")
        )
        restore = getattr(self, "_output_switch_restore", None)
        if restore is not None:
            self.requested_driver = restore.get("requested_driver")
            self.requested_device_id = restore.get("requested_device_id")
            self.current_driver = restore.get("current_driver")
            self.current_device_id = restore.get("current_device_id")
            self._apply_driver_spectrum_policy(self.current_driver)
            self.output_state = restore.get("output_state", "idle")
            self.output_error = restore.get("output_error")
            self._output_switch_restore = None
        else:
            self.output_state = "error"
            self.output_error = msg
        logger.error(
            "Rust output switch failed: driver=%s device=%s rc=%s detail=%s",
            driver,
            resolved_device_id,
            rc,
            detail or "n/a",
        )
        return False

    def is_playing(self):
        self._refresh_rust_cache(force=False)
        return bool(self._cached_is_playing)

    def get_latency(self):
        lat = float(self._rust.get_latency() or 0.0)
        try:
            now = time.monotonic()
            last = float(getattr(self, "_lat_probe_log_ts", 0.0) or 0.0)
            if (now - last) >= 3.0:
                setattr(self, "_lat_probe_log_ts", now)
                probe = self._rust.get_latency_probe() or {}
                log_fn = logger.info if self._viz_trace_enabled else logger.debug
                log_fn(
                    "Rust latency probe: source=%s latency_ms=%.3f",
                    str(probe.get("source", "unknown")),
                    float(probe.get("latency_s", 0.0) or 0.0) * 1000.0,
                )
        except Exception:
            pass
        return max(0.0, lat)

    def get_position(self):
        self._refresh_rust_cache(force=False)
        p = float(self._cached_pos_s or 0.0)
        d = float(self._cached_dur_s or 0.0)
        if self._seek_target_s is not None and time.monotonic() < self._seek_hold_until:
            target = float(self._seek_target_s)
            # Mask transient 0/rebound frame right after flush seek.
            if p < max(0.2, target * 0.5):
                return target, d
        else:
            self._seek_target_s = None
        return p, d

    def set_speed(self, speed):
        return self._rust.set_speed(speed) == 0

    def set_pitch(self, semitones):
        return self._rust.set_pitch(semitones) == 0

    def get_devices_for_driver(self, driver):
        driver_name = str(driver or "")
        devices = self._rust.list_devices(driver)
        if devices is not None:
            try:
                key = driver_name
                sig = tuple((str(d.get("name") or ""), str(d.get("device_id") or "")) for d in devices)
                prev = self._last_enum_signature_by_driver.get(key)
                if prev != sig:
                    self._last_enum_signature_by_driver[key] = sig
                    logger.info("Output devices via Rust enum: driver=%s count=%d", driver, len(devices))
                    if driver_name == "PipeWire":
                        mapped = ", ".join(
                            f"{str(d.get('name') or '').strip()} -> {str(d.get('device_id') or '').strip() or 'default'}"
                            for d in devices
                        )
                        logger.info("PipeWire enum map: %s", mapped)
            except Exception:
                logger.info("Output devices via Rust enum: driver=%s count=%d", driver, len(devices))
            return devices
        logger.error("Rust device enumeration unavailable for driver=%s", driver)
        return []

    def set_output_format_preference(self, format_name=None):
        fmt = str(format_name or "").strip().upper()
        self.preferred_output_format = fmt
        rc = -1
        try:
            rc = int(self._rust.set_preferred_output_format(fmt or None))
        except Exception:
            logger.debug("Rust preferred output format setter failed", exc_info=True)
            rc = -1
        if fmt:
            logger.info("Preferred output format set: %s", fmt)
        else:
            logger.info("Preferred output format cleared")
        return rc == 0 or rc == -3


def create_audio_engine(on_eos_callback=None, on_tag_callback=None, on_spectrum_callback=None, on_viz_sync_offset_update=None):
    logger.info("Audio engine policy: Rust-only")
    return RustAudioPlayerAdapter(
        on_eos_callback=on_eos_callback,
        on_tag_callback=on_tag_callback,
        on_spectrum_callback=on_spectrum_callback,
        on_viz_sync_offset_update=on_viz_sync_offset_update,
    )
