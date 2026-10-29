import asyncio
from types import SimpleNamespace

import fluxwave


def track(*, plugin_info: dict[str, object] | None = None) -> fluxwave.Track:
    payload: dict[str, object] = {
        "encoded": "abc",
        "info": {
            "identifier": "abc",
            "isSeekable": True,
            "author": "artist",
            "length": 120_000,
            "isStream": False,
            "position": 0,
            "title": "song",
            "sourceName": "youtube",
        },
        "userData": {},
    }
    if plugin_info is not None:
        payload["pluginInfo"] = plugin_info
    return fluxwave.Track.from_payload(payload)


class FakeSponsorClient:
    def __init__(self, segments: list[dict[str, object]]) -> None:
        self._segments = segments
        self.calls: list[str] = []

    async def segments(self, identifier: str) -> list[dict[str, object]]:
        self.calls.append(identifier)
        return self._segments


class FakePlayer:
    def __init__(self, position: int = 0) -> None:
        self.position = position
        self.current: fluxwave.Track | None = None
        self.seeks: list[int] = []
        self.notifications: list[tuple[fluxwave.SponsorSegment, int]] = []
        self.node: object | None = None

    async def seek(self, position: int = 0) -> None:
        self.seeks.append(position)

    def _notify_sponsorblock_skip(self, segment: fluxwave.SponsorSegment, position: int) -> None:
        self.notifications.append((segment, position))


def test_segment_helpers() -> None:
    segment = fluxwave.SponsorSegment.from_payload(
        {"category": "sponsor", "start": "1000", "end": 4000, "UUID": "u1"}
    )

    assert segment.duration == 3000
    assert segment.key == "u1"
    assert segment.contains(2000, margin=0)
    assert not segment.contains(500)
    assert not segment.contains(4000)


def test_handle_track_start_reads_inline_segments() -> None:
    player = FakePlayer()
    manager = fluxwave.SponsorBlockManager(player)

    manager.handle_track_start(
        track(plugin_info={"sponsorblock": [{"category": "sponsor", "start": 0, "end": 5000}]})
    )

    assert len(manager.segments) == 1
    assert manager.enabled


async def test_handle_player_update_skips_past_segment_once() -> None:
    player = FakePlayer()
    manager = fluxwave.SponsorBlockManager(player)
    manager.handle_track_start(
        track(plugin_info={"sponsorblock": [{"category": "sponsor", "start": 0, "end": 5000}]})
    )

    manager.handle_player_update(1000)
    await asyncio.sleep(0)

    assert player.seeks == [5000]
    assert player.notifications[0][1] == 1000

    manager.handle_player_update(1200)
    await asyncio.sleep(0)
    assert player.seeks == [5000]


async def test_notify_action_notifies_without_seeking() -> None:
    player = FakePlayer()
    manager = fluxwave.SponsorBlockManager(
        player,
        config=fluxwave.SponsorBlockConfig(
            action=fluxwave.SponsorBlockAction.NOTIFY,
            categories=("sponsor",),
        ),
    )
    manager.handle_track_start(
        track(plugin_info={"sponsorblock": [{"category": "sponsor", "start": 0, "end": 5000}]})
    )

    manager.handle_player_update(1000)

    assert player.seeks == []
    assert len(player.notifications) == 1
    assert player.notifications[0][0].category == "sponsor"

    manager.handle_player_update(1200)
    assert len(player.notifications) == 1


async def test_inline_segments_are_filtered_by_category_and_duration() -> None:
    player = FakePlayer()
    manager = fluxwave.SponsorBlockManager(
        player, config=fluxwave.SponsorBlockConfig(categories=("sponsor",))
    )
    manager.handle_track_start(
        track(
            plugin_info={
                "sponsorblock": [
                    {"category": "sponsor", "start": 0, "end": 5000},
                    {"category": "selfpromo", "start": 6000, "end": 9000},
                    {"category": "sponsor", "start": 10_000, "end": 10_100},
                ]
            }
        )
    )

    assert [segment.category for segment in manager.segments] == ["sponsor"]
    assert len(manager.segments) == 1


