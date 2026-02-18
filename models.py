import os
import time
import json
import uuid


class LocalAlbum:
    def __init__(self, data):
        self.id = data.get("id")
        self.name = data.get("name")
        # 伪装成 Tidal 的 Artist 对象，防止 main.py 报错
        self.artist = type(
            "obj",
            (object,),
            {
                "name": data.get("artist", "Unknown"),
                "id": data.get("artist_id"),
            },
        )
        self.cover_url = data.get("cover_url")
        self.release_date = None
        self.num_tracks = "?"


class LocalTrack:
    def __init__(self, data):
        self.id = data.get("id")
        self.name = data.get("name", "Unknown Track")
        self.duration = data.get("duration", 0) or 0
        self.cover = data.get("cover")
        self.artist = type(
            "obj",
            (object,),
            {
                "name": data.get("artist", "Unknown"),
                "id": data.get("artist_id"),
            },
        )
        self.album = type(
            "obj",
            (object,),
            {
                "id": data.get("album_id"),
                "name": data.get("album_name", "Unknown Album"),
                "cover": data.get("cover"),
            },
        )


class HistoryManager:
    def __init__(self, base_dir=None, scope_key="guest"):
        self.base_dir = os.path.expanduser(base_dir or "~/.cache/hiresti")
        self.scope_key = "guest"
        self.path = ""
        self.set_scope(scope_key)

    def set_scope(self, scope_key):
        key = str(scope_key or "guest").strip() or "guest"
        self.scope_key = key
        if key == "guest":
            # Keep legacy guest path for backward compatibility.
            self.path = os.path.join(self.base_dir, "history.json")
        else:
            self.path = os.path.join(self.base_dir, "profiles", key, "history.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def add(self, track, cover_url):
        try:
            history = self.load_raw()
            alb_obj = getattr(track, "album", None)
            art_obj = getattr(track, "artist", None)

            new_entry = {
                "type": "track_play",
                "track_id": getattr(track, "id", None),
                "track_name": getattr(track, "name", "Unknown Track"),
                "duration": getattr(track, "duration", 0) or 0,
                "album_id": getattr(alb_obj, "id", None),
                "album_name": getattr(alb_obj, "name", "Unknown Album"),
                "artist": getattr(art_obj, "name", "Unknown"),
                "artist_id": getattr(art_obj, "id", None),
                "cover": cover_url,
                "cover_url": cover_url,
                "timestamp": time.time(),
            }
            history.insert(0, new_entry)
            history = history[:500]
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(history, f)
        except Exception:
            pass

    def load_raw(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def to_local_track(self, entry):
        if not isinstance(entry, dict):
            return None
        track_id = entry.get("track_id")
        if not track_id:
            return None
        return LocalTrack(
            {
                "id": track_id,
                "name": entry.get("track_name") or entry.get("name") or "Unknown Track",
                "duration": entry.get("duration", 0),
                "artist": entry.get("artist", "Unknown"),
                "artist_id": entry.get("artist_id"),
                "album_id": entry.get("album_id") or entry.get("id"),
                "album_name": entry.get("album_name") or entry.get("name") or "Unknown Album",
                "cover": entry.get("cover") or entry.get("cover_url"),
            }
        )

    def get_recent_track_entries(self, limit=300):
        raw = self.load_raw()
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            if item.get("track_id"):
                out.append(item)
            if len(out) >= limit:
                break
        return out

    def get_top_tracks(self, limit=20):
        counts = {}
        latest_meta = {}
        for item in self.load_raw():
            if not isinstance(item, dict):
                continue
            tid = item.get("track_id")
            if not tid:
                continue
            key = str(tid)
            counts[key] = counts.get(key, 0) + 1
            if key not in latest_meta:
                latest_meta[key] = item
                continue
            prev = latest_meta.get(key) or {}
            prev_cover = prev.get("cover") or prev.get("cover_url")
            curr_cover = item.get("cover") or item.get("cover_url")
            # Keep newest record by default, but upgrade with any non-empty cover we find.
            if not prev_cover and curr_cover:
                merged = dict(prev)
                merged["cover"] = item.get("cover")
                merged["cover_url"] = item.get("cover_url")
                if not merged.get("album_id") and item.get("album_id"):
                    merged["album_id"] = item.get("album_id")
                if (not merged.get("album_name")) and item.get("album_name"):
                    merged["album_name"] = item.get("album_name")
                latest_meta[key] = merged

        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        out = []
        for tid, cnt in ranked[:limit]:
            tr = self.to_local_track(latest_meta.get(tid, {}))
            if tr is None:
                continue
            tr.play_count = cnt
            out.append(tr)
        return out

    # [必须确保有这个方法]
    def get_albums(self):
        raw = self.load_raw()
        seen = set()
        albums = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            alb_id = item.get("album_id") or item.get("id")
            if not alb_id or alb_id in seen:
                continue
            seen.add(alb_id)
            albums.append(
                LocalAlbum(
                    {
                        "id": alb_id,
                        "name": item.get("album_name") or item.get("name") or "Unknown Album",
                        "artist": item.get("artist", "Unknown"),
                        "artist_id": item.get("artist_id"),
                        "cover_url": item.get("cover_url") or item.get("cover"),
                    }
                )
            )
            if len(albums) >= 20:
                break
        return albums


class PlaylistManager:
    def __init__(self, base_dir=None, scope_key="guest"):
        self.base_dir = os.path.expanduser(base_dir or "~/.cache/hiresti")
        self.scope_key = "guest"
        self.path = ""
        self.set_scope(scope_key)

    def set_scope(self, scope_key):
        key = str(scope_key or "guest").strip() or "guest"
        self.scope_key = key
        if key == "guest":
            # Keep legacy guest path for backward compatibility.
            self.path = os.path.join(self.base_dir, "playlists.json")
        else:
            self.path = os.path.join(self.base_dir, "profiles", key, "playlists.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def _load(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def _save(self, playlists):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(playlists, f)
        except Exception:
            pass

    def list_playlists(self):
        return self._load()

    def get_playlist(self, playlist_id):
        for p in self._load():
            if str(p.get("id")) == str(playlist_id):
                return p
        return None

    def create_playlist(self, name):
        playlists = self._load()
        now = int(time.time())
        p = {
            "id": str(uuid.uuid4()),
            "name": (name or "New Playlist").strip() or "New Playlist",
            "created_at": now,
            "updated_at": now,
            "tracks": [],
        }
        playlists.insert(0, p)
        self._save(playlists)
        return p

    def add_track(self, playlist_id, track, cover_url=None, dedupe=False):
        if track is None:
            return False
        playlists = self._load()
        changed = False
        for p in playlists:
            if str(p.get("id")) != str(playlist_id):
                continue
            if dedupe:
                tid = str(getattr(track, "id", ""))
                for e in p.setdefault("tracks", []):
                    if str(e.get("track_id", "")) == tid:
                        return False
            alb_obj = getattr(track, "album", None)
            art_obj = getattr(track, "artist", None)
            entry = {
                "track_id": getattr(track, "id", None),
                "track_name": getattr(track, "name", "Unknown Track"),
                "duration": getattr(track, "duration", 0) or 0,
                "album_id": getattr(alb_obj, "id", None),
                "album_name": getattr(alb_obj, "name", "Unknown Album"),
                "artist": getattr(art_obj, "name", "Unknown"),
                "artist_id": getattr(art_obj, "id", None),
                "cover": cover_url,
                "added_at": int(time.time()),
            }
            p.setdefault("tracks", []).append(entry)
            p["updated_at"] = int(time.time())
            changed = True
            break
        if changed:
            self._save(playlists)
        return changed

    def move_track(self, playlist_id, index, direction):
        playlists = self._load()
        changed = False
        for p in playlists:
            if str(p.get("id")) != str(playlist_id):
                continue
            tracks = p.setdefault("tracks", [])
            idx = int(index)
            target = idx + int(direction)
            if 0 <= idx < len(tracks) and 0 <= target < len(tracks):
                tracks[idx], tracks[target] = tracks[target], tracks[idx]
                p["updated_at"] = int(time.time())
                changed = True
            break
        if changed:
            self._save(playlists)
        return changed

    def move_track_to(self, playlist_id, from_index, to_index):
        playlists = self._load()
        changed = False
        for p in playlists:
            if str(p.get("id")) != str(playlist_id):
                continue
            tracks = p.setdefault("tracks", [])
            src = int(from_index)
            dst = int(to_index)
            if not (0 <= src < len(tracks) and 0 <= dst < len(tracks)):
                break
            if src == dst:
                return False
            item = tracks.pop(src)
            tracks.insert(dst, item)
            p["updated_at"] = int(time.time())
            changed = True
            break
        if changed:
            self._save(playlists)
        return changed

    def rename_playlist(self, playlist_id, name):
        new_name = (name or "").strip()
        if not new_name:
            return False
        playlists = self._load()
        changed = False
        for p in playlists:
            if str(p.get("id")) != str(playlist_id):
                continue
            p["name"] = new_name
            p["updated_at"] = int(time.time())
            changed = True
            break
        if changed:
            self._save(playlists)
        return changed

    def delete_playlist(self, playlist_id):
        playlists = self._load()
        new_list = [p for p in playlists if str(p.get("id")) != str(playlist_id)]
        if len(new_list) == len(playlists):
            return False
        self._save(new_list)
        return True

    def remove_track(self, playlist_id, index):
        playlists = self._load()
        changed = False
        for p in playlists:
            if str(p.get("id")) != str(playlist_id):
                continue
            tracks = p.setdefault("tracks", [])
            if 0 <= int(index) < len(tracks):
                tracks.pop(int(index))
                p["updated_at"] = int(time.time())
                changed = True
            break
        if changed:
            self._save(playlists)
        return changed

    def get_tracks(self, playlist_id):
        p = self.get_playlist(playlist_id)
        if not p:
            return []
        out = []
        for e in p.get("tracks", []):
            tr = LocalTrack(
                {
                    "id": e.get("track_id"),
                    "name": e.get("track_name", "Unknown Track"),
                    "duration": e.get("duration", 0),
                    "artist": e.get("artist", "Unknown"),
                    "artist_id": e.get("artist_id"),
                    "album_id": e.get("album_id"),
                    "album_name": e.get("album_name", "Unknown Album"),
                    "cover": e.get("cover"),
                }
            )
            out.append(tr)
        return out

    def get_cover_refs(self, playlist, limit=4):
        if not playlist:
            return []

        tracks = list(playlist.get("tracks", []))
        if not tracks:
            return []

        refs = []
        seen_albums = set()
        # Newest tracks first so newly added albums affect the cover immediately.
        for e in reversed(tracks):
            c = e.get("cover")
            if not c:
                continue
            alb_id = e.get("album_id")
            alb_name = (e.get("album_name") or "").strip().lower()
            key = str(alb_id) if alb_id is not None else alb_name
            if not key:
                key = f"cover:{c}"
            if key in seen_albums:
                continue
            seen_albums.add(key)
            refs.append(c)
            if len(refs) >= limit:
                break
        return refs
