import hashlib
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")
pytest.importorskip("cairo")

from app import app_now_playing
from actions import playback_stream_actions


class _Progress:
    def __init__(self):
        self.fraction = None
        self.set_fraction_calls = 0

    def set_fraction(self, value):
        self.fraction = float(value)
        self.set_fraction_calls += 1


class _Label:
    def __init__(self):
        self.text = None
        self.tooltip = None
        self.set_text_calls = 0

    def set_text(self, value):
        self.text = str(value)
        self.set_text_calls += 1

    def set_tooltip_text(self, value):
        self.tooltip = None if value is None else str(value)


class _Button:
    def __init__(self):
        self.icon_name = None
        self.set_icon_calls = 0

    def set_icon_name(self, value):
        self.icon_name = str(value)
        self.set_icon_calls += 1


class _SensitiveButton:
    def __init__(self):
        self.sensitive = None
        self.set_sensitive_calls = 0

    def set_sensitive(self, value):
        self.sensitive = bool(value)
        self.set_sensitive_calls += 1


class _NavRow:
    def __init__(self, nav_id):
        self.nav_id = str(nav_id)
        self._next = None

    def get_next_sibling(self):
        return self._next


class _NavList:
    def __init__(self, nav_ids):
        self._rows = [_NavRow(nav_id) for nav_id in nav_ids]
        for left, right in zip(self._rows, self._rows[1:]):
            left._next = right
        self.selected = None

    def get_first_child(self):
        return self._rows[0] if self._rows else None

    def select_row(self, row):
        self.selected = row


class _Stack:
    def __init__(self, visible_child_name):
        self._visible_child_name = str(visible_child_name)
        self.set_calls = []

    def get_visible_child_name(self):
        return self._visible_child_name

    def set_visible_child_name(self, value):
        self._visible_child_name = str(value)
        self.set_calls.append(str(value))


class _CssWidget:
    def __init__(self):
        self.add_calls = 0
        self.remove_calls = 0
        self.markup_calls = 0
        self.active = False

    def add_css_class(self, _name):
        self.add_calls += 1
        self.active = True

    def remove_css_class(self, _name):
        self.remove_calls += 1
        self.active = False

    def set_markup(self, _markup):
        self.markup_calls += 1


class _ToggleTarget:
    def __init__(self):
        self.visible = []
        self.can_target = []

    def set_visible(self, value):
        self.visible.append(bool(value))

    def set_can_target(self, value):
        self.can_target.append(bool(value))


class _CssClassTarget:
    def __init__(self):
        self.classes = set()

    def add_css_class(self, value):
        self.classes.add(str(value))

    def remove_css_class(self, value):
        self.classes.discard(str(value))


class _Revealer(_ToggleTarget):
    def __init__(self):
        super().__init__()
        self.reveal_child = []

    def set_reveal_child(self, value):
        self.reveal_child.append(bool(value))

    def get_transition_duration(self):
        return 260


class _FocusButton:
    def __init__(self):
        self.grab_focus_calls = 0

    def grab_focus(self):
        self.grab_focus_calls += 1


class _Player:
    def get_position(self):
        return (15.0, 180.0)

    def is_playing(self):
        return True


class _CssProvider:
    def __init__(self):
        self.loaded = b""

    def load_from_data(self, data):
        self.loaded = bytes(data)


class _SizedWidget:
    def __init__(self, width=0, width_request=0):
        self._width = int(width)
        self._width_request = int(width_request)

    def get_width(self):
        return self._width

    def get_width_request(self):
        return self._width_request


class _Area:
    def __init__(self):
        self._target_url = ""
        self._cover_pixbuf = None
        self._cover_dark_rgb = None
        self._cover_cache_key = None
        self._cover_cache_surface = None
        self.queue_draw_calls = 0

    def queue_draw(self):
        self.queue_draw_calls += 1


