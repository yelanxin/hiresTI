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
        
        # [修改] 初始化时尝试同步 Config
        self.quality = self._get_best_quality()
        self._apply_global_config() 
        
        self.fav_album_ids = set()

    def _get_best_quality(self):
        # 优先检测 HI_RES (Max), 其次 MASTER (MQA), 最后 LOSSLESS (HiFi)
        for q in ['HI_RES', 'MASTER', 'LOSSLESS']:
            if hasattr(tidalapi.Quality, q):
                val = getattr(tidalapi.Quality, q)
                if not callable(val): return val
        return getattr(tidalapi.Quality, 'LOSSLESS', 'LOSSLESS')

    def _apply_global_config(self):
        try:
            if hasattr(self.session, 'config'):
                # 某些版本需要直接修改属性
                self.session.config.quality = self.quality
                # 某些版本可能需要通过 set 方法
                if hasattr(self.session.config, 'set_quality'):
                    self.session.config.set_quality(self.quality)
                print(f"[Backend] Global session config updated to: {self.quality}")
        except Exception as e:
            print(f"[Backend] Config Sync Warning: {e}")

    def start_oauth(self):
        # 重新创建 session 时也要应用配置
        self.session = tidalapi.Session()
        self._apply_global_config()

        # 获取 OAuth 链接和 future
        login_url_obj, future = self.session.login_oauth()

        # [关键修复] 显式转换并检查 URL
        # 有些版本需要访问 login_url_obj.verification_uri_complete
        if hasattr(login_url_obj, 'verification_uri_complete'):
            url = login_url_obj.verification_uri_complete
        else:
            url = str(login_url_obj)

        print(f"[Backend] OAuth URL: {url}") # 在终端打印出来，方便手动复制
        return url, future

    def finish_login(self, future):
        try:
            future.result()
            if self.session.check_login():
                self.user = self.session.user
                self.save_session()
                self.refresh_favorite_ids()
                # 登录成功后再次确保配置正确
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
                    self._apply_global_config() # 这里的也加上
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

    def get_tracks(self, album):
        try:
            if hasattr(album, 'id') and not (hasattr(album, 'tracks') and callable(album.tracks)):
                print(f"[Backend] Fetching tracks for history album ID: {album.id}")
                real_album = self.session.album(album.id)
                if real_album:
                    res = real_album.tracks()
                    return res() if callable(res) else res
            
            if hasattr(album, 'tracks') and callable(album.tracks):
                res = album.tracks()
                return res() if callable(res) else res
            
            return []
        except Exception as e:
            print(f"Get Tracks Error: {e}")
            return []

    def get_artwork_url(self, obj, size=320):
        if not obj: return None
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

    # [tidal_backend.py] 恢复稳健版
    def get_stream_url(self, track):
        """
        恢复最稳健的 URL 获取逻辑。
        不再显式传递参数，而是依赖全局 Session 配置。
        """
        try:
            # 1. 确保在获取 URL 之前，Session 的配置是最新的
            self._apply_global_config()
            
            # 2. 获取真正的 Track 对象
            full_track = self.session.track(track.id)
            
            # 3. 使用最原始的 get_url()。
            # 这是最兼容的方式，由库根据 self.session.config.quality 自动决定请求参数。
            url = full_track.get_url()
            
            print(f"[Backend] Successfully fetched URL for {track.name} using quality: {self.quality}")
            return url

        except Exception as e:
            print(f"[Backend] Stream URL Error: {e}")
            # 如果报错 401，通常是会话失效，建议重新登录
            return None

    def set_quality_mode(self, mode_str):
        # [修改] 官方三档映射逻辑
        # Max -> HI_RES (或 MASTER)
        # High -> LOSSLESS
        # Low -> HIGH (AAC 320)
        mapping = {
            "Max (Up to 24-bit, 192 kHz)": ['HI_RES', 'MASTER'], 
            "High (16-bit, 44.1 kHz)": ['LOSSLESS'],             
            "Low (320 kbps)": ['HIGH', 'LOW']                    
        }
        
        # 默认回退到 HIGH (即 320k AAC)，保证基本播放
        target_keys = mapping.get(mode_str, ['HIGH'])
        found_quality = None
        
        # 自动适配不同版本的 tidalapi 枚举值
        for key in target_keys:
            if hasattr(tidalapi.Quality, key):
                found_quality = getattr(tidalapi.Quality, key)
                break
        
        # 如果枚举值里没找到，尝试直接使用字符串（部分旧库支持）
        if found_quality is None:
            found_quality = target_keys[0]

        self.quality = found_quality
        print(f"[Backend] Quality resolved to: {self.quality} for {mode_str}")
            
        # 立即同步到全局 Session 配置
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
        # 1. 删除本地 Token 文件
        if os.path.exists(self.token_file):
            try: os.remove(self.token_file)
            except: pass

        # 2. 重置 Session 和 User
        self.user = None
        self.session = tidalapi.Session()
        self.fav_album_ids = set()

        # 3. 重新应用配置 (防止 session 重置后音质设置丢失)
        self._apply_global_config()
