import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import ui_actions
from app import app_album


class _Label:
    def __init__(self):
        self.text = None
        self.tooltip = None

    def set_text(self, value):
        self.text = str(value)

    def set_tooltip_text(self, value):
        self.tooltip = None if value is None else str(value)


class _Stack:
    def __init__(self, visible_child_name="grid_view"):
        self.visible_child_name = visible_child_name
        self.set_calls = []

    def get_visible_child_name(self):
        return self.visible_child_name

    def set_visible_child_name(self, value):
        self.visible_child_name = str(value)
        self.set_calls.append(str(value))


class _Button:
    def __init__(self):
        self.sensitive = None

    def set_sensitive(self, value):
        self.sensitive = bool(value)


class _ImmediateThread:
    def __init__(self, target=None, daemon=None):
        self._target = target
        self.daemon = bool(daemon)

    def start(self):
        return None


def test_show_album_details_uses_playing_track_artist_when_album_artist_missing(monkeypatch):
    album = SimpleNamespace(id="album-1", name="Bookends", artist=None)
    playing_track = SimpleNamespace(
        album=SimpleNamespace(id="album-1"),
        artist=SimpleNamespace(id="artist-7", name="Simon & Garfunkel"),
    )
    app = SimpleNamespace(
        right_stack=_Stack(),
        nav_history=[],
        current_album=None,
        current_album_artist_id=None,
        current_album_artist_name="",
        back_btn=_Button(),
        header_title=_Label(),
        header_artist=_Label(),
        header_meta=_Label(),
        header_art=object(),
        backend=SimpleNamespace(is_favorite=lambda _album_id: False, get_tracks=lambda _alb: []),
        cache_dir="/tmp",
        fav_btn=None,
        add_playlist_btn=None,
        remote_playlist_edit_btn=None,
        remote_playlist_visibility_btn=None,
        remote_playlist_more_btn=None,
        track_list=SimpleNamespace(get_first_child=lambda: None),
        album_sort_field=None,
        album_sort_asc=True,
        album_track_source=[],
        playing_track=playing_track,
        _update_fav_icon=lambda *_args: None,
        load_album_tracks=lambda _tracks: None,
    )

    monkeypatch.setattr(ui_actions, "_ensure_play_shuffle_btns", lambda _app: None)
    monkeypatch.setattr(ui_actions.utils, "load_img", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_actions, "Thread", _ImmediateThread)

    ui_actions.show_album_details(app, album)

    assert app.current_album is album
    assert app.current_album_artist_id == "artist-7"
    assert app.current_album_artist_name == "Simon & Garfunkel"
    assert app.header_artist.text == "Simon & Garfunkel"
    assert app.header_artist.tooltip == "Simon & Garfunkel"


def test_header_artist_click_uses_saved_album_artist_context(monkeypatch):
    resolved_artist = SimpleNamespace(id="artist-7", name="Simon & Garfunkel")
    resolved = []
    resolve_calls = []
    app = SimpleNamespace(
        current_album=SimpleNamespace(id="album-1", artist=None),
        current_album_artist_id="artist-7",
        current_album_artist_name="Simon & Garfunkel",
        backend=SimpleNamespace(
            resolve_artist=lambda artist_id=None, artist_name="": (
                resolve_calls.append((artist_id, artist_name)) or resolved_artist
            )
        ),
        on_artist_clicked=lambda artist: resolved.append(artist),
    )

    monkeypatch.setattr(app_album, "submit_daemon", lambda fn: fn())
    monkeypatch.setattr(app_album.GLib, "idle_add", lambda fn, *args: fn(*args))

    app_album.on_header_artist_clicked(app, None, None, None, None)

    assert resolve_calls == [("artist-7", "Simon & Garfunkel")]
    assert resolved == [resolved_artist]
