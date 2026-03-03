import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("gi")

from actions import ui_actions


def test_home_section_header_uses_context_kicker_as_small_line():
    result = ui_actions._home_section_header_lines(
        {
            "title": "Because you liked",
            "subtitle": "",
            "section_type": "HORIZONTAL_LIST_WITH_CONTEXT",
            "context_header": {"name": "初次嚐到寂寞"},
        }
    )

    assert result == {
        "title": "初次嚐到寂寞",
        "kicker": "Because you liked",
        "secondary": "",
    }


def test_home_section_header_keeps_full_context_sentence_as_secondary():
    result = ui_actions._home_section_header_lines(
        {"title": "Recommended Tracks", "subtitle": "Because you liked Hello", "section_type": "HORIZONTAL_LIST"}
    )

    assert result == {
        "title": "Recommended Tracks",
        "kicker": "",
        "secondary": "Because you liked Hello",
    }
