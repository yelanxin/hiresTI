"""UI actions for DSP preset management."""
import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

logger = logging.getLogger(__name__)


def refresh_dsp_preset_list(self):
    """Rebuild the preset dropdown model from the preset manager."""
    mgr = getattr(self, "dsp_preset_mgr", None)
    dd = getattr(self, "dsp_preset_dd", None)
    if mgr is None or dd is None:
        return
    names = mgr.list_presets()
    model = Gtk.StringList.new(names if names else ["(no presets)"])
    dd.set_model(model)
    dd.set_sensitive(bool(names))
    load_btn = getattr(self, "dsp_preset_load_btn", None)
    del_btn = getattr(self, "dsp_preset_delete_btn", None)
    if load_btn is not None:
        load_btn.set_sensitive(bool(names))
    if del_btn is not None:
        del_btn.set_sensitive(bool(names))


def on_dsp_preset_save_clicked(self, btn):
    """Show a dialog to enter a preset name, then save."""
    dialog = Adw.MessageDialog(
        transient_for=getattr(self, "win", None),
        heading="Save DSP Preset",
        body="Enter a name for this preset:",
    )
    name_entry = Gtk.Entry(placeholder_text="My Preset", width_chars=28)
    name_entry.set_margin_top(8)
    name_entry.set_margin_bottom(4)
    dialog.set_extra_child(name_entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("save", "Save")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

    def on_response(d, response):
        if response != "save":
            return
        name = name_entry.get_text().strip()
        if not name:
            return
        mgr = getattr(self, "dsp_preset_mgr", None)
        if mgr is None:
            return
        ok = mgr.save_preset(name, self.settings)
        if ok:
            refresh_dsp_preset_list(self)
            # Select the newly saved preset
            dd = getattr(self, "dsp_preset_dd", None)
            if dd is not None:
                names = mgr.list_presets()
                if name in names:
                    dd.set_selected(names.index(name))
        else:
            err = Adw.MessageDialog(
                transient_for=getattr(self, "win", None),
                heading="Cannot Save Preset",
                body=f"Preset limit reached (max {20}) or name is empty.",
            )
            err.add_response("ok", "OK")
            err.present()

    dialog.connect("response", on_response)
    dialog.present()


def on_dsp_preset_load_clicked(self, btn):
    """Load the selected preset and apply it to the player."""
    mgr = getattr(self, "dsp_preset_mgr", None)
    dd = getattr(self, "dsp_preset_dd", None)
    if mgr is None or dd is None:
        return

    selected = dd.get_selected_item()
    if selected is None:
        return
    name = selected.get_string()
    if not name or name == "(no presets)":
        return

    preset = mgr.load_preset(name)
    if preset is None:
        return

    # Apply preset values into app.settings
    self.settings.update(preset)
    self.schedule_save_settings()

    # Apply to player
    _apply_dsp_preset_to_player(self, preset)

    if hasattr(self, "show_output_notice"):
        self.show_output_notice(f"DSP preset loaded: {name}", "info", 2500)


def on_dsp_preset_delete_clicked(self, btn):
    """Confirm and delete the selected preset."""
    mgr = getattr(self, "dsp_preset_mgr", None)
    dd = getattr(self, "dsp_preset_dd", None)
    if mgr is None or dd is None:
        return

    selected = dd.get_selected_item()
    if selected is None:
        return
    name = selected.get_string()
    if not name or name == "(no presets)":
        return

    dialog = Adw.MessageDialog(
        transient_for=getattr(self, "win", None),
        heading="Delete Preset",
        body=f'Delete preset "{name}"?',
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("delete", "Delete")
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

    def on_response(d, response):
        if response == "delete":
            mgr.delete_preset(name)
            refresh_dsp_preset_list(self)

    dialog.connect("response", on_response)
    dialog.present()


def _apply_dsp_preset_to_player(self, preset: dict):
    """Push all DSP settings from a preset dict to the player."""
    p = self.player

    # Master DSP enabled
    try:
        p.set_dsp_enabled(bool(preset.get("dsp_enabled", True)))
    except Exception:
        pass

    # DSP order
    order = preset.get("dsp_order")
    if order and hasattr(p, "set_dsp_order"):
        try:
            p.set_dsp_order(list(order))
        except Exception:
            pass

    # PEQ
    try:
        bands = list(preset.get("dsp_peq_bands") or [])
        while len(bands) < 10:
            bands.append(0.0)
        for idx, gain in enumerate(bands[:10]):
            p.set_eq_band(idx, float(gain))
        p.set_peq_enabled(bool(preset.get("dsp_peq_enabled", False)))
        self.eq_band_values = bands[:10]
    except Exception:
        pass

    # Convolver
    path = str(preset.get("dsp_convolver_path", "") or "").strip()
    if path and hasattr(p, "load_convolver_ir"):
        try:
            loaded = bool(p.load_convolver_ir(path))
        except Exception:
            loaded = False
        if loaded:
            try:
                mix = int(preset.get("dsp_convolver_mix", 100) or 100)
                delay = int(preset.get("dsp_convolver_pre_delay_ms", 0) or 0)
                p.set_convolver_mix(mix / 100.0)
                p.set_convolver_pre_delay(float(delay))
                p.set_convolver_enabled(bool(preset.get("dsp_convolver_enabled", False)))
            except Exception:
                pass

    # Resampler
    try:
        p.set_resampler_quality(int(preset.get("dsp_resampler_quality", 10) or 10))
        rate = int(preset.get("dsp_resampler_target_rate", 0) or 0)
        if rate > 0 and hasattr(p, "set_resampler_target_rate"):
            p.set_resampler_target_rate(rate)
        p.set_resampler_enabled(bool(preset.get("dsp_resampler_enabled", False)))
    except Exception:
        pass

    # Tape
    try:
        p.set_tape_drive(int(preset.get("dsp_tape_drive", 30) or 30))
        p.set_tape_tone(int(preset.get("dsp_tape_tone", 60) or 60))
        p.set_tape_warmth(int(preset.get("dsp_tape_warmth", 40) or 40))
        p.set_tape_enabled(bool(preset.get("dsp_tape_enabled", False)))
    except Exception:
        pass

    # Tube
    try:
        p.set_tube_drive(int(preset.get("dsp_tube_drive", 28) or 28))
        p.set_tube_bias(int(preset.get("dsp_tube_bias", 55) or 55))
        p.set_tube_sag(int(preset.get("dsp_tube_sag", 18) or 18))
        p.set_tube_air(int(preset.get("dsp_tube_air", 52) or 52))
        p.set_tube_enabled(bool(preset.get("dsp_tube_enabled", False)))
    except Exception:
        pass

    # Widener
    try:
        p.set_widener_width(int(preset.get("dsp_widener_width", 125) or 125))
        p.set_widener_bass_mono_freq(int(preset.get("dsp_widener_bass_mono_freq", 120) or 120))
        p.set_widener_bass_mono_amount(int(preset.get("dsp_widener_bass_mono_amount", 100) or 100))
        p.set_widener_enabled(bool(preset.get("dsp_widener_enabled", False)))
    except Exception:
        pass

    # Limiter
    try:
        threshold = int(preset.get("dsp_limiter_threshold", 85) or 85)
        ratio = int(preset.get("dsp_limiter_ratio", 20) or 20)
        p.set_limiter_threshold(float(threshold) / 100.0)
        p.set_limiter_ratio(float(ratio))
        p.set_limiter_enabled(bool(preset.get("dsp_limiter_enabled", False)))
    except Exception:
        pass

    # LV2 slots
    lv2_slots = preset.get("dsp_lv2_slots") or []
    if lv2_slots and hasattr(p, "lv2_restore_slots"):
        try:
            p.lv2_restore_slots(lv2_slots)
        except Exception:
            pass
