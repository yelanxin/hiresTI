from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LocalArtist:
    """Simplified artist object"""
    name: str = "Unknown"
    id: Optional[Any] = None


@dataclass
class LocalAlbumInfo:
    """Simplified album info for track objects"""
    id: Optional[Any] = None
    name: str = "Unknown Album"
    cover: Optional[str] = None


@dataclass
class LocalAlbum:
    """Local album representation"""
    id: Optional[Any] = None
    name: Optional[str] = None
    artist: LocalArtist = field(default_factory=LocalArtist)
    cover_url: Optional[str] = None
    release_date: Optional[str] = None
    num_tracks: str = "?"

    @classmethod
    def from_dict(cls, data: dict) -> LocalAlbum:
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            artist=LocalArtist(
                name=data.get("artist", "Unknown"),
                id=data.get("artist_id"),
            ),
            cover_url=data.get("cover_url"),
        )


@dataclass
class LocalTrack:
    """Local track representation"""
    id: Optional[Any] = None
    name: str = "Unknown Track"
    duration: int = 0
    cover: Optional[str] = None
    artist: LocalArtist = field(default_factory=LocalArtist)
    album: LocalAlbumInfo = field(default_factory=LocalAlbumInfo)
    play_count: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> LocalTrack:
        return cls(
            id=data.get("id"),
            name=data.get("name", "Unknown Track"),
            duration=data.get("duration", 0) or 0,
            cover=data.get("cover"),
            artist=LocalArtist(
                name=data.get("artist", "Unknown"),
                id=data.get("artist_id"),
            ),
            album=LocalAlbumInfo(
                id=data.get("album_id"),
                name=data.get("album_name", "Unknown Album"),
                cover=data.get("cover"),
            ),
        )
