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
                print(f"[Backend] Global session config updated to: {self.quality}")
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
        except Exception as e:
            print(f"Toggle Fav Error: {e}")
            return False

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

    def get_mixes(self):
        try:
            if hasattr(self.session, 'mixes'):
                res = self.session.mixes()
                return res() if callable(res) else res
            elif hasattr(self.user, 'mixes'):
                res = self.user.mixes()
                return res() if callable(res) else res
            return []
        except Exception as e:
            print(f"[Backend] Get Mixes Error: {e}")
            return []

    def get_tracks(self, item):
        try:
            if hasattr(item, 'tracks') and callable(item.tracks):
                res = item.tracks()
                return res() if callable(res) else res
            
            if hasattr(item, 'items') and callable(item.items):
                res = item.items()
                items = res() if callable(res) else res
                if items and hasattr(items[0], 'track'):
                     return [i.track for i in items if i.track] 
                return items

            if hasattr(item, 'id'):
                print(f"[Backend] Fetching deep object for ID: {item.id}")
                real_album = self.session.album(item.id)
                if real_album:
                    res = real_album.tracks()
                    return res() if callable(res) else res
            
            return []
        except Exception as e:
            print(f"Get Tracks Error: {e}")
            return []

    # [关键修复] 升级版 get_artwork_url，兼容 Mixes/Playlists 的 UUID 图片
    def get_artwork_url(self, obj, size=320):
        if not obj: return None
        
        # 1. 尝试直接获取 Mix/Playlist 的 image 属性 (通常是 UUID 字符串)
        # 这是 My Mix 封面最常见的存储位置
        if hasattr(obj, 'image') and isinstance(obj.image, str) and obj.image:
             path = obj.image.replace('-', '/')
             return f"https://resources.tidal.com/images/{path}/{size}x{size}.jpg"

        # 2. 尝试处理 images 对象/字典/列表
        if hasattr(obj, 'images'):
            try:
                # 如果是 tidalapi 的 Images 对象，直接读属性
                if hasattr(obj.images, 'large'): return obj.images.large
                if hasattr(obj.images, 'medium'): return obj.images.medium
                
                # 如果是字典
                if isinstance(obj.images, dict):
                    return list(obj.images.values())[0] 
                # 如果是列表
                elif isinstance(obj.images, list) and len(obj.images) > 0:
                     return obj.images[0].url
            except: pass

        # 3. 回退到 Album 逻辑 (针对 Tracks)
        if hasattr(obj, 'album') and obj.album: obj = obj.album
            
        # 4. 处理 Artists 的 picture
        if hasattr(obj, 'picture'):
            if callable(obj.picture): return obj.picture(width=size, height=size)
            elif isinstance(obj.picture, str): 
                try: return f"https://resources.tidal.com/images/{obj.picture.replace('-', '/')}/{size}x{size}.jpg"
                except: pass

        # 5. 处理 Albums 的 cover
        if hasattr(obj, 'cover'):
            if callable(obj.cover): return obj.cover(width=size, height=size)
            elif isinstance(obj.cover, str):
                try: return f"https://resources.tidal.com/images/{obj.cover.replace('-', '/')}/{size}x{size}.jpg"
                except: pass
        
        # 6. 处理本地对象可能存在的 cover_url
        if hasattr(obj, 'cover_url'): return obj.cover_url
        
        return None

    def get_stream_url(self, track):
        try:
            self._apply_global_config()
            full_track = self.session.track(track.id)
            url = full_track.get_url()
            print(f"[Backend] Successfully fetched URL for {track.name} using quality: {self.quality}")
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
        
        if found_quality is None:
            found_quality = target_keys[0]

        self.quality = found_quality
        print(f"[Backend] Quality resolved to: {self.quality} for {mode_str}")
        self._apply_global_config()

    def search_artist(self, query):
        try:
            return self.session.search(query, models=[tidalapi.models.Artist], limit=10).artists
        except: return []

    def search_items(self, query):
        print(f"[Backend] Searching for: {query}")
        results = {'artists': [], 'albums': [], 'tracks': []}
        try:
            res = self.session.search(query, limit=50)
            if hasattr(res, 'artists'):
                raw = res.artists; results['artists'] = (raw() if callable(raw) else raw)[:6]
            elif isinstance(res, dict) and 'artists' in res: results['artists'] = res['artists'][:6]

            if hasattr(res, 'albums'):
                raw = res.albums; results['albums'] = (raw() if callable(raw) else raw)[:6]
            elif isinstance(res, dict) and 'albums' in res: results['albums'] = res['albums'][:6]

            if hasattr(res, 'tracks'):
                raw = res.tracks; results['tracks'] = (raw() if callable(raw) else raw)[:30]
            elif isinstance(res, dict) and 'tracks' in res: results['tracks'] = res['tracks'][:30]
            return results
        except Exception as e:
            print(f"[Search Error]: {e}")
            return results

    def logout(self):
        print("[Backend] Logging out...")
        if os.path.exists(self.token_file):
            try: os.remove(self.token_file)
            except: pass

        self.user = None
        self.session = tidalapi.Session()
        self.fav_album_ids = set()
        self._apply_global_config()