def test_overlay_tick_updates_progress_without_resizing(monkeypatch):
    lyric_positions = []
    app = SimpleNamespace(
        now_playing_progress=_Progress(),
        now_playing_elapsed_label=_Label(),
        now_playing_total_label=_Label(),
        now_playing_play_btn=_Button(),
        _sync_now_playing_surface_size=lambda: (_ for _ in ()).throw(AssertionError("unexpected resize")),
        _sync_now_playing_lyrics=lambda pos: lyric_positions.append(float(pos)),
    )

    monkeypatch.setattr(app_now_playing, "is_now_playing_overlay_open", lambda _app: True)

    app_now_playing._sync_now_playing_overlay_state(app, 12.4, 120.0, True)
    app_now_playing._sync_now_playing_overlay_state(app, 12.4, 120.0, True)

    assert app.now_playing_progress.fraction == pytest.approx(12.4 / 120.0)
    assert app.now_playing_progress.set_fraction_calls == 1
    assert app.now_playing_elapsed_label.text == "0:12"
    assert app.now_playing_elapsed_label.set_text_calls == 1
    assert app.now_playing_total_label.text == "2:00"
    assert app.now_playing_total_label.set_text_calls == 1
    assert app.now_playing_play_btn.icon_name == "media-playback-pause-symbolic"
    assert app.now_playing_play_btn.set_icon_calls == 1
    assert lyric_positions == [12.4, 12.4]


def test_hidden_now_playing_lyrics_tab_skips_lyric_work(monkeypatch):
    widget = _CssWidget()
    main = _CssWidget()
    app = SimpleNamespace(
        now_playing_stack=_Stack("queue"),
        lyrics_mgr=SimpleNamespace(has_synced=True),
        now_playing_lyric_widgets=[
            {
                "time": 0.0,
                "widget": widget,
                "main": main,
                "sub": None,
                "karaoke_words": [],
                "karaoke_last_idx": -1,
            }
        ],
        current_now_playing_lyric_index=-1,
        lyrics_user_offset_ms=0,
        now_playing_lyrics_scroller=None,
    )

    monkeypatch.setattr(app_now_playing, "is_now_playing_overlay_open", lambda _app: True)

    app_now_playing._sync_now_playing_lyrics(app, 5.0)

    assert app.current_now_playing_lyric_index == -1
    assert widget.add_calls == 0
    assert widget.remove_calls == 0
    assert main.add_calls == 0
    assert main.remove_calls == 0
    assert main.markup_calls == 0


def test_show_overlay_reuses_current_snapshot_for_smoother_reveal(monkeypatch):
    calls = []
    app = SimpleNamespace(
        playing_track=SimpleNamespace(id="track-1", duration=180),
        is_mini_mode=False,
        close_queue_drawer=lambda: calls.append("close_queue"),
        _sync_now_playing_surface_size=lambda: calls.append("size"),
        _refresh_now_playing_from_track=lambda: calls.append("refresh"),
        _sync_now_playing_overlay_state=lambda p, d, playing: calls.append(("state", p, d, playing)),
        _now_playing_render_track_key="track-1",
        now_playing_backdrop=_ToggleTarget(),
        now_playing_anchor=_ToggleTarget(),
        now_playing_revealer=_Revealer(),
        now_playing_stack=_Stack("lyrics"),
        now_playing_close_btn=_FocusButton(),
        player=_Player(),
        _now_playing_hide_source=0,
        _now_playing_focus_source=0,
    )

    monkeypatch.setattr(app_now_playing.GLib, "idle_add", lambda func: func())
    monkeypatch.setattr(app_now_playing.GLib, "timeout_add", lambda _ms, func: func() or 1)

    app_now_playing.show_now_playing_overlay(app)

    assert "refresh" not in calls
    assert calls[0] == "close_queue"
    assert calls[1] == "size"
    assert app.now_playing_stack.get_visible_child_name() == "queue"
    assert app.now_playing_stack.set_calls == ["queue"]
    assert app.now_playing_revealer.visible == [True]
    assert app.now_playing_revealer.can_target == [True]
    assert app.now_playing_revealer.reveal_child == [True]
    assert ("state", 15.0, 180.0, True) in calls
    assert app.now_playing_close_btn.grab_focus_calls == 1


