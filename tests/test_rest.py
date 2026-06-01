from typing import Any

import pytest

import fluxwave
from fluxwave.types import JsonPayload


class VersionClient(fluxwave.RestClient):
    async def request(
        self,
        method: object,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> object:
        return "4.0.0"


class CustomClient(fluxwave.RestClient):
    def __init__(self) -> None:
        super().__init__("http://localhost:2333", password="password", user_id=123)
        self.calls: list[tuple[object, str, dict[str, Any] | None]] = []

    async def request(
        self,
        method: object,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> object:
        self.calls.append((method, path, json))
        return {"ok": True}


class DecodeClient(fluxwave.RestClient):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[tuple[object, str, JsonPayload | None]] = []

    async def request(
        self,
        method: object,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonPayload | None = None,
    ) -> object:
        self.calls.append((method, path, json))
        payload = {
            "encoded": "abc",
            "info": {
                "identifier": "id",
                "isSeekable": True,
                "author": "artist",
                "length": 1000,
                "isStream": False,
                "position": 0,
                "title": "song",
            },
        }
        if path == "/v4/decodetracks":
            return [payload]
        return payload


class RoutePlannerClient(fluxwave.RestClient):
    def __init__(self) -> None:
        super().__init__("http://localhost:2333", password="password", user_id=123)
        self.calls: list[tuple[object, str, dict[str, Any] | None]] = []

    async def request(
        self,
        method: object,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> object:
        self.calls.append((method, path, json))
        if path == "/v4/routeplanner/status":
            return {
                "class": "RotatingIpRoutePlanner",
                "details": {"failingAddresses": [{"address": "1.2.3.4"}]},
            }
        return None


class ErrorClient(fluxwave.RestClient):
    async def request(
        self,
        method: object,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> object:
        response = fluxwave.LavalinkErrorResponse.from_payload(
            {
                "timestamp": 1,
                "status": 401,
                "error": "Unauthorized",
                "message": "bad password",
                "path": "/v4/info",
            },
            fallback_status=401,
        )
        raise fluxwave.LavalinkError(response)


@pytest.mark.asyncio
async def test_fetch_version_parses_text_response() -> None:
    client = VersionClient("http://localhost:2333", password="password", user_id=123)

    assert await client.fetch_version() == "4.0.0"


@pytest.mark.asyncio
async def test_structured_lavalink_error_response() -> None:
    client = ErrorClient("http://localhost:2333", password="password", user_id=123)

    with pytest.raises(fluxwave.LavalinkError) as exc_info:
        await client.fetch_info()

    assert exc_info.value.response.status == 401
    assert exc_info.value.response.message == "bad password"


def test_player_update_payload_prefers_encoded_track() -> None:
    payload = fluxwave.PlayerUpdate(
        encoded_track="abc",
        identifier="ytsearch:test",
        user_data={"requester": 1},
        volume=250,
        paused=False,
    ).to_payload()

    assert payload == {
        "track": {"encoded": "abc", "userData": {"requester": 1}},
        "volume": 250,
        "paused": False,
    }


def test_session_update_payload_omits_unset_values() -> None:
    assert fluxwave.SessionUpdate(resuming=True).to_payload() == {"resuming": True}


@pytest.mark.asyncio
async def test_custom_rest_request_passthrough() -> None:
    client = CustomClient()

    response = await client.custom_request(
        "POST",
        "/v4/plugin/example",
        json={"value": 1},
    )

    assert response == {"ok": True}
    assert client.calls == [("POST", "/v4/plugin/example", {"value": 1})]


@pytest.mark.asyncio
async def test_decode_track_endpoints() -> None:
    client = DecodeClient("http://localhost:2333", password="password", user_id=123)

    track = await client.decode_track("abc")
    tracks = await client.decode_tracks(["abc"])

    assert track.encoded == "abc"
    assert tracks[0].title == "song"
    assert client.calls[-1] == ("POST", "/v4/decodetracks", ["abc"])


@pytest.mark.asyncio
async def test_routeplanner_rest_helpers() -> None:
    client = RoutePlannerClient()

    status = await client.fetch_routeplanner_status()
    await client.free_routeplanner_address("1.2.3.4")
    await client.free_all_routeplanner_addresses()

    assert status is not None
    assert status.class_name == "RotatingIpRoutePlanner"
    assert status.has_route_planner
    assert status.details["failingAddresses"] == [{"address": "1.2.3.4"}]
    assert client.calls == [
        ("GET", "/v4/routeplanner/status", None),
        ("POST", "/v4/routeplanner/free/address", {"address": "1.2.3.4"}),
        ("POST", "/v4/routeplanner/free/all", None),
    ]
