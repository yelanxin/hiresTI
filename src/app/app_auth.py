"""Authentication/login handlers extracted from app_handlers."""

import logging
import os
import subprocess
import time
import webbrowser
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, GLib

from core.errors import classify_exception
from core.executor import submit_daemon
from ui import config as ui_config
from ui import views_builders as ui_views_builders

try:
    import qrcode
    try:
        import qrcode.image.svg as qrcode_svg
    except Exception:
        qrcode_svg = None
except Exception:
    qrcode = None
    qrcode_svg = None

logger = logging.getLogger(__name__)


def on_login_clicked(self, btn):
    if self.backend.user:
        self.user_popover.popup()
        return
    if self._login_in_progress:
        self.show_output_notice("Login already in progress.", "warn", 2200)
        if self._login_dialog is not None:
            self._login_dialog.present()
        return
    self._show_login_method_dialog()


def on_logout_clicked(self, btn):
    self.user_popover.popdown()
    self._login_in_progress = False
    self._login_attempt_id = None
    self._login_mode = None
    self._cleanup_login_dialog()
    self.backend.logout()
    self._apply_account_scope(force=True)
    self._home_sections_cache = None
    self._top_sections_cache = None
    self._new_sections_cache = None
    self._genres_definitions = None
    self._genres_tab_cache = None
    self._genres_cache_time = 0.0
    self._genres_selected_tab = ""
    self.stream_prefetch_cache.clear()
    self._toggle_login_view(False)
    self._clear_initial_search_focus()
    self.refresh_visible_track_fav_buttons()
    self.refresh_current_track_favorite_state()
    while c := self.collection_content_box.get_first_child():
        self.collection_content_box.remove(c)
    logger.info("User logged out.")


def _toggle_login_view(self, logged_in):
    self._session_restore_pending = False
    if not logged_in:
        right_stack = getattr(self, "right_stack", None)
        if right_stack is not None:
            right_stack.set_visible_child_name("grid_view")
        nav_history = getattr(self, "nav_history", None)
        if hasattr(nav_history, "clear"):
            nav_history.clear()
        back_btn = getattr(self, "back_btn", None)
        if back_btn is not None:
            back_btn.set_sensitive(False)
        artist_fav_btn = getattr(self, "artist_fav_btn", None)
        if artist_fav_btn is not None:
            artist_fav_btn.set_visible(False)
    paned = getattr(self, "paned", None)
    if paned is not None:
        if not logged_in:
            paned.set_position(0)
        else:
            win_w = (self.win.get_width() if self.win else 0) or ui_config.WINDOW_WIDTH
            sidebar_px = int(max(120, win_w * float(ui_config.SIDEBAR_RATIO)))
            paned.set_position(min(sidebar_px, max(0, win_w - 320)))
    ui_views_builders.toggle_login_view(self, logged_in)
    if paned is not None:
        if logged_in:
            GLib.idle_add(self._restore_paned_position_after_layout)
        paned.set_visible(True)
    mini_btn = getattr(self, "mini_btn", None)
    if mini_btn is not None:
        mini_btn.set_visible(bool(logged_in))
    tools_btn = getattr(self, "tools_btn", None)
    if tools_btn is not None:
        tools_btn.set_visible(bool(logged_in))
    player_overlay = getattr(self, "player_overlay", None)
    if player_overlay is not None:
        player_overlay.set_visible(bool(logged_in))
    bottom_bar = getattr(self, "bottom_bar", None)
    if bottom_bar is not None:
        bottom_bar.set_visible(bool(logged_in))
    self._set_overlay_handles_visible(bool(logged_in))
    if logged_in and hasattr(self, "_schedule_viz_handle_realign"):
        GLib.idle_add(lambda: (self._schedule_viz_handle_realign(animate=False), False)[1])
        GLib.timeout_add(160, lambda: (self._schedule_viz_handle_realign(animate=False), False)[1])


