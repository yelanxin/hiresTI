import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

import utils
from ui.track_table import build_tracks_header


def build_grid_view(app):
    grid_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["home-view"])
    title_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=4,
        margin_start=32,
        margin_end=32,
        margin_top=28,
        margin_bottom=10,
        css_classes=["home-topbar"],
    )
    title_row = Gtk.Box(spacing=12)
    app.grid_title_label = Gtk.Label(label="Home", xalign=0, css_classes=["section-title"])
    app.grid_subtitle_label = Gtk.Label(
        label="Fresh picks and playlists tailored to your listening",
        xalign=0,
        css_classes=["home-subtitle", "dim-label"],
    )
    app.artist_fav_btn = Gtk.Button(
        css_classes=["heart-btn"],
        icon_name="emblem-favorite-symbolic",
        visible=False,
    )
    app.artist_fav_btn.connect("clicked", app.on_artist_fav_clicked)
    title_row.append(app.grid_title_label)
    title_row.append(Gtk.Box(hexpand=True))
    title_row.append(app.artist_fav_btn)
    title_box.append(title_row)
    title_box.append(app.grid_subtitle_label)
    grid_vbox.append(title_box)

    app.login_prompt_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=20,
        valign=Gtk.Align.CENTER,
        vexpand=True,
    )
    app.login_prompt_box.set_visible(False)
    prompt_icon = Gtk.Image(icon_name="avatar-default-symbolic", pixel_size=128, css_classes=["dim-label"])
    prompt_label = Gtk.Label(label="Please login to access your Tidal collection", css_classes=["heading"])
    prompt_btn = Gtk.Button(
        label="Login to Tidal",
        css_classes=["pill", "suggested-action"],
        halign=Gtk.Align.CENTER,
    )
    prompt_btn.connect("clicked", app.on_login_clicked)
    app.login_prompt_box.append(prompt_icon)
    app.login_prompt_box.append(prompt_label)
    app.login_prompt_box.append(prompt_btn)
    grid_vbox.append(app.login_prompt_box)

    app.alb_scroll = Gtk.ScrolledWindow(vexpand=True)
    app.collection_content_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=20,
        margin_start=32,
        margin_end=32,
        margin_bottom=32,
        css_classes=["home-content-box"],
    )
    app.collection_base_margin_bottom = 32
    app.alb_scroll.set_child(app.collection_content_box)
    grid_vbox.append(app.alb_scroll)
    app.right_stack.add_named(grid_vbox, "grid_view")


def toggle_login_view(app, logged_in):
    app.login_prompt_box.set_visible(not logged_in)
    app.alb_scroll.set_visible(logged_in)
    if not logged_in:
        app.login_btn.set_label("Login")
        app.grid_title_label.set_text("Welcome")
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text("Sign in to load your personalized mixes and library picks")
        return

    display_name = "User"
    user = app.backend.user
    if user:
        meta = getattr(user, "profile_metadata", None)
        if meta:
            if isinstance(meta, dict):
                display_name = meta.get("name") or meta.get("firstName") or display_name
            else:
                display_name = getattr(meta, "name", None) or getattr(meta, "first_name", None) or display_name

        if display_name == "User" or display_name is None:
            candidates = [
                getattr(user, "first_name", None),
                getattr(user, "name", None),
                getattr(user, "firstname", None),
            ]
            for candidate in candidates:
                if candidate and isinstance(candidate, str) and candidate.strip():
                    display_name = candidate
                    break

        if (not display_name or display_name == "User") and hasattr(user, "username") and user.username:
            try:
                display_name = user.username.split("@")[0].capitalize()
            except Exception:
                display_name = user.username

    app.login_btn.set_label(f"Hi, {display_name}")
    app.grid_title_label.set_text("Home")
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text("Fresh picks and playlists tailored to your listening")


