import gi
import logging
import os
import sys

_viz_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'viz')
if _viz_dir not in sys.path:
    sys.path.insert(0, _viz_dir)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Adw, Pango, GLib, Gdk

from background_viz import BackgroundVisualizer
from visualizer import SpectrumVisualizer
from ui import config as ui_config

logger = logging.getLogger(__name__)
_SEARCH_HEADER_DRAG_THRESHOLD_PX = 6.0


def _build_global_share_popover(app, parent):
    pop = Gtk.Popover()
    pop.set_parent(parent)
    pop.set_has_arrow(False)
    pop.set_autohide(False)
    pop.add_css_class("playlist-more-menu")

    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=0,
        margin_top=4,
        margin_bottom=4,
        margin_start=4,
        margin_end=4,
    )
    share_btn = Gtk.Button(css_classes=["flat"])
    share_row = Gtk.Box(spacing=8)
    share_row.append(Gtk.Label(label="Share...", xalign=0))
    share_btn.set_child(share_row)
    share_btn.connect("clicked", lambda _btn: _on_global_share_clicked(app))
    box.append(share_btn)
    box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

    close_btn = Gtk.Button(css_classes=["flat"])
    close_row = Gtk.Box(spacing=8)
    close_row.append(Gtk.Label(label="Close", xalign=0))
    close_btn.set_child(close_row)
    close_btn.connect("clicked", lambda _btn: _on_global_close_clicked(app))
    box.append(close_btn)
    pop.set_child(box)
    return pop


def _popup_global_share_popover(app, x, y):
    pop = getattr(app, "global_share_popover", None)
    if pop is None:
        return
    rect = Gdk.Rectangle()
    rect.x = int(x)
    rect.y = int(y)
    rect.width = 1
    rect.height = 1
    try:
        pop.set_pointing_to(rect)
    except Exception:
        pass
    pop.popup()


def _on_global_share_clicked(app):
    pop = getattr(app, "global_share_popover", None)
    if pop is not None:
        pop.popdown()
    _suppress_search_focus(app)
    GLib.idle_add(lambda: _clear_search_focus(app))
    share = getattr(app, "_copy_share_url_to_clipboard", None)
    if callable(share):
        copied = bool(share())
        notice = getattr(app, "show_output_notice", None)
        if callable(notice):
            notice("Link copied to clipboard." if copied else "Failed to copy link.", "ok" if copied else "warn", 1800)


def _on_global_close_clicked(app):
    pop = getattr(app, "global_share_popover", None)
    if pop is not None:
        pop.popdown()
    win = getattr(app, "win", None)
    if win is not None:
        try:
            win.close()
        except Exception:
            pass


def _popover_is_visible(pop):
    if pop is None:
        return False
    getter = getattr(pop, "get_visible", None)
    if callable(getter):
        try:
            return bool(getter())
        except Exception:
            return False
    return bool(getattr(pop, "visible", False))


def _on_global_context_menu_pressed(app, gesture, x, y):
    win = getattr(app, "win", None)
    header = getattr(app, "header", None)
    hit = None
    if win is not None:
        try:
            hit = win.pick(x, y, Gtk.PickFlags.DEFAULT)
        except Exception:
            hit = None
    if header is not None and hit is not None and _widget_is_descendant(hit, header):
        return
    try:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
    except Exception:
        pass
    _clear_search_focus(app)
    _popup_global_share_popover(app, x, y)


def _setup_global_context_menu(app, parent):
    app.global_share_popover = _build_global_share_popover(app, parent)
    gesture = Gtk.GestureClick()
    gesture.set_button(Gdk.BUTTON_SECONDARY)
    gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    gesture.connect("pressed", lambda gest, _n, x, y: _on_global_context_menu_pressed(app, gest, x, y))
    parent.add_controller(gesture)
    app._global_share_gesture = gesture


def _close_search_suggestions(app):
    pop = getattr(app, "search_suggest_popover", None)
    if pop is not None:
        pop.popdown()


def _clear_search_focus(app):
    _close_search_suggestions(app)
    win = getattr(app, "win", None)
    if win is not None:
        try:
            win.set_focus(None)
        except Exception:
            pass
    return False


def _widget_is_descendant(widget, ancestor):
    cur = widget
    while cur is not None:
        if cur is ancestor:
            return True
        try:
            cur = cur.get_parent()
        except Exception:
            return False
    return False


