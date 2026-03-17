import tidalapi
import tidalapi.user as tidal_user
import logging
import os
import json
import time
import threading
import collections
import requests
import requests.adapters
from datetime import datetime
from urllib.parse import urlparse
from core.errors import classify_exception
from core.http_session import get_global_session
from utils.paths import get_cache_dir, get_config_dir

logger = logging.getLogger(__name__)


class TidalBackend:
    def __init__(self):
        self._normalize_tls_ca_env()
        self.session = tidalapi.Session()
        self._tune_http_pool()
        config_dir = get_config_dir()
        os.makedirs(config_dir, exist_ok=True)
        self.token_file = os.path.join(config_dir, "hiresti_token.json")
        self.legacy_token_file = os.path.join(config_dir, "hiresti_token.pkl")
        self._migrate_token_from_cache()
        self.user = None
        self.quality = self._get_best_quality()
        self._apply_global_config() 
        self.fav_album_ids = set()
        self.fav_artist_ids = set()
        self.fav_track_ids = set()
        self._cached_albums = []
        self._cached_albums_ts = 0.0
        self._albums_cache_ttl = 0.0
        self._favorite_artists_index_dirty = False
        self._artist_artwork_cache = collections.OrderedDict()  # LRU cache
        self.max_artist_artwork_cache = 500  # Limit cache size to prevent memory leak
        self._artist_artwork_inflight: dict[str, threading.Event] = {}  # per-key dedup lock
        self._artist_artwork_inflight_lock = threading.Lock()
        self._artist_placeholder_uuids = {
            "1e01cdb6-f15d-4d8b-8440-a047976c1cac",
        }
        extra_placeholder_ids = str(os.getenv("HIRESTI_ARTIST_PLACEHOLDER_UUIDS", "") or "").strip()
        if extra_placeholder_ids:
            for raw in extra_placeholder_ids.split(","):
                val = raw.strip().lower()
                if val:
                    self._artist_placeholder_uuids.add(val)
        self.lyrics_cache = collections.OrderedDict()  # LRU cache
        self.max_lyrics_cache = 300
        self._last_login_error = ""
        # Circuit breaker for unstable mix endpoint.
        self._mix_fail_until = {}
        self._session_recovery_lock = threading.Lock()
        # Set to (old_id_str, alt_track) when album fallback succeeds in get_stream_url.
        # Consumed by the app layer to update liked_tracks_data / fav_track_ids.
        self._last_track_redirect = None

    def _default_ca_bundle_candidates(self):
        candidates = [
            "/etc/ssl/certs/ca-certificates.crt",                # Debian/Ubuntu
            "/etc/pki/tls/certs/ca-bundle.crt",                  # RHEL/Fedora
            "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem", # RHEL legacy path
            "/etc/ssl/cert.pem",                                 # Alpine/macOS-style
        ]
        try:
            import certifi
            certifi_path = str(certifi.where() or "").strip()
            if certifi_path:
                candidates.insert(0, certifi_path)
        except Exception:
            pass
        return candidates

    def _resolve_existing_ca_bundle(self):
        for p in self._default_ca_bundle_candidates():
            if p and os.path.isfile(p):
                return p
        return ""

    def _normalize_tls_ca_env(self):
        """
        Fix invalid CA bundle env values inherited from host shells (for example
        an RHEL-only path on Ubuntu). requests will fail with:
        'Could not find a suitable TLS CA certificate bundle, invalid path: ...'
        """
        vars_to_check = ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE")
        invalid_vars = []
        for k in vars_to_check:
            raw = str(os.getenv(k, "") or "").strip()
            if not raw:
                continue
            if not os.path.isfile(raw):
                invalid_vars.append((k, raw))

        if not invalid_vars:
            return

        fallback = self._resolve_existing_ca_bundle()
        if fallback:
            for k, bad in invalid_vars:
                os.environ[k] = fallback
                logger.warning(
                    "Invalid %s path '%s'; using '%s' instead.",
                    k,
                    bad,
                    fallback,
                )
            return

        # Last resort: unset invalid overrides and let requests/certifi defaults work.
        for k, bad in invalid_vars:
            os.environ.pop(k, None)
            logger.warning(
                "Invalid %s path '%s'; cleared override to use default CA bundle discovery.",
                k,
                bad,
            )

    def get_last_login_error(self):
        return str(self._last_login_error or "").strip()

    def _set_last_login_error(self, message):
        self._last_login_error = str(message or "").strip()

    def _format_login_error(self, exc):
        kind = classify_exception(exc)
        etype = type(exc).__name__
        msg = str(exc or "").strip() or "(no message)"
        return f"[{kind}/{etype}] {msg}"

    def _tune_http_pool(self, session_obj=None):
        """
        Raise requests/urllib3 pool size for high-volume library fetches.
        This avoids noisy 'Connection pool is full, discarding connection' warnings
        when many background tasks hit api.tidal.com in parallel.
        """
        try:
            # Also initialize global session for helpers.py requests
            get_global_session()
        except Exception as e:
            logger.debug("Failed initializing global session: %s", e)

        try:
            # Get session from different possible locations (tidalapi may create it lazily)
            target_session = self.session if session_obj is None else session_obj
            req_obj = getattr(target_session, "request", None)
            if req_obj is None:
                logger.debug("HTTP pool tuning skipped: no request object yet")
                return
            # tidalapi.Session.request_session is the underlying requests.Session
            sess = getattr(target_session, "request_session", None)
            if sess is None:
                # Fallback: older tidalapi may embed it under request.session
                sess = getattr(req_obj, "session", None)
            if sess is None:
                logger.debug("HTTP pool tuning skipped: no session in request object yet")
                return
            pool_size = int(os.getenv("HIRESTI_HTTP_POOL_SIZE", "64") or 64)
            pool_size = max(10, min(256, pool_size))
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=pool_size,
                pool_maxsize=pool_size,
            )
            sess.mount("https://", adapter)
            sess.mount("http://", adapter)
            logger.info("HTTP pool tuned for tidalapi session: size=%s", pool_size)
        except Exception as e:
            logger.debug("Failed tuning tidalapi HTTP pool: %s", e)

    def _resolve_quality(self, candidates, fallback="LOSSLESS"):
        """
        Resolve quality across different tidalapi enum shapes:
        - new enum names: hi_res_lossless / high_lossless / low_320k ...
        - legacy names: HI_RES / LOSSLESS / HIGH ...
        """
        quality_enum = getattr(tidalapi, "Quality", None)
        cand_list = [str(c).strip() for c in list(candidates or []) if str(c).strip()]
        if quality_enum is not None:
            # 1) Match enum attribute name directly.
            for name in cand_list:
                if hasattr(quality_enum, name):
                    val = getattr(quality_enum, name)
                    if not callable(val):
                        return val

            # 2) Match enum member value string.
            try:
                members = list(quality_enum)  # enum iteration
            except Exception:
                members = []
            for name in cand_list:
                upper_name = name.upper()
                for m in members:
                    m_val = str(getattr(m, "value", m) or "")
                    if m_val.upper() == upper_name:
                        return m

        # 3) Fallback to first provided string.
        return cand_list[0] if cand_list else fallback

    def _get_best_quality(self):
        return self._resolve_quality(
            [
                "hi_res_lossless",
                "HI_RES_LOSSLESS",
                "HI_RES",
                "MASTER",
                "high_lossless",
                "LOSSLESS",
                "low_320k",
                "HIGH",
            ],
            fallback="LOSSLESS",
        )

    def _apply_global_config(self, session_obj=None):
        try:
            target_session = self.session if session_obj is None else session_obj
            if hasattr(target_session, 'config'):
                target_session.config.quality = self.quality
                if hasattr(target_session.config, 'set_quality'):
                    target_session.config.set_quality(self.quality)
        except Exception as e:
            logger.warning("Config sync warning: %s", e)

    def _apply_session_quality(self, quality, session_obj=None):
        try:
            target_session = self.session if session_obj is None else session_obj
            if hasattr(target_session, "config"):
                target_session.config.quality = quality
                if hasattr(target_session.config, "set_quality"):
                    target_session.config.set_quality(quality)
        except Exception as e:
            logger.debug("Failed to apply session quality %s: %s", quality, e)

    def _get_stream_quality_fallback_chain(self):
        """
        Keep user-selected quality as first choice, then fallback to broadly
        supported tiers when stream URL endpoint rejects higher tier.
        """
        primary = self.quality
        primary_str = str(primary or "").upper()
        chain = [primary]

        if "HI_RES" in primary_str or "MASTER" in primary_str:
            chain.append(self._resolve_quality(["high_lossless", "LOSSLESS"], fallback="LOSSLESS"))
            chain.append(self._resolve_quality(["low_320k", "HIGH"], fallback="HIGH"))
        elif "LOSSLESS" in primary_str:
            chain.append(self._resolve_quality(["low_320k", "HIGH"], fallback="HIGH"))

        # Dedupe by string representation while preserving order.
        result = []
        seen = set()
        for q in chain:
            key = str(q or "")
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(q)
        return result

    def start_oauth(self):
        self._normalize_tls_ca_env()
        self._set_last_login_error("")
        self.session = tidalapi.Session()
        self._apply_global_config()
        login_url_obj, future = self.session.login_oauth()
        verification_uri_complete = getattr(login_url_obj, "verification_uri_complete", None)
        verification_uri = getattr(login_url_obj, "verification_uri", None)
        user_code = getattr(login_url_obj, "user_code", None)

        raw_url = verification_uri_complete or verification_uri or str(login_url_obj or "")
        normalized_url, normalized = self._normalize_oauth_url(raw_url)
        if not normalized_url:
            raise RuntimeError("OAuth URL is empty")

        parsed = urlparse(normalized_url)
        logger.info(
            "OAuth URL prepared (scheme=%s host=%s normalized=%s has_user_code=%s).",
            parsed.scheme,
            parsed.netloc,
            normalized,
            bool(user_code),
        )
        return {
            "url": normalized_url,
            "future": future,
            "user_code": str(user_code or "").strip(),
            "verification_uri": str(verification_uri or "").strip(),
            "normalized": normalized,
        }

    def _normalize_oauth_url(self, url):
        raw = str(url or "").strip()
        if not raw:
            return "", False
        normalized = raw
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        elif "://" not in normalized:
            if normalized.startswith(("link.tidal.com/", "listen.tidal.com/", "tidal.com/", "www.")):
                normalized = f"https://{normalized}"
        return normalized, normalized != raw

    def finish_login(self, future):
        try:
            future.result()
            if self.session.check_login():
                self.user = self.session.user
                self._tune_http_pool()  # Ensure pool is tuned after session is ready
                self.save_session()
                self.refresh_favorite_ids()
                self._apply_global_config()
                self._set_last_login_error("")
                return True
            self._set_last_login_error("OAuth completed but session is not logged in.")
            logger.warning("Login failed: %s", self.get_last_login_error())
        except Exception as e:
            detail = self._format_login_error(e)
            self._set_last_login_error(detail)
            logger.error("Login failed: %s", detail)
        return False

    def check_login(self):
        return self.session.check_login()

    def _serialize_expiry(self, value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def _deserialize_expiry(self, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return value
        return value

    def _migrate_token_from_cache(self):
        """Move token files from the old cache location to the config dir (one-time migration)."""
        try:
            old_dir = get_cache_dir()
            new_dir = os.path.dirname(self.token_file)
            for fname in ("hiresti_token.json", "hiresti_token.pkl"):
                old_path = os.path.join(old_dir, fname)
                new_path = os.path.join(new_dir, fname)
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    os.rename(old_path, new_path)
                    logger.info("Migrated token file: %s -> %s", old_path, new_path)
        except Exception as e:
            logger.warning("Token file migration failed: %s", e)

    def save_session(self):
        os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
        data = {
            'token_type': self.session.token_type,
            'access_token': self.session.access_token,
            'refresh_token': self.session.refresh_token,
            'expiry_time': self._serialize_expiry(self.session.expiry_time),
        }
        temp_file = f"{self.token_file}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(temp_file, self.token_file)
        os.chmod(self.token_file, 0o600)
        logger.debug("Session saved to %s", self.token_file)

    def _read_saved_session_data(self):
        if os.path.exists(self.legacy_token_file) and not os.path.exists(self.token_file):
            logger.warning("Legacy token file detected (.pkl). Please login again to migrate.")
            return None

        if not os.path.exists(self.token_file):
            return None

        with open(self.token_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        required = ('token_type', 'access_token', 'refresh_token', 'expiry_time')
        if not all(k in data for k in required):
            logger.warning("Session file invalid: missing required fields.")
            return None
        return data

    def _restore_session_from_saved_data(self, data, reason="restore"):
        try:
            new_session = tidalapi.Session()
            self._apply_global_config(session_obj=new_session)
            new_session.load_oauth_session(
                data['token_type'],
                data['access_token'],
                data['refresh_token'],
                self._deserialize_expiry(data['expiry_time']),
            )
            if not new_session.check_login():
                logger.warning("Session %s failed: check_login returned false.", reason)
                return False

            self.session = new_session
            self.user = new_session.user
            self._tune_http_pool()
            self._apply_global_config()
            self._set_last_login_error("")
            try:
                self.save_session()
            except Exception as e:
                logger.debug("Session save after %s skipped: %s", reason, e)
            return True
        except Exception as e:
            logger.warning("Session %s error [%s]: %s", reason, classify_exception(e), e)
            return False

    def recover_session(self, reason="api"):
        with self._session_recovery_lock:
            # Discard stale connections (e.g. after system sleep/resume) so that
            # check_login() and subsequent requests use fresh TCP/SSL connections.
            try:
                from core.http_session import reset_global_session
                reset_global_session()
            except Exception as e:
                logger.debug("HTTP session reset skipped: %s", e)
            try:
                data = self._read_saved_session_data()
            except Exception as e:
                logger.warning("Session recovery read failed [%s]: %s", classify_exception(e), e)
                return False
            if not data:
                return False
            return self._restore_session_from_saved_data(data, reason=f"recovery:{reason}")

    def _call_with_session_recovery(self, fn, context="api"):
        try:
            return fn()
        except Exception as e:
            kind = classify_exception(e)
            if kind not in ("auth", "network", "server"):
                raise
            logger.warning("%s failed [%s]; attempting session recovery: %s", context, kind, e)
            if not self.recover_session(reason=context):
                raise
            return fn()

    def try_load_session(self):
        try:
            data = self._read_saved_session_data()
            if not data:
                return False
            if self._restore_session_from_saved_data(data, reason="startup"):
                self.refresh_favorite_ids()
                return True
        except Exception as e:
            logger.warning("Session load error [%s]: %s", classify_exception(e), e)
        return False

    def refresh_favorite_ids(self):
        from threading import Thread
        thread = Thread(target=self._refresh_favorite_ids_sync, daemon=True)
        thread.start()

    def _refresh_favorite_ids_sync(self):
        try:
            if not self.user: return
            # Reuse album cache when fresh to avoid a duplicate full API fetch.
            now = time.time()
            if self._has_fresh_recent_albums_cache(now=now):
                albums = self._cached_albums
            else:
                albums = self.get_recent_albums(limit=20000)
            self.fav_album_ids = {
                str(getattr(a, "id", ""))
                for a in (albums or [])
                if getattr(a, "id", None) is not None
            }
        except Exception as e:
            logger.debug("Failed to refresh favorite ids: %s", e)
        try:
            if not self.user:
                return
            artists = self.get_favorites(limit=20000)
            self.fav_artist_ids = {
                str(getattr(a, "id", ""))
                for a in (artists or [])
                if getattr(a, "id", None) is not None
            }
        except Exception as e:
            logger.debug("Failed to refresh favorite artist ids: %s", e)
        try:
            if not self.user:
                return
            # Use paginated fetch to avoid keeping only the first page of favorite track ids.
            tracks = self.get_favorite_tracks(limit=20000)
            self.fav_track_ids = {
                str(getattr(t, "id", ""))
                for t in (tracks or [])
                if getattr(t, "id", None) is not None
            }
        except Exception as e:
            logger.debug("Failed to refresh favorite track ids: %s", e)

    def is_favorite(self, album_id):
        return str(album_id) in self.fav_album_ids

    def is_artist_favorite(self, artist_id):
        return str(artist_id) in self.fav_artist_ids

    def is_track_favorite(self, track_id):
        return str(track_id) in self.fav_track_ids

    def _album_cache_ttl_seconds(self, default=300.0):
        try:
            return float(getattr(self, "_albums_cache_ttl", default))
        except Exception:
            return float(default)

    def _has_fresh_recent_albums_cache(self, now=None):
        cached = list(getattr(self, "_cached_albums", []) or [])
        if not cached:
            return False
        ttl = self._album_cache_ttl_seconds()
        if ttl <= 0.0:
            return False
        current_time = float(time.time() if now is None else now)
        last_ts = float(getattr(self, "_cached_albums_ts", 0.0) or 0.0)
        return (current_time - last_ts) < ttl

    def _sync_recent_albums_cache_after_favorite_toggle(self, album_id, add):
        album_key = str(album_id or "").strip()
        if add:
            # Added albums should be reloaded from server so ordering stays correct.
            self._cached_albums = []
            self._cached_albums_ts = 0.0
            return

        cached = list(getattr(self, "_cached_albums", []) or [])
        if not cached or not album_key:
            self._cached_albums = []
            self._cached_albums_ts = 0.0
            return

        filtered = [
            alb for alb in cached
            if str(getattr(alb, "id", "") or "") != album_key
        ]
        if len(filtered) != len(cached):
            self._cached_albums = filtered
            self._cached_albums_ts = time.time()
            return

        # If cache content does not match the removed album, force a clean refetch.
        self._cached_albums = []
        self._cached_albums_ts = 0.0

    def toggle_album_favorite(self, album_id, add=True):
        try:
            if add:
                self.user.favorites.add_album(album_id)
                self.fav_album_ids.add(str(album_id))
            else:
                self.user.favorites.remove_album(album_id)
                self.fav_album_ids.discard(str(album_id))
            self._sync_recent_albums_cache_after_favorite_toggle(album_id, add)
            return True
        except Exception as e:
            logger.warning("Failed to toggle album favorite for %s (add=%s): %s", album_id, add, e)
            return False

    def toggle_artist_favorite(self, artist_id, add=True):
        try:
            if add:
                self.user.favorites.add_artist(artist_id)
                self.fav_artist_ids.add(str(artist_id))
            else:
                self.user.favorites.remove_artist(artist_id)
                self.fav_artist_ids.discard(str(artist_id))
            self._favorite_artists_index_dirty = True
            return True
        except Exception as e:
            logger.warning("Failed to toggle artist favorite for %s (add=%s): %s", artist_id, add, e)
            return False

    def toggle_track_favorite(self, track_id, add=True):
        try:
            fav = self.user.favorites
            if add:
                if hasattr(fav, "add_track"):
                    fav.add_track(track_id)
                elif hasattr(fav, "add_tracks"):
                    fav.add_tracks([track_id])
                else:
                    raise AttributeError("favorites API has no add_track(s)")
                self.fav_track_ids.add(str(track_id))
            else:
                if hasattr(fav, "remove_track"):
                    fav.remove_track(track_id)
                elif hasattr(fav, "remove_tracks"):
                    fav.remove_tracks([track_id])
                else:
                    raise AttributeError("favorites API has no remove_track(s)")
                self.fav_track_ids.discard(str(track_id))
            return True
        except Exception as e:
            logger.warning("Failed to toggle track favorite for %s (add=%s): %s", track_id, add, e)
            return False

    def _paginate_favorites_api(self, api_callable, limit=1000, page_size=100, count_callable=None):
        if not callable(api_callable):
            return []

        target = max(0, int(limit or 0))
        if target <= 0:
            return []

        if callable(count_callable):
            try:
                total = max(0, int(count_callable() or 0))
            except Exception as e:
                logger.debug("Failed to fetch favorites count: %s", e)
            else:
                if total > 0:
                    target = min(target, total)
                    if target <= 0:
                        return []

        def _normalize(seq):
            if isinstance(seq, list):
                return seq
            return list(seq or [])

        def _fetch_page(offset, size):
            call_specs = (
                {"limit": size, "offset": offset},
                {"offset": offset, "limit": size},
                {"limit": size},
                {},
            )
            for kwargs in call_specs:
                try:
                    res = api_callable(**kwargs) if kwargs else api_callable()
                except TypeError:
                    continue
                page = res() if callable(res) else res
                return _normalize(page), kwargs
            res = api_callable()
            page = res() if callable(res) else res
            return _normalize(page), {}

        size = min(max(1, int(page_size or 100)), max(1, target))
        merged = []
        seen = set()
        offset = 0

        while len(merged) < target:
            page, used_kwargs = _fetch_page(offset, size)
            if not page:
                break

            new_added = 0
            for item in page:
                iid = getattr(item, "id", None)
                key = f"id:{iid}" if iid is not None else f"obj:{id(item)}"
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                new_added += 1
                if len(merged) >= target:
                    break

            if "offset" not in used_kwargs or new_added == 0:
                break

            offset += len(page)
            if offset > 100000:
                break

        return merged[:target]

    def _fetch_favorites_collection(
        self,
        fav,
        *,
        paginated_attr,
        api_attr,
        count_attr=None,
        limit=1000,
        page_size=100,
    ):
        target = max(0, int(limit or 0))
        if fav is None or target <= 0:
            return []

        paginated_api = getattr(fav, paginated_attr, None)
        if callable(paginated_api):
            try:
                items = paginated_api()
                items = items() if callable(items) else items
                return list(items or [])[:target]
            except Exception as e:
                logger.debug(
                    "Failed to fetch %s via paginated API; falling back to manual pagination: %s",
                    paginated_attr,
                    e,
                )

        api_callable = getattr(fav, api_attr, None)
        count_callable = getattr(fav, count_attr, None) if count_attr else None
        return self._paginate_favorites_api(
            api_callable,
            limit=target,
            page_size=page_size,
            count_callable=count_callable,
        )

    def get_favorites(self, limit=20000):
        try: 
            def _fetch():
                if not self.user:
                    return []
                fav = getattr(self.user, "favorites", None)
                return self._fetch_favorites_collection(
                    fav,
                    paginated_attr="artists_paginated",
                    api_attr="artists",
                    count_attr="get_artists_count",
                    limit=limit,
                    page_size=100,
                )

            return self._call_with_session_recovery(_fetch, context="favorite artists")
        except Exception as e:
            logger.warning("Failed to fetch favorite artists: %s", e)
            return []

    def get_favorite_artists_count(self):
        try:
            def _fetch():
                if not self.user:
                    return 0
                fav = getattr(self.user, "favorites", None)
                count_api = getattr(fav, "get_artists_count", None)
                if callable(count_api):
                    return max(0, int(count_api() or 0))
                # API doesn't expose a count endpoint; return 0 and let the caller
                # derive the total from page results (offset + len(items)).
                return 0

            return max(0, int(self._call_with_session_recovery(_fetch, context="favorite artists count") or 0))
        except Exception as e:
            logger.warning("Failed to fetch favorite artists count: %s", e)
            return 0

    def get_favorite_artists_page(self, limit=50, offset=0, sort="name_asc"):
        page_size = max(1, int(limit or 50))
        page_offset = max(0, int(offset or 0))
        sort_key = str(sort or "name_asc").strip().lower()

        order = None
        order_direction = None
        if sort_key.startswith("name"):
            order = getattr(tidal_user.ArtistOrder, "Name", None)
            order_direction = (
                getattr(tidal_user.OrderDirection, "Descending", None)
                if sort_key.endswith("_desc")
                else getattr(tidal_user.OrderDirection, "Ascending", None)
            )
        else:
            order = getattr(tidal_user.ArtistOrder, "DateAdded", None)
            order_direction = (
                getattr(tidal_user.OrderDirection, "Ascending", None)
                if sort_key.endswith("_asc")
                else getattr(tidal_user.OrderDirection, "Descending", None)
            )

        try:
            def _fetch():
                if not self.user:
                    return []
                fav = getattr(self.user, "favorites", None)
                artists_api = getattr(fav, "artists", None)
                if not callable(artists_api):
                    return []
                kwargs = {"limit": page_size, "offset": page_offset}
                if order is not None:
                    kwargs["order"] = order
                if order_direction is not None:
                    kwargs["order_direction"] = order_direction
                res = artists_api(**kwargs)
                return list((res() if callable(res) else res) or [])

            return list(self._call_with_session_recovery(_fetch, context="favorite artists page") or [])
        except Exception as e:
            logger.warning(
                "Failed to fetch favorite artists page offset=%s limit=%s sort=%s: %s",
                page_offset,
                page_size,
                sort_key,
                e,
            )
            return []

    def get_recent_albums(self, limit=20000):
        try:
            def _fetch():
                if not self.user:
                    return []
                fav = getattr(self.user, "favorites", None)
                return self._fetch_favorites_collection(
                    fav,
                    paginated_attr="albums_paginated",
                    api_attr="albums",
                    count_attr="get_albums_count",
                    limit=limit,
                    page_size=1000,
                )

            result = self._call_with_session_recovery(_fetch, context="recent albums")
            # Populate cache and fav_album_ids so callers can avoid re-fetching.
            self._cached_albums = list(result)
            self._cached_albums_ts = time.time()
            self.fav_album_ids = {
                str(getattr(a, "id", ""))
                for a in result
                if getattr(a, "id", None) is not None
            }
            return result
        except Exception as e:
            logger.warning("Failed to fetch recent albums: %s", e)
            if classify_exception(e) in ("auth", "network", "server"):
                cached = list(getattr(self, "_cached_albums", []) or [])
                if cached:
                    logger.info("Using cached recent albums after transient failure: count=%s", len(cached))
                    return cached
            return []

    def get_favorite_tracks(self, limit=50):
        try:
            def _fetch():
                if not self.user:
                    return []
                fav = getattr(self.user, "favorites", None)
                return self._fetch_favorites_collection(
                    fav,
                    paginated_attr="tracks_paginated",
                    api_attr="tracks",
                    count_attr="get_tracks_count",
                    limit=limit,
                    page_size=1000,
                )

            return self._call_with_session_recovery(_fetch, context="favorite tracks")
        except Exception as e:
            logger.warning("Failed to fetch favorite tracks: %s", e)
            return []

    def get_user_playlists(self, limit=80):
        if not self.user:
            return []
        merged = []
        seen = set()

        def _push(items):
            if items is None:
                return
            seq = items() if callable(items) else items
            for p in (seq or []):
                pid = str(getattr(p, "id", "") or "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                merged.append(p)

        try:
            if hasattr(self.user, "playlists"):
                _push(self.user.playlists())
        except Exception as e:
            logger.debug("Failed to fetch user playlists: %s", e)

        try:
            fav = getattr(self.user, "favorites", None)
            if fav is not None and hasattr(fav, "playlists"):
                _push(fav.playlists())
        except Exception as e:
            logger.debug("Failed to fetch favorite playlists: %s", e)

        return merged[: max(0, int(limit))]

    def _resolve_user_playlist(self, playlist_or_id):
        if playlist_or_id is None:
            return None
        if hasattr(playlist_or_id, "add"):
            return playlist_or_id
        pid = getattr(playlist_or_id, "id", playlist_or_id)
        if not pid:
            return None
        try:
            return self.session.playlist(pid)
        except Exception as e:
            logger.warning("Failed to resolve playlist %s: %s", pid, e)
            return None

    def create_cloud_playlist(self, name, description=""):
        if not self.user:
            logger.warning("Cannot create cloud playlist while not logged in.")
            return None
        title = str(name or "").strip() or "New Playlist"
        desc = str(description or "")
        try:
            pl = self.user.create_playlist(title, desc, parent_id="root")
            logger.info("Cloud playlist created: id=%s name=%r", getattr(pl, "id", None), title)
            return pl
        except Exception as e:
            logger.warning("Failed to create cloud playlist %r: %s", title, e)
            return None

    def create_cloud_playlist_in_folder(self, name, description="", parent_folder_id="root"):
        if not self.user:
            logger.warning("Cannot create cloud playlist while not logged in.")
            return None
        title = str(name or "").strip() or "New Playlist"
        desc = str(description or "")
        parent_id = str(parent_folder_id or "root")
        try:
            pl = self.user.create_playlist(title, desc, parent_id=parent_id)
            logger.info(
                "Cloud playlist created: id=%s name=%r folder=%s",
                getattr(pl, "id", None),
                title,
                parent_id,
            )
            return pl
        except Exception as e:
            logger.warning("Failed to create cloud playlist %r in folder %s: %s", title, parent_id, e)
            return None

    def create_cloud_folder(self, name, parent_folder_id="root"):
        if not self.user:
            logger.warning("Cannot create cloud folder while not logged in.")
            return None
        title = str(name or "").strip() or "New Folder"
        parent_id = str(parent_folder_id or "root")
        try:
            folder = self.user.create_folder(title, parent_id=parent_id)
            logger.info(
                "Cloud folder created: id=%s name=%r parent=%s",
                getattr(folder, "id", None),
                title,
                parent_id,
            )
            return folder
        except Exception as e:
            logger.warning("Failed to create cloud folder %r in parent %s: %s", title, parent_id, e)
            return None

    def _resolve_user_folder(self, folder_or_id):
        if folder_or_id is None:
            return None
        if hasattr(folder_or_id, "rename") and hasattr(folder_or_id, "remove"):
            return folder_or_id
        fid = str(getattr(folder_or_id, "id", folder_or_id) or "").strip()
        if not fid:
            return None
        try:
            for item in self.get_all_playlist_folders(limit=5000, max_depth=12):
                if str(item.get("id", "")) == fid:
                    obj = item.get("obj")
                    if obj is not None:
                        return obj
        except Exception as e:
            logger.debug("Folder resolve scan failed for %s: %s", fid, e)
        return None

    def rename_cloud_folder(self, folder_or_id, name):
        folder = self._resolve_user_folder(folder_or_id)
        new_name = str(name or "").strip()
        if folder is None or not new_name:
            return {"ok": False, "folder_id": getattr(folder, "id", None) if folder is not None else None}
        try:
            ok = bool(folder.rename(new_name))
            if ok:
                try:
                    folder.name = new_name
                except Exception:
                    pass
            return {"ok": ok, "folder_id": getattr(folder, "id", None), "name": new_name}
        except Exception as e:
            logger.warning("Failed renaming folder %s: %s", getattr(folder, "id", None), e)
            return {"ok": False, "folder_id": getattr(folder, "id", None), "name": new_name}

    def delete_cloud_folder(self, folder_or_id):
        folder = self._resolve_user_folder(folder_or_id)
        if folder is None:
            return {"ok": False, "folder_id": None}
        try:
            ok = bool(folder.remove())
            return {"ok": ok, "folder_id": getattr(folder, "id", None)}
        except Exception as e:
            logger.warning("Failed deleting folder %s: %s", getattr(folder, "id", None), e)
            return {"ok": False, "folder_id": getattr(folder, "id", None)}

    def _fetch_playlist_folders_page(self, parent_folder_id="root", limit=50, offset=0):
        if not self.user or not hasattr(self.user, "favorites"):
            return []
        fav = self.user.favorites
        if not hasattr(fav, "playlist_folders"):
            return []
        return list(
            fav.playlist_folders(
                limit=int(limit),
                offset=int(offset),
                parent_folder_id=str(parent_folder_id or "root"),
            )
            or []
        )

    def get_playlist_folders(self, parent_folder_id="root", limit=1000):
        out = []
        page_size = 50
        offset = 0
        max_items = max(0, int(limit or 0))
        while len(out) < max_items:
            try:
                page = self._fetch_playlist_folders_page(parent_folder_id=parent_folder_id, limit=page_size, offset=offset)
            except Exception as e:
                logger.warning("Failed fetching playlist folders (parent=%s): %s", parent_folder_id, e)
                break
            if not page:
                break
            out.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
        return out[:max_items]

    def get_playlists_in_folder(self, parent_folder=None, limit=1000):
        max_items = max(0, int(limit or 0))
        if max_items <= 0:
            return []

        out = []
        page_size = 50

        # Root folder.
        if parent_folder is None or str(parent_folder) == "root":
            if not self.user or not hasattr(self.user, "favorites"):
                return []
            fav = self.user.favorites
            if not hasattr(fav, "playlists"):
                return []
            offset = 0
            while len(out) < max_items:
                try:
                    page = list(fav.playlists(limit=page_size, offset=offset) or [])
                except Exception as e:
                    logger.warning("Failed fetching root playlists: %s", e)
                    break
                if not page:
                    break
                out.extend(page)
                if len(page) < page_size:
                    break
                offset += len(page)
            return out[:max_items]

        folder = parent_folder
        if not hasattr(folder, "items"):
            try:
                folder = self.session.folder(getattr(parent_folder, "id", parent_folder))
            except Exception as e:
                logger.warning("Failed resolving folder %s: %s", parent_folder, e)
                return []

        offset = 0
        while len(out) < max_items:
            try:
                page = list(folder.items(offset=offset, limit=page_size) or [])
            except Exception as e:
                logger.warning("Failed fetching playlists for folder %s: %s", getattr(folder, "id", None), e)
                break
            if not page:
                break
            out.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
        return out[:max_items]

    def get_playlists_and_folders(self, parent_folder=None, limit=1000):
        parent_id = "root" if parent_folder is None else str(getattr(parent_folder, "id", parent_folder) or "root")
        folders = self.get_playlist_folders(parent_folder_id=parent_id, limit=limit)
        playlists = self.get_playlists_in_folder(parent_folder=parent_folder, limit=limit)
        return {"folders": folders, "playlists": playlists}

    def get_folder_preview_artworks(self, folder_or_id, limit=4, size=320):
        urls = []
        max_items = max(1, int(limit or 4))
        folder = folder_or_id
        if folder is None:
            return urls
        if not hasattr(folder, "items"):
            try:
                folder = self.session.folder(getattr(folder_or_id, "id", folder_or_id))
            except Exception as e:
                logger.debug("Failed to resolve folder for preview artwork %s: %s", folder_or_id, e)
                return urls
        try:
            items = list(folder.items(offset=0, limit=max_items) or [])
            for pl in items:
                u = self.get_artwork_url(pl, size=size)
                if u:
                    urls.append(u)
                if len(urls) >= max_items:
                    break
        except Exception as e:
            logger.debug(
                "Failed to fetch folder preview artworks for folder %s: %s",
                getattr(folder, "id", None),
                e,
            )
        return urls[:max_items]

    def get_all_playlist_folders(self, limit=1000, max_depth=8):
        results = []
        queue = [("root", "", 0)]
        seen = set(["root"])
        while queue and len(results) < int(limit):
            parent_id, parent_path, depth = queue.pop(0)
            if depth >= int(max_depth):
                continue
            children = self.get_playlist_folders(parent_folder_id=parent_id, limit=1000)
            for f in children:
                fid = str(getattr(f, "id", "") or "")
                if not fid or fid in seen:
                    continue
                seen.add(fid)
                name = str(getattr(f, "name", "") or "Folder")
                path = f"{parent_path}/{name}" if parent_path else name
                results.append({"id": fid, "name": name, "path": path, "obj": f, "parent_id": parent_id})
                queue.append((fid, path, depth + 1))
                if len(results) >= int(limit):
                    break
        return results

    def move_cloud_playlist_to_folder(self, playlist_or_id, target_folder_id="root"):
        pl = self._resolve_user_playlist(playlist_or_id)
        if pl is None:
            return {"ok": False, "playlist_id": None, "target_folder_id": str(target_folder_id or "root")}

        pid = str(getattr(pl, "id", "") or "").strip()
        trn = str(getattr(pl, "trn", "") or "").strip() or (f"trn:playlist:{pid}" if pid else "")
        if not trn:
            return {"ok": False, "playlist_id": pid or None, "target_folder_id": str(target_folder_id or "root")}

        endpoint = "my-collection/playlists/folders/move"
        params = {"folderId": str(target_folder_id or "root"), "trns": trn}
        try:
            res = self.session.request.request(
                "PUT",
                endpoint,
                base_url=self.session.config.api_v2_location,
                params=params,
            )
            return {
                "ok": bool(getattr(res, "ok", False)),
                "playlist_id": pid or None,
                "target_folder_id": str(target_folder_id or "root"),
            }
        except Exception as e:
            logger.warning(
                "Failed moving playlist %s to folder %s: %s",
                pid or getattr(pl, "id", None),
                target_folder_id,
                e,
            )
            return {"ok": False, "playlist_id": pid or None, "target_folder_id": str(target_folder_id or "root")}

    def _extract_track_ids(self, items):
        """Extract track IDs from mixed input: str, int, dict, or object with .id attribute."""
        raw_ids = []
        skipped = 0
        for t in list(items or []):
            tid = None
            if isinstance(t, (str, int)):
                tid = str(t).strip()
            elif isinstance(t, dict):
                tid = str(t.get("track_id") or t.get("id") or "").strip()
            else:
                tid = str(getattr(t, "id", "") or "").strip()
            if not tid:
                skipped += 1
                continue
            raw_ids.append(tid)
        return raw_ids, skipped

    def add_tracks_to_cloud_playlist(self, playlist_or_id, tracks, dedupe=True, batch_size=100):
        pl = self._resolve_user_playlist(playlist_or_id)
        if pl is None:
            return {"ok": False, "playlist_id": None, "requested": 0, "added": 0, "skipped_invalid": 0}
        if not hasattr(pl, "add"):
            logger.warning("Resolved playlist does not support add(): id=%s", getattr(pl, "id", None))
            return {"ok": False, "playlist_id": getattr(pl, "id", None), "requested": 0, "added": 0, "skipped_invalid": 0}

        raw_ids, skipped_invalid = self._extract_track_ids(tracks)

        if not raw_ids:
            return {"ok": True, "playlist_id": getattr(pl, "id", None), "requested": 0, "added": 0, "skipped_invalid": skipped_invalid}

        track_ids = raw_ids
        if dedupe:
            # Keep order while removing duplicates from incoming list.
            seen = set()
            unique = []
            for tid in raw_ids:
                if tid in seen:
                    continue
                seen.add(tid)
                unique.append(tid)
            track_ids = unique

            # Skip existing tracks in target playlist.
            existing = set()
            try:
                existing_tracks = pl.tracks(limit=None)
                for et in list(existing_tracks or []):
                    eid = str(getattr(et, "id", "") or "").strip()
                    if eid:
                        existing.add(eid)
            except Exception as e:
                logger.debug("Failed to prefetch existing cloud playlist tracks for dedupe: %s", e)
            if existing:
                track_ids = [tid for tid in track_ids if tid not in existing]

        if not track_ids:
            return {"ok": True, "playlist_id": getattr(pl, "id", None), "requested": len(raw_ids), "added": 0, "skipped_invalid": skipped_invalid}

        bs = max(1, int(batch_size or 100))
        added = 0
        try:
            for i in range(0, len(track_ids), bs):
                chunk = track_ids[i : i + bs]
                pl.add(chunk, allow_duplicates=not dedupe)
                added += len(chunk)
            return {
                "ok": True,
                "playlist_id": getattr(pl, "id", None),
                "requested": len(raw_ids),
                "added": added,
                "skipped_invalid": skipped_invalid,
            }
        except Exception as e:
            logger.warning("Failed adding tracks to cloud playlist %s: %s", getattr(pl, "id", None), e)
            return {
                "ok": False,
                "playlist_id": getattr(pl, "id", None),
                "requested": len(raw_ids),
                "added": added,
                "skipped_invalid": skipped_invalid,
            }

    def remove_tracks_from_cloud_playlist(self, playlist_or_id, tracks_or_ids):
        pl = self._resolve_user_playlist(playlist_or_id)
        if pl is None:
            return {"ok": False, "playlist_id": None, "requested": 0, "removed": 0, "skipped_invalid": 0}

        raw_ids, skipped_invalid = self._extract_track_ids(tracks_or_ids)

        if not raw_ids:
            return {
                "ok": True,
                "playlist_id": getattr(pl, "id", None),
                "requested": 0,
                "removed": 0,
                "skipped_invalid": skipped_invalid,
            }

        seen = set()
        track_ids = []
        for tid in raw_ids:
            if tid in seen:
                continue
            seen.add(tid)
            track_ids.append(tid)

        removed = 0
        try:
            if hasattr(pl, "delete_by_id"):
                ok = bool(pl.delete_by_id(track_ids))
                removed = len(track_ids) if ok else 0
                return {
                    "ok": ok,
                    "playlist_id": getattr(pl, "id", None),
                    "requested": len(raw_ids),
                    "removed": removed,
                    "skipped_invalid": skipped_invalid,
                }

            logger.warning("Cloud playlist does not support delete_by_id(): id=%s", getattr(pl, "id", None))
            return {
                "ok": False,
                "playlist_id": getattr(pl, "id", None),
                "requested": len(raw_ids),
                "removed": 0,
                "skipped_invalid": skipped_invalid,
            }
        except Exception as e:
            logger.warning("Failed removing tracks from cloud playlist %s: %s", getattr(pl, "id", None), e)
            return {
                "ok": False,
                "playlist_id": getattr(pl, "id", None),
                "requested": len(raw_ids),
                "removed": removed,
                "skipped_invalid": skipped_invalid,
            }

    def rename_cloud_playlist(self, playlist_or_id, name, description=None):
        pl = self._resolve_user_playlist(playlist_or_id)
        new_name = str(name or "").strip()
        if pl is None or not new_name:
            return {"ok": False, "playlist_id": getattr(pl, "id", None) if pl is not None else None}
        if not hasattr(pl, "edit"):
            logger.warning("Cloud playlist does not support edit(): id=%s", getattr(pl, "id", None))
            return {"ok": False, "playlist_id": getattr(pl, "id", None)}
        try:
            desc = description
            if desc is None:
                desc = getattr(pl, "description", "") or ""
            ok = bool(pl.edit(title=new_name, description=desc))
            if ok:
                # Keep in-memory object aligned even if caller still holds old instance.
                try:
                    pl.name = new_name
                except Exception:
                    pass
            return {"ok": ok, "playlist_id": getattr(pl, "id", None), "name": new_name}
        except Exception as e:
            logger.warning("Failed renaming cloud playlist %s: %s", getattr(pl, "id", None), e)
            return {"ok": False, "playlist_id": getattr(pl, "id", None), "name": new_name}

    def update_cloud_playlist(self, playlist_or_id, name=None, description=None, is_public=None):
        pl = self._resolve_user_playlist(playlist_or_id)
        if pl is None:
            return {"ok": False, "playlist_id": None}

        ok = True
        new_name = str(name or getattr(pl, "name", "") or "").strip()
        new_desc = str(description if description is not None else (getattr(pl, "description", "") or ""))

        if hasattr(pl, "edit"):
            try:
                ok = bool(pl.edit(title=new_name, description=new_desc)) and ok
                if ok:
                    try:
                        pl.name = new_name
                        pl.description = new_desc
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("Failed editing cloud playlist %s: %s", getattr(pl, "id", None), e)
                ok = False

        if is_public is not None:
            desired_public = bool(is_public)
            current_public = bool(getattr(pl, "public", False))
            if desired_public != current_public:
                try:
                    if desired_public and hasattr(pl, "set_playlist_public"):
                        ok = bool(pl.set_playlist_public()) and ok
                    elif (not desired_public) and hasattr(pl, "set_playlist_private"):
                        ok = bool(pl.set_playlist_private()) and ok
                    else:
                        logger.warning("Cloud playlist does not support public/private toggle: id=%s", getattr(pl, "id", None))
                        ok = False
                    try:
                        pl.public = desired_public
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("Failed updating cloud playlist visibility %s: %s", getattr(pl, "id", None), e)
                    ok = False

        return {
            "ok": bool(ok),
            "playlist_id": getattr(pl, "id", None),
            "name": new_name,
            "description": new_desc,
            "public": bool(getattr(pl, "public", False)),
        }

    def delete_cloud_playlist(self, playlist_or_id):
        pl = self._resolve_user_playlist(playlist_or_id)
        if pl is None:
            return {"ok": False, "playlist_id": None}
        if not hasattr(pl, "delete"):
            logger.warning("Cloud playlist does not support delete(): id=%s", getattr(pl, "id", None))
            return {"ok": False, "playlist_id": getattr(pl, "id", None)}
        try:
            ok = bool(pl.delete())
            return {"ok": ok, "playlist_id": getattr(pl, "id", None)}
        except Exception as e:
            logger.warning("Failed deleting cloud playlist %s: %s", getattr(pl, "id", None), e)
            return {"ok": False, "playlist_id": getattr(pl, "id", None)}

    def sync_local_playlist_to_cloud(self, local_playlist, cloud_playlist_id=None, dedupe=True):
        name = str((local_playlist or {}).get("name", "") or "").strip() or "New Playlist"
        tracks = list((local_playlist or {}).get("tracks", []) or [])
        target = self._resolve_user_playlist(cloud_playlist_id) if cloud_playlist_id else None
        created = False
        if target is None:
            target = self.create_cloud_playlist(name, "Synced from HiresTI local playlist")
            created = bool(target is not None)
        if target is None:
            return {
                "ok": False,
                "cloud_playlist_id": None,
                "cloud_playlist_name": None,
                "created": False,
                "requested": len(tracks),
                "added": 0,
                "skipped_invalid": 0,
            }

        add_res = self.add_tracks_to_cloud_playlist(target, tracks, dedupe=dedupe, batch_size=100)
        return {
            "ok": bool(add_res.get("ok")),
            "cloud_playlist_id": getattr(target, "id", None),
            "cloud_playlist_name": getattr(target, "name", name),
            "created": created,
            "requested": int(add_res.get("requested", 0)),
            "added": int(add_res.get("added", 0)),
            "skipped_invalid": int(add_res.get("skipped_invalid", 0)),
        }

    def get_albums(self, art):
        def _fetch():
            a = art
            # History/Local objects may only contain artist id/name and
            # do not expose get_albums(). Resolve to a real artist first.
            if isinstance(a, (int, str)):
                a = self.session.artist(a)
            elif hasattr(a, "id") and not hasattr(a, "get_albums"):
                a = self.session.artist(getattr(a, "id"))
            res = a.get_albums()
            return list((res() if callable(res) else res) or [])
        try:
            return self._call_with_session_recovery(_fetch, context="artist albums")
        except Exception as e:
            logger.warning("Failed to fetch albums for artist %s: %s", getattr(art, "id", "unknown"), e)
            return []

    def get_artist_top_tracks(self, art, limit=20, offset=0):
        page_size = max(1, int(limit or 20))
        page_offset = max(0, int(offset or 0))

        def _fetch():
            a = art
            if isinstance(a, (int, str)):
                a = self.session.artist(a)
            elif hasattr(a, "id") and not hasattr(a, "get_top_tracks"):
                a = self.session.artist(getattr(a, "id"))
            fetcher = getattr(a, "get_top_tracks", None)
            if not callable(fetcher):
                return []
            res = fetcher(limit=page_size, offset=page_offset)
            return list((res() if callable(res) else res) or [])

        try:
            return list(self._call_with_session_recovery(_fetch, context="artist top tracks") or [])
        except Exception as e:
            logger.warning(
                "Failed to fetch top tracks for artist %s limit=%s offset=%s: %s",
                getattr(art, "id", "unknown"),
                page_size,
                page_offset,
                e,
            )
            return []

    def _get_artist_album_collection(self, art, method_name, limit=2000, page_size=100):
        target = max(0, int(limit or 0))
        if target <= 0:
            return []

        def _fetch():
            a = art
            if isinstance(a, (int, str)):
                a = self.session.artist(a)
            elif hasattr(a, "id") and not hasattr(a, method_name):
                a = self.session.artist(getattr(a, "id"))
            fetcher = getattr(a, method_name, None)
            if not callable(fetcher):
                return []

            merged = []
            offset = 0
            size = min(max(1, int(page_size or 100)), target)
            while len(merged) < target:
                page = fetcher(limit=size, offset=offset)
                page = list((page() if callable(page) else page) or [])
                if not page:
                    break
                merged.extend(page)
                offset += len(page)
            return merged[:target]

        return list(self._call_with_session_recovery(_fetch, context=f"artist {method_name}") or [])

    def get_artist_albums_all(self, art, limit=2000):
        try:
            return self._get_artist_album_collection(art, "get_albums", limit=limit, page_size=100)
        except Exception as e:
            logger.warning("Failed to fetch all albums for artist %s: %s", getattr(art, "id", "unknown"), e)
            return []

    def get_similar_artists(self, art):
        def _fetch():
            a = art
            if isinstance(a, (int, str)):
                a = self.session.artist(a)
            elif hasattr(a, "id") and not hasattr(a, "get_similar"):
                a = self.session.artist(getattr(a, "id"))
            return list(a.get_similar() or [])
        try:
            return list(self._call_with_session_recovery(_fetch, context="similar artists") or [])
        except Exception as e:
            logger.warning("Failed to fetch similar artists for %s: %s", getattr(art, "id", "unknown"), e)
            return []

    def get_artist_ep_singles_all(self, art, limit=2000):
        try:
            artist_obj = art
            if isinstance(artist_obj, (int, str)):
                artist_obj = self.session.artist(artist_obj)
            elif hasattr(artist_obj, "id") and not hasattr(artist_obj, "get_ep_singles") and not hasattr(artist_obj, "get_albums_ep_singles"):
                artist_obj = self.session.artist(getattr(artist_obj, "id"))

            if callable(getattr(artist_obj, "get_ep_singles", None)):
                return self._get_artist_album_collection(artist_obj, "get_ep_singles", limit=limit, page_size=100)
            return self._get_artist_album_collection(artist_obj, "get_albums_ep_singles", limit=limit, page_size=100)
        except Exception as e:
            logger.warning("Failed to fetch all EPs/singles for artist %s: %s", getattr(art, "id", "unknown"), e)
            return []

    def get_albums_page(self, art, limit=50, offset=0):
        """Fetch one page of artist albums. Uses session recovery on transient errors."""
        def _fetch():
            a = art
            if isinstance(a, (int, str)):
                a = self.session.artist(a)
            elif hasattr(a, "id") and not hasattr(a, "get_albums"):
                a = self.session.artist(getattr(a, "id"))
            res = a.get_albums(limit=limit, offset=offset)
            return list((res() if callable(res) else res) or [])
        try:
            return self._call_with_session_recovery(_fetch, context="artist albums page")
        except Exception as e:
            logger.warning("Failed to fetch albums page artist=%s offset=%s: %s",
                           getattr(art, "id", "?"), offset, e)
            return []

    def resolve_artist(self, artist_id=None, artist_name=None):
        """
        Resolve a lightweight/local artist reference into a real TIDAL artist object.
        """
        if artist_id is not None:
            try:
                return self.session.artist(artist_id)
            except Exception as e:
                logger.debug("Resolve artist by id failed for %s: %s", artist_id, e)

        if artist_name:
            candidates = self.search_artist(artist_name)
            if not candidates:
                return None

            target = artist_name.strip().lower()
            for cand in candidates:
                if getattr(cand, "name", "").strip().lower() == target:
                    return cand
            logger.debug("resolve_artist: no exact name match for %r among %s candidates", artist_name, len(candidates))

        return None

    # ==========================================
    # [核心修改] 带过滤功能的 get_home_page
    # ==========================================
    def _home_source_value(self, source, key):
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def _get_home_section_subtitle(self, category):
        title = str(self._home_source_value(category, "title") or "").strip()
        candidates = [
            self._home_source_value(category, "subtitle"),
            self._home_source_value(category, "description"),
        ]
        seen = set()
        for raw in candidates:
            text = str(raw or "").strip()
            low = text.lower()
            if not text or low == title.lower() or low in seen:
                continue
            seen.add(low)
            return text
        return ""

    def _parse_home_feed_item(self, item):
        if not isinstance(item, dict):
            return None
        item_type = str(item.get("type", "") or "").strip().upper()
        data = item.get("data")
        if not item_type or not isinstance(data, dict):
            return None

        try:
            obj = None
            if item_type == "ALBUM" and hasattr(self.session, "parse_album"):
                obj = self.session.parse_album(data)
            elif item_type == "ARTIST" and hasattr(self.session, "parse_artist"):
                obj = self.session.parse_artist(data)
            elif item_type == "TRACK" and hasattr(self.session, "parse_track"):
                obj = self.session.parse_track(data)
            elif item_type == "PLAYLIST" and hasattr(self.session, "parse_playlist"):
                obj = self.session.parse_playlist(data)
            elif item_type == "VIDEO" and hasattr(self.session, "parse_video"):
                obj = self.session.parse_video(data)
            elif item_type == "MIX":
                mix_parser = getattr(self.session, "parse_v2_mix", None) or getattr(self.session, "parse_mix", None)
                if callable(mix_parser):
                    obj = mix_parser(data)
            if obj is None:
                return None
            processed = self._process_generic_item(obj)
            if not processed:
                return None
            processed["obj"] = obj
            processed["type"] = processed.get("type") or item_type.title()
            return processed
        except Exception as e:
            logger.debug("Failed to parse home feed item type=%s: %s", item_type, e)
            return None

    def _fetch_home_page_raw(self):
        if not getattr(self, "session", None):
            return {}
        request_obj = getattr(self.session, "request", None)
        config_obj = getattr(self.session, "config", None)
        if request_obj is None or config_obj is None or not hasattr(request_obj, "request"):
            return {}

        def _fetch():
            return request_obj.request(
                "GET",
                "home/feed/static",
                base_url=config_obj.api_v2_location,
                params={
                    "deviceType": "BROWSER",
                    "locale": getattr(self.session, "locale", None),
                    "platform": "WEB",
                },
            ).json()

        return self._call_with_session_recovery(_fetch, context="home page")

    def get_home_page(self):
        """
        获取 Tidal 首页，并根据用户需求过滤栏目。
        """
        # 定义您想要显示的关键词 (不区分大小写)
        ALLOWED_KEYWORDS = [
            # English
            "mix", "spotlight", "suggested", "because", "recommended",
            "new", "radio", "station", "uploads", "for you", "albums",
            # Chinese (Simplified/Traditional)
            "推荐", "精选", "最新", "专辑", "电台", "为你", "新歌", "热播",
            # Japanese
            "ミックス", "ラジオ", "おすすめ", "新着", "アルバム", "あなた", "人気"
        ]

        home_sections = []
        try:
            raw_home = self._fetch_home_page_raw()
            raw_items = list((raw_home or {}).get("items") or [])
            if raw_items:
                logger.debug("Fetching home page from raw home/feed/static payload...")
                for category in raw_items:
                    if not isinstance(category, dict):
                        continue
                    title = str(category.get("title", "") or "").strip()
                    subtitle = self._get_home_section_subtitle(category)
                    description = str(category.get("description", "") or "").strip()
                    filter_text = " ".join(
                        part for part in (title, subtitle, description)
                        if str(part or "").strip()
                    ).lower()

                    is_allowed = any(k in filter_text for k in ALLOWED_KEYWORDS)
                    if not is_allowed:
                        continue

                    items = []
                    for item in list(category.get("items") or []):
                        processed_item = self._parse_home_feed_item(item)
                        if processed_item:
                            items.append(processed_item)
                    if not items:
                        continue

                    section = {
                        "title": title,
                        "subtitle": subtitle,
                        "section_type": str(category.get("type", "") or ""),
                        "items": items,
                    }
                    context_header = self._parse_home_feed_item(category.get("header"))
                    if context_header:
                        section["context_header"] = context_header
                    home_sections.append(section)
            elif hasattr(self.session, 'home'):
                logger.debug("Fetching session.home()...")
                home = self.session.home()
                if hasattr(home, 'categories'):
                    for category in home.categories:
                        title = str(getattr(category, "title", "") or "").strip()
                        subtitle = self._get_home_section_subtitle(category)
                        description = str(getattr(category, "description", "") or "").strip()
                        filter_text = " ".join(
                            part for part in (title, subtitle, description)
                            if str(part or "").strip()
                        ).lower()
                        
                        # [过滤逻辑] 检查标题是否包含任一关键词
                        is_allowed = any(k in filter_text for k in ALLOWED_KEYWORDS)
                        
                        if is_allowed:
                            section = {
                                'title': title,
                                'subtitle': subtitle,
                                'section_type': str(getattr(category, "type", "") or ""),
                                'items': []
                            }
                            if hasattr(category, 'items'):
                                for item in category.items:
                                    processed_item = self._process_generic_item(item)
                                    if processed_item:
                                        section['items'].append(processed_item)
                            
                            if section['items']:
                                home_sections.append(section)
                        else:
                            # 可以在这里打印被过滤掉的栏目，方便调试
                            # print(f"[Backend] Filtered out: {title}")
                            pass
            else:
                # 回退模式
                logger.info("session.home() not found, using fallback.")
                mixes = self._get_fallback_mixes()
                if mixes: home_sections.append({'title': 'Mixes for you', 'items': mixes})
                
        except Exception as e:
            logger.warning("Get home page error [%s]: %s", classify_exception(e), e)
            
        return home_sections

    def get_top_page(self):
        """
        Fetch official TIDAL platform Top page sections from /pages/explore_top_music.
        """
        def _norm_path(path):
            p = str(path or "").strip()
            if not p:
                return None
            return p[1:] if p.startswith("/") else p

        sections = []
        seen_paths = set()
        seen_titles = set()

        def _norm_text(v):
            s = str(v or "").strip().lower()
            keep = []
            for ch in s:
                if ch.isalnum() or ch.isspace():
                    keep.append(ch)
            return " ".join("".join(keep).split())

        def _dedupe_items(items):
            out = []
            seen = set()
            for it in list(items or []):
                if not isinstance(it, dict):
                    continue
                obj = it.get("obj")
                item_id = None
                if obj is not None:
                    item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None)
                    if item_id is None and isinstance(obj, dict):
                        item_id = obj.get("id") or obj.get("track_id")
                typ = str(it.get("type") or "")
                if item_id is not None and str(item_id).strip():
                    key = (typ, str(item_id).strip())
                else:
                    key = (typ, _norm_text(it.get("name")), _norm_text(it.get("sub_title")))
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
            return out

        def _collect_category_items(category):
            items = list(getattr(category, "items", None) or [])
            more = getattr(category, "_more", None)
            more_path = _norm_path(getattr(more, "api_path", None) if more is not None else None)
            if not more_path or not hasattr(self.session, "page") or self.session.page is None:
                return items
            try:
                more_page = self.session.page.get(more_path, params={"deviceType": "BROWSER"})
            except Exception as e:
                logger.debug("Top category view-all fetch failed for %s: %s", more_path, e)
                return items

            merged = list(items)
            for sub_cat in list(getattr(more_page, "categories", None) or []):
                sub_items = list(getattr(sub_cat, "items", None) or [])
                if sub_items:
                    merged.extend(sub_items)
            return merged

        def _top_image_url_from_uuid(image_id, size=320):
            val = str(image_id or "").strip()
            if not val:
                return None
            if val.startswith("http://") or val.startswith("https://"):
                return val
            token = val.replace("-", "/")
            return f"https://resources.tidal.com/images/{token}/{int(size)}x{int(size)}.jpg"

        def _process_top_item(item):
            # Fast path: avoid eager item.get() network calls during page load.
            try:
                if item is None:
                    return None
                if hasattr(item, "header") and hasattr(item, "type"):
                    raw_type = str(getattr(item, "type", "") or "").strip().upper()
                    type_map = {
                        "TRACK": "Track",
                        "ALBUM": "Album",
                        "ARTIST": "Artist",
                        "PLAYLIST": "Playlist",
                        "VIDEO": "Video",
                        "MIX": "Mix",
                    }
                    return {
                        "obj": item,
                        "name": str(getattr(item, "header", "") or getattr(item, "short_header", "") or "Unknown"),
                        "sub_title": str(getattr(item, "short_sub_header", "") or ""),
                        "image_url": _top_image_url_from_uuid(getattr(item, "image_id", None), size=320),
                        "type": type_map.get(raw_type, "PageItem"),
                    }
                if hasattr(item, "title") and hasattr(item, "api_path"):
                    return {
                        "obj": item,
                        "name": (lambda _t: str(_t) if _t is not None and not callable(_t) else "")(getattr(item, "title", None)) or "Top",
                        "sub_title": "",
                        "image_url": _top_image_url_from_uuid(getattr(item, "image_id", None), size=320),
                        "type": "PageLink",
                    }
            except Exception:
                return None
            return None

        try:
            if not hasattr(self.session, "page") or self.session.page is None:
                return sections

            queue = ["pages/explore_top_music"]
            while queue:
                path = _norm_path(queue.pop(0))
                if not path or path in seen_paths:
                    continue
                seen_paths.add(path)

                try:
                    page_obj = self.session.page.get(path, params={"deviceType": "BROWSER"})
                except Exception as e:
                    logger.debug("Top page fetch failed for %s: %s", path, e)
                    continue

                categories = list(getattr(page_obj, "categories", None) or [])
                for category in categories:
                    _ct = getattr(category, "title", "")
                    title = (str(_ct) if _ct is not None and not callable(_ct) else "").strip() or "Top"
                    raw_items = _collect_category_items(category)
                    sec_items = []

                    for item in raw_items:
                        link_path = getattr(item, "api_path", None)
                        if link_path is None and isinstance(item, dict):
                            link_path = item.get("apiPath")
                        link_norm = _norm_path(link_path)
                        if link_norm and "explore_top" in link_norm and link_norm not in seen_paths:
                            queue.append(link_norm)

                        processed = _process_top_item(item)
                        if not processed:
                            processed = self._process_generic_item(item)
                        if processed:
                            sec_items.append(processed)

                    sec_items = _dedupe_items(sec_items)
                    if not sec_items:
                        continue
                    dedupe_key = f"{path}:{title.lower()}"
                    if dedupe_key in seen_titles:
                        continue
                    seen_titles.add(dedupe_key)
                    sections.append({"title": title, "items": sec_items})
        except Exception as e:
            logger.warning("Get top page error [%s]: %s", classify_exception(e), e)
        return sections

    def get_new_page(self):
        """
        Fetch official TIDAL New page sections from /pages/explore_new_music.
        Excludes music-video categories/items.
        """
        def _norm_path(path):
            p = str(path or "").strip()
            if not p:
                return None
            return p[1:] if p.startswith("/") else p

        def _is_video_text(text):
            s = str(text or "").strip().lower()
            if not s:
                return False
            return ("video" in s) or ("mv" in s) or ("音乐视频" in s) or ("音樂視頻" in s)

        def _collect_category_items(category):
            items = list(getattr(category, "items", None) or [])
            more = getattr(category, "_more", None)
            more_path = _norm_path(getattr(more, "api_path", None) if more is not None else None)
            if not more_path or not hasattr(self.session, "page") or self.session.page is None:
                return items
            try:
                more_page = self.session.page.get(more_path, params={"deviceType": "BROWSER"})
            except Exception as e:
                logger.debug("New category view-all fetch failed for %s: %s", more_path, e)
                return items

            merged = list(items)
            for sub_cat in list(getattr(more_page, "categories", None) or []):
                sub_items = list(getattr(sub_cat, "items", None) or [])
                if sub_items:
                    merged.extend(sub_items)
            return merged

        def _image_url_from_uuid(image_id, size=320):
            val = str(image_id or "").strip()
            if not val:
                return None
            if val.startswith("http://") or val.startswith("https://"):
                return val
            token = val.replace("-", "/")
            return f"https://resources.tidal.com/images/{token}/{int(size)}x{int(size)}.jpg"

        def _process_item(item):
            try:
                if item is None:
                    return None
                if hasattr(item, "header") and hasattr(item, "type"):
                    raw_type = str(getattr(item, "type", "") or "").strip().upper()
                    if raw_type == "VIDEO":
                        return None
                    type_map = {
                        "TRACK": "Track",
                        "ALBUM": "Album",
                        "ARTIST": "Artist",
                        "PLAYLIST": "Playlist",
                        "MIX": "Mix",
                    }
                    return {
                        "obj": item,
                        "name": str(getattr(item, "header", "") or getattr(item, "short_header", "") or "Unknown"),
                        "sub_title": str(getattr(item, "short_sub_header", "") or ""),
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None), size=320),
                        "type": type_map.get(raw_type, "PageItem"),
                    }
                if hasattr(item, "title") and hasattr(item, "api_path"):
                    if _is_video_text(getattr(item, "title", "")):
                        return None
                    return {
                        "obj": item,
                        "name": (lambda _t: str(_t) if _t is not None and not callable(_t) else "")(getattr(item, "title", None)) or "New",
                        "sub_title": "",
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None), size=320),
                        "type": "PageLink",
                    }
            except Exception:
                return None
            return None

        sections = []
        seen_paths = set()
        seen_titles = set()

        def _norm_text(v):
            s = str(v or "").strip().lower()
            keep = []
            for ch in s:
                if ch.isalnum() or ch.isspace():
                    keep.append(ch)
            return " ".join("".join(keep).split())

        def _dedupe_items(items):
            out = []
            seen = set()
            for it in list(items or []):
                if not isinstance(it, dict):
                    continue
                obj = it.get("obj")
                item_id = None
                if obj is not None:
                    item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None)
                    if item_id is None and isinstance(obj, dict):
                        item_id = obj.get("id") or obj.get("track_id")
                typ = str(it.get("type") or "")
                if item_id is not None and str(item_id).strip():
                    key = (typ, str(item_id).strip())
                else:
                    key = (typ, _norm_text(it.get("name")), _norm_text(it.get("sub_title")))
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
            return out
        try:
            if not hasattr(self.session, "page") or self.session.page is None:
                return sections

            queue = ["pages/explore_new_music"]
            while queue:
                path = _norm_path(queue.pop(0))
                if not path or path in seen_paths:
                    continue
                seen_paths.add(path)

                try:
                    page_obj = self.session.page.get(path, params={"deviceType": "BROWSER"})
                except Exception as e:
                    logger.debug("New page fetch failed for %s: %s", path, e)
                    continue

                categories = list(getattr(page_obj, "categories", None) or [])
                for category in categories:
                    _ct = getattr(category, "title", "")
                    title = (str(_ct) if _ct is not None and not callable(_ct) else "").strip() or "New"
                    if _is_video_text(title):
                        continue
                    raw_items = _collect_category_items(category)
                    sec_items = []

                    for item in raw_items:
                        link_path = getattr(item, "api_path", None)
                        if link_path is None and isinstance(item, dict):
                            link_path = item.get("apiPath")
                        link_norm = _norm_path(link_path)
                        if link_norm and "explore_new" in link_norm and link_norm not in seen_paths:
                            queue.append(link_norm)

                        processed = _process_item(item)
                        if not processed:
                            processed = self._process_generic_item(item)
                        if processed and not _is_video_text(processed.get("name")) and not _is_video_text(processed.get("sub_title")):
                            sec_items.append(processed)

                    sec_items = _dedupe_items(sec_items)
                    if not sec_items:
                        continue
                    dedupe_key = f"{path}:{title.lower()}"
                    if dedupe_key in seen_titles:
                        continue
                    seen_titles.add(dedupe_key)
                    sections.append({"title": title, "items": sec_items})
        except Exception as e:
            logger.warning("Get new page error [%s]: %s", classify_exception(e), e)
        return sections

    def get_decades_page(self):
        """
        Fetch TIDAL Decades content.
        Each decade has its own page at pages/m_1950s, pages/m_1960s, …
        Returns a list of sections, one per decade, each with all items
        from all categories on that decade's page merged together.
        """
        DECADES = [
            ("1950s", "pages/m_1950s"),
            ("1960s", "pages/m_1960s"),
            ("1970s", "pages/m_1970s"),
            ("1980s", "pages/m_1980s"),
            ("1990s", "pages/m_1990s"),
            ("2000s", "pages/m_2000s"),
            ("2010s", "pages/m_2010s"),
        ]

        def _image_url_from_uuid(image_id, size=320):
            val = str(image_id or "").strip()
            if not val:
                return None
            if val.startswith("http://") or val.startswith("https://"):
                return val
            token = val.replace("-", "/")
            return f"https://resources.tidal.com/images/{token}/{int(size)}x{int(size)}.jpg"

        def _process_item(item):
            try:
                if item is None:
                    return None
                if hasattr(item, "header") and hasattr(item, "type"):
                    raw_type = str(getattr(item, "type", "") or "").strip().upper()
                    type_map = {
                        "TRACK": "Track", "ALBUM": "Album", "ARTIST": "Artist",
                        "PLAYLIST": "Playlist", "MIX": "Mix",
                    }
                    return {
                        "obj": item,
                        "name": str(getattr(item, "header", "") or getattr(item, "short_header", "") or "Unknown"),
                        "sub_title": str(getattr(item, "short_sub_header", "") or ""),
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None)),
                        "type": type_map.get(raw_type, "PageItem"),
                    }
                if hasattr(item, "title") and hasattr(item, "api_path"):
                    _t = getattr(item, "title", None)
                    return {
                        "obj": item,
                        "name": str(_t if _t is not None and not callable(_t) else "") or "Unknown",
                        "sub_title": "",
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None)),
                        "type": "PageLink",
                    }
            except Exception:
                return None
            return None

        def _dedupe_items(items):
            out, seen = [], set()
            for it in list(items or []):
                if not isinstance(it, dict):
                    continue
                obj = it.get("obj")
                item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None) if obj is not None else None
                typ = str(it.get("type") or "")
                key = (typ, str(item_id).strip()) if item_id is not None and str(item_id).strip() else (typ, str(it.get("name", "")).strip().lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
            return out

        def _fetch_decade(label, path):
            """Fetch one decade page; preserve each category as a sub-section."""
            try:
                page_obj = self.session.page.get(path, params={"deviceType": "BROWSER"})
                categories = []
                seen_cat_titles = set()
                for category in list(getattr(page_obj, "categories", None) or []):
                    cat_title = str(getattr(category, "title", "") or "").strip()
                    if not cat_title or cat_title.lower() in seen_cat_titles:
                        continue
                    seen_cat_titles.add(cat_title.lower())
                    cat_items = []
                    for item in list(getattr(category, "items", None) or []):
                        processed = _process_item(item)
                        if not processed:
                            processed = self._process_generic_item(item)
                        if processed:
                            cat_items.append(processed)
                    cat_items = _dedupe_items(cat_items)
                    if cat_items:
                        categories.append({"title": cat_title, "items": cat_items})
                if categories:
                    logger.debug("Decades: loaded %d categories for %s", len(categories), label)
                    return {"title": label, "categories": categories}
            except Exception as e:
                logger.debug("Decades: failed to fetch %s (%s): %s", label, path, e)
            return None

        if not hasattr(self.session, "page") or self.session.page is None:
            return [], []

        # Return the decade definitions and only the first decade's content eagerly.
        # Callers use get_decade_section() to fetch remaining decades on demand.
        first_sec = _fetch_decade(DECADES[0][0], DECADES[0][1])
        eager = [first_sec] if first_sec else []
        return DECADES, eager

    def get_decade_section(self, label, path):
        """Fetch a single decade's content on demand (used for lazy tab loading)."""
        DECADES = [
            ("1950s", "pages/m_1950s"),
            ("1960s", "pages/m_1960s"),
            ("1970s", "pages/m_1970s"),
            ("1980s", "pages/m_1980s"),
            ("1990s", "pages/m_1990s"),
            ("2000s", "pages/m_2000s"),
            ("2010s", "pages/m_2010s"),
        ]

        def _image_url_from_uuid(image_id, size=320):
            val = str(image_id or "").strip()
            if not val:
                return None
            if val.startswith("http://") or val.startswith("https://"):
                return val
            token = val.replace("-", "/")
            return f"https://resources.tidal.com/images/{token}/{int(size)}x{int(size)}.jpg"

        def _process_item(item):
            try:
                if item is None:
                    return None
                if hasattr(item, "header") and hasattr(item, "type"):
                    raw_type = str(getattr(item, "type", "") or "").strip().upper()
                    type_map = {
                        "TRACK": "Track", "ALBUM": "Album", "ARTIST": "Artist",
                        "PLAYLIST": "Playlist", "MIX": "Mix",
                    }
                    return {
                        "obj": item,
                        "name": str(getattr(item, "header", "") or getattr(item, "short_header", "") or "Unknown"),
                        "sub_title": str(getattr(item, "short_sub_header", "") or ""),
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None)),
                        "type": type_map.get(raw_type, "PageItem"),
                    }
                if hasattr(item, "title") and hasattr(item, "api_path"):
                    _t = getattr(item, "title", None)
                    return {
                        "obj": item,
                        "name": str(_t if _t is not None and not callable(_t) else "") or "Unknown",
                        "sub_title": "",
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None)),
                        "type": "PageLink",
                    }
            except Exception:
                return None
            return None

        def _dedupe_items(items):
            out, seen = [], set()
            for it in list(items or []):
                if not isinstance(it, dict):
                    continue
                obj = it.get("obj")
                item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None) if obj is not None else None
                typ = str(it.get("type") or "")
                key = (typ, str(item_id).strip()) if item_id is not None and str(item_id).strip() else (typ, str(it.get("name", "")).strip().lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
            return out

        try:
            page_obj = self.session.page.get(path, params={"deviceType": "BROWSER"})
            categories = []
            seen_cat_titles = set()
            for category in list(getattr(page_obj, "categories", None) or []):
                cat_title = str(getattr(category, "title", "") or "").strip()
                if not cat_title or cat_title.lower() in seen_cat_titles:
                    continue
                seen_cat_titles.add(cat_title.lower())
                cat_items = []
                for item in list(getattr(category, "items", None) or []):
                    processed = _process_item(item)
                    if not processed:
                        processed = self._process_generic_item(item)
                    if processed:
                        cat_items.append(processed)
                cat_items = _dedupe_items(cat_items)
                if cat_items:
                    categories.append({"title": cat_title, "items": cat_items})
            if categories:
                return {"title": label, "categories": categories}
        except Exception as e:
            logger.debug("Decades: failed to fetch %s (%s): %s", label, path, e)
        return None

    def get_genres_page(self):
        """
        Fetch official TIDAL Genres tab definitions from /pages/genre_page.
        Returns the tab definitions plus the first tab's content eagerly.
        """
        def _norm_path(path):
            p = str(path or "").strip()
            if not p:
                return None
            return p[1:] if p.startswith("/") else p

        definitions = []
        seen = set()

        try:
            if not hasattr(self.session, "page") or self.session.page is None:
                return [], []

            page_fetch = getattr(self.session, "genres", None)
            if callable(page_fetch):
                page_obj = page_fetch()
            else:
                page_obj = self.session.page.get("pages/genre_page", params={"deviceType": "BROWSER"})

            for category in list(getattr(page_obj, "categories", None) or []):
                for item in list(getattr(category, "items", None) or []):
                    _title = getattr(item, "title", None)
                    title = (str(_title) if _title is not None and not callable(_title) else "").strip()
                    path = _norm_path(getattr(item, "api_path", None))
                    if not title or not path:
                        continue
                    key = (title.lower(), path)
                    if key in seen:
                        continue
                    seen.add(key)
                    definitions.append((title, path))
        except Exception as e:
            logger.warning("Get genres page error [%s]: %s", classify_exception(e), e)
            return [], []

        eager = []
        if definitions:
            first_label, first_path = definitions[0]
            first_sec = self.get_genre_section(first_label, first_path)
            if first_sec:
                eager.append(first_sec)
        return definitions, eager

    def get_genre_section(self, label, path):
        """Fetch a single genre page on demand (used for lazy tab loading)."""
        def _norm_path(raw_path):
            p = str(raw_path or "").strip()
            if not p:
                return None
            return p[1:] if p.startswith("/") else p

        def _image_url_from_uuid(image_id, size=320):
            val = str(image_id or "").strip()
            if not val:
                return None
            if val.startswith("http://") or val.startswith("https://"):
                return val
            token = val.replace("-", "/")
            return f"https://resources.tidal.com/images/{token}/{int(size)}x{int(size)}.jpg"

        def _collect_category_items(category):
            """Return (initial_items, more_path).

            The _more link is NOT fetched here; it is returned as more_path so
            the UI can fetch it on demand when the user clicks "Show More",
            avoiding N extra serial network calls on every tab switch.
            """
            items = list(getattr(category, "items", None) or [])
            more = getattr(category, "_more", None)
            more_path = _norm_path(getattr(more, "api_path", None) if more is not None else None)
            return items, more_path

        def _process_item(item):
            try:
                if item is None:
                    return None
                if hasattr(item, "header") and hasattr(item, "type"):
                    raw_type = str(getattr(item, "type", "") or "").strip().upper()
                    type_map = {
                        "TRACK": "Track",
                        "ALBUM": "Album",
                        "ARTIST": "Artist",
                        "PLAYLIST": "Playlist",
                        "MIX": "Mix",
                    }
                    return {
                        "obj": item,
                        "name": str(getattr(item, "header", "") or getattr(item, "short_header", "") or "Unknown"),
                        "sub_title": str(getattr(item, "short_sub_header", "") or ""),
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None)),
                        "type": type_map.get(raw_type, "PageItem"),
                    }
                if hasattr(item, "title") and hasattr(item, "api_path"):
                    _title = getattr(item, "title", None)
                    return {
                        "obj": item,
                        "name": str(_title if _title is not None and not callable(_title) else "") or "Unknown",
                        "sub_title": "",
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None)),
                        "type": "PageLink",
                    }
            except Exception:
                return None
            return None

        def _norm_text(value):
            s = str(value or "").strip().lower()
            keep = []
            for ch in s:
                if ch.isalnum() or ch.isspace():
                    keep.append(ch)
            return " ".join("".join(keep).split())

        def _dedupe_items(items):
            out, seen = [], set()
            for it in list(items or []):
                if not isinstance(it, dict):
                    continue
                obj = it.get("obj")
                item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None) if obj is not None else None
                typ = str(it.get("type") or "")
                if item_id is not None and str(item_id).strip():
                    key = (typ, str(item_id).strip())
                else:
                    key = (typ, _norm_text(it.get("name")), _norm_text(it.get("sub_title")))
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
            return out

        try:
            genre_path = _norm_path(path)
            if not genre_path or not hasattr(self.session, "page") or self.session.page is None:
                return None

            page_obj = self.session.page.get(genre_path, params={"deviceType": "BROWSER"})
            categories = []
            seen_cat_titles = set()
            for category in list(getattr(page_obj, "categories", None) or []):
                _title = getattr(category, "title", None)
                cat_title = (str(_title) if _title is not None and not callable(_title) else "").strip()
                if not cat_title or cat_title.lower() in seen_cat_titles:
                    continue
                seen_cat_titles.add(cat_title.lower())
                cat_items = []
                raw_items, more_path = _collect_category_items(category)
                for item in raw_items:
                    processed = _process_item(item)
                    if not processed:
                        processed = self._process_generic_item(item)
                    if processed:
                        cat_items.append(processed)
                cat_items = _dedupe_items(cat_items)
                if cat_items:
                    categories.append({"title": cat_title, "items": cat_items, "more_path": more_path})
            if categories:
                return {"title": label, "categories": categories}
        except Exception as e:
            logger.debug("Genres: failed to fetch %s (%s): %s", label, path, e)
        return None

    def fetch_genre_more(self, more_path):
        """Fetch additional items from a genre category _more link on demand.

        Called when the user clicks "Show More" after exhausting the initial
        items returned by get_genre_section().  Returns a flat list of
        processed item dicts ready for the UI, or [] on failure.
        """
        def _norm(p):
            p = str(p or "").strip()
            return p[1:] if p.startswith("/") else p or None

        def _img(image_id, size=320):
            val = str(image_id or "").strip()
            if not val:
                return None
            if val.startswith("http://") or val.startswith("https://"):
                return val
            return f"https://resources.tidal.com/images/{val.replace('-', '/')}/{size}x{size}.jpg"

        def _proc(item):
            try:
                if item is None:
                    return None
                if hasattr(item, "header") and hasattr(item, "type"):
                    raw_type = str(getattr(item, "type", "") or "").strip().upper()
                    type_map = {"TRACK": "Track", "ALBUM": "Album", "ARTIST": "Artist",
                                "PLAYLIST": "Playlist", "MIX": "Mix"}
                    return {
                        "obj": item,
                        "name": str(getattr(item, "header", "") or getattr(item, "short_header", "") or "Unknown"),
                        "sub_title": str(getattr(item, "short_sub_header", "") or ""),
                        "image_url": _img(getattr(item, "image_id", None)),
                        "type": type_map.get(raw_type, "PageItem"),
                    }
                if hasattr(item, "title") and hasattr(item, "api_path"):
                    _t = getattr(item, "title", None)
                    return {
                        "obj": item,
                        "name": str(_t if _t is not None and not callable(_t) else "") or "Unknown",
                        "sub_title": "",
                        "image_url": _img(getattr(item, "image_id", None)),
                        "type": "PageLink",
                    }
            except Exception:
                return None
            return None

        try:
            norm = _norm(more_path)
            if not norm or not hasattr(self.session, "page") or self.session.page is None:
                return []
            more_page = self.session.page.get(norm, params={"deviceType": "BROWSER"})
            result, seen = [], set()
            for sub_cat in list(getattr(more_page, "categories", None) or []):
                for raw_item in list(getattr(sub_cat, "items", None) or []):
                    processed = _proc(raw_item) or self._process_generic_item(raw_item)
                    if not processed:
                        continue
                    obj = processed.get("obj")
                    item_id = getattr(obj, "id", None) if obj is not None else None
                    key = (processed.get("type"), str(item_id).strip()) if item_id else None
                    if key and key in seen:
                        continue
                    if key:
                        seen.add(key)
                    result.append(processed)
            return result
        except Exception as e:
            logger.debug("Genres: fetch_genre_more failed for %s: %s", more_path, e)
            return []

    def get_hires_page(self):
        """
        Fetch TIDAL Hi-Res page sections from /pages/hires.
        """
        def _norm_path(path):
            p = str(path or "").strip()
            if not p:
                return None
            return p[1:] if p.startswith("/") else p

        def _image_url_from_uuid(image_id, size=320):
            val = str(image_id or "").strip()
            if not val:
                return None
            if val.startswith("http://") or val.startswith("https://"):
                return val
            token = val.replace("-", "/")
            return f"https://resources.tidal.com/images/{token}/{int(size)}x{int(size)}.jpg"

        def _collect_category_items(category):
            items = list(getattr(category, "items", None) or [])
            more = getattr(category, "_more", None)
            more_path = _norm_path(getattr(more, "api_path", None) if more is not None else None)
            if not more_path or not hasattr(self.session, "page") or self.session.page is None:
                return items
            try:
                more_page = self.session.page.get(more_path, params={"deviceType": "BROWSER"})
                for sub_cat in list(getattr(more_page, "categories", None) or []):
                    sub_items = list(getattr(sub_cat, "items", None) or [])
                    if sub_items:
                        items.extend(sub_items)
            except Exception as e:
                logger.debug("Hi-Res category view-all fetch failed for %s: %s", more_path, e)
            return items

        def _process_item(item):
            try:
                if item is None:
                    return None
                if hasattr(item, "header") and hasattr(item, "type"):
                    raw_type = str(getattr(item, "type", "") or "").strip().upper()
                    type_map = {
                        "TRACK": "Track", "ALBUM": "Album", "ARTIST": "Artist",
                        "PLAYLIST": "Playlist", "MIX": "Mix",
                    }
                    return {
                        "obj": item,
                        "name": str(getattr(item, "header", "") or getattr(item, "short_header", "") or "Unknown"),
                        "sub_title": str(getattr(item, "short_sub_header", "") or ""),
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None)),
                        "type": type_map.get(raw_type, "PageItem"),
                    }
                if hasattr(item, "title") and hasattr(item, "api_path"):
                    _t = getattr(item, "title", None)
                    return {
                        "obj": item,
                        "name": str(_t if _t is not None and not callable(_t) else "") or "Hi-Res",
                        "sub_title": "",
                        "image_url": _image_url_from_uuid(getattr(item, "image_id", None)),
                        "type": "PageLink",
                    }
            except Exception:
                return None
            return None

        def _norm_text(v):
            s = str(v or "").strip().lower()
            return " ".join(ch for ch in s if ch.isalnum() or ch.isspace()).split() and " ".join(
                ch for ch in s if ch.isalnum() or ch.isspace()
            ) or ""

        def _dedupe_items(items):
            out, seen = [], set()
            for it in list(items or []):
                if not isinstance(it, dict):
                    continue
                obj = it.get("obj")
                item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None) if obj is not None else None
                typ = str(it.get("type") or "")
                key = (typ, str(item_id).strip()) if item_id is not None and str(item_id).strip() else (typ, _norm_text(it.get("name")))
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
            return out

        sections = []
        seen_titles = set()
        try:
            if not hasattr(self.session, "page") or self.session.page is None:
                return sections
            page_obj = self.session.page.get("pages/hires", params={"deviceType": "BROWSER"})
            for category in list(getattr(page_obj, "categories", None) or []):
                _ct = getattr(category, "title", "")
                title = (str(_ct) if _ct is not None and not callable(_ct) else "").strip() or "Hi-Res"
                dedupe_key = title.lower()
                if dedupe_key in seen_titles:
                    continue
                seen_titles.add(dedupe_key)
                raw_items = _collect_category_items(category)
                sec_items = []
                for item in raw_items:
                    processed = _process_item(item)
                    if not processed:
                        processed = self._process_generic_item(item)
                    if processed:
                        sec_items.append(processed)
                sec_items = _dedupe_items(sec_items)
                if sec_items:
                    sections.append({"title": title, "items": sec_items})
        except Exception as e:
            logger.warning("Get hires page error [%s]: %s", classify_exception(e), e)
        return sections

    def _process_generic_item(self, item):
        try:
            # 基础信息
            _t = getattr(item, 'title', None)
            _name = str(_t) if _t is not None and not callable(_t) else str(getattr(item, 'name', None) or 'Unknown')
            data = {
                'obj': item,
                'name': _name,
                'sub_title': '',
                'image_url': self.get_artwork_url(item, 320),
                'type': type(item).__name__ 
            }
            
            # 补充子标题
            if hasattr(item, 'artist') and item.artist:
                data['sub_title'] = item.artist.name
            elif hasattr(item, 'artists') and item.artists:
                data['sub_title'] = ", ".join([a.name for a in item.artists[:2]])
            elif hasattr(item, 'description'):
                data['sub_title'] = item.description
            # 处理 Track 类型
            elif hasattr(item, 'album'):
                 data['sub_title'] = getattr(item.artist, 'name', '')
                
            return data
        except Exception as e:
            logger.debug("Failed to process home item of type %s: %s", type(item).__name__, e)
            return None

    def _get_fallback_mixes(self):
        try:
            if hasattr(self.user, 'mixes'):
                raw = self.user.mixes()
                return [self._process_generic_item(m) for m in (raw() if callable(raw) else raw)]
        except Exception as e:
            logger.warning("Failed to fetch fallback mixes: %s", e)
            return []

    def get_tracks(self, item):
        try:
            def _fetch():
                # 1. 解包
                resolved = item
                if isinstance(resolved, dict) and 'obj' in resolved:
                    resolved = resolved['obj']

                item_type = type(resolved).__name__
                item_id = getattr(resolved, 'id', None)

                # 2. 优先通过当前 session 重新解析远端对象，避免使用挂在旧 session
                # 上的 album/playlist object（挂起后更容易失效）。
                if item_id:
                    logger.debug("Reloading %s with ID %s", item_type, item_id)

                    if 'Mix' in item_type:
                        now = time.time()
                        fail_until = self._mix_fail_until.get(str(item_id), 0)
                        if now < fail_until:
                            logger.info(
                                "Skipping mix %s fetch for %ss due to recent server failures.",
                                item_id,
                                int(fail_until - now),
                            )
                            return []

                        def fetch_mix_items():
                            mix = self.session.mix(item_id)
                            return self._extract_tracks_from_items(mix.items())

                        try:
                            tracks = self._retry_api_call(fetch_mix_items, attempts=3, base_delay=0.4)
                            # Clear circuit breaker after successful fetch.
                            self._mix_fail_until.pop(str(item_id), None)
                            return tracks
                        except Exception as e:
                            # Temporary circuit breaker to avoid spamming unstable endpoint.
                            if self._is_server_error(e):
                                self._mix_fail_until[str(item_id)] = time.time() + 60
                            raise

                    if 'Playlist' in item_type:
                        pl = self.session.playlist(item_id)
                        return self._extract_tracks_from_items(pl.items())

                    if 'Album' in item_type:
                        alb = self.session.album(item_id)
                        return alb.tracks()

                # 3. 回退到对象自带方法（适配部分本地/轻量对象）。
                if hasattr(resolved, 'tracks') and callable(resolved.tracks):
                    return resolved.tracks()
                if hasattr(resolved, 'items') and callable(resolved.items):
                    return self._extract_tracks_from_items(resolved.items())
                if hasattr(resolved, 'id'):
                    return self.session.album(resolved.id).tracks()
                return []

            return self._call_with_session_recovery(_fetch, context="album tracks")
        except Exception as e:
            logger.warning("Get tracks error [%s]: %s", classify_exception(e), e)
            return []

    def get_playlist_tracks_page(self, playlist_or_id, limit=100, offset=0):
        pl = self._resolve_user_playlist(playlist_or_id)
        if pl is None:
            return []
        page_size = max(1, min(200, int(limit or 100)))
        page_offset = max(0, int(offset or 0))
        try:
            if hasattr(pl, "tracks") and callable(pl.tracks):
                return list(pl.tracks(limit=page_size, offset=page_offset) or [])
            if hasattr(pl, "items") and callable(pl.items):
                return self._extract_tracks_from_items(pl.items(limit=page_size, offset=page_offset))
        except Exception as e:
            logger.warning(
                "Get playlist page error [%s]: playlist=%s limit=%s offset=%s err=%s",
                classify_exception(e),
                getattr(pl, "id", None),
                page_size,
                page_offset,
                e,
            )
        return []

    def _is_server_error(self, exc):
        text = str(exc).lower()
        return any(k in text for k in ("500", "502", "503", "504", "internal server error", "bad gateway"))

    def _is_retryable_error(self, exc):
        text = str(exc).lower()
        if self._is_server_error(exc):
            return True
        return any(k in text for k in ("timeout", "timed out", "connection", "network", "temporary"))

    def _retry_api_call(self, fn, attempts=3, base_delay=0.35):
        last_exc = None
        for i in range(attempts):
            try:
                return fn()
            except Exception as e:
                last_exc = e
                if i >= attempts - 1 or not self._is_retryable_error(e):
                    raise
                delay = base_delay * (i + 1)
                logger.info("Retrying API call after transient error (%s). attempt=%s/%s", e, i + 1, attempts)
                time.sleep(delay)
        if last_exc:
            raise last_exc
        return []

    def _extract_tracks_from_items(self, items):
        res = items() if callable(items) else items
        final_tracks = []
        for i in res:
            if hasattr(i, 'track'):
                if i.track: final_tracks.append(i.track)
            else:
                final_tracks.append(i)
        return final_tracks

    def get_artwork_url(self, obj, size=320):
        """
        [增强版] 自动识别各种 Tidal 对象的封面/头像 UUID，支持 LocalAlbum
        """
        if isinstance(obj, dict) and 'obj' in obj: obj = obj['obj']
        if not obj: return None

        # Playlist artwork is often exposed via object methods/typed fields;
        # UUID-to-resources URL synthesis can fail with 403 on some objects.
        if "Playlist" in type(obj).__name__:
            scanned = self._scan_image_like_attrs(obj, size=size)
            if scanned:
                return scanned
            pl_id = getattr(obj, "id", None)
            if pl_id:
                try:
                    full_pl = self.session.playlist(pl_id)
                    scanned_full = self._scan_image_like_attrs(full_pl, size=size)
                    if scanned_full:
                        return scanned_full
                except Exception as e:
                    logger.debug("Playlist artwork refresh failed for %s: %s", pl_id, e)

        uuid = None

        # 1. 优先检查 cover_url (LocalAlbum 历史记录对象使用此属性)
        # 以前这里直接返回，现在增加 UUID 检测
        raw_url = getattr(obj, 'cover_url', None)
        if raw_url:
            if isinstance(raw_url, str) and "http" in raw_url:
                return raw_url # 已经是完整 URL
            elif isinstance(raw_url, str) and len(raw_url) > 20:
                uuid = raw_url # 是 UUID，留给后面处理

        # 2. 如果没找到，尝试常规 Tidal 对象的属性 (picture/cover/images)
        if not uuid:
            # 尝试调用方法
            for attr in ['picture', 'cover', 'image', 'square_image', 'square_picture', 'wide_image']:
                val = getattr(obj, attr, None)
                if val and callable(val):
                    try:
                        return val(width=size, height=size)
                    except Exception as e:
                        logger.debug("Artwork provider '%s'(w/h) failed for %s: %s", attr, type(obj).__name__, e)
                    try:
                        out = val(size)
                        if isinstance(out, str) and out:
                            if "http" in out:
                                return out
                            if len(out) > 20:
                                uuid = out
                                break
                    except Exception:
                        pass
                    try:
                        out = val()
                        if isinstance(out, str) and out:
                            if "http" in out:
                                return out
                            if len(out) > 20:
                                uuid = out
                                break
                    except Exception:
                        pass
            
            # 检查 images 集合
            if hasattr(obj, 'images') and obj.images:
                try:
                    if hasattr(obj.images, 'large'): return obj.images.large
                    if isinstance(obj.images, dict): return list(obj.images.values())[0]
                except Exception as e:
                    logger.debug("Failed to resolve artwork from images on %s: %s", type(obj).__name__, e)

            # 属性探测
            check_attrs = ['picture_id', 'cover_id', 'picture', 'cover', 'image', 'avatar', 'square_image']
            for attr in check_attrs:
                val = getattr(obj, attr, None)
                if not (val and isinstance(val, str)):
                    continue
                if "http" in val:
                    return val
                if len(val) > 20:
                    uuid = val
                    break
        
        # 3. 如果还是没找到，且是单曲，尝试用专辑封面
        if not uuid and hasattr(obj, 'album') and obj.album:
            return self.get_artwork_url(obj.album, size)

        # 4. 最终生成 URL
        if uuid:
            path = uuid.replace('-', '/')
            return f"https://resources.tidal.com/images/{path}/{size}x{size}.jpg"
            
        return None

    def _coerce_image_ref_to_url(self, value, size):
        if not isinstance(value, str):
            return None
        raw = value.strip()
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if len(raw) > 20:
            path = raw.replace("-", "/")
            return f"https://resources.tidal.com/images/{path}/{size}x{size}.jpg"
        return None

    def _extract_tidal_image_uuid(self, url):
        if not isinstance(url, str):
            return None
        if "resources.tidal.com/images/" not in url:
            return None
        tail = url.split("/images/", 1)[-1]
        parts = tail.split("/")
        if len(parts) < 5:
            return None
        return "-".join(parts[:5]).strip().lower()

    def _is_placeholder_artist_artwork_url(self, url):
        img_uuid = self._extract_tidal_image_uuid(url)
        if not img_uuid:
            return False
        return img_uuid in self._artist_placeholder_uuids

    def _scan_image_like_attrs(self, obj, size=320):
        if obj is None:
            return None
        keywords = ("image", "cover", "picture", "avatar", "art")
        for name in dir(obj):
            low = str(name).lower()
            if not any(k in low for k in keywords):
                continue
            if low.startswith("_"):
                continue
            try:
                val = getattr(obj, name)
            except Exception:
                continue
            if callable(val):
                for args in ((size, size), (size,), tuple()):
                    try:
                        out = val(*args)
                    except Exception:
                        continue
                    url = self._coerce_image_ref_to_url(out, size)
                    if url:
                        return url
            else:
                url = self._coerce_image_ref_to_url(val, size)
                if url:
                    return url
        return None

    def get_artist_artwork_url(self, artist_obj, size=320, local_only=False):
        cache_key = None
        artist_id = getattr(artist_obj, "id", None)
        artist_name_raw = str(getattr(artist_obj, "name", "") or "").strip()
        if artist_id is not None:
            cache_key = f"id:{artist_id}:{int(size)}"
        else:
            artist_name = artist_name_raw.lower()
            if artist_name:
                cache_key = f"name:{artist_name}:{int(size)}"
        if cache_key and cache_key in self._artist_artwork_cache:
            cached = self._artist_artwork_cache[cache_key]
            if cached:
                # LRU: move to end (most recently used)
                # Use try-except for compatibility with dict subclasses
                try:
                    self._artist_artwork_cache.move_to_end(cache_key)
                except AttributeError:
                    # Fallback for dict subclasses without move_to_end
                    self._artist_artwork_cache[cache_key] = self._artist_artwork_cache.pop(cache_key)
                logger.debug(
                    "Artist artwork cache hit: id=%s name=%r size=%s url=%s",
                    artist_id,
                    artist_name_raw,
                    size,
                    cached,
                )
                return cached
            # Do not keep negative cache entries forever; allow retry.
            self._artist_artwork_cache.pop(cache_key, None)

        # Deduplicate concurrent resolution for the same key: if another thread
        # is already fetching this artist's artwork, wait for it and use the result.
        if cache_key:
            with self._artist_artwork_inflight_lock:
                if cache_key in self._artist_artwork_inflight:
                    event = self._artist_artwork_inflight[cache_key]
                else:
                    event = threading.Event()
                    self._artist_artwork_inflight[cache_key] = event
                    event = None  # this thread is the resolver
            if event is not None:
                event.wait(timeout=15)
                return self._artist_artwork_cache.get(cache_key)

        def _album_cover_fallback(*artist_candidates):
            for cand in artist_candidates:
                if cand is None:
                    continue
                try:
                    albums = self.get_albums(cand) or []
                except Exception:
                    albums = []
                for alb in list(albums)[:8]:
                    u = self.get_artwork_url(alb, size) or self._scan_image_like_attrs(alb, size)
                    if u:
                        return u
            return None

        chosen_url = None
        try:
            logger.debug(
                "Resolving artist artwork: id=%s name=%r size=%s",
                artist_id,
                artist_name_raw,
                size,
            )
            u = self.get_artwork_url(artist_obj, size)
            if u and self._is_placeholder_artist_artwork_url(u):
                logger.debug(
                    "Skip placeholder artist artwork from source object: id=%s name=%r url=%s",
                    artist_id,
                    artist_name_raw,
                    u,
                )
                u = None
            if u:
                logger.debug("Artist artwork resolved from source object: id=%s name=%r url=%s", artist_id, artist_name_raw, u)
                chosen_url = u
                return chosen_url
            artist_id = getattr(artist_obj, "id", None)
            if bool(local_only):
                logger.debug(
                    "Artist artwork local-only mode, skip remote fallback: id=%s name=%r",
                    artist_id,
                    artist_name_raw,
                )
                return None
            full_artist = None
            if artist_id:
                full_artist = self.session.artist(artist_id)
                u = self.get_artwork_url(full_artist, size) or self._scan_image_like_attrs(full_artist, size)
                if u and self._is_placeholder_artist_artwork_url(u):
                    logger.debug(
                        "Skip placeholder artist artwork from full artist object: id=%s name=%r url=%s",
                        artist_id,
                        artist_name_raw,
                        u,
                    )
                    u = None
                if u:
                    logger.debug("Artist artwork resolved from full artist object: id=%s name=%r url=%s", artist_id, artist_name_raw, u)
                    chosen_url = u
                    return chosen_url
            # Last fallback: resolve by name from search results and retry image extraction.
            artist_name = artist_name_raw
            target = None
            if artist_name:
                candidates = self.search_artist(artist_name) or []
                logger.debug(
                    "Artist artwork name-search candidates: id=%s name=%r count=%s",
                    artist_id,
                    artist_name,
                    len(candidates),
                )
                low = artist_name.lower()
                for c in candidates:
                    n = str(getattr(c, "name", "") or "").strip().lower()
                    if n == low:
                        target = c
                        break
                if target is None and candidates:
                    logger.debug(
                        "Artist artwork name-search: no exact match for %r among %s candidates, skipping to avoid wrong-artist match",
                        artist_name,
                        len(candidates),
                    )
                if target is not None:
                    u = self.get_artwork_url(target, size) or self._scan_image_like_attrs(target, size)
                    if u and self._is_placeholder_artist_artwork_url(u):
                        logger.debug(
                            "Skip placeholder artist artwork from search target: id=%s name=%r url=%s",
                            artist_id,
                            artist_name_raw,
                            u,
                        )
                        u = None
                    if u:
                        logger.debug("Artist artwork resolved from search target: id=%s name=%r url=%s", artist_id, artist_name_raw, u)
                        chosen_url = u
                        return chosen_url
            # Final fallback: use one album cover of this artist.
            chosen_url = _album_cover_fallback(artist_obj, full_artist, target)
            if chosen_url:
                logger.debug("Artist artwork resolved from album fallback: id=%s name=%r url=%s", artist_id, artist_name_raw, chosen_url)
            else:
                logger.debug("Artist artwork resolution failed: id=%s name=%r size=%s", artist_id, artist_name_raw, size)
            return chosen_url
        except Exception as e:
            logger.debug("Failed artist artwork fallback for %s: %s", getattr(artist_obj, "id", "?"), e)
            return None
        finally:
            if cache_key and chosen_url:
                # LRU: add new entry at end (most recently used position)
                self._artist_artwork_cache[cache_key] = chosen_url
                # Enforce cache size limit: remove oldest entries from beginning
                while len(self._artist_artwork_cache) > self.max_artist_artwork_cache:
                    self._artist_artwork_cache.popitem(last=False)
            # Unblock any threads that were waiting for this resolution.
            if cache_key:
                with self._artist_artwork_inflight_lock:
                    event = self._artist_artwork_inflight.pop(cache_key, None)
                if event is not None:
                    event.set()

    def _get_url_from_stream(self, full_track):
        """Resolve a playable URI via the newer playbackinfopostpaywall endpoint.

        Uses get_stream() which supports HI_RES_LOSSLESS and works with all auth
        types, unlike the legacy urlpostpaywall endpoint which caps at LOSSLESS.

        Returns (uri, stream) on success, raises on failure.
        - BTS manifests: direct HTTP URL, GStreamer handles natively.
        - MPD manifests: written to a temp file and returned as file:// URI so
          GStreamer's dashdemux (gst-plugins-bad) can parse and fetch segments.
        """
        import os
        import tempfile

        stream = full_track.get_stream()
        manifest = stream.get_stream_manifest()

        if manifest.is_bts:
            urls = manifest.get_urls()
            if not urls:
                raise ValueError("Empty URL list in BTS manifest")
            return urls[0], stream

        if manifest.is_mpd:
            # Write the MPD XML to a per-track temp file.  Using a shared single
            # file caused a race condition: the prefetch thread overwrote the file
            # for the current track before GStreamer finished reading it, causing
            # GStreamer to load the wrong track's segments.
            mpd_xml = stream.get_manifest_data()
            track_id = str(getattr(full_track, "id", "") or "tmp")
            tmp_path = os.path.join(
                tempfile.gettempdir(), f"hiresti_{track_id}.mpd"
            )
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(mpd_xml)
            return f"file://{tmp_path}", stream

        raise ValueError(f"Unknown manifest type: {stream.manifest_mime_type}")

    def get_stream_url(self, track):
        preferred = self.quality
        qualities = self._get_stream_quality_fallback_chain()
        last_exc = None
        try:
            for idx, q in enumerate(qualities):
                try:
                    self._apply_session_quality(q)
                    full_track = self.session.track(track.id)

                    # Prefer the newer playbackinfopostpaywall endpoint (get_stream).
                    # It supports HI_RES_LOSSLESS; the legacy urlpostpaywall endpoint
                    # caps at LOSSLESS regardless of subscription.
                    url = None
                    stream_info = None
                    try:
                        url, stream_info = self._get_url_from_stream(full_track)
                    except Exception as stream_exc:
                        logger.debug(
                            "get_stream() path failed (%s), falling back to get_url(): %s",
                            type(stream_exc).__name__,
                            stream_exc,
                        )
                        url = full_track.get_url()

                    # Cache source format from TIDAL API for the player to inject
                    # into stream_info (GStreamer TAGs don't carry Hz/-bit info).
                    self._last_stream_bit_depth = int(
                        getattr(stream_info, "bit_depth", 0) or 0
                    )
                    self._last_stream_sample_rate = int(
                        getattr(stream_info, "sample_rate", 0) or 0
                    )

                    if idx == 0:
                        if stream_info is not None:
                            logger.info(
                                "Stream resolved for '%s': quality=%s %sbit/%sHz",
                                getattr(track, "name", "?"),
                                getattr(stream_info, "audio_quality", q),
                                getattr(stream_info, "bit_depth", "?"),
                                getattr(stream_info, "sample_rate", "?"),
                            )
                        else:
                            logger.info(
                                "Stream URL resolved for '%s' with quality %s",
                                getattr(track, "name", "?"),
                                q,
                            )
                    else:
                        logger.warning(
                            "Stream quality fallback for '%s': preferred=%s actual=%s %sbit/%sHz",
                            getattr(track, "name", "unknown"),
                            preferred,
                            q,
                            getattr(stream_info, "bit_depth", "?") if stream_info else "?",
                            getattr(stream_info, "sample_rate", "?") if stream_info else "?",
                        )
                    return url
                except Exception as e:
                    last_exc = e
                    kind = classify_exception(e)
                    # Keep trying lower tiers for auth/availability rejections.
                    if idx < len(qualities) - 1 and kind in ("auth", "server", "unknown"):
                        logger.warning(
                            "Stream URL failed at quality %s [%s], trying fallback...",
                            q,
                            kind,
                        )
                        continue
                    if idx < len(qualities) - 1:
                        continue
            if last_exc is not None:
                logger.warning("Stream URL error [%s]: %s", classify_exception(last_exc), last_exc)
                # When a track ID is dead (404/not_found) — common for liked songs that
                # reference old catalog IDs that were later replaced — try to recover the
                # correct track by looking it up through its album.  This is exactly what
                # users do manually when they "find the song in its album and play it".
                if classify_exception(last_exc) == "not_found":
                    album_id = getattr(getattr(track, "album", None), "id", None)
                    track_name = str(getattr(track, "name", "") or "").strip().lower()
                    if album_id and track_name:
                        try:
                            album = self.session.album(album_id)
                            album_tracks = album.tracks()
                            alt_track = next(
                                (
                                    t for t in (album_tracks or [])
                                    if str(getattr(t, "name", "") or "").strip().lower() == track_name
                                    and getattr(t, "id", None) != getattr(track, "id", None)
                                ),
                                None,
                            )
                            if alt_track is not None:
                                logger.warning(
                                    "Stream URL album fallback: stale_id=%s → album_id=%s alt_id=%s name=%r",
                                    getattr(track, "id", None),
                                    album_id,
                                    alt_track.id,
                                    getattr(track, "name", ""),
                                )
                                self._last_track_redirect = (
                                    str(getattr(track, "id", "") or ""),
                                    alt_track,
                                )
                                return self.get_stream_url(alt_track)
                        except Exception as fb_exc:
                            logger.debug(
                                "Album fallback for track %s failed: %s",
                                getattr(track, "id", None),
                                fb_exc,
                            )
            return None
        finally:
            # Restore selected preference for subsequent requests.
            self._apply_session_quality(preferred)

    def set_quality_mode(self, mode_str):
        mapping = {
            "Max (Up to 24-bit, 192 kHz)": [
                "hi_res_lossless",
                "HI_RES_LOSSLESS",
                "HI_RES",
                "MASTER",
            ],
            "High (16-bit, 44.1 kHz)": [
                "high_lossless",
                "LOSSLESS",
            ],
            "Low (320 kbps)": [
                "low_320k",
                "HIGH",
                "low_96k",
                "LOW",
            ],
        }
        target_keys = mapping.get(mode_str, ["low_320k", "HIGH"])
        self.quality = self._resolve_quality(target_keys, fallback="LOSSLESS")
        logger.info("Quality mode set: %s -> %s", mode_str, self.quality)
        self._apply_global_config()

    def search_artist(self, query):
        try:
            # Some tidalapi versions do not expose tidalapi.models.
            # Use generic search and extract artists in a compatible way.
            res = self.session.search(query, limit=20)
            artists = getattr(res, "artists", None)
            if artists is None and isinstance(res, dict):
                artists = res.get("artists")
            if artists is None:
                return []
            artist_list = artists() if callable(artists) else artists
            return list(artist_list)[:10]
        except Exception as e:
            logger.warning("Artist search failed for query '%s': %s", query, e)
            return []

    def _parse_search_results(self, res, limit_per_type=6):
        """Parse tidal search results with compatibility for dict vs object."""
        results = {'artists': [], 'albums': [], 'tracks': []}
        for key in results:
            raw = None
            if hasattr(res, key):
                raw = getattr(res, key)
            elif isinstance(res, dict):
                raw = res.get(key)
            if raw:
                items = raw() if callable(raw) else raw
                results[key] = list(items)[:limit_per_type]
        return results

    def search_items(self, query):
        logger.info("Starting search for query: '%s'", query)
        
        if not self.session.check_login():
            logger.warning("Session expired or not logged in during search.")
            return {'artists': [], 'albums': [], 'tracks': []}

        try:
            res = self.session.search(query, limit=300)
            logger.debug("Raw search response type: %s", type(res))
            results = self._parse_search_results(res, limit_per_type=6)
            logger.info(
                "Search parsed: %s artists, %s albums, %s tracks",
                len(results['artists']),
                len(results['albums']),
                len(results['tracks']),
            )
            return results

        except Exception as e:
            logger.exception("Search critical failure [%s]: %s", classify_exception(e), e)
            return results

    def get_lyrics(self, track_id):
        logger.debug("Fetching lyrics for track id: %s", track_id)
        if track_id in self.lyrics_cache:
            # LRU: move to end (most recently used)
            # Use try-except for compatibility with dict subclasses
            try:
                self.lyrics_cache.move_to_end(track_id)
            except AttributeError:
                # Fallback for dict subclasses without move_to_end
                self.lyrics_cache[track_id] = self.lyrics_cache.pop(track_id)
            logger.debug("Lyrics cache hit for track id: %s", track_id)
            return self.lyrics_cache.get(track_id)

        try:
            lyrics_obj = self.session.track(track_id).lyrics()

            if not lyrics_obj:
                logger.debug("Lyrics result: none (no lyrics object found)")
                self._cache_lyrics(track_id, None)
                return None

            if hasattr(lyrics_obj, 'subtitles') and lyrics_obj.subtitles:
                logger.debug("Lyrics result: synced lyrics found")
                self._cache_lyrics(track_id, lyrics_obj.subtitles)
                return lyrics_obj.subtitles

            if hasattr(lyrics_obj, 'text') and lyrics_obj.text:
                logger.debug("Lyrics result: static text lyrics found")
                self._cache_lyrics(track_id, lyrics_obj.text)
                return lyrics_obj.text

            logger.debug("Lyrics result: lyrics object empty")
            self._cache_lyrics(track_id, None)
            return None
        except Exception as e:
            # 404 是正常的（表示没歌词），不打印错误堆栈
            if "404" in str(e):
                logger.debug("Lyrics result: 404 not found (no lyrics)")
                self._cache_lyrics(track_id, None)
            else:
                logger.warning("Lyrics fetch error [%s]: %s", classify_exception(e), e)
            return None

    def _cache_lyrics(self, track_id, value):
        # LRU: add new entry at end (most recently used position)
        self.lyrics_cache[track_id] = value
        # Enforce cache size limit: remove oldest entries from beginning
        while len(self.lyrics_cache) > self.max_lyrics_cache:
            self.lyrics_cache.popitem(last=False)

    def logout(self):
        for token_path in (self.token_file, self.legacy_token_file):
            if os.path.exists(token_path):
                try:
                    os.remove(token_path)
                except Exception as e:
                    logger.warning("Failed to remove token file %s: %s", token_path, e)
        self.user = None
        self.session = tidalapi.Session()
        self.fav_album_ids = set()
        self.fav_track_ids = set()
        self._cached_albums = []
        self._cached_albums_ts = 0.0
        self._apply_global_config()
