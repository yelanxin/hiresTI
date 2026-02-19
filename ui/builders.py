import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango

from visualizer import SpectrumVisualizer
from background_viz import BackgroundVisualizer
import ui_config


def build_header(app, container):
    app.header = Adw.HeaderBar()
    container.append(app.header)

    app.back_btn = Gtk.Button(icon_name="go-previous-symbolic", sensitive=False)
    app.back_btn.connect("clicked", app.on_back_clicked)
    app.header.pack_start(app.back_btn)

    app.search_entry = Gtk.Entry(
        placeholder_text="Search...",
        width_request=200,
        valign=Gtk.Align.CENTER,
    )
    app.search_entry.connect("activate", app.on_search)
    app.search_entry.connect("changed", app.on_search_changed)
    app.header.set_title_widget(app.search_entry)

    box_right = Gtk.Box(spacing=6)

    app.login_btn = Gtk.Button(label="Login", css_classes=["flat"])
    app.login_btn.connect("clicked", app.on_login_clicked)
    app.user_popover = app._build_user_popover()
    app.user_popover.set_parent(app.login_btn)

    app.help_pop = app._build_help_popover()

    app.mini_btn = Gtk.Button(icon_name="hiresti-mini-symbolic", css_classes=["flat"])
    app.mini_btn.set_tooltip_text("Mini Player Mode")
    app.mini_btn.connect("clicked", app.toggle_mini_mode)

    app.tools_btn = Gtk.Button(icon_name="hiresti-gear-symbolic", css_classes=["flat"])
    app.tools_btn.set_tooltip_text("Tools & Settings")
    app.tools_pop = Gtk.Popover()
    app.tools_pop.set_parent(app.tools_btn)
    tools_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=4,
        margin_top=8,
        margin_bottom=8,
        margin_start=8,
        margin_end=8,
    )

    def _tool_row(icon_name, label, callback):
        btn = Gtk.Button(css_classes=["flat"])
        row = Gtk.Box(spacing=8)
        row.append(Gtk.Image.new_from_icon_name(icon_name))
        row.append(Gtk.Label(label=label, xalign=0))
        btn.set_child(row)
        btn.connect("clicked", callback)
        return btn

    def _on_shortcuts_clicked(_btn):
        app.tools_pop.popdown()
        app.help_pop.set_parent(app.tools_btn)
        app.help_pop.popup()

    def _on_signal_path_clicked(_btn):
        app.tools_pop.popdown()
        app.on_tech_info_clicked(_btn)

    def _on_settings_clicked(_btn):
        app.tools_pop.popdown()
        app.on_settings_clicked(_btn)

    tools_box.append(_tool_row("hiresti-shortcuts-symbolic", "Keyboard Shortcuts", _on_shortcuts_clicked))
    tools_box.append(_tool_row("hiresti-tech-symbolic", "Signal Path / Tech Info", _on_signal_path_clicked))
    tools_box.append(_tool_row("hiresti-gear-symbolic", "Settings", _on_settings_clicked))
    app.tools_pop.set_child(tools_box)
    app.tools_btn.connect("clicked", lambda _b: app.tools_pop.popup())

    box_right.append(app.login_btn)
    box_right.append(app.mini_btn)
    box_right.append(app.tools_btn)
    app.header.pack_end(box_right)


