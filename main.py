import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GdkPixbuf, Gdk, Gio

import os, requests, webbrowser, logging, time, hashlib, json
from threading import Thread
from tidal_backend import TidalBackend
from audio_player import AudioPlayer
import ui_config

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 辅助类保持不变 ---
class LocalAlbum:
    def __init__(self, data):
        self.id = data.get('id')
        self.name = data.get('name')
        self.artist = type('obj', (object,), {'name': data.get('artist', 'Unknown')})
        self.cover_url = data.get('cover_url')
        self.release_date = None
        self.num_tracks = '?'

class HistoryManager:
    def __init__(self):
        self.path = os.path.expanduser("~/.cache/hiresti/history.json")
    def add(self, track, cover_url):
        try:
            history = self.load_raw()
            alb_id = track.album.id
            history = [h for h in history if h.get('id') != alb_id]
            new_entry = { 'id': alb_id, 'name': track.album.name, 'artist': getattr(track.artist, 'name', 'Unknown'), 'cover_url': cover_url, 'timestamp': time.time() }
            history.insert(0, new_entry); history = history[:50]
            with open(self.path, 'w') as f: json.dump(history, f)
        except: pass
    def load_raw(self):
        if not os.path.exists(self.path): return []
        try: 
            with open(self.path, 'r') as f: return json.load(f)
        except: return []
    def get_albums(self): return [LocalAlbum(x) for x in self.load_raw()]

class TidalApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.hiresti.player", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.backend = TidalBackend()
        self.player = AudioPlayer(on_eos_callback=self.on_next_track, on_tag_callback=self.update_tech_label)
        self.history_mgr = HistoryManager()
        self.current_track_list = []; self.current_index = -1
        self.window_created = False; self.is_programmatic_update = False
        self.cache_dir = os.path.expanduser("~/.cache/hiresti/covers")
        os.makedirs(self.cache_dir, exist_ok=True)

    def do_activate(self):
        if self.window_created: self.win.present(); return
        provider = Gtk.CssProvider()
        
        # 修复：移除了不支持的 'cursor: pointer'，保留 opacity 动画
        css_tweaks = ui_config.CSS_DATA + """
        .playback-art { transition: opacity 0.2s; }
        .playback-art:hover { opacity: 0.8; } 
        """
        provider.load_from_data(css_tweaks.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win = Adw.ApplicationWindow(application=self, title="hiresTI Desktop", default_width=ui_config.WINDOW_WIDTH, default_height=ui_config.WINDOW_HEIGHT)
        self.window_created = True
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.win.set_content(main_vbox)

        # HeaderBar
        header = Adw.HeaderBar()
        main_vbox.append(header)
        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", sensitive=False)
        self.back_btn.connect("clicked", self.on_back_clicked)
        header.pack_start(self.back_btn)
        self.search_entry = Gtk.Entry(placeholder_text="Search Tidal...", width_request=380, valign=Gtk.Align.CENTER)
        self.search_entry.connect("activate", self.on_search)
        header.set_title_widget(self.search_entry)
        box_right = Gtk.Box(spacing=10)
        self.quality_dd = Gtk.DropDown(model=Gtk.StringList.new(["Hi-Res (FLAC)", "Standard (AAC)"]))
        self.quality_dd.set_valign(Gtk.Align.CENTER)
        self.quality_dd.connect("notify::selected-item", self.on_quality_changed)
        box_right.append(self.quality_dd)
        self.login_btn = Gtk.Button(label="Login")
        self.login_btn.connect("clicked", self.on_login_clicked)
        box_right.append(self.login_btn)
        header.pack_end(box_right)

        # Body
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        main_vbox.append(self.paned)

        # Sidebar
        self.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.nav_list = Gtk.ListBox(css_classes=["navigation-sidebar"], margin_top=10, margin_bottom=10)
        self.nav_list.connect("row-activated", self.on_nav_selected)
        
        row_home = Gtk.ListBoxRow(); row_home.nav_id = "home"
        box_home = Gtk.Box(spacing=12, margin_start=12, margin_top=8, margin_bottom=8)
        box_home.append(Gtk.Image.new_from_icon_name("user-bookmarks-symbolic"))
        box_home.append(Gtk.Label(label="My Collection", css_classes=["sidebar-row-label"]))
        row_home.set_child(box_home); self.nav_list.append(row_home)

        row_hist = Gtk.ListBoxRow(); row_hist.nav_id = "history"
        box_hist = Gtk.Box(spacing=12, margin_start=12, margin_top=8, margin_bottom=8)
        box_hist.append(Gtk.Image.new_from_icon_name("document-open-recent-symbolic"))
        box_hist.append(Gtk.Label(label="History", css_classes=["sidebar-row-label"]))
        row_hist.set_child(box_hist); self.nav_list.append(row_hist)

        self.sidebar_box.append(self.nav_list)
        self.sidebar_box.append(Gtk.Label(label="LIBRARY", xalign=0, css_classes=["sidebar-header"]))
        sidebar_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.artist_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.artist_list.connect("row-activated", self.on_artist_selected)
        sidebar_scroll.set_child(self.artist_list); self.sidebar_box.append(sidebar_scroll)
        self.paned.set_start_child(self.sidebar_box)

        # Right Stack
        self.right_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.paned.set_end_child(self.right_stack)
        
        # 强制设置初始比例
        initial_pos = int(ui_config.WINDOW_WIDTH * ui_config.SIDEBAR_RATIO)
        self.paned.set_position(initial_pos)

        # Grid
        grid_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.grid_title_label = Gtk.Label(label="My Collection", xalign=0, css_classes=["section-title"])
        grid_vbox.append(self.grid_title_label)
        self.album_flow = Gtk.FlowBox(valign=Gtk.Align.START, halign=Gtk.Align.FILL, homogeneous=False, max_children_per_line=30, min_children_per_line=1, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=28, margin_start=24, margin_end=24, margin_bottom=24)
        self.album_flow.connect("child-activated", self.on_album_selected)
        alb_scroll = Gtk.ScrolledWindow(vexpand=True); alb_scroll.set_child(self.album_flow); grid_vbox.append(alb_scroll)
        self.right_stack.add_titled(grid_vbox, "albums", "Albums")

        # Track List
        trk_main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        trk_scroll = Gtk.ScrolledWindow(vexpand=True)
        trk_content_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.album_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24, css_classes=["album-header-box"])
        self.header_art = Gtk.Image(width_request=160, height_request=160, css_classes=["header-art"])
        
        info_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        info_vbox.set_hexpand(True) 
        
        self.header_title = Gtk.Label(xalign=0, wrap=True, max_width_chars=25, css_classes=["album-title-large"])
        self.header_artist = Gtk.Label(xalign=0, css_classes=["album-artist-medium"])
        self.header_meta = Gtk.Label(xalign=0, css_classes=["album-meta"])
        
        info_vbox.append(self.header_title)
        info_vbox.append(self.header_artist)
        info_vbox.append(self.header_meta)
        
        self.fav_btn = Gtk.Button(css_classes=["heart-btn"])
        self.fav_btn.set_icon_name("emblem-favorite-symbolic")
        self.fav_btn.set_valign(Gtk.Align.CENTER)
        self.fav_btn.connect("clicked", self.on_fav_clicked)
        
        self.album_header_box.append(self.header_art)
        self.album_header_box.append(info_vbox)
        self.album_header_box.append(self.fav_btn)
        
        trk_content_vbox.append(self.album_header_box)
        self.track_list = Gtk.ListBox(css_classes=["boxed-list"], margin_start=32, margin_end=32, margin_bottom=32)
        self.track_list.connect("row-activated", self.on_track_selected)
        trk_content_vbox.append(self.track_list); trk_scroll.set_child(trk_content_vbox)
        trk_main_vbox.append(trk_scroll); self.right_stack.add_titled(trk_main_vbox, "tracks", "Tracks")

        # Bottom Bar
        self.bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24, css_classes=["card-bar"])
        main_vbox.append(self.bottom_bar)
        
        self.info_area = Gtk.Box(spacing=14, valign=Gtk.Align.CENTER)
        self.art_img = Gtk.Image(width_request=64, height_request=64, css_classes=["playback-art"])
        
        # --- 核心修复：光标和点击事件 ---
        
        # 1. 点击事件
        gesture = Gtk.GestureClick()
        gesture.connect("pressed", self.on_player_art_clicked)
        self.art_img.add_controller(gesture)
        
        # 2. 悬停变手型光标 (使用 EventControllerMotion)
        cursor_ctrl = Gtk.EventControllerMotion()
        def on_enter(ctrl, x, y):
            self.art_img.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        def on_leave(ctrl):
            self.art_img.set_cursor(None)
        cursor_ctrl.connect("enter", on_enter)
        cursor_ctrl.connect("leave", on_leave)
        self.art_img.add_controller(cursor_ctrl)
        
        t_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.lbl_title = Gtk.Label(xalign=0, css_classes=["heading"], ellipsize=3); self.lbl_tech = Gtk.Label(xalign=0, css_classes=["tech-label"])
        t_box.append(self.lbl_title); t_box.append(self.lbl_tech)
        self.info_area.append(self.art_img); self.info_area.append(t_box); self.bottom_bar.append(self.info_area)

        center_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        ctrls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER)
        self.play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["pill", "suggested-action"])
        self.play_btn.connect("clicked", self.on_play_pause)
        ctrls.append(Gtk.Button(icon_name="media-skip-backward-symbolic", css_classes=["flat"])); ctrls.append(self.play_btn); ctrls.append(Gtk.Button(icon_name="media-skip-forward-symbolic", css_classes=["flat"]))
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_hexpand(True); self.scale.connect("value-changed", self.on_seek)
        center_vbox.append(ctrls); center_vbox.append(self.scale); self.bottom_bar.append(center_vbox)

        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.vol_scale.set_value(80); self.vol_scale.set_size_request(120, -1)
        self.vol_scale.connect("value-changed", lambda s: self.player.set_volume(s.get_value()/100.0))
        self.bottom_bar.append(self.vol_scale)

        self.win.connect("notify::default-width", self.update_layout_proportions)
        if self.backend.try_load_session(): self.on_login_success()
        self.win.present(); GLib.timeout_add(1000, self.update_ui_loop)

    # --- Methods ---
    def load_img(self, w, url_provider, size=84):
        def fetch():
            try:
                u = url_provider() if callable(url_provider) else url_provider
                if not u: return
                f_name = hashlib.md5(u.encode('utf-8')).hexdigest()
                f_path = os.path.join(self.cache_dir, f_name)
                if not os.path.exists(f_path):
                    r = requests.get(str(u), timeout=10, verify=False)
                    if r.status_code == 200:
                        with open(f_path, 'wb') as f: f.write(r.content)
                    else: return
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(f_path, size, size, True)
                GLib.idle_add(w.set_from_pixbuf, pix)
            except Exception as e:
                if 'f_path' in locals() and os.path.exists(f_path):
                    try: os.remove(f_path)
                    except: pass
        Thread(target=fetch, daemon=True).start()

    def show_album_details(self, alb):
        self.current_album = alb
        self.right_stack.set_visible_child_name("tracks")
        self.back_btn.set_sensitive(True)
        self.header_title.set_text(alb.name)
        self.header_artist.set_text(getattr(alb.artist, 'name', 'Unknown Artist'))
        year = str(alb.release_date.year) if hasattr(alb, 'release_date') and alb.release_date else ""
        tracks_count = getattr(alb, 'num_tracks', '?')
        self.header_meta.set_text(f"{year}  •  {tracks_count} Tracks".strip(' •'))
        if self.backend.is_favorite(alb.id): self.fav_btn.add_css_class("active")
        else: self.fav_btn.remove_css_class("active")
        if hasattr(alb, 'cover_url') and alb.cover_url: self.load_img(self.header_art, alb.cover_url, 160)
        else: self.load_img(self.header_art, lambda: self.backend.get_artwork_url(alb, 640), 160)
        while c := self.track_list.get_first_child(): self.track_list.remove(c)
        Thread(target=lambda: (ts := self.backend.get_tracks(alb)) and GLib.idle_add(self.populate_tracks, ts), daemon=True).start()

    def on_album_selected(self, flow, child):
        if child: self.show_album_details(child.album_obj)

    def on_player_art_clicked(self, gesture, n_press, x, y):
        if self.current_index >= 0 and self.current_index < len(self.current_track_list):
            current_track = self.current_track_list[self.current_index]
            if hasattr(current_track, 'album'): self.show_album_details(current_track.album)

    def on_track_selected(self, box, row):
        if not row: return
        idx = row.get_index(); track = self.current_track_list[idx]; self.current_index = idx
        self.lbl_title.set_text(track.name)
        cover_url = self.backend.get_artwork_url(track.album, 1280)
        self.load_img(self.art_img, cover_url, 140)
        Thread(target=lambda: self.history_mgr.add(track, cover_url), daemon=True).start()
        def play():
            url = self.backend.get_stream_url(track)
            if url: GLib.idle_add(lambda: (self.player.load(url), self.player.play(), self.play_btn.set_icon_name("media-playback-pause-symbolic")))
        Thread(target=play, daemon=True).start()

    def populate_tracks(self, tracks):
        self.current_track_list = tracks
        for i, t in enumerate(tracks):
            b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, margin_top=10, margin_bottom=10, spacing=16)
            b.append(Gtk.Label(label=str(i+1), width_request=30, css_classes=["dim-label"]))
            b.append(Gtk.Label(label=getattr(t, 'name', 'Unknown'), xalign=0, hexpand=True, ellipsize=3))
            if getattr(t, 'duration', 0): b.append(Gtk.Label(label=f"{int(t.duration)//60}:{int(t.duration)%60:02d}", css_classes=["dim-label"]))
            self.track_list.append(b)

    def on_fav_clicked(self, btn):
        if not hasattr(self, 'current_album'): return
        alb_id = self.current_album.id
        is_currently_fav = self.backend.is_favorite(alb_id)
        action_add = not is_currently_fav
        def do_toggle():
            success = self.backend.toggle_album_favorite(alb_id, action_add)
            if success: GLib.idle_add(self.update_fav_icon, action_add)
        Thread(target=do_toggle, daemon=True).start()

    def update_fav_icon(self, is_fav):
        if is_fav: self.fav_btn.add_css_class("active")
        else: self.fav_btn.remove_css_class("active")

    def on_nav_selected(self, box, row):
        if not row: return
        nav_id = getattr(row, 'nav_id', None)
        self.artist_list.select_row(None) 
        self.right_stack.set_visible_child_name("albums")
        while c := self.album_flow.get_first_child(): self.album_flow.remove(c)
        if nav_id == "home":
            self.grid_title_label.set_text("My Collection")
            Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums()))).start()
        elif nav_id == "history":
            self.grid_title_label.set_text("Recently Played (Local)")
            hist_albums = self.history_mgr.get_albums()
            Thread(target=lambda: GLib.idle_add(self.batch_load_albums, hist_albums)).start()

    def batch_load_albums(self, albs, batch=6):
        if not albs: return False
        curr, rem = albs[:batch], albs[batch:]
        for alb in curr:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
            v.set_hexpand(False); v.set_halign(Gtk.Align.CENTER)
            if hasattr(alb, 'cover_url') and alb.cover_url: url_prov = alb.cover_url
            else: url_prov = lambda: self.backend.get_artwork_url(alb, 640)
            img = Gtk.Image(pixel_size=130, css_classes=["album-cover-img"]); self.load_img(img, url_prov, 130)
            v.append(img); v.append(Gtk.Label(label=alb.name, ellipsize=3, halign=Gtk.Align.CENTER, wrap=True, max_width_chars=16))
            c = Gtk.FlowBoxChild(); c.set_child(v); c.album_obj = alb
            c.set_hexpand(False); c.set_halign(Gtk.Align.CENTER)
            self.album_flow.append(c)
        if rem: GLib.timeout_add(50, self.batch_load_albums, rem, batch)
        return False

    def on_artist_selected(self, box, row):
        if not row: return
        self.right_stack.set_visible_child_name("albums")
        self.artist_list.select_row(row) 
        self.nav_list.select_row(None)
        self.grid_title_label.set_text(f"Albums by {row.artist_obj.name}")
        while c := self.album_flow.get_first_child(): self.album_flow.remove(c)
        Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_albums(row.artist_obj))), daemon=True).start()

    def on_quality_changed(self, dd, p):
        selected = dd.get_selected_item().get_string()
        self.backend.set_quality_mode(selected)
    def update_tech_label(self, info):
        bits = self.player.get_current_bits()
        codec = info.get('codec', '-')
        bitrate = info.get('bitrate', 0)
        if "FLAC" in str(codec).upper() and bits == "-":
            if bitrate > 1500000: bits = "24-bit"
            else: bits = "16-bit"
        display_br = f"{bitrate//1000} kbps" if bitrate > 0 else ""
        self.lbl_tech.set_text(f"{codec} | {bits} | {display_br}")
    def on_login_clicked(self, btn):
        url, f = self.backend.start_oauth(); webbrowser.open(url)
        Thread(target=lambda: self.backend.finish_login(f) and GLib.idle_add(self.on_login_success), daemon=True).start()
    def on_login_success(self):
        self.login_btn.set_label("Hi, Eason")
        self.grid_title_label.set_text("My Collection")
        Thread(target=lambda: (GLib.idle_add(self.populate_artists, self.backend.get_favorites()), 
                               GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums()))), daemon=True).start()
    def on_search(self, entry):
        q = entry.get_text()
        if q: Thread(target=lambda: GLib.idle_add(self.populate_artists, self.backend.search_artist(q)), daemon=True).start()
    def populate_artists(self, artists):
        while c := self.artist_list.get_first_child(): self.artist_list.remove(c)
        for art in artists:
            row = Gtk.ListBoxRow(); row.artist_obj = art; box = Gtk.Box(spacing=12, margin_start=8, margin_top=4, margin_bottom=4)
            img = Gtk.Image(pixel_size=36, css_classes=["circular-avatar"])
            self.load_img(img, lambda: self.backend.get_artwork_url(art, 160), 36)
            box.append(img); box.append(Gtk.Label(label=art.name, xalign=0))
            row.set_child(box); self.artist_list.append(row)
    def on_play_pause(self, btn):
        if self.player.is_playing(): self.player.pause(); btn.set_icon_name("media-playback-start-symbolic")
        else: self.player.play(); btn.set_icon_name("media-playback-pause-symbolic")
    def on_next_track(self):
        if self.current_index < len(self.current_track_list)-1:
            self.current_index += 1; self.on_track_selected(None, self.track_list.get_row_at_index(self.current_index))
    def on_back_clicked(self, btn): self.right_stack.set_visible_child_name("albums"); btn.set_sensitive(False)
    def on_seek(self, s): 
        if not self.is_programmatic_update: self.player.seek(s.get_value())
    def update_ui_loop(self):
        p, d = self.player.get_position()
        if d > 0:
            self.is_programmatic_update = True; self.scale.set_range(0, d); self.scale.set_value(p); self.is_programmatic_update = False
            if self.player.is_playing(): self.update_tech_label(self.player.stream_info)
        return True
    def update_layout_proportions(self, w, p):
        width = self.win.get_width(); s_px = max(int(width * ui_config.SIDEBAR_RATIO), 240)
        self.paned.set_position(s_px); self.info_area.set_size_request(s_px, -1)

if __name__ == "__main__":
    app = TidalApp()
    app.run(None)
