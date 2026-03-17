import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import ui_actions
from actions import ui_navigation
from app import app_album


class _Label:
    def __init__(self, text=None):
        self.text = text
        self.tooltip = None

    def set_text(self, value):
        self.text = str(value)

    def get_text(self):
        return self.text

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
        self.visible = None

    def set_sensitive(self, value):
        self.sensitive = bool(value)

    def set_visible(self, value):
        self.visible = bool(value)


class _Icon:
    def __init__(self):
        self.visible = None

    def set_visible(self, value):
        self.visible = bool(value)


class _Widget:
    def __init__(self, name="widget"):
        self.name = name
        self.parent = None

    def get_next_sibling(self):
        if self.parent is None:
            return None
        siblings = self.parent.children
        idx = siblings.index(self)
        return siblings[idx + 1] if idx + 1 < len(siblings) else None

    def get_first_child(self):
        return None


class _DashboardRow(_Widget):
    def __init__(self, track_id="", track_name="", track_artist=""):
        super().__init__(name="dashboard-row")
        self._dashboard_track_id = str(track_id)
        self._dashboard_track_name = str(track_name)
        self._dashboard_track_artist = str(track_artist)
        self._dashboard_playing_icon = _Icon()
        self.classes = set()

    def add_css_class(self, value):
        self.classes.add(str(value))

    def remove_css_class(self, value):
        self.classes.discard(str(value))


class _Container:
    def __init__(self, children=None):
        self.children = []
        self._width = 0
        for child in list(children or []):
            self.append(child)

    def append(self, child):
        old_parent = getattr(child, "parent", None)
        if old_parent is self:
            self.children.append(child)
            return
        if old_parent is not None and hasattr(old_parent, "remove"):
            old_parent.remove(child)
        child.parent = self
        self.children.append(child)

    def remove(self, child):
        self.children.remove(child)
        child.parent = None

    def get_first_child(self):
        return self.children[0] if self.children else None

    def get_width(self):
        return self._width


class _Adjustment:
    def __init__(self, value=0.0, upper=2000.0, page_size=500.0):
        self.value = float(value)
        self.upper = float(upper)
        self.page_size = float(page_size)

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = float(value)

    def get_upper(self):
        return self.upper

    def get_page_size(self):
        return self.page_size


class _Scroll:
    def __init__(self, adj, width=0):
        self._adj = adj
        self._width = width

    def get_vadjustment(self):
        return self._adj

    def get_width(self):
        return self._width


class _NavList:
    def __init__(self, row):
        self._row = row

    def get_selected_row(self):
        return self._row


class _Window:
    def __init__(self, width=0, height=0):
        self._width = width
        self._height = height

    def get_width(self):
        return self._width

    def get_height(self):
        return self._height


class _BodyOverlay:
    def __init__(self, height=0):
        self._height = height

    def get_height(self):
        return self._height


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


def test_capture_and_restore_artists_page_state_restores_children_and_scroll(monkeypatch):
    monkeypatch.setattr(ui_navigation.GLib, "idle_add", lambda fn, *args: fn(*args))

    artists_section = _Widget("artists-section")
    detail_section = _Widget("detail-section")
    flow = _Widget("artists-flow")
    content = _Container([artists_section])
    adj = _Adjustment(value=420.0, upper=1800.0, page_size=500.0)
    app = SimpleNamespace(
        nav_list=_NavList(SimpleNamespace(nav_id="artists")),
        collection_content_box=content,
        alb_scroll=_Scroll(adj),
        grid_title_label=_Label("Favorite Artists"),
        grid_subtitle_label=_Label("Artists you follow and love"),
        main_flow=flow,
    )

    ui_navigation._capture_artists_page_state(app)

    content.remove(artists_section)
    content.append(detail_section)
    adj.set_value(0.0)
    app.main_flow = _Widget("detail-flow")

    assert ui_navigation._restore_artists_page_state(app) is True
    assert [child.name for child in content.children] == ["artists-section"]
    assert adj.get_value() == 420.0
    assert app.main_flow is flow


