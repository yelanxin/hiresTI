import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.settings import CURRENT_SETTINGS_VERSION, normalize_settings


def test_normalize_settings_accepts_custom_dsp_order():
    out = normalize_settings(
        {
            "settings_version": CURRENT_SETTINGS_VERSION,
            "dsp_order": ["tube", "peq", "widener", "convolver", "tape"],
        }
    )
    assert out["dsp_order"] == ["tube", "peq", "widener", "convolver", "tape"]


def test_normalize_settings_sanitizes_invalid_dsp_order_entries():
    out = normalize_settings(
        {
            "settings_version": CURRENT_SETTINGS_VERSION,
            "dsp_order": ["tube", "tube", "bogus", "peq"],
        }
    )
    assert out["dsp_order"] == ["tube", "peq", "convolver", "tape", "widener"]


def test_normalize_settings_dedupes_lv2_slots_by_uri_and_prunes_order():
    out = normalize_settings(
        {
            "settings_version": CURRENT_SETTINGS_VERSION,
            "dsp_order": ["peq", "lv2_0", "lv2_1", "tube", "convolver", "tape", "widener"],
            "dsp_lv2_slots": [
                {"slot_id": "lv2_0", "uri": "http://example.com/plugin", "enabled": True, "port_values": {}},
                {"slot_id": "lv2_1", "uri": "http://example.com/plugin", "enabled": True, "port_values": {}},
            ],
        }
    )

    assert out["dsp_lv2_slots"] == [
        {"slot_id": "lv2_0", "uri": "http://example.com/plugin", "enabled": True, "port_values": {}}
    ]
    assert out["dsp_order"] == ["peq", "lv2_0", "tube", "convolver", "tape", "widener"]
