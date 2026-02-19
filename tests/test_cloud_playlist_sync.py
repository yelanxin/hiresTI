from types import SimpleNamespace

from tidal_backend import TidalBackend


class FakeCloudPlaylist:
    def __init__(self, pid="pl1", name="Cloud"):
        self.id = pid
        self.name = name
        self._ids = set()
        self.add_calls = []

    def tracks(self, limit=None):
        _ = limit
        return [SimpleNamespace(id=i) for i in sorted(self._ids)]

    def add(self, media_ids, allow_duplicates=False, position=-1, limit=100):
        _ = (allow_duplicates, position, limit)
        self.add_calls.append(list(media_ids))
        for mid in media_ids:
            self._ids.add(str(mid))
        return []


class FakeUser:
    def __init__(self):
        self.created = []
        self._counter = 0

    def create_playlist(self, title, description, parent_id="root"):
        _ = (description, parent_id)
        self._counter += 1
        pl = FakeCloudPlaylist(pid=f"cloud-{self._counter}", name=title)
        self.created.append(pl)
        return pl


def test_sync_local_playlist_to_new_cloud_playlist():
    backend = TidalBackend()
    backend.user = FakeUser()
    backend.session = SimpleNamespace(playlist=lambda _pid: None)

    local = {
        "name": "My Local",
        "tracks": [
            {"track_id": "1"},
            {"track_id": "2"},
            {"track_id": "2"},  # duplicate
            {"track_id": None},  # invalid
        ],
    }
    result = backend.sync_local_playlist_to_cloud(local, cloud_playlist_id=None, dedupe=True)

    assert result["ok"] is True
    assert result["created"] is True
    assert result["cloud_playlist_id"] == "cloud-1"
    assert result["requested"] == 3
    assert result["added"] == 2
    assert result["skipped_invalid"] == 1


def test_sync_local_playlist_to_existing_cloud_playlist_dedupes_existing():
    backend = TidalBackend()
    backend.user = FakeUser()
    existing = FakeCloudPlaylist(pid="cloud-99", name="Remote Existing")
    existing._ids.add("2")
    backend.session = SimpleNamespace(playlist=lambda _pid: existing)

    local = {
        "name": "My Local",
        "tracks": [
            {"track_id": "1"},
            {"track_id": "2"},  # already exists in cloud playlist
            {"track_id": "3"},
        ],
    }
    result = backend.sync_local_playlist_to_cloud(local, cloud_playlist_id="cloud-99", dedupe=True)

    assert result["ok"] is True
    assert result["created"] is False
    assert result["cloud_playlist_id"] == "cloud-99"
    assert result["requested"] == 3
    assert result["added"] == 2
    assert result["skipped_invalid"] == 0
