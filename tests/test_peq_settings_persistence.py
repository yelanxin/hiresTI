import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.settings import normalize_settings


def test_normalize_settings_keeps_peq_persistence_fields():
    out = normalize_settings(
        {
            "dsp_peq_enabled": True,
            "dsp_peq_bands": [1.5, -30, 13, "bad"],
        }
    )

    assert out["dsp_peq_enabled"] is True
    assert out["dsp_peq_bands"] == [1.5, -24.0, 12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
