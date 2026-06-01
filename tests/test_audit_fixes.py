"""Regression tests for the full-codebase audit bug fixes.

Each test pins a specific bug found during the audit so it cannot silently
regress. Helpers are kept self-contained on purpose.
"""

import asyncio

import pytest

import fluxwave
from fluxwave.player import TRACK_FILTERS_USER_DATA_KEY
from fluxwave.watchdog import VoiceWatchdog, WatchdogConfig


def make_track(
    encoded: str = "abc",
    *,
    is_stream: bool = False,
    length: int = 120_000,
    filters: fluxwave.Filters | None = None,
) -> fluxwave.Track:
    track = fluxwave.Track.from_payload(
        {
            "encoded": encoded,
            "info": {
                "identifier": encoded,
                "isSeekable": True,
                "author": "artist",
                "length": length,
                "isStream": is_stream,
                "position": 0,
                "title": "song",
                "sourceName": "youtube",
            },
        }
    )
    if filters is not None:
        track = track.with_user_data(**{TRACK_FILTERS_USER_DATA_KEY: filters.to_payload()})
    return track


class FakeGuild:
    def __init__(self) -> None:
        self.id = 123

    async def change_voice_state(self, **kwargs: object) -> None:
        return None


class FakeChannel:
    def __init__(self) -> None:
        self.id = 456
        self.guild = FakeGuild()
        self.members: list[object] = []


class FakeClient:
    def __init__(self, channel: FakeChannel) -> None:
        self.user = object()
        self.channel = channel

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self.channel if self.channel.id == channel_id else None

    def dispatch(self, event: str, payload: object) -> None:
        return None


class FakeNode:
    def __init__(self) -> None:
        self.identifier = "node"
        self.status = fluxwave.NodeStatus.CONNECTED
        self.updates: list[fluxwave.PlayerUpdate] = []
        self.listeners: dict[str, list[object]] = {}
        self.inactive_player_timeout = None
        self.inactive_channel_tokens = None
        self.regions = None
        self.shard_ids = None
        self.health_score = 0.0

    def on(self, event: str, callback: object) -> None:
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event: str, callback: object) -> None:
        self.listeners.get(event, []).remove(callback)

    def dispatch(self, event: str, payload: object) -> None:
        for callback in tuple(self.listeners.get(event, [])):
            callback(payload)

    def register_player(self, player: object) -> None:
        return None

    def unregister_player(self, guild_id: int) -> None:
        return None

    async def update_player(
        self,
        guild_id: int,
        update: fluxwave.PlayerUpdate,
        *,
        replace: bool = False,
    ) -> fluxwave.LavalinkPlayer:
        self.updates.append(update)
        return fluxwave.LavalinkPlayer.from_payload(
            {
                "guildId": guild_id,
                "track": None,
                "volume": update.volume or 100,
                "paused": bool(update.paused),
                "state": {"time": 0, "position": 0, "connected": True, "ping": 1},
                "voice": {},
                "filters": {},
            }
        )

    async def destroy_player(self, guild_id: int) -> None:
        return None


class CrashingNode(FakeNode):
    async def update_player(self, *args: object, **kwargs: object) -> fluxwave.LavalinkPlayer:
        msg = "node update failed"
        raise RuntimeError(msg)


def build_player(node: FakeNode) -> fluxwave.FluxPlayer:
    channel = FakeChannel()
    return fluxwave.FluxPlayer(
        FakeClient(channel),  # type: ignore[arg-type]
        channel,  # type: ignore[arg-type]
        node=node,  # type: ignore[arg-type]
    )


def test_player_falls_back_to_global_pool_when_no_node_given() -> None:
    # discord.py's channel.connect(cls=FluxPlayer) builds the player with no
    # node; it must resolve one from the connected global Pool instead of raising.
    node = FakeNode()
    fluxwave.Pool.add(node)  # type: ignore[arg-type]
    try:
        channel = FakeChannel()
        player = fluxwave.FluxPlayer(
            FakeClient(channel),  # type: ignore[arg-type]
            channel,  # type: ignore[arg-type]
        )
        assert player.node is node
    finally:
        fluxwave.Pool.reset()


def test_player_without_node_or_pool_raises_clear_error() -> None:
    fluxwave.Pool.reset()
    channel = FakeChannel()
    with pytest.raises(fluxwave.InvalidNodeError):
        fluxwave.FluxPlayer(FakeClient(channel), channel)  # type: ignore[arg-type]


