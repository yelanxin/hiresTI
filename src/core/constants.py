"""Application constants extracted from main.py"""

class PlayMode:
    LOOP = 0
    ONE = 1
    SHUFFLE = 2
    SMART = 3

    ICONS = {
        0: "hiresti-mode-loop-symbolic",
        1: "hiresti-mode-one-symbolic",
        2: "hiresti-mode-shuffle-symbolic",
        3: "hiresti-mode-smart-symbolic"
    }

    TOOLTIPS = {
        0: "Loop All (Album/Playlist)",
        1: "Loop Single Track",
        2: "Shuffle (Randomize Order)",
        3: "Smart Shuffle (Algorithm)"
    }


class LyricsSettings:
    FONT_PRESETS = ["Live", "Studio", "Compact"]


class AudioLatency:
    OPTIONS = ["Safe (400ms)", "Standard (100ms)", "Low Latency (40ms)", "Aggressive (20ms)"]
    MAP = {
        "Safe (400ms)":      (400, 40),
        "Standard (100ms)":  (100, 10),
        "Low Latency (40ms)": (40, 4),
        "Aggressive (20ms)": (20, 2)
    }


class AlsaMmapRealtimePriority:
    DEFAULT_LABEL = "Recommended (60)"
    DEFAULT_VALUE = 60
    OPTIONS = ["Off", "Low (40)", "Recommended (60)", "High (70)", "Very High (80)"]
    MAP = {
        "Off": 0,
        "Low (40)": 40,
        "Recommended (60)": 60,
        "High (70)": 70,
        "Very High (80)": 80,
    }


class VisualizerSettings:
    BAR_OPTIONS = [4, 8, 16, 32, 48, 64, 128, 256, 512]
    BACKEND_POLICIES = ["Quality"]


class CacheSettings:
    DEFAULT_MAX_MB = 300
    DEFAULT_MAX_DAYS = 30
    DEFAULT_AUDIO_TRACKS = 20


class LikedTracksCache:
    TTL_SEC = 300.0  # 5 minutes; fav toggles bypass TTL via force=True


class VizWarmup:
    DURATION_S = 2.0


class DiagEvents:
    MAX_ENTRIES = 120