def test_schedule_surface_resync_debounces_idle_and_refreshes_settle_timers(monkeypatch):
    sync_calls = []
    removed = []
    idle_callbacks = {}
    timeout_callbacks = {}
    next_source = {"value": 1}

    def _next_source():
        value = next_source["value"]
        next_source["value"] += 1
        return value

    def _idle_add(func):
        source = _next_source()
        idle_callbacks[source] = func
        return source

    def _timeout_add(delay_ms, func):
        source = _next_source()
        timeout_callbacks[source] = (int(delay_ms), func)
        return source

    app = SimpleNamespace(
        now_playing_surface=object(),
        content_overlay=object(),
        _sync_now_playing_surface_size=lambda: sync_calls.append("size"),
        _now_playing_resize_idle_source=0,
        _now_playing_resize_settle_source=0,
        _now_playing_resize_finish_source=0,
    )

    monkeypatch.setattr(app_now_playing.GLib, "idle_add", _idle_add)
    monkeypatch.setattr(app_now_playing.GLib, "timeout_add", _timeout_add)
    monkeypatch.setattr(app_now_playing.GLib, "source_remove", lambda source: removed.append(int(source)))

    app_now_playing._schedule_now_playing_surface_resync(app)

    assert sorted(timeout[0] for timeout in timeout_callbacks.values()) == [90, 300]
    assert len(idle_callbacks) == 1
    assert app._now_playing_resize_idle_source == 1
    assert app._now_playing_resize_settle_source == 2
    assert app._now_playing_resize_finish_source == 3

    app_now_playing._schedule_now_playing_surface_resync(app)

    assert len(idle_callbacks) == 1
    assert removed == [2, 3]
    assert app._now_playing_resize_idle_source == 1
    assert app._now_playing_resize_settle_source == 4
    assert app._now_playing_resize_finish_source == 5

    idle_callbacks[1]()
    timeout_callbacks[4][1]()
    timeout_callbacks[5][1]()

    assert sync_calls == ["size", "size", "size"]
    assert app._now_playing_resize_idle_source == 0
    assert app._now_playing_resize_settle_source == 0
    assert app._now_playing_resize_finish_source == 0


def test_now_playing_lyrics_clears_stale_previous_active_line(monkeypatch):
    prev_widget = _CssWidget()
    prev_main = _CssWidget()
    cur_widget = _CssWidget()
    cur_main = _CssWidget()
    prev_widget.active = True
    prev_main.active = True
    cur_widget.active = True
    cur_main.active = True
    app = SimpleNamespace(
        now_playing_stack=_Stack("lyrics"),
        lyrics_mgr=SimpleNamespace(has_synced=True),
        now_playing_lyric_widgets=[
            {
                "time": 0.0,
                "widget": prev_widget,
                "main": prev_main,
                "sub": None,
                "is_active": True,
                "karaoke_words": [],
                "karaoke_last_idx": -1,
            },
            {
                "time": 3.0,
                "widget": cur_widget,
                "main": cur_main,
                "sub": None,
                "is_active": True,
                "karaoke_words": [],
                "karaoke_last_idx": -1,
            },
        ],
        current_now_playing_lyric_index=1,
        lyrics_user_offset_ms=0,
        now_playing_lyrics_scroller=None,
    )

    monkeypatch.setattr(app_now_playing, "is_now_playing_overlay_open", lambda _app: True)

    app_now_playing._sync_now_playing_lyrics(app, 5.0)

    assert prev_widget.active is False
    assert prev_main.active is False
    assert app.now_playing_lyric_widgets[0]["is_active"] is False
    assert cur_widget.active is True
    assert cur_main.active is True
    assert app.now_playing_lyric_widgets[1]["is_active"] is True


