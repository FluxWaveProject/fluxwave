"""Low-level Lavalink REST client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

import aiohttp

from .exceptions import LavalinkError, LavalinkErrorResponse, NodeError
from .routeplanner import RoutePlannerStatus
from .tracks import LavalinkPlayer, LoadResult, NodeInfo, Stats, Track, VoiceState
from .types import JsonObject, JsonPayload

HttpMethod = Literal["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]
RestResponse = JsonObject | list[Any] | str | None


@dataclass(slots=True)
class PlayerUpdate:
    """Payload for Lavalink's update-player endpoint."""

    encoded_track: str | None = None
    identifier: str | None = None
    user_data: JsonObject | None = None
    position: int | None = None
    end_time: int | None = None
    volume: int | None = None
    paused: bool | None = None
    filters: JsonObject | None = None
    voice: VoiceState | None = None
    clear_track: bool = False

    def to_payload(self) -> JsonObject:
        """Convert to Lavalink's JSON request shape."""

        payload: JsonObject = {}

        if self.clear_track:
            payload["track"] = {"encoded": None}
        elif self.encoded_track is not None:
            track: JsonObject = {"encoded": self.encoded_track}
            if self.user_data is not None:
                track["userData"] = self.user_data
            payload["track"] = track
        elif self.identifier is not None:
            track = {"identifier": self.identifier}
            if self.user_data is not None:
                track["userData"] = self.user_data
            payload["track"] = track

        if self.position is not None:
            payload["position"] = self.position
        if self.end_time is not None:
            payload["endTime"] = self.end_time
        if self.volume is not None:
            payload["volume"] = self.volume
        if self.paused is not None:
            payload["paused"] = self.paused
        if self.filters is not None:
            payload["filters"] = self.filters
        if self.voice is not None:
            payload["voice"] = self.voice.to_payload()

        return payload


@dataclass(slots=True)
class SessionUpdate:
    """Payload for Lavalink's update-session endpoint."""

    resuming: bool | None = None
    timeout: int | None = None

    def to_payload(self) -> JsonObject:
        """Convert to Lavalink's JSON request shape."""

        payload: JsonObject = {}
        if self.resuming is not None:
            payload["resuming"] = self.resuming
        if self.timeout is not None:
            payload["timeout"] = self.timeout
        return payload


