import os
import sys
import logging
import subprocess
os.environ["MESA_LOG_LEVEL"] = "error"

_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw
from core.logging import setup_logging
from core.constants import PlayMode, LyricsSettings, AudioLatency, VisualizerSettings
from app import app_bootstrap
from app import app_diagnostics
from app import app_init_refs
from app import app_init_runtime
from app import app_state_persistence
from app import app_storage_scope

logger = logging.getLogger(__name__)

class TidalApp(Adw.Application):
    MODE_LOOP = PlayMode.LOOP
    MODE_ONE = PlayMode.ONE
    MODE_SHUFFLE = PlayMode.SHUFFLE
    MODE_SMART = PlayMode.SMART

    MODE_ICONS = PlayMode.ICONS
    MODE_TOOLTIPS = PlayMode.TOOLTIPS

    LYRICS_FONT_PRESETS = LyricsSettings.FONT_PRESETS
    LATENCY_OPTIONS = AudioLatency.OPTIONS
    LATENCY_MAP = AudioLatency.MAP
    VIZ_BAR_OPTIONS = VisualizerSettings.BAR_OPTIONS
    VIZ_BACKEND_POLICIES = VisualizerSettings.BACKEND_POLICIES

    def _init_ui_refs(self):
        return app_init_refs.init_ui_refs(self)

    def record_diag_event(self, message):
        return app_diagnostics.record_diag_event(self, message)

    def _apply_status_class(self, label, state):
        return app_diagnostics._apply_status_class(self, label, state)

    def set_diag_health(self, kind, state, detail=None):
        return app_diagnostics.set_diag_health(self, kind, state, detail)

    def show_diag_events(self, _btn=None):
        return app_diagnostics.show_diag_events(self, _btn)

    def show_output_notice(self, text, state="idle", timeout_ms=2600):
        return app_diagnostics.show_output_notice(self, text, state, timeout_ms)

    def on_output_state_transition(self, prev_state, state, detail=None):
        return app_diagnostics.on_output_state_transition(self, prev_state, state, detail)

    def _schedule_cache_maintenance(self):
        return app_storage_scope._schedule_cache_maintenance(self)

    def _account_scope_from_backend_user(self):
        return app_storage_scope._account_scope_from_backend_user(self)

    def _apply_account_scope(self, force=False):
        return app_storage_scope._apply_account_scope(self, force)

    def __init__(self):
        super().__init__(application_id="com.hiresti.player")
        app_init_runtime.init_runtime(self)

    def _detect_app_version(self):
        return app_bootstrap.detect_app_version(self)

    def save_settings(self):
        return app_state_persistence.save_settings(self)

    def schedule_save_settings(self, delay_ms=250):
        return app_state_persistence.schedule_save_settings(self, delay_ms)

    def _remember_last_nav(self, nav_id):
        return app_state_persistence._remember_last_nav(self, nav_id)

    def _remember_last_view(self, view_name):
        return app_state_persistence._remember_last_view(self, view_name)

    def _save_search_history(self):
        return app_state_persistence._save_search_history(self)

    # Keep vfunc overrides on the class body; GTK/GApplication does not treat
    # late monkey-patched methods as virtual overrides.
    def do_shutdown(self):
        return app_bootstrap.do_shutdown(self)

    def _restore_runtime_state(self):
        return app_bootstrap._restore_runtime_state(self)

    def do_activate(self):
        return app_bootstrap.do_activate(self)

    def _build_player_bar(self, container):
        from ui import builders as ui_builders

        ui_builders.build_player_bar(self, container)

from app.app_wiring import wire_tidal_app

wire_tidal_app(TidalApp)

if __name__ == "__main__":
    setup_logging()
    try:
        git_rev = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.5,
            ).strip()
        )
    except Exception:
        git_rev = "unknown"
    logger.info("Starting HiresTI build: git_rev=%s", git_rev)
    TidalApp().run(None)
