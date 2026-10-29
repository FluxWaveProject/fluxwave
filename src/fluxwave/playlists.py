"""Named, user-owned playlist storage built on the persistence backends."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from os import PathLike
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from .exceptions import FluxWaveError
from .tracks import Track
from .types import JsonObject

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^\w \-.]", re.UNICODE)


class PlaylistError(FluxWaveError):
    """Base error for named-playlist operations."""


class PlaylistNotFound(PlaylistError):
    """Raised when a named playlist does not exist."""


class PlaylistAlreadyExists(PlaylistError):
    """Raised when creating a playlist whose name is already taken."""


@dataclass(frozen=True, slots=True)
class SavedPlaylist:
    """A named, user-owned playlist of raw Lavalink track payloads."""

    name: str
    owner_id: int
    track_payloads: list[JsonObject] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    guild_id: int | None = None
    extra: JsonObject = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Case-insensitive lookup key."""

        return self.name.casefold()

    @property
    def size(self) -> int:
        """Number of tracks in the playlist."""

        return len(self.track_payloads)

    @property
    def tracks(self) -> list[Track]:
        """Reconstruct the stored tracks, skipping any that no longer decode."""

        tracks: list[Track] = []
        for payload in self.track_payloads:
            with contextlib.suppress(Exception):
                tracks.append(Track.from_payload(payload))
        return tracks

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""

        return {
            "name": self.name,
            "owner_id": self.owner_id,
            "track_payloads": [dict(payload) for payload in self.track_payloads],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "guild_id": self.guild_id,
            "extra": dict(self.extra),
        }

    def to_json(self) -> str:
        """Serialise to a JSON string."""

        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SavedPlaylist:
        """Restore a playlist from a plain dict."""

        return cls(
            name=str(data["name"]),
            owner_id=int(data["owner_id"]),
            track_payloads=[
                payload for payload in data.get("track_payloads", []) if isinstance(payload, dict)
            ],
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            guild_id=(int(data["guild_id"]) if data.get("guild_id") is not None else None),
            extra=dict(data.get("extra", {})),
        )

    @classmethod
    def from_json(cls, text: str) -> SavedPlaylist:
        """Restore a playlist from a JSON string."""

        return cls.from_dict(json.loads(text))

    @classmethod
    def from_tracks(
        cls,
        owner_id: int,
        name: str,
        tracks: Iterable[Track],
        *,
        guild_id: int | None = None,
        extra: JsonObject | None = None,
    ) -> SavedPlaylist:
        """Build a playlist snapshot from live tracks."""

        now = time.time()
        return cls(
            name=name,
            owner_id=owner_id,
            track_payloads=[track.raw_data.copy() for track in tracks],
            created_at=now,
            updated_at=now,
            guild_id=guild_id,
            extra=dict(extra) if extra else {},
        )

    def renamed(self, name: str) -> SavedPlaylist:
        """Return a copy under a new name (touching ``updated_at``)."""

        return replace(self, name=name, updated_at=time.time())

    def with_tracks(self, tracks: Iterable[Track]) -> SavedPlaylist:
        """Return a copy with its tracks replaced."""

        return replace(
            self,
            track_payloads=[track.raw_data.copy() for track in tracks],
            updated_at=time.time(),
        )


@runtime_checkable
class PlaylistStore(Protocol):
    """Protocol for named-playlist back-ends (memory, file, Redis, DB, …)."""

    async def save(self, playlist: SavedPlaylist) -> None: ...
    async def load(self, owner_id: int, name: str) -> SavedPlaylist | None: ...
    async def delete(self, owner_id: int, name: str) -> None: ...
    async def list_for(self, owner_id: int) -> list[SavedPlaylist]: ...


class MemoryPlaylistStore:
    """In-process named-playlist store backed by a dict."""

    __slots__ = ("_data",)

    def __init__(self) -> None:
        self._data: dict[tuple[int, str], SavedPlaylist] = {}

    async def save(self, playlist: SavedPlaylist) -> None:
        self._data[(playlist.owner_id, playlist.key)] = playlist

    async def load(self, owner_id: int, name: str) -> SavedPlaylist | None:
        return self._data.get((owner_id, name.casefold()))

    async def delete(self, owner_id: int, name: str) -> None:
        self._data.pop((owner_id, name.casefold()), None)

    async def list_for(self, owner_id: int) -> list[SavedPlaylist]:
        return sorted(
            (p for (owner, _), p in self._data.items() if owner == owner_id),
            key=lambda p: p.name.casefold(),
        )

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"MemoryPlaylistStore(playlists={len(self._data)})"


