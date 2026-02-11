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
        
        # 核心新增：本地缓存已收藏的专辑 ID，用于快速判断 UI 状态
        self.fav_album_ids = set()

        logger.info(f"初始化目标音质: {self.quality}")

    def _get_best_quality(self):
        for q in ['HI_RES', 'MASTER', 'LOSSLESS']:
            if hasattr(tidalapi.Quality, q):
                val = getattr(tidalapi.Quality, q)
                if not callable(val): return val
        return 'LOSSLESS'

    def get_stream_url(self, t):
        target_q = self.quality
        
        # 1. 设置 Session 配置
        if hasattr(self.session, 'config'):
            try:
                if getattr(self.session.config, 'quality', None) != target_q:
                    self.session.config.quality = target_q
            except: pass
        
        # 2. 尝试获取
        try:
            url = t.get_url() 
            if callable(url): url = url()
            if url: return url
        except: pass

        # 3. 强制 Session 调用
        try:
            url = None
            if hasattr(self.session, 'get_media_url'):
                url = self.session.get_media_url(t.id, target_q)
            elif hasattr(self.session, 'track_url'):
                url = self.session.track_url(t.id, target_q)
            if callable(url): url = url()
            if url: return url
        except: pass
        
        return ""

    # --- 收藏功能核心 ---
    def refresh_favorite_ids(self):
        """拉取所有收藏专辑的 ID，用于 UI 判断状态"""
        try:
            if not self.user: return
            # 获取收藏专辑（可能需要处理分页，这里简化获取默认列表）
            favs = self.user.favorites.albums()
            if callable(favs): favs = favs()
            self.fav_album_ids = {str(a.id) for a in favs}
            logger.info(f"已刷新收藏缓存，共 {len(self.fav_album_ids)} 张专辑")
        except Exception as e:
            logger.warning(f"刷新收藏列表失败: {e}")

    def is_favorite(self, album_id):
        return str(album_id) in self.fav_album_ids

    def toggle_album_favorite(self, album_id, is_add):
        """调用 Tidal 接口添加或移除收藏"""
        try:
            if is_add:
                self.user.favorites.add_album(album_id)
                self.fav_album_ids.add(str(album_id))
                logger.info(f"已收藏专辑: {album_id}")
            else:
                self.user.favorites.remove_album(album_id)
                if str(album_id) in self.fav_album_ids:
                    self.fav_album_ids.remove(str(album_id))
                logger.info(f"已取消收藏: {album_id}")
            return True
        except Exception as e:
            logger.error(f"收藏操作失败: {e}")
            return False

    # --- 基础方法 ---
    def start_oauth(self):
        m = 'login_oauth_64' if hasattr(self.session, 'login_oauth_64') else 'login_oauth'
        res = getattr(self.session, m)()
        url_obj = res[1] if len(res) >= 2 else res[0]
        fut = res[2] if len(res) == 3 else res[1]
        return str(getattr(url_obj, 'verification_uri_complete', url_obj)), fut

    def finish_login(self, fut):
        try:
            fut.result()
            if self.session.check_login():
                self.user = self.session.user
                self.save_session()
                # 登录成功后立即刷新 ID 缓存
                self.refresh_favorite_ids()
                return True
        except: pass
        return False

    def save_session(self):
        os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
        with open(self.token_file, 'wb') as f:
            pickle.dump({'token_type': self.session.token_type, 'access_token': self.session.access_token, 
                         'refresh_token': self.session.refresh_token, 'expiry_time': self.session.expiry_time}, f)

    def try_load_session(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'rb') as f:
                    d = pickle.load(f)
                    self.session.load_oauth_session(d['token_type'], d['access_token'], d['refresh_token'], d['expiry_time'])
                if self.session.check_login(): 
                    self.user = self.session.user
                    # 加载 session 后也要刷新 ID
                    self.refresh_favorite_ids()
                    return True
            except: pass
        return False

    def get_favorites(self):
        try:
            f = self.user.favorites if hasattr(self.user, 'favorites') else self.user.favorites()
            res = f.artists()
            return res() if callable(res) else res
        except: return []

    def get_recent_albums(self):
        try:
            f = self.user.favorites if hasattr(self.user, 'favorites') else self.user.favorites()
            res = f.albums()
            return res() if callable(res) else res
        except: return []

    def get_albums(self, art):
        try:
            res = art.get_albums() if hasattr(art, 'get_albums') else art.albums
            return res() if callable(res) else res
        except: return []

    def get_tracks(self, alb):
        try:
            res = alb.get_tracks() if hasattr(alb, 'get_tracks') else alb.tracks
            return res() if callable(res) else res
        except: return []

    def get_artwork_url(self, obj, size=640):
        try:
            url = None
            if hasattr(obj, 'image'):
                try: url = obj.image(size=size)
                except: 
                    try: url = obj.image(width=size, height=size)
                    except: url = obj.image()
            return str(url) if url else None
        except: return None

    def search_artist(self, q):
        try:
            res = self.session.search(q, models=[tidalapi.Artist]).get('artists', [])
            return res() if callable(res) else res
        except: return []

    def set_quality_mode(self, label):
        target_name = 'HIGH'
        if "Hi-Res" in label:
            for candidate in ['HI_RES', 'MASTER', 'LOSSLESS']:
                if hasattr(tidalapi.Quality, candidate) and not callable(getattr(tidalapi.Quality, candidate)):
                    target_name = candidate
                    break
        
        if hasattr(tidalapi.Quality, target_name):
            self.quality = getattr(tidalapi.Quality, target_name)
            logger.info(f"用户切换音质为: {self.quality}")
