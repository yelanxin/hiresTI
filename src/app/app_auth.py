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

# Optional embedded browser for the PKCE redirect-capture path.  When
# WebKitGTK 6.0 introspection (`gir1.2-webkit-6.0` / `webkitgtk-6.0`)
# is present we open the Tidal login page inside the app, intercept
# the redirect to `tidal.com/android/login/auth?code=...` directly,
# and skip the manual copy-paste step entirely.  When it's missing we
# fall through to the paste-URL dialog so the auth flow still works.
try:
    gi.require_version('WebKit', '6.0')
    from gi.repository import WebKit  # noqa: F401
    _WEBKIT_AVAILABLE = True
except (ValueError, ImportError):
    WebKit = None
    _WEBKIT_AVAILABLE = False

# Disable WebKitGTK's bwrap-based sandbox before the first WebView
# spawns its network/web process. Default-on sandboxing requires
# xdg-dbus-proxy + bwrap + a working user-namespace setup; on hosts
# where any of those is broken (Ubuntu kernel with userns disabled,
# AppArmor restricting unprivileged_userns_clone, dbus-proxy build
# missing the .service file, dbus-proxy itself launching but exiting
# non-zero) the WebView crashes the whole process with a SIGTRAP
# the moment its first page load tries to set up the sandbox — the
# C-side abort isn't catchable from Python. Issue #65 surfaced this
# on Ubuntu 24.04 even with `xdg-dbus-proxy` 0.1.5 installed.
#
# Sandbox-off keeps WebKit's seamless redirect interception (no
# copy-paste) while making the dbus-proxy + bwrap chain irrelevant.
# Trade-off: web content runs at the app process's privilege level;
# we only ever load Tidal's login pages here, so the surface is
# acceptable.
if _WEBKIT_AVAILABLE:
    try:
        WebKit.WebContext.get_default().set_sandbox_enabled(False)
        logging.getLogger(__name__).debug(
            "WebKit sandbox disabled to avoid xdg-dbus-proxy / bwrap dependency"
        )
    except Exception as _e:
        # If the API surface ever changes (WebKit 7+) we'd rather log and
        # move on than refuse to launch the app entirely. The PKCE path
        # has its own paste-URL fallback that still works.
        logging.getLogger(__name__).warning(
            "Could not disable WebKit sandbox: %s — PKCE may crash on hosts "
            "with broken xdg-dbus-proxy/bwrap setups", _e,
        )

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

    pkce_btn = Gtk.Button(css_classes=["flat"])
    pkce_row = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
    pkce_row.append(Gtk.Image.new_from_icon_name("audio-x-generic-symbolic"))
    pkce_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    pkce_text.append(Gtk.Label(label="HiFi Login (PKCE)", xalign=0))
    pkce_text.append(Gtk.Label(
        label="Required for full LOSSLESS / HI-RES",
        xalign=0,
        css_classes=["dim-label"],
        wrap=True,
        max_width_chars=44,
    ))
    pkce_row.append(pkce_text)
    pkce_btn.set_child(pkce_row)

    actions.append(web_btn)
    actions.append(qr_btn)
    actions.append(pkce_btn)
    root.append(actions)

    cancel_btn = Gtk.Button(label="Cancel", css_classes=["flat"])
    cancel_btn.connect("clicked", lambda _b: dialog.close())
    root.append(cancel_btn)

    web_btn.connect("clicked", lambda _b: (dialog.close(), self._start_login_flow("web")))
    qr_btn.connect("clicked", lambda _b: (dialog.close(), self._start_login_flow("qr")))
    pkce_btn.connect("clicked", lambda _b: (dialog.close(), self._start_pkce_login_flow()))

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