def _widget_chain_preserves_search_focus(widget):
    cur = widget
    interactive_types = tuple(
        cls for cls in (
            getattr(Gtk, "Button", None),
            getattr(Gtk, "ToggleButton", None),
            getattr(Gtk, "CheckButton", None),
            getattr(Gtk, "Switch", None),
            getattr(Gtk, "DropDown", None),
            getattr(Gtk, "ComboBox", None),
            getattr(Gtk, "ComboBoxText", None),
            getattr(Gtk, "Entry", None),
            getattr(Gtk, "SearchEntry", None),
            getattr(Gtk, "SpinButton", None),
            getattr(Gtk, "Scale", None),
            getattr(Gtk, "TextView", None),
        )
        if cls is not None
    )
    while cur is not None:
        if interactive_types and isinstance(cur, interactive_types):
            return True
        if not isinstance(cur, Gtk.Widget):
            getter = getattr(cur, "get_focusable", None)
            if getter is not None:
                try:
                    if getter():
                        return True
                except Exception:
                    pass
        try:
            cur = cur.get_parent()
        except Exception:
            return False
    return False


def _suppress_search_focus(app, duration_ms=220):
    try:
        now_us = GLib.get_monotonic_time()
    except Exception:
        now_us = 0
    app._search_focus_suppressed_until_us = int(now_us) + (int(duration_ms) * 1000)


def _search_focus_is_suppressed(app):
    try:
        now_us = GLib.get_monotonic_time()
    except Exception:
        now_us = 0
    return int(getattr(app, "_search_focus_suppressed_until_us", 0) or 0) > int(now_us)


def _reset_search_press_state(app):
    app._search_press_active = False
    app._search_press_start_x = 0.0
    app._search_press_start_y = 0.0
    app._search_press_in_header = False
    app._search_header_dragging = False


def _check_search_suggestions_focus(app):
    app._search_suggest_focus_check_source = 0
    pop = getattr(app, "search_suggest_popover", None)
    entry = getattr(app, "search_entry", None)
    win = getattr(app, "win", None)
    if pop is None or entry is None or win is None or not pop.get_visible():
        return False
    try:
        focus = win.get_focus()
    except Exception:
        focus = None
    if focus is not None and (_widget_is_descendant(focus, entry) or _widget_is_descendant(focus, pop)):
        return False
    _close_search_suggestions(app)
    return False


def _queue_search_suggestions_focus_check(app, delay_ms=0):
    pending = int(getattr(app, "_search_suggest_focus_check_source", 0) or 0)
    if pending:
        GLib.source_remove(pending)
        app._search_suggest_focus_check_source = 0

    def _run():
        return _check_search_suggestions_focus(app)

    if int(delay_ms or 0) > 0:
        app._search_suggest_focus_check_source = GLib.timeout_add(int(delay_ms), _run)
    else:
        app._search_suggest_focus_check_source = GLib.idle_add(_run)


def _maybe_show_search_suggestions(app):
    entry = getattr(app, "search_entry", None)
    pop = getattr(app, "search_suggest_popover", None)
    if entry is None or pop is None:
        return
    if _search_focus_is_suppressed(app):
        return
    pending = int(getattr(app, "_search_suggest_focus_check_source", 0) or 0)
    if pending:
        GLib.source_remove(pending)
        app._search_suggest_focus_check_source = 0
    if not entry.get_visible() or not entry.get_sensitive():
        pop.popdown()
        return
    if not list(getattr(app, "search_history", [])):
        pop.popdown()
        return
    if hasattr(app, "render_search_history"):
        app.render_search_history()
    pop.popup()



def _on_search_entry_changed_for_suggestions(app, entry):
    if str(entry.get_text() or "").strip():
        _close_search_suggestions(app)
        return
    if entry.has_focus():
        _maybe_show_search_suggestions(app)


def _on_search_entry_focus_enter(app):
    if _search_focus_is_suppressed(app):
        GLib.idle_add(lambda: _clear_search_focus(app))
        return
    _maybe_show_search_suggestions(app)


def _click_is_on_entry(entry, win, x, y):
    try:
        ok, rect = entry.compute_bounds(win)
        if not ok or rect is None:
            return False
        return (rect.get_x() <= x <= rect.get_x() + rect.get_width() and
                rect.get_y() <= y <= rect.get_y() + rect.get_height())
    except Exception:
        hit = win.pick(x, y, Gtk.PickFlags.DEFAULT)
        return hit is not None and _widget_is_descendant(hit, entry)


