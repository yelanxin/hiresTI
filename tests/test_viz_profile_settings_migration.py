import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.settings import CURRENT_SETTINGS_VERSION, DEFAULT_SETTINGS, normalize_settings


def test_viz_profile_defaults_to_dynamic_after_gentle_insert():
    assert CURRENT_SETTINGS_VERSION == 4
    assert DEFAULT_SETTINGS["viz_profile"] == 2


def test_viz_profile_migration_shifts_legacy_indices_by_one():
    assert normalize_settings({"settings_version": 3, "viz_profile": 0})["viz_profile"] == 1
    assert normalize_settings({"settings_version": 3, "viz_profile": 1})["viz_profile"] == 2
    assert normalize_settings({"settings_version": 3, "viz_profile": 3})["viz_profile"] == 4


def test_viz_profile_accepts_new_gentle_slot():
    assert normalize_settings({"settings_version": 4, "viz_profile": 0})["viz_profile"] == 0
