"""Autoplay and recommendation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .search import Search, SearchSource
from .tracks import Track


class SearchNode(Protocol):
    """Node subset needed by the default recommendation provider."""

    async def search(
        self,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        use_cache: bool = True,
    ) -> Search:
        """Search for tracks."""
        ...


class AutoPlayMode(StrEnum):
    """How a player should use generated recommendations."""

    DISABLED = "disabled"
    PARTIAL = "partial"
    ENABLED = "enabled"
    disabled = "disabled"
    partial = "partial"
    enabled = "enabled"


class RecommendationProvider(Protocol):
    """Interface for source-specific recommendation providers."""

    async def recommendations(
        self,
        seed: Track,
        *,
        limit: int = 5,
    ) -> list[Track]:
        """Return recommendation tracks for a seed track."""
        ...


@dataclass(slots=True)
class SearchRecommendationProvider:
    """Simple recommendation provider using Lavalink search sources."""

    node: SearchNode
    source: SearchSource | str | None = None

    async def recommendations(
        self,
        seed: Track,
        *,
        limit: int = 5,
    ) -> list[Track]:
        tracks: list[Track] = []
        seen = {_track_key(seed)}
        for query, source in _queries_for_track(seed, limit=limit, source=self.source):
            result = await self.node.search(query, source=source)
            if not isinstance(result, list):
                continue

            for track in result:
                key = _track_key(track)
                if key in seen:
                    continue

                seen.add(key)
                tracks.append(track.as_recommended())
                if len(tracks) >= limit:
                    return _rank_recommendations(seed, tracks)

        return _rank_recommendations(seed, tracks)


def _source_for_track(track: Track) -> SearchSource | str | None:
    if track.source == "spotify":
        return None
    if track.source == "youtube":
        return None
    if track.source == "soundcloud":
        return SearchSource.SOUNDCLOUD
    return SearchSource.YOUTUBE


def _query_for_track(track: Track, *, limit: int) -> str:
    if track.source == "spotify":
        return f"sprec:seed_tracks={track.identifier}&limit={limit}"

    if track.source == "youtube":
        return f"https://music.youtube.com/watch?v={track.identifier}&list=RD{track.identifier}"

    album = track.plugin_info.get("album") or track.plugin_info.get("albumName")
    if isinstance(album, str) and album:
        return f"{track.author} {album}"

    return f"{track.author} {track.title}"


def _queries_for_track(
    track: Track,
    *,
    limit: int,
    source: SearchSource | str | None,
) -> list[tuple[str, SearchSource | str | None]]:
    selected_source = source if source is not None else _source_for_track(track)
    queries: list[tuple[str, SearchSource | str | None]] = [
        (_query_for_track(track, limit=limit), selected_source)
    ]

    title_author = f"{track.author} {track.title}"
    if track.source in {"spotify", "youtube"}:
        queries.append((title_author, SearchSource.YOUTUBE_MUSIC))
        queries.append((title_author, SearchSource.YOUTUBE))
    elif track.source == "soundcloud":
        queries.append((title_author, SearchSource.SOUNDCLOUD))
        queries.append((title_author, SearchSource.YOUTUBE))
    else:
        queries.append((title_author, SearchSource.YOUTUBE_MUSIC))
        queries.append((title_author, SearchSource.SOUNDCLOUD))

    deduped: list[tuple[str, SearchSource | str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for query, query_source in queries:
        key = (query, str(query_source) if query_source is not None else None)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((query, query_source))

    return deduped


def _track_key(track: Track) -> str:
    title = " ".join(track.title.casefold().split())
    author = " ".join(track.author.casefold().split())
    return f"{track.source or ''}:{track.identifier}:{title}:{author}"


def _rank_recommendations(seed: Track, tracks: list[Track]) -> list[Track]:
    return sorted(tracks, key=lambda track: _recommendation_score(seed, track), reverse=True)


def _recommendation_score(seed: Track, track: Track) -> float:
    score = 1.0
    if track.source == seed.source:
        score += 0.3
    if track.author.casefold() == seed.author.casefold():
        score += 0.4
    if seed.title.casefold() in track.title.casefold():
        score -= 0.2
    if track.recommended:
        score += 0.1
    return score