def _should_track_header_drag(app, hit):
    if hit is None:
        return False
    header = getattr(app, "header", None)
    if header is None:
        return False
    if not _widget_is_descendant(hit, header):
        return False
    if _widget_chain_preserves_search_focus(hit):
        return False
    return True


def _on_window_pressed_for_dismiss(app, x, y, gesture=None):
    global_share_pop = getattr(app, "global_share_popover", None)
    pop = getattr(app, "search_suggest_popover", None)
    entry = getattr(app, "search_entry", None)
    win = getattr(app, "win", None)
    if win is None:
        return
    hit = None
    try:
        hit = win.pick(x, y, Gtk.PickFlags.DEFAULT)
    except Exception:
        hit = None
    if _popover_is_visible(global_share_pop):
        if hit is not None and _widget_is_descendant(hit, global_share_pop):
            return
        if gesture is not None:
            try:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            except Exception:
                pass
        try:
            global_share_pop.popdown()
        except Exception:
            pass
        _suppress_search_focus(app)
        GLib.idle_add(lambda: _clear_search_focus(app))
        return
    if pop is None or entry is None:
        return
    app._search_press_active = True
    app._search_press_start_x = float(x)
    app._search_press_start_y = float(y)
    app._search_press_in_header = _should_track_header_drag(app, hit)
    app._search_header_dragging = False
    if _click_is_on_entry(entry, win, x, y):
        if not pop.get_visible():
            GLib.idle_add(lambda: (_maybe_show_search_suggestions(app), False)[1])
        return
    if hit is not None and _widget_is_descendant(hit, pop):
        return
    if pop.get_visible():
        _close_search_suggestions(app)
    if not _widget_chain_preserves_search_focus(hit):
        GLib.idle_add(lambda: _clear_search_focus(app))


def _on_window_motion_for_search_focus(app, x, y):
    if not bool(getattr(app, "_search_press_active", False)):
        return
    if not bool(getattr(app, "_search_press_in_header", False)):
        return
    if bool(getattr(app, "_search_header_dragging", False)):
        return
    dx = abs(float(x) - float(getattr(app, "_search_press_start_x", 0.0) or 0.0))
    dy = abs(float(y) - float(getattr(app, "_search_press_start_y", 0.0) or 0.0))
    if dx >= _SEARCH_HEADER_DRAG_THRESHOLD_PX or dy >= _SEARCH_HEADER_DRAG_THRESHOLD_PX:
        app._search_header_dragging = True


def _on_window_released_for_search_focus(app):
    dragged = bool(getattr(app, "_search_header_dragging", False))
    _reset_search_press_state(app)
    if not dragged:
        return
    _suppress_search_focus(app)
    GLib.idle_add(lambda: _clear_search_focus(app))


def _on_window_focus_widget_changed(app):
    if _search_focus_is_suppressed(app):
        win = getattr(app, "win", None)
        entry = getattr(app, "search_entry", None)
        if win is not None and entry is not None:
            try:
                focus = win.get_focus()
            except Exception:
                focus = None
            if focus is not None and _widget_is_descendant(focus, entry):
                GLib.idle_add(lambda: _clear_search_focus(app))
                return
    _queue_search_suggestions_focus_check(app, delay_ms=10)


def _setup_window_click_dismiss(app):
    win = getattr(app, "win", None)
    if win is None:
        return
    win_click = Gtk.GestureClick()
    win_click.set_button(Gdk.BUTTON_PRIMARY)
    win_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    win_click.connect("pressed", lambda gest, _n, x, y: _on_window_pressed_for_dismiss(app, x, y, gesture=gest))
    win_click.connect("released", lambda *_args: _on_window_released_for_search_focus(app))
    win_click.connect("stopped", lambda *_args: _reset_search_press_state(app))
    win.add_controller(win_click)
    motion = Gtk.EventControllerMotion()
    motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    motion.connect("motion", lambda _ctrl, x, y: _on_window_motion_for_search_focus(app, x, y))
    win.add_controller(motion)
    app._search_dismiss_gesture = win_click
    app._search_focus_motion = motion