def build_body(app, container):
    app.body_overlay = Gtk.Overlay()
    app.body_overlay.set_vexpand(True)
    container.append(app.body_overlay)

    app.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    app.body_overlay.set_child(app.paned)

    app.queue_backdrop = Gtk.Box(css_classes=["queue-backdrop"])
    app.queue_backdrop.set_hexpand(True)
    app.queue_backdrop.set_vexpand(True)
    app.queue_backdrop.set_visible(False)
    backdrop_click = Gtk.GestureClick()
    backdrop_click.connect("released", lambda *_args: app.close_queue_drawer())
    app.queue_backdrop.add_controller(backdrop_click)
    app.body_overlay.add_overlay(app.queue_backdrop)

    app.queue_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT)
    app.queue_revealer.set_transition_duration(180)
    app.queue_revealer.set_reveal_child(False)
    app.queue_revealer.set_halign(Gtk.Align.END)
    app.queue_revealer.set_valign(Gtk.Align.FILL)
    app.queue_revealer.set_hexpand(False)
    app.queue_revealer.set_vexpand(True)

    app.queue_drawer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, css_classes=["queue-drawer"])
    app.queue_drawer_box.set_size_request(240, 500)
    app.queue_drawer_box.set_vexpand(True)

    q_head = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=10, margin_bottom=10)
    q_head.append(Gtk.Label(label="Queue", xalign=0, hexpand=True, css_classes=["home-section-title"]))
    app.queue_count_label = Gtk.Label(label="0 tracks", css_classes=["home-section-count"])
    q_head.append(app.queue_count_label)
    app.queue_clear_btn = None
    app.queue_drawer_box.append(q_head)

    app.queue_drawer_list = Gtk.ListBox(css_classes=["tracks-list", "queue-drawer-list"])
    app.queue_drawer_list.connect("row-activated", app.on_queue_track_selected)
    q_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    q_scroll.add_css_class("queue-drawer-scroll")
    q_scroll.set_margin_start(8)
    q_scroll.set_margin_end(8)
    q_scroll.set_margin_bottom(8)
    q_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    q_scroll.set_child(app.queue_drawer_list)
    app.queue_drawer_box.append(q_scroll)

    app.queue_revealer.set_child(app.queue_drawer_box)

    app.queue_btn = Gtk.Button(icon_name="hiresti-queue-handle-left-symbolic", css_classes=["queue-handle-btn"])
    app.queue_btn.set_tooltip_text("Open Queue")
    app.queue_btn.set_size_request(26, 50)
    app.queue_btn.set_valign(Gtk.Align.CENTER)
    app.queue_btn.set_vexpand(False)
    app.queue_btn.connect("clicked", app.toggle_queue_drawer)

    app.queue_handle_shell = Gtk.Box(css_classes=["queue-handle-shell"])
    app.queue_handle_shell.set_size_request(26, 50)
    app.queue_handle_shell.set_valign(Gtk.Align.CENTER)
    app.queue_handle_shell.set_vexpand(False)
    app.queue_handle_shell.append(app.queue_btn)

    app.queue_anchor = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=0,
        halign=Gtk.Align.END,
        valign=Gtk.Align.CENTER,
        hexpand=True,
        vexpand=True,
        css_classes=["queue-anchor"],
    )
    app.queue_anchor.append(app.queue_handle_shell)
    app.queue_anchor.append(app.queue_revealer)
    app.body_overlay.add_overlay(app.queue_anchor)

    app.output_notice_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
    app.output_notice_revealer.set_transition_duration(180)
    app.output_notice_revealer.set_reveal_child(False)
    app.output_notice_revealer.set_halign(Gtk.Align.END)
    app.output_notice_revealer.set_valign(Gtk.Align.START)
    app.output_notice_revealer.set_margin_top(10)
    app.output_notice_revealer.set_margin_end(10)
    notice_box = Gtk.Box(spacing=8, css_classes=["output-notice-chip"])
    app.output_notice_icon = Gtk.Image(icon_name="hiresti-tech-symbolic")
    app.output_notice_icon.add_css_class("output-notice-icon")
    app.output_notice_label = Gtk.Label(label="", xalign=0, css_classes=["output-notice-text"])
    notice_box.append(app.output_notice_icon)
    notice_box.append(app.output_notice_label)
    app.output_notice_revealer.set_child(notice_box)
    app.body_overlay.add_overlay(app.output_notice_revealer)

    app.viz_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
    app.viz_revealer.set_reveal_child(False)
    app.viz_revealer.set_valign(Gtk.Align.END)
    app.viz_revealer.set_halign(Gtk.Align.FILL)
    app.viz_revealer.set_hexpand(True)
    app.viz_revealer.set_vexpand(False)

    app.viz_btn = Gtk.Button(icon_name="hiresti-pan-up-symbolic", css_classes=["flat", "viz-handle-btn"])
    app.viz_btn.set_tooltip_text("Waveform / Lyrics")
    app.viz_btn.set_size_request(50, 21)
    app.viz_btn.connect("clicked", app.toggle_visualizer)

    app.viz_anchor = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=0,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.END,
        hexpand=True,
        vexpand=True,
        css_classes=["viz-handle-anchor"],
    )
    app.viz_anchor.append(app.viz_revealer)
    app.body_overlay.add_overlay(app.viz_anchor)

    app.viz_handle_box = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=0,
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.END,
        hexpand=True,
        vexpand=True,
        css_classes=["viz-handle-floating"],
    )
    app.viz_handle_box.set_margin_end(0)
    app.viz_handle_box.set_margin_bottom(2)
    app.viz_handle_box.append(app.viz_btn)
    app.body_overlay.add_overlay(app.viz_handle_box)

    app.viz_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    app.viz_root.set_hexpand(True)
    app.viz_root.set_halign(Gtk.Align.FILL)

    app.viz_switcher = Gtk.StackSwitcher()
    app.viz_switcher.set_halign(Gtk.Align.START)
    app.viz_switcher.set_margin_start(0)
    app.viz_switcher.add_css_class("mini-switcher")
    app.viz_switcher.remove_css_class("linked")
    app.viz_switcher.set_hexpand(False)

    app.viz_stack_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    app.viz_stack_box.add_css_class("viz-panel")
    app.viz_stack_box.set_overflow(Gtk.Overflow.HIDDEN)

    app.viz_stack = Gtk.Stack()
    app.viz_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
    app.viz_stack.set_size_request(-1, 250)
    app.viz_switcher.set_stack(app.viz_stack)
    app.viz_stack.connect("notify::visible-child-name", app.on_viz_page_changed)

    app.viz = SpectrumVisualizer()
    app.viz.set_num_bars(32)
    app.viz.set_valign(Gtk.Align.FILL)
    app.viz_stack.add_titled(app.viz, "spectrum", "Spectrum")

    app.viz_bars_dd = Gtk.DropDown(model=Gtk.StringList.new([str(v) for v in app.VIZ_BAR_OPTIONS]))
    app.viz_bars_dd.add_css_class("viz-theme-dd")
    app.viz_bars_dd.add_css_class("viz-right-first")
    app.viz_bars_dd.set_valign(Gtk.Align.CENTER)
    app.viz_bars_dd.connect("notify::selected", app.on_viz_bars_changed)

    app.viz_theme_dd = Gtk.DropDown(model=Gtk.StringList.new(app.viz.get_theme_names()))
    app.viz_theme_dd.add_css_class("viz-theme-dd")
    app.viz_theme_dd.add_css_class("viz-right-last")
    app.viz_theme_dd.set_valign(Gtk.Align.CENTER)
    app.viz_theme_dd.connect("notify::selected", app.on_spectrum_theme_changed)

    app.viz_effect_dd = Gtk.DropDown(model=Gtk.StringList.new(app.viz.get_effect_names()))
    app.viz_effect_dd.add_css_class("viz-theme-dd")
    app.viz_effect_dd.set_valign(Gtk.Align.CENTER)
    app.viz_effect_dd.connect("notify::selected", app.on_viz_effect_changed)

    app.viz_profile_dd = Gtk.DropDown(model=Gtk.StringList.new(app.viz.get_profile_names()))
    app.viz_profile_dd.add_css_class("viz-theme-dd")
    app.viz_profile_dd.set_valign(Gtk.Align.CENTER)
    app.viz_profile_dd.connect("notify::selected", app.on_viz_profile_changed)

    app.lyrics_font_dd = Gtk.DropDown(model=Gtk.StringList.new(app.LYRICS_FONT_PRESETS))
    app.lyrics_font_dd.add_css_class("viz-theme-dd")
    app.lyrics_font_dd.add_css_class("lyrics-font-dd")
    app.lyrics_font_dd.set_valign(Gtk.Align.CENTER)
    app.lyrics_font_dd.connect("notify::selected", app.on_lyrics_font_preset_changed)

    theme_row = Gtk.Box(spacing=10)
    theme_row.add_css_class("viz-theme-row")
    theme_row.set_hexpand(True)
    theme_row.set_halign(Gtk.Align.FILL)
    theme_row.set_margin_start(32)
    theme_row.set_margin_end(32)
    theme_row.set_margin_top(8)
    theme_row.append(app.viz_switcher)
    theme_row.append(Gtk.Box(hexpand=True))
    right_ctrl_box = Gtk.Box(spacing=0)
    right_ctrl_box.add_css_class("viz-right-controls")
    right_ctrl_box.set_halign(Gtk.Align.END)
    theme_row.append(right_ctrl_box)
    right_ctrl_box.append(app.viz_bars_dd)
    right_ctrl_box.append(app.viz_profile_dd)
    right_ctrl_box.append(app.viz_effect_dd)
    right_ctrl_box.append(app.viz_theme_dd)
    app.lyrics_font_dd.set_visible(False)
    app.lyrics_ctrl_box = Gtk.Box(spacing=0)
    app.lyrics_ctrl_box.add_css_class("viz-right-controls")
    app.lyrics_ctrl_box.set_visible(False)
    right_ctrl_box.append(app.lyrics_ctrl_box)
    app.lyrics_ctrl_box.append(app.lyrics_font_dd)

    app.lyrics_tab_root = Gtk.Overlay()
    app.bg_viz = BackgroundVisualizer()
    app.lyrics_tab_root.set_child(app.bg_viz)
    app.lyrics_motion_dd = Gtk.DropDown(model=Gtk.StringList.new(app.bg_viz.get_motion_mode_names()))
    app.lyrics_motion_dd.add_css_class("viz-theme-dd")
    app.lyrics_motion_dd.add_css_class("lyrics-motion-dd")
    app.lyrics_motion_dd.set_valign(Gtk.Align.CENTER)
    app.lyrics_motion_dd.connect("notify::selected", app.on_lyrics_motion_changed)
    app.lyrics_motion_dd.set_visible(False)
    app.lyrics_ctrl_box.append(app.lyrics_motion_dd)

    app.lyrics_scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    app.lyrics_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    app.lyrics_scroller.add_css_class("lyrics-scroller")

    app.lyrics_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    app.lyrics_vbox.set_halign(Gtk.Align.CENTER)
    app.lyrics_vbox.set_margin_top(30)
    app.lyrics_vbox.set_margin_bottom(30)

    app.lyrics_scroller.set_child(app.lyrics_vbox)
    app.lyrics_tab_root.add_overlay(app.lyrics_scroller)

    app.lyrics_offset_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    app.lyrics_offset_box.set_halign(Gtk.Align.END)
    app.lyrics_offset_box.set_valign(Gtk.Align.CENTER)
    app.lyrics_offset_box.set_margin_end(12)
    app.lyrics_offset_box.set_visible(False)
    btn_off_up = Gtk.Button(icon_name="go-up-symbolic", css_classes=["flat", "circular", "lyrics-offset-arrow"])
    btn_off_up.connect("clicked", app.on_lyrics_offset_step, 50)
    btn_off_down = Gtk.Button(icon_name="go-down-symbolic", css_classes=["flat", "circular", "lyrics-offset-arrow"])
    btn_off_down.connect("clicked", app.on_lyrics_offset_step, -50)
    app.lyrics_offset_label = Gtk.Label(label="0ms", css_classes=["caption", "dim-label"])
    app.lyrics_offset_box.append(btn_off_up)
    app.lyrics_offset_box.append(app.lyrics_offset_label)
    app.lyrics_offset_box.append(btn_off_down)
    app.lyrics_tab_root.add_overlay(app.lyrics_offset_box)
    app.viz_stack.add_titled(app.lyrics_tab_root, "lyrics", "Lyrics")

    app.viz_stack_box.append(app.viz_stack)
    app.viz_root.append(theme_row)
    app.viz_root.append(app.viz_stack_box)
    app.viz_revealer.set_child(app.viz_root)
    app.on_viz_page_changed(app.viz_stack, None)

    app.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sidebar-shell"])
    app.nav_list = Gtk.ListBox(css_classes=["navigation-sidebar"], margin_top=10)
    app.nav_list.connect("row-activated", app.on_nav_selected)

    nav_items = [
        ("home", "hiresti-home-symbolic", "Home"),
        ("collection", "hiresti-collection-symbolic", "My Albums"),
        ("liked_songs", "hiresti-favorite-symbolic", "Liked Songs"),
        ("artists", "hiresti-artists-symbolic", "Artists"),
        ("playlists", "hiresti-playlists-symbolic", "Playlists"),
        ("history", "hiresti-history-symbolic", "History"),
    ]
    for nid, icon, txt in nav_items:
        row = Gtk.ListBoxRow()
        row.nav_id = nid
        box = Gtk.Box(spacing=12, margin_start=12, margin_top=8, margin_bottom=8)
        box.append(Gtk.Image.new_from_icon_name(icon))
        box.append(Gtk.Label(label=txt))
        row.set_child(box)
        app.nav_list.append(row)

    app.sidebar_box.append(app.nav_list)
    app.paned.set_start_child(app.sidebar_box)
    app.right_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
    app.paned.set_end_child(app.right_stack)

    app._build_grid_view()
    app._build_tracks_view()
    app._build_settings_page()
    app._build_search_view()
    app.paned.set_position(int(ui_config.WINDOW_WIDTH * ui_config.SIDEBAR_RATIO))


