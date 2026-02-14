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

    # [新增] 强制将音质应用到全局 Session Config
    # 这是修复旧版库 "Always AAC" 问题的关键
    def _apply_global_config(self):
        try:
            if hasattr(self.session, 'config'):
                print(f"[Backend] Applying global quality setting: {self.quality}")
                self.session.config.quality = self.quality
        except Exception as e:
            print(f"[Backend] Warning: Could not set session config: {e}")

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

    # ==========================================
    # [兼容性修复] 获取流媒体链接
    # ==========================================
    def get_stream_url(self, track):
        # 旧版库 get_url() 不接受参数，必须依赖 session.config.quality
        # 我们这里依然尝试传参，但更重要的是依赖 _apply_global_config 的效果
        try:
            return self.session.track(track.id).get_url(audio_quality=self.quality)
        except TypeError:
            pass # 参数名错误
        except Exception:
            pass

        try:
            return self.session.track(track.id).get_url(quality=self.quality)
        except TypeError:
            pass
        except Exception:
            pass
        
        # 保底：不传参数 (此时会使用 session.config.quality 的全局值)
        try:
            print("[Backend] Using default get_url() (relying on global config)")
            return self.session.track(track.id).get_url()
        except Exception as e:
            print(f"Stream URL Error: {e}")
            return None
    
    # [修复] 切换音质时，同步更新全局配置
    def set_quality_mode(self, mode_str):
        mapping = {
            "Hi-Res (FLAC)": 'HI_RES',   
            "Standard (AAC)": 'HIGH'     
        }
        
        target_val = mapping.get(mode_str, 'LOSSLESS')
        
        if hasattr(tidalapi.Quality, target_val):
            self.quality = getattr(tidalapi.Quality, target_val)
            print(f"[Tidal] Quality set to: {self.quality} ({mode_str})")
        else:
            print(f"[Tidal] Warning: Quality {target_val} not found, using LOSSLESS.")
            self.quality = getattr(tidalapi.Quality, 'LOSSLESS', 'LOSSLESS')
            
        # 立即应用到全局配置
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
