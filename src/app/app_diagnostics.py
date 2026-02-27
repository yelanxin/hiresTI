"""Diagnostics and output-status helpers delegated from main.py."""

import time
from threading import current_thread, main_thread

from gi.repository import GLib

from actions import audio_settings_actions
from core.constants import DiagEvents


def record_diag_event(self, message):
    if current_thread() is not main_thread():
        GLib.idle_add(self.record_diag_event, message)
        return
    ts = time.strftime("%H:%M:%S")
    self._diag_events.append(f"{ts} | {message}")
    if len(self._diag_events) > DiagEvents.MAX_ENTRIES:
        self._diag_events = self._diag_events[-DiagEvents.MAX_ENTRIES:]
    if self._diag_text is not None:
        combined = list(getattr(self.player, "event_log", [])) + self._diag_events
        buf = self._diag_text.get_buffer()
        buf.set_text("\n".join(combined[-DiagEvents.MAX_ENTRIES:]))


def _apply_status_class(self, label, state):
    if label is None:
        return
    class_map = {
        "ok": "status-active",
        "warn": "status-fallback",
        "error": "status-error",
        "idle": "status-idle",
        "switching": "status-switching",
    }
    for cls in ("status-active", "status-fallback", "status-error", "status-switching", "status-idle"):
        label.remove_css_class(cls)
    label.add_css_class(class_map.get(state, "status-idle"))


def set_diag_health(self, kind, state, detail=None):
    if current_thread() is not main_thread():
        GLib.idle_add(self.set_diag_health, kind, state, detail)
        return
    if kind not in self._diag_health:
        return
    prev = self._diag_health.get(kind)
    self._diag_health[kind] = state
    if prev != state:
        text = f"{kind.upper()} -> {state.upper()}"
        if detail:
            text = f"{text} ({detail})"
        self.record_diag_event(text)
    if kind == "network" and self.network_status_label is not None:
        self.network_status_label.set_text(f"NET {state.upper()}")
        self._apply_status_class(self.network_status_label, state)
    if kind == "decoder" and self.decoder_status_label is not None:
        self.decoder_status_label.set_text(f"DEC {state.upper()}")
        self._apply_status_class(self.decoder_status_label, state)


def show_diag_events(self, _btn=None):
    if self._diag_pop is None or self._diag_text is None:
        return
    combined = list(getattr(self.player, "event_log", [])) + self._diag_events
    buf = self._diag_text.get_buffer()
    buf.set_text("\n".join(combined[-DiagEvents.MAX_ENTRIES:]) if combined else "No events yet.")
    self._diag_pop.popup()


def show_output_notice(self, text, state="idle", timeout_ms=2600):
    if not text or self.output_notice_revealer is None or self.output_notice_label is None:
        return
    self.output_notice_label.set_text(str(text))
    icon_map = {
        "switching": "hiresti-tech-symbolic",
        "ok": "emblem-ok-symbolic",
        "warn": "dialog-warning-symbolic",
        "error": "dialog-error-symbolic",
        "idle": "hiresti-tech-symbolic",
    }
    if self.output_notice_icon is not None:
        self.output_notice_icon.set_from_icon_name(icon_map.get(state, "hiresti-tech-symbolic"))
    chip = self.output_notice_revealer.get_child()
    if chip is not None:
        for cls in ("output-notice-ok", "output-notice-warn", "output-notice-error", "output-notice-switching"):
            chip.remove_css_class(cls)
        class_map = {
            "ok": "output-notice-ok",
            "warn": "output-notice-warn",
            "error": "output-notice-error",
            "switching": "output-notice-switching",
        }
        cls = class_map.get(state)
        if cls:
            chip.add_css_class(cls)
    self.output_notice_revealer.set_reveal_child(True)
    if self._output_notice_source:
        GLib.source_remove(self._output_notice_source)
        self._output_notice_source = 0

    def _hide_notice():
        self._output_notice_source = 0
        if self.output_notice_revealer is not None:
            self.output_notice_revealer.set_reveal_child(False)
        return False

    self._output_notice_source = GLib.timeout_add(int(timeout_ms), _hide_notice)


def on_output_state_transition(self, prev_state, state, detail=None):
    return audio_settings_actions.on_output_state_transition(self, prev_state, state, detail)
