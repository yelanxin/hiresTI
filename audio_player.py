import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import logging

class AudioPlayer:
    def __init__(self, on_eos_callback=None, on_tag_callback=None):
        Gst.init(None)
        self.player = Gst.ElementFactory.make("playbin", "player")
        self.bus = self.player.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self._on_message)
        self.on_eos_callback = on_eos_callback
        self.on_tag_callback = on_tag_callback
        self.stream_info = {"codec": "-", "bits": "-", "bitrate": 0}

    def load(self, url):
        if not url: return
        self.player.set_state(Gst.State.NULL)
        self.stream_info = {"codec": "-", "bits": "-", "bitrate": 0}
        self.player.set_property("uri", url)

    def play(self): self.player.set_state(Gst.State.PLAYING)
    def pause(self): self.player.set_state(Gst.State.PAUSED)
    def stop(self): self.player.set_state(Gst.State.NULL)
    
    def is_playing(self):
        _, state, _ = self.player.get_state(0)
        return state == Gst.State.PLAYING

    def seek(self, seconds):
        if seconds < 0: seconds = 0
        self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, int(seconds * Gst.SECOND))

    def set_volume(self, value):
        self.player.set_property("volume", value)

    def get_position(self):
        try:
            _, dur = self.player.query_duration(Gst.Format.TIME)
            _, pos = self.player.query_position(Gst.Format.TIME)
            return (pos / Gst.SECOND if _ else 0), (dur / Gst.SECOND if _ else 0)
        except: return 0, 0

    def get_current_bits(self):
        bits = self.stream_info.get("bits", "-")
        if bits != "-": return bits
        codec = str(self.stream_info.get("codec", "")).upper()
        if "FLAC" in codec:
            # 智能推断：>1.5Mbps 视为 24-bit，否则 16-bit
            return "24-bit" if self.stream_info.get("bitrate", 0) > 1500000 else "16-bit"
        return "-"

    def _on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            if self.on_eos_callback: GLib.idle_add(self.on_eos_callback)
        elif t == Gst.MessageType.TAG:
            taglist = message.parse_tag()
            _, codec = taglist.get_string(Gst.TAG_AUDIO_CODEC)
            if codec: self.stream_info["codec"] = "FLAC" if "FLAC" in codec.upper() else "AAC"
            _, bitrate = taglist.get_uint(Gst.TAG_BITRATE)
            if bitrate: self.stream_info["bitrate"] = bitrate
            _, bits = taglist.get_uint("audio-device-bits")
            if bits: self.stream_info["bits"] = f"{bits}-bit"
            if self.on_tag_callback: GLib.idle_add(self.on_tag_callback, self.stream_info)
