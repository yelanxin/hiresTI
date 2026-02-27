"""
System tray icon management for TidalApp.
Contains tray icon setup, window-close handling.
"""
import logging
import os

from gi.repository import GLib

try:
    import pystray
    from PIL import Image
except Exception:
    pystray = None
    Image = None

logger = logging.getLogger(__name__)

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_tray_icon_path(self):
    candidates = [
        os.path.join(_SRC_DIR, "icons", "hicolor", "64x64", "apps", "hiresti.png"),
        os.path.join(_SRC_DIR, "icons", "hicolor", "128x128", "apps", "hiresti.png"),
        os.path.join(_SRC_DIR, "icons", "hicolor", "32x32", "apps", "hiresti.png"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _show_from_tray(self, _icon=None, _item=None):
    def _show():
        if self.win is not None:
            self.win.present()
        return False
    GLib.idle_add(_show)


def _quit_from_tray(self, _icon=None, _item=None):
    def _quit():
        self._allow_window_close = True
        self.quit()
        return False
    GLib.idle_add(_quit)


def _init_tray_icon(self):
    if self._tray_ready:
        return
    if pystray is None or Image is None:
        logger.info("pystray is unavailable. Window will still hide to background on close.")
        return
    icon_path = self._get_tray_icon_path()
    if not icon_path:
        logger.info("Tray icon image not found. Skipping tray setup.")
        return
    try:
        image = Image.open(icon_path)
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._show_from_tray, default=True),
            pystray.MenuItem("Quit", self._quit_from_tray),
        )
        self._tray_icon = pystray.Icon("hiresti", image, "HiresTI", menu)
        self._tray_icon.run_detached()
        self._tray_ready = True
    except Exception as e:
        logger.warning("Failed to initialize tray icon: %s", e)
        self._tray_icon = None
        self._tray_ready = False


def _stop_tray_icon(self):
    if self._tray_icon is None:
        return
    try:
        self._tray_icon.stop()
    except Exception:
        pass
    self._tray_icon = None
    self._tray_ready = False


def on_window_close_request(self, _win):
    if self._allow_window_close:
        return False
    try:
        self._init_tray_icon()
        if not self._tray_ready:
            # No tray support (e.g. GNOME without indicator extension): close normally.
            return False
        if self.win is not None:
            self.win.hide()
        logger.info("Window hidden to background. Playback continues.")
    except Exception as e:
        logger.warning("Failed to hide window to background: %s", e)
        return False
    return True
