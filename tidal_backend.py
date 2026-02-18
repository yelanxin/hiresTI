import tidalapi
import logging
import os
import json
import time
from datetime import datetime
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
        self.lyrics_cache = {}
        self.max_lyrics_cache = 300
        # Circuit breaker for unstable mix endpoint.
        self._mix_fail_until = {}

    def _get_best_quality(self):
        for q in ['HI_RES', 'MASTER', 'LOSSLESS']:
            if hasattr(tidalapi.Quality, q):
                val = getattr(tidalapi.Quality, q)
                if not callable(val): return val
        return getattr(tidalapi.Quality, 'LOSSLESS', 'LOSSLESS')

    def _apply_global_config(self):
        try:
            if hasattr(self.session, 'config'):
                self.session.config.quality = self.quality
                if hasattr(self.session.config, 'set_quality'):
                    self.session.config.set_quality(self.quality)
        except Exception as e:
            logger.warning("Config sync warning: %s", e)

    def start_oauth(self):
        self.session = tidalapi.Session()
        self._apply_global_config()
        login_url_obj, future = self.session.login_oauth()
        if hasattr(login_url_obj, 'verification_uri_complete'):
            url = login_url_obj.verification_uri_complete
        else:
            url = str(login_url_obj)
        logger.info("OAuth URL prepared.")
        return url, future

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
            logger.error("Login failed: %s", e)
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
            favs = self.user.favorites.albums()
            res = favs() if callable(favs) else favs
            self.fav_album_ids = {str(a.id) for a in res}
        except Exception as e:
            logger.debug("Failed to refresh favorite ids: %s", e)

    def is_favorite(self, album_id):
        return str(album_id) in self.fav_album_ids

    def is_artist_favorite(self, artist_id):
        try:
            favs = self.user.favorites.artists()
            res = favs() if callable(favs) else favs
            return any(str(a.id) == str(artist_id) for a in res)
        except Exception as e:
            logger.debug("Failed to check artist favorite status for %s: %s", artist_id, e)
            return False

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
            if add: self.user.favorites.add_artist(artist_id)
            else: self.user.favorites.remove_artist(artist_id)
            return True
        except Exception as e:
            logger.warning("Failed to toggle artist favorite for %s (add=%s): %s", artist_id, add, e)
            return False

    def get_favorites(self):
        try: 
            res = self.user.favorites.artists()
            return res() if callable(res) else res
        except Exception as e:
            logger.warning("Failed to fetch favorite artists: %s", e)
            return []

    def get_recent_albums(self):
        try:
            res = self.user.favorites.albums()
            return res() if callable(res) else res
        except Exception as e:
            logger.warning("Failed to fetch recent albums: %s", e)
            return []

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
                        logger.debug("Artwork provider '%s' failed for %s: %s", attr, type(obj).__name__, e)
            
            # 检查 images 集合
            if hasattr(obj, 'images') and obj.images:
                try:
                    if hasattr(obj.images, 'large'): return obj.images.large
                    if isinstance(obj.images, dict): return list(obj.images.values())[0]
                except Exception as e:
                    logger.debug("Failed to resolve artwork from images on %s: %s", type(obj).__name__, e)

            # 属性探测
            check_attrs = ['picture_id', 'cover_id', 'picture', 'cover', 'image']
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

    def get_stream_url(self, track):
        try:
            self._apply_global_config()
            full_track = self.session.track(track.id)
            url = full_track.get_url()
            logger.info("Stream URL resolved for %s with quality %s", track.name, self.quality)
            return url
        except Exception as e:
            logger.warning("Stream URL error [%s]: %s", classify_exception(e), e)
            return None

    def set_quality_mode(self, mode_str):
        mapping = {
            "Max (Up to 24-bit, 192 kHz)": ['HI_RES', 'MASTER'], 
            "High (16-bit, 44.1 kHz)": ['LOSSLESS'],             
            "Low (320 kbps)": ['HIGH', 'LOW']                    
        }
        target_keys = mapping.get(mode_str, ['HIGH'])
        found_quality = None
        for key in target_keys:
            if hasattr(tidalapi.Quality, key):
                found_quality = getattr(tidalapi.Quality, key)
                break
        if found_quality is None: found_quality = target_keys[0]
        self.quality = found_quality
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
            res = self.session.search(query, limit=50)
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
                results['tracks'] = (tracks_raw() if callable(tracks_raw) else tracks_raw)[:30]

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
        self._apply_global_config()
