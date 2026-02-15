import os
# [Fix] 屏蔽 MESA 驱动层非致命调试警告
os.environ["MESA_LOG_LEVEL"] = "error"

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

import webbrowser
import json
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
            "device": "Default Output",
            "bit_perfect": False,
            "exclusive_lock": False
        }
        
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    saved = json.load(f)
                    self.settings.update(saved)
            except: pass

        self.player = AudioPlayer(on_eos_callback=self.on_next_track, on_tag_callback=self.update_tech_label)
        self.history_mgr = HistoryManager()
        self.cache_dir = os.path.expanduser("~/.cache/hiresti/covers")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.current_track_list = []
        self.current_index = -1
        self.playing_track = None
        self.playing_track_id = None 
        
        self.window_created = False
        self.is_programmatic_update = False
        self.current_device_list = []
        self.current_device_name = self.settings.get("device", "Default Output")
        self.search_track_data = []
        self.nav_history = []
        self.ignore_device_change = False

    def do_shutdown(self):
        print("[Main] Shutting down application...")
        if hasattr(self, 'player'):
            self.player.cleanup()
        super().do_shutdown()

    def save_settings(self):
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except: pass

    def do_activate(self):
        if self.window_created: 
            self.win.present()
            return
        
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icons_path = os.path.join(os.path.dirname(__file__), "icons")
        if os.path.exists(icons_path):
            icon_theme.add_search_path(icons_path)

        provider = Gtk.CssProvider()
        provider.load_from_data(ui_config.CSS_DATA.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win = Adw.ApplicationWindow(application=self, title="hiresTI Desktop", default_width=ui_config.WINDOW_WIDTH, default_height=ui_config.WINDOW_HEIGHT)
        self.window_created = True
        
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.win.set_content(main_vbox)

        self._build_header(main_vbox)
        self._build_body(main_vbox)
        self._build_player_bar(main_vbox)

        # [启动恢复逻辑]
        is_bp = self.settings.get("bit_perfect", False)
        is_ex = self.settings.get("exclusive_lock", False)
        
        # 1. 恢复 Bit-Perfect
        if is_bp:
            print("[Init] Restoring Bit-Perfect Mode...")
            self.player.toggle_bit_perfect(True, exclusive_lock=is_ex)
            if hasattr(self, 'bp_switch'): self.bp_switch.set_active(True)
            if hasattr(self, 'eq_btn'): self.eq_btn.set_sensitive(False)
            if hasattr(self, 'bp_label'): self.bp_label.set_visible(True)
            self._lock_volume_controls(True)
        
        # 2. 恢复 Exclusive Lock
        if hasattr(self, 'ex_switch'):
             self.ex_switch.set_sensitive(is_bp)
             self.ex_switch.set_active(is_ex)
        
        # 3. 恢复 Driver
        saved_drv = self.settings.get("driver", "Auto (Default)")
        if is_ex:
            saved_drv = "ALSA"
            self.driver_dd.set_sensitive(False)
        
        print(f"[Init] Restoring Driver: {saved_drv}")
        drivers = self.player.get_drivers()
        if saved_drv in drivers:
            for i, d in enumerate(drivers):
                if d == saved_drv:
                    self.driver_dd.set_selected(i)
                    break
        self.on_driver_changed(self.driver_dd, None)

        # [修改] 检查登录状态并更新 UI
        if self.backend.try_load_session(): 
            self.on_login_success()
        else:
            self._toggle_login_view(False) # 未登录状态

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
        
        # 登录按钮
        self.login_btn = Gtk.Button(label="Login", css_classes=["flat"])
        self.login_btn.connect("clicked", self.on_login_clicked)
        
        # [新增] 创建弹出菜单并设置父控件
        self.user_popover = self._build_user_popover()
        self.user_popover.set_parent(self.login_btn)
        
        self.settings_btn = Gtk.Button(icon_name="emblem-system-symbolic", css_classes=["flat"])
        self.settings_btn.set_tooltip_text("Settings")
        self.settings_btn.connect("clicked", self.on_settings_clicked)
        
        box_right.append(self.login_btn); box_right.append(self.settings_btn); header.pack_end(box_right)

    def _build_user_popover(self):
        """创建包含 Logout 的弹出菜单"""
        pop = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        btn = Gtk.Button(label="Logout", css_classes=["flat", "destructive-action"])
        btn.connect("clicked", self.on_logout_clicked)
        vbox.append(btn)
        pop.set_child(vbox)
        return pop

    def _build_body(self, container):
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True); container.append(self.paned)
        self.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.nav_list = Gtk.ListBox(css_classes=["navigation-sidebar"], margin_top=10); self.nav_list.connect("row-activated", self.on_nav_selected)
        
        nav_items = [
            ("home", "user-bookmarks-symbolic", "My Collection"),
            ("artists", "avatar-default-symbolic", "Artists"),
            ("history", "document-open-recent-symbolic", "History")
        ]
        
        for nid, icon, txt in nav_items:
            r = Gtk.ListBoxRow(); r.nav_id = nid; b = Gtk.Box(spacing=12, margin_start=12, margin_top=8, margin_bottom=8)
            b.append(Gtk.Image.new_from_icon_name(icon)); b.append(Gtk.Label(label=txt)); r.set_child(b); self.nav_list.append(r)
            
        self.sidebar_box.append(self.nav_list)
        self.paned.set_start_child(self.sidebar_box)
        self.right_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT); self.paned.set_end_child(self.right_stack)
        
        self._build_grid_view()
        self._build_tracks_view()
        self._build_settings_page()
        self._build_search_view()
        
        self.paned.set_position(int(ui_config.WINDOW_WIDTH * ui_config.SIDEBAR_RATIO))

    def _build_grid_view(self):
        grid_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # 1. 标题区域
        t_box = Gtk.Box(spacing=12, margin_start=32, margin_end=32, margin_top=32, margin_bottom=12)
        self.grid_title_label = Gtk.Label(label="My Collection", xalign=0, css_classes=["section-title"])
        self.artist_fav_btn = Gtk.Button(css_classes=["heart-btn"], icon_name="emblem-favorite-symbolic", visible=False)
        self.artist_fav_btn.connect("clicked", self.on_artist_fav_clicked)
        t_box.append(self.grid_title_label); t_box.append(self.artist_fav_btn); grid_vbox.append(t_box)

        # 2. [新增] 未登录提示区域
        self.login_prompt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, valign=Gtk.Align.CENTER, vexpand=True)
        self.login_prompt_box.set_visible(False)
        
        prompt_icon = Gtk.Image(icon_name="avatar-default-symbolic", pixel_size=128, css_classes=["dim-label"])
        prompt_label = Gtk.Label(label="Please login to access your Tidal collection", css_classes=["heading"])
        prompt_btn = Gtk.Button(label="Login to Tidal", css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        prompt_btn.connect("clicked", self.on_login_clicked)
        
        self.login_prompt_box.append(prompt_icon)
        self.login_prompt_box.append(prompt_label)
        self.login_prompt_box.append(prompt_btn)
        grid_vbox.append(self.login_prompt_box)

        # 3. 专辑列表区域
        self.main_flow = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=30, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=28, margin_start=32, margin_end=32, margin_bottom=32)
        self.main_flow.connect("child-activated", self.on_grid_item_activated)
        
        self.alb_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.alb_scroll.set_child(self.main_flow)
        grid_vbox.append(self.alb_scroll)
        
        self.right_stack.add_named(grid_vbox, "grid_view")


    def _toggle_login_view(self, logged_in):
        """
        根据登录状态切换界面显示。
        [最终修复] 从 profile_metadata 中提取名字，解决 first_name 为空的问题。
        """
        self.login_prompt_box.set_visible(not logged_in)
        self.alb_scroll.set_visible(logged_in)
        
        if not logged_in:
            self.login_btn.set_label("Login")
            self.grid_title_label.set_text("Welcome")
        else:
            display_name = "User"
            user = self.backend.user
            
            if user:
                # 1. 优先尝试从 profile_metadata 里挖名字
                # 这是 Tidal 新版 API 存放用户自定义名字的地方
                meta = getattr(user, 'profile_metadata', None)
                if meta:
                    # 如果 meta 是字典
                    if isinstance(meta, dict):
                        display_name = meta.get('name') or meta.get('firstName') or display_name
                    # 如果 meta 是对象
                    else:
                        display_name = getattr(meta, 'name', None) or getattr(meta, 'first_name', None) or display_name

                # 2. 如果元数据里也没找到，或者还是默认值，再尝试标准字段
                if display_name == "User" or display_name is None:
                    candidates = [
                        getattr(user, 'first_name', None),
                        getattr(user, 'name', None),
                        getattr(user, 'firstname', None),
                    ]
                    for c in candidates:
                        if c and isinstance(c, str) and c.strip():
                            display_name = c
                            break

                # 3. 最后的兜底：用邮箱前缀
                if (not display_name or display_name == "User") and hasattr(user, 'username') and user.username:
                    try:
                        # yelanxin@gmail.com -> Yelanxin
                        display_name = user.username.split('@')[0].capitalize()
                    except:
                        display_name = user.username

            self.login_btn.set_label(f"Hi, {display_name}")
            self.grid_title_label.set_text("My Collection")

    def _build_tracks_view(self):
        trk_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        trk_scroll = Gtk.ScrolledWindow(vexpand=True)
        trk_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.album_header_box = Gtk.Box(spacing=24, css_classes=["album-header-box"])
        self.header_art = Gtk.Image(width_request=160, height_request=160, css_classes=["header-art"])

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.header_title = Gtk.Label(xalign=0, wrap=True, css_classes=["album-title-large"])

        # 歌手名标签
        self.header_artist = Gtk.Label(xalign=0, css_classes=["album-artist-medium"])
        tap = Gtk.GestureClick(); tap.connect("pressed", self.on_header_artist_clicked); self.header_artist.add_controller(tap)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda c,x,y: utils.set_pointer_cursor(self.header_artist, True))
        motion.connect("leave", lambda c: utils.set_pointer_cursor(self.header_artist, False))
        self.header_artist.add_controller(motion)

        self.header_meta = Gtk.Label(xalign=0, css_classes=["album-meta"])

        info.append(self.header_title); info.append(self.header_artist); info.append(self.header_meta)

        self.fav_btn = Gtk.Button(css_classes=["heart-btn"], icon_name="non-starred-symbolic", valign=Gtk.Align.CENTER)
        self.fav_btn.connect("clicked", self.on_fav_clicked)

        self.album_header_box.append(self.header_art); self.album_header_box.append(info); self.album_header_box.append(self.fav_btn)
        trk_content.append(self.album_header_box)

        self.track_list = Gtk.ListBox(css_classes=["boxed-list"], margin_start=32, margin_end=32, margin_bottom=32)
        self.track_list.connect("row-activated", self.on_track_selected)
        trk_content.append(self.track_list)

        trk_scroll.set_child(trk_content); trk_vbox.append(trk_scroll)
        self.right_stack.add_named(trk_vbox, "tracks")

    def _build_settings_page(self):
        settings_scroll = Gtk.ScrolledWindow(vexpand=True)
        settings_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-container"], spacing=20)
        settings_scroll.set_child(settings_vbox)
        settings_vbox.append(Gtk.Label(label="Settings", xalign=0, css_classes=["album-title-large"], margin_bottom=10))

        group_q = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])
        row_q = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        row_q.append(Gtk.Label(label="Audio Quality", hexpand=True, xalign=0))
        
        # [修改] 官方三档选项
        self.quality_dd = Gtk.DropDown(model=Gtk.StringList.new([
            "Max (Up to 24-bit, 192 kHz)", 
            "High (16-bit, 44.1 kHz)", 
            "Low (320 kbps)"
        ]))
        
        self.quality_dd.connect("notify::selected-item", self.on_quality_changed)
        row_q.append(self.quality_dd); group_q.append(row_q); settings_vbox.append(group_q)

        settings_vbox.append(Gtk.Label(label="Audio Output", xalign=0, css_classes=["section-title"], margin_top=10))
        group_out = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])
        
        # 1. Bit-Perfect 开关
        row_bp = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        bp_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        bp_info.append(Gtk.Label(label="Bit-Perfect Mode", xalign=0, css_classes=["settings-label"]))
        bp_info.append(Gtk.Label(label="Bypass software mixer & EQ", xalign=0, css_classes=["dim-label"]))
        row_bp.append(bp_info); row_bp.append(Gtk.Box(hexpand=True))
        self.bp_switch = Gtk.Switch(valign=Gtk.Align.CENTER); self.bp_switch.connect("state-set", self.on_bit_perfect_toggled)
        row_bp.append(self.bp_switch); group_out.append(row_bp)

        # 2. Exclusive Lock 开关
        row_ex = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        ex_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        ex_info.append(Gtk.Label(label="Force Hardware Exclusive", xalign=0, css_classes=["settings-label"]))
        ex_info.append(Gtk.Label(label="Bypass and release system audio control for this device", xalign=0, css_classes=["dim-label"]))
        row_ex.append(ex_info); row_ex.append(Gtk.Box(hexpand=True))
        self.ex_switch = Gtk.Switch(valign=Gtk.Align.CENTER, sensitive=False) 
        self.ex_switch.connect("state-set", self.on_exclusive_toggled)
        row_ex.append(self.ex_switch); group_out.append(row_ex)

        # 3. Drivers
        row_drv = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        row_drv.append(Gtk.Label(label="Audio Driver", hexpand=True, xalign=0))
        drivers = self.player.get_drivers()
        self.driver_dd = Gtk.DropDown(model=Gtk.StringList.new(drivers))
        self.driver_dd.connect("notify::selected-item", self.on_driver_changed)
        row_drv.append(self.driver_dd); group_out.append(row_drv)

        row_dev = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        row_dev.append(Gtk.Label(label="Output Device", hexpand=True, xalign=0))
        self.device_dd = Gtk.DropDown(model=Gtk.StringList.new(["Default"])); self.device_dd.set_sensitive(False)
        self.device_dd.connect("notify::selected-item", self.on_device_changed)
        row_dev.append(self.device_dd); group_out.append(row_dev)
        settings_vbox.append(group_out); self.right_stack.add_named(settings_scroll, "settings")

    def _build_eq_popover(self):
        pop = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        hb = Gtk.Box(spacing=12); hb.append(Gtk.Label(label="10-Band Equalizer", css_classes=["title-4"]))
        reset = Gtk.Button(label="Reset", css_classes=["flat"]); reset.connect("clicked", lambda b: (self.player.reset_eq(), [s.set_value(0) for s in self.sliders])); hb.append(reset); vbox.append(hb)
        hbox = Gtk.Box(spacing=8); freqs = ["30", "60", "120", "240", "480", "1k", "2k", "4k", "8k", "16k"]
        self.sliders = []
        for i, f in enumerate(freqs):
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -24, 12, 1); scale.set_inverted(True); scale.set_size_request(-1, 150); scale.set_value(0); scale.add_mark(0, Gtk.PositionType.RIGHT, None)
            scale.connect("value-changed", lambda s, idx=i: self.player.set_eq_band(idx, s.get_value())); self.sliders.append(scale)
            vb.append(scale); vb.append(Gtk.Label(label=f, css_classes=["caption"])); hbox.append(vb)
        vbox.append(hbox); pop.set_child(vbox); return pop

    def _build_player_bar(self, container):
        self.bottom_bar = Gtk.Box(spacing=24, css_classes=["card-bar"])
        container.append(self.bottom_bar)
        
        # === 1. 左侧：封面与信息 ===
        self.info_area = Gtk.Box(spacing=14, valign=Gtk.Align.CENTER)
        
        # 封面图
        self.art_img = Gtk.Image(width_request=72, height_request=72, css_classes=["playback-art"])
        gest = Gtk.GestureClick(); gest.connect("pressed", self.on_player_art_clicked); self.art_img.add_controller(gest)
        m = Gtk.EventControllerMotion()
        m.connect("enter", lambda c,x,y: utils.set_pointer_cursor(self.art_img, True))
        m.connect("leave", lambda c: utils.set_pointer_cursor(self.art_img, False))
        self.art_img.add_controller(m)
        
        # 文字区域：三行布局
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=0)
        self.lbl_title = Gtk.Label(xalign=0, css_classes=["player-title"], ellipsize=3)
        self.lbl_artist = Gtk.Label(xalign=0, css_classes=["player-artist"], ellipsize=3)
        self.lbl_album = Gtk.Label(xalign=0, css_classes=["player-album"], ellipsize=3)
        
        t.append(self.lbl_title); t.append(self.lbl_artist); t.append(self.lbl_album)
        self.info_area.append(self.art_img); self.info_area.append(t); self.bottom_bar.append(self.info_area)
        
        # === 2. 中间：控制按钮与进度条 ===
        c_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        ctrls = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        ctrls.append(Gtk.Button(icon_name="media-skip-backward-symbolic", css_classes=["flat"]))
        self.play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["pill", "suggested-action"])
        self.play_btn.connect("clicked", self.on_play_pause)
        ctrls.append(self.play_btn)
        ctrls.append(Gtk.Button(icon_name="media-skip-forward-symbolic", css_classes=["flat"]))
        c_box.append(ctrls)
        
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_hexpand(True); self.scale.connect("value-changed", self.on_seek)
        c_box.append(self.scale); self.scale.set_size_request(400, -1); self.scale.set_halign(Gtk.Align.CENTER)
        
        # 技术参数标签区域
        tech_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=4)
        self.bp_label = Gtk.Label(label="BIT PERFECT", css_classes=["bp-text-glow"])
        self.bp_label.set_tooltip_text("Bit-Perfect Mode Active"); self.bp_label.set_visible(False); tech_box.append(self.bp_label)
        self.lbl_tech = Gtk.Label(label="-", css_classes=["tech-label"], ellipsize=3); tech_box.append(self.lbl_tech); c_box.append(tech_box)
        self.bottom_bar.append(c_box)
        
        # === 3. 右侧：音量与EQ ===
        r_box = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        self.eq_btn = Gtk.Button(icon_name="eq-icon-symbolic", css_classes=["flat"])
        self.eq_btn.set_tooltip_text("Equalizer"); self.eq_pop = self._build_eq_popover(); self.eq_pop.set_parent(self.eq_btn); self.eq_btn.connect("clicked", lambda b: self.eq_pop.popup())
        r_box.append(self.eq_btn)
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.vol.set_value(80); self.vol.set_size_request(120, -1); self.vol.connect("value-changed", lambda s: self.player.set_volume(s.get_value()/100.0)); r_box.append(self.vol); self.bottom_bar.append(r_box)

    def _lock_volume_controls(self, locked):
        if not hasattr(self, 'vol'): return
        if locked:
            self.vol.set_value(100); self.player.set_volume(1.0); self.vol.set_sensitive(False)
        else:
            self.vol.set_sensitive(True)

    # 登录/登出逻辑
    def on_login_clicked(self, btn):
        if self.backend.user:
            self.user_popover.popup()
        else:
            u, f = self.backend.start_oauth(); webbrowser.open(u)
            def login_thread():
                if self.backend.finish_login(f):
                    GLib.idle_add(self.on_login_success)
            Thread(target=login_thread, daemon=True).start()

    def on_logout_clicked(self, btn):
        self.user_popover.popdown()
        self.backend.logout()
        self._toggle_login_view(False)
        while c := self.main_flow.get_first_child(): self.main_flow.remove(c)
        print("[UI] User logged out.")

    def on_login_success(self):
        print("[UI] Login successful!")
        self._toggle_login_view(True)
        Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums())), daemon=True).start()

    # 设置相关逻辑
    def on_bit_perfect_toggled(self, switch, state):
        self.settings["bit_perfect"] = state; self.save_settings()
        self._lock_volume_controls(state)
        self.ex_switch.set_sensitive(state)
        if not state: self.ex_switch.set_active(False)
        is_ex = self.ex_switch.get_active()
        self.player.toggle_bit_perfect(state, exclusive_lock=is_ex)
        self.eq_btn.set_sensitive(not state)
        if state: self.eq_pop.popdown()
        if hasattr(self, 'bp_label'): self.bp_label.set_visible(state)
        if is_ex:
            self._force_driver_selection("ALSA"); self.driver_dd.set_sensitive(False); self.on_driver_changed(self.driver_dd, None)
        else:
            self.driver_dd.set_sensitive(True)

    def on_exclusive_toggled(self, switch, state):
        self.settings["exclusive_lock"] = state; self.save_settings()
        self.player.toggle_bit_perfect(True, exclusive_lock=state)
        if state:
            self._force_driver_selection("ALSA"); self.driver_dd.set_sensitive(False); self.on_driver_changed(self.driver_dd, None)
        else:
            self.driver_dd.set_sensitive(True); self.on_device_changed(self.device_dd, None)

    def _force_driver_selection(self, keyword):
        model = self.driver_dd.get_model()
        for i in range(model.get_n_items()):
            if keyword in model.get_item(i).get_string(): self.driver_dd.set_selected(i); break

    def update_tech_label(self, info):
        fmt = self.player.get_format_string(); dev_name = getattr(self, 'current_device_name', 'Default')
        if len(dev_name) > 30: dev_name = dev_name[:28] + ".."
        self.lbl_tech.set_text(f"{info.get('codec','-')} | {fmt} | {info.get('bitrate',0)//1000}kbps | {dev_name}")

    def on_settings_clicked(self, btn):
        self.right_stack.set_visible_child_name("settings"); self.grid_title_label.set_text("Settings"); self.back_btn.set_sensitive(True); self.nav_list.select_row(None)

    def on_quality_changed(self, dd, p):
        selected = dd.get_selected_item()
        if not selected: return
        mode_str = selected.get_string()
        self.backend.set_quality_mode(mode_str)
        
        # 强制重载逻辑
        if self.player.is_playing() and self.current_index >= 0:
            pos, _ = self.player.get_position()
            track = self.current_track_list[self.current_index]
            def refresh():
                new_url = self.backend.get_stream_url(track)
                GLib.idle_add(lambda: self._restart_player_with_url(new_url, pos))
            Thread(target=refresh, daemon=True).start()

    def _restart_player_with_url(self, url, pos):
        if not url: return
        self.player.stop(); self.player.load(url); self.player.play()
        GLib.timeout_add(700, lambda: self.player.seek(pos))

    def on_driver_changed(self, dd, p):
        selected = dd.get_selected_item()
        if not selected: return
        driver_name = selected.get_string()
        if self.ex_switch.get_active() and driver_name != "ALSA": return 
        self.settings["driver"] = driver_name; self.save_settings()
        self.current_device_name = "Default"; self.update_tech_label(self.player.stream_info)
        
        def refresh_devices():
            self.ignore_device_change = True
            devices = self.player.get_devices_for_driver(driver_name)
            self.current_device_list = devices 
            self.device_dd.set_model(Gtk.StringList.new([d["name"] for d in devices]))
            saved_dev = self.settings.get("device")
            sel_idx = 0; found_saved = False
            if saved_dev:
                for i, d in enumerate(devices):
                    if d["name"] == saved_dev: sel_idx = i; found_saved = True; break
            self.device_dd.set_sensitive(len(devices) > 1)
            if sel_idx < self.device_dd.get_model().get_n_items(): self.device_dd.set_selected(sel_idx)
            self.ignore_device_change = False
            target_device_id = None
            if sel_idx < len(devices):
                target_device_id = devices[sel_idx]['device_id']; self.current_device_name = devices[sel_idx]['name']
                if not found_saved: self.settings["device"] = self.current_device_name
            GLib.idle_add(lambda: self.update_tech_label(self.player.stream_info))
            self.player.set_output(driver_name, target_device_id)
        Thread(target=lambda: GLib.idle_add(refresh_devices), daemon=True).start()

    def on_device_changed(self, dd, p):
        if self.ignore_device_change: return
        idx = dd.get_selected()
        if hasattr(self, 'current_device_list') and idx < len(self.current_device_list):
            device_info = self.current_device_list[idx]
            self.current_device_name = device_info['name']
            self.update_tech_label(self.player.stream_info)
            self.settings["device"] = device_info['name']; self.save_settings()
            driver_label = self.driver_dd.get_selected_item().get_string()
            self.player.set_output(driver_label, device_info['device_id'])

    def on_grid_item_activated(self, flow, child):
        if not child: return
        if hasattr(child, 'album_obj'): self.show_album_details(child.album_obj)
        elif hasattr(child, 'artist_obj'): self.on_artist_clicked(child.artist_obj)

    def show_album_details(self, alb):
        current_view = self.right_stack.get_visible_child_name()
        if current_view and current_view != "tracks": self.nav_history.append(current_view)
        self.current_album = alb
        self.right_stack.set_visible_child_name("tracks"); self.back_btn.set_sensitive(True)
        self.header_title.set_text(alb.name)
        artist_name = "Unknown Artist"
        if hasattr(alb, 'artist') and alb.artist: artist_name = alb.artist.name if hasattr(alb.artist, 'name') else str(alb.artist)
        self.header_artist.set_text(artist_name)
        utils.load_img(self.header_art, lambda: self.backend.get_artwork_url(alb, 640), self.cache_dir, 160)
        is_fav = self.backend.is_favorite(alb.id); self._update_fav_icon(self.fav_btn, is_fav)
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
        c = getattr(obj, 'num_tracks', '?'); self.header_meta.set_text(f"{y}  •  {c} Tracks".strip(' • '))

    def populate_tracks(self, tracks):
        self.current_track_list = tracks
        if self.playing_track_id:
            found_idx = -1
            for i, t in enumerate(tracks):
                if t.id == self.playing_track_id: found_idx = i; break
            if found_idx != -1: self.current_index = found_idx

        for i, t in enumerate(tracks):
            b = Gtk.Box(spacing=16, margin_top=10, margin_bottom=10)
            stack = Gtk.Stack(); stack.set_size_request(30, -1)
            lbl = Gtk.Label(label=str(i+1), css_classes=["dim-label"]); stack.add_named(lbl, "num")
            icon = Gtk.Image(icon_name="media-playback-start-symbolic"); stack.add_named(icon, "icon")
            if self.playing_track_id and t.id == self.playing_track_id: stack.set_visible_child_name("icon")
            else: stack.set_visible_child_name("num")
            b.append(stack); b.append(Gtk.Label(label=t.name, xalign=0, hexpand=True, ellipsize=3))
            self.track_list.append(b)

    def on_header_artist_clicked(self, gest, n, x, y):
        if hasattr(self, 'current_album') and self.current_album:
            artist_obj = None
            if hasattr(self.current_album, 'artist') and self.current_album.artist: artist_obj = self.current_album.artist
            if artist_obj and not isinstance(artist_obj, str) and hasattr(artist_obj, 'id'): self.on_artist_clicked(artist_obj)

    def on_artist_clicked(self, artist):
        current_view = self.right_stack.get_visible_child_name()
        if current_view: self.nav_history.append(current_view)
        self.current_selected_artist = artist
        self.right_stack.set_visible_child_name("grid_view")
        self.grid_title_label.set_text(f"Albums by {artist.name}")
        self.back_btn.set_sensitive(True)
        self.artist_fav_btn.set_visible(True)
        is_fav = self.backend.is_artist_favorite(artist.id); self._update_fav_icon(self.artist_fav_btn, is_fav)
        while c := self.main_flow.get_first_child(): self.main_flow.remove(c)
        Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_albums(artist))), daemon=True).start()

    def batch_load_albums(self, albs, batch=6):
        if not albs: return False
        curr, rem = albs[:batch], albs[batch:]
        for alb in curr:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
            img = Gtk.Image(pixel_size=130, css_classes=["album-cover-img"])
            utils.load_img(img, lambda a=alb: self.backend.get_artwork_url(a, 640), self.cache_dir, 130)
            v.append(img); v.append(Gtk.Label(label=alb.name, ellipsize=3, halign=Gtk.Align.CENTER, wrap=True, max_width_chars=16))
            c = Gtk.FlowBoxChild(); c.set_child(v); c.album_obj = alb; self.main_flow.append(c)
        if rem: GLib.timeout_add(50, self.batch_load_albums, rem, batch)
        return False

    def batch_load_artists(self, artists, batch=10):
        if not artists: return False
        curr, rem = artists[:batch], artists[batch:]
        for art in curr:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card"])
            img = Gtk.Image(pixel_size=120, css_classes=["circular-avatar"])
            utils.load_img(img, lambda a=art: self.backend.get_artwork_url(a, 320), self.cache_dir, 120)
            v.append(img); v.append(Gtk.Label(label=art.name, ellipsize=2, halign=Gtk.Align.CENTER, wrap=True, max_width_chars=14, css_classes=["heading"]))
            c = Gtk.FlowBoxChild(); c.set_child(v); c.artist_obj = art; self.main_flow.append(c)
        if rem: GLib.timeout_add(50, self.batch_load_artists, rem, batch)
        return False

    def on_nav_selected(self, box, row):
        if not row: return
        self.nav_history.clear()
        self.artist_fav_btn.set_visible(False)
        self.right_stack.set_visible_child_name("grid_view")
        self.back_btn.set_sensitive(False)
        while c := self.main_flow.get_first_child(): self.main_flow.remove(c)
        if row.nav_id == "home":
            self.grid_title_label.set_text("My Collection")
            if self.backend.user: Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums()))).start()
        elif row.nav_id == "history":
            self.grid_title_label.set_text("History")
            Thread(target=lambda: GLib.idle_add(self.batch_load_albums, self.history_mgr.get_albums())).start()
        elif row.nav_id == "artists":
            self.grid_title_label.set_text("Favorite Artists")
            if self.backend.user: Thread(target=lambda: GLib.idle_add(self.batch_load_artists, self.backend.get_favorites())).start()

    def on_track_selected(self, box, row):
        if not row: return
        idx = row.get_index()
        track = self.current_track_list[idx]
        self.current_index = idx
        self.playing_track = track
        self.playing_track_id = track.id
        self.lbl_title.set_text(track.name)
        art_name = getattr(track.artist, 'name', 'Unknown Artist')
        self.lbl_artist.set_text(art_name)
        alb_name = track.album.name if hasattr(track, 'album') and track.album else "Unknown Album"
        self.lbl_album.set_text(alb_name)
        cover_url = self.backend.get_artwork_url(track, 1280)
        utils.load_img(self.art_img, cover_url, self.cache_dir, 72)
        Thread(target=lambda: self.history_mgr.add(track, cover_url), daemon=True).start()
        def play():
            url = self.backend.get_stream_url(track)
            if url: GLib.idle_add(lambda: (self.player.load(url), self.player.play(), self.play_btn.set_icon_name("media-playback-pause-symbolic")))
        Thread(target=play, daemon=True).start()

    def on_play_pause(self, btn):
        if self.player.is_playing(): self.player.pause(); btn.set_icon_name("media-playback-start-symbolic")
        else: self.player.play(); btn.set_icon_name("media-playback-pause-symbolic")

    def on_next_track(self):
        if self.current_index < len(self.current_track_list)-1: self.current_index += 1; self.on_track_selected(None, self.track_list.get_row_at_index(self.current_index))

    def on_seek(self, s): 
        if not self.is_programmatic_update: self.player.seek(s.get_value())

    def update_ui_loop(self):
        p, d = self.player.get_position()
        if d > 0: self.is_programmatic_update = True; self.scale.set_range(0, d); self.scale.set_value(p); self.is_programmatic_update = False
        return True

    def update_layout_proportions(self, w, p):
        s_px = max(int(self.win.get_width() * ui_config.SIDEBAR_RATIO), 240)
        self.paned.set_position(s_px); self.info_area.set_size_request(s_px, -1)

    def _update_fav_icon(self, btn, is_active):
        if is_active:
            btn.set_icon_name("emblem-favorite-symbolic"); btn.add_css_class("active")
        else:
            btn.set_icon_name("non-starred-symbolic"); btn.remove_css_class("active")

    def on_fav_clicked(self, btn):
        if not hasattr(self, 'current_album'): return
        is_currently_active = "active" in btn.get_css_classes()
        is_add = not is_currently_active
        def do():
            if self.backend.toggle_album_favorite(self.current_album.id, is_add): GLib.idle_add(lambda: self._update_fav_icon(btn, is_add))
        Thread(target=do, daemon=True).start()

    def on_artist_fav_clicked(self, btn):
        if not hasattr(self, 'current_selected_artist'): return
        art = self.current_selected_artist
        is_currently_active = "active" in btn.get_css_classes()
        is_add = not is_currently_active
        def do():
            if self.backend.toggle_artist_favorite(art.id, is_add): GLib.idle_add(lambda: self._update_fav_icon(btn, is_add))
        Thread(target=do, daemon=True).start()

    def _build_search_view(self):
        self.search_scroll = Gtk.ScrolledWindow(vexpand=True)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=32, margin_bottom=32, margin_start=32, margin_end=32)
        self.search_scroll.set_child(vbox)
        self.res_art_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.res_art_box.append(Gtk.Label(label="Artists", xalign=0, css_classes=["section-title"]))
        self.res_art_flow = Gtk.FlowBox(max_children_per_line=10, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=24)
        self.res_art_flow.connect("child-activated", self.on_grid_item_activated) 
        self.res_art_box.append(self.res_art_flow); vbox.append(self.res_art_box)
        self.res_alb_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.res_alb_box.append(Gtk.Label(label="Albums", xalign=0, css_classes=["section-title"]))
        self.res_alb_flow = Gtk.FlowBox(max_children_per_line=10, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=24)
        self.res_alb_flow.connect("child-activated", self.on_grid_item_activated) 
        self.res_alb_box.append(self.res_alb_flow); vbox.append(self.res_alb_box)
        self.res_trk_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.res_trk_box.append(Gtk.Label(label="Tracks", xalign=0, css_classes=["section-title"]))
        self.res_trk_list = Gtk.ListBox(css_classes=["boxed-list"])
        self.res_trk_list.connect("row-activated", self.on_search_track_selected)
        self.res_trk_box.append(self.res_trk_list); vbox.append(self.res_trk_box)
        self.right_stack.add_named(self.search_scroll, "search_view")

    def on_search(self, entry):
        q = entry.get_text()
        if not q: return
        self.nav_history.clear()
        self.right_stack.set_visible_child_name("search_view"); self.nav_list.select_row(None); self.back_btn.set_sensitive(True)
        self.grid_title_label.set_text(f"Search: {q}")
        def clear_container(c):
            while child := c.get_first_child(): c.remove(child)
        clear_container(self.res_art_flow); clear_container(self.res_alb_flow); clear_container(self.res_trk_list)
        def do_search():
            results = self.backend.search_items(q); GLib.idle_add(self.render_search_results, results)
        Thread(target=do_search, daemon=True).start()

    def render_search_results(self, res):
        artists = res.get('artists', []); albums = res.get('albums', []); tracks = res.get('tracks', [])
        self.res_art_box.set_visible(bool(artists))
        for art in artists:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card"])
            img = Gtk.Image(pixel_size=100, css_classes=["circular-avatar"])
            utils.load_img(img, lambda a=art: self.backend.get_artwork_url(a, 320), self.cache_dir, 100)
            v.append(img); v.append(Gtk.Label(label=art.name, ellipsize=2, wrap=True, max_width_chars=12, css_classes=["heading"]))
            c = Gtk.FlowBoxChild(); c.set_child(v); c.artist_obj = art; self.res_art_flow.append(c)
        self.res_alb_box.set_visible(bool(albums))
        for alb in albums:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
            img = Gtk.Image(pixel_size=110, css_classes=["album-cover-img"])
            utils.load_img(img, lambda a=alb: self.backend.get_artwork_url(a, 320), self.cache_dir, 110)
            v.append(img); v.append(Gtk.Label(label=alb.name, ellipsize=2, wrap=True, max_width_chars=14))
            c = Gtk.FlowBoxChild(); c.set_child(v); c.album_obj = alb; self.res_alb_flow.append(c)
        self.res_trk_box.set_visible(bool(tracks)); self.search_track_data = tracks
        for i, t in enumerate(tracks):
            row = Gtk.Box(spacing=16, margin_top=8, margin_bottom=8, margin_start=12)
            img = Gtk.Image(pixel_size=48, css_classes=["album-cover-img"])
            utils.load_img(img, lambda tr=t: self.backend.get_artwork_url(tr, 80), self.cache_dir, 48)
            row.append(img)
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            info.append(Gtk.Label(label=t.name, xalign=0, ellipsize=3, css_classes=["heading"]))
            info.append(Gtk.Label(label=getattr(t.artist, 'name', 'Unknown'), xalign=0, css_classes=["dim-label"]))
            row.append(info); self.res_trk_list.append(row)

    def on_search_track_selected(self, box, row):
        if not row: return
        idx = row.get_index()
        if idx < len(self.search_track_data):
            self.current_track_list = self.search_track_data
            self.current_index = idx
            track = self.current_track_list[idx]
            self.playing_track = track
            self.playing_track_id = track.id
            self.lbl_title.set_text(track.name)
            art_name = getattr(track.artist, 'name', 'Unknown Artist')
            self.lbl_artist.set_text(art_name)
            alb_name = track.album.name if hasattr(track, 'album') and track.album else "Unknown Album"
            self.lbl_album.set_text(alb_name)
            cover_url = self.backend.get_artwork_url(track, 1280)
            if cover_url: utils.load_img(self.art_img, cover_url, self.cache_dir, 72)
            else: self.art_img.set_from_icon_name("audio-x-generic-symbolic")
            def play():
                url = self.backend.get_stream_url(track)
                if url: GLib.idle_add(lambda: (self.player.load(url), self.player.play(), self.play_btn.set_icon_name("media-playback-pause-symbolic")))
            Thread(target=play, daemon=True).start()

    def on_back_clicked(self, btn):
        if self.nav_history:
            target_view = self.nav_history.pop()
            self.right_stack.set_visible_child_name(target_view)
            if target_view == "search_view": return
            if not self.nav_history and target_view == "grid_view":
                btn.set_sensitive(False)
                self.artist_fav_btn.set_visible(False)
                if not self.nav_list.get_selected_row():
                    child = self.nav_list.get_first_child()
                    while child:
                        if hasattr(child, 'nav_id') and child.nav_id == "home": self.nav_list.select_row(child); self.on_nav_selected(None, child); break
                        child = child.get_next_sibling()
            return
        self.right_stack.set_visible_child_name("grid_view")
        btn.set_sensitive(False)
        self.artist_fav_btn.set_visible(False)
        row = self.nav_list.get_selected_row()
        if row: self.on_nav_selected(None, row)
        else:
             child = self.nav_list.get_first_child()
             while child:
                 if hasattr(child, 'nav_id') and child.nav_id == "home": self.nav_list.select_row(child); self.on_nav_selected(None, child); break
                 child = child.get_next_sibling()

    def on_player_art_clicked(self, gest, n, x, y):
        if hasattr(self, 'playing_track') and self.playing_track:
            track = self.playing_track
            if hasattr(track, 'album') and track.album: self.show_album_details(track.album)

if __name__ == "__main__":
    TidalApp().run(None)