def _start_pkce_login_flow(self):
    """PKCE auth-code flow.  Opens the Tidal login URL in the browser,
    then shows a dialog where the user pastes the redirect URL of the
    'Oops' page they end up on after logging in.  PKCE is the only way
    to get full LOSSLESS / HI_RES streams since Tidal closed the device-
    code path for those qualities (python-tidal#404)."""
    attempt_id = int(time.time() * 1000)
    self._login_in_progress = True
    self._login_attempt_id = attempt_id
    self._login_mode = "pkce"
    logger.info("Login start (id=%s mode=pkce).", attempt_id)
    self.record_diag_event(f"AUTH START id={attempt_id} mode=pkce")

    try:
        info = self.backend.start_pkce_login()
        login_url = str((info or {}).get("url", "") or "")
        if not login_url:
            raise RuntimeError("PKCE initialization did not return a login URL")
    except Exception as e:
        self._on_login_failed(attempt_id, e)
        return

    if _WEBKIT_AVAILABLE:
        # Embedded browser path — fully automated, no copy-paste.
        self.show_output_notice(
            "Opening Tidal login in-app. Sign in to continue.",
            "ok",
            2400,
        )
        self._show_pkce_webview_dialog(login_url, attempt_id)
        return

    # Fallback: open external browser + paste-URL dialog.
    browser_ok = self._open_login_url(login_url, attempt_id)
    if browser_ok:
        self.show_output_notice(
            "Browser opened. Sign in, then copy the redirect URL back here.",
            "ok",
            3600,
        )
    else:
        self.show_output_notice(
            "Failed to open browser. Copy the URL from the dialog and open it manually.",
            "warn",
            3600,
        )

    self._show_pkce_paste_dialog(login_url, attempt_id)


