import gi
import logging
import re
import os
import glob
import subprocess
import time

gi.require_version('Gst', '1.0')
gi.require_version('GstPbutils', '1.0') 
from gi.repository import Gst, GLib, GstPbutils

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
        
        # 初始化 Discoverer
        try:
            self.discoverer = GstPbutils.Discoverer.new(1 * Gst.SECOND)
        except Exception as e:
            print(f"[Init Warning] Failed to create Discoverer: {e}")
            self.discoverer = None
        
        self.on_eos_callback = on_eos_callback
        self.on_tag_callback = on_tag_callback
        
        self.equalizer = Gst.ElementFactory.make("equalizer-10bands", "equalizer")
        self.pipeline.set_property("audio-filter", self.equalizer)
        
        self.bit_perfect_mode = False
        self.exclusive_lock_mode = False 
        self.active_rate_switch = False
        
        self.current_driver = "Auto"
        self.current_device_id = None
        self.stream_info = {"codec": "-", "bitrate": 0, "rate": 0, "depth": 0}
        self.probe_id = None
        self.borrowed_pa_card = None

        self.alsa_buffer_time = 100000
        self.alsa_latency_time = 10000

        self._set_auto_sink()

    def set_alsa_latency(self, buffer_ms, latency_ms):
        self.alsa_buffer_time = int(buffer_ms * 1000)   # 毫秒转微秒
        self.alsa_latency_time = int(latency_ms * 1000)
        print(f"[AudioPlayer] ALSA Latency updated: Buffer={self.alsa_buffer_time}us, Period={self.alsa_latency_time}us")

    def cleanup(self):
        print("[AudioPlayer] Cleaning up resources...")
        self.stop()
        self._restore_pa_device()
        self._set_pipewire_clock(0)

    def load(self, uri):
        self.stop()
        
        if self.active_rate_switch and not self.exclusive_lock_mode and self.discoverer:
            self._pre_adjust_pipewire_rate(uri)

        self.pipeline.set_property("uri", uri)
        self.stream_info = {"codec": "Loading...", "bitrate": 0}

    def _pre_adjust_pipewire_rate(self, uri):
        try:
            info = self.discoverer.discover_uri(uri)
            audio_streams = info.get_audio_streams()
            if audio_streams:
                target_rate = audio_streams[0].get_sample_rate()
                if target_rate > 0:
                    print(f"[Rate Switcher] Source is {target_rate}Hz. Adjusting PipeWire clock...")
                    self._set_pipewire_clock(target_rate)
        except Exception as e:
            print(f"[Rate Switcher] Discovery failed (continuing anyway): {e}")

    def _set_pipewire_clock(self, rate):
        try:
            cmd = ["pw-metadata", "-n", "settings", "0", "clock.force-rate", str(rate)]
            subprocess.run(cmd, check=False, stderr=subprocess.DEVNULL)
        except: pass

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

    # ... 设备扫描 ...
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

    # ... 独占管理 ...
    def _release_pa_device(self, alsa_card_index):
        if not self.exclusive_lock_mode: return False
        try:
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
                sink.set_property("buffer-time", self.alsa_buffer_time)
                sink.set_property("latency-time", self.alsa_latency_time)
                sink.set_property("provide-clock", True)
                sink.set_property("slave-method", 1)
                self.pipeline.set_property("audio-sink", sink)
                ret = self.pipeline.set_state(Gst.State.READY)
                if ret == Gst.StateChangeReturn.FAILURE:
                    print(f"[AudioPlayer] ALSA Device {device_id} is BUSY! Falling back.")
                    self.pipeline.set_state(Gst.State.NULL)
                    self._set_auto_sink()
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
        self.active_rate_switch = enabled and not exclusive_lock
        
        if enabled:
            self.pipeline.set_property("audio-filter", None)
        else:
            self._restore_pa_device()
            self._set_pipewire_clock(0)
            self.exclusive_lock_mode = False 
            self.active_rate_switch = False
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
            
            # 计算位深
            depth = "16bit"
            if "S24" in str(fmt): depth = "24bit"
            elif "S32" in str(fmt) or "F32" in str(fmt): depth = "32bit"
            
            # 计算采样率字符串
            khz = f"{rate//1000}kHz" if rate else "?"
            
            # [核心修复] 不要在这里硬编码 "FLAC/PCM"！
            # Codec 信息应该由 on_message 从 TAG 中提取，或者根据 bitrate 推断。
            # self.stream_info["codec"] = "FLAC/PCM" <--- 删除这行
            
            self.stream_info["rate"] = rate
            self.stream_info["fmt_str"] = f"{khz} | {depth}"
            
            if self.on_tag_callback: 
                GLib.idle_add(self.on_tag_callback, self.stream_info)
                
        return Gst.PadProbeReturn.OK

    def on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            if self.on_eos_callback: GLib.idle_add(self.on_eos_callback)
            
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            debug_info = str(debug) if debug else ""
            print(f"[GStreamer Error] Code={err.code}, Msg={err.message}")
            # 忙碌恢复逻辑
            is_busy = err.code == 4 or "Device is being used" in debug_info or "busy" in debug_info
            if is_busy and not self.exclusive_lock_mode:
                print("[Auto-Recovery] Hardware is BUSY. Switching to System Fallback...")
                self.pipeline.set_state(Gst.State.NULL)
                self._set_auto_sink()
                GLib.timeout_add(100, lambda: self.pipeline.set_state(Gst.State.PLAYING))
        
        elif t == Gst.MessageType.TAG:
            tags = message.parse_tag()
            
            # 1. 获取比特率
            res, rate = tags.get_uint(Gst.TAG_BITRATE)
            if not res: res, rate = tags.get_uint(Gst.TAG_NOMINAL_BITRATE)
            if res: self.stream_info["bitrate"] = rate

            # 2. [新增] 尝试获取真实的 Codec 标签
            res, codec_tag = tags.get_string(Gst.TAG_AUDIO_CODEC)
            if res: 
                # 简化显示，比如 "MPEG-4 AAC" -> "AAC"
                if "AAC" in codec_tag: self.stream_info["codec"] = "AAC"
                elif "FLAC" in codec_tag: self.stream_info["codec"] = "FLAC"
                else: self.stream_info["codec"] = codec_tag

            # 3. [保底逻辑] 如果 TAG 没给 Codec，根据比特率智能推断
            # 防止显示 "Loading..." 或 "-"
            current_codec = self.stream_info.get("codec", "-")
            if current_codec in ["-", "Loading..."] and "bitrate" in self.stream_info:
                br = self.stream_info["bitrate"]
                if br > 0 and br < 500000: # 小于 500kbps 认为是 AAC
                    self.stream_info["codec"] = "AAC"
                elif br >= 500000:         # 大于 500kbps 认为是 FLAC
                    self.stream_info["codec"] = "FLAC"

            if self.on_tag_callback:
                GLib.idle_add(self.on_tag_callback, self.stream_info)
                
        elif t == Gst.MessageType.STATE_CHANGED:
            old, new, pending = message.parse_state_changed()
            if new == Gst.State.PLAYING: self._install_pad_probe()

    def get_format_string(self):
        if "fmt_str" in self.stream_info: return self.stream_info["fmt_str"]
        return "Loading..."


    def get_latency(self):
        """获取当前音频输出端的真实延迟 (秒) - 终极增强版"""
        # 1. 基础状态检查：如果没在播放或暂停，硬件未工作，延迟为 0
        current_state = self.pipeline.get_state(0)[1]
        if current_state != Gst.State.PLAYING and current_state != Gst.State.PAUSED:
            return 0.0
            
        latency = 0.0
        
        # 获取当前的 Sink 元素 (例如 alsasink, pulsesink 或 autoaudiosink)
        sink = self.pipeline.get_property("audio-sink")
        
        # --- 方法 A: 标准 GStreamer 查询 (优先尝试) ---
        # 这是最标准的方法，向管道询问"当前延迟是多少"
        try:
            # 如果 sink 是 bin (如 autoaudiosink 内部封装)，直接查 pipeline 可能更准
            target = sink if sink else self.pipeline
            query = Gst.Query.new_latency()
            
            if target.query(query):
                is_live, min_lat, max_lat = query.parse_latency()
                # GStreamer 返回的是纳秒 (10^-9)，转换为秒
                latency = float(min_lat) / 1e9
        except: 
            pass

        # --- 方法 B: 属性读取保底 (针对 ALSA 驱动不上报的情况) ---
        # 如果方法 A 失败 (返回 0 或极小值)，尝试直接读取 Sink 的属性
        if latency <= 0.001 and sink:
            try:
                # 检查 sink 是否有 'buffer-time' 属性 (alsasink, pulsesink 都有)
                # 这个属性通常对应硬件的缓冲区大小
                if hasattr(sink.props, 'buffer_time'):
                    # buffer-time 单位是微秒 (us)
                    buf_time = sink.get_property("buffer-time")
                    if buf_time > 0:
                        latency = float(buf_time) / 1000000.0
            except: 
                pass
                
        # --- 方法 C: 独占模式配置回读 (终极保底) ---
        # 如果以上都失败，但我们处于独占模式，说明延迟是我们自己设定的
        # 直接返回我们保存的配置值 (self.alsa_buffer_time)
        if latency <= 0.001 and self.exclusive_lock_mode:
            # 确保变量存在 (防止初始化前的边缘情况)
            if hasattr(self, 'alsa_buffer_time'):
                return float(self.alsa_buffer_time) / 1000000.0
            else:
                return 0.1 # 如果变量还没初始化，默认返回 100ms
            
        return latency