def test_stack_change_moves_dynamic_background_to_lyrics_page_only():
    lyrics_page = _CssClassTarget()
    right_panel = _CssClassTarget()
    app = SimpleNamespace(
        now_playing_stack=_Stack("lyrics"),
        now_playing_right_panel=right_panel,
        now_playing_lyrics_page=lyrics_page,
        _sync_now_playing_surface_size=lambda: (_ for _ in ()).throw(AssertionError("unexpected resize")),
        player=SimpleNamespace(get_position=lambda: (0.0, 0.0)),
        _sync_now_playing_lyrics=lambda _pos: None,
    )

    app_now_playing._on_now_playing_stack_changed(app)

    assert "lyrics-active" in lyrics_page.classes
    assert "lyrics-active" not in right_panel.classes

    app.now_playing_stack.set_visible_child_name("queue")
    app_now_playing._on_now_playing_stack_changed(app)

    assert "lyrics-active" not in lyrics_page.classes
    assert "lyrics-active" not in right_panel.classes


def test_cover_fade_anchor_uses_layout_formula():
    surface = _SizedWidget(width=1048)
    right_panel = _SizedWidget(width_request=406)
    app = SimpleNamespace(
        now_playing_surface=surface,
        now_playing_right_panel=right_panel,
    )

    visible_left_w = app_now_playing._now_playing_right_content_left_in_left_stage(app)

    assert visible_left_w == 620.0


def test_now_playing_split_widths_use_60_40_layout():
    left_w, right_w = app_now_playing._now_playing_split_widths(1000)

    assert left_w == 587
    assert right_w == 391
    assert left_w + right_w + app_now_playing._NOW_PLAYING_CONTENT_INSET == 1000


def test_dynamic_color_tints_now_playing_track_list():
    provider = _CssProvider()
    app = SimpleNamespace(now_playing_dynamic_provider=provider)

    app_now_playing._apply_now_playing_dynamic_color(app, (0.10, 0.20, 0.30))

    css = provider.loaded.decode()
    assert ".tracks-list.now-playing-track-list" in css
    assert "background-color: rgba(26, 51, 76, 0.30);" in css
    assert ".now-playing-info-card" in css
    assert "background-color: rgba(26, 51, 76, 0.35);" in css


def test_now_playing_track_album_name_falls_back_to_unknown():
    assert app_now_playing._now_playing_track_album_name(SimpleNamespace(album=None)) == "Unknown Album"


def test_now_playing_track_album_name_reads_album_name():
    track = SimpleNamespace(album=SimpleNamespace(name="Fearless"))

    assert app_now_playing._now_playing_track_album_name(track) == "Fearless"


def test_open_album_click_hides_overlay_and_opens_album(monkeypatch):
    album = SimpleNamespace(id="42", name="Fearless")
    opened = []
    hidden = []
    remembered = []
    nav_list = _NavList(["home", "collection", "artists"])
    app = SimpleNamespace(
        playing_track=SimpleNamespace(album=album),
        show_album_details=lambda alb: opened.append(alb),
        nav_list=nav_list,
        _remember_last_nav=lambda nav_id: remembered.append(nav_id),
    )

    monkeypatch.setattr(app_now_playing, "hide_now_playing_overlay", lambda _app: hidden.append(True))

    app_now_playing.on_now_playing_open_album_clicked(app)

    assert hidden == [True]
    assert opened == [album]
    assert nav_list.selected is not None
    assert nav_list.selected.nav_id == "collection"
    assert remembered == ["collection"]


def test_refresh_now_playing_disables_open_album_button_without_album(monkeypatch):
    app = SimpleNamespace(
        playing_track=SimpleNamespace(
            name="Track",
            artist=SimpleNamespace(name="Artist"),
            album=None,
        ),
        now_playing_title_label=_Label(),
        now_playing_artist_label=_Label(),
        now_playing_album_label=_Label(),
        now_playing_open_album_btn=_SensitiveButton(),
        _render_now_playing_queue=lambda _tracks: None,
        _get_active_queue=lambda: [],
        _load_now_playing_album_tracks_async=lambda _album: None,
        _render_now_playing_album_tracks=lambda _tracks: None,
        _render_now_playing_lyrics=lambda _lyrics, _status: None,
        backend=SimpleNamespace(get_artwork_url=lambda _track, _size: None),
        lyrics_mgr=None,
        now_playing_album_tracks=[],
        now_playing_album_id="",
        player=SimpleNamespace(get_position=lambda: (12.0, 180.0), is_playing=lambda: True),
        _sync_now_playing_overlay_state=lambda _pos, _dur, _playing: None,
    )

    monkeypatch.setattr(app_now_playing, "_load_now_playing_cover", lambda _app, _cover_ref: None)

    app_now_playing._refresh_now_playing_from_track(app)

    assert app.now_playing_open_album_btn.sensitive is False
    assert app.now_playing_open_album_btn.set_sensitive_calls == 1


