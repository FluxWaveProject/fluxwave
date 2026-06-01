"""Queue primitives."""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from enum import StrEnum
from typing import overload

from .exceptions import QueueEmpty, QueueError, QueueFull
from .tracks import Playlist, Track


class QueueMode(StrEnum):
    """Playback queue mode."""

    NORMAL = "normal"
    LOOP = "loop"
    LOOP_ALL = "loop_all"
    normal = "normal"
    loop = "loop"
    loop_all = "loop_all"


class Queue:
    """Track queue with history, loop modes, and async wait support."""

    __slots__ = ("_items", "_loaded", "_max_size", "_overflow", "_waiters", "history", "mode")

    def __init__(
        self,
        *,
        history: bool = True,
        max_size: int | None = None,
        overflow: bool = True,
    ) -> None:
        self._items: deque[Track] = deque()
        self._waiters: deque[asyncio.Future[Track]] = deque()
        self._loaded: Track | None = None
        self._max_size: int | None = None
        self._overflow = overflow
        self.max_size = max_size
        self.mode = QueueMode.NORMAL
        self.history: Queue | None = Queue(history=False) if history else None

    def __bool__(self) -> bool:
        return bool(self._items)

    def __call__(self, item: Track | Playlist | Iterable[Track], /, *, atomic: bool = True) -> int:
        """Append tracks using call syntax."""

        return self.put(item, atomic=atomic)

    def __str__(self) -> str:
        return f"Queue(count={len(self)}, mode={self.mode.value})"

    def __repr__(self) -> str:
        return (
            f"Queue(items={len(self)}, loaded={self.loaded!r}, "
            f"history={self.history!r}, mode={self.mode.value!r}, "
            f"max_size={self.max_size!r}, overflow={self.overflow!r})"
        )

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Track]:
        return iter(tuple(self._items))

    def __reversed__(self) -> Iterator[Track]:
        return reversed(tuple(self._items))

    def __contains__(self, track: object) -> bool:
        return track in self._items

    @overload
    def __getitem__(self, index: int) -> Track: ...

    @overload
    def __getitem__(self, index: slice) -> list[Track]: ...

    def __getitem__(self, index: int | slice) -> Track | list[Track]:
        items = list(self._items)
        return items[index]

    def __setitem__(self, index: int, track: Track) -> None:
        self._validate_track(track)
        items = list(self._items)
        try:
            items[index] = track
        except IndexError as exc:
            raise QueueError(f"Queue index out of range: {index}") from exc
        self._items = deque(items)

    def __delitem__(self, index: int | slice) -> None:
        items = list(self._items)
        try:
            del items[index]
        except IndexError as exc:
            raise QueueError("Queue index out of range while deleting tracks.") from exc
        self._items = deque(items)

    @property
    def loaded(self) -> Track | None:
        """Track most recently loaded into the player by this queue."""

        return self._loaded

    @loaded.setter
    def loaded(self, track: Track | None) -> None:
        self._loaded = track

    @property
    def current(self) -> Track | None:
        """Alias for the queue's loaded track."""

        return self._loaded

    @property
    def max_size(self) -> int | None:
        """Maximum queued tracks, or ``None`` for unlimited."""

        return self._max_size

    @max_size.setter
    def max_size(self, value: int | None) -> None:
        if value is None:
            self._max_size = None
            return

        if not isinstance(value, int):
            msg = "Queue max_size must be an integer or None."
            raise TypeError(msg)
        if value <= 0:
            msg = "Queue max_size must be greater than 0."
            raise ValueError(msg)

        if not self._overflow and len(self._items) > value:
            msg = f"Queue already contains {len(self._items)} tracks, above max_size {value}."
            raise QueueFull(msg)

        self._max_size = value
        if self._overflow:
            self._trim_overflow(from_left=True)

    @property
    def overflow(self) -> bool:
        """Whether new tracks displace old queued tracks when the queue is full."""

        return self._overflow

    @overflow.setter
    def overflow(self, value: bool) -> None:
        self._overflow = bool(value)

    @property
    def count(self) -> int:
        """Number of queued tracks."""

        return len(self._items)

    @property
    def is_empty(self) -> bool:
        """Whether this queue has no queued tracks."""

        return not self._items

    @property
    def total_duration(self) -> int:
        """Total duration of all queued tracks in milliseconds. Streams contribute 0."""

        return sum(track.duration for track in self._items if not track.is_stream)

    @classmethod
    def from_tracks(
        cls,
        tracks: Iterable[Track],
        *,
        history: bool = True,
        mode: QueueMode = QueueMode.NORMAL,
        max_size: int | None = None,
        overflow: bool = True,
    ) -> Queue:
        """Create a pre-populated queue from an iterable of tracks."""

        q = cls(history=history, max_size=max_size, overflow=overflow)
        q.mode = mode
        for track in tracks:
            q.put(track)
        return q

    @classmethod
    def from_payloads(
        cls,
        payloads: Sequence[object],
        *,
        history_payloads: Sequence[object] | None = None,
        mode: str = "normal",
        loaded_payload: object | None = None,
        max_size: int | None = None,
        overflow: bool = True,
    ) -> Queue:
        """Restore a queue from raw Lavalink track payload dicts.

        Payloads are the ``track`` JSON objects from a Lavalink response
        (same format accepted by :meth:`~fluxwave.Track.from_payload`).
        """

        from .tracks import Track as TrackCls

        q = cls(history=history_payloads is not None, max_size=max_size, overflow=overflow)
        try:
            q.mode = QueueMode(mode)
        except ValueError:
            q.mode = QueueMode.NORMAL

        for p in payloads:
            if isinstance(p, dict):
                with contextlib.suppress(Exception):
                    q._put_one(TrackCls.from_payload(p))

        if history_payloads is not None and q.history is not None:
            for p in history_payloads:
                if isinstance(p, dict):
                    with contextlib.suppress(Exception):
                        q.history._items.append(TrackCls.from_payload(p))

        if loaded_payload is not None and isinstance(loaded_payload, dict):
            with contextlib.suppress(Exception):
                q._loaded = TrackCls.from_payload(loaded_payload)

        return q

    def put(self, item: Track | Playlist | Iterable[Track], /, *, atomic: bool = True) -> int:
        """Append one track, playlist, or iterable of tracks.

        Returns the number of tracks added.
        """

        tracks = self._coerce_tracks(item)
        if atomic:
            self._validate_tracks(tracks)
            self._ensure_capacity(len(tracks))

        added = 0
        for track in tracks:
            self._validate_track(track)
            self._put_one(track)
            added += 1

        return added

    async def put_wait(
        self,
        item: Track | Playlist | Iterable[Track],
        /,
        *,
        atomic: bool = True,
    ) -> int:
        """Async wrapper around `put` for command flows that prefer awaiting."""

        return self.put(item, atomic=atomic)

    def put_at(self, index: int, item: Track | Playlist | Iterable[Track], /) -> int:
        """Insert tracks at a specific queue index and return the number added."""

        tracks = self._coerce_tracks(item)
        self._validate_tracks(tracks)
        self._ensure_capacity(len(tracks))
        items = list(self._items)
        for offset, track in enumerate(tracks):
            items.insert(index + offset, track)
        self._items = deque(items)
        self._trim_overflow(from_left=index > 0)
        self._wakeup_next()
        return len(tracks)

    def get(self, *, bypass_loop: bool = False) -> Track:
        """Get the next track according to queue mode.

        Set ``bypass_loop=True`` for explicit skip-style behavior where the
        loaded track must not be returned again by ``LOOP``/``LOOP_ALL`` modes.
        """

        if not bypass_loop and self.mode is QueueMode.LOOP and self._loaded is not None:
            return self._loaded

        if (
            not bypass_loop
            and self.mode is QueueMode.LOOP_ALL
            and not self._items
            and self.history is not None
        ):
            self._items.extend(self.history._items)
            self.history.clear()

        if not self._items:
            raise QueueEmpty("The queue is empty.")

        track = self._items.popleft()
        previous = self._loaded
        recycled = not bypass_loop and self.mode is QueueMode.LOOP_ALL and previous is not None
        if recycled and previous is not None:
            self._items.append(previous)

        self._loaded = track
        if self.history is not None and not recycled:
            self.history.put(track)

        return track

    async def get_wait(self) -> Track:
        """Wait until a track is available, then return it."""

        if self._items:
            return self.get()

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[Track] = loop.create_future()
        self._waiters.append(waiter)
        return await waiter

    def get_at(self, index: int, /) -> Track:
        """Remove and return a track at index."""

        try:
            track = self._items[index]
        except IndexError as exc:
            raise QueueError(f"Queue index out of range: {index}") from exc

        del self._items[index]
        return track

    def peek(self, index: int = 0, /) -> Track:
        """Return a queued track without removing it."""

        try:
            return self._items[index]
        except IndexError as exc:
            raise QueueEmpty("The queue is empty.") from exc

    def remove(self, track: Track, /, *, count: int | None = 1) -> int:
        """Remove matching tracks and return the number removed."""

        removed = 0
        remaining: deque[Track] = deque()
        limit = count if count is not None else -1

        while self._items:
            item = self._items.popleft()
            if item == track and (limit < 0 or removed < limit):
                removed += 1
                continue
            remaining.append(item)

        self._items = remaining
        return removed

    def delete(self, index: int, /) -> None:
        """Delete a queued track by index."""

        self.get_at(index)

    def swap(self, first: int, second: int, /) -> None:
        """Swap two queued tracks by index."""

        items = list(self._items)
        try:
            items[first], items[second] = items[second], items[first]
        except IndexError as exc:
            raise QueueError("Queue index out of range while swapping tracks.") from exc

        self._items = deque(items)

    def move(self, source: int, destination: int, /) -> Track:
        """Move a queued track to another index and return it."""

        items = list(self._items)
        try:
            track = items.pop(source)
        except IndexError as exc:
            raise QueueError(f"Queue index out of range: {source}") from exc

        items.insert(destination, track)
        self._items = deque(items)
        return track

    def shuffle(self) -> None:
        """Shuffle queued tracks in place."""

        items = list(self._items)
        random.shuffle(items)
        self._items = deque(items)

    def index(self, track: Track, /) -> int:
        """Return the index of a queued track."""

        try:
            return list(self._items).index(track)
        except ValueError as exc:
            raise QueueError("Track is not in the queue.") from exc

    def find(self, query: str, /) -> Track | None:
        """Return the first queued track matching a title, author, identifier, or URI."""

        matches = self.find_all(query)
        return matches[0] if matches else None

    def find_all(self, query: str, /) -> list[Track]:
        """Return queued tracks matching a title, author, identifier, or URI."""

        needle = query.casefold()
        return [track for track in self._items if self._matches(track, needle)]

    def dedupe(self) -> int:
        """Remove duplicate queued tracks and return the number removed."""

        seen: set[tuple[str, str | None, str | None]] = set()
        kept: deque[Track] = deque()
        removed = 0
        for track in self._items:
            marker = (track.encoded, track.identifier, track.source)
            if marker in seen:
                removed += 1
                continue

            seen.add(marker)
            kept.append(track)

        self._items = kept
        return removed

    def drain(self, limit: int | None = None, /) -> list[Track]:
        """Remove and return up to `limit` tracks from the front of the queue."""

        if limit is not None and limit < 0:
            msg = "Drain limit cannot be negative."
            raise QueueError(msg)

        removed: list[Track] = []
        while self._items and (limit is None or len(removed) < limit):
            removed.append(self._items.popleft())

        return removed

    def clear_next(self, count: int, /) -> list[Track]:
        """Remove and return the next `count` queued tracks."""

        return self.drain(count)

    def clear(self) -> None:
        """Clear queued tracks without touching history or loaded track."""

        self._items.clear()

    def reset(self) -> None:
        """Clear queue, history, waiters, loaded track, and mode."""

        self.clear()
        self._loaded = None
        self.mode = QueueMode.NORMAL
        if self.history is not None:
            self.history.reset()

        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.cancel()

    def to_raw_data(self) -> dict[str, object]:
        """Serialise the queue to a plain dict using raw Lavalink track payloads.

        The returned dict can be passed to :meth:`from_payloads` to restore
        the queue without a live Lavalink node::

            data = queue.to_raw_data()
            restored = Queue.from_payloads(**data)
        """

        return {
            "payloads": [t.raw_data.copy() for t in self._items],
            "history_payloads": (
                [t.raw_data.copy() for t in self.history._items]
                if self.history is not None
                else None
            ),
            "mode": self.mode.value,
            "loaded_payload": self._loaded.raw_data.copy() if self._loaded is not None else None,
            "max_size": self.max_size,
            "overflow": self.overflow,
        }

    def copy(self) -> Queue:
        """Return a shallow copy of this queue."""

        queue = Queue(
            history=self.history is not None,
            max_size=self.max_size,
            overflow=self.overflow,
        )
        queue._items = self._items.copy()
        queue._loaded = self._loaded
        queue.mode = self.mode
        if queue.history is not None and self.history is not None:
            queue.history = self.history.copy()
        return queue

    def _put_one(self, track: Track) -> None:
        self._ensure_capacity(1)
        self._items.append(track)
        self._trim_overflow(from_left=True)
        self._wakeup_next()

    def _ensure_capacity(self, incoming: int) -> None:
        if self.max_size is None or self.overflow:
            return

        available = self.max_size - len(self._items)
        if incoming > available:
            msg = (
                f"Queue max_size {self.max_size} exceeded: "
                f"{len(self._items)} queued, {incoming} incoming."
            )
            raise QueueFull(msg)

    def _trim_overflow(self, *, from_left: bool) -> None:
        if self.max_size is None or not self.overflow:
            return

        while len(self._items) > self.max_size:
            if from_left:
                self._items.popleft()
            else:
                self._items.pop()

    def _wakeup_next(self) -> None:
        # Serve every pending waiter that we have an item for. `put_at` may add
        # several tracks at once, so resolving only a single waiter here would
        # leave the rest parked forever despite available items.
        while self._items and self._waiters:
            waiter = self._waiters.popleft()
            if waiter.done():
                continue

            waiter.set_result(self.get(bypass_loop=True))

    def _coerce_tracks(self, item: Track | Playlist | Iterable[Track]) -> list[Track]:
        if isinstance(item, Track):
            return [item]

        if isinstance(item, Playlist):
            return item.tracks.copy()

        return list(item)

    def _validate_tracks(self, tracks: Iterable[object]) -> None:
        for track in tracks:
            self._validate_track(track)

    def _validate_track(self, track: object) -> None:
        if not isinstance(track, Track):
            raise TypeError(f"Queue entries must be Track instances, not {type(track).__name__}.")

    @staticmethod
    def _matches(track: Track, needle: str) -> bool:
        fields = (
            track.title,
            track.author,
            track.identifier,
            track.uri or "",
            track.source or "",
        )
        return any(needle in field.casefold() for field in fields)
