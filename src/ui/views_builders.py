import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from app.app_remote_control import REMOTE_ACCESS_MODES
import utils
from ui.track_table import build_tracks_header, append_header_action_spacers


def build_grid_view(app):
    content_max_width = 1180
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
        xalign=1.0,
        ellipsize=3,
        max_width_chars=56,
        hexpand=True,
        halign=Gtk.Align.END,
        css_classes=["home-subtitle", "dim-label"],
    )
    app.artist_fav_btn = Gtk.Button(
        css_classes=["heart-btn"],
        icon_name="hiresti-favorite-symbolic",
        visible=False,
    )
    app.artist_fav_btn.connect("clicked", app.on_artist_fav_clicked)
    title_row.append(app.grid_title_label)
    title_row.append(Gtk.Box(hexpand=True))
    title_row.append(app.grid_subtitle_label)
    title_row.append(app.artist_fav_btn)
    title_box.append(title_row)
    top_clamp = Adw.Clamp(maximum_size=content_max_width, tightening_threshold=920)
    top_clamp.set_child(title_box)
    grid_vbox.append(top_clamp)

    app.login_prompt_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=20,
        hexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.CENTER,
        vexpand=True,
    )
    app.login_prompt_box.set_visible(False)
    prompt_card = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=12,
        margin_bottom=12,
        margin_start=18,
        margin_end=18,
        halign=Gtk.Align.CENTER,
        css_classes=["login-hero-card"],
    )
    # Avoid forcing a hard minimum width; small windows (e.g. mini mode / narrow
    # restored width) can otherwise trigger GtkStack measure warnings.
    prompt_card.set_size_request(-1, -1)
    prompt_icon = Gtk.Image(
        icon_name="hiresti",
        pixel_size=104,
        css_classes=["dim-label", "login-hero-icon"],
        halign=Gtk.Align.CENTER,
    )
    prompt_label = Gtk.Label(
        label="Please login to access your TIDAL collection",
        css_classes=["heading", "login-hero-title"],
        wrap=True,
        justify=Gtk.Justification.CENTER,
        xalign=0.5,
    )
    prompt_sub = Gtk.Label(
        label="Open TIDAL authentication to load your personalized home, library, and mixes.",
        css_classes=["dim-label", "login-hero-subtitle"],
        wrap=True,
        justify=Gtk.Justification.CENTER,
        xalign=0.5,
    )
    prompt_btn = Gtk.Button(
        label="Login to Tidal",
        css_classes=["pill", "suggested-action", "login-hero-btn"],
        halign=Gtk.Align.CENTER,
    )
    prompt_btn.set_size_request(220, 46)
    prompt_btn.connect("clicked", app.on_login_clicked)
    prompt_card.append(prompt_icon)
    prompt_card.append(prompt_label)
    prompt_card.append(prompt_sub)
    prompt_card.append(prompt_btn)
    app.login_prompt_box.append(prompt_card)
    grid_vbox.append(app.login_prompt_box)

    app.alb_scroll = Gtk.ScrolledWindow(vexpand=True)
    app.collection_content_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=20,
        margin_start=20,
        margin_end=20,
        margin_bottom=32,
        css_classes=["home-content-box"],
    )
    app.collection_base_margin_bottom = 32
    content_clamp = Adw.Clamp(maximum_size=content_max_width, tightening_threshold=920)
    content_clamp.set_child(app.collection_content_box)
    app.alb_scroll.set_child(content_clamp)
    grid_vbox.append(app.alb_scroll)
    app.right_stack.add_named(grid_vbox, "grid_view")