def test_scrim_css_is_disabled():
    provider = _CssProvider()
    app = SimpleNamespace(now_playing_scrim_provider=provider)

    app_now_playing._apply_now_playing_scrim_css(app, 620)

    css = provider.loaded.decode()
    assert "background: none" in css
    assert "background-color: transparent" in css


def test_tidal_cover_key_ignores_requested_size():
    key_320 = app_now_playing._normalize_now_playing_cover_key(
        "https://resources.tidal.com/images/ab/cd/ef/320x320.jpg"
    )
    key_1280 = app_now_playing._normalize_now_playing_cover_key(
        "https://resources.tidal.com/images/ab/cd/ef/1280x1280.jpg"
    )

    assert key_320 == "ab/cd/ef"
    assert key_1280 == "ab/cd/ef"
    assert key_320 == key_1280


def test_load_now_playing_cover_applies_cached_cover_color_before_async(monkeypatch):
    applied = []
    area = _Area()
    app = SimpleNamespace(
        now_playing_art_img=area,
        now_playing_cover_rgb_cache={},
        cache_dir="/tmp",
    )

    monkeypatch.setattr(
        app_now_playing,
        "_get_now_playing_cached_cover_dark_rgb",
        lambda _app, ref: (0.2, 0.3, 0.4) if ref == "cover://track" else None,
    )
    monkeypatch.setattr(
        app_now_playing,
        "_apply_now_playing_dynamic_color",
        lambda _app, rgb: applied.append(tuple(rgb)),
    )
    monkeypatch.setattr(app_now_playing, "submit_daemon", lambda _task: None)

    app_now_playing._load_now_playing_cover(app, "cover://track")

    assert area._target_url == "cover://track"
    assert area._cover_dark_rgb == (0.2, 0.3, 0.4)
    assert applied == [(0.2, 0.3, 0.4)]


def test_cached_cover_color_reuses_player_artwork_cache_file(monkeypatch):
    with tempfile.TemporaryDirectory() as cache_dir:
        player_url = "https://resources.tidal.com/images/ab/cd/ef/320x320.jpg"
        now_playing_url = "https://resources.tidal.com/images/ab/cd/ef/1280x1280.jpg"
        cached_path = os.path.join(cache_dir, hashlib.md5(player_url.encode()).hexdigest())
        with open(cached_path, "wb") as handle:
            handle.write(b"fake")

        app = SimpleNamespace(
            now_playing_cover_rgb_cache={},
            cache_dir=cache_dir,
            art_img=SimpleNamespace(_target_url=player_url),
        )

        monkeypatch.setattr(app_now_playing.GdkPixbuf.Pixbuf, "new_from_file_at_scale", lambda *_args: object())
        monkeypatch.setattr(app_now_playing, "_dominant_dark_rgb_from_pixbuf", lambda _pb: (0.4, 0.3, 0.2))

        rgb = app_now_playing._get_now_playing_cached_cover_dark_rgb(app, now_playing_url)

        assert rgb == (0.4, 0.3, 0.2)
        assert app.now_playing_cover_rgb_cache["ab/cd/ef"] == (0.4, 0.3, 0.2)