def build_tracks_view(app):
    trk_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["tracks-view"])
    trk_scroll = Gtk.ScrolledWindow(vexpand=True)
    trk_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

    app.album_header_box = Gtk.Box(spacing=24, css_classes=["album-header-box"])
    app.header_art = Gtk.Picture()
    app.header_art.set_size_request(160, 160)
    app.header_art.set_can_shrink(True)
    try:
        app.header_art.set_content_fit(Gtk.ContentFit.COVER)
    except Exception:
        pass
    app.header_art.add_css_class("header-art")

    info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
    app.header_kicker = Gtk.Label(label="Album", xalign=0, css_classes=["album-kicker"])
    app.header_title = Gtk.Label(xalign=0, wrap=True, css_classes=["album-title-large"])
    app.header_artist = Gtk.Label(xalign=0, css_classes=["album-artist-medium"])
    tap = Gtk.GestureClick()
    tap.connect("pressed", app.on_header_artist_clicked)
    app.header_artist.add_controller(tap)
    motion = Gtk.EventControllerMotion()
    motion.connect("enter", lambda c, x, y: utils.set_pointer_cursor(app.header_artist, True))
    motion.connect("leave", lambda c: utils.set_pointer_cursor(app.header_artist, False))
    app.header_artist.add_controller(motion)
    app.header_meta = Gtk.Label(xalign=0, css_classes=["album-meta", "album-meta-pill"])

    info.append(app.header_kicker)
    info.append(app.header_title)
    info.append(app.header_artist)
    info.append(app.header_meta)

    app.fav_btn = Gtk.Button(css_classes=["heart-btn"], icon_name="non-starred-symbolic", valign=Gtk.Align.CENTER)
    app.fav_btn.connect("clicked", app.on_fav_clicked)
    app.add_playlist_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn"], valign=Gtk.Align.CENTER)
    app.add_playlist_btn.set_tooltip_text("Add Album Tracks to Playlist")
    app.add_playlist_btn.connect("clicked", app.on_add_current_album_to_playlist)

    app.album_header_box.append(app.header_art)
    app.album_header_box.append(info)
    app.album_header_box.append(app.add_playlist_btn)
    app.album_header_box.append(app.fav_btn)
    trk_content.append(app.album_header_box)

    tracks_head, head_btns = build_tracks_header(
        on_sort_title=lambda _b: app.on_album_sort_clicked("title"),
        on_sort_artist=lambda _b: app.on_album_sort_clicked("artist"),
        on_sort_album=lambda _b: app.on_album_sort_clicked("album"),
        on_sort_time=lambda _b: app.on_album_sort_clicked("time"),
    )
    trk_content.append(tracks_head)
    app.album_sort_buttons = head_btns

    app.track_list = Gtk.ListBox(css_classes=["boxed-list", "tracks-list"], margin_start=32, margin_end=32, margin_bottom=32)
    app.track_list_base_margin_bottom = 32
    app.track_list.connect("row-activated", app.on_track_selected)
    trk_content.append(app.track_list)

    trk_scroll.set_child(trk_content)
    trk_vbox.append(trk_scroll)
    app.right_stack.add_named(trk_vbox, "tracks")


