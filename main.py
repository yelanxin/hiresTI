import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, GdkPixbuf

import os, webbrowser, hashlib, json
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
        self.settings_file = os.path.expanduser("~/.cache/hiresti/settings.json")
        self.settings = {
            "driver": "Auto (Default)", 
            "device": "Default Device",
            "bit_perfect": False 
        }
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    self.settings.update(json.load(f))
            except: pass

        self.player = AudioPlayer(on_eos_callback=self.on_next_track, on_tag_callback=self.update_tech_label)
        self.history_mgr = HistoryManager()
        self.cache_dir = os.path.expanduser("~/.cache/hiresti/covers")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.current_track_list = []; self.current_index = -1
        self.window_created = False; self.is_programmatic_update = False
        self.current_device_list = [] 

    def save_settings(self):
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f)
        except: pass

    def do_activate(self):
        if self.window_created: self.win.present(); return
        
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icons_path = os.path.join(os.path.dirname(__file__), "icons")
        if os.path.exists(icons_path):
            icon_theme.add_search_path(icons_path)

        provider = Gtk.CssProvider()
        provider.load_from_data(ui_config.CSS_DATA.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win = Adw.ApplicationWindow(application=self, title="hiresTI Desktop", default_width=ui_config.WINDOW_WIDTH, default_height=ui_config.WINDOW_HEIGHT)
        self.window_created = True; main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); self.win.set_content(main_vbox)

        self._build_header(main_vbox)
        self._build_body(main_vbox)
        self._build_player_bar(main_vbox)

        # [RESTORE SETTINGS]
        if self.settings.get("bit_perfect", False):
            print("[Init] Restoring Bit-Perfect Mode...")
            found = self.player.toggle_bit_perfect(True)
            if hasattr(self, 'bp_switch'): self.bp_switch.set_active(True)
            if hasattr(self, 'eq_btn'): self.eq_btn.set_sensitive(False) # Disable EQ
            # [NEW] Show the icon
            if hasattr(self, 'bp_icon'): self.bp_icon.set_visible(True)
            
            if found:
                if hasattr(self, 'driver_dd'): self.driver_dd.set_sensitive(False)
                if hasattr(self, 'device_dd'): self.device_dd.set_sensitive(False)
        else:
             saved_drv = self.settings.get("driver", "Auto (Default)")
             if saved_drv != "Auto (Default)":
                 self.player.set_output(saved_drv)

        if self.backend.try_load_session(): self.on_login_success()
        self.win.present()
        self.win.connect("notify::default-width", self.update_layout_proportions)
        GLib.timeout_add(1000, self.update_ui_loop)

    def _build_header(self, container):
        header = Adw.HeaderBar(); container.append(header)
        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", sensitive=False)
        self.back_btn.connect("clicked", self.on_back_clicked); header.pack_start(self.back_btn)
        
        self.search_entry = Gtk.Entry(placeholder_text="Search...", width_request=300, valign=Gtk.Align.CENTER)
        self.search_entry.connect("activate", self.on_search); header.set_title_widget(self.search_entry)
        
        box_right = Gtk.Box(spacing=6)
        self.login_btn = Gtk.Button(label="Login", css_classes=["flat"])
        self.login_btn.connect("clicked", self.on_login_clicked)
        
        self.settings_btn = Gtk.Button(icon_name="emblem-system-symbolic", css_classes=["flat"])
        self.settings_btn.set_tooltip_text("Settings")
        self.settings_btn.connect("clicked", self.on_settings_clicked)
        
        box_right.append(self.login_btn)
        box_right.append(self.settings_btn)
        header.pack_end(box_right)

    def _build_body(self, container):
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True); container.append(self.paned)
        self.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.nav_list = Gtk.ListBox(css_classes=["navigation-sidebar"], margin_top=10); self.nav_list.connect("row-activated", self.on_nav_selected)
        
        for nid, icon, txt in [("home", "user-bookmarks-symbolic", "My Collection"), ("history", "document-open-recent-symbolic", "History")]:
            r = Gtk.ListBoxRow(); r.nav_id = nid; b = Gtk.Box(spacing=12, margin_start=12, margin_top=8, margin_bottom=8)
            b.append(Gtk.Image.new_from_icon_name(icon)); b.append(Gtk.Label(label=txt)); r.set_child(b); self.nav_list.append(r)
            
        self.sidebar_box.append(self.nav_list); self.sidebar_box.append(Gtk.Label(label="LIBRARY", xalign=0, css_classes=["sidebar-header"]))
        sidebar_scroll = Gtk.ScrolledWindow(vexpand=True); self.artist_list = Gtk.ListBox(css_classes=["navigation-sidebar"]); self.artist_list.connect("row-activated", self.on_artist_selected); sidebar_scroll.set_child(self.artist_list); self.sidebar_box.append(sidebar_scroll)
        self.paned.set_start_child(self.sidebar_box)

        self.right_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT); self.paned.set_end_child(self.right_stack)
        
        self._build_albums_grid()
        self._build_tracks_view()
        self._build_settings_page()
        
        self.paned.set_position(int(ui_config.WINDOW_WIDTH * ui_config.SIDEBAR_RATIO))

    def _build_albums_grid(self):
        grid_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        t_box = Gtk.Box(spacing=12); self.grid_title_label = Gtk.Label(label="My Collection", xalign=0, css_classes=["section-title"]); self.artist_fav_btn = Gtk.Button(css_classes=["heart-btn"], icon_name="emblem-favorite-symbolic", visible=False); self.artist_fav_btn.connect("clicked", self.on_artist_fav_clicked)
        t_box.append(self.grid_title_label); t_box.append(self.artist_fav_btn); grid_vbox.append(t_box)
        self.album_flow = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=30, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=28, margin_start=24); self.album_flow.connect("child-activated", self.on_album_selected)
        alb_scroll = Gtk.ScrolledWindow(vexpand=True); alb_scroll.set_child(self.album_flow); grid_vbox.append(alb_scroll)
        self.right_stack.add_named(grid_vbox, "albums")

    def _build_tracks_view(self):
        trk_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); trk_scroll = Gtk.ScrolledWindow(vexpand=True); trk_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.album_header_box = Gtk.Box(spacing=24, css_classes=["album-header-box"]); self.header_art = Gtk.Image(width_request=160, height_request=160, css_classes=["header-art"])
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.header_title = Gtk.Label(xalign=0, wrap=True, css_classes=["album-title-large"]); self.header_artist = Gtk.Label(xalign=0, css_classes=["album-artist-medium"]); self.header_meta = Gtk.Label(xalign=0, css_classes=["album-meta"])
        info.append(self.header_title); info.append(self.header_artist); info.append(self.header_meta); self.fav_btn = Gtk.Button(css_classes=["heart-btn"], icon_name="emblem-favorite-symbolic", valign=Gtk.Align.CENTER); self.fav_btn.connect("clicked", self.on_fav_clicked)
        self.album_header_box.append(self.header_art); self.album_header_box.append(info); self.album_header_box.append(self.fav_btn); trk_content.append(self.album_header_box)
        self.track_list = Gtk.ListBox(css_classes=["boxed-list"], margin_start=32, margin_end=32); self.track_list.connect("row-activated", self.on_track_selected); trk_content.append(self.track_list); trk_scroll.set_child(trk_content); trk_vbox.append(trk_scroll)
        self.right_stack.add_named(trk_vbox, "tracks")

    def _build_settings_page(self):
        settings_scroll = Gtk.ScrolledWindow(vexpand=True)
        settings_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-container"], spacing=20)
        settings_scroll.set_child(settings_vbox)
        
        settings_vbox.append(Gtk.Label(label="Settings", xalign=0, css_classes=["album-title-large"], margin_bottom=10))

        group_q = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])
        row_q = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        row_q.append(Gtk.Label(label="Streaming Quality", hexpand=True, xalign=0))
        self.quality_dd = Gtk.DropDown(model=Gtk.StringList.new(["Hi-Res (FLAC)", "Standard (AAC)"]))
        self.quality_dd.connect("notify::selected-item", self.on_quality_changed)
        row_q.append(self.quality_dd)
        group_q.append(row_q)
        settings_vbox.append(group_q)

        settings_vbox.append(Gtk.Label(label="Audio Output", xalign=0, css_classes=["section-title"], margin_top=10))
        group_out = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])
        
        row_bp = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        bp_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        bp_info.append(Gtk.Label(label="Bit-Perfect Mode", xalign=0, css_classes=["settings-label"]))
        bp_info.append(Gtk.Label(label="Exclusive hardware lock", xalign=0, css_classes=["dim-label"]))
        row_bp.append(bp_info)
        row_bp.append(Gtk.Box(hexpand=True))
        
        self.bp_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.bp_switch.connect("state-set", self.on_bit_perfect_toggled)
        row_bp.append(self.bp_switch)
        group_out.append(row_bp)

        row_drv = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        row_drv.append(Gtk.Label(label="Audio Driver", hexpand=True, xalign=0))
        drivers = self.player.get_drivers()
        self.driver_dd = Gtk.DropDown(model=Gtk.StringList.new(drivers))
        saved_drv = self.settings.get("driver")
        if saved_drv in drivers:
             for i, d in enumerate(drivers):
                 if d == saved_drv:
                     self.driver_dd.set_selected(i); break
        self.driver_dd.connect("notify::selected-item", self.on_driver_changed)
        row_drv.append(self.driver_dd)
        group_out.append(row_drv)

        row_dev = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        row_dev.append(Gtk.Label(label="Output Device", hexpand=True, xalign=0))
        self.device_dd = Gtk.DropDown(model=Gtk.StringList.new(["Default"]))
        self.device_dd.set_sensitive(False)
        self.device_dd.connect("notify::selected-item", self.on_device_changed)
        row_dev.append(self.device_dd)
        group_out.append(row_dev)
        
        settings_vbox.append(group_out)
        self.right_stack.add_named(settings_scroll, "settings")
        
        if not self.settings.get("bit_perfect", False):
            GLib.idle_add(lambda: self.on_driver_changed(self.driver_dd, None))

    def _build_eq_popover(self):
        pop = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        hb = Gtk.Box(spacing=12)
        hb.append(Gtk.Label(label="10-Band Equalizer", css_classes=["title-4"]))
        reset = Gtk.Button(label="Reset", css_classes=["flat"])
        reset.connect("clicked", lambda b: (self.player.reset_eq(), [s.set_value(0) for s in self.sliders]))
        hb.append(reset)
        vbox.append(hb)
        hbox = Gtk.Box(spacing=8)
        freqs = ["30", "60", "120", "240", "480", "1k", "2k", "4k", "8k", "16k"]
        self.sliders = []
        for i, f in enumerate(freqs):
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -24, 12, 1)
            scale.set_inverted(True)
            scale.set_size_request(-1, 150)
            scale.set_value(0)
            scale.add_mark(0, Gtk.PositionType.RIGHT, None)
            scale.connect("value-changed", lambda s, idx=i: self.player.set_eq_band(idx, s.get_value()))
            self.sliders.append(scale)
            vb.append(scale); vb.append(Gtk.Label(label=f, css_classes=["caption"])); hbox.append(vb)
        vbox.append(hbox); pop.set_child(vbox)
        return pop

    def _build_player_bar(self, container):
        self.bottom_bar = Gtk.Box(spacing=24, css_classes=["card-bar"]); container.append(self.bottom_bar)
        self.info_area = Gtk.Box(spacing=14, valign=Gtk.Align.CENTER)
        self.art_img = Gtk.Image(width_request=64, height_request=64, css_classes=["playback-art"])
        gest = Gtk.GestureClick(); gest.connect("pressed", self.on_player_art_clicked); self.art_img.add_controller(gest)
        m = Gtk.EventControllerMotion(); m.connect("enter", lambda c,x,y: utils.set_pointer_cursor(self.art_img, True)); m.connect("leave", lambda c: utils.set_pointer_cursor(self.art_img, False)); self.art_img.add_controller(m)
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER); self.lbl_title = Gtk.Label(xalign=0, css_classes=["heading"], ellipsize=3); t.append(self.lbl_title)
        self.info_area.append(self.art_img); self.info_area.append(t); self.bottom_bar.append(self.info_area)
        
        c_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        ctrls = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER); ctrls.append(Gtk.Button(icon_name="media-skip-backward-symbolic", css_classes=["flat"]))
        self.play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["pill", "suggested-action"]); self.play_btn.connect("clicked", self.on_play_pause); ctrls.append(self.play_btn)
        ctrls.append(Gtk.Button(icon_name="media-skip-forward-symbolic", css_classes=["flat"])); c_box.append(ctrls)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); self.scale.set_hexpand(True); self.scale.connect("value-changed", self.on_seek); c_box.append(self.scale)
        
        # [NEW] Center Tech Info with Icon
        tech_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=4)
        
        # The Bit-Perfect Icon (Hidden by default)
        self.bp_icon = Gtk.Image(icon_name="audio-card-symbolic") # Represents 'Hardware'
        self.bp_icon.set_tooltip_text("Bit-Perfect Mode (Exclusive Hardware Access)")
        self.bp_icon.set_visible(False)
        # Optional: Add a CSS class if you want to color it
        # self.bp_icon.add_css_class("accent-color") 
        tech_box.append(self.bp_icon)
        
        self.lbl_tech = Gtk.Label(label="-", css_classes=["tech-label"])
        tech_box.append(self.lbl_tech)
        
        c_box.append(tech_box)
        self.bottom_bar.append(c_box)

        r_box = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        self.eq_btn = Gtk.Button(icon_name="eq-icon-symbolic", css_classes=["flat"]); self.eq_btn.set_tooltip_text("Equalizer")
        self.eq_pop = self._build_eq_popover(); self.eq_pop.set_parent(self.eq_btn); self.eq_btn.connect("clicked", lambda b: self.eq_pop.popup()); r_box.append(self.eq_btn)
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5); self.vol.set_value(80); self.vol.set_size_request(120, -1); self.vol.connect("value-changed", lambda s: self.player.set_volume(s.get_value()/100.0)); r_box.append(self.vol)
        self.bottom_bar.append(r_box)

    def on_bit_perfect_toggled(self, switch, state):
        found = self.player.toggle_bit_perfect(state)
        # Disable EQ button and Show Icon
        self.eq_btn.set_sensitive(not state)
        if state: self.eq_pop.popdown()
        
        if hasattr(self, 'bp_icon'): self.bp_icon.set_visible(state)
        
        if state:
            if found:
                self.driver_dd.set_sensitive(False)
                self.device_dd.set_sensitive(False)
            else:
                switch.set_active(False); return True
        else:
            self.driver_dd.set_sensitive(True)
            self.device_dd.set_sensitive(True)
            self.on_driver_changed(self.driver_dd, None)
        self.settings["bit_perfect"] = state
        self.save_settings()

    def update_tech_label(self, info):
        fmt = self.player.get_format_string()
        txt = f"{info.get('codec','-')} | {fmt} | {info.get('bitrate',0)//1000}kbps"
        self.lbl_tech.set_text(txt)

    def on_login_clicked(self, btn):
        u, f = self.backend.start_oauth(); webbrowser.open(u)
        Thread(target=lambda: self.backend.finish_login(f) and GLib.idle_add(self.on_login_success), daemon=True).start()

    def on_login_success(self):
        self.login_btn.set_label("Hi, Eason")
        Thread(target=lambda: (GLib.idle_add(self.populate_artists, self.backend.get_favorites()), GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums()))), daemon=True).start()

    def on_settings_clicked(self, btn):
        self.right_stack.set_visible_child_name("settings")
        self.grid_title_label.set_text("Settings")
        self.back_btn.set_sensitive(True)
        self.nav_list.select_row(None)
        self.artist_list.select_row(None)

    def on_quality_changed(self, dd, p):
        selected = dd.get_selected_item()
        if not selected: return
        label = selected.get_string()
        print(f"[Settings] Quality switched to: {label}")
        self.backend.set_quality_mode(label)
        if self.player.is_playing() and 0 <= self.current_index < len(self.current_track_list):
            pos, _ = self.player.get_position()
            new_url = self.backend.get_stream_url(self.current_track_list[self.current_index])
            if new_url:
                self.player.load(new_url); self.player.play()
                GLib.timeout_add(100, lambda: self.player.seek(pos))

    def on_driver_changed(self, dd, p):
        if self.settings.get("bit_perfect", False): return
        selected = dd.get_selected_item()
        if not selected: return
        driver_name = selected.get_string()
        self.settings["driver"] = driver_name
        self.save_settings()
        self.player.set_output(driver_name)
        def refresh_devices():
            self.ignore_device_change = True
            devices = self.player.get_devices_for_driver(driver_name)
            self.current_device_list = devices 
            names = [d["name"] for d in devices]
            self.device_dd.set_model(Gtk.StringList.new(names))
            saved_dev = self.settings.get("device")
            sel_idx = 0; found_saved = False
            if saved_dev:
                for i, name in enumerate(names):
                    if name == saved_dev: sel_idx = i; found_saved = True; break
            self.device_dd.set_sensitive(len(names) > 1)
            self.device_dd.set_selected(sel_idx)
            self.ignore_device_change = False
            if found_saved:
                if sel_idx < len(self.current_device_list): self.player.set_output(driver_name, self.current_device_list[sel_idx]['device_id'])
            else: GLib.idle_add(lambda: self.on_device_changed(self.device_dd, None))
        Thread(target=lambda: GLib.idle_add(refresh_devices), daemon=True).start()

    def on_device_changed(self, dd, p):
        if getattr(self, 'ignore_device_change', False) or self.settings.get("bit_perfect", False): return
        idx = dd.get_selected()
        if hasattr(self, 'current_device_list') and idx < len(self.current_device_list):
            device_info = self.current_device_list[idx]
            self.settings["device"] = device_info['name']
            self.save_settings()
            driver_label = self.driver_dd.get_selected_item().get_string()
            self.player.set_output(driver_label, device_info['device_id'])

    def on_album_selected(self, flow, child):
        if child: self.show_album_details(child.album_obj)

    def show_album_details(self, alb):
        self.current_album = alb; self.right_stack.set_visible_child_name("tracks"); self.back_btn.set_sensitive(True)
        self.header_title.set_text(alb.name); self.header_artist.set_text(getattr(alb.artist, 'name', 'Unknown'))
        utils.load_img(self.header_art, lambda: self.backend.get_artwork_url(alb, 640), self.cache_dir, 160)
        self.fav_btn.add_css_class("active") if self.backend.is_favorite(alb.id) else self.fav_btn.remove_css_class("active")
        while c := self.track_list.get_first_child(): self.track_list.remove(c)
        def detail_task():
            ts = self.backend.get_tracks(alb)
            if not hasattr(alb, 'release_date') or not alb.release_date:
                try: full = self.backend.session.album(str(alb.id)); GLib.idle_add(self._update_meta, full)
                except: pass
            else: GLib.idle_add(self._update_meta, alb)
            GLib.idle_add(self.populate_tracks, ts)
        Thread(target=detail_task, daemon=True).start()

    def _update_meta(self, obj):
        y = str(obj.release_date.year) if hasattr(obj, 'release_date') and obj.release_date else ""
        c = getattr(obj, 'num_tracks', '?')
        self.header_meta.set_text(f"{y}  •  {c} Tracks".strip(' • '))

    def on_artist_selected(self, box, row):
        if not row: return
        self.current_selected_artist = row.artist_obj; self.right_stack.set_visible_child_name("albums")
        self.grid_title_label.set_text(f"Albums by {row.artist_obj.name}"); self.artist_fav_btn.set_visible(True)
        self.artist_fav_btn.add_css_class("active") if self.backend.is_artist_favorite(row.artist_obj.id) else self.artist_fav_btn.remove_css_class("active")
        while c := self.album_flow.get_first_child(): self.album_flow.remove(c)
        Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_albums(row.artist_obj))), daemon=True).start()

    def batch_load_albums(self, albs, batch=6):
        if not albs: return False
        curr, rem = albs[:batch], albs[batch:]
        for alb in curr:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
            img = Gtk.Image(pixel_size=130, css_classes=["album-cover-img"])
            utils.load_img(img, lambda a=alb: self.backend.get_artwork_url(a, 640), self.cache_dir, 130)
            v.append(img); v.append(Gtk.Label(label=alb.name, ellipsize=3, halign=Gtk.Align.CENTER, wrap=True, max_width_chars=16))
            c = Gtk.FlowBoxChild(); c.set_child(v); c.album_obj = alb; self.album_flow.append(c)
        if rem: GLib.timeout_add(50, self.batch_load_albums, rem, batch)
        return False

    def on_nav_selected(self, box, row):
        if not row: return
        self.artist_fav_btn.set_visible(False); self.right_stack.set_visible_child_name("albums")
        while c := self.album_flow.get_first_child(): self.album_flow.remove(c)
        if row.nav_id == "home":
            self.grid_title_label.set_text("My Collection")
            Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums()))).start()
        elif row.nav_id == "history":
            self.grid_title_label.set_text("History")
            Thread(target=lambda: GLib.idle_add(self.batch_load_albums, self.history_mgr.get_albums())).start()

    def on_track_selected(self, box, row):
        if not row: return
        idx = row.get_index(); track = self.current_track_list[idx]; self.current_index = idx
        self.lbl_title.set_text(track.name); cover_url = self.backend.get_artwork_url(track, 1280)
        utils.load_img(self.art_img, cover_url, self.cache_dir, 140)
        Thread(target=lambda: self.history_mgr.add(track, cover_url), daemon=True).start()
        def play():
            url = self.backend.get_stream_url(track)
            if url: GLib.idle_add(lambda: (self.player.load(url), self.player.play(), self.play_btn.set_icon_name("media-playback-pause-symbolic")))
        Thread(target=play, daemon=True).start()

    def populate_artists(self, artists):
        while c := self.artist_list.get_first_child(): self.artist_list.remove(c)
        for art in artists:
            row = Gtk.ListBoxRow(); row.artist_obj = art; box = Gtk.Box(spacing=12, margin_start=8, margin_top=4, margin_bottom=4)
            img = Gtk.Image(pixel_size=36, css_classes=["circular-avatar"])
            utils.load_img(img, lambda: self.backend.get_artwork_url(art, 160), self.cache_dir, 36)
            box.append(img); box.append(Gtk.Label(label=art.name, xalign=0)); row.set_child(box); self.artist_list.append(row)

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
                GLib.idle_add(lambda: (btn.add_css_class("active") if is_add else btn.remove_css_class("active"), Thread(target=lambda: GLib.idle_add(self.populate_artists, self.backend.get_favorites()), daemon=True).start()))
        Thread(target=do, daemon=True).start()

    def on_search(self, entry):
        q = entry.get_text()
        if q: Thread(target=lambda: GLib.idle_add(self.populate_artists, self.backend.search_artist(q)), daemon=True).start()

    def on_back_clicked(self, btn): self.right_stack.set_visible_child_name("albums"); btn.set_sensitive(False)
    def on_player_art_clicked(self, gest, n, x, y):
        if 0 <= self.current_index < len(self.current_track_list): self.show_album_details(self.current_track_list[self.current_index].album)

if __name__ == "__main__":
    TidalApp().run(None)
