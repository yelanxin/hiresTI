import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from ui import builders


def test_sidebar_nav_sections_group_discover_library_and_recent():
    sections = builders._sidebar_nav_sections()

    assert [header for header, _items in sections] == [
        "DISCOVER",
        "YOUR LIBRARY",
        "RECENT",
    ]

    discover_ids = [nav_id for nav_id, _icon, _label in sections[0][1]]
    library_ids = [nav_id for nav_id, _icon, _label in sections[1][1]]
    recent_ids = [nav_id for nav_id, _icon, _label in sections[2][1]]

    assert discover_ids == ["home", "new", "top", "hires", "genres", "decades"]
    assert library_ids == ["collection", "liked_songs", "artists", "playlists"]
    assert recent_ids == ["history"]
