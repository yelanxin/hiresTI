import gi
import logging
import re
import os
import glob
import subprocess
import time

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioPlayer:
    def __init__(self, on_eos_callback=None, on_tag_callback=None):
        try:
            Gst.init(None)
        except:
            pass
            
        self.pipeline = Gst.ElementFactory.make("playbin", "player")
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        
        self.on_eos_callback = on_eos_callback
        self.on_tag_callback = on_tag_callback
        
        self.equalizer = Gst.ElementFactory.make("equalizer-10bands", "equalizer")
        self.pipeline.set_property("audio-filter", self.equalizer)
        
        self.bit_perfect_mode = False
        self.exclusive_lock_mode = False 
        
        self.current_driver = "Auto"
        self.current_device_id = None
        self.stream_info = {"codec": "-", "bitrate": 0, "rate": 0, "depth": 0}
        self.probe_id = None
        
        self.borrowed_pa_card = None

        self._set_auto_sink()

    def cleanup(self):
        """程序退出时调用"""
        print("[AudioPlayer] Cleaning up resources...")
        self.stop()
        self._restore_pa_device()

    def load(self, uri):
        self.stop()
        self.pipeline.set_property("uri", uri)
        self.stream_info = {"codec": "Loading...", "bitrate": 0}

    def play(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def pause(self):
        self.pipeline.set_state(Gst.State.PAUSED)

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)

    def is_playing(self):
        _, state, _ = self.pipeline.get_state(1)
        return state == Gst.State.PLAYING

    def seek(self, position_seconds):
        self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, int(position_seconds * Gst.SECOND))

    def get_position(self):
        try:
            success, pos = self.pipeline.query_position(Gst.Format.TIME)
            success_dur, dur = self.pipeline.query_duration(Gst.Format.TIME)
            if success and success_dur:
                return pos / Gst.SECOND, dur / Gst.SECOND
        except: pass
        return 0, 0

    def set_volume(self, vol):
        self.pipeline.set_property("volume", vol)

    def set_eq_band(self, band_index, gain):
        if 0 <= band_index < 10 and self.equalizer:
            if hasattr(self.equalizer.props, f"band{band_index}"):
                self.equalizer.set_property(f"band{band_index}", gain)
    
    def reset_eq(self):
        if self.equalizer:
            for i in range(10):
                self.equalizer.set_property(f"band{i}", 0.0)

    # ==========================================
    # 辅助：获取 PulseAudio/PipeWire 设备列表
    # ==========================================
    def _get_pulseaudio_devices(self):
        devices = []
        try:
            output = subprocess.check_output(["pactl", "list", "sinks"], text=True)
            sinks = output.split("Sink #")
            for sink_block in sinks:
                if not sink_block.strip(): continue
                name_match = re.search(r'Name:\s+(.*)', sink_block)
                desc_match = re.search(r'Description:\s+(.*)', sink_block)
                if name_match:
                    dev_id = name_match.group(1).strip()
                    if dev_id.endswith(".monitor"): continue
                    friendly_name = dev_id 
                    if desc_match: friendly_name = desc_match.group(1).strip()
                    devices.append({"name": friendly_name, "device_id": dev_id})
        except: pass
        return devices

    # ==========================================
    # 设备扫描
    # ==========================================
    def get_drivers(self):
        return ["Auto (Default)", "PipeWire", "PulseAudio", "ALSA"]

    def get_devices_for_driver(self, driver):
        devices = []
        
        if driver == "Auto (Default)":
            devices.append({"name": "Default Output", "device_id": None})
            return devices

        if driver == "PulseAudio" or driver == "PipeWire":
            label = "Default System Output"
            devices.append({"name": label, "device_id": None})
            pa_devs = self._get_pulseaudio_devices()
            devices.extend(pa_devs)
            return devices

        if driver == "ALSA":
            try:
                with open("/proc/asound/cards", "r") as f:
                    content = f.read()
                pattern = re.compile(r'^\s*(\d+)\s+\[(.*?)\s*\]:\s+(.*?)\s+-\s+(.*?)$', re.MULTILINE)
                matches = pattern.findall(content)
                for m in matches:
                    idx = m[0]
                    long_name = m[3]
                    friendly_name = f"{long_name} (Card {idx})"
                    hw_id = f"hw:{idx},0"
                    devices.append({"name": friendly_name, "device_id": hw_id})
            except Exception as e:
                print(f"[ALSA Scan Error] {e}")
            devices.sort(key=lambda x: "USB" not in x["name"])
            return devices
            
        return []

    # ==========================================
    # 声音服务器管理
    # ==========================================
    def _release_pa_device(self, alsa_card_index):
        if not self.exclusive_lock_mode:
            return False

        try:
            print(f"[Device Manager] Exclusive Lock ON: Releasing PA Card {alsa_card_index}...")
            subprocess.run(["fuser", "-k", f"/dev/snd/pcmC{alsa_card_index}D0p"], stderr=subprocess.DEVNULL)
            output = subprocess.check_output(["pactl", "list", "cards"], text=True)
            target_pa_name = None
            current_name = None
            for line in output.splitlines():
                if "Name:" in line: current_name = line.split(":", 1)[1].strip()
                if f'alsa.card = "{alsa_card_index}"' in line:
                    target_pa_name = current_name
                    break
            if target_pa_name:
                subprocess.run(["pactl", "set-card-profile", target_pa_name, "off"], check=False)
                self.borrowed_pa_card = target_pa_name
                return True
        except: pass
        return False

    def _restore_pa_device(self):
        if self.borrowed_pa_card:
            print(f"[Device Manager] Restoring Card: {self.borrowed_pa_card}")
            try:
                res = subprocess.run(["pactl", "set-card-profile", self.borrowed_pa_card, "pro-audio"], capture_output=True)
                if res.returncode != 0:
                     subprocess.run(["pactl", "set-card-profile", self.borrowed_pa_card, "output:analog-stereo"])
                self.borrowed_pa_card = None
            except: pass

    # ==========================================
    # 输出设置
    # ==========================================
    def set_output(self, driver, device_id=None):
        print(f"[AudioPlayer] Setting Output -> Driver: {driver}, Device: {device_id}")
        
        was_playing = self.is_playing()
        self.pipeline.set_state(Gst.State.NULL)
        
        if self.borrowed_pa_card:
             if not self.exclusive_lock_mode or driver != "ALSA" or not device_id:
                 self._restore_pa_device()

        if driver == "ALSA" and device_id:
            try:
                card_idx = device_id.split(':')[1].split(',')[0]
                self._release_pa_device(card_idx)
                if self.exclusive_lock_mode: time.sleep(0.5)
            except: pass

            sink = Gst.ElementFactory.make("alsasink", "audio_sink")
            if sink:
                sink.set_property("device", device_id)
                sink.set_property("buffer-time", 100000)
                sink.set_property("latency-time", 10000)
                self.pipeline.set_property("audio-sink", sink)
            else:
                self._set_auto_sink()

        elif driver == "PipeWire" or driver == "PulseAudio":
            if not device_id:
                if driver == "PipeWire":
                    sink = Gst.ElementFactory.make("pipewiresink", "audio_sink")
                    if not sink: sink = Gst.ElementFactory.make("pulsesink", "audio_sink")
                else:
                    sink = Gst.ElementFactory.make("pulsesink", "audio_sink")
                self.pipeline.set_property("audio-sink", sink)
            else:
                sink = Gst.ElementFactory.make("pulsesink", "audio_sink")
                if sink:
                    sink.set_property("device", device_id)
                    self.pipeline.set_property("audio-sink", sink)
                else:
                    self._set_auto_sink()
        else:
            self._set_auto_sink()

        if was_playing:
            self.pipeline.set_state(Gst.State.PLAYING)
            
        GLib.timeout_add(500, self._install_pad_probe)

    def _set_auto_sink(self):
        sink = Gst.ElementFactory.make("autoaudiosink", "audio_sink")
        self.pipeline.set_property("audio-sink", sink)

    def toggle_bit_perfect(self, enabled, exclusive_lock=False):
        self.bit_perfect_mode = enabled
        self.exclusive_lock_mode = exclusive_lock 
        
        if enabled:
            self.pipeline.set_property("audio-filter", None)
        else:
            self._restore_pa_device()
            self.exclusive_lock_mode = False 
            if self.equalizer:
                self.pipeline.set_property("audio-filter", self.equalizer)
            self._set_auto_sink()
        return None

    def _install_pad_probe(self):
        try:
            sink = self.pipeline.get_property("audio-sink")
            if not sink: return False
            pad = sink.get_static_pad("sink")
            if not pad: return False
            if self.probe_id: self.probe_id = None
            self.probe_id = pad.add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, self._pad_probe_cb)
            return False
        except: return False

    def _pad_probe_cb(self, pad, info):
        event = info.get_event()
        if event.type == Gst.EventType.CAPS:
            caps = event.parse_caps()
            structure = caps.get_structure(0)
            fmt = structure.get_value("format")
            rate = structure.get_value("rate")
            depth = "16bit"
            if "S24" in str(fmt): depth = "24bit"
            elif "S32" in str(fmt) or "F32" in str(fmt): depth = "32bit"
            khz = f"{rate//1000}kHz" if rate else "?"
            self.stream_info["codec"] = "FLAC/PCM"
            self.stream_info["rate"] = rate
            self.stream_info["fmt_str"] = f"{khz} | {depth}"
            if self.on_tag_callback: GLib.idle_add(self.on_tag_callback, self.stream_info)
        return Gst.PadProbeReturn.OK

    # ==========================================
    # [核心修复] 消息处理与自动救援
    # ==========================================
    def on_message(self, bus, message):
        t = message.type
        
        if t == Gst.MessageType.EOS:
            if self.on_eos_callback: GLib.idle_add(self.on_eos_callback)
            
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            debug_info = str(debug) if debug else ""
            print(f"[GStreamer Error] Code={err.code}, Msg={err.message}")
            print(f"Debug Info: {debug_info}")

            # 1. 检查是否是 'Device busy' 错误 (Code 4 = RESOURCE_BUSY)
            is_busy = err.code == 4 or "Device is being used" in debug_info or "busy" in debug_info
            
            # 2. 如果发生了 Busy 错误，且我们并没有强制独占
            # 说明用户想开 Bit-Perfect 但设备被系统占了
            # 我们应该做 "Soft Fallback"
            if is_busy and not self.exclusive_lock_mode:
                print("[Auto-Recovery] Hardware is BUSY. Switching to System Fallback...")
                
                # 必须先停止 pipeline 才能换 sink
                self.pipeline.set_state(Gst.State.NULL)
                
                # 换回 Auto Sink
                self._set_auto_sink()
                
                # 尝试重新播放
                # 注意：如果在初始化阶段就出错，这里可能需要延时
                GLib.timeout_add(100, lambda: self.pipeline.set_state(Gst.State.PLAYING))
                
        elif t == Gst.MessageType.STATE_CHANGED:
            old, new, pending = message.parse_state_changed()
            if new == Gst.State.PLAYING: self._install_pad_probe()

    def get_format_string(self):
        if "fmt_str" in self.stream_info: return self.stream_info["fmt_str"]
        return "Loading..."