def _build_search_suggestions_popover(app):
    pop = Gtk.Popover()
    pop.set_parent(app.search_entry)
    pop.set_has_arrow(False)
    pop.set_autohide(False)
    pop.add_css_class("search-suggest-popover")

    try:
        pop.set_position(Gtk.PositionType.BOTTOM)
    except Exception:
        pass
    try:
        pop.set_offset(0, 8)
    except Exception:
        pass

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_propagate_natural_height(True)
    scroll.set_min_content_width(600)
    scroll.set_max_content_height(480)
    scroll.add_css_class("search-suggest-scroll")

    content = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=0,
        margin_bottom=14,
        margin_start=14,
        margin_end=14,
        css_classes=["search-suggest-content"],
    )

    history_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["search-suggest-section"])
    history_head = Gtk.Box(spacing=8)
    history_head.append(Gtk.Label(label="Recent Searches", xalign=0, css_classes=["search-suggest-title"], hexpand=True))
    clear_btn = Gtk.Button(label="Clear", css_classes=["flat"])
    clear_btn.connect("clicked", lambda _b: app.clear_search_history())
    history_head.append(clear_btn)
    history_section.append(history_head)

    history_flow = Gtk.FlowBox(
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=4,
        row_spacing=6,
        css_classes=["search-suggest-flow"],
    )
    history_flow.set_min_children_per_line(1)
    history_flow.set_max_children_per_line(100)
    history_flow.set_homogeneous(False)
    history_flow.set_hexpand(True)
    history_flow.set_halign(Gtk.Align.FILL)
    history_section.append(history_flow)
    content.append(history_section)

    app.search_history_section = history_section
    app.search_history_flow = history_flow
    app.clear_history_btn = clear_btn

    scroll.set_child(content)
    pop.set_child(scroll)
    return pop


def build_header(app, container):
    app.window_handle = Gtk.WindowHandle()
    container.append(app.window_handle)

    app.header = Adw.HeaderBar()
    app.window_handle.set_child(app.header)

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
    app.search_suggest_popover = _build_search_suggestions_popover(app)

    app.search_entry.connect("activate", lambda _entry: _close_search_suggestions(app))
    app.search_entry.connect("changed", lambda entry: _on_search_entry_changed_for_suggestions(app, entry))

    focus_controller = Gtk.EventControllerFocus()
    focus_controller.connect("enter", lambda *_args: _on_search_entry_focus_enter(app))
    focus_controller.connect("leave", lambda *_args: _queue_search_suggestions_focus_check(app))
    app.search_entry.add_controller(focus_controller)

    if getattr(app, "win", None) is not None:
        app.win.connect("notify::focus-widget", lambda *_args: _on_window_focus_widget_changed(app))
        _setup_window_click_dismiss(app)

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

    def _on_about_clicked(_btn):
        app.tools_pop.popdown()
        app.on_about_clicked(_btn)

    tools_box.append(_tool_row("hiresti-shortcuts-symbolic", "Keyboard Shortcuts", _on_shortcuts_clicked))
    tools_box.append(_tool_row("hiresti-tech-symbolic", "Signal Path / Tech Info", _on_signal_path_clicked))
    tools_box.append(_tool_row("hiresti-gear-symbolic", "Settings", _on_settings_clicked))
    tools_box.append(_tool_row("help-about-symbolic", "About", _on_about_clicked))
    app.tools_pop.set_child(tools_box)
    app.tools_btn.connect("clicked", lambda _b: app.tools_pop.popup())

    box_right.append(app.login_btn)
    box_right.append(app.mini_btn)
    box_right.append(app.tools_btn)
    app.header.pack_end(box_right)