def build_player_bar(app, container):
    app.player_overlay = Gtk.Overlay()
    app.player_overlay.add_css_class("player-overlay-container")
    container.append(app.player_overlay)

    app.bottom_bar = Gtk.CenterBox(css_classes=["card-bar"])
    app.player_overlay.set_child(app.bottom_bar)
    bottom_click = Gtk.GestureClick()
    bottom_click.set_button(0)
    bottom_click.connect("released", lambda *_args: app.close_queue_drawer())
    app.bottom_bar.add_controller(bottom_click)

    app.mini_controls = Gtk.Box(spacing=4, valign=Gtk.Align.START, halign=Gtk.Align.END)
    app.mini_controls.set_margin_top(6)
    app.mini_controls.set_margin_end(6)
    app.mini_controls.set_visible(False)

    m_restore = Gtk.Button(icon_name="view-fullscreen-symbolic", css_classes=["flat", "circular"])
    m_restore.set_tooltip_text("Restore to Default View")
    m_restore.connect("clicked", app.toggle_mini_mode)

    m_close = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "circular"])
    m_close.connect("clicked", lambda b: app.win.close())

    app.mini_controls.append(m_restore)
    app.mini_controls.append(m_close)
    app.player_overlay.add_overlay(app.mini_controls)

    side_panel_width = 340
    app.player_side_panel_width = side_panel_width

    left_panel = Gtk.Box()
    left_panel.set_hexpand(False)
    left_panel.set_halign(Gtk.Align.START)
    left_panel.set_size_request(side_panel_width, -1)

    app.info_area = Gtk.Box(spacing=14, valign=Gtk.Align.CENTER, halign=Gtk.Align.START)
    app.info_area.set_hexpand(False)
    app.info_area.set_size_request(side_panel_width, -1)
    app.art_img = Gtk.Image()
    app.art_img.set_size_request(80, 80)
    app.art_img.set_margin_top(6)
    app.art_img.set_margin_start(6)
    app.art_img.set_margin_bottom(6)
    app.art_img.add_css_class("playback-art")
    gest = Gtk.GestureClick()
    gest.connect("pressed", app.on_player_art_clicked)
    app.art_img.add_controller(gest)

    text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=0)
    text_box.set_hexpand(True)
    text_box.set_size_request(240, -1)
    title_row = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER, hexpand=True)
    app.lbl_title = Gtk.Label(xalign=0, css_classes=["player-title"], ellipsize=3)
    app.lbl_title.set_single_line_mode(True)
    app.lbl_title.set_width_chars(-1)
    app.lbl_title.set_max_width_chars(-1)
    app.lbl_title.set_hexpand(False)
    app.lbl_title.set_halign(Gtk.Align.START)
    app.track_fav_btn = Gtk.Button(css_classes=["flat", "circular", "player-heart-btn"], icon_name="hiresti-favorite-outline-symbolic", valign=Gtk.Align.START)
    app.track_fav_btn.set_margin_top(-5)
    app.track_fav_btn.set_margin_start(5)
    app.track_fav_btn.set_tooltip_text("Favorite Track")
    app.track_fav_btn.set_sensitive(False)
    app.track_fav_btn.set_visible(False)
    app.track_fav_btn.connect("clicked", app.on_track_fav_clicked)
    app.lbl_artist = Gtk.Label(xalign=0, css_classes=["player-artist"], ellipsize=3)
    app.lbl_artist.set_single_line_mode(True)
    app.lbl_artist.set_width_chars(20)
    app.lbl_artist.set_max_width_chars(20)
    app.lbl_album = Gtk.Label(xalign=0, css_classes=["player-album"], ellipsize=3)
    app.lbl_album.set_single_line_mode(True)
    app.lbl_album.set_width_chars(20)
    app.lbl_album.set_max_width_chars(20)
    title_row.append(app.lbl_title)
    title_row.append(app.track_fav_btn)
    text_box.append(title_row)
    text_box.append(app.lbl_artist)
    text_box.append(app.lbl_album)

    app.info_area.append(app.art_img)
    app.info_area.append(text_box)
    left_clamp = Adw.Clamp(maximum_size=side_panel_width, tightening_threshold=240)
    left_clamp.set_child(app.info_area)
    left_panel.append(left_clamp)
    app.player_left_panel = left_panel
    app.player_left_clamp = left_clamp
    app.player_text_box = text_box
    app.bottom_bar.set_start_widget(left_panel)

    center_panel = Gtk.Box()
    center_panel.set_hexpand(True)
    center_panel.set_halign(Gtk.Align.FILL)

    center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    ctrls = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
    ctrls.add_css_class("player-ctrls-box")

    btn_prev = Gtk.Button(icon_name="media-skip-backward-symbolic", css_classes=["flat", "transport-btn"])
    btn_prev.connect("clicked", app.on_prev_track)
    ctrls.append(btn_prev)

    app.play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["pill", "transport-main-btn"])
    app.play_btn.connect("clicked", app.on_play_pause)
    ctrls.append(app.play_btn)

    btn_next = Gtk.Button(icon_name="media-skip-forward-symbolic", css_classes=["flat", "transport-btn"])
    btn_next.connect("clicked", lambda b: app.on_next_track())
    ctrls.append(btn_next)
    center_box.append(ctrls)

    app.timeline_box = Gtk.Box(spacing=12, orientation=Gtk.Orientation.HORIZONTAL)
    attr_list = Pango.AttrList.from_string("font-features 'tnum=1'")
    app.lbl_current_time = Gtk.Label(label="0:00", css_classes=["dim-label"])
    app.lbl_current_time.set_attributes(attr_list)
    app.lbl_current_time.set_width_chars(5)
    app.lbl_current_time.set_max_width_chars(5)
    app.lbl_current_time.set_xalign(1.0)
    app.lbl_total_time = Gtk.Label(label="0:00", css_classes=["dim-label"])
    app.lbl_total_time.set_attributes(attr_list)
    app.lbl_total_time.set_width_chars(5)
    app.lbl_total_time.set_max_width_chars(5)
    app.lbl_total_time.set_xalign(0.0)
    app.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    app.scale.set_hexpand(True)
    app.scale.connect("value-changed", app.on_seek)
    app.timeline_box.append(app.lbl_current_time)
    app.timeline_box.append(app.scale)
    app.timeline_box.append(app.lbl_total_time)
    app.timeline_box.set_size_request(450, -1)
    app.timeline_box.set_halign(Gtk.Align.CENTER)
    center_box.append(app.timeline_box)

    app.tech_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=4)
    # Keep a stable reserved slot so playback start/stop does not shift controls.
    app.tech_box.set_size_request(-1, 22)
    app.bp_label = None
    app.lbl_tech = Gtk.Label(label="", ellipsize=3, visible=True)
    app.tech_box.append(app.lbl_tech)
    center_box.append(app.tech_box)

    center_panel.append(center_box)
    app.bottom_bar.set_center_widget(center_panel)

    right_panel = Gtk.Box()
    right_panel.set_hexpand(False)
    right_panel.set_halign(Gtk.Align.END)
    # Keep start/end widths symmetric so transport controls stay truly centered.
    right_panel.set_size_request(side_panel_width, -1)

    app.vol_box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
    app.vol_box.set_hexpand(False)
    app.vol_box.set_halign(Gtk.Align.END)

    app.mode_btn = Gtk.Button(icon_name=app.MODE_ICONS[app.MODE_LOOP], css_classes=["flat", "circular", "player-side-btn"])
    app.mode_btn.set_tooltip_text(app.MODE_TOOLTIPS[app.MODE_LOOP])
    app.mode_btn.connect("clicked", app.on_toggle_mode)
    app.vol_box.append(app.mode_btn)

    app.eq_btn = Gtk.Button(icon_name="eq-icon-symbolic", css_classes=["flat", "eq-btn", "player-side-btn"])
    app.eq_pop = app._build_eq_popover()
    app.eq_pop.set_parent(app.eq_btn)
    app.eq_btn.connect("clicked", lambda b: app.eq_pop.popup())
    app.vol_box.append(app.eq_btn)

    app.vol_btn = Gtk.Button(icon_name="hiresti-volume-high-symbolic", css_classes=["flat", "player-side-btn"])
    app.vol_pop = app._build_volume_popover()
    app.vol_pop.set_parent(app.vol_btn)
    app.vol_btn.connect("clicked", lambda b: app.vol_pop.popup())
    app.vol_box.append(app.vol_btn)

    right_panel.append(Gtk.Box(hexpand=True))
    right_panel.append(app.vol_box)
    app.player_right_panel = right_panel
    app.bottom_bar.set_end_widget(right_panel)

    # Start/end use content width to avoid large dead space on wide windows.
