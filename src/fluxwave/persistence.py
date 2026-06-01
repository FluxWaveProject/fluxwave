"""Player state persistence: capture, serialise, and restore player snapshots."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, Unpack, runtime_checkable
from uuid import uuid4

from .autoplay import AutoPlayMode
from .tracks import Track
from .types import JsonObject

if TYPE_CHECKING:
    from .player import FluxPlayer

logger = logging.getLogger(__name__)


class JsonDumpOptions(TypedDict, total=False):
    """Supported JSON dump options for persisted-state serialisation."""

    ensure_ascii: bool
    indent: int | str | None
    sort_keys: bool


@dataclass(frozen=True, slots=True)
class PersistedState:
    """Serialisable snapshot of a :class:`~fluxwave.FluxPlayer` at a point in time.

    Tracks are stored as their raw Lavalink payloads so restoration does not
    require a live node for decoding.  If the raw payload is unavailable only
    the encoded string is stored; a connected node will be needed to decode it.
    """

    guild_id: int
    channel_id: int | None

    current_track_payload: JsonObject | None
    """Full ``track`` payload dict so the track can be reconstructed offline."""

    current_position: int
    is_paused: bool
    volume: int
    queue_mode: str

    queue_payloads: list[JsonObject]
    """Ordered list of raw track payloads for queued tracks."""

    history_payloads: list[JsonObject]
    """Ordered list of raw track payloads from queue history."""

    auto_queue_payloads: list[JsonObject]
    """Ordered list of raw track payloads from the autoplay queue."""

    auto_queue_history_payloads: list[JsonObject]
    """Ordered list of raw track payloads from autoplay queue history."""

    autoplay_mode: str
    """Saved :class:`~fluxwave.AutoPlayMode` value."""

    recommendation_seed_payloads: list[JsonObject]
    """Raw payloads for recommendation seed tracks."""

    previous_seed_ids: list[str]
    """Recently used recommendation seed identifiers."""

    filters_payload: JsonObject
    """Raw Lavalink filters dict."""

    filter_stack_payloads: dict[str, JsonObject] = field(default_factory=dict)
    """Tagged player filter stack payloads."""

    preload_filter_tags: list[str] = field(default_factory=list)
    """Filter tags that were preloaded for future playback."""

    extra: JsonObject = field(default_factory=dict)
    """Arbitrary caller-defined metadata."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "current_track_payload": self.current_track_payload,
            "current_position": self.current_position,
            "is_paused": self.is_paused,
            "volume": self.volume,
            "queue_mode": self.queue_mode,
            "queue_payloads": list(self.queue_payloads),
            "history_payloads": list(self.history_payloads),
            "auto_queue_payloads": list(self.auto_queue_payloads),
            "auto_queue_history_payloads": list(self.auto_queue_history_payloads),
            "autoplay_mode": self.autoplay_mode,
            "recommendation_seed_payloads": list(self.recommendation_seed_payloads),
            "previous_seed_ids": list(self.previous_seed_ids),
            "filters_payload": dict(self.filters_payload),
            "filter_stack_payloads": {
                tag: dict(payload) for tag, payload in self.filter_stack_payloads.items()
            },
            "preload_filter_tags": list(self.preload_filter_tags),
            "extra": dict(self.extra),
        }

    def to_json(self, **kwargs: Unpack[JsonDumpOptions]) -> str:
        """Serialise to a JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersistedState:
        """Restore a :class:`PersistedState` from a plain dict."""
        return cls(
            guild_id=int(data["guild_id"]),
            channel_id=int(data["channel_id"]) if data.get("channel_id") is not None else None,
            current_track_payload=data.get("current_track_payload"),
            current_position=int(data.get("current_position", 0)),
            is_paused=bool(data.get("is_paused", False)),
            volume=int(data.get("volume", 100)),
            queue_mode=str(data.get("queue_mode", "normal")),
            queue_payloads=list(data.get("queue_payloads", [])),
            history_payloads=list(data.get("history_payloads", [])),
            auto_queue_payloads=list(data.get("auto_queue_payloads", [])),
            auto_queue_history_payloads=list(data.get("auto_queue_history_payloads", [])),
            autoplay_mode=str(data.get("autoplay_mode", AutoPlayMode.DISABLED.value)),
            recommendation_seed_payloads=list(data.get("recommendation_seed_payloads", [])),
            previous_seed_ids=[str(item) for item in data.get("previous_seed_ids", [])],
            filters_payload=dict(data.get("filters_payload", {})),
            filter_stack_payloads={
                str(tag): dict(payload)
                for tag, payload in dict(data.get("filter_stack_payloads", {})).items()
                if isinstance(payload, dict)
            },
            preload_filter_tags=[str(tag) for tag in data.get("preload_filter_tags", [])],
            extra=dict(data.get("extra", {})),
        )

    @classmethod
    def from_json(cls, text: str) -> PersistedState:
        """Restore a :class:`PersistedState` from a JSON string."""
        return cls.from_dict(json.loads(text))

    @property
    def current_track(self) -> Track | None:
        """Reconstruct the current :class:`~fluxwave.Track` from the stored payload."""
        if self.current_track_payload is None:
            return None
        try:
            return Track.from_payload(self.current_track_payload)
        except Exception:
            return None

    @property
    def queued_tracks(self) -> list[Track]:
        """Reconstruct queued :class:`~fluxwave.Track` objects from stored payloads."""
        tracks: list[Track] = []
        for payload in self.queue_payloads:
            with contextlib.suppress(Exception):
                tracks.append(Track.from_payload(payload))
        return tracks

    @property
    def history_tracks(self) -> list[Track]:
        """Reconstruct history :class:`~fluxwave.Track` objects from stored payloads."""
        tracks: list[Track] = []
        for payload in self.history_payloads:
            with contextlib.suppress(Exception):
                tracks.append(Track.from_payload(payload))
        return tracks

    @property
    def auto_queue_tracks(self) -> list[Track]:
        """Reconstruct autoplay queue :class:`~fluxwave.Track` objects."""
        tracks: list[Track] = []
        for payload in self.auto_queue_payloads:
            with contextlib.suppress(Exception):
                tracks.append(Track.from_payload(payload))
        return tracks

    @property
    def recommendation_seed_tracks(self) -> list[Track]:
        """Reconstruct saved autoplay recommendation seed tracks."""
        tracks: list[Track] = []
        for payload in self.recommendation_seed_payloads:
            with contextlib.suppress(Exception):
                tracks.append(Track.from_payload(payload))
        return tracks


def capture(player: FluxPlayer, *, extra: JsonObject | None = None) -> PersistedState:
    """Capture the current state of *player* as a :class:`PersistedState`.

    This is a pure, synchronous snapshot — it does not interact with Lavalink::

        state = fluxwave.persistence.capture(player)
        await redis.set(f"player:{guild_id}", state.to_json())
    """
    channel_id: int | None = None
    ch = getattr(player, "channel", None)
    if ch is not None:
        channel_id = getattr(ch, "id", None)

    current = player.current
    current_payload = current.raw_data.copy() if current is not None else None

    queue_payloads = [t.raw_data.copy() for t in player.queue]
    history_payloads = (
        [t.raw_data.copy() for t in player.queue.history]
        if player.queue.history is not None
        else []
    )
    auto_queue_payloads = [t.raw_data.copy() for t in player.auto_queue]
    auto_queue_history_payloads = (
        [t.raw_data.copy() for t in player.auto_queue.history]
        if player.auto_queue.history is not None
        else []
    )
    recommendation_seed_payloads = [t.raw_data.copy() for t in player.recommendation_seeds]

    return PersistedState(
        guild_id=player.guild.id,
        channel_id=channel_id,
        current_track_payload=current_payload,
        current_position=player.position,
        is_paused=player.paused,
        volume=player.volume,
        queue_mode=player.queue.mode.value,
        queue_payloads=queue_payloads,
        history_payloads=history_payloads,
        auto_queue_payloads=auto_queue_payloads,
        auto_queue_history_payloads=auto_queue_history_payloads,
        autoplay_mode=player.autoplay.value,
        recommendation_seed_payloads=recommendation_seed_payloads,
        previous_seed_ids=list(player._previous_seed_ids),
        filters_payload=player.filters.to_payload(),
        filter_stack_payloads={
            tag: filters.to_payload() for tag, filters in player._filter_stack.items()
        },
        preload_filter_tags=list(player._preload_filter_tags),
        extra=dict(extra) if extra else {},
    )


@runtime_checkable
class PersistenceBackend(Protocol):
    """Protocol for custom persistence back-ends (Redis, file, DB, …)."""

    async def save(self, guild_id: int, state: PersistedState) -> None: ...
    async def load(self, guild_id: int) -> PersistedState | None: ...
    async def delete(self, guild_id: int) -> None: ...


class MemoryStore:
    """Thread-safe in-process persistence store backed by a plain dict.

    Suitable for development and single-process bots. Replace with a
    :class:`PersistenceBackend` implementation for multi-process / distributed
    setups::

        store = fluxwave.persistence.MemoryStore()
        await store.save(guild_id, fluxwave.persistence.capture(player))
        state = await store.load(guild_id)
    """

    __slots__ = ("_data",)

    def __init__(self) -> None:
        self._data: dict[int, PersistedState] = {}

    async def save(self, guild_id: int, state: PersistedState) -> None:
        self._data[guild_id] = state

    async def load(self, guild_id: int) -> PersistedState | None:
        return self._data.get(guild_id)

    async def delete(self, guild_id: int) -> None:
        self._data.pop(guild_id, None)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, guild_id: object) -> bool:
        return guild_id in self._data

    def __repr__(self) -> str:
        return f"MemoryStore(guilds={len(self._data)})"


class FileStore:
    """Persistence backend that stores each guild's snapshot as a JSON file.

    Dependency-free and crash-safe (writes go through a temp file and an atomic
    rename), suitable for single-process bots that must survive restarts. File
    I/O runs in a worker thread so it never blocks the event loop::

        store = fluxwave.persistence.FileStore("data/players")
        await store.save(guild_id, fluxwave.persistence.capture(player))
        for guild_id in await store.all_guild_ids():
            state = await store.load(guild_id)
    """

    __slots__ = ("_directory",)

    def __init__(self, directory: str | PathLike[str]) -> None:
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        """Directory snapshots are written to."""

        return self._directory

    async def save(self, guild_id: int, state: PersistedState) -> None:
        await asyncio.to_thread(self._write, guild_id, state.to_json())

    async def load(self, guild_id: int) -> PersistedState | None:
        text = await asyncio.to_thread(self._read, guild_id)
        if text is None:
            return None

        try:
            return PersistedState.from_json(text)
        except (ValueError, KeyError, TypeError):
            logger.warning("Discarding unreadable persisted state for guild %s.", guild_id)
            return None

    async def delete(self, guild_id: int) -> None:
        await asyncio.to_thread(self._delete, guild_id)

    async def all_guild_ids(self) -> list[int]:
        """Return guild IDs that currently have a saved snapshot."""

        return await asyncio.to_thread(self._scan)

    def _path(self, guild_id: int) -> Path:
        return self._directory / f"{guild_id}.json"

    def _write(self, guild_id: int, text: str) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path(guild_id)
        # Unique temp name per write so concurrent saves for the same guild can't
        # interleave into a shared temp file and promote corrupted JSON on rename.
        tmp = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
        finally:
            # On a successful replace the temp is already gone; only cleans up a
            # leftover if write_text or replace failed partway.
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()

    def _read(self, guild_id: int) -> str | None:
        try:
            return self._path(guild_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _delete(self, guild_id: int) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(guild_id).unlink()

    def _scan(self) -> list[int]:
        if not self._directory.exists():
            return []

        guild_ids: list[int] = []
        for file in self._directory.glob("*.json"):
            try:
                guild_ids.append(int(file.stem))
            except ValueError:
                continue
        return guild_ids

    def __repr__(self) -> str:
        return f"FileStore(directory={str(self._directory)!r})"
