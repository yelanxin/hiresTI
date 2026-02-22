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

logger = logging.getLogger(__name__)

class AudioPlayer:
    def __init__(self, on_eos_callback=None, on_tag_callback=None, on_spectrum_callback=None, on_viz_sync_offset_update=None):
        """
        完整初始化：包含频谱仪集成、技术参数存储、以及 ALSA/Pulse 状态管理
        """
        try:
            Gst.init(None)
        except Exception as e:
            logger.debug("GStreamer init skipped/failed: %s", e)

        # 1. 创建核心管道 (使用 playbin 自动处理解码)
        self.pipeline = Gst.ElementFactory.make("playbin", "player")

        # 2. 初始化核心状态变量 (修复 AttributeError 的关键)
        self.stream_info = {"codec": "-", "bitrate": 0, "rate": 0, "depth": 0}
        self.probe_id = None
        self.bit_perfect_mode = False
        self.exclusive_lock_mode = False
        self.active_rate_switch = False
        self.output_state = "idle"
        self.output_error = None
        self.requested_driver = None
        self.requested_device_id = None
        self.event_log = []
        self.last_latency_source = "none"
        self.last_latency_seconds = 0.0
        self.visual_sync_offset_ms = 0
        self.visual_sync_base_ms = 0
        self.visual_sync_lead_ms = 0
        self.visual_sync_startup_ms = 0
        self.visual_sync_auto_offset_ms = 0.0
        self._viz_offset_report_last_ts = 0.0
        self._viz_offset_report_last_val = 0
        self._viz_latency_cached_ms = 0.0
        self._viz_latency_smooth_ms = 0.0
        self._viz_msg_age_smooth_ms = 0.0
        self._viz_latency_last_probe_ts = 0.0
        self._viz_start_guard_until = 0.0
        self._viz_epoch = 0
        self._viz_debug_last_ts = 0.0
        self.spectrum_enabled = False
        self._spectrum_bands_active = 64
        self._spectrum_bands_idle = 16
        self._spectrum_interval_active_ns = 33000000
        self._spectrum_interval_idle_ns = 220000000

        # 声卡与独占模式管理变量
        self.borrowed_pa_card = None
        self.current_driver = "Auto"
        self.current_device_id = None

        # 默认音频参数 (为 Honda Civic 优化的低延迟预设)
        self.alsa_buffer_time = 100000
        self.alsa_latency_time = 10000

        # 保存回调函数
        self.on_eos_callback = on_eos_callback
        self.on_tag_callback = on_tag_callback
        self.on_spectrum_callback = on_spectrum_callback
        self.on_viz_sync_offset_update = on_viz_sync_offset_update

        # 3. 初始化 Discoverer (用于获取媒体元数据)
        try:
            self.discoverer = GstPbutils.Discoverer.new(1 * Gst.SECOND)
        except Exception as e:
            logger.warning("Failed to create Discoverer: %s", e)
            self.discoverer = None

        # 4. 构建音频处理过滤器链 (Equalizer + Spectrum)
        self._setup_filter_chain()

        # 5. 连接总线消息监听 (捕获 EOS、错误以及频谱数据)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        # 专门监听 element 消息以抓取 spectrum 数据
        bus.connect("message::element", self._on_bus_message)

    def _push_event(self, message):
        ts = time.strftime("%H:%M:%S")
        self.event_log.append(f"{ts} | {message}")
        if len(self.event_log) > 20:
            self.event_log = self.event_log[-20:]

    def _setup_filter_chain(self):
        """
        内部辅助方法：构建均衡器和频谱仪链条 (同步优化版)
        """
        # 1. 必须先创建元素！(这是解决 AttributeError 的关键)
        self.equalizer = Gst.ElementFactory.make("equalizer-10bands", "equalizer")
        self.spectrum = Gst.ElementFactory.make("spectrum", "spectrum")
        
        # 安全检查
        if not self.equalizer:
            self.equalizer = Gst.ElementFactory.make("audioconvert", "eq_placeholder")

        if not self.spectrum:
            logger.error("spectrum element missing")
            return

        # 2. 现在才能配置属性
        # Keep these runtime-stable to avoid native race/crash in some stacks.
        self.spectrum.set_property("bands", int(self._spectrum_bands_active))
        self.spectrum.set_property("interval", int(self._spectrum_interval_active_ns))
        
        spec_props = [p.name for p in self.spectrum.list_properties()]
        if 'message' in spec_props:
            self.spectrum.set_property("message", bool(self.spectrum_enabled))
        elif 'post-messages' in spec_props:
            self.spectrum.set_property("post-messages", bool(self.spectrum_enabled))

        # 3. 构建并链接 Bin
        self.filter_bin = Gst.Bin.new("filter_bin")
        self.filter_bin.add(self.equalizer)
        self.filter_bin.add(self.spectrum)
        self.equalizer.link(self.spectrum)
        
        sink_pad = self.equalizer.get_static_pad("sink")
        src_pad = self.spectrum.get_static_pad("src")

        if sink_pad and src_pad:
            self.filter_bin.add_pad(Gst.GhostPad.new("sink", sink_pad))
            self.filter_bin.add_pad(Gst.GhostPad.new("src", src_pad))
            self.pipeline.set_property("audio-filter", self.filter_bin)

    def set_spectrum_enabled(self, enabled):
        enabled = bool(enabled)
        self.spectrum_enabled = enabled
        if not hasattr(self, "spectrum") or self.spectrum is None:
            return
        try:
            # Runtime mutation of spectrum caps/timing can race with the streaming thread
            # on some stacks (observed native SIGSEGV in gobject/gstreamer path).
            # Keep bands/interval stable after setup; only toggle message emission.
            spec_props = [p.name for p in self.spectrum.list_properties()]
            if "message" in spec_props:
                self.spectrum.set_property("message", enabled)
            elif "post-messages" in spec_props:
                self.spectrum.set_property("post-messages", enabled)
        except Exception as e:
            logger.debug("Failed to toggle spectrum messages: %s", e)

    def set_alsa_latency(self, buffer_ms, latency_ms):
        self.alsa_buffer_time = int(buffer_ms * 1000)   # 毫秒转微秒
        self.alsa_latency_time = int(latency_ms * 1000)
        logger.info(
            "ALSA latency updated: buffer=%sus period=%sus",
            self.alsa_buffer_time,
            self.alsa_latency_time,
        )

    def cleanup(self):
        logger.info("Cleaning up audio resources...")
        self.stop()
        self._restore_pa_device()
        self._set_pipewire_clock(0)

    def _reset_visual_sync_state(self):
        self._viz_latency_cached_ms = 0.0
        self._viz_latency_smooth_ms = 0.0
        self._viz_msg_age_smooth_ms = 0.0
        self._viz_latency_last_probe_ts = 0.0
        self._viz_start_guard_until = 0.0
        self._viz_epoch += 1

    def _arm_visual_start_guard(self):
        self._viz_start_guard_until = time.monotonic() + (max(0.0, float(self.visual_sync_startup_ms or 0)) / 1000.0)

    def _dispatch_spectrum(self, magnitudes, pos_s, epoch):
        if epoch != self._viz_epoch:
            return False
        try:
            self.on_spectrum_callback(magnitudes, pos_s)
        except Exception:
            pass
        return False

    def load(self, uri):
        self.stop()
        self._reset_visual_sync_state()
        
        if self.active_rate_switch and not self.exclusive_lock_mode and self.discoverer:
            self._pre_adjust_pipewire_rate(uri)

        self.pipeline.set_property("uri", uri)
        self.stream_info = {"codec": "Loading...", "bitrate": 0}
        if hasattr(self, 'filter_bin'):
            self.pipeline.set_property("audio-filter", self.filter_bin)

    def _pre_adjust_pipewire_rate(self, uri):
        try:
            info = self.discoverer.discover_uri(uri)
            audio_streams = info.get_audio_streams()
            if audio_streams:
                target_rate = audio_streams[0].get_sample_rate()
                if target_rate > 0:
                    logger.info("Source is %sHz. Adjusting PipeWire clock...", target_rate)
                    self._set_pipewire_clock(target_rate)
        except Exception as e:
            logger.warning("Rate discovery failed (continuing): %s", e)

    def _set_pipewire_clock(self, rate):
        custom_setter = getattr(self, "pipewire_clock_setter", None)
        if callable(custom_setter):
            try:
                if bool(custom_setter(rate)):
                    return
            except Exception as e:
                logger.debug("Custom PipeWire clock setter failed (%s): %s", rate, e)
        try:
            cmd = ["pw-metadata", "-n", "settings", "0", "clock.force-rate", str(rate)]
            subprocess.run(cmd, check=False, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.debug("Failed to set PipeWire clock rate to %s: %s", rate, e)

    def set_uri(self, uri):
        """
        设置播放链接 (修正版：修复属性检测 bug)
        """
        # 1. 停止播放
        self.stop()
        self._reset_visual_sync_state()
        
        # 定义一个内部函数来检查属性是否存在
        def has_property(obj, prop_name):
            try:
                # GObject.list_properties 返回的是参数规格对象(ParamSpec)列表
                # 我们需要检查这些对象的 .name 属性
                return any(p.name == prop_name for p in obj.list_properties())
            except Exception:
                return False

        # 2. 方案 A: 检查 Pipeline 本身是否有 "uri" 属性 (针对 playbin)
        if has_property(self.pipeline, "uri"):
            # print(f"[AudioPlayer] Setting URI on pipeline (playbin)")
            self.pipeline.set_property("uri", uri)
            return

        # 3. 方案 B: 查找名为 "source" 的元件
        source = self.pipeline.get_by_name("source")
        if source and has_property(source, "location"):
            source.set_property("location", uri)
            return

        # 4. 方案 C: 遍历所有元件寻找支持 "location" 的 (针对 souphttpsrc/filesrc)
        iterator = self.pipeline.iterate_elements()
        while True:
            result, elem = iterator.next()
            if result != Gst.IteratorResult.OK:
                break
            
            if has_property(elem, "location"):
                # print(f"[AudioPlayer] Found source element: {elem.get_name()}")
                elem.set_property("location", uri)
                return

        # 5. 如果都失败了，打印调试信息
        logger.error("Could not find target for URI. Pipeline type: %s", type(self.pipeline))

    def play(self):
        # Apply a short guard window on every resume/start.
        # Some outputs keep a noticeable re-prime latency even from PAUSED.
        self._reset_visual_sync_state()
        self._arm_visual_start_guard()
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
        except Exception as e:
            logger.debug("Failed to query position/duration: %s", e)
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
        except Exception as e:
            logger.debug("Failed to enumerate PulseAudio sinks: %s", e)
        return devices

    def get_drivers(self):
        return ["Auto (Default)", "PipeWire", "ALSA"]

    def get_devices_for_driver(self, driver):
        devices = []
        if driver == "Auto (Default)":
            devices.append({"name": "Default Output", "device_id": None})
            return devices
        if driver == "PipeWire":
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
                logger.warning("ALSA scan error: %s", e)
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
        except Exception as e:
            logger.debug("Failed to release PA device for card %s: %s", alsa_card_index, e)
        return False

    def _restore_pa_device(self):
        if self.borrowed_pa_card:
            try:
                res = subprocess.run(["pactl", "set-card-profile", self.borrowed_pa_card, "pro-audio"], capture_output=True)
                if res.returncode != 0:
                     subprocess.run(["pactl", "set-card-profile", self.borrowed_pa_card, "output:analog-stereo"])
                self.borrowed_pa_card = None
            except Exception as e:
                logger.warning("Failed to restore PA device profile for %s: %s", self.borrowed_pa_card, e)

    # ==========================================
    # 输出设置
    # ==========================================
    def set_output(self, driver, device_id=None):
        """
        设置音频输出驱动和设备 (整合 ALSA/PipeWire/PulseAudio 终极优化版)
        """
        if driver == "PulseAudio":
            # Backward compatibility for old saved settings.
            driver = "PipeWire"
        logger.info("Setting output: driver=%s device=%s", driver, device_id)
        self.output_state = "switching"
        self.output_error = None
        self.requested_driver = driver
        self.requested_device_id = device_id
        self._push_event(f"Output switch requested: {driver} / {device_id or 'default'}")

        # 1. 停止播放并清理旧状态
        was_playing = self.is_playing()
        self.pipeline.set_state(Gst.State.NULL)

        # 如果从独占模式切换出去，尝试恢复 PulseAudio 设备配置
        if self.borrowed_pa_card:
             if not self.exclusive_lock_mode or driver != "ALSA" or not device_id:
                 self._restore_pa_device()

        # ==========================================
        # 分支 A: ALSA (硬件独占 / Bit-Perfect)
        # ==========================================
        if driver == "ALSA" and device_id:
            try:
                # 尝试释放 PulseAudio 占用 (抢占声卡)
                card_idx = device_id.split(':')[1].split(',')[0]
                self._release_pa_device(card_idx)
                if self.exclusive_lock_mode: time.sleep(0.5) # 给硬件一点喘息时间
            except Exception as e:
                logger.debug("ALSA pre-release step failed for %s: %s", device_id, e)

            sink = Gst.ElementFactory.make("alsasink", "audio_sink")
            if sink:
                sink.set_property("device", device_id)

                # --- [核心优化 1] 动态延迟参数 ---
                # 使用我们之前定义的变量 (来自用户设置的档位)
                # 确保 self.alsa_buffer_time 已在 __init__ 或 set_alsa_latency 中定义
                target_buffer = getattr(self, 'alsa_buffer_time', 100000)
                target_latency = getattr(self, 'alsa_latency_time', 10000)

                sink.set_property("buffer-time", target_buffer)
                sink.set_property("latency-time", target_latency)

                # --- [核心优化 2] 发烧级时钟设置 ---
                # 强制让 DAC 做主时钟 (Master)，电脑做从属，大幅降低 Jitter
                try:
                    sink.set_property("provide-clock", True)
                except Exception as e:
                    logger.debug("ALSA sink provide-clock unsupported: %s", e)

                # --- [核心优化 3] 时钟漂移校正 ---
                # 1 = SKEW (微调指针)。相比 RESAMPLE (重采样)，这能保证原始数据不被修改。
                try:
                    sink.set_property("slave-method", 1)
                except Exception as e:
                    logger.debug("ALSA sink slave-method unsupported: %s", e)

                # 应用 Sink
                self.pipeline.set_property("audio-sink", sink)

                # 测试设备是否繁忙
                ret = self.pipeline.set_state(Gst.State.READY)
                if ret == Gst.StateChangeReturn.FAILURE:
                    self._switch_to_auto_sink(f"alsa busy: {device_id}")
            else:
                self._set_auto_sink()

        # ==========================================
        # 分支 B: PipeWire (低延迟 / 新一代架构)
        # ==========================================
        elif driver == "PipeWire":
            sink = Gst.ElementFactory.make("pipewiresink", "audio_sink")
            if sink:
                # 1. 绑定设备
                if device_id:
                    # PipeWire 使用 target-object 指定 Node ID 或 Serial
                    try:
                        sink.set_property("target-object", device_id)
                    except Exception as e: # 旧版插件可能不支持
                        logger.debug("PipeWire target-object unsupported for %s: %s", device_id, e)

                # 2. 构建高级参数
                props = Gst.Structure.new_empty("props")

                # --- [核心优化 4] 智能 Quantum 计算 ---
                # 将用户的 ALSA 延迟档位映射到 PipeWire Quantum
                # 公式: Quantum = Buffer时间(秒) * 48000
                target_buffer_us = getattr(self, 'alsa_buffer_time', 100000)

                # 基础 Quantum 计算
                base_quantum = int((target_buffer_us / 1000000.0) * 48000)

                # 寻找最近的 2 的幂 (PipeWire 喜欢 2 的幂: 1024, 2048, 4096...)
                # 例如 100ms -> 4800 -> 映射到 4096
                #      20ms  -> 960  -> 映射到 1024
                quantum = 1024
                for p in [256, 512, 1024, 2048, 4096, 8192]:
                    if abs(p - base_quantum) < abs(quantum - base_quantum):
                        quantum = p

                # 强制限制在合理范围内 (发烧友建议 1024 - 4096)
                quantum = max(512, min(quantum, 8192))

                logger.info("PipeWire latency map: buffer %sus -> quantum %s/48000", target_buffer_us, quantum)

                props.set_value("node.latency", f"{quantum}/48000")
                props.set_value("node.autoconnect", "false" if device_id else "true")
                props.set_value("media.role", "Music")       # 标记为音乐流，提高优先级
                props.set_value("resample.quality", 12)      # 高质量重采样 (0-14)

                # 尝试开启“独占式”调度 (如果支持)
                # props.set_value("node.lock-quantum", "true")

                sink.set_property("stream-properties", props)
                self.pipeline.set_property("audio-sink", sink)
            else:
                # 如果系统没装 pipewiresink，回退到 Auto
                self._set_auto_sink()
                return

        # ==========================================
        # 分支 C: PulseAudio (传统兼容模式)
        # ==========================================
        elif driver == "PulseAudio":
            sink = Gst.ElementFactory.make("pulsesink", "audio_sink")
            if sink:
                if device_id:
                    sink.set_property("device", device_id)

                # 虽然 PulseAudio 不一定听话，但我们还是把参数传过去
                # 这有助于在低负载下获得正确的延迟
                target_buffer = getattr(self, 'alsa_buffer_time', 100000)
                target_latency = getattr(self, 'alsa_latency_time', 10000)
                sink.set_property("buffer-time", target_buffer)
                sink.set_property("latency-time", target_latency)

                # 同样开启 DAC 主时钟模式
                try:
                    sink.set_property("provide-clock", True)
                except Exception as e:
                    logger.debug("Pulse sink provide-clock unsupported: %s", e)

                self.pipeline.set_property("audio-sink", sink)
            else:
                self._set_auto_sink()

        # ==========================================
        # 分支 D: Auto / Fallback
        # ==========================================
        else:
            self._set_auto_sink()

        # 恢复播放状态
        if was_playing:
            self.pipeline.set_state(Gst.State.PLAYING)
        if self.output_state == "switching":
            self.output_state = "active"
            self._push_event(f"Output active: {driver} / {device_id or 'default'}")

        # 重新安装 Probe 以获取新的格式信息
        GLib.timeout_add(500, self._install_pad_probe)

    def _set_auto_sink(self):
        sink = Gst.ElementFactory.make("autoaudiosink", "audio_sink")
        self.pipeline.set_property("audio-sink", sink)

    def _switch_to_auto_sink(self, reason, resume_play=False):
        logger.warning("Switching to system fallback sink: %s", reason)
        self.pipeline.set_state(Gst.State.NULL)
        self._set_auto_sink()
        self.output_state = "fallback"
        self.output_error = reason
        self._push_event(f"Fallback to auto sink: {reason}")
        if resume_play:
            GLib.timeout_add(100, lambda: self.pipeline.set_state(Gst.State.PLAYING))

    def toggle_bit_perfect(self, enabled, exclusive_lock=False):
        self.bit_perfect_mode = enabled
        self.exclusive_lock_mode = exclusive_lock 
        self.active_rate_switch = enabled and not exclusive_lock
        self._push_event(f"Bit-Perfect={'ON' if enabled else 'OFF'} Exclusive={'ON' if exclusive_lock else 'OFF'}")
        
        if enabled:
            # [修正] Bit-Perfect 开启时，我们依然保留 spectrum，但旁路掉 equalizer
            # 我们可以通过设置均衡器的各频段为 0，或者重新构建只含 spectrum 的 filter_bin
            self.reset_eq() 
            logger.info("Bit-Perfect ON: EQ bypassed, spectrum kept")
        else:
            self._restore_pa_device()
            self._set_pipewire_clock(0)
            logger.info("Bit-Perfect OFF: EQ enabled")
            
        # 确保 filter_bin 始终挂载，除非你真的想彻底关闭所有视觉反馈
        self.pipeline.set_property("audio-filter", self.filter_bin)
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
        except Exception as e:
            logger.debug("Failed to install pad probe: %s", e)
            return False

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

    def _on_bus_message(self, bus, msg):
        if not self.spectrum_enabled:
            return
        if msg.type == Gst.MessageType.ELEMENT:
            s = msg.get_structure()
            if s and s.get_name() == "spectrum":
                magnitudes = self._extract_spectrum_magnitudes(s)

                if magnitudes and self.on_spectrum_callback:
                    epoch = self._viz_epoch
                    pos_s = None
                    try:
                        ok, pos_ns = self.pipeline.query_position(Gst.Format.TIME)
                        if ok and pos_ns is not None and pos_ns >= 0:
                            pos_s = float(pos_ns) / float(Gst.SECOND)
                    except Exception:
                        pos_s = None
                    msg_pos_s = self._extract_spectrum_message_pos_s(s)
                    delay_ms = self._estimate_visual_delay_ms(current_pos_s=pos_s, msg_pos_s=msg_pos_s)
                    if delay_ms <= 0:
                        GLib.idle_add(self._dispatch_spectrum, magnitudes, pos_s, epoch)
                    else:
                        GLib.timeout_add(delay_ms, self._dispatch_spectrum, magnitudes, pos_s, epoch)

    def _extract_spectrum_magnitudes(self, s):
        """Parse spectrum magnitude list with low overhead."""
        if not s:
            return []
        try:
            if not s.has_field("magnitude"):
                return []
            raw = s.get_value("magnitude")
            if raw is None:
                return []

            # Common fast paths first.
            if isinstance(raw, (list, tuple)):
                return [float(v) for v in raw]
            if hasattr(raw, "__iter__"):
                return [float(v) for v in raw]

            # Some bindings expose a boxed value array; try index access.
            out = []
            if hasattr(raw, "__len__") and hasattr(raw, "__getitem__"):
                for i in range(len(raw)):
                    out.append(float(raw[i]))
                if out:
                    return out
        except Exception:
            pass

        # Last resort compatibility path for uncommon GI representations.
        try:
            s_str = s.to_string()
            m = re.search(r"magnitude=.*?[\{<]\s*(.*?)\s*[\}>]", s_str)
            if not m:
                return []
            raw_data = m.group(1)
            return [float(x.strip()) for x in raw_data.split(", ") if x.strip()]
        except Exception:
            return []

    def _extract_spectrum_message_pos_s(self, s):
        """Try to extract the spectrum frame time (seconds) from message structure."""
        if not s:
            return None
        ns_value = None
        for key in ("endtime", "running-time", "stream-time", "timestamp"):
            try:
                if s.has_field(key):
                    # 1) Preferred: explicit clock-time getter.
                    try:
                        ct = s.get_clock_time(key)
                        if isinstance(ct, int) and ct >= 0:
                            ns_value = ct
                            break
                    except Exception:
                        pass
                    # 2) uint64 path.
                    try:
                        ok_u64, v_u64 = s.get_uint64(key)
                        if ok_u64 and isinstance(v_u64, int) and v_u64 >= 0:
                            ns_value = v_u64
                            break
                    except Exception:
                        pass
                    # 3) generic value path.
                    raw = s.get_value(key)
                    if isinstance(raw, int) and raw >= 0:
                        ns_value = raw
                        break
            except Exception:
                continue
        # 4) Last-resort parse from structure text.
        if ns_value is None:
            try:
                s_str = s.to_string()
                m = re.search(r"(?:endtime|running-time|stream-time|timestamp)=\((?:g?uint64|uint64)\)\s*(\d+)", s_str)
                if m:
                    ns_value = int(m.group(1))
            except Exception:
                pass
        if ns_value is None:
            return None
        return float(ns_value) / float(Gst.SECOND)

    def _estimate_visual_delay_ms(self, current_pos_s=None, msg_pos_s=None):
        now = time.monotonic()

        # Always sample sink latency at low rate; this is the audible-path lag.
        if (now - self._viz_latency_last_probe_ts) >= 0.12:
            self._viz_latency_last_probe_ts = now
            try:
                lat_s = float(self.get_latency() or 0.0)
            except Exception:
                lat_s = 0.0
            self._viz_latency_cached_ms = max(0.0, min(lat_s * 1000.0, 1500.0))

        # Smooth sink latency itself; frame scheduling uses per-frame timestamp delta.
        if self._viz_latency_smooth_ms <= 0.0:
            self._viz_latency_smooth_ms = self._viz_latency_cached_ms
        else:
            self._viz_latency_smooth_ms = (self._viz_latency_smooth_ms * 0.80) + (self._viz_latency_cached_ms * 0.20)

        # Core timing:
        # emit when this spectrum frame is expected to be audible:
        #   delay = (frame_time + sink_latency - current_time)
        if (
            msg_pos_s is not None
            and current_pos_s is not None
            and msg_pos_s >= 0.0
            and current_pos_s >= 0.0
        ):
            msg_age_ms = max(0.0, (float(current_pos_s) - float(msg_pos_s)) * 1000.0)
            if self._viz_msg_age_smooth_ms <= 0.0:
                self._viz_msg_age_smooth_ms = msg_age_ms
            else:
                self._viz_msg_age_smooth_ms = (self._viz_msg_age_smooth_ms * 0.85) + (msg_age_ms * 0.15)
            target_ms = ((float(msg_pos_s) + (self._viz_latency_smooth_ms / 1000.0) - float(current_pos_s)) * 1000.0)
        else:
            # No reliable frame timestamp: subtract learned message age overhead.
            target_ms = max(0.0, self._viz_latency_smooth_ms - self._viz_msg_age_smooth_ms)

        learned_offset_ms = float(self.visual_sync_offset_ms or 0)
        total_ms = (
            target_ms
            + float(self.visual_sync_base_ms or 0)
            + learned_offset_ms
            - float(self.visual_sync_lead_ms or 0)
        )
        # Disabled: do not auto-persist learned offset to avoid drift/corruption.
        if logger.isEnabledFor(logging.DEBUG) and (now - self._viz_debug_last_ts) >= 1.0:
            self._viz_debug_last_ts = now
            logger.debug(
                "viz-sync delay=%.1fms target=%.1fms lat=%.1fms msg_age=%.1fms off=%d cur=%.3fs msg=%.3fs",
                total_ms,
                target_ms,
                self._viz_latency_smooth_ms,
                self._viz_msg_age_smooth_ms,
                int(round(learned_offset_ms)),
                float(current_pos_s or 0.0),
                float(msg_pos_s or -1.0),
            )
        return int(max(0.0, min(total_ms, 2000.0)))

    def on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            if self.on_eos_callback: GLib.idle_add(self.on_eos_callback)
            
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            debug_info = str(debug) if debug else ""
            logger.error("GStreamer error: code=%s msg=%s", err.code, err.message)
            self.output_state = "error"
            self.output_error = err.message
            self._push_event(f"GStreamer error: {err.message}")
            # 忙碌恢复逻辑
            is_busy = err.code == 4 or "Device is being used" in debug_info or "busy" in debug_info
            if is_busy and not self.exclusive_lock_mode:
                self._switch_to_auto_sink("runtime busy recovery", resume_play=True)
        
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
            self.last_latency_source = "not-playing"
            self.last_latency_seconds = 0.0
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
                if latency > 0.001:
                    self.last_latency_source = "gst-query"
                    self.last_latency_seconds = latency
                    return latency
        except Exception as e:
            logger.debug("Latency query failed: %s", e)

        # --- 方法 B: 属性读取保底 (针对 ALSA 驱动不上报的情况) ---
        # 如果方法 A 失败 (返回 0 或极小值)，尝试直接读取 Sink 的属性
        if latency <= 0.001 and sink:
            try:
                # 优先读取运行时“实际”缓冲属性（如果插件支持）
                prop_names = {p.name for p in sink.list_properties()}
                for actual_name in ("actual-latency-time", "actual-buffer-time"):
                    if actual_name in prop_names:
                        actual_us = sink.get_property(actual_name)
                        if actual_us and actual_us > 0:
                            latency = float(actual_us) / 1000000.0
                            self.last_latency_source = actual_name
                            self.last_latency_seconds = latency
                            break

                if latency > 0.001:
                    return latency

                # 检查 sink 是否有 'buffer-time' 属性 (alsasink, pulsesink 都有)
                # 这个属性通常对应硬件的缓冲区大小
                if hasattr(sink.props, 'buffer_time'):
                    # buffer-time 单位是微秒 (us)
                    buf_time = sink.get_property("buffer-time")
                    if buf_time > 0:
                        latency = float(buf_time) / 1000000.0
                        self.last_latency_source = "buffer-time"
                        self.last_latency_seconds = latency
            except Exception as e:
                logger.debug("Latency fallback via buffer-time failed: %s", e)
                
        # --- 方法 C: 独占模式配置回读 (终极保底) ---
        # 如果以上都失败，但我们处于独占模式，说明延迟是我们自己设定的
        # 直接返回我们保存的配置值 (self.alsa_buffer_time)
        if latency <= 0.001 and self.exclusive_lock_mode:
            # 确保变量存在 (防止初始化前的边缘情况)
            if hasattr(self, 'alsa_buffer_time'):
                latency = float(self.alsa_buffer_time) / 1000000.0
                self.last_latency_source = "config-fallback"
                self.last_latency_seconds = latency
                return latency
            else:
                self.last_latency_source = "default-fallback"
                self.last_latency_seconds = 0.1
                return 0.1 # 如果变量还没初始化，默认返回 100ms

        self.last_latency_source = "none"
        self.last_latency_seconds = latency
        return latency
