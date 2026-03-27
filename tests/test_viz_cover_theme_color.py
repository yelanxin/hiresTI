import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from viz.visualizer import _cover_theme_from_rgbs, _pick_cover_theme_colors


def test_cover_theme_picker_prefers_bright_color_when_coverage_is_meaningful():
    dark = [(0.08, 0.10, 0.18)] * 60
    bright = [(0.92, 0.74, 0.22)] * 28
    accent = [(0.94, 0.22, 0.18)] * 12

    colors = _pick_cover_theme_colors(dark + bright + accent)

    assert colors is not None
    r, g, b = colors["bright"]
    assert r > 0.75
    assert g > 0.55
    assert b < 0.40
    dr, dg, db = colors["dark"]
    assert dr < 0.20
    assert dg < 0.20
    assert db < 0.30


def test_cover_theme_picker_ignores_tiny_bright_patch():
    main = [(0.20, 0.68, 0.44)] * 94
    tiny = [(0.98, 0.96, 0.20)] * 6

    colors = _pick_cover_theme_colors(main + tiny)

    assert colors is not None
    r, g, b = colors["bright"]
    assert 0.12 <= r <= 0.30
    assert 0.58 <= g <= 0.78
    assert 0.34 <= b <= 0.54


def test_cover_theme_picker_selects_distinct_dark_anchor():
    dark = [(0.10, 0.12, 0.18)] * 44
    bright = [(0.82, 0.58, 0.24)] * 40
    mid = [(0.36, 0.34, 0.42)] * 16

    colors = _pick_cover_theme_colors(dark + bright + mid)

    assert colors is not None
    br, bg, bb = colors["bright"]
    dr, dg, db = colors["dark"]
    assert br > dr
    assert bg > dg
    assert bb > db


def test_cover_theme_from_rgbs_lifts_brightness_after_selection():
    theme = _cover_theme_from_rgbs(
        {
            "bright": (0.24, 0.38, 0.52),
            "dark": (0.08, 0.12, 0.18),
        },
        {"gradient": ()},
    )

    bright_stop = theme["gradient"][0][1]
    deep_stop = theme["gradient"][-1][1]

    assert bright_stop[0] > 0.45
    assert bright_stop[1] > 0.55
    assert bright_stop[2] > 0.70
    assert deep_stop[0] < 0.20
    assert deep_stop[1] < 0.24
    assert deep_stop[2] < 0.34
    assert deep_stop[2] > deep_stop[1] > deep_stop[0]


def test_cover_theme_from_rgbs_keeps_dark_tone_in_same_hue_family():
    theme = _cover_theme_from_rgbs(
        {
            "bright": (0.42, 0.66, 0.96),
            "dark": (0.18, 0.16, 0.14),
        },
        {"gradient": ()},
    )

    deep_stop = theme["gradient"][-1][1]

    assert deep_stop[2] > deep_stop[1]
    assert deep_stop[1] > deep_stop[0]
