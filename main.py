import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

import os, webbrowser, hashlib
from threading import Thread
from tidal_backend import TidalBackend
from audio_player import AudioPlayer
from models import HistoryManager
import utils
import ui_config

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class TidalApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.hiresti.player")
        self.backend = TidalBackend()
        # 初始化时需要的 callback
        self.player = AudioPlayer(on_eos_callback=self.on_next_track, on_tag_callback=self.update_tech_label)
        self.history_mgr = HistoryManager()
        self.cache_dir = os.path.expanduser("~/.cache/hiresti/covers")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # 状态变量
        self.current_track_list = []
        self.current_index = -1
        self.window_created = False
        self.is_programmatic_update = False

    def do_activate(self):
        if self.window_created: self.win.present(); return
        
        # 加载样式
        provider = Gtk.CssProvider()
        provider.load_from_data(ui_config.CSS_DATA.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # 构建窗口
        self.win = Adw.ApplicationWindow(application=self, title="hiresTI Desktop", default_width=ui_config.WINDOW_WIDTH, default_height=ui_config.WINDOW_HEIGHT)
        self.window_created = True
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.win.set_content(main_vbox)

        # 模块化 UI 构建
        self._build_header(main_vbox)
        self._build_body(main_vbox)
        self._build_player_bar(main_vbox)

        # 初始化状态
        if self.backend.try_load_session(): self.on_login_success()
        self.win.present()
        self.win.connect("notify::default-width", self.update_layout_proportions)
        GLib.timeout_add(1000, self.update_ui_loop)

    # --- UI 构建私有方法 ---

    def _build_header(self, container):
        header = Adw.HeaderBar(); container.append(header)
        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", sensitive=False)
        self.back_btn.connect("clicked", self.on_back_clicked)
        header.pack_start(self.back_btn)

        self.search_entry = Gtk.Entry(placeholder_text="Search Tidal...", width_request=380, valign=Gtk.Align.CENTER)
        self.search_entry.connect("activate", self.on_search)
        header.set_title_widget(self.search_entry)

        box_right = Gtk.Box(spacing=10)
        self.quality_dd = Gtk.DropDown(model=Gtk.StringList.new(["Hi-Res (FLAC)", "Standard (AAC)"]))
        self.quality_dd.set_valign(Gtk.Align.CENTER)
        box_right.append(self.quality_dd)
        
        self.login_btn = Gtk.Button(label="Login")
        self.login_btn.connect("clicked", self.on_login_clicked)
        box_right.append(self.login_btn)
        header.pack_end(box_right)

    def _build_body(self, container):
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        container.append(self.paned)

        # 侧边栏构建
        self.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.nav_list = Gtk.ListBox(css_classes=["navigation-sidebar"], margin_top=10, margin_bottom=10)
        self.nav_list.connect("row-activated", self.on_nav_selected)
        
        for nid, icon, txt in [("home", "user-bookmarks-symbolic", "My Collection"), ("history", "document-open-recent-symbolic", "History")]:
            r = Gtk.ListBoxRow(); r.nav_id = nid
            b = Gtk.Box(spacing=12, margin_start=12, margin_top=8, margin_bottom=8)
            b.append(Gtk.Image.new_from_icon_name(icon)); b.append(Gtk.Label(label=txt))
            r.set_child(b); self.nav_list.append(r)
            
        self.sidebar_box.append(self.nav_list)
        self.sidebar_box.append(Gtk.Label(label="LIBRARY", xalign=0, css_classes=["sidebar-header"]))
        
        sidebar_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.artist_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.artist_list.connect("row-activated", self.on_artist_selected)
        sidebar_scroll.set_child(self.artist_list); self.sidebar_box.append(sidebar_scroll)
        self.paned.set_start_child(self.sidebar_box)

        # 右侧堆栈构建
        self.right_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.paned.set_end_child(self.right_stack)
        
        # 1. 专辑网格视图
        grid_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.grid_title_label = Gtk.Label(label="My Collection", xalign=0, css_classes=["section-title"])
        self.artist_fav_btn = Gtk.Button(css_classes=["heart-btn"])
        self.artist_fav_btn.set_icon_name("emblem-favorite-symbolic")
        self.artist_fav_btn.set_visible(False)
        self.artist_fav_btn.connect("clicked", self.on_artist_fav_clicked)
        title_box.append(self.grid_title_label); title_box.append(self.artist_fav_btn); grid_vbox.append(title_box)
        
        self.album_flow = Gtk.FlowBox(valign=Gtk.Align.START, halign=Gtk.Align.FILL, max_children_per_line=30, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=28, margin_start=24, margin_end=24)
        self.album_flow.connect("child-activated", self.on_album_selected)
        alb_scroll = Gtk.ScrolledWindow(vexpand=True); alb_scroll.set_child(self.album_flow); grid_vbox.append(alb_scroll)
        self.right_stack.add_titled(grid_vbox, "albums", "Albums")

        # 2. 歌曲列表视图
        trk_main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); trk_scroll = Gtk.ScrolledWindow(vexpand=True); trk_content_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.album_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24, css_classes=["album-header-box"])
        self.header_art = Gtk.Image(width_request=160, height_request=160, css_classes=["header-art"])
        info_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.header_title = Gtk.Label(xalign=0, wrap=True, max_width_chars=25, css_classes=["album-title-large"])
        self.header_artist = Gtk.Label(xalign=0, css_classes=["album-artist-medium"])
        self.header_meta = Gtk.Label(xalign=0, css_classes=["album-meta"])
        info_vbox.append(self.header_title); info_vbox.append(self.header_artist); info_vbox.append(self.header_meta)
        
        self.fav_btn = Gtk.Button(css_classes=["heart-btn"])
        self.fav_btn.set_icon_name("emblem-favorite-symbolic")
        self.fav_btn.set_valign(Gtk.Align.CENTER); self.fav_btn.connect("clicked", self.on_fav_clicked)
        self.album_header_box.append(self.header_art); self.album_header_box.append(info_vbox); self.album_header_box.append(self.fav_btn)
        trk_content_vbox.append(self.album_header_box)
        
        self.track_list = Gtk.ListBox(css_classes=["boxed-list"], margin_start=32, margin_end=32)
        self.track_list.connect("row-activated", self.on_track_selected)
        trk_content_vbox.append(self.track_list); trk_scroll.set_child(trk_content_vbox); trk_main_vbox.append(trk_scroll)
        self.right_stack.add_titled(trk_main_vbox, "tracks", "Tracks")
        
        # 初始侧边栏比例
        initial_pos = int(ui_config.WINDOW_WIDTH * ui_config.SIDEBAR_RATIO)
        self.paned.set_position(initial_pos)

    def _build_player_bar(self, container):
        self.bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24, css_classes=["card-bar"])
        container.append(self.bottom_bar)
        
        self.info_area = Gtk.Box(spacing=14, valign=Gtk.Align.CENTER)
        self.art_img = Gtk.Image(width_request=64, height_request=64, css_classes=["playback-art"])
        
        # 交互手势
        gest = Gtk.GestureClick(); gest.connect("pressed", self.on_player_art_clicked); self.art_img.add_controller(gest)
        m_ctrl = Gtk.EventControllerMotion()
        m_ctrl.connect("enter", lambda c,x,y: utils.set_pointer_cursor(self.art_img, True))
        m_ctrl.connect("leave", lambda c: utils.set_pointer_cursor(self.art_img, False))
        self.art_img.add_controller(m_ctrl)
        
        t_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.lbl_title = Gtk.Label(xalign=0, css_classes=["heading"], ellipsize=3)
        self.lbl_tech = Gtk.Label(xalign=0, css_classes=["tech-label"])
        t_box.append(self.lbl_title); t_box.append(self.lbl_tech)
        self.info_area.append(self.art_img); self.info_area.append(t_box); self.bottom_bar.append(self.info_area)
        
        center_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        ctrls = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        self.play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["pill", "suggested-action"])
        self.play_btn.connect("clicked", self.on_play_pause)
        
        ctrls.append(Gtk.Button(icon_name="media-skip-backward-symbolic", css_classes=["flat"]))
        ctrls.append(self.play_btn)
        ctrls.append(Gtk.Button(icon_name="media-skip-forward-symbolic", css_classes=["flat"]))
        
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_hexpand(True); self.scale.connect("value-changed", self.on_seek)
        center_vbox.append(ctrls); center_vbox.append(self.scale); self.bottom_bar.append(center_vbox)
        
        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.vol_scale.set_value(80); self.vol_scale.set_size_request(120, -1)
        self.vol_scale.connect("value-changed", lambda s: self.player.set_volume(s.get_value()/100.0))
        self.bottom_bar.append(self.vol_scale)

    # --- 事件处理器 (核心业务逻辑) ---

    def on_login_clicked(self, btn):
        url, fut = self.backend.start_oauth(); webbrowser.open(url)
        Thread(target=lambda: self.backend.finish_login(fut) and GLib.idle_add(self.on_login_success), daemon=True).start()

    def on_login_success(self):
        self.login_btn.set_label("Hi, Eason")
        Thread(target=lambda: (GLib.idle_add(self.populate_artists, self.backend.get_favorites()), 
                               GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums()))), daemon=True).start()

    def on_nav_selected(self, box, row):
        if not row: return
        self.artist_fav_btn.set_visible(False); self.artist_list.select_row(None); self.right_stack.set_visible_child_name("albums")
        while c := self.album_flow.get_first_child(): self.album_flow.remove(c)
        if row.nav_id == "home":
            self.grid_title_label.set_text("My Collection")
            Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums()))).start()
        elif row.nav_id == "history":
            self.grid_title_label.set_text("History")
            Thread(target=lambda: GLib.idle_add(self.batch_load_albums, self.history_mgr.get_albums())).start()

    def on_artist_selected(self, box, row):
        if not row: return
        self.current_selected_artist = row.artist_obj
        self.right_stack.set_visible_child_name("albums"); self.artist_list.select_row(row); self.nav_list.select_row(None)
        self.grid_title_label.set_text(f"Albums by {row.artist_obj.name}"); self.artist_fav_btn.set_visible(True)
        if self.backend.is_artist_favorite(row.artist_obj.id): self.artist_fav_btn.add_css_class("active")
        else: self.artist_fav_btn.remove_css_class("active")
        while c := self.album_flow.get_first_child(): self.album_flow.remove(c)
        Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_albums(row.artist_obj))), daemon=True).start()

    def on_album_selected(self, flow, child):
        if child: self.show_album_details(child.album_obj)

    def show_album_details(self, alb):
        self.current_album = alb; self.right_stack.set_visible_child_name("tracks"); self.back_btn.set_sensitive(True)
        self.header_title.set_text(alb.name); self.header_artist.set_text(getattr(alb.artist, 'name', 'Unknown'))
        utils.load_img(self.header_art, lambda: self.backend.get_artwork_url(alb, 640), self.cache_dir, 160)
        if self.backend.is_favorite(alb.id): self.fav_btn.add_css_class("active")
        else: self.fav_btn.remove_css_class("active")
        while c := self.track_list.get_first_child(): self.track_list.remove(c)
        Thread(target=lambda: (ts := self.backend.get_tracks(alb)) and GLib.idle_add(self.populate_tracks, ts), daemon=True).start()

    def on_track_selected(self, box, row):
        if not row: return
        idx = row.get_index(); track = self.current_track_list[idx]; self.current_index = idx
        self.lbl_title.set_text(track.name); cover_url = self.backend.get_artwork_url(track.album, 1280)
        utils.load_img(self.art_img, cover_url, self.cache_dir, 140)
        Thread(target=lambda: self.history_mgr.add(track, cover_url), daemon=True).start()
        def play():
            url = self.backend.get_stream_url(track)
            if url: GLib.idle_add(lambda: (self.player.load(url), self.player.play(), self.play_btn.set_icon_name("media-playback-pause-symbolic")))
        Thread(target=play, daemon=True).start()

    # --- 辅助方法 & 回调 ---

    def populate_artists(self, artists):
        while c := self.artist_list.get_first_child(): self.artist_list.remove(c)
        for art in artists:
            row = Gtk.ListBoxRow(); row.artist_obj = art; box = Gtk.Box(spacing=12, margin_start=8, margin_top=4, margin_bottom=4)
            img = Gtk.Image(pixel_size=36, css_classes=["circular-avatar"])
            utils.load_img(img, lambda: self.backend.get_artwork_url(art, 160), self.cache_dir, 36)
            box.append(img); box.append(Gtk.Label(label=art.name, xalign=0)); row.set_child(box); self.artist_list.append(row)

    def batch_load_albums(self, albs, batch=6):
        if not albs: return False
        curr, rem = albs[:batch], albs[batch:]
        for alb in curr:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
            u_prov = alb.cover_url if hasattr(alb, 'cover_url') else lambda: self.backend.get_artwork_url(alb, 640)
            img = Gtk.Image(pixel_size=130, css_classes=["album-cover-img"])
            utils.load_img(img, u_prov, self.cache_dir, 130)
            v.append(img); v.append(Gtk.Label(label=alb.name, ellipsize=3, halign=Gtk.Align.CENTER, wrap=True, max_width_chars=16))
            c = Gtk.FlowBoxChild(); c.set_child(v); c.album_obj = alb; self.album_flow.append(c)
        if rem: GLib.timeout_add(50, self.batch_load_albums, rem, batch)
        return False

    def populate_tracks(self, tracks):
        self.current_track_list = tracks
        for i, t in enumerate(tracks):
            b = Gtk.Box(spacing=16, margin_top=10, margin_bottom=10)
            b.append(Gtk.Label(label=str(i+1), width_request=30, css_classes=["dim-label"]))
            b.append(Gtk.Label(label=t.name, xalign=0, hexpand=True, ellipsize=3)); self.track_list.append(b)

    def on_play_pause(self, btn):
        if self.player.is_playing(): self.player.pause(); btn.set_icon_name("media-playback-start-symbolic")
        else: self.player.play(); btn.set_icon_name("media-playback-pause-symbolic")

    def on_next_track(self):
        if self.current_index < len(self.current_track_list)-1:
            self.current_index += 1; self.on_track_selected(None, self.track_list.get_row_at_index(self.current_index))

    def on_seek(self, s): 
        if not self.is_programmatic_update: self.player.seek(s.get_value())

    def update_tech_label(self, info):
        bits = self.player.get_current_bits(); codec = info.get('codec', '-'); bitrate = info.get('bitrate', 0)
        self.lbl_tech.set_text(f"{codec} | {bits} | {bitrate//1000}kbps")

    def update_ui_loop(self):
        p, d = self.player.get_position()
        if d > 0:
            self.is_programmatic_update = True; self.scale.set_range(0, d); self.scale.set_value(p); self.is_programmatic_update = False
        return True

    def update_layout_proportions(self, w, p):
        s_px = max(int(self.win.get_width() * ui_config.SIDEBAR_RATIO), 240)
        self.paned.set_position(s_px); self.info_area.set_size_request(s_px, -1)

    def on_fav_clicked(self, btn):
        if not hasattr(self, 'current_album'): return
        is_add = "active" not in btn.get_css_classes()
        def do():
            if self.backend.toggle_album_favorite(self.current_album.id, is_add):
                GLib.idle_add(lambda: btn.add_css_class("active") if is_add else btn.remove_css_class("active"))
        Thread(target=do, daemon=True).start()

    def on_artist_fav_clicked(self, btn):
        if not hasattr(self, 'current_selected_artist'): return
        art = self.current_selected_artist; is_add = "active" not in btn.get_css_classes()
        def do():
            if self.backend.toggle_artist_favorite(art.id, is_add):
                GLib.idle_add(lambda: (btn.add_css_class("active") if is_add else btn.remove_css_class("active"),
                                      Thread(target=lambda: GLib.idle_add(self.populate_artists, self.backend.get_favorites()), daemon=True).start()))
        Thread(target=do, daemon=True).start()

    def on_search(self, entry):
        q = entry.get_text()
        if q: Thread(target=lambda: GLib.idle_add(self.populate_artists, self.backend.search_artist(q)), daemon=True).start()

    def on_back_clicked(self, btn): self.right_stack.set_visible_child_name("albums"); btn.set_sensitive(False)
    def on_player_art_clicked(self, gest, n, x, y):
        if 0 <= self.current_index < len(self.current_track_list): self.show_album_details(self.current_track_list[self.current_index].album)

if __name__ == "__main__":
    app = TidalApp()
    app.run(None)
