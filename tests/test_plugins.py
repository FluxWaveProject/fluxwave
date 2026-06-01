import pytest

import fluxwave


class FakePluginNode:
    def __init__(self) -> None:
        self.session_id: str | None = "session"
        self.requests: list[tuple[str, str, dict[str, str] | None, dict[str, object] | None]] = []
        self.searches: list[tuple[str, str | None, bool]] = []

    async def custom_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.requests.append((method, path, params, json))
        return {"ok": True}

    async def search(
        self,
        query: str,
        *,
        source: str | None = None,
        use_cache: bool = True,
    ) -> list[fluxwave.Track]:
        self.searches.append((query, source, use_cache))
        return []


async def test_plugin_helpers_route_common_calls() -> None:
    node = FakePluginNode()
    helpers = fluxwave.PluginHelpers(node)

    await helpers.lavasrc.spotify("song", use_cache=False)
    await helpers.lyrics.current(123)
    await helpers.lyrics.track("encoded-track", skip_track_source=True)
    await helpers.sponsorblock.categories(123)
    await helpers.sponsorblock.set_categories(123, ["sponsor", "intro"])
    await helpers.sponsorblock.clear_categories(123)
    await helpers.rest.custom("POST", "/v4/plugin/test", json={"value": 1})

    assert node.searches == [("song", "spsearch", False)]
    assert node.requests == [
        (
            "GET",
            "/v4/sessions/session/players/123/track/lyrics",
            {"skipTrackSource": "false"},
            None,
        ),
        (
            "GET",
            "/v4/lyrics",
            {"track": "encoded-track", "skipTrackSource": "true"},
            None,
        ),
        ("GET", "/v4/sessions/session/players/123/sponsorblock/categories", None, None),
        (
            "PUT",
            "/v4/sessions/session/players/123/sponsorblock/categories",
            None,
            ["sponsor", "intro"],
        ),
        ("DELETE", "/v4/sessions/session/players/123/sponsorblock/categories", None, None),
        ("POST", "/v4/plugin/test", None, {"value": 1}),
    ]


async def test_lyrics_current_requires_session() -> None:
    node = FakePluginNode()
    node.session_id = None

    with pytest.raises(fluxwave.NodeError):
        await fluxwave.LyricsClient(node).current(123)


async def test_sponsorblock_categories_require_session() -> None:
    node = FakePluginNode()
    node.session_id = None

    with pytest.raises(fluxwave.NodeError):
        await fluxwave.SponsorBlockClient(node).categories(123)
