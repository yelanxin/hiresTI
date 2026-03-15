"""UI actions for scrobbling settings (Last.fm / ListenBrainz)."""
import logging
import subprocess
from threading import Thread

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

logger = logging.getLogger(__name__)


# ---- Last.fm ----

def on_lastfm_enabled_toggled(self, switch, state):
    self.settings["scrobble_lastfm_enabled"] = bool(state)
    self.schedule_save_settings()
    if hasattr(self, "scrobbler"):
        self.scrobbler.configure(self.settings)
    _refresh_lastfm_status_ui(self)
    return False


def on_lastfm_connect_clicked(self, btn):
    btn.set_sensitive(False)
    btn.set_label("Connecting…")

    def do():
        token = None
        if hasattr(self, "scrobbler"):
            try:
                token = self.scrobbler.get_lastfm_auth_token()
            except Exception as e:
                logger.warning("Last.fm get token failed: %s", e)
        GLib.idle_add(lambda: _on_token_received(self, token, btn))

    Thread(target=do, daemon=True).start()


def _on_token_received(self, token, connect_btn):
    connect_btn.set_sensitive(True)
    connect_btn.set_label("Connect")

    if not token:
        _show_scrobble_error(self, "Failed to get auth token from Last.fm.\nCheck your API key/secret.")
        return

    self._lastfm_pending_token = token

    # Open browser
    auth_url = ""
    if hasattr(self, "scrobbler"):
        auth_url = self.scrobbler.get_lastfm_auth_url(token)
    if auth_url:
        try:
            subprocess.Popen(["xdg-open", auth_url])
        except Exception:
            pass

    # Show confirmation dialog
    dialog = Adw.MessageDialog(
        transient_for=getattr(self, "win", None),
        heading="Authorize Last.fm",
        body=(
            "A browser window has been opened.\n\n"
            "Please authorize hiresTI on Last.fm, then click Confirm."
        ),
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("confirm", "Confirm")
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
    dialog.connect("response", lambda d, r: _on_lastfm_auth_confirmed(self, r))
    dialog.present()


def _on_lastfm_auth_confirmed(self, response):
    if response != "confirm":
        self._lastfm_pending_token = None
        return

    token = getattr(self, "_lastfm_pending_token", None)
    self._lastfm_pending_token = None
    if not token:
        return

    def do():
        session_key = None
        if hasattr(self, "scrobbler"):
            try:
                session_key = self.scrobbler.exchange_lastfm_token(token)
            except Exception as e:
                logger.warning("Last.fm exchange token failed: %s", e)
        GLib.idle_add(lambda: _on_session_key_received(self, session_key))

    Thread(target=do, daemon=True).start()


def _on_session_key_received(self, session_key):
    if session_key:
        self.settings["scrobble_lastfm_session_key"] = session_key
        self.schedule_save_settings()
        if hasattr(self, "scrobbler"):
            self.scrobbler.configure(self.settings)
        logger.info("Last.fm session key saved")
    else:
        _show_scrobble_error(
            self,
            "Authorization failed. Make sure you approved the request on Last.fm."
        )
    _refresh_lastfm_status_ui(self)


def on_lastfm_disconnect_clicked(self, btn):
    self.settings["scrobble_lastfm_session_key"] = ""
    self.settings["scrobble_lastfm_enabled"] = False
    self.schedule_save_settings()
    if hasattr(self, "scrobbler"):
        self.scrobbler.configure(self.settings)
    _refresh_lastfm_status_ui(self)

    sw = getattr(self, "scrobble_lastfm_switch", None)
    if sw is not None:
        sw.set_active(False)


def _refresh_lastfm_status_ui(self):
    lbl = getattr(self, "scrobble_lastfm_status_label", None)
    if lbl is None:
        return
    session_key = str(self.settings.get("scrobble_lastfm_session_key", "") or "")
    enabled = bool(self.settings.get("scrobble_lastfm_enabled", False))
    if session_key and enabled:
        lbl.set_text("Connected")
        lbl.remove_css_class("dim-label")
        lbl.add_css_class("success-text")
    elif session_key:
        lbl.set_text("Authorized (disabled)")
        lbl.add_css_class("dim-label")
        lbl.remove_css_class("success-text")
    else:
        lbl.set_text("Not connected")
        lbl.add_css_class("dim-label")
        lbl.remove_css_class("success-text")

    disconnect_btn = getattr(self, "scrobble_lastfm_disconnect_btn", None)
    if disconnect_btn is not None:
        disconnect_btn.set_sensitive(bool(session_key))

    connect_btn = getattr(self, "scrobble_lastfm_connect_btn", None)
    if connect_btn is not None:
        connect_btn.set_visible(not bool(session_key))


# ---- ListenBrainz ----

def on_listenbrainz_enabled_toggled(self, switch, state):
    self.settings["scrobble_listenbrainz_enabled"] = bool(state)
    self.schedule_save_settings()
    if hasattr(self, "scrobbler"):
        self.scrobbler.configure(self.settings)
    return False


def on_listenbrainz_token_saved(self, btn):
    entry = getattr(self, "scrobble_lb_token_entry", None)
    if entry is None:
        return
    token = entry.get_text().strip()
    self.settings["scrobble_listenbrainz_token"] = token
    self.schedule_save_settings()
    if hasattr(self, "scrobbler"):
        self.scrobbler.configure(self.settings)
    lbl = getattr(self, "scrobble_lb_status_label", None)
    if lbl is not None:
        lbl.set_text("Token saved" if token else "No token")


# ---- Helpers ----

def _show_scrobble_error(self, message: str):
    dialog = Adw.MessageDialog(
        transient_for=getattr(self, "win", None),
        heading="Scrobbling Error",
        body=message,
    )
    dialog.add_response("ok", "OK")
    dialog.present()


def init_scrobble_settings_ui(self):
    """Sync scrobbling settings UI to current settings values. Call after build."""
    sw = getattr(self, "scrobble_lastfm_switch", None)
    if sw is not None:
        sw.set_active(bool(self.settings.get("scrobble_lastfm_enabled", False)))

    lb_sw = getattr(self, "scrobble_lb_switch", None)
    if lb_sw is not None:
        lb_sw.set_active(bool(self.settings.get("scrobble_listenbrainz_enabled", False)))

    lb_token = getattr(self, "scrobble_lb_token_entry", None)
    if lb_token is not None:
        lb_token.set_text(str(self.settings.get("scrobble_listenbrainz_token", "") or ""))

    _refresh_lastfm_status_ui(self)
