import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ui import config as ui_config


def test_app_css_avoids_gtk_unsupported_max_size_properties():
    assert "max-height:" not in ui_config.CSS_DATA
    assert "max-width:" not in ui_config.CSS_DATA