def toggle_login_view(app, logged_in):
    app.login_prompt_box.set_visible(not logged_in)
    app.alb_scroll.set_visible(logged_in)
    if hasattr(app, "search_entry") and app.search_entry is not None:
        app.search_entry.set_visible(logged_in)
    if hasattr(app, "sidebar_box") and app.sidebar_box is not None:
        app.sidebar_box.set_visible(logged_in)
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
    trk_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=32, margin_end=32)

    app.album_header_box = Gtk.Box(spacing=24, css_classes=["album-header-box"])
    app.header_art = Gtk.Picture()
    app.header_art.set_size_request(utils.COVER_SIZE, utils.COVER_SIZE)
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

    app.fav_btn = Gtk.Button(css_classes=["flat", "album-fav-btn"], icon_name="hiresti-favorite-outline-symbolic", valign=Gtk.Align.CENTER)
    app.fav_btn.connect("clicked", app.on_fav_clicked)
    app.add_playlist_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn"], valign=Gtk.Align.CENTER)
    app.add_playlist_btn.set_tooltip_text("Add Album Tracks to Playlist")
    app.add_playlist_btn.connect("clicked", app.on_add_current_album_to_playlist)
    app.remote_playlist_edit_btn = Gtk.Button(icon_name="document-edit-symbolic", css_classes=["flat", "circular", "history-scroll-btn"], valign=Gtk.Align.CENTER)
    app.remote_playlist_edit_btn.set_tooltip_text("Edit Playlist")
    app.remote_playlist_edit_btn.set_visible(False)
    app.remote_playlist_edit_btn.connect("clicked", lambda _b: app.on_remote_playlist_rename_clicked())
    app.remote_playlist_visibility_btn = Gtk.Button(icon_name="changes-prevent-symbolic", css_classes=["flat", "circular", "history-scroll-btn"], valign=Gtk.Align.CENTER)
    app.remote_playlist_visibility_btn.set_tooltip_text("Set public/private")
    app.remote_playlist_visibility_btn.set_visible(False)
    app.remote_playlist_visibility_btn.connect("clicked", lambda _b: app.on_remote_playlist_toggle_public_clicked())
    app.remote_playlist_more_btn = Gtk.Button(icon_name="open-menu-symbolic", css_classes=["flat", "circular", "history-scroll-btn"], valign=Gtk.Align.CENTER)
    app.remote_playlist_more_btn.set_tooltip_text("More")
    app.remote_playlist_more_btn.set_visible(False)
    app.remote_playlist_more_pop = Gtk.Popover()
    app.remote_playlist_more_pop.set_parent(app.remote_playlist_more_btn)
    more_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=0,
        margin_top=4,
        margin_bottom=4,
        margin_start=4,
        margin_end=4,
        css_classes=["playlist-more-menu"],
    )
    # Edit Playlist
    edit_menu_btn = Gtk.Button(css_classes=["flat"])
    edit_menu_row = Gtk.Box(spacing=8)
    edit_menu_row.append(Gtk.Image.new_from_icon_name("document-edit-symbolic"))
    edit_menu_row.append(Gtk.Label(label="Edit Playlist", xalign=0))
    edit_menu_btn.set_child(edit_menu_row)
    edit_menu_btn.connect("clicked", lambda _b: (app.remote_playlist_more_pop.popdown(), app.on_remote_playlist_rename_clicked()))
    more_box.append(edit_menu_btn)
    # Toggle Visibility
    vis_menu_btn = Gtk.Button(css_classes=["flat"])
    vis_menu_row = Gtk.Box(spacing=8)
    app._vis_menu_icon = Gtk.Image.new_from_icon_name("changes-prevent-symbolic")
    app._vis_menu_label = Gtk.Label(label="Make Public", xalign=0)
    vis_menu_row.append(app._vis_menu_icon)
    vis_menu_row.append(app._vis_menu_label)
    vis_menu_btn.set_child(vis_menu_row)
    vis_menu_btn.connect("clicked", lambda _b: (app.remote_playlist_more_pop.popdown(), app.on_remote_playlist_toggle_public_clicked()))
    more_box.append(vis_menu_btn)
    # Add to Playlist
    add_menu_btn = Gtk.Button(css_classes=["flat"])
    add_menu_row = Gtk.Box(spacing=8)
    add_menu_row.append(Gtk.Image.new_from_icon_name("list-add-symbolic"))
    add_menu_row.append(Gtk.Label(label="Add to Playlist", xalign=0))
    add_menu_btn.set_child(add_menu_row)
    add_menu_btn.connect("clicked", lambda _b: (app.remote_playlist_more_pop.popdown(), app.on_add_current_album_to_playlist()))
    more_box.append(add_menu_btn)
    more_box.append(Gtk.Separator())
    # Move to Folder
    move_btn = Gtk.Button(css_classes=["flat"])
    move_row = Gtk.Box(spacing=8)
    move_row.append(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
    move_row.append(Gtk.Label(label="Move to Folder", xalign=0))
    move_btn.set_child(move_row)
    move_btn.connect("clicked", lambda _b: (app.remote_playlist_more_pop.popdown(), app.on_remote_playlist_move_to_folder_clicked()))
    more_box.append(move_btn)
    del_btn = Gtk.Button(css_classes=["flat"])
    del_row = Gtk.Box(spacing=8)
    del_row.append(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
    del_row.append(Gtk.Label(label="Delete Playlist", xalign=0))
    del_btn.set_child(del_row)
    del_btn.connect("clicked", lambda _b: (app.remote_playlist_more_pop.popdown(), app.on_remote_playlist_delete_clicked()))
    more_box.append(del_btn)
    app.remote_playlist_more_pop.set_child(more_box)
    app.remote_playlist_more_btn.connect("clicked", lambda _b: app.remote_playlist_more_pop.popup())

    app.album_action_btns_box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER, css_classes=["album-action-btns"])
    app.album_action_btns_box.append(app.remote_playlist_more_btn)
    app.album_action_btns_box.append(app.fav_btn)
    app.album_action_btns_box.append(app.add_playlist_btn)

    app.album_header_box.append(app.header_art)
    app.album_header_box.append(info)
    app.album_header_box.append(app.album_action_btns_box)
    trk_content.append(app.album_header_box)

    tracks_head, head_btns = build_tracks_header(
        on_sort_title=lambda _b: app.on_album_sort_clicked("title"),
        on_sort_artist=lambda _b: app.on_album_sort_clicked("artist"),
        on_sort_album=lambda _b: app.on_album_sort_clicked("album"),
        on_sort_time=lambda _b: app.on_album_sort_clicked("time"),
    )
    append_header_action_spacers(tracks_head, ["fav", "add"])
    trk_content.append(tracks_head)
    app.album_sort_buttons = head_btns

    app.track_list = Gtk.ListBox(css_classes=["tracks-list"], margin_start=0, margin_end=0, margin_bottom=32)
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

    row_rebind = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    rebind_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    rebind_info.append(Gtk.Label(label="Auto Rebind Once", xalign=0, css_classes=["settings-label"]))
    rebind_info.append(
        Gtk.Label(
            label="When a disconnected device returns, auto switch back one time",
            xalign=0,
            css_classes=["dim-label"],
        )
    )
    row_rebind.append(rebind_info)
    row_rebind.append(Gtk.Box(hexpand=True))
    app.auto_rebind_once_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
    app.auto_rebind_once_switch.set_active(bool(app.settings.get("output_auto_rebind_once", False)))
    app.auto_rebind_once_switch.connect("state-set", app.on_auto_rebind_once_toggled)
    row_rebind.append(app.auto_rebind_once_switch)
    group_out.append(row_rebind)

    settings_vbox.append(group_out)

    settings_vbox.append(Gtk.Label(label="Remote Control", xalign=0, css_classes=["section-title"], margin_top=10))
    group_remote = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-group"])

    row_remote_enable = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    remote_enable_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    remote_enable_info.append(Gtk.Label(label="Enable Remote Control", xalign=0, css_classes=["settings-label"]))
    remote_enable_info.append(
        Gtk.Label(
            label="Expose playback and queue control over HTTP JSON-RPC",
            xalign=0,
            css_classes=["dim-label"],
        )
    )
    row_remote_enable.append(remote_enable_info)
    row_remote_enable.append(Gtk.Box(hexpand=True))
    app.remote_api_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
    app.remote_api_switch.connect("state-set", app.on_remote_api_enabled_toggled)
    row_remote_enable.append(app.remote_api_switch)
    group_remote.append(row_remote_enable)

    row_remote_mode = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    mode_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    mode_info.append(Gtk.Label(label="Access Mode", xalign=0, css_classes=["settings-label"]))
    mode_info.append(
        Gtk.Label(
            label="Local only is for same-machine clients. LAN is for another device on your network.",
            xalign=0,
            css_classes=["dim-label"],
            wrap=True,
        )
    )
    row_remote_mode.append(mode_info)
    row_remote_mode.append(Gtk.Box(hexpand=True))
    app.remote_api_access_dd = Gtk.DropDown(model=Gtk.StringList.new(REMOTE_ACCESS_MODES))
    app.remote_api_access_dd.connect("notify::selected-item", app.on_remote_api_access_mode_changed)
    row_remote_mode.append(app.remote_api_access_dd)
    group_remote.append(row_remote_mode)

    row_remote_network = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    app.remote_api_network_row = row_remote_network
    network_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    network_info.append(Gtk.Label(label="Network Binding", xalign=0, css_classes=["settings-label"]))
    network_info.append(
        Gtk.Label(
            label="Configure the bind address and port. Apply is required before changes take effect.",
            xalign=0,
            css_classes=["dim-label"],
            wrap=True,
        )
    )
    row_remote_network.append(network_info)
    network_controls = Gtk.Box(spacing=8, hexpand=True, halign=Gtk.Align.END)
    app.remote_api_bind_entry = Gtk.Entry(placeholder_text="0.0.0.0")
    app.remote_api_bind_entry.set_width_chars(13)
    network_controls.append(app.remote_api_bind_entry)
    app.remote_api_port_spin = Gtk.SpinButton.new_with_range(1, 65535, 1)
    app.remote_api_port_spin.set_numeric(True)
    app.remote_api_port_spin.set_width_chars(6)
    network_controls.append(app.remote_api_port_spin)
    app.remote_api_apply_btn = Gtk.Button(label="Apply", css_classes=["flat"])
    app.remote_api_apply_btn.connect("clicked", app.on_remote_api_apply_network_settings)
    network_controls.append(app.remote_api_apply_btn)
    row_remote_network.append(network_controls)
    group_remote.append(row_remote_network)

    row_remote_allow = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    app.remote_api_allowlist_row = row_remote_allow
    allow_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    allow_info.append(Gtk.Label(label="Allowed Clients", xalign=0, css_classes=["settings-label"]))
    allow_info.append(
        Gtk.Label(
            label="Optional CIDRs, e.g. 192.168.1.0/24 or 192.168.1.50/32",
            xalign=0,
            css_classes=["dim-label"],
        )
    )
    row_remote_allow.append(allow_info)
    row_remote_allow.append(Gtk.Box(hexpand=True))
    app.remote_api_allowlist_entry = Gtk.Entry(placeholder_text="192.168.1.0/24, 192.168.1.50/32")
    app.remote_api_allowlist_entry.set_width_chars(28)
    row_remote_allow.append(app.remote_api_allowlist_entry)
    group_remote.append(row_remote_allow)

    row_remote_endpoint = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    row_remote_endpoint.append(Gtk.Label(label="MCP Endpoint", xalign=0, css_classes=["settings-label"]))
    row_remote_endpoint.append(Gtk.Box(hexpand=True))
    endpoint_controls = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    app.remote_api_endpoint_label = Gtk.Label(label="", xalign=1, css_classes=["dim-label"])
    app.remote_api_endpoint_label.set_selectable(True)
    endpoint_controls.append(app.remote_api_endpoint_label)
    app.remote_api_endpoint_copy_btn = Gtk.Button(label="Copy", css_classes=["flat"])
    app.remote_api_endpoint_copy_btn.connect("clicked", app.on_remote_api_copy_endpoint_clicked)
    endpoint_controls.append(app.remote_api_endpoint_copy_btn)
    row_remote_endpoint.append(endpoint_controls)
    group_remote.append(row_remote_endpoint)

    row_remote_rpc_endpoint = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    row_remote_rpc_endpoint.append(Gtk.Label(label="RPC Endpoint", xalign=0, css_classes=["settings-label"]))
    row_remote_rpc_endpoint.append(Gtk.Box(hexpand=True))
    rpc_endpoint_controls = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    app.remote_api_rpc_endpoint_label = Gtk.Label(label="", xalign=1, css_classes=["dim-label"])
    app.remote_api_rpc_endpoint_label.set_selectable(True)
    rpc_endpoint_controls.append(app.remote_api_rpc_endpoint_label)
    app.remote_api_rpc_endpoint_copy_btn = Gtk.Button(label="Copy", css_classes=["flat"])
    app.remote_api_rpc_endpoint_copy_btn.connect("clicked", app.on_remote_api_copy_rpc_endpoint_clicked)
    rpc_endpoint_controls.append(app.remote_api_rpc_endpoint_copy_btn)
    row_remote_rpc_endpoint.append(rpc_endpoint_controls)
    group_remote.append(row_remote_rpc_endpoint)

    row_remote_status = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    row_remote_status.append(Gtk.Label(label="Status", xalign=0, css_classes=["settings-label"]))
    row_remote_status.append(Gtk.Box(hexpand=True))
    app.remote_api_status_label = Gtk.Label(label="Stopped", xalign=1, css_classes=["dim-label"])
    app.remote_api_status_label.set_selectable(True)
    row_remote_status.append(app.remote_api_status_label)
    group_remote.append(row_remote_status)

    row_remote_key = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
    key_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    key_info.append(Gtk.Label(label="API Key", xalign=0, css_classes=["settings-label"]))
    key_info.append(
        Gtk.Label(
            label="Use this bearer token from OpenClaw or the MCP bridge.",
            xalign=0,
            css_classes=["dim-label"],
        )
    )
    row_remote_key.append(key_info)
    key_controls = Gtk.Box(spacing=8, hexpand=True, halign=Gtk.Align.END)
    app.remote_api_key_entry = Gtk.Entry(editable=False, hexpand=True)
    app.remote_api_key_entry.set_width_chars(32)
    key_controls.append(app.remote_api_key_entry)
    app.remote_api_copy_btn = Gtk.Button(label="Copy", css_classes=["flat"])
    app.remote_api_copy_btn.connect("clicked", app.on_remote_api_copy_key_clicked)
    key_controls.append(app.remote_api_copy_btn)
    app.remote_api_generate_btn = Gtk.Button(label="Generate Key", css_classes=["flat"])
    app.remote_api_generate_btn.connect("clicked", app.on_remote_api_generate_key_clicked)
    key_controls.append(app.remote_api_generate_btn)
    row_remote_key.append(key_controls)
    group_remote.append(row_remote_key)

    settings_vbox.append(group_remote)

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
    if hasattr(app, "_refresh_remote_api_settings_ui"):
        app._refresh_remote_api_settings_ui()
    app.right_stack.add_named(settings_scroll, "settings")


def build_search_view(app):
    content_max_width = 1180
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
    search_clamp = Adw.Clamp(maximum_size=content_max_width, tightening_threshold=920)
    search_clamp.set_child(vbox)
    app.search_scroll.set_child(search_clamp)
    app.search_content_box = vbox
    app.search_base_margin_bottom = 32

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
    app.res_art_box.set_visible(False)
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
    app.res_alb_box.set_visible(False)
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
    app.res_pl_box.set_visible(False)
    vbox.append(app.res_pl_box)

    app.res_trk_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
    trk_head = Gtk.Box(spacing=8)
    trk_head.append(Gtk.Label(label="Tracks", xalign=0, hexpand=True, css_classes=["home-section-title"]))
    app.search_tracks_page_label = Gtk.Label(label="Page 1/1", css_classes=["dim-label"], valign=Gtk.Align.CENTER)
    trk_head.append(app.search_tracks_page_label)
    app.search_prev_page_btn = Gtk.Button(label="Prev", css_classes=["flat"])
    app.search_prev_page_btn.set_sensitive(False)
    app.search_prev_page_btn.connect("clicked", app.on_search_tracks_prev_page)
    trk_head.append(app.search_prev_page_btn)
    app.search_next_page_btn = Gtk.Button(label="Next", css_classes=["flat"])
    app.search_next_page_btn.set_sensitive(False)
    app.search_next_page_btn.connect("clicked", app.on_search_tracks_next_page)
    trk_head.append(app.search_next_page_btn)
    app.like_selected_tracks_btn = Gtk.Button(label="Like Selected", css_classes=["flat", "pill"])
    app.like_selected_tracks_btn.set_sensitive(False)
    app.like_selected_tracks_btn.connect("clicked", app.on_like_selected_search_tracks)
    trk_head.append(app.like_selected_tracks_btn)
    app.add_selected_tracks_btn = Gtk.Button(label="Add Selected", css_classes=["flat", "pill"])
    app.add_selected_tracks_btn.set_sensitive(False)
    app.add_selected_tracks_btn.connect("clicked", app.on_add_selected_search_tracks)
    trk_head.append(app.add_selected_tracks_btn)
    app.res_trk_box.append(trk_head)
    app.res_trk_list = Gtk.ListBox(css_classes=["boxed-list", "tracks-list", "search-tracks-list"])
    app.res_trk_list.connect("row-activated", app.on_search_track_selected)
    app.res_trk_box.append(app.res_trk_list)
    app.res_trk_box.set_visible(False)
    vbox.append(app.res_trk_box)

    app.right_stack.add_named(app.search_scroll, "search_view")
