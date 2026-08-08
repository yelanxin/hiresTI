#!/usr/bin/env python3
"""Minimal WebKitGTK login probe for issue #83 manual testing.

Self-contained: only needs Python + PyGObject + GTK4 + WebKitGTK (no hiresTI
app imports / pip requirements). Opens a WebView with the same GStreamer/WebKit
mitigations as app_auth.py and loads the TIDAL login page.
"""

import os
import sys

# Mirror main.py startup env before any gi/WebKit import.
os.environ.setdefault("GST_PLUGIN_FEATURE_RANK", "pipewiredeviceprovider:NONE")

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

_GST_PIPEWIRE_PROVIDER_DISABLED = False

LOGIN_URL = os.environ.get(
    "HIRESTI_PROBE_LOGIN_URL",
    "https://login.tidal.com/authorize",
)


def _disable_gst_pipewire_device_provider():
    """Demote GStreamer's PipeWire device provider before WebKit starts it."""
    global _GST_PIPEWIRE_PROVIDER_DISABLED
    if _GST_PIPEWIRE_PROVIDER_DISABLED:
        return
    try:
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        if not Gst.is_initialized():
            Gst.init(None)
        factory = Gst.DeviceProviderFactory.find("pipewiredeviceprovider")
        if factory is not None:
            factory.set_rank(Gst.Rank.NONE)
            print("Disabled GStreamer pipewiredeviceprovider.", file=sys.stderr)
        _GST_PIPEWIRE_PROVIDER_DISABLED = True
    except Exception as exc:
        print(f"pipewire provider demote skipped: {exc}", file=sys.stderr)


def _configure_login_webview_settings(settings):
    """PKCE login only needs HTML/JS + redirect capture."""
    for attr, value in (
        ("enable_webrtc", False),
        ("enable_media_stream", False),
        ("enable_webaudio", False),
        ("enable_mediasource", False),
    ):
        setter = getattr(settings, f"set_{attr}", None)
        if not callable(setter):
            continue
        try:
            setter(value)
        except Exception as exc:
            print(f"WebKit settings {attr}={value} skipped: {exc}", file=sys.stderr)


def _load_webkit():
    try:
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit

        return WebKit
    except (ValueError, ImportError) as exc:
        print(f"WebKitGTK unavailable: {exc}", file=sys.stderr)
        return None


class ProbeApp(Adw.Application):
    def do_activate(self):
        WebKit = _load_webkit()
        if WebKit is None:
            self.quit()
            return

        _disable_gst_pipewire_device_provider()

        win = Gtk.Window(title="hiresTI WebKit login probe", default_width=560, default_height=760)
        win.set_application(self)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(8)
        root.set_margin_end(8)

        status = Gtk.Label(
            label="Loading TIDAL login (WebKit probe)…",
            xalign=0,
            css_classes=["dim-label"],
        )
        root.append(status)

        try:
            webview = WebKit.WebView()
        except Exception as exc:
            status.set_label(f"WebKit.WebView() failed: {exc}")
            win.set_child(root)
            win.present()
            return

        try:
            settings = webview.get_settings()
            _configure_login_webview_settings(settings)
            settings.set_user_agent(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
            )
        except Exception as exc:
            print(f"settings configure warning: {exc}", file=sys.stderr)

        def _on_load(_view, event):
            if event == WebKit.LoadEvent.FINISHED:
                status.set_label(f"Loaded: {webview.get_uri() or LOGIN_URL}")

        webview.connect("load-changed", _on_load)
        webview.set_hexpand(True)
        webview.set_vexpand(True)
        root.append(webview)
        win.set_child(root)
        win.present()
        webview.load_uri(LOGIN_URL)


def main():
    Adw.init()
    app = ProbeApp(application_id="com.hiresti.webkit-probe")
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