def _show_pkce_webview_dialog(self, login_url, attempt_id):
    """Embedded-browser PKCE flow.  Opens Tidal's login page inside a
    WebKit.WebView and intercepts the navigation to the Android redirect
    URI to capture the auth code automatically — no copy-paste required.

    Falls back to the paste dialog when the navigation interception fails
    or the user closes the window without finishing login (covered by the
    cancel path)."""
    self._cleanup_login_dialog()

    window = Gtk.Window(title="Sign in to TIDAL", transient_for=self.win, modal=True)
    window.set_default_size(560, 760)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

    status_bar = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=10, margin_end=10)
    status_lbl = Gtk.Label(
        label="Loading TIDAL login…",
        xalign=0,
        css_classes=["dim-label"],
    )
    status_lbl.set_hexpand(True)
    status_bar.append(status_lbl)
    cancel_btn = Gtk.Button(label="Cancel", css_classes=["flat"])
    status_bar.append(cancel_btn)
    root.append(status_bar)

    # Use the default network session.  An earlier draft created a
    # fresh `WebKit.NetworkSession.new_ephemeral()` each invocation,
    # but on second open the new web process inherited a broken state
    # from the previous teardown and rendered a blank page.  The
    # default session is shared across WebViews and survives open /
    # close cycles cleanly.
    webview = WebKit.WebView()

    # Tidal's bot challenge flags WebKitGTK's default Safari UA on Linux.
    # Spoof a recent stable Chrome string so the login page loads without
    # the captcha gate.
    try:
        webview.get_settings().set_user_agent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        )
    except Exception as e:
        logger.debug("Could not override WebView user agent: %s", e)

    webview.set_hexpand(True)
    webview.set_vexpand(True)
    root.append(webview)

    submitted_marker = {"done": False}

    closed_marker = {"done": False}

    def _close_window():
        if closed_marker["done"]:
            return
        closed_marker["done"] = True
        # Drop self-reference + modal grab BEFORE destroying so any
        # signals that fire during teardown don't see a half-alive
        # window.  Stop the in-flight load so the WebKit web process
        # has a chance to release its resources cleanly.
        if self._login_dialog is window:
            self._login_dialog = None
        # Cancel the login attempt eagerly here.  Relying solely on
        # the destroy callback is racey with WebKit's web-process
        # teardown after the captcha challenge — by the time destroy
        # runs, `_login_in_progress` may not get cleared and the next
        # login click hits "Login already in progress."
        if (
            self._login_in_progress
            and attempt_id == self._login_attempt_id
            and not submitted_marker["done"]
        ):
            self._cancel_login_attempt(attempt_id, reason="user-cancel")
        try:
            window.set_modal(False)
        except Exception:
            pass
        try:
            window.set_transient_for(None)
        except Exception:
            pass
        try:
            webview.stop_loading()
        except Exception:
            pass
        try:
            window.destroy()
        except Exception:
            pass

    def _capture_redirect(redirect_url):
        if submitted_marker["done"]:
            return
        submitted_marker["done"] = True
        status_lbl.set_text("Authorization received — exchanging token…")

        def _finish_thread():
            ok = self.backend.finish_pkce_login(redirect_url)
            if ok:
                GLib.idle_add(self._on_login_success_for_attempt, attempt_id)
                GLib.idle_add(_close_window)
            else:
                msg = "PKCE login failed"
                try:
                    detail = str(getattr(self.backend, "get_last_login_error", lambda: "")() or "").strip()
                    if detail:
                        msg = detail
                except Exception:
                    pass
                GLib.idle_add(self._on_login_failed_for_attempt, attempt_id, msg)
                GLib.idle_add(_close_window)

        submit_daemon(_finish_thread)

    def _on_decide_policy(_view, decision, decision_type):
        # Only intercept top-level navigation; let sub-resources load freely.
        try:
            nav_types = (
                WebKit.PolicyDecisionType.NAVIGATION_ACTION,
                WebKit.PolicyDecisionType.NEW_WINDOW_ACTION,
            )
        except Exception:
            nav_types = ()
        if decision_type not in nav_types:
            return False
        try:
            request = decision.get_navigation_action().get_request()
            uri = request.get_uri() or ""
        except Exception as e:
            logger.debug("decide-policy: failed to read request URI: %s", e)
            return False
        # The Tidal Android client redirects to this URL with `?code=…&state=…`.
        # That's exactly what `pkce_get_auth_token()` needs.  Stop the WebView
        # before it loads the (404) target page and run the token exchange
        # ourselves.
        if "tidal.com/android/login/auth" in uri and "code=" in uri:
            decision.ignore()
            _capture_redirect(uri)
            return True
        return False

    webview.connect("decide-policy", _on_decide_policy)

    def _on_load_changed(_view, load_event):
        try:
            done = (load_event == WebKit.LoadEvent.FINISHED)
        except Exception:
            done = False
        if done and not submitted_marker["done"]:
            current = webview.get_uri() or ""
            if "tidal.com/android/login/auth" in current and "code=" in current:
                _capture_redirect(current)
            else:
                status_lbl.set_text("Sign in with your TIDAL credentials.")

    webview.connect("load-changed", _on_load_changed)

    cancel_btn.connect("clicked", lambda _b: _close_window())

    def _on_close_request(_w):
        # GDK_EVENT_PROPAGATE — let the default handler destroy the
        # window.  If we returned True the window would stay open.
        _close_window()
        return False

    def _on_destroy(_w):
        if self._login_dialog is window:
            self._login_dialog = None
        if (
            self._login_in_progress
            and attempt_id == self._login_attempt_id
            and not submitted_marker["done"]
        ):
            self._cancel_login_attempt(attempt_id, reason="user-cancel")

    window.connect("close-request", _on_close_request)
    window.connect("destroy", _on_destroy)

    # Escape closes the dialog even if Tidal's iframe has captured focus.
    esc_ctrl = Gtk.EventControllerKey()
    esc_ctrl.connect("key-pressed", lambda _c, keyval, _kc, _st: (
        _close_window() if keyval == 0xff1b else None) or False)
    window.add_controller(esc_ctrl)

    window.set_child(root)
    self._login_dialog = window
    self._login_status_label = status_lbl
    webview.load_uri(login_url)
    window.present()


