from __future__ import annotations

import aiohttp
import pytest

import fluxwave


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        json_data: object = None,
        text_data: str = "",
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.json_data = json_data
        self.text_data = text_data

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def json(self) -> object:
        if self.json_data is aiohttp.ContentTypeError:
            raise aiohttp.ContentTypeError(request_info=None, history=())  # type: ignore[arg-type]
        return self.json_data

    async def text(self) -> str:
        return self.text_data


class FakeSession:
    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self.closed = False
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls.append({"args": args, "kwargs": kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_rest_request_retries_client_errors() -> None:
    session = FakeSession(
        aiohttp.ClientConnectionError("temporary"),
        FakeResponse(
            headers={"Content-Type": "application/json"},
            json_data={"ok": True},
        ),
    )
    client = fluxwave.RestClient(
        "http://localhost:2333",
        password="password",
        user_id=123,
        session=session,  # type: ignore[arg-type]
        retries=1,
        retry_base_delay=0,
    )

    assert await client.request("GET", "/v4/test") == {"ok": True}
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_rest_request_raises_structured_lavalink_errors() -> None:
    session = FakeSession(
        FakeResponse(
            status=401,
            headers={"Content-Type": "application/json"},
            json_data={"status": 401, "error": "Unauthorized", "message": "bad password"},
        )
    )
    client = fluxwave.RestClient(
        "http://localhost:2333",
        password="password",
        user_id=123,
        session=session,  # type: ignore[arg-type]
        retries=0,
    )

    with pytest.raises(fluxwave.LavalinkError) as exc_info:
        await client.request("GET", "/v4/info")

    assert exc_info.value.response.status == 401
    assert exc_info.value.response.message == "bad password"


@pytest.mark.asyncio
async def test_rest_request_parses_text_and_empty_responses() -> None:
    session = FakeSession(
        FakeResponse(headers={"Content-Type": "text/plain"}, text_data="4.0.0"),
        FakeResponse(status=204),
    )
    client = fluxwave.RestClient(
        "http://localhost:2333",
        password="password",
        user_id=123,
        session=session,  # type: ignore[arg-type]
        retries=0,
    )

    assert await client.request("GET", "/version") == "4.0.0"
    assert await client.request("DELETE", "/v4/sessions/session/players/123") is None
