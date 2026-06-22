import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import ui_actions
from app import app_queue


class _Stack:
    def get_visible_child_name(self):
        return "collection"

    def set_visible_child_name(self, _name):
        return None


class _Button:
    def set_sensitive(self, _value):
        return None


class _Label:
    def __init__(self):
        self.text = ""
        self.tooltip = ""

    def get_text(self):
        return self.text

    def set_text(self, value):
        self.text = value

    def set_tooltip_text(self, value):
        self.tooltip = value


def _make_track(track_id="42", name="Test Song"):
    return SimpleNamespace(id=str(track_id), name=name)


def _make_app(backend=None):
    notices = []
    opened = []
    app = SimpleNamespace()
    app.backend = backend or SimpleNamespace()
    app.show_output_notice = lambda text, state="idle", timeout_ms=0: notices.append((text, state, timeout_ms))
    app.show_album_details = lambda mix: opened.append(mix)
    app._notices = notices
    app._opened = opened
    return app


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()


def test_on_go_to_track_radio_clicked_opens_mix_view(monkeypatch):
    mix = SimpleNamespace(id="mix-1", title="Track Radio")
    backend = SimpleNamespace(get_track_radio_mix=lambda track: mix)
    app = _make_app(backend)
    track = _make_track()
    monkeypatch.setattr(app_queue, "Thread", _ImmediateThread)
    monkeypatch.setattr(app_queue.GLib, "idle_add", lambda fn, *args: fn(*args))

    app_queue.on_go_to_track_radio_clicked(app, track)

    assert app._opened == [mix]
    assert ("Loading track radio…", "info", 2200) in app._notices


class _Mix(SimpleNamespace):
    pass


def test_show_album_details_selects_mixes_sidebar_for_mix(monkeypatch):
    mix = _Mix(id="mix-1", title="Track Radio", name="Track Radio", artist=None)
    selected = []
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
        header_kicker=_Label(),
        header_art=object(),
        grid_title_label=_Label(),
        backend=SimpleNamespace(is_mix_favorite=lambda _mix_id: False, get_tracks=lambda _mix: []),
        cache_dir="/tmp",
        fav_btn=None,
        add_playlist_btn=None,
        remote_playlist_edit_btn=None,
        remote_playlist_visibility_btn=None,
        remote_playlist_more_btn=None,
        track_list=SimpleNamespace(get_first_child=lambda: None),
        album_sort_field=None,
        album_sort_asc=True,
        _update_fav_icon=lambda *_args: None,
        load_album_tracks=lambda _tracks: None,
        _select_sidebar_nav_row=lambda nav_id: selected.append(nav_id) or True,
        _remember_last_view=lambda _view: None,
    )
    app.grid_title_label.text = "Albums"

    class _ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr(ui_actions, "_ensure_play_shuffle_btns", lambda _app: None)
    monkeypatch.setattr(ui_actions.utils, "load_img", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_actions, "Thread", _ImmediateThread)

    ui_actions.show_album_details(app, mix)

    assert selected == ["mixes"]
    assert app._track_view_source == {
        "type": "mix",
        "name": "Track Radio",
        "obj": mix,
        "open_method": "show_album_details",
    }


def test_on_go_to_track_radio_clicked_shows_unavailable_notice(monkeypatch):
    backend = SimpleNamespace(get_track_radio_mix=lambda track: None)
    app = _make_app(backend)
    track = _make_track(name="Shanghai Beach")
    monkeypatch.setattr(app_queue, "Thread", _ImmediateThread)
    monkeypatch.setattr(app_queue.GLib, "idle_add", lambda fn, *args: fn(*args))

    app_queue.on_go_to_track_radio_clicked(app, track)

    assert app._opened == []
    assert app._notices[-1] == ("Track radio not available for Shanghai Beach", "warn", 3200)