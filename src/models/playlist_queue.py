"""A playlist queue whose metadata is fetched independently of the track view."""

from threading import Lock

from models.local import LocalAlbumInfo, LocalArtist, LocalTrack


class PlaylistQueue:
    PAGE_SIZE = 100

    def __init__(self, total, fetch_track, name="Playlist", shuffled=False, fetch_page=None):
        self.total = total
        self.name = name
        self.shuffled = shuffled
        self._fetch_track = fetch_track
        self._fetch_page = fetch_page
        self._tracks = {}
        self._lock = Lock()

    def resolve(self, position):
        # Playback and prefetch can request the same entry concurrently.
        with self._lock:
            if position not in self._tracks:
                track = self._fetch_track(position)
                if track is None or getattr(track, "id", None) is None:
                    raise ValueError("Could not load the playlist track. Please try again.")
                self._tracks[position] = track
            return self._tracks[position]

    def pages_for(self, positions):
        """Page offsets covering ``positions`` that still have unloaded entries, in order."""
        offsets = []
        for position in positions:
            if position in self._tracks:
                continue
            offset = position - position % self.PAGE_SIZE
            if offset not in offsets:
                offsets.append(offset)
        return offsets

    def hydrate_page(self, offset):
        """Load one page of display metadata. Returns the number of new entries."""
        if self._fetch_page is None:
            return 0
        page = self._fetch_page(offset, self.PAGE_SIZE)
        added = 0
        with self._lock:
            for i, track in enumerate(page):
                position = offset + i
                if position >= self.total or getattr(track, "id", None) is None:
                    continue
                if position not in self._tracks:
                    self._tracks[position] = track
                    added += 1
        return added

    def entries(self):
        return [PlaylistQueueTrack(self, position) for position in range(self.total)]


class PlaylistQueueTrack:
    """Nonblocking queue entry. Only resolve() performs network I/O."""

    def __init__(self, source, position):
        self.source = source
        self.position = position
        self._placeholder = LocalTrack(
            name=f"Track {position + 1} — details pending",
            artist=LocalArtist(name=""),
            album=LocalAlbumInfo(name=source.name),
        )

    @property
    def resolved_track(self):
        return self.source._tracks.get(self.position)

    def resolve(self):
        return self.source.resolve(self.position)

    def __getattr__(self, name):
        track = self.resolved_track
        return getattr(track if track is not None else self._placeholder, name)
