"""Command-friendly result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from .filters import Filters
from .tracks import Playlist, Track
from .types import JsonObject


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    """Result returned by command-oriented queue helpers."""

    added: int
    tracks: list[Track] = field(default_factory=list)
    playlist: Playlist | None = None
    first_track: Track | None = None
    source: str | None = None
    filters: Filters | None = None
    message: str = ""

    @property
    def track(self) -> Track | None:
        """Alias for `first_track`."""

        return self.first_track

    @property
    def empty(self) -> bool:
        """Whether no tracks were added."""

        return self.added == 0


@dataclass(frozen=True, slots=True)
class LyricsLine:
    """One lyrics line, optionally timestamped in milliseconds."""

    text: str
    timestamp: int | None = None
    duration: int | None = None
    raw: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LyricsResult:
    """Lyrics payload normalized for bot commands."""

    text: str
    lines: list[LyricsLine] = field(default_factory=list)
    provider: str | None = None
    source: str | None = None
    synced: bool = False
    raw: JsonObject = field(default_factory=dict)

    def at(self, position: int) -> LyricsLine | None:
        """Return the latest synced line at a playback position."""

        selected: LyricsLine | None = None
        best = -1
        for line in self.lines:
            timestamp = line.timestamp
            if timestamp is None or timestamp > position:
                continue
            if timestamp > best:
                best = timestamp
                selected = line

        return selected