@dataclass(slots=True)
class RestClient:
    """Async Lavalink v4 REST client.

    The client owns a session only when one is not provided. Call `close()` when
    done, or use it as an async context manager.
    """

    base_uri: str
    password: str
    user_id: int | str
    client_name: str = "FluxWave/0.1"
    session: aiohttp.ClientSession | None = None
    request_timeout: float = 15.0
    retries: int = 2
    retry_base_delay: float = 0.25
    _owns_session: bool = field(default=False, init=False)

    async def __aenter__(self) -> RestClient:
        self._ensure_session()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    @property
    def headers(self) -> dict[str, str]:
        """Headers required by Lavalink REST endpoints."""

        return {
            "Authorization": self.password,
            "User-Id": str(self.user_id),
            "Client-Name": self.client_name,
        }

    async def close(self) -> None:
        """Close an internally owned aiohttp session."""

        if self._owns_session and self.session and not self.session.closed:
            await self.session.close()

    async def fetch_info(self) -> NodeInfo:
        """Fetch `/v4/info`."""

        return NodeInfo.from_payload(self._expect_object(await self.request("GET", "/v4/info")))

    async def fetch_stats(self) -> Stats:
        """Fetch `/v4/stats`."""

        return Stats.from_payload(self._expect_object(await self.request("GET", "/v4/stats")))

    async def fetch_version(self) -> str:
        """Fetch `/version`."""

        response = await self.request("GET", "/version")
        if not isinstance(response, str):
            msg = "Lavalink returned a non-text version response."
            raise NodeError(msg)
        return response

    async def load_tracks(self, identifier: str) -> LoadResult:
        """Fetch `/v4/loadtracks` for a URL or search identifier."""

        return LoadResult.from_payload(
            self._expect_object(
                await self.request("GET", "/v4/loadtracks", params={"identifier": identifier})
            )
        )

    async def decode_track(self, encoded_track: str) -> Track:
        """Decode one Lavalink encoded track."""

        return Track.from_payload(
            self._expect_object(
                await self.request(
                    "GET",
                    "/v4/decodetrack",
                    params={"encodedTrack": encoded_track},
                )
            )
        )

    async def decode_tracks(self, encoded_tracks: list[str]) -> list[Track]:
        """Decode multiple Lavalink encoded tracks."""

        response = await self.request("POST", "/v4/decodetracks", json=encoded_tracks)
        if not isinstance(response, list):
            msg = "Lavalink returned a non-list decoded tracks response."
            raise NodeError(msg)

        return [Track.from_payload(track) for track in response if isinstance(track, dict)]

    async def fetch_players(self, session_id: str) -> list[LavalinkPlayer]:
        """Fetch all players for a Lavalink session."""

        response = await self.request("GET", f"/v4/sessions/{quote(session_id, safe='')}/players")
        if not isinstance(response, list):
            msg = "Lavalink returned a non-list players response."
            raise NodeError(msg)
        return [
            LavalinkPlayer.from_payload(player) for player in response if isinstance(player, dict)
        ]

    async def fetch_player(self, session_id: str, guild_id: int) -> LavalinkPlayer:
        """Fetch one Lavalink player."""

        return LavalinkPlayer.from_payload(
            self._expect_object(
                await self.request(
                    "GET",
                    f"/v4/sessions/{quote(session_id, safe='')}/players/{guild_id}",
                )
            )
        )

    async def update_player(
        self,
        session_id: str,
        guild_id: int,
        update: PlayerUpdate,
        *,
        replace: bool = False,
    ) -> LavalinkPlayer:
        """Patch a Lavalink player."""

        response = await self.request(
            "PATCH",
            f"/v4/sessions/{quote(session_id, safe='')}/players/{guild_id}",
            params={"noReplace": str(not replace).lower()},
            json=update.to_payload(),
        )
        return LavalinkPlayer.from_payload(self._expect_object(response))

    async def destroy_player(self, session_id: str, guild_id: int) -> None:
        """Delete a Lavalink player."""

        await self.request(
            "DELETE",
            f"/v4/sessions/{quote(session_id, safe='')}/players/{guild_id}",
        )

    async def update_session(self, session_id: str, update: SessionUpdate) -> JsonObject:
        """Patch a Lavalink session."""

        return self._expect_object(
            await self.request(
                "PATCH",
                f"/v4/sessions/{quote(session_id, safe='')}",
                json=update.to_payload(),
            )
        )

    async def fetch_routeplanner_status(self) -> RoutePlannerStatus | None:
        """Fetch Lavalink route planner status, if route planner is configured."""

        response = await self.request("GET", "/v4/routeplanner/status")
        if response is None:
            return None

        return RoutePlannerStatus.from_payload(self._expect_object(response))

    async def free_routeplanner_address(self, address: str) -> None:
        """Free a failing address in Lavalink's route planner."""

        await self.request("POST", "/v4/routeplanner/free/address", json={"address": address})

    async def free_all_routeplanner_addresses(self) -> None:
        """Free all failing addresses in Lavalink's route planner."""

        await self.request("POST", "/v4/routeplanner/free/all")

    async def custom_request(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonPayload | None = None,
    ) -> RestResponse:
        """Call a Lavalink core or plugin REST endpoint and return the parsed response."""

        return await self.request(method, path, params=params, json=json)

    async def request(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonPayload | None = None,
    ) -> RestResponse:
        """Send a retry-safe request and parse JSON/text/empty responses."""

        session = self._ensure_session()
        url = f"{self.base_uri.rstrip('/')}/{path.lstrip('/')}"
        attempts = max(self.retries, 0) + 1

        for attempt in range(attempts):
            try:
                async with session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout),
                ) as response:
                    return await self._parse_response(response)
            except (aiohttp.ClientError, TimeoutError) as exc:
                if attempt >= attempts - 1:
                    msg = f"Request to Lavalink failed after {attempts} attempt(s): {method} {path}"
                    raise NodeError(msg) from exc

                await asyncio.sleep(self.retry_base_delay * (2**attempt))

        msg = "Request retry loop ended unexpectedly."
        raise NodeError(msg)

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            self.session = aiohttp.ClientSession()
            self._owns_session = True
            return self.session

        if self.session.closed:
            # Never silently take ownership of (and replace) a session the caller
            # provided and then closed — surface it instead of masking the misuse.
            if not self._owns_session:
                msg = "The externally provided aiohttp session is closed."
                raise NodeError(msg)
            self.session = aiohttp.ClientSession()
            self._owns_session = True

        return self.session

    async def _parse_response(
        self,
        response: aiohttp.ClientResponse,
    ) -> RestResponse:
        if response.status == 204:
            return None

        if response.status >= 300:
            raise LavalinkError(await self._parse_error(response))

        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            parsed = await response.json()
            if isinstance(parsed, dict | list):
                return parsed
            msg = "Lavalink returned an unsupported JSON response."
            raise NodeError(msg)

        text = await response.text()
        return text if text else None

    def _expect_object(self, response: RestResponse) -> JsonObject:
        if isinstance(response, dict):
            return response

        msg = "Lavalink returned a non-object response."
        raise NodeError(msg)

    async def _parse_error(self, response: aiohttp.ClientResponse) -> LavalinkErrorResponse:
        try:
            parsed = await response.json()
        except (aiohttp.ContentTypeError, ValueError):
            parsed = {}

        if not isinstance(parsed, dict):
            parsed = {}

        return LavalinkErrorResponse.from_payload(parsed, fallback_status=response.status)
