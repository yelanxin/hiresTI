import os
# [Fix] 屏蔽 MESA 驱动层非致命调试警告
os.environ["MESA_LOG_LEVEL"] = "error"

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango

import webbrowser
import json
from threading import Thread
from tidal_backend import TidalBackend
from audio_player import AudioPlayer
from models import HistoryManager
from signal_path import AudioSignalPathWindow
import utils
import ui_config

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class TidalApp(Adw.Application):
    # [新增] 定义延迟档位配置
    LATENCY_OPTIONS = ["Safe (400ms)", "Standard (100ms)", "Low Latency (40ms)", "Aggressive (20ms)"]
    LATENCY_MAP = {
        "Safe (400ms)":      (400, 40),  # Buffer, Latency
        "Standard (100ms)":  (100, 10),
        "Low Latency (40ms)":(40, 4),
        "Aggressive (20ms)": (20, 2)
    }
    def __init__(self):
        super().__init__(application_id="com.hiresti.player")
        GLib.set_application_name("HiresTI")
        GLib.set_prgname("HiresTI")
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

        # [修复点] 这里的 self.on_next_track 现在能在下面找到定义了
        self.player = AudioPlayer(on_eos_callback=self.on_next_track, on_tag_callback=self.update_tech_label)

        saved_profile = self.settings.get("latency_profile", "Standard (100ms)")
        if saved_profile not in self.LATENCY_MAP: saved_profile = "Standard (100ms)"
        buf_ms, lat_ms = self.LATENCY_MAP[saved_profile]
        self.player.set_alsa_latency(buf_ms, lat_ms)

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
        
        # Mini Mode 状态与尺寸记忆
        self.is_mini_mode = False
        self.saved_width = ui_config.WINDOW_WIDTH
        self.saved_height = ui_config.WINDOW_HEIGHT

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
        
        self.window_handle = Gtk.WindowHandle()
        self.win.set_content(self.window_handle)
        
        self.main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window_handle.set_child(self.main_vbox)

        self._build_header(self.main_vbox)
        self._build_body(self.main_vbox)
        self._build_player_bar(self.main_vbox)

        # === 恢复设置逻辑 ===
        is_bp = self.settings.get("bit_perfect", False)
        is_ex = self.settings.get("exclusive_lock", False)
        
        # 1. 应用 Bit-Perfect 和 独占状态
        self.player.toggle_bit_perfect(is_bp, exclusive_lock=is_ex)
        if is_bp:
            if hasattr(self, 'bp_label'): self.bp_label.set_visible(True)
            self._lock_volume_controls(True)
        
        # 2. 应用 Latency
        saved_profile = self.settings.get("latency_profile", "Standard (100ms)")
        if saved_profile in self.LATENCY_MAP:
            buf_ms, lat_ms = self.LATENCY_MAP[saved_profile]
            self.player.set_alsa_latency(buf_ms, lat_ms)
        
        # 3. 恢复驱动选择
        drivers = self.player.get_drivers()
        saved_drv = self.settings.get("driver", "Auto (Default)")
        
        # 如果保存的是 ALSA 或其他驱动，先尝试选中
        if saved_drv in drivers:
            try:
                idx = drivers.index(saved_drv)
                self.driver_dd.set_selected(idx)
            except: pass
            
        # 触发一次驱动加载
        self.on_driver_changed(self.driver_dd, None)

        # [修复重点] 4. 如果启动时独占模式是开启的，必须强制禁用驱动选择框
        if is_ex:
            self.driver_dd.set_sensitive(False)
            # 双重保险：确保 UI 选中的是 ALSA
            self._force_driver_selection("ALSA")

        if self.backend.try_load_session(): 
            self.on_login_success()
        else:
            self._toggle_login_view(False) 

        self.win.present()
        self.win.connect("notify::default-width", self.update_layout_proportions)
        GLib.timeout_add(1000, self.update_ui_loop)

    def _build_header(self, container):
        self.header = Adw.HeaderBar(); container.append(self.header)
        
        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", sensitive=False)
        self.back_btn.connect("clicked", self.on_back_clicked) 
        self.header.pack_start(self.back_btn)
        
        self.search_entry = Gtk.Entry(placeholder_text="Search...", width_request=300, valign=Gtk.Align.CENTER)
        self.search_entry.connect("activate", self.on_search); self.header.set_title_widget(self.search_entry)
        
        box_right = Gtk.Box(spacing=6)
        
        self.login_btn = Gtk.Button(label="Login", css_classes=["flat"])
        self.login_btn.connect("clicked", self.on_login_clicked)
        
        self.user_popover = self._build_user_popover()
        self.user_popover.set_parent(self.login_btn)
        
        self.info_btn = Gtk.Button(icon_name="media-view-subtitles-symbolic", css_classes=["flat"])
        self.info_btn.set_tooltip_text("Signal Path / Tech Info")
        self.info_btn.connect("clicked", self.on_tech_info_clicked)
        
        # Mini Player 按钮
        self.mini_btn = Gtk.Button(icon_name="view-restore-symbolic", css_classes=["flat"])
        self.mini_btn.set_tooltip_text("Mini Player Mode")
        self.mini_btn.connect("clicked", self.toggle_mini_mode)

        self.settings_btn = Gtk.Button(icon_name="emblem-system-symbolic", css_classes=["flat"])
        self.settings_btn.set_tooltip_text("Settings")
        self.settings_btn.connect("clicked", self.on_settings_clicked)
        
        box_right.append(self.login_btn)
        box_right.append(self.info_btn)
        box_right.append(self.mini_btn)
        box_right.append(self.settings_btn)
        self.header.pack_end(box_right)

    def _build_volume_popover(self):
        pop = Gtk.Popover()
        # 创建垂直布局容器
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

        # 垂直滑块
        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 5)
        self.vol_scale.set_inverted(True) # 让 100 在上面，0 在下面，符合直觉
        self.vol_scale.set_size_request(-1, 150) # 设置高度
        self.vol_scale.set_value(80) # 默认值

        # 绑定事件：调整音量 + 动态更新图标
        self.vol_scale.connect("value-changed", self.on_volume_changed_ui)

        vbox.append(self.vol_scale)
        pop.set_child(vbox)
        return pop
    
    def on_volume_changed_ui(self, scale):
        val = scale.get_value()
        self.player.set_volume(val / 100.0)

        # 根据音量大小切换图标
        icon = "audio-volume-high-symbolic"
        if val == 0: icon = "audio-volume-muted-symbolic"
        elif val < 30: icon = "audio-volume-low-symbolic"
        elif val < 70: icon = "audio-volume-medium-symbolic"

        if hasattr(self, 'vol_btn'):
            self.vol_btn.set_icon_name(icon)


    def toggle_mini_mode(self, btn):
        self.is_mini_mode = not self.is_mini_mode
        
        if self.is_mini_mode:
            # === 进入迷你模式 ===
            self.saved_width = self.win.get_width()
            self.saved_height = self.win.get_height()
            
            # 1. [核心] 添加 CSS 类 "mini-state"，对应 ui_config.py
            self.bottom_bar.add_css_class("mini-state")
            
            # 2. 移除主界面
            self.main_vbox.remove(self.paned)
            self.header.set_visible(False)
            self.mini_controls.set_visible(True)
            
            # 3. [核心] 隐藏不需要的组件 (实现极简)
            if hasattr(self, 'timeline_box'): self.timeline_box.set_visible(False)
            if hasattr(self, 'vol_box'): self.vol_box.set_visible(False)
            if hasattr(self, 'tech_box'): self.tech_box.set_visible(False)

            # 4. 设置无边框
            self.win.set_decorated(False)

            self.win.set_resizable(False)
            
            # 5. 压缩高度 (因为没有进度条了，可以非常扁)
            self.win.set_size_request(450, 85) 
            self.win.set_default_size(450, 85)
            self.win.present()
            
            if hasattr(self, 'mini_btn'): self.mini_btn.set_icon_name("view-fullscreen-symbolic")
            
        else:
            # === 恢复完整模式 ===
            self.win.set_resizable(True)
            
            # 1. [核心] 移除 CSS 类，恢复 margin
            self.bottom_bar.remove_css_class("mini-state")
            
            # 2. 恢复主界面
            self.main_vbox.insert_child_after(self.paned, self.header)
            self.header.set_visible(True)
            self.paned.set_visible(True)
            self.mini_controls.set_visible(False)
            
            # 3. [核心] 恢复组件显示
            if hasattr(self, 'timeline_box'): 
                self.timeline_box.set_visible(True)
                self.timeline_box.set_size_request(450, -1)
                
            if hasattr(self, 'vol_box'): self.vol_box.set_visible(True)
            if hasattr(self, 'tech_box'): self.tech_box.set_visible(True)
            
            # 4. 恢复窗口
            self.win.set_decorated(True)
            self.win.set_size_request(ui_config.WINDOW_WIDTH, ui_config.WINDOW_HEIGHT)
            self.win.set_default_size(self.saved_width, self.saved_height)
            
            if hasattr(self, 'mini_btn'): self.mini_btn.set_icon_name("view-restore-symbolic")

    def _build_user_popover(self):
        pop = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        btn = Gtk.Button(label="Logout", css_classes=["flat", "destructive-action"])
        btn.connect("clicked", self.on_logout_clicked)
        vbox.append(btn)
        pop.set_child(vbox)
        return pop
    
    def on_tech_info_clicked(self, btn):
        win = AudioSignalPathWindow(self)
        win.present()

    def _build_body(self, container):
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True); container.append(self.paned)
        self.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.nav_list = Gtk.ListBox(css_classes=["navigation-sidebar"], margin_top=10); self.nav_list.connect("row-activated", self.on_nav_selected)
        
        nav_items = [
            ("home", "go-home-symbolic", "Home"),
            ("collection", "user-bookmarks-symbolic", "My Collection"),
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
        t_box = Gtk.Box(spacing=12, margin_start=32, margin_end=32, margin_top=32, margin_bottom=12)
        self.grid_title_label = Gtk.Label(label="Home", xalign=0, css_classes=["section-title"])
        self.artist_fav_btn = Gtk.Button(css_classes=["heart-btn"], icon_name="emblem-favorite-symbolic", visible=False)
        self.artist_fav_btn.connect("clicked", self.on_artist_fav_clicked)
        t_box.append(self.grid_title_label); t_box.append(self.artist_fav_btn); grid_vbox.append(t_box)

        self.login_prompt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, valign=Gtk.Align.CENTER, vexpand=True)
        self.login_prompt_box.set_visible(False)
        prompt_icon = Gtk.Image(icon_name="avatar-default-symbolic", pixel_size=128, css_classes=["dim-label"])
        prompt_label = Gtk.Label(label="Please login to access your Tidal collection", css_classes=["heading"])
        prompt_btn = Gtk.Button(label="Login to Tidal", css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        prompt_btn.connect("clicked", self.on_login_clicked)
        self.login_prompt_box.append(prompt_icon); self.login_prompt_box.append(prompt_label); self.login_prompt_box.append(prompt_btn)
        grid_vbox.append(self.login_prompt_box)

        self.alb_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.collection_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=32, margin_start=32, margin_end=32, margin_bottom=32)
        self.alb_scroll.set_child(self.collection_content_box)
        grid_vbox.append(self.alb_scroll)
        self.right_stack.add_named(grid_vbox, "grid_view")

    def _toggle_login_view(self, logged_in):
        self.login_prompt_box.set_visible(not logged_in)
        self.alb_scroll.set_visible(logged_in)
        if not logged_in:
            self.login_btn.set_label("Login")
            self.grid_title_label.set_text("Welcome")
        else:
            display_name = "User"
            user = self.backend.user
            if user:
                meta = getattr(user, 'profile_metadata', None)
                if meta:
                    if isinstance(meta, dict): display_name = meta.get('name') or meta.get('firstName') or display_name
                    else: display_name = getattr(meta, 'name', None) or getattr(meta, 'first_name', None) or display_name
                if display_name == "User" or display_name is None:
                    candidates = [getattr(user, 'first_name', None), getattr(user, 'name', None), getattr(user, 'firstname', None)]
                    for c in candidates:
                        if c and isinstance(c, str) and c.strip(): display_name = c; break
                if (not display_name or display_name == "User") and hasattr(user, 'username') and user.username:
                    try: display_name = user.username.split('@')[0].capitalize()
                    except: display_name = user.username
            self.login_btn.set_label(f"Hi, {display_name}")
            self.grid_title_label.set_text("Home")

    def _build_tracks_view(self):
        trk_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        trk_scroll = Gtk.ScrolledWindow(vexpand=True)
        trk_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.album_header_box = Gtk.Box(spacing=24, css_classes=["album-header-box"])
        self.header_art = Gtk.Image(width_request=160, height_request=160, css_classes=["header-art"])

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.header_title = Gtk.Label(xalign=0, wrap=True, css_classes=["album-title-large"])

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
        # 信号连接
        self.track_list.connect("row-activated", self.on_track_selected)
        trk_content.append(self.track_list)

        trk_scroll.set_child(trk_content); trk_vbox.append(trk_scroll)
        self.right_stack.add_named(trk_vbox, "tracks")

    def _build_settings_page(self):
        settings_scroll = Gtk.ScrolledWindow(vexpand=True)
        settings_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-container"], spacing=20)
        settings_scroll.set_child(settings_vbox)
        settings_vbox.append(Gtk.Label(label="Settings", xalign=0, css_classes=["album-title-large"], margin_bottom=10))

        # --- Audio Quality ---
        group_q = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])
        row_q = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        row_q.append(Gtk.Label(label="Audio Quality", hexpand=True, xalign=0))
        self.quality_dd = Gtk.DropDown(model=Gtk.StringList.new(["Max (Up to 24-bit, 192 kHz)", "High (16-bit, 44.1 kHz)", "Low (320 kbps)"]))
        self.quality_dd.connect("notify::selected-item", self.on_quality_changed)
        row_q.append(self.quality_dd); group_q.append(row_q); settings_vbox.append(group_q)

        # --- Audio Output ---
        settings_vbox.append(Gtk.Label(label="Audio Output", xalign=0, css_classes=["section-title"], margin_top=10))
        group_out = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])

        # 1. Bit-Perfect
        row_bp = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        bp_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        bp_info.append(Gtk.Label(label="Bit-Perfect Mode", xalign=0, css_classes=["settings-label"]))
        bp_info.append(Gtk.Label(label="Bypass software mixer & EQ", xalign=0, css_classes=["dim-label"]))
        row_bp.append(bp_info); row_bp.append(Gtk.Box(hexpand=True))
        self.bp_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.bp_switch.set_active(self.settings.get("bit_perfect", False))
        self.bp_switch.connect("state-set", self.on_bit_perfect_toggled)
        row_bp.append(self.bp_switch); group_out.append(row_bp)

        # 2. Exclusive Mode
        row_ex = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        ex_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        title_box = Gtk.Box(spacing=6, orientation=Gtk.Orientation.HORIZONTAL)
        title_box.append(Gtk.Label(label="Force Hardware Exclusive", xalign=0, css_classes=["settings-label"]))
        help_btn = Gtk.Button(icon_name="dialog-question-symbolic", css_classes=["flat", "circular"])
        help_btn.set_tooltip_text("Click for details") 
        help_pop = Gtk.Popover(); help_pop.set_parent(help_btn); help_pop.set_autohide(True)
        pop_content = Gtk.Label(wrap=True, max_width_chars=40, xalign=0)
        pop_content.set_markup("<b>Exclusive Mode Control</b>\n\n<b>⚠️ Recommendation:</b>\nOnly enable this for <b>External USB DACs</b>.\n\n• <b>Benefits:</b> Ensures true Bit-Perfect playback.\n• <b>Limitations:</b> System volume DISABLED.")
        pop_box = Gtk.Box(margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        pop_box.append(pop_content); help_pop.set_child(pop_box)
        help_btn.connect("clicked", lambda x: help_pop.popup())
        title_box.append(help_btn); ex_info.append(title_box)
        ex_info.append(Gtk.Label(label="Bypass and release system audio control for this device", xalign=0, css_classes=["dim-label"]))
        row_ex.append(ex_info); row_ex.append(Gtk.Box(hexpand=True))
        self.ex_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.ex_switch.set_sensitive(self.settings.get("bit_perfect", False))
        self.ex_switch.set_active(self.settings.get("exclusive_lock", False))
        self.ex_switch.connect("state-set", self.on_exclusive_toggled)
        row_ex.append(self.ex_switch); group_out.append(row_ex)

        # 3. Latency
        row_lat = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        lat_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        lat_info.append(Gtk.Label(label="Output Latency", xalign=0, css_classes=["settings-label"]))
        lat_info.append(Gtk.Label(label="Target buffer size (Effective in Exclusive Mode)", xalign=0, css_classes=["dim-label"]))
        row_lat.append(lat_info); row_lat.append(Gtk.Box(hexpand=True))
        self.latency_dd = Gtk.DropDown(model=Gtk.StringList.new(self.LATENCY_OPTIONS))
        self.latency_dd.set_valign(Gtk.Align.CENTER)
        
        # [修复重点] 这里的可用性必须依赖于 exclusive_lock 的状态
        self.latency_dd.set_sensitive(self.settings.get("exclusive_lock", False))
        
        saved_profile = self.settings.get("latency_profile", "Standard (100ms)")
        if saved_profile not in self.LATENCY_OPTIONS: saved_profile = "Standard (100ms)"
        try:
            target_idx = self.LATENCY_OPTIONS.index(saved_profile)
            self.latency_dd.set_selected(target_idx)
        except ValueError:
            self.latency_dd.set_selected(1)
        self.latency_dd.connect("notify::selected-item", self.on_latency_changed)
        row_lat.append(self.latency_dd); group_out.append(row_lat)

        # 4. Driver
        row_drv = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        row_drv.append(Gtk.Label(label="Audio Driver", hexpand=True, xalign=0))
        drivers = self.player.get_drivers()
        self.driver_dd = Gtk.DropDown(model=Gtk.StringList.new(drivers))
        self.driver_dd.connect("notify::selected-item", self.on_driver_changed)
        row_drv.append(self.driver_dd); group_out.append(row_drv)

        # 5. Device
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
        self.player_overlay = Gtk.Overlay()
        container.append(self.player_overlay)

        self.bottom_bar = Gtk.Box(spacing=24, css_classes=["card-bar"])
        self.player_overlay.set_child(self.bottom_bar)
        
        # 迷你模式控制按钮（右上角）
        self.mini_controls = Gtk.Box(spacing=4, valign=Gtk.Align.START, halign=Gtk.Align.END)
        self.mini_controls.set_margin_top(6)
        self.mini_controls.set_margin_end(6)
        self.mini_controls.set_visible(False)
        
        m_restore = Gtk.Button(icon_name="view-fullscreen-symbolic", css_classes=["flat", "circular"])
        m_restore.set_tooltip_text("Restore to Default View")
        m_restore.connect("clicked", self.toggle_mini_mode)
        
        m_close = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "circular"])
        m_close.connect("clicked", lambda b: self.win.close())
        
        self.mini_controls.append(m_restore)
        self.mini_controls.append(m_close)
        self.player_overlay.add_overlay(self.mini_controls)

        # --- 1. 左侧：歌曲信息 ---
        self.info_area = Gtk.Box(spacing=14, valign=Gtk.Align.CENTER)
        self.art_img = Gtk.Image(width_request=72, height_request=72, css_classes=["playback-art"])
        gest = Gtk.GestureClick(); gest.connect("pressed", self.on_player_art_clicked); self.art_img.add_controller(gest)
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=0)
        self.lbl_title = Gtk.Label(xalign=0, css_classes=["player-title"], ellipsize=3)
        self.lbl_artist = Gtk.Label(xalign=0, css_classes=["player-artist"], ellipsize=3)
        self.lbl_album = Gtk.Label(xalign=0, css_classes=["player-album"], ellipsize=3)
        t.append(self.lbl_title); t.append(self.lbl_artist); t.append(self.lbl_album)
        self.info_area.append(self.art_img); self.info_area.append(t); self.bottom_bar.append(self.info_area)
        
        # --- 2. 中间：播放控制 ---
        c_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        
        ctrls = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        ctrls.add_css_class("player-ctrls-box") 
        # ctrls.set_margin_top(25) # 已由 CSS 控制
        
        btn_prev = Gtk.Button(icon_name="media-skip-backward-symbolic", css_classes=["flat"])
        btn_prev.connect("clicked", self.on_prev_track); ctrls.append(btn_prev)
        self.play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["pill", "suggested-action"])
        self.play_btn.connect("clicked", self.on_play_pause); ctrls.append(self.play_btn)
        btn_next = Gtk.Button(icon_name="media-skip-forward-symbolic", css_classes=["flat"])
        btn_next.connect("clicked", lambda b: self.on_next_track()); ctrls.append(btn_next)
        c_box.append(ctrls)
        
        self.timeline_box = Gtk.Box(spacing=12, orientation=Gtk.Orientation.HORIZONTAL)
        attr_list = Pango.AttrList.from_string("font-features 'tnum=1'")
        self.lbl_current_time = Gtk.Label(label="0:00", css_classes=["dim-label"]); self.lbl_current_time.set_attributes(attr_list)
        self.lbl_total_time = Gtk.Label(label="0:00", css_classes=["dim-label"]); self.lbl_total_time.set_attributes(attr_list)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); self.scale.set_hexpand(True); self.scale.connect("value-changed", self.on_seek)
        self.timeline_box.append(self.lbl_current_time); self.timeline_box.append(self.scale); self.timeline_box.append(self.lbl_total_time)
        self.timeline_box.set_size_request(450, -1); self.timeline_box.set_halign(Gtk.Align.CENTER); c_box.append(self.timeline_box)
        
        self.tech_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=4)
        self.bp_label = Gtk.Label(label="BIT PERFECT", css_classes=["bp-text-glow"], visible=False); self.tech_box.append(self.bp_label)
        self.lbl_tech = Gtk.Label(label="", css_classes=["tech-label"], ellipsize=3, visible=False); self.tech_box.append(self.lbl_tech); c_box.append(self.tech_box)
        
        self.bottom_bar.append(c_box)
        
        # --- 3. 右侧：EQ 和 音量 (修改部分) ---
        # 减小间距，让图标靠得更近
        self.vol_box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER) 
        
        # EQ 按钮
        self.eq_btn = Gtk.Button(icon_name="eq-icon-symbolic", css_classes=["flat"])
        self.eq_pop = self._build_eq_popover()
        self.eq_pop.set_parent(self.eq_btn)
        self.eq_btn.connect("clicked", lambda b: self.eq_pop.popup())
        self.vol_box.append(self.eq_btn)
        
        # [修改] 音量按钮 (替代旧的 Slider)
        self.vol_btn = Gtk.Button(icon_name="audio-volume-high-symbolic", css_classes=["flat"])
        self.vol_pop = self._build_volume_popover()
        self.vol_pop.set_parent(self.vol_btn)
        self.vol_btn.connect("clicked", lambda b: self.vol_pop.popup())
        self.vol_box.append(self.vol_btn)
        
        self.bottom_bar.append(self.vol_box)

    def _lock_volume_controls(self, locked):
        # 检查新组件是否存在
        if not hasattr(self, 'vol_scale'): return
        
        if locked:
            # 锁定：设为 100%，并禁用按钮
            self.vol_scale.set_value(100)
            self.player.set_volume(1.0)
            
            # 禁用按钮，让用户无法点开调节
            self.vol_btn.set_sensitive(False)
            self.vol_btn.set_tooltip_text("Volume locked in Bit-Perfect/Exclusive mode")
        else:
            # 解锁
            self.vol_btn.set_sensitive(True)
            self.vol_scale.set_sensitive(True)
            self.vol_btn.set_tooltip_text("Adjust Volume")

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
        while c := self.collection_content_box.get_first_child(): self.collection_content_box.remove(c)
        print("[UI] User logged out.")

    def on_login_success(self):
        print("[UI] Login successful!")
        self._toggle_login_view(True)
        child = self.nav_list.get_first_child()
        while child:
            if hasattr(child, 'nav_id') and child.nav_id == 'home':
                self.nav_list.select_row(child)
                self.on_nav_selected(self.nav_list, child)
                break
            child = child.get_next_sibling()

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
        self.settings["exclusive_lock"] = state
        self.save_settings()
        
        self.player.toggle_bit_perfect(True, exclusive_lock=state)
        
        # [修复重点] 恢复互锁：独占开 -> Latency 可用；独占关 -> Latency 变灰
        self.latency_dd.set_sensitive(state)

        if state:
            # 开启独占：强制 ALSA，禁用驱动选择
            self._force_driver_selection("ALSA")
            self.driver_dd.set_sensitive(False)
            self.on_driver_changed(self.driver_dd, None)
        else:
            # 关闭独占：恢复驱动选择
            self.driver_dd.set_sensitive(True)
            # 刷新一下非独占状态下的设备列表
            self.on_device_changed(self.device_dd, None)

    def on_latency_changed(self, dd, p):
        selected = dd.get_selected_item()
        if not selected: return
        profile_name = selected.get_string()

        # 1. 保存设置
        self.settings["latency_profile"] = profile_name
        self.save_settings()

        # 2. 应用到 Player
        if profile_name in self.LATENCY_MAP:
            buf_ms, lat_ms = self.LATENCY_MAP[profile_name]
            self.player.set_alsa_latency(buf_ms, lat_ms)

            # 3. 如果当前正处于独占模式，必须重启输出才能生效
            if self.ex_switch.get_active():
                print("[Main] Latency changed, restarting output...")
                # 重新触发一次 set_output
                self.on_driver_changed(self.driver_dd, None)

    def _force_driver_selection(self, keyword):
        model = self.driver_dd.get_model()
        for i in range(model.get_n_items()):
            if keyword in model.get_item(i).get_string(): self.driver_dd.set_selected(i); break

    def update_tech_label(self, info):
        fmt = info.get('fmt_str', '')
        codec = info.get('codec', '-')
        if not fmt and (not codec or codec in ["-", "Loading..."]):
            self.lbl_tech.set_visible(False)
            return
        dev_name = getattr(self, 'current_device_name', 'Default')
        if len(dev_name) > 30: dev_name = dev_name[:28] + ".."
        display_codec = codec
        if not display_codec or display_codec in ["-", "Loading..."]:
            display_codec = "PCM" 
        self.lbl_tech.set_text(f"{display_codec} | {fmt} | {info.get('bitrate',0)//1000}kbps | {dev_name}")
        self.lbl_tech.set_visible(True)

    def on_settings_clicked(self, btn):
        self.right_stack.set_visible_child_name("settings"); self.grid_title_label.set_text("Settings"); self.back_btn.set_sensitive(True); self.nav_list.select_row(None)

    def on_quality_changed(self, dd, p):
        selected = dd.get_selected_item()
        if not selected: return
        mode_str = selected.get_string()
        self.backend.set_quality_mode(mode_str)
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
        
        # 保存驱动设置
        if not self.ex_switch.get_active() or driver_name == "ALSA":
            self.settings["driver"] = driver_name
            self.save_settings()

        self.current_device_name = "Default"
        self.update_tech_label(self.player.stream_info)

        def refresh_devices():
            # [关键] 暂停设备变更的监听，防止刷新列表时误触保存
            self.ignore_device_change = True
            
            devices = self.player.get_devices_for_driver(driver_name)
            self.current_device_list = devices 
            self.device_dd.set_model(Gtk.StringList.new([d["name"] for d in devices]))
            
            # --- 设备恢复逻辑 ---
            saved_dev = self.settings.get("device")
            sel_idx = 0
            found = False
            
            if saved_dev:
                for i, d in enumerate(devices):
                    # 只要名字匹配就选中
                    if d["name"] == saved_dev: 
                        sel_idx = i
                        found = True
                        break
            
            self.device_dd.set_sensitive(len(devices) > 1)
            
            # 设置选中项
            if sel_idx < len(devices):
                self.device_dd.set_selected(sel_idx)
                
            # [关键] 恢复监听
            self.ignore_device_change = False
            
            # 只有在确实切换了设备的情况下才应用输出
            target_id = None
            if sel_idx < len(devices):
                target_id = devices[sel_idx]['device_id']
                self.current_device_name = devices[sel_idx]['name']
                
            GLib.idle_add(lambda: self.update_tech_label(self.player.stream_info))
            self.player.set_output(driver_name, target_id)

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

    # [统一点击入口]
    def on_grid_item_activated(self, flow, child):
        if not child: return
        data = getattr(child, 'data_item', None)
        if not data: return
        obj = data.get('obj')
        
        if data['type'] == 'Track':
            self._play_single_track(obj)
            return
        if data['type'] == 'Artist':
            self.on_artist_clicked(obj)
            return
        self.show_album_details(obj)

    def _play_single_track(self, track):
        self.current_track_list = [track]
        self.current_index = 0
        self.playing_track = track
        self.playing_track_id = track.id
        self._update_track_list_icon()
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

    def show_album_details(self, alb):
        current_view = self.right_stack.get_visible_child_name()
        if current_view and current_view != "tracks": self.nav_history.append(current_view)
        self.current_album = alb
        self.right_stack.set_visible_child_name("tracks"); self.back_btn.set_sensitive(True)
        title = getattr(alb, 'title', getattr(alb, 'name', 'Unknown'))
        self.header_title.set_text(title)
        artist_name = "Various Artists"
        if hasattr(alb, 'artist') and alb.artist: 
            artist_name = alb.artist.name if hasattr(alb.artist, 'name') else str(alb.artist)
        self.header_artist.set_text(artist_name)
        utils.load_img(self.header_art, lambda: self.backend.get_artwork_url(alb, 640), self.cache_dir, 160)
        is_fav = self.backend.is_favorite(getattr(alb, 'id', '')); self._update_fav_icon(self.fav_btn, is_fav)
        while c := self.track_list.get_first_child(): self.track_list.remove(c)
        def detail_task():
            ts = self.backend.get_tracks(alb)
            desc = ""
            if hasattr(alb, 'release_date') and alb.release_date:
                desc += str(alb.release_date.year)
            elif hasattr(alb, 'last_updated'):
                desc += "Updated Recently"
            count = len(ts) if ts else 0
            if count > 0: desc += f"  •  {count} Tracks"
            GLib.idle_add(lambda: self.header_meta.set_text(desc.strip(' • ')))
            GLib.idle_add(self.populate_tracks, ts)
        Thread(target=detail_task, daemon=True).start()

    def populate_tracks(self, tracks):
        self.current_track_list = tracks
        if self.playing_track_id:
            found_idx = -1
            for i, t in enumerate(tracks):
                if t.id == self.playing_track_id: found_idx = i; break
            if found_idx != -1: self.current_index = found_idx
        while c := self.track_list.get_first_child(): self.track_list.remove(c)
        for i, t in enumerate(tracks):
            row = Gtk.ListBoxRow(); row.track_id = t.id
            b = Gtk.Box(spacing=16, margin_top=10, margin_bottom=10)
            stack = Gtk.Stack(); stack.set_size_request(30, -1)
            lbl = Gtk.Label(label=str(i+1), css_classes=["dim-label"]); stack.add_named(lbl, "num")
            icon = Gtk.Image(icon_name="media-playback-start-symbolic"); icon.add_css_class("accent"); stack.add_named(icon, "icon")
            if self.playing_track_id and t.id == self.playing_track_id: stack.set_visible_child_name("icon")
            else: stack.set_visible_child_name("num")
            b.append(stack)
            lbl_title = Gtk.Label(label=t.name, xalign=0, hexpand=True, ellipsize=3); b.append(lbl_title)
            art_name = getattr(t.artist, 'name', '-') if hasattr(t, 'artist') else '-'
            lbl_art = Gtk.Label(label=art_name, xalign=0, ellipsize=3, css_classes=["dim-label"])
            lbl_art.set_size_request(160, -1); lbl_art.set_max_width_chars(20); lbl_art.set_margin_end(12); b.append(lbl_art)
            alb_name = t.album.name if hasattr(t, 'album') and t.album else "-"
            lbl_alb = Gtk.Label(label=alb_name, xalign=0, ellipsize=3, css_classes=["dim-label"])
            lbl_alb.set_size_request(260, -1); lbl_alb.set_max_width_chars(20); lbl_alb.set_margin_end(12); b.append(lbl_alb)
            dur_sec = getattr(t, 'duration', 0)
            if dur_sec:
                m, s = divmod(dur_sec, 60); dur_str = f"{m}:{s:02d}"
                lbl_dur = Gtk.Label(label=dur_str, css_classes=["dim-label"])
                lbl_dur.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'")); lbl_dur.set_margin_end(24); b.append(lbl_dur)
            row.set_child(b); self.track_list.append(row)

    def _update_track_list_icon(self):
        row = self.track_list.get_first_child()
        while row:
            if hasattr(row, 'track_id'):
                box = row.get_child()
                if box:
                    stack = box.get_first_child()
                    if isinstance(stack, Gtk.Stack):
                        if row.track_id == self.playing_track_id: stack.set_visible_child_name("icon")
                        else: stack.set_visible_child_name("num")
            row = row.get_next_sibling()

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
        while c := self.collection_content_box.get_first_child(): self.collection_content_box.remove(c)
        self.main_flow = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=30, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=28)
        self.main_flow.connect("child-activated", self.on_grid_item_activated)
        self.collection_content_box.append(self.main_flow)
        Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_albums(artist))), daemon=True).start()

    def batch_load_albums(self, albs, batch=6):
        if not albs: return False
        curr, rem = albs[:batch], albs[batch:]
        for alb in curr:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
            img = Gtk.Image(pixel_size=130, css_classes=["album-cover-img"])
            utils.load_img(img, lambda a=alb: self.backend.get_artwork_url(a, 640), self.cache_dir, 130)
            v.append(img); v.append(Gtk.Label(label=alb.name, ellipsize=3, halign=Gtk.Align.CENTER, wrap=True, max_width_chars=16))
            c = Gtk.FlowBoxChild(); c.set_child(v)
            c.data_item = {'obj': alb, 'type': 'Album'}
            self.main_flow.append(c)
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
            c = Gtk.FlowBoxChild(); c.set_child(v)
            c.data_item = {'obj': art, 'type': 'Artist'}
            self.main_flow.append(c)
        if rem: GLib.timeout_add(50, self.batch_load_artists, rem, batch)
        return False

    def batch_load_home(self, sections):
        if not sections: return
        for sec in sections:
            self.collection_content_box.append(Gtk.Label(label=sec['title'], xalign=0, css_classes=["title-4", "dim-label"]))
            flow = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=30, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=28)
            flow.connect("child-activated", self.on_grid_item_activated)
            self.collection_content_box.append(flow)
            for item_data in sec['items']:
                v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
                img_size = 130; img_cls = "album-cover-img"
                if item_data['type'] == 'Artist' or 'Radio' in item_data['name']:
                    img_size = 120; img_cls = "circular-avatar"
                img = Gtk.Image(pixel_size=img_size, css_classes=[img_cls])
                if item_data['image_url']: utils.load_img(img, item_data['image_url'], self.cache_dir, img_size)
                else: img.set_from_icon_name("audio-x-generic-symbolic")
                v.append(img)
                v.append(Gtk.Label(label=item_data['name'], ellipsize=2, halign=Gtk.Align.CENTER, wrap=True, max_width_chars=16, css_classes=["heading"]))
                if item_data['sub_title']:
                    v.append(Gtk.Label(label=item_data['sub_title'], ellipsize=1, halign=Gtk.Align.CENTER, css_classes=["caption", "dim-label"]))
                c = Gtk.FlowBoxChild(); c.set_child(v); c.data_item = item_data
                flow.append(c)

    def on_nav_selected(self, box, row):
        if not row: return
        self.nav_history.clear()
        self.artist_fav_btn.set_visible(False)
        self.right_stack.set_visible_child_name("grid_view")
        self.back_btn.set_sensitive(False)
        while c := self.collection_content_box.get_first_child(): self.collection_content_box.remove(c)
        if row.nav_id == "home":
            self.grid_title_label.set_text("Home")
            if self.backend.user: 
                Thread(target=lambda: GLib.idle_add(self.batch_load_home, self.backend.get_home_page())).start()
        elif row.nav_id == "collection":
            self.grid_title_label.set_text("My Collection")
            self.create_album_flow()
            if self.backend.user: Thread(target=lambda: GLib.idle_add(self.batch_load_albums, list(self.backend.get_recent_albums()))).start()
        elif row.nav_id == "history":
            self.grid_title_label.set_text("History")
            self.create_album_flow()
            Thread(target=lambda: GLib.idle_add(self.batch_load_albums, self.history_mgr.get_albums())).start()
        elif row.nav_id == "artists":
            self.grid_title_label.set_text("Favorite Artists")
            self.create_album_flow()
            if self.backend.user: Thread(target=lambda: GLib.idle_add(self.batch_load_artists, self.backend.get_favorites())).start()

    def create_album_flow(self):
        self.main_flow = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=30, selection_mode=Gtk.SelectionMode.NONE, column_spacing=24, row_spacing=28)
        self.main_flow.connect("child-activated", self.on_grid_item_activated)
        self.collection_content_box.append(self.main_flow)

    def on_play_pause(self, btn):
        if self.player.is_playing(): self.player.pause(); btn.set_icon_name("media-playback-start-symbolic")
        else: self.player.play(); btn.set_icon_name("media-playback-pause-symbolic")


    def on_next_track(self):
        """处理自动切歌回调：由 AudioPlayer 触发 EOS 时调用"""
        if self.current_index < len(self.current_track_list) - 1:
            self.current_index += 1
            # 获取下一行的 ListBoxRow
            next_row = self.track_list.get_row_at_index(self.current_index)
            if next_row:
                # 模拟列表行激活，自动开始播放
                self.track_list.select_row(next_row)
                self.on_track_selected(self.track_list, next_row)
        else:
            print("[Player] Reached end of current track list.")

    # [新增] 补全 on_prev_track
    def on_prev_track(self, btn):
        if self.current_index > 0:
            self.current_index -= 1
            prev_row = self.track_list.get_row_at_index(self.current_index)
            if prev_row:
                self.track_list.select_row(prev_row)
                self.on_track_selected(self.track_list, prev_row)

    def on_seek(self, s): 
        if not self.is_programmatic_update: self.player.seek(s.get_value())

    def update_ui_loop(self):
        p, d = self.player.get_position()
        if d > 0: 
            self.is_programmatic_update = True
            self.scale.set_range(0, d)
            self.scale.set_value(p)
            self.is_programmatic_update = False
            self.lbl_current_time.set_text(f"{int(p//60)}:{int(p%60):02d}")
            self.lbl_total_time.set_text(f"{int(d//60)}:{int(d%60):02d}")
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
            c = Gtk.FlowBoxChild(); c.set_child(v);
            c.data_item = {'obj': art, 'type': 'Artist'}
            self.res_art_flow.append(c)
        self.res_alb_box.set_visible(bool(albums))
        for alb in albums:
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
            img = Gtk.Image(pixel_size=110, css_classes=["album-cover-img"])
            utils.load_img(img, lambda a=alb: self.backend.get_artwork_url(a, 320), self.cache_dir, 110)
            v.append(img); v.append(Gtk.Label(label=alb.name, ellipsize=2, wrap=True, max_width_chars=14))
            c = Gtk.FlowBoxChild(); c.set_child(v)
            c.data_item = {'obj': alb, 'type': 'Album'}
            self.res_alb_flow.append(c)
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

    # [已修复] 补全 on_track_selected
    def on_track_selected(self, box, row):
        if not row: return
        idx = row.get_index()
        track = self.current_track_list[idx]
        self.current_index = idx
        self.playing_track = track
        self.playing_track_id = track.id
        self._update_track_list_icon()

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

    # [已修复] 补全 on_back_clicked
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