def test_prime_cover_color_ignores_stale_track(monkeypatch):
    applied = []
    app = SimpleNamespace(
        playing_track=SimpleNamespace(cover="new-cover", album=None),
        now_playing_cover_rgb_cache={},
        cache_dir="/tmp",
        _get_tidal_image_url=lambda ref: f"https://resources.tidal.com/images/{ref}/320x320.jpg",
        backend=SimpleNamespace(get_artwork_url=lambda _track, size=320: f"unexpected:{size}"),
    )

    monkeypatch.setattr(app_now_playing, "_cached_cover_path_for_ref", lambda *_args: "/tmp/fake-cover")
    monkeypatch.setattr(app_now_playing.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(app_now_playing, "_sample_cached_cover_dark_rgb", lambda _path: (0.4, 0.2, 0.1))
    monkeypatch.setattr(app_now_playing, "_apply_now_playing_dynamic_color", lambda _app, rgb: applied.append(tuple(rgb)))
    monkeypatch.setattr(app_now_playing.GLib, "idle_add", lambda func: func())

    app_now_playing._prime_now_playing_cover_color(
        app,
        "https://resources.tidal.com/images/old-cover/320x320.jpg",
    )

    assert applied == []


def test_playback_cover_load_primes_now_playing_color(monkeypatch):
    calls = []
    app = SimpleNamespace(
        _get_tidal_image_url=lambda ref: f"https://resources.tidal.com/images/{ref}/320x320.jpg",
        _prime_now_playing_cover_color=lambda url: calls.append(("prime", url)),
        art_img=object(),
        cache_dir="/tmp/cache",
    )

    monkeypatch.setattr(playback_stream_actions.utils, "load_img", lambda widget, url, cache_dir, size: calls.append(("img", widget, url, cache_dir, size)))

    playback_stream_actions.load_cover_art(app, "cover-uuid")

    assert calls[0] == ("prime", "https://resources.tidal.com/images/cover-uuid/320x320.jpg")
    assert calls[1] == ("img", app.art_img, "https://resources.tidal.com/images/cover-uuid/320x320.jpg", "/tmp/cache", 80)


def test_show_overlay_resyncs_dynamic_color_from_current_player_art(monkeypatch):
    applied = []
    player_art = SimpleNamespace(
        _target_url="https://resources.tidal.com/images/ab/cd/ef/320x320.jpg",
        _loaded_pixbuf=object(),
    )
    app = SimpleNamespace(
        playing_track=SimpleNamespace(cover="ab-cd-ef", album=None, id="track-1", duration=180),
        art_img=player_art,
        _get_tidal_image_url=lambda ref: f"https://resources.tidal.com/images/{ref.replace('-', '/')}/320x320.jpg",
        now_playing_cover_rgb_cache={},
        is_mini_mode=False,
        close_queue_drawer=lambda: None,
        _sync_now_playing_surface_size=lambda: None,
        _refresh_now_playing_from_track=lambda: (_ for _ in ()).throw(AssertionError("unexpected refresh")),
        _sync_now_playing_overlay_state=lambda *_args: None,
        _now_playing_render_track_key="track-1",
        now_playing_backdrop=_ToggleTarget(),
        now_playing_anchor=_ToggleTarget(),
        now_playing_revealer=_Revealer(),
        now_playing_stack=_Stack("queue"),
        now_playing_close_btn=_FocusButton(),
        player=_Player(),
        _now_playing_hide_source=0,
        _now_playing_focus_source=0,
    )

    monkeypatch.setattr(app_now_playing, "_apply_now_playing_dynamic_color", lambda _app, rgb: applied.append(tuple(rgb)))
    monkeypatch.setattr(app_now_playing, "_dominant_dark_rgb_from_pixbuf", lambda _pb: (0.2, 0.25, 0.3))
    monkeypatch.setattr(app_now_playing.GLib, "idle_add", lambda func: func())
    monkeypatch.setattr(app_now_playing.GLib, "timeout_add", lambda _ms, func: func() or 1)

    app_now_playing.show_now_playing_overlay(app)

    assert applied[0] == (0.2, 0.25, 0.3)
    assert app.now_playing_cover_rgb_cache["ab/cd/ef"] == (0.2, 0.25, 0.3)
