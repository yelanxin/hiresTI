"""Scrobbler service for Last.fm and ListenBrainz.

Handles "now playing" notifications and scrobble submissions.
Last.fm scrobble rules: track played >= 30s AND (>= 50% of duration OR >= 4 min).
"""
import hashlib
import json
import logging
import time
from threading import Thread
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
LISTENBRAINZ_API_URL = "https://api.listenbrainz.org/1/submit-listens"
_HTTP_TIMEOUT = 10


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _lastfm_sign(params: dict, secret: str) -> str:
    keys = sorted(k for k in params if k != "format")
    sig_str = "".join(f"{k}{params[k]}" for k in keys)
    sig_str += secret
    return _md5(sig_str)


def _lastfm_post(params: dict) -> dict:
    params = dict(params)
    params["format"] = "json"
    data = urlencode(params).encode("utf-8")
    req = Request(LASTFM_API_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        logger.warning("Last.fm request failed: %s", e)
        return {}
    except Exception as e:
        logger.warning("Last.fm request error: %s", e)
        return {}


def _listenbrainz_post(token: str, payload: dict) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = Request(LISTENBRAINZ_API_URL, data=data, method="POST")
    req.add_header("Authorization", f"Token {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return resp.status == 200
    except URLError as e:
        logger.warning("ListenBrainz request failed: %s", e)
        return False
    except Exception as e:
        logger.warning("ListenBrainz request error: %s", e)
        return False


class ScrobblerService:
    """Manages scrobbling to Last.fm and/or ListenBrainz."""

    def __init__(self):
        self._lastfm_enabled = False
        self._lastfm_api_key = ""
        self._lastfm_api_secret = ""
        self._lastfm_session_key = ""
        self._listenbrainz_enabled = False
        self._listenbrainz_token = ""

        # Current track scrobble state
        self._scrobble_track = None
        self._scrobble_start_time = 0
        self._scrobble_sent = False

    def configure(self, settings: dict):
        """Update service configuration from app settings dict."""
        self._lastfm_enabled = bool(settings.get("scrobble_lastfm_enabled", False))
        self._lastfm_api_key = str(settings.get("scrobble_lastfm_api_key", "") or "")
        self._lastfm_api_secret = str(settings.get("scrobble_lastfm_api_secret", "") or "")
        self._lastfm_session_key = str(settings.get("scrobble_lastfm_session_key", "") or "")
        self._listenbrainz_enabled = bool(settings.get("scrobble_listenbrainz_enabled", False))
        self._listenbrainz_token = str(settings.get("scrobble_listenbrainz_token", "") or "")

    @property
    def lastfm_active(self) -> bool:
        return bool(
            self._lastfm_enabled
            and self._lastfm_api_key
            and self._lastfm_api_secret
            and self._lastfm_session_key
        )

    @property
    def listenbrainz_active(self) -> bool:
        return bool(self._listenbrainz_enabled and self._listenbrainz_token)

    @property
    def any_active(self) -> bool:
        return self.lastfm_active or self.listenbrainz_active

    @staticmethod
    def _extract_track_info(track) -> tuple:
        """Returns (title, artist, album, duration_secs)."""
        title = str(getattr(track, "name", "") or "")
        artist_obj = getattr(track, "artist", None)
        artist = str(getattr(artist_obj, "name", "") or "") if artist_obj else ""
        album_obj = getattr(track, "album", None)
        album = str(getattr(album_obj, "name", "") or "") if album_obj else ""
        duration = int(getattr(track, "duration", 0) or 0)
        return title, artist, album, duration

    def on_track_started(self, track):
        """Call when a new track begins playing. Sends 'now playing' notification."""
        self._scrobble_sent = False
        self._scrobble_track = track
        self._scrobble_start_time = int(time.time())

        if not self.any_active:
            return

        title, artist, album, duration = self._extract_track_info(track)
        if not title or not artist:
            return

        Thread(
            target=self._notify_now_playing,
            args=(title, artist, album, duration),
            daemon=True,
        ).start()

    def check_scrobble(self, position_s: float, duration_s: float):
        """Call from UI loop. Submits scrobble when threshold is reached.

        Threshold: position >= 30s AND position >= min(duration * 0.5, 240s).
        """
        if self._scrobble_sent or self._scrobble_track is None:
            return
        if not self.any_active:
            return
        if duration_s <= 0 or position_s < 30.0:
            return

        threshold = min(duration_s * 0.5, 240.0)
        if position_s < threshold:
            return

        track = self._scrobble_track
        start_ts = self._scrobble_start_time
        self._scrobble_sent = True

        def do():
            title, artist, album, duration = self._extract_track_info(track)
            if title and artist:
                self._do_scrobble(title, artist, album, duration, start_ts)

        Thread(target=do, daemon=True).start()

    def _notify_now_playing(self, title: str, artist: str, album: str, duration: int):
        if self.lastfm_active:
            params = {
                "method": "track.updateNowPlaying",
                "track": title,
                "artist": artist,
                "album": album,
                "api_key": self._lastfm_api_key,
                "sk": self._lastfm_session_key,
            }
            if duration > 0:
                params["duration"] = str(duration)
            params["api_sig"] = _lastfm_sign(params, self._lastfm_api_secret)
            result = _lastfm_post(params)
            if result.get("error"):
                logger.warning("Last.fm now playing error %s: %s", result.get("error"), result.get("message"))
            else:
                logger.debug("Last.fm now playing sent: %s - %s", artist, title)

        if self.listenbrainz_active:
            payload = {
                "listen_type": "playing_now",
                "payload": [{
                    "track_metadata": {
                        "artist_name": artist,
                        "track_name": title,
                        "release_name": album,
                    }
                }],
            }
            ok = _listenbrainz_post(self._listenbrainz_token, payload)
            if ok:
                logger.debug("ListenBrainz playing_now sent: %s - %s", artist, title)

    def _do_scrobble(self, title: str, artist: str, album: str, duration: int, timestamp: int):
        if self.lastfm_active:
            params = {
                "method": "track.scrobble",
                "track[0]": title,
                "artist[0]": artist,
                "album[0]": album,
                "timestamp[0]": str(timestamp),
                "api_key": self._lastfm_api_key,
                "sk": self._lastfm_session_key,
            }
            if duration > 0:
                params["duration[0]"] = str(duration)
            params["api_sig"] = _lastfm_sign(params, self._lastfm_api_secret)
            result = _lastfm_post(params)
            if result.get("error"):
                logger.warning("Last.fm scrobble error %s: %s", result.get("error"), result.get("message"))
            else:
                logger.info("Last.fm scrobbled: %s - %s", artist, title)

        if self.listenbrainz_active:
            payload = {
                "listen_type": "single",
                "payload": [{
                    "listened_at": timestamp,
                    "track_metadata": {
                        "artist_name": artist,
                        "track_name": title,
                        "release_name": album,
                    },
                }],
            }
            ok = _listenbrainz_post(self._listenbrainz_token, payload)
            if ok:
                logger.info("ListenBrainz scrobbled: %s - %s", artist, title)

    # ---- Last.fm auth helpers ----

    def get_lastfm_auth_token(self) -> str | None:
        """Step 1: Get a short-lived token to start the auth flow."""
        if not self._lastfm_api_key or not self._lastfm_api_secret:
            return None
        params = {
            "method": "auth.getToken",
            "api_key": self._lastfm_api_key,
        }
        params["api_sig"] = _lastfm_sign(params, self._lastfm_api_secret)
        result = _lastfm_post(params)
        return result.get("token")

    def get_lastfm_auth_url(self, token: str) -> str:
        """Step 2: URL to open in browser for user to authorize."""
        return f"https://www.last.fm/api/auth/?api_key={self._lastfm_api_key}&token={token}"

    def exchange_lastfm_token(self, token: str) -> str | None:
        """Step 3: Exchange authorized token for a permanent session key."""
        if not self._lastfm_api_key or not self._lastfm_api_secret:
            return None
        params = {
            "method": "auth.getSession",
            "api_key": self._lastfm_api_key,
            "token": token,
        }
        params["api_sig"] = _lastfm_sign(params, self._lastfm_api_secret)
        result = _lastfm_post(params)
        session = result.get("session")
        if isinstance(session, dict):
            return session.get("key")
        return None