def build_settings_page(app):
    settings_scroll = Gtk.ScrolledWindow(vexpand=True)
    settings_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-container"], spacing=20)
    settings_scroll.set_child(settings_vbox)
    settings_vbox.append(Gtk.Label(label="Settings", xalign=0, css_classes=["album-title-large"], margin_bottom=10))

    group_q = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])
    row_q = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    row_q.append(Gtk.Label(label="Audio Quality", hexpand=True, xalign=0))
    app.quality_dd = Gtk.DropDown(
        model=Gtk.StringList.new(
            ["Max (Up to 24-bit, 192 kHz)", "High (16-bit, 44.1 kHz)", "Low (320 kbps)"]
        )
    )
    app.quality_dd.connect("notify::selected-item", app.on_quality_changed)
    row_q.append(app.quality_dd)
    group_q.append(row_q)
    settings_vbox.append(group_q)

    settings_vbox.append(Gtk.Label(label="Audio Output", xalign=0, css_classes=["section-title"], margin_top=10))
    group_out = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])

    row_bp = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    bp_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    bp_info.append(Gtk.Label(label="Bit-Perfect Mode", xalign=0, css_classes=["settings-label"]))
    bp_info.append(Gtk.Label(label="Bypass software mixer & EQ", xalign=0, css_classes=["dim-label"]))
    row_bp.append(bp_info)
    row_bp.append(Gtk.Box(hexpand=True))
    app.bp_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
    app.bp_switch.set_active(app.settings.get("bit_perfect", False))
    app.bp_switch.connect("state-set", app.on_bit_perfect_toggled)
    row_bp.append(app.bp_switch)
    group_out.append(row_bp)

    row_ex = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    ex_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    title_box = Gtk.Box(spacing=6, orientation=Gtk.Orientation.HORIZONTAL)
    title_box.append(Gtk.Label(label="Force Hardware Exclusive", xalign=0, css_classes=["settings-label"]))
    help_btn = Gtk.Button(icon_name="dialog-question-symbolic", css_classes=["flat", "circular"])
    help_btn.set_tooltip_text("Click for details")
    help_pop = Gtk.Popover()
    help_pop.set_parent(help_btn)
    help_pop.set_autohide(True)
    pop_content = Gtk.Label(wrap=True, max_width_chars=40, xalign=0)
    pop_content.set_markup(
        "<b>Exclusive Mode Control</b>\n\n"
        "<b>⚠️ Recommendation:</b>\nOnly enable this for <b>External USB DACs</b>.\n\n"
        "• <b>Benefits:</b> Ensures true Bit-Perfect playback.\n"
        "• <b>Limitations:</b> System volume DISABLED."
    )
    pop_box = Gtk.Box(margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
    pop_box.append(pop_content)
    help_pop.set_child(pop_box)
    help_btn.connect("clicked", lambda x: help_pop.popup())
    title_box.append(help_btn)
    ex_info.append(title_box)
    ex_info.append(
        Gtk.Label(
            label="Bypass and release system audio control for this device",
            xalign=0,
            css_classes=["dim-label"],
        )
    )
    row_ex.append(ex_info)
    row_ex.append(Gtk.Box(hexpand=True))
    app.ex_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
    app.ex_switch.set_sensitive(app.settings.get("bit_perfect", False))
    app.ex_switch.set_active(app.settings.get("exclusive_lock", False))
    app.ex_switch.connect("state-set", app.on_exclusive_toggled)
    row_ex.append(app.ex_switch)
    group_out.append(row_ex)

    row_lat = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    lat_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    lat_info.append(Gtk.Label(label="Output Latency", xalign=0, css_classes=["settings-label"]))
    lat_info.append(
        Gtk.Label(
            label="Target buffer size (Effective in Exclusive Mode)",
            xalign=0,
            css_classes=["dim-label"],
        )
    )
    row_lat.append(lat_info)
    row_lat.append(Gtk.Box(hexpand=True))
    app.latency_dd = Gtk.DropDown(model=Gtk.StringList.new(app.LATENCY_OPTIONS))
    app.latency_dd.set_valign(Gtk.Align.CENTER)
    app.latency_dd.set_sensitive(app.settings.get("exclusive_lock", False))

    saved_profile = app.settings.get("latency_profile", "Standard (100ms)")
    if saved_profile not in app.LATENCY_OPTIONS:
        saved_profile = "Standard (100ms)"
    try:
        target_idx = app.LATENCY_OPTIONS.index(saved_profile)
        app.latency_dd.set_selected(target_idx)
    except ValueError:
        app.latency_dd.set_selected(1)
    app.latency_dd.connect("notify::selected-item", app.on_latency_changed)
    row_lat.append(app.latency_dd)
    group_out.append(row_lat)

    row_drv = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    row_drv.append(Gtk.Label(label="Audio Driver", hexpand=True, xalign=0))
    drivers = app.player.get_drivers()
    app.driver_dd = Gtk.DropDown(model=Gtk.StringList.new(drivers))
    app.driver_dd.connect("notify::selected-item", app.on_driver_changed)
    row_drv.append(app.driver_dd)
    group_out.append(row_drv)

    row_dev = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    row_dev.append(Gtk.Label(label="Output Device", hexpand=True, xalign=0))
    app.device_dd = Gtk.DropDown(model=Gtk.StringList.new(["Default"]))
    app.device_dd.set_sensitive(False)
    app.device_dd.connect("notify::selected-item", app.on_device_changed)
    row_dev.append(app.device_dd)
    group_out.append(row_dev)

    row_state = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    row_state.append(Gtk.Label(label="Output Status", hexpand=True, xalign=0))
    app.output_status_label = Gtk.Label(label="Idle", xalign=1, css_classes=["dim-label"])
    row_state.append(app.output_status_label)
    app.output_recover_btn = Gtk.Button(label="Recover", css_classes=["flat"])
    app.output_recover_btn.connect("clicked", app.on_recover_output_clicked)
    app.output_recover_btn.set_sensitive(False)
    row_state.append(app.output_recover_btn)
    group_out.append(row_state)

    settings_vbox.append(group_out)

    settings_vbox.append(Gtk.Label(label="Diagnostics", xalign=0, css_classes=["section-title"], margin_top=10))
    group_diag = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])
    row_diag = Gtk.Box(spacing=10, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    row_diag.append(Gtk.Label(label="Runtime Health", xalign=0, hexpand=True))
    app.network_status_label = Gtk.Label(label="NET IDLE", xalign=1, css_classes=["diag-chip", "status-idle"])
    app.decoder_status_label = Gtk.Label(label="DEC IDLE", xalign=1, css_classes=["diag-chip", "status-idle"])
    app.events_btn = Gtk.Button(label="Events", css_classes=["flat"])
    row_diag.append(app.network_status_label)
    row_diag.append(app.decoder_status_label)
    row_diag.append(app.events_btn)
    group_diag.append(row_diag)
    settings_vbox.append(group_diag)

    app._diag_pop = Gtk.Popover()
    app._diag_pop.set_parent(app.events_btn)
    pop_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=8,
        margin_top=10,
        margin_bottom=10,
        margin_start=10,
        margin_end=10,
    )
    pop_box.append(Gtk.Label(label="Recent Events", xalign=0, css_classes=["settings-label"]))
    sw = Gtk.ScrolledWindow(min_content_height=180, min_content_width=540)
    app._diag_text = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    sw.set_child(app._diag_text)
    pop_box.append(sw)
    app._diag_pop.set_child(pop_box)
    app.events_btn.connect("clicked", app.show_diag_events)
    app.right_stack.add_named(settings_scroll, "settings")