class FilePlaylistStore:
    """Named-playlist store that writes one JSON file per owner.

    Writes go through a temp file and atomic rename, matching
    :class:`~fluxwave.FileStore`::

        store = fluxwave.FilePlaylistStore("data/playlists")
    """

    __slots__ = ("_directory",)

    def __init__(self, directory: str | PathLike[str]) -> None:
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        """Directory playlists are written to."""

        return self._directory

    async def save(self, playlist: SavedPlaylist) -> None:
        await asyncio.to_thread(self._write, playlist)

    async def load(self, owner_id: int, name: str) -> SavedPlaylist | None:
        data = await asyncio.to_thread(self._read, owner_id)
        return data.get(name.casefold())

    async def delete(self, owner_id: int, name: str) -> None:
        await asyncio.to_thread(self._delete, owner_id, name.casefold())

    async def list_for(self, owner_id: int) -> list[SavedPlaylist]:
        data = await asyncio.to_thread(self._read, owner_id)
        return sorted(data.values(), key=lambda p: p.name.casefold())

    def _path(self, owner_id: int) -> Path:
        return self._directory / f"{owner_id}.json"

    def _read(self, owner_id: int) -> dict[str, SavedPlaylist]:
        try:
            text = self._path(owner_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}

        try:
            raw = json.loads(text)
        except ValueError:
            logger.warning("Discarding unreadable playlist file for owner %s.", owner_id)
            return {}

        if not isinstance(raw, dict):
            return {}

        playlists: dict[str, SavedPlaylist] = {}
        for value in raw.values():
            if isinstance(value, dict):
                with contextlib.suppress(KeyError, ValueError, TypeError):
                    playlist = SavedPlaylist.from_dict(value)
                    playlists[playlist.key] = playlist
        return playlists

    def _write(self, playlist: SavedPlaylist) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        data = self._read(playlist.owner_id)
        data[playlist.key] = playlist
        payload = {key: value.to_dict() for key, value in data.items()}
        text = json.dumps(payload, ensure_ascii=False)

        path = self._path(playlist.owner_id)
        tmp = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()

    def _delete(self, owner_id: int, key: str) -> None:
        data = self._read(owner_id)
        if key not in data:
            return

        del data[key]
        if data:
            self._write_all(owner_id, data)
        else:
            with contextlib.suppress(FileNotFoundError):
                self._path(owner_id).unlink()

    def _write_all(self, owner_id: int, data: dict[str, SavedPlaylist]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            {key: value.to_dict() for key, value in data.items()},
            ensure_ascii=False,
        )
        path = self._path(owner_id)
        tmp = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()

    def __repr__(self) -> str:
        return f"FilePlaylistStore(directory={str(self._directory)!r})"


class PlaylistManager:
    """High-level CRUD over a :class:`PlaylistStore`."""

    __slots__ = ("_store",)

    def __init__(self, store: PlaylistStore | None = None) -> None:
        self._store = store if store is not None else MemoryPlaylistStore()

    @property
    def store(self) -> PlaylistStore:
        """Backing store."""

        return self._store

    async def create(
        self,
        owner_id: int,
        name: str,
        tracks: Iterable[Track] | None = None,
        *,
        guild_id: int | None = None,
        overwrite: bool = False,
        extra: JsonObject | None = None,
    ) -> SavedPlaylist:
        """Create (or overwrite) a named playlist."""

        clean = _validate_name(name)
        existing = await self._store.load(owner_id, clean)
        if existing is not None and not overwrite:
            raise PlaylistAlreadyExists(f"Playlist {clean!r} already exists.")

        if existing is not None:
            playlist = existing.with_tracks(tracks or [])
            if extra:
                playlist = replace(playlist, extra=dict(extra))
        else:
            playlist = SavedPlaylist.from_tracks(
                owner_id,
                clean,
                tracks or [],
                guild_id=guild_id,
                extra=extra,
            )
        await self._store.save(playlist)
        return playlist

    async def get(self, owner_id: int, name: str) -> SavedPlaylist | None:
        """Return a playlist, or ``None`` when it does not exist."""

        return await self._store.load(owner_id, _validate_name(name))

    async def require(self, owner_id: int, name: str) -> SavedPlaylist:
        """Return a playlist or raise :class:`PlaylistNotFound`."""

        playlist = await self.get(owner_id, name)
        if playlist is None:
            raise PlaylistNotFound(f"Playlist {name!r} was not found.")
        return playlist

    async def list(self, owner_id: int) -> list[SavedPlaylist]:
        """List a user's playlists, sorted by name."""

        return await self._store.list_for(owner_id)

    async def delete(self, owner_id: int, name: str) -> bool:
        """Delete a playlist, returning whether it existed."""

        playlist = await self.get(owner_id, name)
        if playlist is None:
            return False
        await self._store.delete(owner_id, playlist.name)
        return True

    async def rename(self, owner_id: int, name: str, new_name: str) -> SavedPlaylist:
        """Rename a playlist, rejecting a name already in use."""

        playlist = await self.require(owner_id, name)
        clean = _validate_name(new_name)
        if clean.casefold() != playlist.key and await self.get(owner_id, clean) is not None:
            raise PlaylistAlreadyExists(f"Playlist {clean!r} already exists.")

        renamed = playlist.renamed(clean)
        await self._store.save(renamed)
        if renamed.key != playlist.key:
            await self._store.delete(owner_id, playlist.name)
        return renamed

    async def add_tracks(
        self,
        owner_id: int,
        name: str,
        tracks: Iterable[Track],
    ) -> SavedPlaylist:
        """Append tracks to an existing playlist and return it."""

        playlist = await self.require(owner_id, name)
        combined = playlist.tracks
        combined.extend(tracks)
        updated = playlist.with_tracks(combined)
        await self._store.save(updated)
        return updated

    async def remove_index(self, owner_id: int, name: str, index: int) -> Track:
        """Remove and return the track at *index* in a playlist."""

        playlist = await self.require(owner_id, name)
        tracks = playlist.tracks
        try:
            removed = tracks.pop(index)
        except IndexError as exc:
            raise PlaylistError(f"Playlist index out of range: {index}") from exc

        await self._store.save(playlist.with_tracks(tracks))
        return removed

    def __repr__(self) -> str:
        return f"PlaylistManager(store={self._store!r})"


def _validate_name(name: str) -> str:
    clean = " ".join(name.split()).strip()
    if not clean:
        raise PlaylistError("Playlist name cannot be empty.")
    return _SAFE_NAME_RE.sub("", clean)[:100] or clean[:100]
