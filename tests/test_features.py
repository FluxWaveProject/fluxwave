import asyncio
from pathlib import Path

import fluxwave


def track_payload(identifier: str = "id") -> dict[str, object]:
    return {
        "encoded": identifier,
        "info": {
            "identifier": identifier,
            "isSeekable": True,
            "author": "artist",
            "length": 120_000,
            "isStream": False,
            "position": 0,
            "title": "song",
            "sourceName": "youtube",
            "uri": "https://example.test/x",
        },
    }


def make_track(identifier: str = "id") -> fluxwave.Track:
    return fluxwave.Track.from_payload(track_payload(identifier))


def make_state(guild_id: int = 42) -> fluxwave.PersistedState:
    return fluxwave.PersistedState(
        guild_id=guild_id,
        channel_id=7,
        current_track_payload=track_payload("cur"),
        current_position=1000,
        is_paused=False,
        volume=80,
        queue_mode="normal",
        queue_payloads=[track_payload("a")],
        history_payloads=[],
        auto_queue_payloads=[],
        auto_queue_history_payloads=[],
        autoplay_mode="disabled",
        recommendation_seed_payloads=[],
        previous_seed_ids=[],
        filters_payload={},
    )


class _SlowRest:
    def __init__(self) -> None:
        self.calls = 0
        self.gate = asyncio.Event()

    async def load_tracks(self, identifier: str) -> fluxwave.LoadResult:
        self.calls += 1
        await self.gate.wait()
        return fluxwave.LoadResult.from_payload(
            {"loadType": "search", "data": [track_payload(identifier)]}
        )


async def test_concurrent_identical_loads_are_coalesced() -> None:
    node = fluxwave.Node("http://localhost:2333", password="x", user_id=1, identifier="coalesce")
    rest = _SlowRest()
    node.rest = rest  # type: ignore[assignment]

    tasks = [asyncio.create_task(node.load_tracks("same")) for _ in range(5)]
    for _ in range(10):
        await asyncio.sleep(0)
    rest.gate.set()
    results = await asyncio.gather(*tasks)

    assert rest.calls == 1
    assert all(result is results[0] for result in results)
    assert node._inflight_loads == {}


async def test_failed_load_is_not_cached_and_clears_inflight() -> None:
    node = fluxwave.Node(
        "http://localhost:2333", password="x", user_id=1, identifier="coalesce-err"
    )

    class _FailingRest:
        async def load_tracks(self, identifier: str) -> fluxwave.LoadResult:
            raise RuntimeError("boom")

    node.rest = _FailingRest()  # type: ignore[assignment]

    try:
        await node.load_tracks("bad")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    assert node._inflight_loads == {}


async def test_file_store_round_trip(tmp_path: Path) -> None:
    store = fluxwave.FileStore(tmp_path / "players")

    assert await store.all_guild_ids() == []
    assert await store.load(42) is None

    await store.save(42, make_state(42))
    await store.save(7, make_state(7))

    assert sorted(await store.all_guild_ids()) == [7, 42]
    loaded = await store.load(42)
    assert loaded is not None
    assert loaded.guild_id == 42
    assert loaded.volume == 80
    assert loaded.current_track is not None

    await store.delete(42)
    assert await store.load(42) is None
    assert await store.all_guild_ids() == [7]


async def test_file_store_discards_corrupt_file(tmp_path: Path) -> None:
    directory = tmp_path / "players"
    directory.mkdir(parents=True)
    (directory / "99.json").write_text("not json", encoding="utf-8")

    store = fluxwave.FileStore(directory)
    assert await store.load(99) is None


def test_format_duration() -> None:
    assert fluxwave.format_duration(0) == "0:00"
    assert fluxwave.format_duration(65_000) == "1:05"
    assert fluxwave.format_duration(3_661_000) == "1:01:01"
    assert fluxwave.format_duration(-5) == "0:00"


def test_progress_bar_spans_length_and_shows_time() -> None:
    bar = fluxwave.progress_bar(30_000, 120_000, length=10)
    cells = bar.split(" ")[0]

    assert len(cells) == 10
    assert bar.endswith("0:30 / 2:00")


def test_progress_bar_plain_and_zero_duration() -> None:
    assert fluxwave.progress_bar(0, 0, length=5, marker="", show_time=False) == "─────"


def test_paginate_queue() -> None:
    tracks = [make_track(str(index)) for index in range(25)]
    pages = fluxwave.paginate_queue(tracks, per_page=10)

    assert len(pages) == 3
    assert pages[0].number == 1
    assert pages[0].page_count == 3
    assert pages[0].items[0][0] == 1
    assert pages[2].items[-1][0] == 25
    assert pages[0].lines()[0].startswith("1. song — artist")


def test_paginate_queue_supports_start_offset_and_empty() -> None:
    pages = fluxwave.paginate_queue([make_track("only")], per_page=10, start=2)
    assert pages[0].items[0][0] == 2

    empty = fluxwave.paginate_queue([])
    assert len(empty) == 1
    assert empty[0].items == []
    assert empty[0].total == 0
