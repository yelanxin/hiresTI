"""MPRIS (Media Player Remote Interfacing Specification) service."""

import logging
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)

BUS_NAME = "org.mpris.MediaPlayer2.hiresti"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
IFACE_ROOT = "org.mpris.MediaPlayer2"
IFACE_PLAYER = "org.mpris.MediaPlayer2.Player"
IFACE_PROPS = "org.freedesktop.DBus.Properties"
IFACE_DBUS = "org.freedesktop.DBus"
DBUS_OBJECT_PATH = "/org/freedesktop/DBus"

_DBUS_REQUEST_NAME = "RequestName"
_DBUS_RELEASE_NAME = "ReleaseName"
_DBUS_NAME_FLAG_NONE = 0
_DBUS_NAME_PRIMARY_OWNER = 1
_DBUS_NAME_ALREADY_OWNER = 4

_INTROSPECTION_XML = """\
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek">
      <arg direction="in" name="Offset" type="x"/>
    </method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/>
      <arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri">
      <arg direction="in" name="Uri" type="s"/>
    </method>
    <signal name="Seeked">
      <arg name="Position" type="x"/>
    </signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="read"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _seconds_to_micros(seconds):
    return int(max(0, round(_safe_float(seconds, 0.0) * 1_000_000.0)))


def track_id_to_object_path(track_id):
    raw = str(track_id or "").strip()
    if not raw:
        raw = "unknown"
    token = "".join(ch if ch.isalnum() else "_" for ch in raw)
    token = token.strip("_") or "unknown"
    if token[0].isdigit():
        token = f"t_{token}"
    return f"/com/hiresti/player/track/{token}"


def play_mode_to_loop_shuffle(play_mode, mode_loop=0, mode_one=1, mode_shuffle=2, mode_smart=3):
    mode = _safe_int(play_mode, mode_loop)
    if mode == _safe_int(mode_one, 1):
        return "Track", False
    if mode in (_safe_int(mode_shuffle, 2), _safe_int(mode_smart, 3)):
        return "Playlist", True
    return "Playlist", False


class MPRISService:
    def __init__(self, app):
        self.app = app
        self._conn = None
        self._node_info = None
        self._reg_ids = []
        self._name_owned = False
        self._started = False
        self._last_position_emit_ts = 0.0
        self._last_position_us = -1
        self._stopped_override = False

    @property
    def started(self):
        return bool(self._started)

    def start(self):
        if self._started:
            return True
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            if self._conn is None:
                logger.info("MPRIS disabled: session DBus connection unavailable.")
                return False

            self._node_info = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION_XML)
            root_info = self._node_info.lookup_interface(IFACE_ROOT)
            player_info = self._node_info.lookup_interface(IFACE_PLAYER)
            if root_info is None or player_info is None:
                logger.warning("MPRIS disabled: failed to parse introspection data.")
                return False

            self._reg_ids.append(
                self._conn.register_object(
                    OBJECT_PATH,
                    root_info,
                    self._on_method_call,
                    self._on_get_property,
                    self._on_set_property,
                )
            )
            self._reg_ids.append(
                self._conn.register_object(
                    OBJECT_PATH,
                    player_info,
                    self._on_method_call,
                    self._on_get_property,
                    self._on_set_property,
                )
            )

            if not self._request_bus_name():
                self.stop()
                return False

            self._started = True
            self.sync_all(force=True)
            logger.info("MPRIS service started: %s", BUS_NAME)
            return True
        except Exception as e:
            logger.info("MPRIS disabled: start failed: %s", e)
            self.stop()
            return False

    def stop(self):
        try:
            if self._conn is not None and self._name_owned:
                try:
                    self._conn.call_sync(
                        IFACE_DBUS,
                        DBUS_OBJECT_PATH,
                        IFACE_DBUS,
                        _DBUS_RELEASE_NAME,
                        GLib.Variant("(s)", (BUS_NAME,)),
                        GLib.VariantType.new("(u)"),
                        Gio.DBusCallFlags.NONE,
                        -1,
                        None,
                    )
                except Exception:
                    pass
        finally:
            self._name_owned = False

        if self._conn is not None:
            for reg_id in list(self._reg_ids):
                try:
                    self._conn.unregister_object(reg_id)
                except Exception:
                    pass
        self._reg_ids = []
        self._conn = None
        self._node_info = None
        self._started = False
        self._last_position_emit_ts = 0.0
        self._last_position_us = -1

    def sync_all(self, force=False):
        if not self._started:
            return
        self.sync_metadata()
        self.sync_playback()
        self.sync_volume()
        self.sync_position(force=force)

    def sync_metadata(self):
        if not self._started:
            return
        loop_status, shuffle = self._loop_shuffle()
        changes = {
            "LoopStatus": GLib.Variant("s", loop_status),
            "Shuffle": GLib.Variant("b", bool(shuffle)),
            "Metadata": self._metadata_variant(),
            "CanGoNext": GLib.Variant("b", self._can_go_next()),
            "CanGoPrevious": GLib.Variant("b", self._can_go_previous()),
            "CanSeek": GLib.Variant("b", self._can_seek()),
            "CanPlay": GLib.Variant("b", self._can_play()),
            "CanPause": GLib.Variant("b", self._can_pause()),
            "CanControl": GLib.Variant("b", True),
        }
        self._emit_properties_changed(IFACE_PLAYER, changes)

    def sync_playback(self):
        if not self._started:
            return
        playback = self._playback_status()
        changes = {
            "PlaybackStatus": GLib.Variant("s", playback),
            "CanPlay": GLib.Variant("b", self._can_play()),
            "CanPause": GLib.Variant("b", self._can_pause()),
            "CanControl": GLib.Variant("b", True),
        }
        self._emit_properties_changed(IFACE_PLAYER, changes)

    def sync_volume(self):
        if not self._started:
            return
        self._emit_properties_changed(
            IFACE_PLAYER,
            {"Volume": GLib.Variant("d", self._volume())},
        )

    def sync_position(self, force=False):
        if not self._started:
            return
        now = time.monotonic()
        interval = 0.25 if self._is_playing() else 0.8
        if (not force) and (now - self._last_position_emit_ts) < interval:
            return
        pos_us = self._position_us()
        if (not force) and self._last_position_us >= 0 and abs(pos_us - self._last_position_us) < 100_000:
            return
        self._last_position_emit_ts = now
        self._last_position_us = pos_us
        self._emit_properties_changed(
            IFACE_PLAYER,
            {"Position": GLib.Variant("x", pos_us)},
        )

    def emit_seeked(self, position_seconds=None):
        if not self._started or self._conn is None:
            return
        if position_seconds is None:
            pos_us = self._position_us()
        else:
            pos_us = _seconds_to_micros(position_seconds)
        try:
            self._conn.emit_signal(
                None,
                OBJECT_PATH,
                IFACE_PLAYER,
                "Seeked",
                GLib.Variant("(x)", (pos_us,)),
            )
        except Exception:
            logger.debug("Failed to emit MPRIS Seeked signal", exc_info=True)
        self.sync_position(force=True)

    def _request_bus_name(self):
        if self._conn is None:
            return False
        try:
            reply = self._conn.call_sync(
                IFACE_DBUS,
                DBUS_OBJECT_PATH,
                IFACE_DBUS,
                _DBUS_REQUEST_NAME,
                GLib.Variant("(su)", (BUS_NAME, _DBUS_NAME_FLAG_NONE)),
                GLib.VariantType.new("(u)"),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            result = _safe_int(reply.unpack()[0], 0)
            self._name_owned = result in (_DBUS_NAME_PRIMARY_OWNER, _DBUS_NAME_ALREADY_OWNER)
            if not self._name_owned:
                logger.info("MPRIS disabled: bus name unavailable (%s)", result)
            return self._name_owned
        except Exception as e:
            logger.info("MPRIS disabled: request name failed: %s", e)
            self._name_owned = False
            return False

    def _emit_properties_changed(self, iface_name, changed):
        if self._conn is None or not changed:
            return
        try:
            payload = GLib.Variant("(sa{sv}as)", (iface_name, changed, []))
            self._conn.emit_signal(None, OBJECT_PATH, IFACE_PROPS, "PropertiesChanged", payload)
        except Exception:
            logger.debug("Failed to emit MPRIS PropertiesChanged for %s", iface_name, exc_info=True)

    def _run_on_main(self, fn, *args):
        def _task():
            try:
                fn(*args)
            except Exception:
                logger.exception("MPRIS action failed")
            return False

        GLib.idle_add(_task)

    def _on_method_call(
        self,
        _connection,
        _sender,
        _object_path,
        interface_name,
        method_name,
        parameters,
        invocation,
    ):
        try:
            if interface_name == IFACE_ROOT:
                self._handle_root_method(method_name, invocation)
                return
            if interface_name == IFACE_PLAYER:
                self._handle_player_method(method_name, parameters, invocation)
                return
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", f"Unknown interface: {interface_name}")
        except Exception as e:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.Failed", str(e))

    def _on_get_property(self, _connection, _sender, _object_path, interface_name, property_name):
        if interface_name == IFACE_ROOT:
            return self._root_property_variant(property_name)
        if interface_name == IFACE_PLAYER:
            return self._player_property_variant(property_name)
        return None

    def _on_set_property(self, _connection, _sender, _object_path, interface_name, property_name, value):
        if interface_name != IFACE_PLAYER:
            return False
        try:
            if property_name == "Volume":
                self._run_on_main(self._apply_volume, _safe_float(value.unpack(), self._volume()))
                return True
            if property_name == "Shuffle":
                self._run_on_main(self._apply_shuffle, bool(value.unpack()))
                return True
            if property_name == "LoopStatus":
                self._run_on_main(self._apply_loop_status, str(value.unpack() or "Playlist"))
                return True
        except Exception:
            return False
        return False

    def _handle_root_method(self, method_name, invocation):
        if method_name == "Raise":
            self._run_on_main(self._action_raise)
            invocation.return_value(None)
            return
        if method_name == "Quit":
            self._run_on_main(self._action_quit)
            invocation.return_value(None)
            return
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method_name)

    def _handle_player_method(self, method_name, parameters, invocation):
        if method_name == "Next":
            self._run_on_main(self._action_next)
            invocation.return_value(None)
            return
        if method_name == "Previous":
            self._run_on_main(self._action_previous)
            invocation.return_value(None)
            return
        if method_name == "Pause":
            self._run_on_main(self._action_pause)
            invocation.return_value(None)
            return
        if method_name == "PlayPause":
            self._run_on_main(self._action_play_pause)
            invocation.return_value(None)
            return
        if method_name == "Stop":
            self._run_on_main(self._action_stop)
            invocation.return_value(None)
            return
        if method_name == "Play":
            self._run_on_main(self._action_play)
            invocation.return_value(None)
            return
        if method_name == "Seek":
            offset_us = _safe_int(parameters.unpack()[0], 0)
            self._run_on_main(self._action_seek, offset_us)
            invocation.return_value(None)
            return
        if method_name == "SetPosition":
            track_path, position_us = parameters.unpack()
            self._run_on_main(self._action_set_position, str(track_path or ""), _safe_int(position_us, 0))
            invocation.return_value(None)
            return
        if method_name == "OpenUri":
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.NotSupported",
                "OpenUri is not supported",
            )
            return
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method_name)

    def _root_property_variant(self, name):
        if name == "CanQuit":
            return GLib.Variant("b", True)
        if name == "CanRaise":
            return GLib.Variant("b", True)
        if name == "HasTrackList":
            return GLib.Variant("b", False)
        if name == "Identity":
            return GLib.Variant("s", "HiresTI")
        if name == "DesktopEntry":
            return GLib.Variant("s", "com.hiresti.player")
        if name == "SupportedUriSchemes":
            return GLib.Variant("as", [])
        if name == "SupportedMimeTypes":
            return GLib.Variant("as", [])
        return None

    def _player_property_variant(self, name):
        if name == "PlaybackStatus":
            return GLib.Variant("s", self._playback_status())
        if name == "LoopStatus":
            return GLib.Variant("s", self._loop_shuffle()[0])
        if name == "Rate":
            return GLib.Variant("d", 1.0)
        if name == "Shuffle":
            return GLib.Variant("b", self._loop_shuffle()[1])
        if name == "Metadata":
            return self._metadata_variant()
        if name == "Volume":
            return GLib.Variant("d", self._volume())
        if name == "Position":
            return GLib.Variant("x", self._position_us())
        if name == "MinimumRate":
            return GLib.Variant("d", 1.0)
        if name == "MaximumRate":
            return GLib.Variant("d", 1.0)
        if name == "CanGoNext":
            return GLib.Variant("b", self._can_go_next())
        if name == "CanGoPrevious":
            return GLib.Variant("b", self._can_go_previous())
        if name == "CanPlay":
            return GLib.Variant("b", self._can_play())
        if name == "CanPause":
            return GLib.Variant("b", self._can_pause())
        if name == "CanSeek":
            return GLib.Variant("b", self._can_seek())
        if name == "CanControl":
            return GLib.Variant("b", True)
        return None

    def _active_queue(self):
        getter = getattr(self.app, "_get_active_queue", None)
        if callable(getter):
            try:
                return list(getter() or [])
            except Exception:
                return []
        return list(getattr(self.app, "current_track_list", []) or [])

    def _current_track(self):
        track = getattr(self.app, "playing_track", None)
        if track is not None:
            return track
        queue = self._active_queue()
        idx = _safe_int(getattr(self.app, "current_track_index", -1), -1)
        if idx < 0:
            idx = _safe_int(getattr(self.app, "current_index", -1), -1)
        if 0 <= idx < len(queue):
            return queue[idx]
        return None

    def _current_track_path(self):
        track = self._current_track()
        if track is None:
            return track_id_to_object_path("unknown")
        return track_id_to_object_path(getattr(track, "id", None))

    def _metadata_variant(self):
        track = self._current_track()
        metadata = {
            "mpris:trackid": GLib.Variant("o", self._current_track_path()),
        }
        if track is not None:
            title = str(getattr(track, "name", "") or "").strip()
            artist = str(getattr(getattr(track, "artist", None), "name", "") or "").strip()
            album = str(getattr(getattr(track, "album", None), "name", "") or "").strip()
            if title:
                metadata["xesam:title"] = GLib.Variant("s", title)
            if artist:
                metadata["xesam:artist"] = GLib.Variant("as", [artist])
                metadata["xesam:albumArtist"] = GLib.Variant("as", [artist])
            if album:
                metadata["xesam:album"] = GLib.Variant("s", album)
            art_url = ""
            backend = getattr(self.app, "backend", None)
            if backend is not None:
                get_artwork = getattr(backend, "get_artwork_url", None)
                if callable(get_artwork):
                    try:
                        art_url = str(get_artwork(track, 640) or "").strip()
                    except Exception:
                        art_url = ""
            if art_url:
                metadata["mpris:artUrl"] = GLib.Variant("s", art_url)
            duration_us = self._duration_us()
            if duration_us > 0:
                metadata["mpris:length"] = GLib.Variant("x", duration_us)
        return GLib.Variant("a{sv}", metadata)

    def _mode_constants(self):
        return (
            _safe_int(getattr(self.app, "MODE_LOOP", 0), 0),
            _safe_int(getattr(self.app, "MODE_ONE", 1), 1),
            _safe_int(getattr(self.app, "MODE_SHUFFLE", 2), 2),
            _safe_int(getattr(self.app, "MODE_SMART", 3), 3),
        )

    def _loop_shuffle(self):
        mode_loop, mode_one, mode_shuffle, mode_smart = self._mode_constants()
        play_mode = _safe_int(getattr(self.app, "play_mode", mode_loop), mode_loop)
        return play_mode_to_loop_shuffle(play_mode, mode_loop, mode_one, mode_shuffle, mode_smart)

    def _set_play_mode(self, new_mode):
        mode = _safe_int(new_mode, getattr(self.app, "MODE_LOOP", 0))
        self.app.play_mode = mode
        mode_btn = getattr(self.app, "mode_btn", None)
        mode_icons = getattr(self.app, "MODE_ICONS", {})
        mode_tips = getattr(self.app, "MODE_TOOLTIPS", {})
        if mode_btn is not None:
            try:
                mode_btn.set_icon_name(mode_icons.get(mode, "hiresti-mode-loop-symbolic"))
                mode_btn.set_tooltip_text(mode_tips.get(mode, "Loop"))
            except Exception:
                pass
        mode_shuffle = _safe_int(getattr(self.app, "MODE_SHUFFLE", 2), 2)
        mode_smart = _safe_int(getattr(self.app, "MODE_SMART", 3), 3)
        if mode in (mode_shuffle, mode_smart):
            gen = getattr(self.app, "_generate_shuffle_list", None)
            if callable(gen):
                try:
                    gen()
                except Exception:
                    pass
        else:
            self.app.shuffle_indices = []
        settings = getattr(self.app, "settings", None)
        if isinstance(settings, dict):
            settings["play_mode"] = mode
        saver = getattr(self.app, "schedule_save_settings", None)
        if callable(saver):
            try:
                saver()
            except Exception:
                pass
        self.sync_metadata()

    def _apply_loop_status(self, loop_status):
        loop = str(loop_status or "Playlist")
        mode_loop, mode_one, mode_shuffle, mode_smart = self._mode_constants()
        cur_mode = _safe_int(getattr(self.app, "play_mode", mode_loop), mode_loop)
        if loop == "Track":
            self._set_play_mode(mode_one)
            return
        if loop == "Playlist":
            if cur_mode in (mode_shuffle, mode_smart):
                self._set_play_mode(mode_shuffle)
            else:
                self._set_play_mode(mode_loop)
            return
        self._set_play_mode(mode_loop)

    def _apply_shuffle(self, enabled):
        on = bool(enabled)
        mode_loop, _mode_one, mode_shuffle, mode_smart = self._mode_constants()
        cur_mode = _safe_int(getattr(self.app, "play_mode", mode_loop), mode_loop)
        if on:
            if cur_mode not in (mode_shuffle, mode_smart):
                self._set_play_mode(mode_shuffle)
            return
        if cur_mode in (mode_shuffle, mode_smart):
            self._set_play_mode(mode_loop)

    def _volume(self):
        scale = getattr(self.app, "vol_scale", None)
        if scale is not None:
            try:
                return max(0.0, min(1.0, _safe_float(scale.get_value(), 0.0) / 100.0))
            except Exception:
                pass
        settings = getattr(self.app, "settings", None)
        if isinstance(settings, dict):
            return max(0.0, min(1.0, _safe_float(settings.get("volume", 80), 80.0) / 100.0))
        return 0.8

    def _apply_volume(self, normalized):
        if bool(getattr(getattr(self.app, "settings", None), "get", lambda *_args, **_kwargs: False)("bit_perfect", False)):
            self.sync_volume()
            return
        vol = max(0.0, min(1.0, _safe_float(normalized, self._volume())))
        scale = getattr(self.app, "vol_scale", None)
        if scale is not None:
            try:
                scale.set_value(vol * 100.0)
            except Exception:
                pass
        else:
            player = getattr(self.app, "player", None)
            if player is not None:
                try:
                    player.set_volume(vol)
                except Exception:
                    pass
            settings = getattr(self.app, "settings", None)
            if isinstance(settings, dict):
                settings["volume"] = int(round(vol * 100.0))
            saver = getattr(self.app, "schedule_save_settings", None)
            if callable(saver):
                try:
                    saver()
                except Exception:
                    pass
        self.sync_volume()

    def _position_pair(self):
        player = getattr(self.app, "player", None)
        if player is None:
            return 0.0, 0.0
        try:
            pos, dur = player.get_position()
            return max(0.0, _safe_float(pos, 0.0)), max(0.0, _safe_float(dur, 0.0))
        except Exception:
            return 0.0, 0.0

    def _position_us(self):
        pos, _dur = self._position_pair()
        return _seconds_to_micros(pos)

    def _duration_us(self):
        _pos, dur = self._position_pair()
        return _seconds_to_micros(dur)

    def _is_playing(self):
        player = getattr(self.app, "player", None)
        if player is None:
            return False
        try:
            return bool(player.is_playing())
        except Exception:
            return False

    def _can_play(self):
        if self._active_queue():
            return True
        return self._current_track() is not None

    def _can_pause(self):
        return self._can_play()

    def _can_seek(self):
        return self._duration_us() > 0

    def _can_go_next(self):
        return len(self._active_queue()) > 1

    def _can_go_previous(self):
        return len(self._active_queue()) > 1

    def _playback_status(self):
        if self._is_playing():
            self._stopped_override = False
            return "Playing"
        if self._stopped_override:
            return "Stopped"
        if self._current_track() is not None:
            return "Paused"
        return "Stopped"

    def _action_raise(self):
        win = getattr(self.app, "win", None)
        if win is not None:
            try:
                win.present()
            except Exception:
                pass

    def _action_quit(self):
        try:
            self.app._allow_window_close = True
        except Exception:
            pass
        quitter = getattr(self.app, "quit", None)
        if callable(quitter):
            quitter()

    def _action_next(self):
        self._stopped_override = False
        fn = getattr(self.app, "on_next_track", None)
        if callable(fn):
            fn(None)
        self.sync_metadata()
        self.sync_playback()

    def _action_previous(self):
        self._stopped_override = False
        fn = getattr(self.app, "on_prev_track", None)
        if callable(fn):
            fn(None)
        self.sync_metadata()
        self.sync_playback()

    def _action_play_pause(self):
        self._stopped_override = False
        fn = getattr(self.app, "on_play_pause", None)
        if callable(fn):
            fn(getattr(self.app, "play_btn", None))
        self.sync_playback()
        self.sync_position(force=True)

    def _action_pause(self):
        player = getattr(self.app, "player", None)
        if player is not None and self._is_playing():
            try:
                player.pause()
            except Exception:
                pass
        play_btn = getattr(self.app, "play_btn", None)
        if play_btn is not None:
            try:
                play_btn.set_icon_name("media-playback-start-symbolic")
            except Exception:
                pass
        self.sync_playback()
        self.sync_position(force=True)

    def _action_play(self):
        if self._is_playing():
            return
        self._stopped_override = False
        player = getattr(self.app, "player", None)
        play_track = getattr(self.app, "play_track", None)
        track = self._current_track()
        if track is not None and player is not None:
            try:
                player.play()
            except Exception:
                pass
        elif callable(play_track):
            queue = self._active_queue()
            if queue:
                idx = _safe_int(getattr(self.app, "current_track_index", 0), 0)
                if idx < 0 or idx >= len(queue):
                    idx = 0
                play_track(idx)
        self.sync_playback()
        self.sync_position(force=True)

    def _action_stop(self):
        player = getattr(self.app, "player", None)
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass
        play_btn = getattr(self.app, "play_btn", None)
        if play_btn is not None:
            try:
                play_btn.set_icon_name("media-playback-start-symbolic")
            except Exception:
                pass
        self._stopped_override = True
        self.sync_playback()
        self.sync_position(force=True)

    def _action_seek(self, offset_us):
        player = getattr(self.app, "player", None)
        if player is None:
            return
        cur_us = self._position_us()
        target_us = max(0, int(cur_us + _safe_int(offset_us, 0)))
        try:
            player.seek(float(target_us) / 1_000_000.0)
            self._stopped_override = False
            self.emit_seeked(float(target_us) / 1_000_000.0)
            self.sync_playback()
        except Exception:
            pass

    def _action_set_position(self, track_path, position_us):
        expected = self._current_track_path()
        if str(track_path or "") != str(expected):
            return
        player = getattr(self.app, "player", None)
        if player is None:
            return
        target_us = max(0, _safe_int(position_us, 0))
        try:
            player.seek(float(target_us) / 1_000_000.0)
            self._stopped_override = False
            self.emit_seeked(float(target_us) / 1_000_000.0)
            self.sync_playback()
        except Exception:
            pass