async def test_set_config_is_not_destructive() -> None:
    player = FakePlayer()
    manager = fluxwave.SponsorBlockManager(player)
    manager.handle_track_start(
        track(
            plugin_info={
                "sponsorblock": [
                    {"category": "sponsor", "start": 0, "end": 5000},
                    {"category": "outro", "start": 6000, "end": 9000},
                ]
            }
        )
    )

    manager.set_config(fluxwave.SponsorBlockConfig(categories=("sponsor",)))
    assert [segment.category for segment in manager.segments] == ["sponsor"]

    manager.set_config(fluxwave.SponsorBlockConfig(categories=("sponsor", "outro")))
    assert [segment.category for segment in manager.segments] == ["sponsor", "outro"]


async def test_refresh_uses_plugin_and_filters_categories_and_duration() -> None:
    player = FakePlayer()
    client = FakeSponsorClient(
        [
            {"category": "sponsor", "start": 0, "end": 5000, "UUID": "keep"},
            {"category": "sponsor", "start": 0, "end": 100, "UUID": "too-short"},
            {"category": "outro", "start": 0, "end": 5000, "UUID": "wrong-category"},
        ]
    )
    player.node = SimpleNamespace(plugins=SimpleNamespace(sponsorblock=client))
    manager = fluxwave.SponsorBlockManager(
        player, config=fluxwave.SponsorBlockConfig(categories=("sponsor",))
    )

    segments = await manager.refresh(track())

    assert client.calls == ["abc"]
    assert [segment.uuid for segment in segments] == ["keep"]


async def test_refresh_is_not_destructive_when_categories_widen() -> None:
    player = FakePlayer()
    client = FakeSponsorClient(
        [
            {"category": "sponsor", "start": 0, "end": 5000, "UUID": "sponsor"},
            {"category": "outro", "start": 6000, "end": 9000, "UUID": "outro"},
        ]
    )
    player.node = SimpleNamespace(plugins=SimpleNamespace(sponsorblock=client))
    manager = fluxwave.SponsorBlockManager(
        player, config=fluxwave.SponsorBlockConfig(categories=("sponsor",))
    )

    assert [segment.uuid for segment in await manager.refresh(track())] == ["sponsor"]

    manager.set_config(fluxwave.SponsorBlockConfig(categories=("sponsor", "outro")))
    assert [segment.uuid for segment in manager.segments] == ["sponsor", "outro"]


def test_set_config_toggles_enabled_and_refilters_segments() -> None:
    player = FakePlayer()
    manager = fluxwave.SponsorBlockManager(player)
    manager.handle_track_start(
        track(
            plugin_info={
                "sponsorblock": [
                    {"category": "sponsor", "start": 0, "end": 5000},
                    {"category": "outro", "start": 6000, "end": 9000},
                ]
            }
        )
    )

    manager.set_config(fluxwave.SponsorBlockConfig(categories=("sponsor",)))
    assert [segment.category for segment in manager.segments] == ["sponsor"]

    disabled = manager.set_config(
        fluxwave.SponsorBlockConfig(action=fluxwave.SponsorBlockAction.DISABLED)
    )
    assert not manager.enabled
    assert disabled.action is fluxwave.SponsorBlockAction.DISABLED


def test_disabled_manager_does_not_skip() -> None:
    player = FakePlayer()
    manager = fluxwave.SponsorBlockManager(
        player,
        config=fluxwave.SponsorBlockConfig(action=fluxwave.SponsorBlockAction.DISABLED),
    )
    manager.handle_track_start(
        track(plugin_info={"sponsorblock": [{"category": "sponsor", "start": 0, "end": 5000}]})
    )

    manager.handle_player_update(1000)

    assert player.seeks == []
    assert player.notifications == []


async def test_cancel_stops_in_flight_fetch() -> None:
    player = FakePlayer()
    manager = fluxwave.SponsorBlockManager(player)
    manager.handle_track_start(track())
    task = manager._task

    manager.cancel()

    assert task is not None
    await asyncio.sleep(0)
    assert manager._task is None
