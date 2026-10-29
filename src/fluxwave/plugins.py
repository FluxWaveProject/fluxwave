"""Convenience helpers for common Lavalink plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .exceptions import NodeError
from .filters import Filters
from .rest import HttpMethod, RestResponse
from .search import Search
from .types import JsonPayload


class PluginNode(Protocol):
    """Node surface needed by plugin helper clients."""

    session_id: str | None

    async def custom_request(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonPayload | None = None,
    ) -> RestResponse:
        """Call a plugin REST endpoint."""
        ...

    async def search(
        self,
        query: str,
        *,
        source: str | None = None,
        use_cache: bool = True,
    ) -> Search:
        """Search with a plugin source prefix."""
        ...


@dataclass(frozen=True, slots=True)
class PluginClient:
    """Low-level plugin REST helper."""

    node: PluginNode

    async def custom(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonPayload | None = None,
    ) -> RestResponse:
        """Call any plugin endpoint through the node."""

        return await self.node.custom_request(method, path, params=params, json=json)


@dataclass(frozen=True, slots=True)
class LavaSrcClient:
    """Search helpers for LavaSrc-compatible source prefixes."""

    node: PluginNode

    async def spotify(self, query: str, *, use_cache: bool = True) -> Search:
        """Search Spotify via LavaSrc's `spsearch` prefix."""

        return await self.node.search(query, source="spsearch", use_cache=use_cache)

    async def apple_music(self, query: str, *, use_cache: bool = True) -> Search:
        """Search Apple Music via LavaSrc's `amsearch` prefix."""

        return await self.node.search(query, source="amsearch", use_cache=use_cache)

    async def deezer(self, query: str, *, use_cache: bool = True) -> Search:
        """Search Deezer via LavaSrc's `dzsearch` prefix."""

        return await self.node.search(query, source="dzsearch", use_cache=use_cache)

    async def yandex_music(self, query: str, *, use_cache: bool = True) -> Search:
        """Search Yandex Music via LavaSrc's `ymsearch` prefix."""

        return await self.node.search(query, source="ymsearch", use_cache=use_cache)


@dataclass(frozen=True, slots=True)
class LyricsClient:
    """Best-effort helpers for Lavalink lyrics plugins."""

    node: PluginNode

    async def current(
        self,
        guild_id: int,
        *,
        skip_track_source: bool = False,
    ) -> RestResponse:
        """Fetch lyrics for a guild's current player when supported by LavaLyrics."""

        session_id = self._require_session()
        return await self.node.custom_request(
            "GET",
            f"/v4/sessions/{session_id}/players/{guild_id}/track/lyrics",
            params={"skipTrackSource": str(skip_track_source).lower()},
        )

    async def track(
        self,
        encoded_track: str,
        *,
        skip_track_source: bool = False,
    ) -> RestResponse:
        """Fetch lyrics for an encoded Lavalink track."""

        return await self.node.custom_request(
            "GET",
            "/v4/lyrics",
            params={
                "track": encoded_track,
                "skipTrackSource": str(skip_track_source).lower(),
            },
        )

    async def search(self, query: str, *, source: str | None = None) -> RestResponse:
        """Search lyrics when a custom lyrics plugin exposes `/v4/lyrics/search`.

        LavaLyrics itself does not expose this endpoint; use :meth:`current` or
        :meth:`track` for LavaLyrics.
        """

        params = {"query": query}
        if source is not None:
            params["source"] = source
        return await self.node.custom_request("GET", "/v4/lyrics/search", params=params)

    def _require_session(self) -> str:
        if self.node.session_id is None:
            msg = "Node does not have an active Lavalink session."
            raise NodeError(msg)

        return self.node.session_id


