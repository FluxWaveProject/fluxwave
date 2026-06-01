"""High-level search helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
from urllib.parse import urlparse

from .exceptions import TrackLoadError
from .tracks import LoadResult, LoadType, Playlist, Track

Search: TypeAlias = list[Track] | Playlist


class SearchSource(StrEnum):
    """Built-in Lavalink search source prefixes."""

    YOUTUBE = "ytsearch"
    YOUTUBE_MUSIC = "ytmsearch"
    SOUNDCLOUD = "scsearch"
    youtube = "ytsearch"
    youtube_music = "ytmsearch"
    soundcloud = "scsearch"


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Normalized Lavalink search query."""

    original: str
    identifier: str
    source: str | None
    is_url: bool
    has_prefix: bool


def build_search_query(
    query: str,
    *,
    source: SearchSource | str | None = SearchSource.YOUTUBE,
) -> SearchQuery:
    """Build a Lavalink identifier from a user query and optional source."""

    cleaned = query.strip()
    if not cleaned:
        raise ValueError("Search query cannot be empty.")

    is_url = _is_url(cleaned)
    has_prefix = _has_prefix(cleaned)
    normalized_source = _normalize_source(source)

    if is_url or has_prefix or normalized_source is None:
        identifier = cleaned
    else:
        identifier = f"{normalized_source}:{cleaned}"

    return SearchQuery(
        original=query,
        identifier=identifier,
        source=normalized_source,
        is_url=is_url,
        has_prefix=has_prefix,
    )


def unwrap_load_result(result: LoadResult) -> Search:
    """Convert a load result into the high-level search return shape."""

    if result.load_type is LoadType.PLAYLIST:
        if result.playlist is None:
            return []
        return result.playlist

    if result.load_type in {LoadType.TRACK, LoadType.SEARCH}:
        return result.tracks

    if result.load_type is LoadType.EMPTY:
        return []

    if result.load_type is LoadType.ERROR:
        message = result.error.message if result.error else "Lavalink failed to load tracks."
        raise TrackLoadError(
            message,
            severity=result.error.severity if result.error else None,
            cause=result.error.cause if result.error else None,
        )

    return []


def _normalize_source(source: SearchSource | str | None) -> str | None:
    if source is None:
        return None

    prefix = str(source.value if isinstance(source, SearchSource) else source).strip()
    if not prefix:
        return None

    return prefix.removesuffix(":")


def _is_url(query: str) -> bool:
    parsed = urlparse(query)
    return bool(parsed.scheme and parsed.netloc)


_KNOWN_SEARCH_PREFIXES = frozenset(
    {
        "ytsearch",
        "ytmsearch",
        "scsearch",
        "spsearch",
        "sprec",
        "amsearch",
        "dzsearch",
        "dzisrc",
        "ymsearch",
        "vksearch",
        "tdsearch",
        "bcsearch",
        "ftts",
    }
)


def _has_prefix(query: str) -> bool:
    if ":" not in query:
        return False

    head = query.split(":", 1)[0]
    if not head or " " in head or _is_url(query):
        return False

    lowered = head.lower()
    return lowered in _KNOWN_SEARCH_PREFIXES or lowered.endswith("search")