def test_on_back_clicked_restores_artists_page_without_reloading(monkeypatch):
    monkeypatch.setattr(ui_navigation.GLib, "idle_add", lambda fn, *args: fn(*args))

    artists_section = _Widget("artists-section")
    detail_section = _Widget("detail-section")
    content = _Container([detail_section])
    adj = _Adjustment(value=0.0, upper=1800.0, page_size=500.0)
    btn = _Button()
    fav_btn = _Button()
    reloaded = []
    app = SimpleNamespace(
        current_remote_playlist=None,
        current_playlist_id=None,
        playlist_edit_mode=False,
        playlist_rename_mode=False,
        nav_history=["grid_view"],
        right_stack=_Stack("grid_view"),
        nav_list=_NavList(SimpleNamespace(nav_id="artists")),
        collection_content_box=content,
        alb_scroll=_Scroll(adj),
        grid_title_label=_Label("Albums by Demo"),
        grid_subtitle_label=_Label("Discography"),
        artist_fav_btn=fav_btn,
        on_nav_selected=lambda *_args: reloaded.append(True),
        _remember_last_view=lambda _view: None,
        _artist_albums_render_token=9,
        current_selected_artist=SimpleNamespace(id="artist-1", name="Demo"),
        _artists_page_state={
            "children": [artists_section],
            "main_flow": _Widget("artists-flow"),
            "scroll_y": 360.0,
            "title": "Favorite Artists",
            "subtitle": "Artists you follow and love",
        },
    )

    ui_navigation.on_back_clicked(app, btn)

    assert reloaded == []
    assert [child.name for child in content.children] == ["artists-section"]
    assert adj.get_value() == 360.0
    assert btn.sensitive is False
    assert fav_btn.visible is False
    assert app._artist_albums_render_token == 10
    assert app.current_selected_artist is None


