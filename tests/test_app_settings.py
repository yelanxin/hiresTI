import json

from app_settings import DEFAULT_SETTINGS, load_settings, normalize_settings, save_settings


def test_normalize_settings_coerces_and_applies_dependency():
    raw = {
        "driver": "",
        "device": "USB DAC",
        "bit_perfect": False,
        "exclusive_lock": True,
        "latency_profile": "Low Latency (40ms)",
    }
    out = normalize_settings(raw)
    assert out["driver"] == DEFAULT_SETTINGS["driver"]
    assert out["device"] == "USB DAC"
    assert out["latency_profile"] == "Low Latency (40ms)"
    assert out["exclusive_lock"] is False


def test_load_settings_invalid_file_returns_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not-json", encoding="utf-8")
    loaded = load_settings(str(path))
    assert loaded == DEFAULT_SETTINGS


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    data = {
        "driver": "ALSA",
        "device": "hw:0,0",
        "bit_perfect": True,
        "exclusive_lock": True,
        "latency_profile": "Aggressive (20ms)",
    }
    save_settings(str(path), data)
    loaded = load_settings(str(path))
    assert loaded["driver"] == "ALSA"
    assert loaded["device"] == "hw:0,0"
    assert loaded["bit_perfect"] is True
    assert loaded["exclusive_lock"] is True
    assert loaded["latency_profile"] == "Aggressive (20ms)"

    saved_json = json.loads(path.read_text(encoding="utf-8"))
    assert "settings_version" in saved_json
