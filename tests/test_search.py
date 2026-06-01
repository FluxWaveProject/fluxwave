import pytest

import fluxwave


def track_payload(encoded: str = "abc") -> dict[str, object]:
    return {
        "encoded": encoded,
        "info": {
            "identifier": encoded,
            "isSeekable": True,
            "author": "artist",
            "length": 1000,
            "isStream": False,
            "position": 0,
            "title": encoded,
        },
    }


class SearchRest:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.identifiers: list[str] = []

    async def load_tracks(self, identifier: str) -> fluxwave.LoadResult:
        self.identifiers.append(identifier)
        return fluxwave.LoadResult.from_payload(self.payload)


def make_node(payload: dict[str, object]) -> fluxwave.Node:
    node = fluxwave.Node("http://localhost:2333", password="password", user_id=123)
    node.rest = SearchRest(payload)  # type: ignore[assignment]
    node.search_cache_capacity = 4
    return node


def test_build_search_query_adds_default_prefix() -> None:
    query = fluxwave.build_search_query("never gonna give you up")

    assert query.identifier == "ytsearch:never gonna give you up"
    assert not query.is_url
    assert not query.has_prefix
    assert fluxwave.SearchSource.youtube is fluxwave.SearchSource.YOUTUBE
    assert fluxwave.SearchSource.youtube_music is fluxwave.SearchSource.YOUTUBE_MUSIC
    assert fluxwave.SearchSource.soundcloud is fluxwave.SearchSource.SOUNDCLOUD


def test_build_search_query_preserves_urls_and_existing_prefixes() -> None:
    url = fluxwave.build_search_query("https://example.test/watch?v=1")
    prefixed = fluxwave.build_search_query("spsearch:track id")
    raw = fluxwave.build_search_query("plain", source=None)

    assert url.identifier == "https://example.test/watch?v=1"
    assert url.is_url
    assert prefixed.identifier == "spsearch:track id"
    assert prefixed.has_prefix
    assert raw.identifier == "plain"


async def test_node_search_returns_tracks_and_uses_cache() -> None:
    node = make_node({"loadType": "search", "data": [track_payload()]})

    first = await node.search("abc")
    second = await node.search("abc")

    assert isinstance(first, list)
    assert first[0].title == "abc"
    assert second == first
    assert node.rest.identifiers == ["ytsearch:abc"]  # type: ignore[attr-defined]


async def test_node_search_returns_playlist() -> None:
    node = make_node(
        {
            "loadType": "playlist",
            "data": {
                "info": {"name": "mix", "selectedTrack": -1},
                "tracks": [track_payload()],
            },
        }
    )

    result = await node.search("https://example.test/playlist")

    assert isinstance(result, fluxwave.Playlist)
    assert result.name == "mix"


async def test_node_search_empty_and_error_handling() -> None:
    empty_node = make_node({"loadType": "empty", "data": {}})
    error_node = make_node(
        {
            "loadType": "error",
            "data": {
                "message": "load failed",
                "severity": "fault",
                "cause": "test",
            },
        }
    )

    assert await empty_node.search("nothing") == []

    with pytest.raises(fluxwave.TrackLoadError) as exc_info:
        await error_node.search("bad")

    assert str(exc_info.value) == "load failed"
    assert exc_info.value.severity == "fault"