@dataclass(frozen=True, slots=True)
class SponsorBlockClient:
    """Best-effort helpers for SponsorBlock-compatible Lavalink plugins."""

    node: PluginNode

    async def categories(self, guild_id: int) -> RestResponse:
        """Fetch enabled SponsorBlock categories for a guild player."""

        return await self.node.custom_request(
            "GET",
            self._categories_path(guild_id),
        )

    async def set_categories(
        self,
        guild_id: int,
        categories: list[str],
    ) -> RestResponse:
        """Set SponsorBlock categories for a guild player."""

        return await self.node.custom_request(
            "PUT",
            self._categories_path(guild_id),
            json=categories,
        )

    async def clear_categories(self, guild_id: int) -> RestResponse:
        """Disable SponsorBlock categories for a guild player."""

        return await self.node.custom_request(
            "DELETE",
            self._categories_path(guild_id),
        )

    async def segments(self, identifier: str) -> RestResponse:
        """Fetch SponsorBlock segments for a source identifier when supported.

        Most SponsorBlock Lavalink plugins expose player category routes and
        send segment data through events instead of a direct segment lookup.
        This helper remains best-effort for compatible custom builds.
        """

        return await self.node.custom_request(
            "GET",
            "/v4/sponsorblock/segments",
            params={"identifier": identifier},
        )

    async def chapters(self, identifier: str) -> RestResponse:
        """Fetch SponsorBlock chapters for a source identifier when supported."""

        return await self.node.custom_request(
            "GET",
            "/v4/sponsorblock/chapters",
            params={"identifier": identifier},
        )

    def _categories_path(self, guild_id: int) -> str:
        session_id = self._require_session()
        return f"/v4/sessions/{session_id}/players/{guild_id}/sponsorblock/categories"

    def _require_session(self) -> str:
        if self.node.session_id is None:
            msg = "Node does not have an active Lavalink session."
            raise NodeError(msg)

        return self.node.session_id


@dataclass(frozen=True, slots=True)
class LavaDSPXClient:
    """Helpers for the LavaDSPX audio-filter plugin.

    LavaDSPX applies effects through Lavalink's ``pluginFilters.lavadspx``
    payload, so these helpers build a :class:`~fluxwave.Filters` container rather
    than calling a REST route.
    """

    node: PluginNode

    def filters(self, **effects: object) -> Filters:
        """Return filters with LavaDSPX effects configured::

        filters = node.plugins.lavadspx.filters(echo={"delay": 0.5})
        """

        return Filters().set_plugin_filters(lavadspx=effects)


@dataclass(frozen=True, slots=True)
class LavaSearchClient:
    """REST helpers for the LavaSearch multi-source search plugin."""

    node: PluginNode

    async def tracks(self, query: str) -> RestResponse:
        """Search tracks across all configured sources."""

        return await self._search("tracks", query)

    async def albums(self, query: str) -> RestResponse:
        """Search albums across all configured sources."""

        return await self._search("albums", query)

    async def artists(self, query: str) -> RestResponse:
        """Search artists across all configured sources."""

        return await self._search("artists", query)

    async def playlists(self, query: str) -> RestResponse:
        """Search playlists across all configured sources."""

        return await self._search("playlists", query)

    async def text(self, query: str) -> RestResponse:
        """Search plain text across all configured sources."""

        return await self._search("text", query)

    async def _search(self, resource: str, query: str) -> RestResponse:
        return await self.node.custom_request(
            "GET",
            f"/v4/lavasearch/{resource}",
            params={"query": query},
        )


@dataclass(frozen=True, slots=True)
class PluginHelpers:
    """Grouped plugin helpers for a node."""

    node: PluginNode

    @property
    def rest(self) -> PluginClient:
        """Low-level plugin REST helper."""

        return PluginClient(self.node)

    @property
    def lavasrc(self) -> LavaSrcClient:
        """LavaSrc search helpers."""

        return LavaSrcClient(self.node)

    @property
    def lavasearch(self) -> LavaSearchClient:
        """LavaSearch multi-source search helpers."""

        return LavaSearchClient(self.node)

    @property
    def lavadspx(self) -> LavaDSPXClient:
        """LavaDSPX audio-filter helpers."""

        return LavaDSPXClient(self.node)

    @property
    def lyrics(self) -> LyricsClient:
        """Lyrics plugin helpers."""

        return LyricsClient(self.node)

    @property
    def sponsorblock(self) -> SponsorBlockClient:
        """SponsorBlock plugin helpers."""

        return SponsorBlockClient(self.node)
