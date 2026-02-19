import tidalapi
import logging
import os
import json
import time
from datetime import datetime
from urllib.parse import urlparse
from app_errors import classify_exception

logger = logging.getLogger(__name__)

class TidalBackend:
    def __init__(self):
        self.session = tidalapi.Session()
        self.token_file = os.path.expanduser("~/.cache/hiresti_token.json")
        self.legacy_token_file = os.path.expanduser("~/.cache/hiresti_token.pkl")
        self.user = None
        self.quality = self._get_best_quality()
        self._apply_global_config() 
        self.fav_album_ids = set()
        self.fav_artist_ids = set()
        self.fav_track_ids = set()
        self._artist_artwork_cache = {}
        self._artist_placeholder_uuids = {
            "1e01cdb6-f15d-4d8b-8440-a047976c1cac",
        }
        extra_placeholder_ids = str(os.getenv("HIRESTI_ARTIST_PLACEHOLDER_UUIDS", "") or "").strip()
        if extra_placeholder_ids:
            for raw in extra_placeholder_ids.split(","):
                val = raw.strip().lower()
                if val:
                    self._artist_placeholder_uuids.add(val)
        self.lyrics_cache = {}
        self.max_lyrics_cache = 300
        # Circuit breaker for unstable mix endpoint.
        self._mix_fail_until = {}

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

    def _apply_global_config(self):
        try:
            if hasattr(self.session, 'config'):
                self.session.config.quality = self.quality
                if hasattr(self.session.config, 'set_quality'):
                    self.session.config.set_quality(self.quality)
        except Exception as e:
            logger.warning("Config sync warning: %s", e)

    def _apply_session_quality(self, quality):
        try:
            if hasattr(self.session, "config"):
                self.session.config.quality = quality
                if hasattr(self.session.config, "set_quality"):
                    self.session.config.set_quality(quality)
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
                self.save_session()
                self.refresh_favorite_ids()
                self._apply_global_config()
                return True
        except Exception as e:
            kind = classify_exception(e)
            logger.error("Login failed [%s]: %s", kind, e)
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

    def try_load_session(self):
        if os.path.exists(self.legacy_token_file) and not os.path.exists(self.token_file):
            logger.warning("Legacy token file detected (.pkl). Please login again to migrate.")
            return False

        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    d = json.load(f)

                required = ('token_type', 'access_token', 'refresh_token', 'expiry_time')
                if not all(k in d for k in required):
                    logger.warning("Session file invalid: missing required fields.")
                    return False

                self.session.load_oauth_session(
                    d['token_type'],
                    d['access_token'],
                    d['refresh_token'],
                    self._deserialize_expiry(d['expiry_time']),
                )
                if self.session.check_login():
                    self.user = self.session.user
                    self.refresh_favorite_ids()
                    self._apply_global_config() 
                    return True
            except Exception as e:
                logger.warning("Session load error [%s]: %s", classify_exception(e), e)
        return False

    def refresh_favorite_ids(self):
        try:
            if not self.user: return
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

    def toggle_album_favorite(self, album_id, add=True):
        try:
            if add:
                self.user.favorites.add_album(album_id)
                self.fav_album_ids.add(str(album_id))
            else:
                self.user.favorites.remove_album(album_id)
                self.fav_album_ids.discard(str(album_id))
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

    def _paginate_favorites_api(self, api_callable, limit=1000, page_size=100):
        if not callable(api_callable):
            return []

        target = max(0, int(limit or 0))
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
            if len(page) < size:
                break

            offset += len(page)
            if offset > 100000:
                break

        return merged[:target]

    def get_favorites(self, limit=20000):
        try: 
            if not self.user:
                return []
            fav = getattr(self.user, "favorites", None)
            artists_api = getattr(fav, "artists", None)
            return self._paginate_favorites_api(artists_api, limit=limit, page_size=100)
        except Exception as e:
            logger.warning("Failed to fetch favorite artists: %s", e)
            return []

    def get_recent_albums(self, limit=20000):
        try:
            if not self.user:
                return []
            fav = getattr(self.user, "favorites", None)
            albums_api = getattr(fav, "albums", None)
            return self._paginate_favorites_api(albums_api, limit=limit, page_size=100)
        except Exception as e:
            logger.warning("Failed to fetch recent albums: %s", e)
            return []

    def get_favorite_tracks(self, limit=50):
        try:
            if not self.user:
                return []
            target = max(0, int(limit))
            if target <= 0:
                return []

            tracks_api = getattr(self.user.favorites, "tracks", None)
            if not callable(tracks_api):
                return []

            def _normalize(seq):
                if isinstance(seq, list):
                    return seq
                return list(seq or [])

            def _fetch_page(offset, page_size):
                call_specs = (
                    {"limit": page_size, "offset": offset},
                    {"offset": offset, "limit": page_size},
                    {"limit": page_size},
                    {},
                )
                for kwargs in call_specs:
                    try:
                        res = tracks_api(**kwargs) if kwargs else tracks_api()
                    except TypeError:
                        continue
                    page = res() if callable(res) else res
                    return _normalize(page), kwargs
                # Fallback: plain call if all signature probes failed.
                res = tracks_api()
                page = res() if callable(res) else res
                return _normalize(page), {}

            page_size = min(100, max(1, target))
            merged = []
            seen_ids = set()
            offset = 0
            while len(merged) < target:
                page, used_kwargs = _fetch_page(offset, page_size)
                if not page:
                    break

                new_added = 0
                for tr in page:
                    tid = getattr(tr, "id", None)
                    key = f"id:{tid}" if tid is not None else f"obj:{id(tr)}"
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    merged.append(tr)
                    new_added += 1
                    if len(merged) >= target:
                        break

                # Stop if paging is unsupported or no forward progress.
                if "offset" not in used_kwargs or new_added == 0:
                    break
                if len(page) < page_size:
                    break

                offset += len(page)
                if offset > 10000:
                    break

            return merged[:target]
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
            pl = self.user.create_playlist(title, desc)
            logger.info("Cloud playlist created: id=%s name=%r", getattr(pl, "id", None), title)
            return pl
        except Exception as e:
            logger.warning("Failed to create cloud playlist %r: %s", title, e)
            return None

    def add_tracks_to_cloud_playlist(self, playlist_or_id, tracks, dedupe=True, batch_size=100):
        pl = self._resolve_user_playlist(playlist_or_id)
        if pl is None:
            return {"ok": False, "playlist_id": None, "requested": 0, "added": 0, "skipped_invalid": 0}
        if not hasattr(pl, "add"):
            logger.warning("Resolved playlist does not support add(): id=%s", getattr(pl, "id", None))
            return {"ok": False, "playlist_id": getattr(pl, "id", None), "requested": 0, "added": 0, "skipped_invalid": 0}

        raw_ids = []
        skipped_invalid = 0
        for t in list(tracks or []):
            tid = None
            if isinstance(t, (str, int)):
                tid = str(t).strip()
            elif isinstance(t, dict):
                tid = str(t.get("track_id") or t.get("id") or "").strip()
            else:
                tid = str(getattr(t, "id", "") or "").strip()
            if not tid:
                skipped_invalid += 1
                continue
            raw_ids.append(tid)

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
        try:
            # History/Local objects may only contain artist id/name and
            # do not expose get_albums(). Resolve to a real artist first.
            if isinstance(art, (int, str)):
                art = self.session.artist(art)
            elif hasattr(art, "id") and not hasattr(art, "get_albums"):
                art = self.session.artist(getattr(art, "id"))

            res = art.get_albums()
            return res() if callable(res) else res
        except Exception as e:
            logger.warning("Failed to fetch albums for artist %s: %s", getattr(art, "id", "unknown"), e)
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
            return candidates[0]

        return None

    # ==========================================
    # [核心修改] 带过滤功能的 get_home_page
    # ==========================================
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
            if hasattr(self.session, 'home'):
                logger.debug("Fetching session.home()...")
                home = self.session.home()
                if hasattr(home, 'categories'):
                    for category in home.categories:
                        title = category.title
                        title_lower = title.lower()
                        
                        # [过滤逻辑] 检查标题是否包含任一关键词
                        is_allowed = any(k in title_lower for k in ALLOWED_KEYWORDS)
                        
                        if is_allowed:
                            section = {
                                'title': title,
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

    def _process_generic_item(self, item):
        try:
            # 基础信息
            data = {
                'obj': item, 
                'name': getattr(item, 'title', getattr(item, 'name', 'Unknown')),
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
            # 1. 解包
            if isinstance(item, dict) and 'obj' in item:
                item = item['obj']

            # 2. 优先尝试直接调用方法
            if hasattr(item, 'tracks') and callable(item.tracks):
                return item.tracks()
            if hasattr(item, 'items') and callable(item.items):
                return self._extract_tracks_from_items(item.items())

            # 3. 重新抓取
            item_type = type(item).__name__
            item_id = getattr(item, 'id', None)
            
            if not item_id: return []

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
            
            elif 'Playlist' in item_type:
                pl = self.session.playlist(item_id)
                return self._extract_tracks_from_items(pl.items())
            
            elif 'Album' in item_type:
                alb = self.session.album(item_id)
                return alb.tracks()

            if hasattr(item, 'id'):
                return self.session.album(item.id).tracks()
            
            return []
        except Exception as e:
            logger.warning("Get tracks error [%s]: %s", classify_exception(e), e)
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
            for attr in ['picture', 'cover']:
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
        # 3a. 对于 Playlist，部分对象是轻量快照，可能没有实时封面字段。
        #     按 id 重新拉一次完整对象再尝试取图。
        if not uuid and "Playlist" in type(obj).__name__:
            pl_id = getattr(obj, "id", None)
            if pl_id:
                try:
                    full_pl = self.session.playlist(pl_id)
                    if full_pl:
                        # 先走通用扫描，避免重复执行整段提取逻辑。
                        scanned = self._scan_image_like_attrs(full_pl, size=size)
                        if scanned:
                            return scanned
                        for attr in ("picture", "square_picture", "wide_image", "image", "cover"):
                            val = getattr(full_pl, attr, None)
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
                except Exception as e:
                    logger.debug("Playlist artwork refresh failed for %s: %s", pl_id, e)

        # 3b. 如果还是没找到，且是单曲，尝试用专辑封面
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

    def get_artist_artwork_url(self, artist_obj, size=320):
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
                    target = candidates[0]
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
                self._artist_artwork_cache[cache_key] = chosen_url

    def get_stream_url(self, track):
        preferred = self.quality
        qualities = self._get_stream_quality_fallback_chain()
        last_exc = None
        try:
            for idx, q in enumerate(qualities):
                try:
                    self._apply_session_quality(q)
                    full_track = self.session.track(track.id)
                    url = full_track.get_url()
                    if idx > 0:
                        logger.warning(
                            "Stream quality fallback used for %s: preferred=%s actual=%s",
                            getattr(track, "name", "unknown"),
                            preferred,
                            q,
                        )
                    else:
                        logger.info("Stream URL resolved for %s with quality %s", track.name, q)
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

    def search_items(self, query):
        logger.info("Starting search for query: '%s'", query)
        results = {'artists': [], 'albums': [], 'tracks': []}
        
        # 1. 检查登录状态
        if not self.session.check_login():
            logger.warning("Session expired or not logged in during search.")
            return results

        try:
            # 2. 明确指定搜索模型
            res = self.session.search(query, limit=300)
            logger.debug("Raw search response type: %s", type(res))

            # 3. 兼容性处理 (部分版本返回字典，部分返回对象)
            # 处理歌手
            artists_raw = None
            if hasattr(res, 'artists'): artists_raw = res.artists
            elif isinstance(res, dict): artists_raw = res.get('artists')
            
            if artists_raw:
                results['artists'] = (artists_raw() if callable(artists_raw) else artists_raw)[:6]
            
            # 处理专辑 (Tidal 专辑属性通常是 .albums)
            albums_raw = None
            if hasattr(res, 'albums'): albums_raw = res.albums
            elif isinstance(res, dict): albums_raw = res.get('albums')
            
            if albums_raw:
                results['albums'] = (albums_raw() if callable(albums_raw) else albums_raw)[:6]
            
            # 处理歌曲
            tracks_raw = None
            if hasattr(res, 'tracks'): tracks_raw = res.tracks
            elif isinstance(res, dict): tracks_raw = res.get('tracks')
            
            if tracks_raw:
                results['tracks'] = list(tracks_raw() if callable(tracks_raw) else tracks_raw)

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
        self.lyrics_cache[track_id] = value
        if len(self.lyrics_cache) <= self.max_lyrics_cache:
            return
        oldest_key = next(iter(self.lyrics_cache))
        self.lyrics_cache.pop(oldest_key, None)

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
        self._apply_global_config()