def _set_login_view_pending(self):
    self._session_restore_pending = True
    paned = getattr(self, "paned", None)
    if paned is not None:
        paned.set_visible(False)
    if hasattr(self, "login_prompt_box") and self.login_prompt_box is not None:
        self.login_prompt_box.set_visible(False)
    if hasattr(self, "alb_scroll") and self.alb_scroll is not None:
        self.alb_scroll.set_visible(False)
    if hasattr(self, "sidebar_box") and self.sidebar_box is not None:
        self.sidebar_box.set_visible(False)
    if hasattr(self, "search_entry") and self.search_entry is not None:
        self.search_entry.set_visible(False)
    mini_btn = getattr(self, "mini_btn", None)
    if mini_btn is not None:
        mini_btn.set_visible(False)
    tools_btn = getattr(self, "tools_btn", None)
    if tools_btn is not None:
        tools_btn.set_visible(False)
    player_overlay = getattr(self, "player_overlay", None)
    if player_overlay is not None:
        player_overlay.set_visible(False)
    bottom_bar = getattr(self, "bottom_bar", None)
    if bottom_bar is not None:
        bottom_bar.set_visible(False)
    self._set_overlay_handles_visible(False)


def _set_overlay_handles_visible(self, visible):
    queue_anchor = getattr(self, "queue_anchor", None)
    if queue_anchor is not None:
        queue_anchor.set_visible(bool(visible))

    viz_handle_box = getattr(self, "viz_handle_box", None)
    if viz_handle_box is not None:
        viz_handle_box.set_visible(bool(visible))

    if visible:
        return

    if hasattr(self, "hide_now_playing_overlay"):
        self.hide_now_playing_overlay()
    self.close_queue_drawer()
    revealer = getattr(self, "viz_revealer", None)
    if revealer is not None:
        self._set_visualizer_expanded(False)