def build_body(app, container):
    _setup_global_context_menu(app, container)

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
    app.queue_drawer_box.set_size_request(240, -1)
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
    app.queue_btn.set_size_request(23, 50)
    app.queue_btn.set_valign(Gtk.Align.CENTER)
    app.queue_btn.set_vexpand(False)
    app.queue_btn.connect("clicked", app.toggle_queue_drawer)

    app.queue_handle_shell = Gtk.Box(css_classes=["queue-handle-shell"])
    app.queue_handle_shell.set_size_request(23, 50)
    app.queue_handle_shell.set_valign(Gtk.Align.CENTER)
    app.queue_handle_shell.set_vexpand(False)
    app.queue_handle_shell.append(app.queue_btn)

    app.queue_anchor = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=0,
        halign=Gtk.Align.END,
        valign=Gtk.Align.FILL,
        hexpand=True,
        vexpand=True,
        css_classes=["queue-anchor"],
    )
    queue_gap = int(max(0, ui_config.WINDOW_HEIGHT * 0.10))
    app.queue_anchor.set_margin_top(queue_gap)
    app.queue_anchor.set_margin_bottom(queue_gap)
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

    app.viz_fullscreen_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE)
    app.viz_fullscreen_revealer.set_reveal_child(False)
    app.viz_fullscreen_revealer.set_visible(False)
    app.viz_fullscreen_revealer.set_halign(Gtk.Align.FILL)
    app.viz_fullscreen_revealer.set_valign(Gtk.Align.FILL)
    app.viz_fullscreen_revealer.set_hexpand(True)
    app.viz_fullscreen_revealer.set_vexpand(True)
    app.viz_fullscreen_revealer.add_css_class("viz-panel")
    app.viz_fullscreen_revealer.add_css_class("viz-fullscreen-revealer")
    if getattr(app, "content_overlay", None) is not None:
        app.content_overlay.add_overlay(app.viz_fullscreen_revealer)

    app.viz_btn = Gtk.Button(icon_name="hiresti-pan-up-symbolic", css_classes=["flat", "viz-handle-btn"])
    app.viz_btn.set_tooltip_text("Waveform / Lyrics")
    app.viz_btn.set_size_request(50, 23)
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
    app.viz_stack.set_size_request(-1, int(ui_config.WINDOW_HEIGHT / 3))
    app.viz_switcher.set_stack(app.viz_stack)
    app.viz_stack.connect("notify::visible-child-name", app.on_viz_page_changed)

    app.viz_surface_overlay = Gtk.Overlay()
    app.viz_surface_overlay.set_hexpand(True)
    app.viz_surface_overlay.set_vexpand(True)
    app.viz_surface_overlay.set_child(app.viz_stack)

    app.viz = SpectrumVisualizer()
    logger.info("Visualizer backend selected: cairo")
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

    effect_names = list(app.viz.get_effect_names() or [])
    if "Dots" not in effect_names:
        effect_names.append("Dots")
    logger.info("Visualizer effects available: %s", effect_names)
    app.viz_effect_dd = Gtk.DropDown(model=Gtk.StringList.new(effect_names))
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
    app.viz_theme_row = theme_row
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
    app.viz_fullscreen_btn = Gtk.Button(icon_name="view-fullscreen-symbolic", css_classes=["flat", "circular"])
    app.viz_fullscreen_btn.set_tooltip_text("Expand Waveform")
    app.viz_fullscreen_btn.connect("clicked", app.toggle_viz_fullscreen)
    app.viz_fullscreen_btn.set_halign(Gtk.Align.END)
    app.viz_fullscreen_btn.set_valign(Gtk.Align.START)
    app.viz_fullscreen_btn.set_margin_top(10)
    app.viz_fullscreen_btn.set_margin_end(10)
    app.viz_fullscreen_btn.add_css_class("viz-fullscreen-btn")
    app.viz_surface_overlay.add_overlay(app.viz_fullscreen_btn)
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

    app.viz_stack_box.append(app.viz_surface_overlay)
    app.viz_stack_box.set_size_request(-1, int(ui_config.WINDOW_HEIGHT / 3))
    app.viz_root.append(theme_row)
    app.viz_root.append(app.viz_stack_box)
    app.viz_revealer.set_child(app.viz_root)
    if hasattr(app, "_sync_viz_height_to_window"):
        app._sync_viz_height_to_window()
    app.on_viz_page_changed(app.viz_stack, None)

    app.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sidebar-shell"])
    app.nav_list = Gtk.ListBox(css_classes=["navigation-sidebar"], margin_top=10)
    app.nav_list.connect("row-activated", app.on_nav_selected)

    nav_items = [
        ("home", "hiresti-home-symbolic", "Home"),
        ("new", "starred-symbolic", "New"),
        ("top", "view-grid-symbolic", "Top"),
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
    app.track_fav_btn.set_margin_top(0)
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

    center_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        valign=Gtk.Align.CENTER,
        halign=Gtk.Align.CENTER,
        spacing=8,
    )
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
