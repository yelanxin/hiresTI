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
        self.fav_album_ids = set()

    def _get_best_quality(self):
        for q in ['HI_RES', 'MASTER', 'LOSSLESS']:
            if hasattr(tidalapi.Quality, q):
                val = getattr(tidalapi.Quality, q)
                if not callable(val): return val
        return 'LOSSLESS'

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

    def toggle_artist_favorite(self, artist_id, is_add):
        try:
            if is_add: self.user.favorites.add_artist(artist_id)
            else: self.user.favorites.remove_artist(artist_id)
            return True
        except: return False

    def toggle_album_favorite(self, album_id, is_add):
        try:
            if is_add: self.user.favorites.add_album(album_id); self.fav_album_ids.add(str(album_id))
            else: self.user.favorites.remove_album(album_id); self.fav_album_ids.discard(str(album_id))
            return True
        except: return False

    def get_artwork_url(self, obj, size=640):
        if not obj: return None
        if hasattr(obj, 'cover_url') and obj.cover_url: return str(obj.cover_url)
        try:
            if hasattr(obj, 'picture'):
                try: return obj.picture(width=size, height=size)
                except: pass
            if hasattr(obj, 'image'):
                try: return obj.image(size=size)
                except:
                    try: return obj.image(width=size, height=size)
                    except: return obj.image()
            if hasattr(obj, 'album') and obj.album:
                return self.get_artwork_url(obj.album, size)
        except: pass
        return None

    def get_tracks(self, alb):
        try:
            if hasattr(alb, 'get_tracks') or hasattr(alb, 'tracks'):
                res = alb.get_tracks() if hasattr(alb, 'get_tracks') else alb.tracks
                return res() if callable(res) else res
            else:
                full_album = self.session.album(str(alb.id))
                return full_album.tracks()
        except: return []


    def set_quality_mode(self, label):
        """
        可靠的音质切换逻辑：同时兼容大小写常量，并强制同步 Session
        """
        import tidalapi

        # 1. 定义目标优先级队列
        if "Hi-Res" in label:
            # 优先找母带/高解析，没有就找无损
            candidates = ['HI_RES', 'hi_res', 'MASTER', 'master', 'LOSSLESS', 'lossless']
        else:
            # 默认标准音质
            candidates = ['HIGH', 'high']

        target_quality = None

        # 2. 穷举查找存在的常量
        for c in candidates:
            if hasattr(tidalapi.Quality, c):
                val = getattr(tidalapi.Quality, c)
                # 排除掉方法，只取属性
                if not callable(val):
                    target_quality = val
                    logger.info(f"匹配到音质常量: tidalapi.Quality.{c}")
                    break

        # 3. 兜底策略：如果都没找到（极少见），回退到默认
        if target_quality is None:
            # 尝试硬编码 fallback
            if "Hi-Res" in label:
                 # 假设是一个较新的版本，尝试直接赋值字符串（某些版本允许）
                 target_quality = 'HI_RES'
            else:
                 target_quality = 'HIGH'
            logger.warning(f"未找到标准常量，使用 Fallback: {target_quality}")

        self.quality = target_quality

        # 4. 强制应用到 Session
        try:
            self.session.audio_quality = self.quality
            if hasattr(self.session, 'config'):
                self.session.config.quality = self.quality
        except Exception as e:
            logger.error(f"应用音质设置失败: {e}")

    def get_stream_url(self, track):
        try:
            # 双重保险：获取链接前再次强制声明质量
            self.session.audio_quality = self.quality
            if hasattr(self.session, 'config'):
                self.session.config.quality = self.quality

            url = track.get_url()
            return url() if callable(url) else url
        except: return ""


    def start_oauth(self):
        """
        启动 OAuth 流程（修复版：适配新版 tidalapi 返回结构）
        """
        # 1. 调用登录接口
        if hasattr(self.session, 'login_oauth_64'):
            res = self.session.login_oauth_64()
        else:
            res = self.session.login_oauth()

        # 2. 打印调试信息（可选，方便排查）
        print(f"[DEBUG] OAuth 返回结构长度: {len(res)}")

        # 3. 核心修复：
        # 新版 tidalapi 返回的是 (DeviceCode, Future)
        # res[0] -> DeviceCode 对象 (包含 verification_uri_complete)
        # res[1] -> Future 对象 (用于等待登录完成)

        device_code = res[0]
        future = res[1]

        # 获取完整验证链接
        login_url = device_code.verification_uri_complete

        return str(login_url), future

    def finish_login(self, fut):
        try:
            fut.result()
            if self.session.check_login():
                self.user = self.session.user; self.save_session(); self.refresh_favorite_ids(); return True
        except: pass
        return False

    def save_session(self):
        os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
        with open(self.token_file, 'wb') as f:
            pickle.dump({'token_type': self.session.token_type, 'access_token': self.session.access_token, 'refresh_token': self.session.refresh_token, 'expiry_time': self.session.expiry_time}, f)

    def try_load_session(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'rb') as f:
                    d = pickle.load(f); self.session.load_oauth_session(d['token_type'], d['access_token'], d['refresh_token'], d['expiry_time'])
                if self.session.check_login(): self.user = self.session.user; self.refresh_favorite_ids(); return True
            except: pass
        return False

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

    def search_artist(self, q):
        try: return self.session.search(q, models=[tidalapi.Artist]).get('artists', [])
        except: return []