def test_batch_load_albums_uses_explicit_flow_target_and_token(monkeypatch):
    class _FakeGtkBox:
        def __init__(self, *args, **kwargs):
            self.children = []

        def append(self, child):
            self.children.append(child)

    class _FakeGtkImage:
        def __init__(self, *args, **kwargs):
            self.icon_name = None

        def set_from_icon_name(self, icon_name):
            self.icon_name = icon_name

    class _FakeGtkLabel:
        def __init__(self, *args, **kwargs):
            self.tooltip = None

        def set_tooltip_text(self, value):
            self.tooltip = value

    class _FakeGtkButton:
        def __init__(self, *args, **kwargs):
            self.child = None

        def set_child(self, child):
            self.child = child

        def connect(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        ui_actions,
        "Gtk",
        SimpleNamespace(
            Box=_FakeGtkBox,
            Image=_FakeGtkImage,
            Label=_FakeGtkLabel,
            Button=_FakeGtkButton,
            Orientation=SimpleNamespace(VERTICAL="vertical"),
            Align=SimpleNamespace(CENTER="center"),
        ),
    )
    monkeypatch.setattr(ui_actions, "_build_feed_media_overlay", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(ui_actions.utils, "load_img", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_actions, "_album_title_text", lambda alb: alb.name)
    monkeypatch.setattr(ui_actions, "_album_artist_year_subtitle_text", lambda _alb: "Artist  •  1970")
    monkeypatch.setattr(ui_actions.GLib, "timeout_add", lambda *_args, **_kwargs: None)

    target_flow = _Container()
    wrong_flow = _Container()
    app = SimpleNamespace(
        main_flow=wrong_flow,
        backend=SimpleNamespace(get_artwork_url=lambda *_args, **_kwargs: ""),
        cache_dir="/tmp",
        show_album_details=lambda *_args, **_kwargs: None,
        _artist_albums_render_token=4,
    )

    ui_actions.batch_load_albums(
        app,
        [SimpleNamespace(id="album-1", name="Album One")],
        6,
        target_flow,
        4,
        "_artist_albums_render_token",
    )

    assert len(target_flow.children) == 1
    assert wrong_flow.children == []

    target_flow_2 = _Container()
    ui_actions.batch_load_albums(
        app,
        [SimpleNamespace(id="album-2", name="Album Two")],
        6,
        target_flow_2,
        3,
        "_artist_albums_render_token",
    )

    assert target_flow_2.children == []


def test_batch_load_artists_uses_explicit_flow_target(monkeypatch):
    class _FakeGtkBox:
        def __init__(self, *args, **kwargs):
            self.children = []

        def append(self, child):
            self.children.append(child)

    class _FakeGtkImage:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeGtkLabel:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeGtkFlowBoxChild:
        def __init__(self):
            self.child = None
            self.data_item = None

        def set_child(self, child):
            self.child = child

    monkeypatch.setattr(
        ui_actions,
        "Gtk",
        SimpleNamespace(
            Box=_FakeGtkBox,
            Image=_FakeGtkImage,
            Label=_FakeGtkLabel,
            FlowBoxChild=_FakeGtkFlowBoxChild,
            Orientation=SimpleNamespace(VERTICAL="vertical"),
            Align=SimpleNamespace(CENTER="center"),
        ),
    )
    monkeypatch.setattr(ui_actions, "_build_feed_media_overlay", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(ui_actions.utils, "load_img", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_actions.GLib, "timeout_add", lambda *_args, **_kwargs: None)

    target_flow = _Container()
    wrong_flow = _Container()
    app = SimpleNamespace(
        main_flow=wrong_flow,
        backend=SimpleNamespace(
            get_artist_artwork_url=lambda *_args, **_kwargs: "",
            _artist_artwork_cache={},
            get_artwork_url=lambda *_args, **_kwargs: "",
            _is_placeholder_artist_artwork_url=lambda *_args, **_kwargs: False,
        ),
        cache_dir="/tmp",
        _artists_render_token=7,
    )

    ui_actions.batch_load_artists(
        app,
        [SimpleNamespace(id="artist-1", name="Artist One")],
        10,
        7,
        target_flow,
    )

    assert len(target_flow.children) == 1
    assert wrong_flow.children == []


def test_render_artists_dashboard_places_prev_next_in_search_toolbar(monkeypatch):
    class _FakeGtkBox(_Container):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.css_classes = list(kwargs.get("css_classes", []))
            self.visible = True

        def set_visible(self, value):
            self.visible = bool(value)

    class _FakeGtkEntry:
        def __init__(self, *args, **kwargs):
            self.css_classes = list(kwargs.get("css_classes", []))
            self.hexpand = bool(kwargs.get("hexpand", False))
            self.placeholder_text = kwargs.get("placeholder_text")
            self.text = ""

        def set_placeholder_text(self, value):
            self.placeholder_text = value

        def set_text(self, value):
            self.text = str(value)

        def get_text(self):
            return self.text

        def connect(self, *_args, **_kwargs):
            return None

    class _FakeGtkLabel:
        def __init__(self, *args, **kwargs):
            self.css_classes = list(kwargs.get("css_classes", []))
            self.label = str(kwargs.get("label", ""))
            self.text = self.label
            self.hexpand = bool(kwargs.get("hexpand", False))

        def set_text(self, value):
            self.text = str(value)

        def get_text(self):
            return self.text

        def set_hexpand(self, value):
            self.hexpand = bool(value)

    class _FakeGtkDropDown:
        def __init__(self, *args, **kwargs):
            self.css_classes = list(kwargs.get("css_classes", []))
            self.model = kwargs.get("model")
            self.selected = 0
            self.tooltip = None
            self.size_request = None

        def set_selected(self, value):
            self.selected = int(value)

        def get_selected(self):
            return self.selected

        def set_tooltip_text(self, value):
            self.tooltip = value

        def set_size_request(self, width, height):
            self.size_request = (width, height)

        def connect(self, *_args, **_kwargs):
            return None

    class _FakeGtkButton:
        def __init__(self, *args, **kwargs):
            self.css_classes = list(kwargs.get("css_classes", []))
            self.label = str(kwargs.get("label", ""))
            self.tooltip = None
            self.sensitive = None

        def set_tooltip_text(self, value):
            self.tooltip = value

        def set_sensitive(self, value):
            self.sensitive = bool(value)

        def connect(self, *_args, **_kwargs):
            return None

    class _FakeGtkStringList:
        @staticmethod
        def new(values):
            return list(values)

    monkeypatch.setattr(
        ui_actions,
        "Gtk",
        SimpleNamespace(
            Box=_FakeGtkBox,
            Entry=_FakeGtkEntry,
            Label=_FakeGtkLabel,
            DropDown=_FakeGtkDropDown,
            Button=_FakeGtkButton,
            StringList=_FakeGtkStringList,
            Align=SimpleNamespace(CENTER="center"),
        ),
    )
    monkeypatch.setattr(ui_actions, "Thread", _ImmediateThread)

    content = _Container()
    app = SimpleNamespace(
        collection_content_box=content,
        backend=SimpleNamespace(user=None),
        grid_subtitle_label=_Label("Artists you follow and love"),
        artists_query="",
        artists_sort="name_asc",
        artists_page=0,
        artists_page_size=50,
        playlist_track_list=object(),
        queue_track_list=object(),
        batch_load_artists=lambda *_args, **_kwargs: None,
    )

    def _create_album_flow():
        app.main_flow = _Container()
        section = _Container([app.main_flow])
        app.collection_content_box.append(section)

    app.create_album_flow = _create_album_flow

    ui_actions.render_artists_dashboard(app)

    toolbar = content.children[0]
    pager_bar = content.children[1]

    assert toolbar.css_classes == ["search-bar"]
    assert toolbar.children[0].css_classes == ["search-entry"]
    assert toolbar.children[1].css_classes == ["sort-dropdown"]
    assert [child.label for child in toolbar.children[2:4]] == ["Prev", "Next"]
    assert len(pager_bar.children) == 1
    assert not any(isinstance(child, _FakeGtkButton) for child in pager_bar.children)


def test_render_artists_dashboard_moves_total_count_to_grid_subtitle(monkeypatch):
    class _RunThread:
        def __init__(self, target=None, daemon=None):
            self._target = target
            self.daemon = bool(daemon)

        def start(self):
            if self._target is not None:
                self._target()

    class _FakeGtkBox(_Container):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.css_classes = list(kwargs.get("css_classes", []))
            self.visible = True

        def set_visible(self, value):
            self.visible = bool(value)

    class _FakeGtkEntry:
        def __init__(self, *args, **kwargs):
            self.css_classes = list(kwargs.get("css_classes", []))
            self.text = ""

        def set_placeholder_text(self, _value):
            return None

        def set_text(self, value):
            self.text = str(value)

        def get_text(self):
            return self.text

        def connect(self, *_args, **_kwargs):
            return None

    class _FakeGtkLabel:
        def __init__(self, *args, **kwargs):
            self.text = str(kwargs.get("label", ""))
            self.css_classes = list(kwargs.get("css_classes", []))
            self.hexpand = bool(kwargs.get("hexpand", False))

        def set_text(self, value):
            self.text = str(value)

        def get_text(self):
            return self.text

        def set_hexpand(self, value):
            self.hexpand = bool(value)

    class _FakeGtkDropDown:
        def __init__(self, *args, **kwargs):
            self.selected = 0
            self.css_classes = list(kwargs.get("css_classes", []))

        def set_selected(self, value):
            self.selected = int(value)

        def get_selected(self):
            return self.selected

        def set_tooltip_text(self, _value):
            return None

        def set_size_request(self, _width, _height):
            return None

        def connect(self, *_args, **_kwargs):
            return None

    class _FakeGtkButton:
        def __init__(self, *args, **kwargs):
            self.label = str(kwargs.get("label", ""))
            self.sensitive = None

        def set_tooltip_text(self, _value):
            return None

        def set_sensitive(self, value):
            self.sensitive = bool(value)

        def connect(self, *_args, **_kwargs):
            return None

    class _FakeGtkStringList:
        @staticmethod
        def new(values):
            return list(values)

    monkeypatch.setattr(
        ui_actions,
        "Gtk",
        SimpleNamespace(
            Box=_FakeGtkBox,
            Entry=_FakeGtkEntry,
            Label=_FakeGtkLabel,
            DropDown=_FakeGtkDropDown,
            Button=_FakeGtkButton,
            StringList=_FakeGtkStringList,
            Align=SimpleNamespace(CENTER="center"),
        ),
    )
    monkeypatch.setattr(ui_actions, "Thread", _RunThread)
    monkeypatch.setattr(ui_actions.GLib, "idle_add", lambda fn, *args: fn(*args))

    content = _Container()
    app = SimpleNamespace(
        collection_content_box=content,
        backend=SimpleNamespace(
            user=None,
            get_favorite_artists_count=lambda: 100,
            get_favorite_artists_page=lambda **_kwargs: [SimpleNamespace(id="artist-1", name="Artist One")],
        ),
        grid_subtitle_label=_Label("Artists you follow and love"),
        artists_query="",
        artists_sort="name_asc",
        artists_page=0,
        artists_page_size=50,
        playlist_track_list=object(),
        queue_track_list=object(),
        batch_load_artists=lambda *_args, **_kwargs: None,
    )

    def _create_album_flow():
        app.main_flow = _Container()
        section = _Container([app.main_flow])
        app.collection_content_box.append(section)

    app.create_album_flow = _create_album_flow

    ui_actions.render_artists_dashboard(app)

    assert app.grid_subtitle_label.text == "100 Artists you follow and love"
    assert content.children[1].visible is False


def test_artist_detail_hero_height_tracks_three_equal_columns():
    content_box = _Container()
    content_box._width = 1080
    app = SimpleNamespace(
        collection_content_box=content_box,
        alb_scroll=_Scroll(_Adjustment(), width=1080),
        body_overlay=_BodyOverlay(height=900),
        win=_Window(width=1080, height=700),
        saved_width=0,
        saved_height=0,
    )

    assert ui_actions._artist_detail_available_width(app) == 1080
    assert ui_actions._artist_detail_column_width(app) == 360
    assert ui_actions._artist_detail_hero_height(app) == 360


def test_refresh_dashboard_playing_state_updates_artist_detail_top_track_row():
    row = _DashboardRow(track_id="track-42", track_name="pretty boy", track_artist="m2m")
    root = _Container([row])
    app = SimpleNamespace(
        collection_content_box=root,
        playing_track_id="track-42",
        playing_track=SimpleNamespace(
            id="track-42",
            name="Pretty Boy",
            artist=SimpleNamespace(name="M2M"),
        ),
    )

    ui_actions.refresh_dashboard_playing_state(app)

    assert "track-row-playing" in row.classes
    assert row._dashboard_playing_icon.visible is True