def _show_pkce_paste_dialog(self, login_url, attempt_id):
    self._cleanup_login_dialog()
    dialog = Gtk.Dialog(title="Complete HiFi Login", transient_for=self.win, modal=True)
    dialog.set_default_size(560, 360)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=10,
        margin_top=12,
        margin_bottom=12,
        margin_start=14,
        margin_end=14,
    )

    title = Gtk.Label(label="Paste the 'Oops' page URL", xalign=0, css_classes=["title-3"])
    sub = Gtk.Label(
        label=(
            "1) Sign in to TIDAL in the browser tab that just opened.\n"
            "2) After login, you'll land on a page that looks like \"Oops, something went wrong\". "
            "That's expected.\n"
            "3) Copy the entire URL from the browser address bar and paste it below."
        ),
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    root.append(title)
    root.append(sub)

    # Always-visible login URL so the user can re-open / copy it if the
    # browser auto-open failed.
    url_box = Gtk.Box(spacing=6)
    url_entry = Gtk.Entry(hexpand=True)
    url_entry.set_text(login_url)
    url_entry.set_editable(False)
    url_entry.set_can_focus(True)
    copy_btn = Gtk.Button(label="Copy", css_classes=["flat"])

    def _on_copy(_b):
        try:
            self.win.get_clipboard().set(login_url)
            self.show_output_notice("Login URL copied to clipboard.", "ok", 1600)
        except Exception as e:
            logger.debug("Clipboard copy failed: %s", e)

    copy_btn.connect("clicked", _on_copy)
    url_box.append(url_entry)
    url_box.append(copy_btn)
    root.append(url_box)

    paste_label = Gtk.Label(label="Redirect URL:", xalign=0)
    root.append(paste_label)
    paste_entry = Gtk.Entry(hexpand=True)
    paste_entry.set_placeholder_text("https://tidal.com/android/login/auth?code=...")
    root.append(paste_entry)

    status_lbl = Gtk.Label(
        label="Waiting for redirect URL...",
        xalign=0,
        wrap=True,
        css_classes=["dim-label"],
    )
    root.append(status_lbl)
    self._login_status_label = status_lbl

    btn_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel", css_classes=["flat"])
    submit_btn = Gtk.Button(label="Sign In", css_classes=["suggested-action"])
    btn_row.append(cancel_btn)
    btn_row.append(submit_btn)
    root.append(btn_row)

    def _do_submit(_widget=None):
        if attempt_id != self._login_attempt_id:
            return
        url_text = paste_entry.get_text().strip()
        if not url_text or "code=" not in url_text:
            status_lbl.set_text("That doesn't look like the redirect URL. It must contain '?code='.")
            return
        submit_btn.set_sensitive(False)
        cancel_btn.set_sensitive(False)
        status_lbl.set_text("Exchanging authorization code…")

        def _finish_thread():
            ok = self.backend.finish_pkce_login(url_text)
            if ok:
                GLib.idle_add(self._on_login_success_for_attempt, attempt_id)
            else:
                msg = "PKCE login failed"
                try:
                    detail = str(getattr(self.backend, "get_last_login_error", lambda: "")() or "").strip()
                    if detail:
                        msg = detail
                except Exception:
                    pass
                GLib.idle_add(self._on_login_failed_for_attempt, attempt_id, msg)

        submit_daemon(_finish_thread)

    submit_btn.connect("clicked", _do_submit)
    paste_entry.connect("activate", _do_submit)
    cancel_btn.connect("clicked", lambda _b: dialog.close())

    dialog.set_child(root)

    def _on_close(d):
        if self._login_dialog is d:
            self._login_dialog = None
        if self._login_in_progress and attempt_id == self._login_attempt_id:
            self._cancel_login_attempt(attempt_id, reason="user-cancel")

    dialog.connect("destroy", _on_close)
    self._login_dialog = dialog
    dialog.present()
    paste_entry.grab_focus()


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