def build_search_view(app):
    app.search_scroll = Gtk.ScrolledWindow(vexpand=True)
    vbox = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=24,
        margin_top=32,
        margin_bottom=32,
        margin_start=32,
        margin_end=32,
        css_classes=["home-view", "search-view"],
    )
    app.search_scroll.set_child(vbox)
    app.search_content_box = vbox
    app.search_base_margin_bottom = 32

    app.search_history_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["home-section"])
    history_head = Gtk.Box(spacing=8)
    history_head.append(Gtk.Label(label="Recent Searches", xalign=0, css_classes=["home-section-title"], hexpand=True))
    app.clear_history_btn = Gtk.Button(label="Clear", css_classes=["flat"])
    app.clear_history_btn.connect("clicked", app.clear_search_history)
    history_head.append(app.clear_history_btn)
    app.search_history_section.append(history_head)

    app.search_history_flow = Gtk.FlowBox(
        max_children_per_line=8,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=8,
        row_spacing=8,
    )
    app.search_history_section.append(app.search_history_flow)
    app.search_history_section.set_visible(False)
    vbox.append(app.search_history_section)

    app.search_status_label = Gtk.Label(xalign=0, css_classes=["dim-label", "search-status-label"])
    app.search_status_label.set_visible(False)
    vbox.append(app.search_status_label)

    app.res_art_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
    app.res_art_box.append(Gtk.Label(label="Artists", xalign=0, css_classes=["home-section-title"]))
    app.res_art_flow = Gtk.FlowBox(
        max_children_per_line=10,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=24,
        row_spacing=24,
    )
    app.res_art_flow.connect("child-activated", app.on_grid_item_activated)
    app.res_art_box.append(app.res_art_flow)
    vbox.append(app.res_art_box)

    app.res_alb_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
    app.res_alb_box.append(Gtk.Label(label="Albums", xalign=0, css_classes=["home-section-title"]))
    app.res_alb_flow = Gtk.FlowBox(
        max_children_per_line=10,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=24,
        row_spacing=24,
    )
    app.res_alb_flow.connect("child-activated", app.on_grid_item_activated)
    app.res_alb_box.append(app.res_alb_flow)
    vbox.append(app.res_alb_box)

    app.res_pl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
    app.res_pl_box.append(Gtk.Label(label="Playlists", xalign=0, css_classes=["home-section-title"]))
    app.res_pl_flow = Gtk.FlowBox(
        max_children_per_line=10,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=24,
        row_spacing=24,
    )
    app.res_pl_box.append(app.res_pl_flow)
    vbox.append(app.res_pl_box)

    app.res_hist_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
    app.res_hist_box.append(Gtk.Label(label="History Tracks", xalign=0, css_classes=["home-section-title"]))
    app.res_hist_list = Gtk.ListBox(css_classes=["boxed-list", "tracks-list", "search-tracks-list"])
    app.res_hist_list.connect("row-activated", app.on_search_history_track_selected)
    app.res_hist_box.append(app.res_hist_list)
    vbox.append(app.res_hist_box)

    app.res_trk_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
    trk_head = Gtk.Box(spacing=8)
    trk_head.append(Gtk.Label(label="Tracks", xalign=0, hexpand=True, css_classes=["home-section-title"]))
    app.add_selected_tracks_btn = Gtk.Button(label="Add Selected", css_classes=["flat", "pill"])
    app.add_selected_tracks_btn.set_sensitive(False)
    app.add_selected_tracks_btn.connect("clicked", app.on_add_selected_search_tracks)
    trk_head.append(app.add_selected_tracks_btn)
    app.res_trk_box.append(trk_head)
    app.res_trk_list = Gtk.ListBox(css_classes=["boxed-list", "tracks-list", "search-tracks-list"])
    app.res_trk_list.connect("row-activated", app.on_search_track_selected)
    app.res_trk_box.append(app.res_trk_list)
    vbox.append(app.res_trk_box)

    app.right_stack.add_named(app.search_scroll, "search_view")