async def test_play_increments_metrics_and_feeds_tracer() -> None:
    # The metrics counters and the tracer must actually be wired into operations,
    # not just exist as dead scaffolding.
    fluxwave.metrics.reset()
    fluxwave.tracer.clear()
    fluxwave.tracer.enable()
    try:
        player = build_player(FakeNode())
        await player.play(make_track("metric-probe"))
        assert fluxwave.metrics.track_play_count == 1
        assert len(fluxwave.tracer) >= 1
        assert any(e.category == fluxwave.TraceCategory.PLAYER for e in fluxwave.tracer.recent())
    finally:
        fluxwave.tracer.disable()
        fluxwave.tracer.clear()
        fluxwave.metrics.reset()


async def test_play_rolls_back_on_non_lavalink_error() -> None:
    # Previously play() only rolled back local state on LavalinkError, leaving a
    # phantom current track if update_player raised anything else.
    player = build_player(CrashingNode())
    old = make_track("old")
    player._current = old

    with pytest.raises(RuntimeError):
        await player.play(make_track("new"))

    assert player.current is old
    assert player._last_update_ms is None


async def test_play_no_replace_keeps_current_track_filters() -> None:
    # play(replace=False) while a track is playing must not push the rejected
    # track's preloaded filters onto the currently playing track.
    node = FakeNode()
    player = build_player(node)
    playing = make_track("playing")
    player._current = playing

    nightcore = fluxwave.Filters().nightcore()
    candidate = make_track("candidate", filters=nightcore)
    await player.play(candidate, replace=False)

    assert player.current is playing
    assert node.updates[-1].filters in (None, {}, player._filters.to_payload())
    assert player.filters.to_payload() == {}


async def test_empty_channel_timeout_does_not_overwrite_inactive_timeout() -> None:
    # Applying voice_empty_timeout on an empty channel must not permanently
    # shorten the player's general inactive_timeout.
    node = FakeNode()
    player = build_player(node)
    player.auto_disconnect = True
    player.inactive_timeout = 300.0
    player.voice_empty_timeout = 5.0
    player._connected = True

    await player.check_voice_channel_safety()

    assert player.inactive_timeout == 300.0
    player._cancel_inactivity_timer()


def test_lavalink_player_ignores_encodeless_track() -> None:
    # A present-but-encoded-less track object must read as "no track".
    parsed = fluxwave.LavalinkPlayer.from_payload(
        {
            "guildId": 1,
            "track": {"encoded": None, "info": {}},
            "volume": 100,
            "paused": False,
            "state": {"time": 0, "position": 0, "connected": True, "ping": 1},
            "voice": {},
            "filters": {},
        }
    )
    assert parsed.track is None


def test_search_recognizes_spotify_recommendation_prefix() -> None:
    query = fluxwave.build_search_query(
        "sprec:seed_tracks=abc", source=fluxwave.SearchSource.YOUTUBE
    )
    assert query.has_prefix
    assert query.identifier == "sprec:seed_tracks=abc"


async def test_rest_raises_when_external_session_is_closed() -> None:
    class ClosedSession:
        closed = True

    client = fluxwave.RestClient(
        "http://localhost:2333",
        password="password",
        user_id=123,
        session=ClosedSession(),  # type: ignore[arg-type]
    )
    with pytest.raises(fluxwave.NodeError):
        client._ensure_session()


async def test_queue_put_at_wakes_multiple_waiters() -> None:
    # put_at adding several tracks must wake every parked waiter, not just one.
    queue = fluxwave.Queue()
    first = asyncio.create_task(queue.get_wait())
    second = asyncio.create_task(queue.get_wait())
    await asyncio.sleep(0)

    queue.put_at(0, [make_track("a"), make_track("b")])

    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=1.0)
    assert {track.encoded for track in results} == {"a", "b"}


class _FrozenPlayer:
    def __init__(self, current: fluxwave.Track) -> None:
        self.destroyed = False
        self.paused = False
        self.playing = True
        self.current = current
        self.raw_position = 1000
        self.position = 1000
        self.played: list[fluxwave.Track] = []

        class _Guild:
            id = 7

        self.guild = _Guild()

    async def play(self, track: fluxwave.Track, **kwargs: object) -> fluxwave.Track:
        self.played.append(track)
        return track


async def test_watchdog_strikes_when_raw_position_is_frozen() -> None:
    # The watchdog must react to a stalled server position, even though the
    # extrapolated player.position keeps advancing.
    player = _FrozenPlayer(make_track("frozen"))
    watchdog = VoiceWatchdog(
        player,  # type: ignore[arg-type]
        WatchdogConfig(stagnation_threshold=0.0, max_strikes=1),
    )
    watchdog._last_position = 1000
    watchdog._last_change_at = 1.0  # far in the past on the monotonic clock

    await watchdog._tick()

    assert watchdog.stats.recoveries == 1
    assert player.played and player.played[0] is player.current
