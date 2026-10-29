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


@dataclass(frozen=True, slots=True)
class NowPlaying:
    """Library-agnostic snapshot of a player suitable for an embed.

    :meth:`fields` returns ``(name, value, inline)`` tuples that map directly
    onto discord.py/py-cord/nextcord/disnake ``Embed.add_field`` calls, and
    :meth:`to_dict` returns the same data as a plain dict::

        view = NowPlaying.from_player(player)
        embed = discord.Embed(title=view.title, description=view.progress(length=15))
        for name, value, inline in view.fields():
            embed.add_field(name=name, value=value, inline=inline)
    """

    track: Track | None = None
    position: int = 0
    volume: int = 100
    paused: bool = False
    loop_mode: str = "normal"
    autoplay: bool = False
    queue_length: int = 0
    requester: object | None = None

    @classmethod
    def from_player(
        cls,
        player: object,
        *,
        requester: object | None = None,
    ) -> NowPlaying:
        """Build a snapshot from a player-like object."""

        track = getattr(player, "current", None)
        if requester is None and isinstance(track, Track):
            requester = track.user_data.get("requester")

        queue = getattr(player, "queue", None)
        mode = getattr(queue, "mode", None)
        autoplay = getattr(player, "autoplay", None)

        return cls(
            track=track if isinstance(track, Track) else None,
            position=int(getattr(player, "position", 0) or 0),
            volume=int(getattr(player, "volume", 100) or 0),
            paused=bool(getattr(player, "paused", False)),
            loop_mode=str(getattr(mode, "value", mode) or "normal"),
            autoplay=str(getattr(autoplay, "value", autoplay) or "disabled").casefold()
            not in {"", "disabled", "none", "false"},
            queue_length=len(queue) if queue is not None else 0,
            requester=requester,
        )

    @property
    def title(self) -> str:
        """Display title for the now-playing embed."""

        return self.track.title if self.track is not None else "Nothing playing"

    @property
    def duration(self) -> int:
        """Current track duration in milliseconds."""

        return self.track.duration if self.track is not None else 0

    def progress(self, *, length: int = 20, **options: object) -> str:
        """Render a progress bar for the current track."""

        if self.track is None:
            return ""

        duration = 0 if self.track.is_stream else self.track.duration
        return progress_bar(self.position, duration, length=length, **options)  # type: ignore[arg-type]

    def fields(self, *, progress_length: int = 20) -> list[tuple[str, str, bool]]:
        """Return ``(name, value, inline)`` embed fields."""

        if self.track is None:
            return [("Playback", "Nothing is playing.", False)]

        fields: list[tuple[str, str, bool]] = [
            ("Author", self.track.author or "Unknown", True),
            ("Duration", self.track.length_display, True),
            ("Volume", f"{self.volume}%", True),
            ("Progress", self.progress(length=progress_length), False),
            ("Queue", str(self.queue_length), True),
            ("Loop", self.loop_mode, True),
            ("Autoplay", "on" if self.autoplay else "off", True),
        ]
        if self.track.uri:
            fields.append(("Source", self.track.uri, False))
        if self.requester is not None:
            fields.append(("Requested by", str(self.requester), False))
        return fields

    def to_dict(self, *, progress_length: int = 20) -> dict[str, object]:
        """Return the snapshot as a plain dict."""

        return {
            "title": self.title,
            "author": self.track.author if self.track is not None else None,
            "duration": self.track.length_display if self.track is not None else None,
            "position": self.position,
            "volume": self.volume,
            "paused": self.paused,
            "loop_mode": self.loop_mode,
            "autoplay": self.autoplay,
            "queue_length": self.queue_length,
            "requester": self.requester,
            "progress": self.progress(length=progress_length),
            "fields": self.fields(progress_length=progress_length),
            "artwork_url": self.track.artwork_url if self.track is not None else None,
        }


@dataclass(frozen=True, slots=True)
class QueueView:
    """A paged view over a queue, plus the currently playing track."""

    pages: list[QueuePage]
    current: Track | None = None
    total_duration: int = 0

    @classmethod
    def from_queue(
        cls,
        queue: object,
        *,
        current: Track | None = None,
        per_page: int = 10,
        start: int = 1,
    ) -> QueueView:
        """Build a paged view from a queue-like object."""

        tracks = list(queue) if isinstance(queue, Iterable) else []
        total = int(getattr(queue, "total_duration", 0) or 0)
        return cls(
            pages=paginate_queue(tracks, per_page=per_page, start=start),
            current=current,
            total_duration=total,
        )

    @property
    def page_count(self) -> int:
        """Number of available pages."""

        return len(self.pages)

    def page(self, index: int = 0) -> QueuePage:
        """Return a page, clamped into range."""

        if not self.pages:
            return QueuePage(index=0, page_count=1, items=[], per_page=1, total=0)
        return self.pages[max(0, min(index, self.page_count - 1))]

    def fields(
        self,
        *,
        page: int = 0,
        template: str = "{position}. {title} — {author} [{duration}]",
        empty: str = "The queue is empty.",
    ) -> list[tuple[str, str, bool]]:
        """Return ``(name, value, inline)`` embed fields for one page."""

        current_page = self.page(page)
        header = f"**Now:** {self.current.title}" if self.current is not None else None
        body = "\n".join(current_page.lines(template=template)) or empty
        if header is not None:
            body = f"{header}\n{body}"

        return [
            (
                f"Queue ({current_page.number}/{current_page.page_count})",
                body,
                False,
            ),
            ("Total length", format_duration(self.total_duration), True),
            ("Tracks", str(current_page.total), True),
        ]

    def to_dict(
        self,
        *,
        page: int = 0,
        template: str = "{position}. {title} — {author} [{duration}]",
        empty: str = "The queue is empty.",
    ) -> dict[str, object]:
        """Return the page as a plain dict."""

        current_page = self.page(page)
        return {
            "page": current_page.number,
            "page_count": current_page.page_count,
            "total": current_page.total,
            "lines": current_page.lines(template=template),
            "fields": self.fields(page=page, template=template, empty=empty),
            "total_duration": self.total_duration,
        }