def _show_login_method_dialog(self):
    self._cleanup_login_dialog()
    dialog = Gtk.Dialog(title="Choose Login Method", transient_for=self.win, modal=True)
    dialog.set_default_size(460, 250)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
    )
    title = Gtk.Label(label="Select Login Method", xalign=0)
    title.add_css_class("title-3")
    sub = Gtk.Label(
        label="Choose one method to continue with your TIDAL account authorization.",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    root.append(title)
    root.append(sub)

    actions = Gtk.Box(spacing=10, orientation=Gtk.Orientation.VERTICAL)

    web_btn = Gtk.Button(css_classes=["suggested-action"])
    web_row = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
    web_row.append(Gtk.Image.new_from_icon_name("network-workgroup-symbolic"))
    web_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    web_text.append(Gtk.Label(label="Web Login", xalign=0))
    web_text.append(Gtk.Label(label="Open browser on this device to authorize", xalign=0, css_classes=["dim-label"]))
    web_row.append(web_text)
    web_btn.set_child(web_row)

    qr_btn = Gtk.Button(css_classes=["flat"])
    qr_row = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
    qr_row.append(Gtk.Image.new_from_icon_name("camera-web-symbolic"))
    qr_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    qr_text.append(Gtk.Label(label="QR Login", xalign=0))
    qr_text.append(Gtk.Label(label="Scan QR code with your phone", xalign=0, css_classes=["dim-label"]))
    qr_row.append(qr_text)
    qr_btn.set_child(qr_row)

    actions.append(web_btn)
    actions.append(qr_btn)
    root.append(actions)

    cancel_btn = Gtk.Button(label="Cancel", css_classes=["flat"])
    cancel_btn.connect("clicked", lambda _b: dialog.close())
    root.append(cancel_btn)

    web_btn.connect("clicked", lambda _b: (dialog.close(), self._start_login_flow("web")))
    qr_btn.connect("clicked", lambda _b: (dialog.close(), self._start_login_flow("qr")))

    dialog.set_child(root)

    def _on_close(d):
        if self._login_dialog is d:
            self._login_dialog = None

    dialog.connect("destroy", _on_close)
    self._login_dialog = dialog
    dialog.present()


def _start_login_flow(self, mode):
    attempt_id = int(time.time() * 1000)
    self._login_in_progress = True
    self._login_attempt_id = attempt_id
    self._login_mode = mode
    logger.info("Login start (id=%s mode=%s).", attempt_id, mode)
    self.record_diag_event(f"AUTH START id={attempt_id} mode={mode}")

    try:
        oauth = self.backend.start_oauth()
        login_url = oauth.get("url", "")
        login_future = oauth.get("future")
        if not login_url or login_future is None:
            raise RuntimeError("OAuth initialization did not return authorization payload")
    except Exception as e:
        self._on_login_failed(attempt_id, e)
        return

    if mode == "web":
        browser_ok = self._open_login_url(login_url, attempt_id)
        if browser_ok:
            self.show_output_notice("Browser opened. Please complete login there.", "ok", 3200)
        else:
            self.show_output_notice("Failed to open browser. Please retry or use QR login.", "warn", 3600)
    else:
        shown = self._show_login_qr_dialog(oauth, attempt_id)
        if not shown:
            self._on_login_failed_for_attempt(
                attempt_id,
                "QR generation unavailable. Please install qrcode package or use web login.",
            )
            return
        self.show_output_notice("Please scan the QR code with your phone to login.", "ok", 3200)

    def login_thread():
        ok = self.backend.finish_login(login_future)
        if ok:
            GLib.idle_add(self._on_login_success_for_attempt, attempt_id)
        else:
            msg = "Authorization timed out"
            try:
                detail = str(getattr(self.backend, "get_last_login_error", lambda: "")() or "").strip()
                if detail:
                    msg = detail
            except Exception:
                pass
            GLib.idle_add(self._on_login_failed_for_attempt, attempt_id, msg)

    submit_daemon(login_thread)


def _open_login_url(self, url, attempt_id):
    opened = False
    try:
        opened = bool(webbrowser.open(url))
        logger.info(
            "Browser open result=%s (id=%s host=%s).",
            opened,
            attempt_id,
            urlparse(url).netloc,
        )
        self.record_diag_event(f"AUTH BROWSER id={attempt_id} opened={opened}")
    except Exception as e:
        logger.warning("Browser open failed (id=%s): %s", attempt_id, e)
        self.record_diag_event(f"AUTH BROWSER ERROR id={attempt_id} err={e}")
    return opened


def _cleanup_login_dialog(self):
    if self._login_dialog is not None:
        try:
            self._login_dialog.destroy()
        except Exception:
            pass
        self._login_dialog = None
    self._login_status_label = None
    if self._login_qr_tempfile:
        try:
            if os.path.exists(self._login_qr_tempfile):
                os.remove(self._login_qr_tempfile)
        except Exception as e:
            logger.debug("Failed to remove QR temp file %s: %s", self._login_qr_tempfile, e)
        self._login_qr_tempfile = None


def _cancel_login_attempt(self, attempt_id, reason="canceled"):
    if not self._login_in_progress:
        return
    if attempt_id != self._login_attempt_id:
        return
    self.record_diag_event(f"AUTH CANCELED id={attempt_id} reason={reason}")
    self._login_in_progress = False
    self._login_attempt_id = None
    self._login_mode = None
    self._cleanup_login_dialog()
    self.show_output_notice("Login canceled.", "warn", 1800)


def _build_qr_tempfile(self, url, attempt_id):
    if not url:
        logger.error("QR generation aborted: empty login url (id=%s).", attempt_id)
        return None

    base_path = os.path.join(GLib.get_tmp_dir(), f"hiresti-login-qr-{attempt_id}")
    svg_path = f"{base_path}.svg"
    png_path = f"{base_path}.png"

    if _build_qr_svg(url, svg_path):
        return svg_path
    if _build_qr_png(url, png_path):
        return png_path
    if _build_qr_with_qrencode(url, png_path):
        return png_path
    return None


def _build_qr_svg(url, path):
    if not qrcode or not qrcode_svg:
        return False
    try:
        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(image_factory=qrcode_svg.SvgPathImage)
        img.save(path)
        _ensure_svg_white_background(path)
        return True
    except Exception as e:
        logger.debug("SVG QR generation failed for %s: %s", path, e)
        return False


def _ensure_svg_white_background(path):
    tree = ET.parse(path)
    root = tree.getroot()
    ns_end = root.tag.find("}")
    ns = root.tag[1:ns_end] if root.tag.startswith("{") and ns_end > 0 else ""
    rect_tag = f"{{{ns}}}rect" if ns else "rect"

    for child in root:
        if child.tag == rect_tag and child.attrib.get("fill") == "white":
            return

    if ns:
        ET.register_namespace("", ns)

    bg = ET.Element(
        rect_tag,
        {
            "width": "100%",
            "height": "100%",
            "fill": "white",
        },
    )
    root.insert(0, bg)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _build_qr_png(url, path):
    if not qrcode:
        return False
    try:
        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(path)
        return True
    except Exception as e:
        logger.debug("PNG QR generation failed for %s: %s", path, e)
        return False


def _build_qr_with_qrencode(url, path):
    try:
        proc = subprocess.run(
            ["qrencode", "-o", path, url],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        logger.debug("qrencode fallback failed for %s: %s", path, e)
        return False

    if proc.returncode != 0:
        logger.debug(
            "qrencode returned %s for %s: %s",
            proc.returncode,
            path,
            (proc.stderr or "").strip(),
        )
        return False

    return True


def _show_login_qr_dialog(self, oauth, attempt_id):
    self._cleanup_login_dialog()
    login_url = str((oauth or {}).get("url", "") or "")
    if not login_url:
        return False

    dialog = Gtk.Dialog(title="Scan to Login", transient_for=self.win, modal=True)
    dialog.set_default_size(420, 520)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
    )

    qr_path = self._build_qr_tempfile(login_url, attempt_id)
    self._login_qr_tempfile = qr_path
    if not qr_path:
        dialog.destroy()
        return False

    pic = Gtk.Picture.new_for_filename(qr_path)
    pic.set_size_request(280, 280)
    pic.set_can_shrink(True)
    try:
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
    except Exception:
        pass

    title = Gtk.Label(label="Scan QR code with TIDAL app", css_classes=["title-3"])
    status = Gtk.Label(
        label="Waiting for authorization...",
        xalign=0.5,
        wrap=True,
        css_classes=["dim-label"],
    )
    self._login_status_label = status

    cancel_btn = Gtk.Button(label="Cancel", css_classes=["flat"])
    cancel_btn.connect("clicked", lambda _b: dialog.close())

    root.append(title)
    root.append(pic)
    root.append(status)
    root.append(cancel_btn)
    dialog.set_child(root)

    def _on_close(d):
        if self._login_dialog is d:
            self._login_dialog = None
        if self._login_in_progress and attempt_id == self._login_attempt_id:
            self._cancel_login_attempt(attempt_id, reason="user-cancel")

    dialog.connect("destroy", _on_close)
    self._login_dialog = dialog
    dialog.present()
    return True


def _on_login_success_for_attempt(self, attempt_id):
    if attempt_id != self._login_attempt_id:
        return
    self.record_diag_event(f"AUTH SUCCESS id={attempt_id}")
    if self._login_status_label is not None:
        self._login_status_label.set_text("Authorization complete, signing in...")
    self._login_in_progress = False
    self._login_attempt_id = None
    self._login_mode = None
    self._cleanup_login_dialog()
    self.on_login_success()


def _on_login_failed(self, attempt_id, exc):
    kind = classify_exception(exc)
    logger.warning("Login start failed [kind=%s id=%s]: %s", kind, attempt_id, exc)
    self.record_diag_event(f"AUTH ERROR id={attempt_id} kind={kind}")
    self._login_in_progress = False
    self._login_attempt_id = None
    self._login_mode = None
    self._cleanup_login_dialog()
    self.show_output_notice("Login start failed.", "error", 2800)


def _on_login_failed_for_attempt(self, attempt_id, message):
    if attempt_id != self._login_attempt_id:
        return
    logger.warning("Login failed (id=%s): %s", attempt_id, message)
    self.record_diag_event(f"AUTH FAILED id={attempt_id}")
    if self._login_status_label is not None:
        self._login_status_label.set_text(f"Authorization failed: {message}")
    self._login_in_progress = False
    self._login_attempt_id = None
    self._login_mode = None
    self._cleanup_login_dialog()
    self.show_output_notice("Login failed. Please retry.", "error", 2800)


def on_login_success(self):
    logger.info("Login successful.")
    self.backend._tune_http_pool()
    self._apply_account_scope(force=True)
    self.show_output_notice("Login successful.", "ok", 2000)
    self._toggle_login_view(True)
    self.refresh_visible_track_fav_buttons()
    self.refresh_current_track_favorite_state()
    self._restore_last_view()
