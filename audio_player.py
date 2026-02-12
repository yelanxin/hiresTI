import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

class AudioPlayer:
    def __init__(self, on_eos_callback=None, on_tag_callback=None):
        Gst.init(None)
        
        self.player = Gst.ElementFactory.make("playbin", "player")
        self.current_sink = Gst.ElementFactory.make("autoaudiosink", "audio_sink")
        self.player.set_property("audio-sink", self.current_sink)

        # [EQ] Initialize 10-Band Equalizer
        self.equalizer = Gst.ElementFactory.make("equalizer-10bands", "equalizer")
        if self.equalizer:
            self.player.set_property("audio-filter", self.equalizer)
            print("[Audio] Equalizer-10bands initialized and attached.")
        else:
            print("[Audio] Warning: equalizer-10bands not found. EQ disabled.")
        
        self.bus = self.player.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self._on_message)
        
        self.on_eos_callback = on_eos_callback
        self.on_tag_callback = on_tag_callback
        
        self.stream_info = {
            "codec": "-", "bitrate": 0, "bits": "-", "rate": "-", 
            "output_bits": "-", "output_rate": "-"
        }
        
        self.current_driver = "Auto"
        self.is_auto = True
        
        self.monitor = Gst.DeviceMonitor()
        self.monitor.add_filter("Audio/Sink", None)
        self.monitor.start()
        
        GLib.timeout_add(500, self._poll_leaf_sink_caps)

    # --- [修正] Bit-Perfect Logic ---
    def toggle_bit_perfect(self, enable):
        """Smart Switch: Auto-lock to USB DAC and BYPASS EQ"""
        if not enable:
            # [Fix] 关闭时只恢复 EQ，不要强制设置 Auto
            # 让上层 UI (main.py) 决定切回哪个驱动
            if self.equalizer:
                self.player.set_property("audio-filter", self.equalizer)
                print("[Audio] EQ Restored.")
            return None

        print("[Audio] Engaging Bit-Perfect Mode (Bypassing EQ)...")
        
        # 1. Bypass EQ (Crucial for Bit-Perfect)
        self.player.set_property("audio-filter", None)
        
        # 2. Find Hardware
        devices = self.get_devices_for_driver("ALSA")
        target_dev = None
        target_name = ""

        # Priority: USB Hardware > Other Hardware
        for d in devices:
            if "hw:" in d["name"] and "USB" in d["name"]:
                target_dev = d["device_id"]; target_name = d["name"]; break
        
        if not target_dev:
            for d in devices:
                if "hw:" in d["name"] and "HDMI" not in d["name"]:
                    target_dev = d["device_id"]; target_name = d["name"]; break
        
        if not target_dev:
            for d in devices:
                 if "hw:" in d["name"]:
                    target_dev = d["device_id"]; target_name = d["name"]; break

        if target_dev:
            print(f"[Audio] Locked to: {target_name}")
            self.set_output("ALSA", target_dev)
            return target_name
        else:
            print("[Audio] No suitable DAC found.")
            # Restore EQ if fail
            if self.equalizer: self.player.set_property("audio-filter", self.equalizer)
            self.set_output("Auto")
            return None

    # --- Deep Drill Logic ---
    def _get_leaf_sink(self, bin_element):
        if not isinstance(bin_element, Gst.Bin): return bin_element
        iterator = bin_element.iterate_sinks()
        while True:
            result, elem = iterator.next()
            if result != Gst.IteratorResult.OK: break
            leaf = self._get_leaf_sink(elem)
            if leaf: return leaf
        return None

    def _poll_leaf_sink_caps(self):
        if self.player.get_state(0).state != Gst.State.PLAYING: return True
        try:
            leaf_sink = self._get_leaf_sink(self.current_sink)
            if leaf_sink:
                if self.is_auto:
                    factory = leaf_sink.get_factory()
                    if factory:
                        fname = factory.get_name()
                        if "pulse" in fname: self.current_driver = "PulseAudio (Auto)"
                        elif "pipewire" in fname: self.current_driver = "PipeWire (Auto)"
                        elif "alsa" in fname: self.current_driver = "ALSA (Auto)"
                        elif "wasapi" in fname: self.current_driver = "WASAPI (Auto)"
                        elif "osx" in fname: self.current_driver = "CoreAudio (Auto)"
                
                pad = leaf_sink.get_static_pad("sink")
                if pad:
                    caps = pad.get_current_caps()
                    if caps: self._parse_caps(caps)
        except: pass
        return True

    def _parse_caps(self, caps):
        try:
            struct = caps.get_structure(0)
            fmt = struct.get_value("format")
            out_bits = "-"
            if fmt:
                if "S16" in fmt: out_bits = "16bit"
                elif "S24" in fmt: out_bits = "24bit"
                elif "S32" in fmt or "F32" in fmt: out_bits = "32bit"
                elif "F64" in fmt: out_bits = "64bit"
            
            out_rate = "-"
            if struct.has_field("rate"):
                r = struct.get_value("rate")
                if r: out_rate = f"{r/1000:.1f}kHz"
            
            if out_bits != "-" and out_rate != "-":
                changed = (out_bits != self.stream_info["output_bits"]) or \
                          (out_rate != self.stream_info["output_rate"])
                if changed:
                    self.stream_info["output_bits"] = out_bits
                    self.stream_info["output_rate"] = out_rate
                    if self.on_tag_callback:
                        GLib.idle_add(self.on_tag_callback, self.stream_info)
        except: pass

    def get_drivers(self):
        drivers = ["Auto (Default)"]
        sinks = [("pipewiresink", "PipeWire"), ("pulsesink", "PulseAudio"), ("alsasink", "ALSA")]
        for factory_name, label in sinks:
            if Gst.ElementFactory.find(factory_name): drivers.append(label)
        return drivers

    def get_devices_for_driver(self, driver_label):
        if "Auto" in driver_label: return [{"name": "System Default", "device_id": None}]
        devices = []
        self.monitor.start()
        detected = self.monitor.get_devices()
        for d in detected:
            if d.get_device_class() != "Audio/Sink": continue
            name = d.get_display_name(); props = d.get_properties()
            api = props.get_string("device.api") if props.has_field("device.api") else "unknown"
            is_match = False; hw_string = ""
            if "ALSA" in driver_label:
                if api == "alsa" or props.has_field("alsa.card"):
                    is_match = True
                    if props.has_field("device.str"): hw_string = props.get_string("device.str")
                    if not hw_string and props.has_field("alsa.card") and props.has_field("alsa.device"):
                        try: hw_string = f"hw:{props.get_value('alsa.card')},{props.get_value('alsa.device')}"
                        except: pass
            elif "Pulse" in driver_label:
                if api == "pulse" or "Pulse" in name: is_match = True
            elif "PipeWire" in driver_label: is_match = True
            if is_match:
                lbl = f"{name} ({hw_string})" if hw_string else name
                devices.append({"name": lbl, "device_id": d})
        devices.insert(0, {"name": "Default Device", "device_id": None})
        return devices

    def set_output(self, driver_label, device_obj=None):
        state = self.player.get_state(0).state
        was_playing = (state == Gst.State.PLAYING)
        self.player.set_state(Gst.State.NULL)
        
        if "PipeWire" in driver_label:
            self.current_driver = "PipeWire"
            self.is_auto = False
        elif "Pulse" in driver_label:
            self.current_driver = "PulseAudio"
            self.is_auto = False
        elif "ALSA" in driver_label:
            self.current_driver = "ALSA"
            self.is_auto = False
        else:
            self.current_driver = "Auto"
            self.is_auto = True
        
        factory_name = "autoaudiosink"
        if "PipeWire" in driver_label: factory_name = "pipewiresink"
        elif "Pulse" in driver_label: factory_name = "pulsesink"
        elif "ALSA" in driver_label: factory_name = "alsasink"
        
        print(f"[Audio] Switching to: {factory_name}")
        try:
            new_sink = None
            if device_obj and isinstance(device_obj, Gst.Device):
                new_sink = device_obj.create_element("audio_sink")
            else:
                new_sink = Gst.ElementFactory.make(factory_name, "audio_sink")
            if new_sink:
                self.player.set_property("audio-sink", new_sink)
                self.current_sink = new_sink
            else:
                self.current_sink = Gst.ElementFactory.make("autoaudiosink", "audio_sink")
                self.player.set_property("audio-sink", self.current_sink)
        except: pass
        if was_playing: self.player.set_state(Gst.State.PLAYING)

    def load(self, url):
        self.player.set_state(Gst.State.NULL)
        self.player.set_property("uri", url)
        self.stream_info = {"codec": "-", "bitrate": 0, "bits": "-", "rate": "-", "output_bits": "-", "output_rate": "-"}
        if self.on_tag_callback: GLib.idle_add(self.on_tag_callback, self.stream_info)

    def play(self): self.player.set_state(Gst.State.PLAYING)
    def pause(self): self.player.set_state(Gst.State.PAUSED)
    def is_playing(self): return self.player.get_state(0).state == Gst.State.PLAYING
    def get_position(self):
        try:
            succ, pos = self.player.query_position(Gst.Format.TIME)
            succ2, dur = self.player.query_duration(Gst.Format.TIME)
            if succ and succ2: return (pos / Gst.SECOND, dur / Gst.SECOND)
        except: pass
        return (0, 0)
    def seek(self, seconds):
        self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, int(seconds * Gst.SECOND))
    def set_volume(self, val): self.player.set_property("volume", val)

    def get_format_string(self):
        s_bits = self.stream_info.get("bits", "-")
        s_rate = self.stream_info.get("rate", "-")
        o_bits = self.stream_info.get("output_bits", "-")
        o_rate = self.stream_info.get("output_rate", "-")
        if s_rate == "-" and o_rate != "-": s_rate = o_rate
        if s_bits == "-" and o_bits != "-": s_bits = o_bits
        src_str = f"{s_bits}/{s_rate}" if s_rate != "-" else s_bits
        out_str = f"{o_bits}/{o_rate}" if o_rate != "-" else o_bits
        if src_str == "-" and out_str == "-": return "-"
        return f"{src_str} -> {self.current_driver} | {out_str}"

    def _on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            if self.on_eos_callback: GLib.idle_add(self.on_eos_callback)
        elif t == Gst.MessageType.TAG:
            taglist = message.parse_tag()
            is_lossy = False
            success, codec = taglist.get_string("audio-codec")
            if not success and hasattr(Gst, "TAG_AUDIO_CODEC"): success, codec = taglist.get_string(Gst.TAG_AUDIO_CODEC)
            if success and codec:
                c_upper = codec.upper()
                if "FLAC" in c_upper: self.stream_info["codec"] = "FLAC"
                elif "MPEG-4 AAC" in c_upper or "MP4A" in c_upper: self.stream_info["codec"] = "AAC"; is_lossy = True
                else: self.stream_info["codec"] = codec.split()[0]
            success, bitrate = taglist.get_uint("bitrate")
            if not success and hasattr(Gst, "TAG_BITRATE"): success, bitrate = taglist.get_uint(Gst.TAG_BITRATE)
            if success and bitrate: self.stream_info["bitrate"] = bitrate
            for key in ["rate", "sample-rate", "audio-sample-rate"]:
                success, rate = taglist.get_uint(key)
                if success and rate > 0: self.stream_info["rate"] = f"{rate/1000:.1f}kHz"; break
            success, bits = taglist.get_uint("audio-device-bits")
            if not success: success, bits = taglist.get_uint("bits-per-sample")
            if success and bits: self.stream_info["bits"] = f"{bits}bit"
            elif is_lossy: self.stream_info["bits"] = "16bit"
            elif self.stream_info["codec"] == "FLAC":
                br = self.stream_info.get("bitrate", 0)
                if br > 1200000: self.stream_info["bits"] = "24bit"
                elif br > 0: self.stream_info["bits"] = "16bit"
            if self.on_tag_callback: GLib.idle_add(self.on_tag_callback, self.stream_info)
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer Error: {err.message}")

    # --- EQ Controls ---
    def set_eq_band(self, band_idx, gain_db):
        if not self.equalizer: return
        if 0 <= band_idx <= 9:
            try:
                gain_db = max(-24.0, min(12.0, float(gain_db)))
                self.equalizer.set_property(f"band{band_idx}", gain_db)
            except: pass

    def reset_eq(self):
        if not self.equalizer: return
        for i in range(10): self.set_eq_band(i, 0.0)

    def get_eq_bands(self):
        if not self.equalizer: return [0.0]*10
        return [self.equalizer.get_property(f"band{i}") for i in range(10)]
