import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.settings import CURRENT_SETTINGS_VERSION, normalize_settings


def test_viz_effect_migration_maps_removed_pro_effects():
    assert CURRENT_SETTINGS_VERSION == 4

    assert normalize_settings({"settings_version": 2, "viz_effect": 14})["viz_effect"] == 0
    assert normalize_settings({"settings_version": 2, "viz_effect": 15})["viz_effect"] == 1
    assert normalize_settings({"settings_version": 2, "viz_effect": 16})["viz_effect"] == 14


def test_viz_effect_migration_still_handles_pre_v2_shift():
    assert normalize_settings({"settings_version": 1, "viz_effect": 15})["viz_effect"] == 0
    assert normalize_settings({"settings_version": 1, "viz_effect": 17})["viz_effect"] == 14


def test_viz_effect_accepts_new_appended_effects():
    assert normalize_settings({"settings_version": 3, "viz_effect": 15})["viz_effect"] == 15
    assert normalize_settings({"settings_version": 3, "viz_effect": 16})["viz_effect"] == 16
    assert normalize_settings({"settings_version": 4, "viz_effect": 17})["viz_effect"] == 17
    assert normalize_settings({"settings_version": 4, "viz_effect": 18})["viz_effect"] == 18
    assert normalize_settings({"settings_version": 4, "viz_effect": 19})["viz_effect"] == 19
    assert normalize_settings({"settings_version": 4, "viz_effect": 20})["viz_effect"] == 20
    assert normalize_settings({"settings_version": 4, "viz_effect": 21})["viz_effect"] == 21
    assert normalize_settings({"settings_version": 4, "viz_effect": 22})["viz_effect"] == 22
    assert normalize_settings({"settings_version": 4, "viz_effect": 23})["viz_effect"] == 23
