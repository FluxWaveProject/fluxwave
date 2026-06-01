"""Library-agnostic rendering helpers for now-playing displays and queue pages.

These return plain strings and data so they work with any Discord library's
embed/message API. They never touch a live node or player.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .tracks import Track


def format_duration(milliseconds: int) -> str:
    """Format a millisecond duration as ``H:MM:SS`` or ``M:SS``."""

    milliseconds = max(milliseconds, 0)
    total_seconds = milliseconds // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def progress_bar(
    position: int,
    duration: int,
    *,
    length: int = 20,
    filled: str = "█",
    empty: str = "─",
    marker: str = "\U0001f518",
    show_time: bool = True,
) -> str:
    """Render a textual playback progress bar from millisecond values.

    With the default ``marker`` the bar always spans exactly ``length`` cells::

        progress_bar(60_000, 180_000, length=10)

    Set ``marker=""`` for a plain filled/empty bar, and ``show_time=False`` to
    omit the trailing ``position / duration`` text.
    """

    length = max(length, 1)
    ratio = 0.0 if duration <= 0 else min(max(position / duration, 0.0), 1.0)

    if marker:
        index = min(int(ratio * length), length - 1)
        bar = filled * index + marker + empty * (length - index - 1)
    else:
        count = min(round(ratio * length), length)
        bar = filled * count + empty * (length - count)

    if not show_time:
        return bar
    return f"{bar} {format_duration(position)} / {format_duration(duration)}"


@dataclass(frozen=True, slots=True)
class QueuePage:
    """One rendered page of queued tracks."""

    index: int
    page_count: int
    items: list[tuple[int, Track]]
    per_page: int
    total: int

    @property
    def number(self) -> int:
        """1-based page number for display."""

        return self.index + 1

    def lines(
        self,
        *,
        template: str = "{position}. {title} — {author} [{duration}]",
    ) -> list[str]:
        """Render each track on the page with a format template.

        Available fields: ``position``, ``title``, ``author``, ``duration``,
        ``identifier``, ``uri``, ``source``.
        """

        return [
            template.format(
                position=position,
                title=track.title,
                author=track.author,
                duration=format_duration(track.duration),
                identifier=track.identifier,
                uri=track.uri or "",
                source=track.source or "",
            )
            for position, track in self.items
        ]


def paginate_queue(
    tracks: Iterable[Track],
    *,
    per_page: int = 10,
    start: int = 1,
) -> list[QueuePage]:
    """Split tracks into :class:`QueuePage` chunks for paged queue displays.

    ``start`` is the 1-based position of the first track (use ``2`` when the
    first queued track is "up next" after the current one). Always returns at
    least one page, which is empty when there are no tracks.
    """

    per_page = max(per_page, 1)
    items = list(tracks)
    total = len(items)
    page_count = max((total + per_page - 1) // per_page, 1)

    pages: list[QueuePage] = []
    for index in range(page_count):
        chunk = items[index * per_page : (index + 1) * per_page]
        positioned = [
            (start + index * per_page + offset, track) for offset, track in enumerate(chunk)
        ]
        pages.append(
            QueuePage(
                index=index,
                page_count=page_count,
                items=positioned,
                per_page=per_page,
                total=total,
            )
        )
    return pages
