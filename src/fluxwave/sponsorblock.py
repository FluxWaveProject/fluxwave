"""Client-side SponsorBlock segment skipping for players."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from .types import JsonObject

if TYPE_CHECKING:
    from .tracks import Track

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES: tuple[str, ...] = (
    "sponsor",
    "selfpromo",
    "interaction",
    "intro",
    "outro",
    "preview",
    "music_offtopic",
)
"""SponsorBlock categories enabled by default."""

_INLINE_KEYS = ("sponsorblock", "sponsorBlock", "sponsorblockSegments")


class SponsorBlockAction(StrEnum):
    """What to do when the playhead enters a SponsorBlock segment."""

    SKIP = "skip"
    NOTIFY = "notify"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class SponsorSegment:
    """One SponsorBlock segment in milliseconds."""

    category: str
    start: int
    end: int
    uuid: str | None = None
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: JsonObject) -> SponsorSegment:
        """Build a segment from a SponsorBlock plugin/API payload."""

        return cls(
            category=_str(payload.get("category")),
            start=_int(payload.get("start")),
            end=_int(payload.get("end")),
            uuid=_optional_str(payload.get("UUID") or payload.get("uuid")),
            raw=payload.copy(),
        )

    @property
    def duration(self) -> int:
        """Segment length in milliseconds."""

        return max(self.end - self.start, 0)

    @property
    def key(self) -> str:
        """Stable identifier used to avoid skipping a segment twice."""

        return self.uuid or f"{self.category}:{self.start}:{self.end}"

    def contains(self, position: int, *, margin: int = 0) -> bool:
        """Whether *position* (ms) falls inside the segment, past *margin* ms.

        The margin keeps a track from being skipped the instant it enters a
        segment, which would otherwise fight a user's own ``seek``.
        """

        return self.start + margin <= position < self.end


@dataclass(frozen=True, slots=True)
class SponsorBlockConfig:
    """Configuration for :class:`SponsorBlockManager`."""

    categories: tuple[str, ...] = DEFAULT_CATEGORIES
    action: SponsorBlockAction = SponsorBlockAction.SKIP
    skip_margin: int = 250
    """Milliseconds to play into a segment before skipping it."""

    min_duration: int = 1000
    """Segments shorter than this are ignored."""

    def with_categories(self, categories: Iterable[str]) -> SponsorBlockConfig:
        """Return a copy with a different category set."""

        return replace(self, categories=tuple(categories))


class SponsorBlockPlayer(Protocol):
    """Player surface the manager needs."""

    @property
    def position(self) -> int: ...

    @property
    def current(self) -> Track | None: ...

    async def seek(self, position: int = 0) -> None: ...


class SponsorBlockManager:
    """Tracks SponsorBlock segments for a player and skips past them."""

    __slots__ = (
        "_config",
        "_generation",
        "_player",
        "_segments",
        "_skip_tasks",
        "_skipped",
        "_task",
    )

    def __init__(
        self,
        player: SponsorBlockPlayer,
        *,
        config: SponsorBlockConfig | None = None,
    ) -> None:
        self._player = player
        self._config = config or SponsorBlockConfig()
        self._segments: tuple[SponsorSegment, ...] = ()
        self._skipped: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._skip_tasks: set[asyncio.Task[None]] = set()
        self._generation = 0

    @property
    def config(self) -> SponsorBlockConfig:
        """Active configuration."""

        return self._config

    @property
    def segments(self) -> tuple[SponsorSegment, ...]:
        """Segments known for the current track, filtered by the active config."""

        return self._filtered_segments(self._segments)

    @property
    def enabled(self) -> bool:
        """Whether automatic skipping or notification is active."""

        return self._config.action is not SponsorBlockAction.DISABLED

    def set_config(self, config: SponsorBlockConfig) -> SponsorBlockConfig:
        """Replace the configuration and reset per-track skip bookkeeping."""

        self._config = config
        self._skipped.clear()
        return self._config

    def handle_track_start(self, track: Track) -> None:
        """Begin tracking a newly started track."""

        self._generation += 1
        self._segments = ()
        self._skipped.clear()
        self.cancel()

        inline = _inline_segments(track)
        if inline:
            # Keep the raw inline set so changing categories later can restore
            # segments; the public ``segments`` property applies the filters.
            self._segments = inline
            return

        if not self.enabled:
            return

        self._task = asyncio.create_task(self._fetch(track, self._generation))

    def handle_player_update(self, position: int) -> None:
        """Skip or notify when the playhead enters a segment."""

        if not self.enabled:
            return

        for segment in self.segments:
            if segment.key in self._skipped:
                continue
            if segment.contains(position, margin=self._config.skip_margin):
                self._skipped.add(segment.key)
                self._schedule_skip(segment, position)
                return

    async def refresh(self, track: Track | None = None) -> list[SponsorSegment]:
        """Fetch and store segments for *track* (or the current track) now."""

        target = track if track is not None else self._player.current
        if target is None:
            self._segments = ()
            return []
        self._segments = await self._load_segments(target)
        return list(self.segments)

    def cancel(self) -> None:
        """Cancel any in-flight segment fetch."""

        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _fetch(self, track: Track, generation: int) -> None:
        try:
            segments = await self._load_segments(track)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("SponsorBlock segment fetch failed.", exc_info=True)
            return

        if generation != self._generation:
            return

        self._segments = segments

    async def _load_segments(self, track: Track) -> tuple[SponsorSegment, ...]:
        inline = _inline_segments(track)
        if inline:
            return inline

        return await _plugin_segments(self._player, track)

    def _filtered_segments(self, segments: Iterable[SponsorSegment]) -> tuple[SponsorSegment, ...]:
        categories = set(self._config.categories)
        return tuple(
            segment
            for segment in segments
            if segment.category in categories and segment.duration >= self._config.min_duration
        )

    def _schedule_skip(self, segment: SponsorSegment, position: int) -> None:
        # Only a NOTIFY-style caller wants to observe the skip without seeking.
        notifier = getattr(self._player, "_notify_sponsorblock_skip", None)
        if notifier is not None:
            notifier(segment, position)

        if self._config.action is not SponsorBlockAction.SKIP:
            return

        try:
            task = asyncio.create_task(self._skip(segment))
        except RuntimeError:
            logger.debug("Cannot schedule SponsorBlock skip without a running loop.")
            return
        self._skip_tasks.add(task)
        task.add_done_callback(self._skip_tasks.discard)

    async def _skip(self, segment: SponsorSegment) -> None:
        with contextlib.suppress(Exception):
            await self._player.seek(segment.end)

    def __repr__(self) -> str:
        return (
            f"SponsorBlockManager(enabled={self.enabled}, "
            f"action={self._config.action.value}, segments={len(self._segments)})"
        )


def _inline_segments(track: Track) -> tuple[SponsorSegment, ...]:
    plugin_info = track.plugin_info
    payload: object = None
    for key in _INLINE_KEYS:
        if key in plugin_info:
            payload = plugin_info[key]
            break

    return _coerce_segments(payload)


async def _plugin_segments(
    player: SponsorBlockPlayer,
    track: Track,
) -> tuple[SponsorSegment, ...]:
    node = getattr(player, "node", None)
    plugins = getattr(node, "plugins", None)
    client = getattr(plugins, "sponsorblock", None)
    fetch = getattr(client, "segments", None)
    if fetch is None:
        return ()

    try:
        response = await fetch(track.identifier)
    except Exception:
        logger.debug("SponsorBlock plugin segment lookup failed.", exc_info=True)
        return ()

    if isinstance(response, dict):
        response = response.get("segments", response.get("data"))
    return _coerce_segments(response)


def _coerce_segments(payload: object) -> tuple[SponsorSegment, ...]:
    if isinstance(payload, dict):
        payload = payload.get("segments", payload.get("data"))
    if not isinstance(payload, list):
        return ()

    segments: list[SponsorSegment] = [
        SponsorSegment.from_payload(item) for item in payload if isinstance(item, dict)
    ]
    return tuple(segments)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _str(value: object, *, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int(value: object, *, default: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default
