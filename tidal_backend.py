import tidalapi
import logging
import os
import pickle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TidalBackend:
    def __init__(self):
        self.session = tidalapi.Session()
        self.token_file = os.path.expanduser("~/.cache/hiresti_token.pkl")
        self.user = None
        self.quality = self._get_best_quality()
        self._apply_global_config() 
        self.fav_album_ids = set()

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
            print(f"[Backend] Config Sync Warning: {e}")

    def start_oauth(self):
        self.session = tidalapi.Session()
        self._apply_global_config()
        login_url_obj, future = self.session.login_oauth()
        if hasattr(login_url_obj, 'verification_uri_complete'):
            url = login_url_obj.verification_uri_complete
        else:
            url = str(login_url_obj)
        print(f"[Backend] OAuth URL: {url}")
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
            print(f"Login Failed: {e}")
        return False

    def check_login(self):
        return self.session.check_login()

    def save_session(self):
        os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
        with open(self.token_file, 'wb') as f:
            data = {
                'token_type': self.session.token_type,
                'access_token': self.session.access_token,
                'refresh_token': self.session.refresh_token,
                'expiry_time': self.session.expiry_time
            }
            pickle.dump(data, f)

    def try_load_session(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'rb') as f:
                    d = pickle.load(f)
                    self.session.load_oauth_session(
                        d['token_type'], d['access_token'], d['refresh_token'], d['expiry_time']
                    )
                if self.session.check_login():
                    self.user = self.session.user
                    self.refresh_favorite_ids()
                    self._apply_global_config() 
                    return True
            except Exception as e:
                print(f"Session Load Error: {e}")
        return False

    def refresh_favorite_ids(self):
        try:
            if not self.user: return
            favs = self.user.favorites.albums()
            res = favs() if callable(favs) else favs
            self.fav_album_ids = {str(a.id) for a in res}
        except: pass

    def is_favorite(self, album_id):
        return str(album_id) in self.fav_album_ids

    def is_artist_favorite(self, artist_id):
        try:
            favs = self.user.favorites.artists()
            res = favs() if callable(favs) else favs
            return any(str(a.id) == str(artist_id) for a in res)
        except: return False

    def toggle_album_favorite(self, album_id, add=True):
        try:
            if add:
                self.user.favorites.add_album(album_id)
                self.fav_album_ids.add(str(album_id))
            else:
                self.user.favorites.remove_album(album_id)
                self.fav_album_ids.discard(str(album_id))
            return True
        except: return False

    def toggle_artist_favorite(self, artist_id, add=True):
        try:
            if add: self.user.favorites.add_artist(artist_id)
            else: self.user.favorites.remove_artist(artist_id)
            return True
        except: return False

    def get_favorites(self):
        try: 
            res = self.user.favorites.artists()
            return res() if callable(res) else res
        except: return []

    def get_recent_albums(self):
        try:
            res = self.user.favorites.albums()
            return res() if callable(res) else res
        except: return []

    def get_albums(self, art):
        try:
            res = art.get_albums()
            return res() if callable(res) else res
        except: return []

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
                print("[Backend] Fetching session.home()...")
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
                print("[Backend] session.home() not found, using fallback.")
                mixes = self._get_fallback_mixes()
                if mixes: home_sections.append({'title': 'Mixes for you', 'items': mixes})
                
        except Exception as e:
            print(f"[Backend] Get Home Page Error: {e}")
            
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
        except:
            return None

    def _get_fallback_mixes(self):
        try:
            if hasattr(self.user, 'mixes'):
                raw = self.user.mixes()
                return [self._process_generic_item(m) for m in (raw() if callable(raw) else raw)]
        except: return []

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

            print(f"[Backend] Reloading {item_type} with ID {item_id}")

            if 'Mix' in item_type:
                mix = self.session.mix(item_id)
                return self._extract_tracks_from_items(mix.items())
            
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
            print(f"Get Tracks Error: {e}")
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
        if isinstance(obj, dict) and 'obj' in obj: obj = obj['obj']
        if not obj: return None
        
        if hasattr(obj, 'image') and isinstance(obj.image, str) and obj.image:
             path = obj.image.replace('-', '/')
             return f"https://resources.tidal.com/images/{path}/{size}x{size}.jpg"

        if hasattr(obj, 'images'):
            try:
                if hasattr(obj.images, 'large'): return obj.images.large
                if hasattr(obj.images, 'medium'): return obj.images.medium
                if isinstance(obj.images, dict): return list(obj.images.values())[0] 
                elif isinstance(obj.images, list) and len(obj.images) > 0: return obj.images[0].url
            except: pass

        if hasattr(obj, 'album') and obj.album: obj = obj.album
            
        if hasattr(obj, 'picture'):
            if callable(obj.picture): return obj.picture(width=size, height=size)
            elif isinstance(obj.picture, str): 
                try: return f"https://resources.tidal.com/images/{obj.picture.replace('-', '/')}/{size}x{size}.jpg"
                except: pass

        if hasattr(obj, 'cover'):
            if callable(obj.cover): return obj.cover(width=size, height=size)
            elif isinstance(obj.cover, str):
                try: return f"https://resources.tidal.com/images/{obj.cover.replace('-', '/')}/{size}x{size}.jpg"
                except: pass
        
        if hasattr(obj, 'cover_url'): return obj.cover_url
        
        return None

    def get_stream_url(self, track):
        try:
            self._apply_global_config()
            full_track = self.session.track(track.id)
            url = full_track.get_url()
            print(f"[Backend] Stream URL for {track.name}: {self.quality}")
            return url
        except Exception as e:
            print(f"[Backend] Stream URL Error: {e}")
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
            return self.session.search(query, models=[tidalapi.models.Artist], limit=10).artists
        except: return []

    def search_items(self, query):
        results = {'artists': [], 'albums': [], 'tracks': []}
        try:
            res = self.session.search(query, limit=50)
            if hasattr(res, 'artists'):
                raw = res.artists; results['artists'] = (raw() if callable(raw) else raw)[:6]
            if hasattr(res, 'albums'):
                raw = res.albums; results['albums'] = (raw() if callable(raw) else raw)[:6]
            if hasattr(res, 'tracks'):
                raw = res.tracks; results['tracks'] = (raw() if callable(raw) else raw)[:30]
            return results
        except Exception as e:
            return results

    # --- tidal_backend.py --- 添加在 get_stream_url 附近

    def get_lyrics(self, track_id):
        print(f"[Backend] Fetching lyrics for Track ID: {track_id}...") # <--- 日志
        try:
            lyrics_obj = self.session.track(track_id).lyrics()

            if not lyrics_obj:
                print("[Backend] Result: None (No lyrics object found)")
                return None

            if hasattr(lyrics_obj, 'subtitles') and lyrics_obj.subtitles:
                print("[Backend] Result: Found Synced Lyrics (LRC)")
                return lyrics_obj.subtitles

            if hasattr(lyrics_obj, 'text') and lyrics_obj.text:
                print("[Backend] Result: Found Static Text Lyrics")
                return lyrics_obj.text

            print("[Backend] Result: Lyrics object empty")
            return None
        except Exception as e:
            # 404 是正常的（表示没歌词），不打印错误堆栈
            if "404" in str(e):
                print("[Backend] Result: 404 Not Found (Track has no lyrics)")
            else:
                print(f"[Backend] Error: {e}")
            return None

    def logout(self):
        if os.path.exists(self.token_file):
            try: os.remove(self.token_file)
            except: pass
        self.user = None
        self.session = tidalapi.Session()
        self.fav_album_ids = set()
        self._apply_global_config()
