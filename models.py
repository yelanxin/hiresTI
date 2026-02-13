import os
import time
import json

class LocalAlbum:
    def __init__(self, data):
        self.id = data.get('id')
        self.name = data.get('name')
        # 伪装成 Tidal 的 Artist 对象，防止 main.py 报错
        self.artist = type('obj', (object,), {'name': data.get('artist', 'Unknown')})
        self.cover_url = data.get('cover_url')
        self.release_date = None
        self.num_tracks = '?'

class HistoryManager:
    def __init__(self):
        self.path = os.path.expanduser("~/.cache/hiresti/history.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def add(self, track, cover_url):
        try:
            history = self.load_raw()
            alb_id = track.album.id
            # 去重：如果已存在则移除旧的
            history = [h for h in history if h.get('id') != alb_id]
            # 新增到最前面
            new_entry = {
                'id': alb_id,
                'name': track.album.name,
                'artist': getattr(track.artist, 'name', 'Unknown'),
                'cover_url': cover_url,
                'timestamp': time.time()
            }
            history.insert(0, new_entry)
            history = history[:50] # 保留最近 50 条
            with open(self.path, 'w') as f:
                json.dump(history, f)
        except:
            pass

    def load_raw(self):
        if not os.path.exists(self.path): return []
        try:
            with open(self.path, 'r') as f:
                return json.load(f)
        except: return []

    # [必须确保有这个方法]
    def get_albums(self):
        raw = self.load_raw()
        return [LocalAlbum(item) for item in raw]
