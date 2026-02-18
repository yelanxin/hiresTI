from lyrics_manager import LyricsManager


def test_parse_synced_lyrics():
    mgr = LyricsManager()
    text = "[00:01.00]line a\n[00:02.50]line b\n"
    mgr.load_lyrics(text)
    assert mgr.has_synced is True
    assert len(mgr.time_points) == 2
    assert mgr.get_lyric_for_time(1.2) == "line a"
    assert mgr.get_lyric_for_time(2.6) == "line b"


def test_parse_plain_text_lyrics():
    mgr = LyricsManager()
    text = "plain lyric line"
    mgr.load_lyrics(text)
    assert mgr.has_synced is False
    assert mgr.time_points == []
    assert mgr.raw_text == text
    assert mgr.get_lyric_for_time(3.0) is None


def test_empty_lyrics_resets_state():
    mgr = LyricsManager()
    mgr.load_lyrics("[00:01.00]line")
    mgr.load_lyrics("")
    assert mgr.has_synced is False
    assert mgr.time_points == []
    assert mgr.lyrics_map == {}
