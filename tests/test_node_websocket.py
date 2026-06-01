import asyncio

import aiohttp
import pytest

import fluxwave
from fluxwave.websocket import WebSocketClient


def track_payload() -> dict[str, object]:
    return {
        "encoded": "abc",
        "info": {
            "identifier": "id",
            "isSeekable": True,
            "author": "artist",
            "length": 1234,
            "isStream": False,
            "position": 0,
            "title": "song",
            "sourceName": "youtube",
        },
    }


class FakeRest:
    def __init__(self) -> None:
        self.calls = 0
        self.sessions: list[tuple[str, fluxwave.SessionUpdate]] = []
        self.version = "4.0.0"

    async def fetch_version(self) -> str:
        return self.version

    async def load_tracks(self, identifier: str) -> fluxwave.LoadResult:
        self.calls += 1
        return fluxwave.LoadResult.from_payload(
            {"loadType": "search", "data": [track_payload() | {"encoded": identifier}]}
        )

    async def decode_track(self, encoded_track: str) -> fluxwave.Track:
        return fluxwave.Track.from_payload(track_payload() | {"encoded": encoded_track})

    async def decode_tracks(self, encoded_tracks: list[str]) -> list[fluxwave.Track]:
        return [
            fluxwave.Track.from_payload(track_payload() | {"encoded": encoded_track})
            for encoded_track in encoded_tracks
        ]

    async def update_session(
        self,
        session_id: str,
        update: fluxwave.SessionUpdate,
    ) -> None:
        self.sessions.append((session_id, update))

    async def fetch_players(self, session_id: str) -> list[fluxwave.LavalinkPlayer]:
        return []

    async def fetch_player(self, session_id: str, guild_id: int) -> fluxwave.LavalinkPlayer:
        return fluxwave.LavalinkPlayer.from_payload(
            {
                "guildId": guild_id,
                "track": None,
                "volume": 100,
                "paused": False,
                "state": {"time": 0, "position": 0, "connected": True, "ping": 1},
                "voice": {},
                "filters": {},
            }
        )

    async def custom_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> object:
        return {"method": method, "path": path, "params": params, "json": json}


class MissingPlayerRest(FakeRest):
    async def fetch_player(self, session_id: str, guild_id: int) -> fluxwave.LavalinkPlayer:
        response = fluxwave.LavalinkErrorResponse.from_payload(
            {"status": 404, "error": "Not Found", "message": "missing"},
            fallback_status=404,
        )
        raise fluxwave.LavalinkError(response)


class FakeGuild:
    id = 123


class RecoverablePlayer:
    def __init__(self) -> None:
        self.guild = FakeGuild()
        self.destroyed = False
        self.recovered = 0

    async def recover_voice_state(self) -> None:
        self.recovered += 1


class MigratablePlayer:
    def __init__(self) -> None:
        self.guild = FakeGuild()
        self.destroyed = False
        self.nodes: list[fluxwave.Node] = []

    async def switch_node(
        self,
        node: fluxwave.Node,
        *,
        allow_disconnected_source: bool = False,
    ) -> None:
        self.allow_disconnected_source = allow_disconnected_source
        self.nodes.append(node)


class ConnectBackPlayer:
    def __init__(self) -> None:
        self.guild = FakeGuild()
        self.destroyed = False
        self._home_node: fluxwave.Node | None = None
        self._node: fluxwave.Node | None = None
        self.nodes: list[fluxwave.Node] = []

    async def switch_node(
        self,
        node: fluxwave.Node,
        *,
        allow_disconnected_source: bool = False,
    ) -> None:
        if self._node is not None:
            self._node.unregister_player(self.guild.id)
        self._node = node
        node.register_player(self)  # type: ignore[arg-type]
        self.nodes.append(node)


class ClosablePlayer:
    def __init__(self) -> None:
        self.guild = FakeGuild()
        self.destroyed = False
        self.disconnects: list[bool] = []

    async def disconnect(self, *, force: bool = False) -> None:
        self.disconnects.append(force)
        self.destroyed = True


class EventPlayer:
    def __init__(self) -> None:
        self.guild = FakeGuild()
        self.destroyed = False
        self.current = fluxwave.Track.from_payload(track_payload() | {"encoded": "original"})

    async def recover_voice_state(self) -> None:
        return None


class FailingWebSocketSession:
    def ws_connect(self, *args: object, **kwargs: object) -> object:
        raise aiohttp.ClientConnectionError("failed")


class FailingWebSocketRest(FakeRest):
    @property
    def headers(self) -> dict[str, str]:
        return {}

    def _ensure_session(self) -> FailingWebSocketSession:
        return FailingWebSocketSession()


class EventuallyConnectingWebSocket:
    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self) -> "EventuallyConnectingWebSocket":
        return self

    async def __anext__(self) -> object:
        await asyncio.Future()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


class EventuallyConnectingSession:
    def __init__(self) -> None:
        self.calls = 0
        self.connected = asyncio.Event()

    async def ws_connect(self, *args: object, **kwargs: object) -> EventuallyConnectingWebSocket:
        self.calls += 1
        if self.calls == 1:
            raise aiohttp.ClientConnectionError("failed once")
        self.connected.set()
        return EventuallyConnectingWebSocket()


class EventuallyConnectingRest(FakeRest):
    def __init__(self) -> None:
        super().__init__()
        self.session = EventuallyConnectingSession()

    @property
    def headers(self) -> dict[str, str]:
        return {}

    def _ensure_session(self) -> EventuallyConnectingSession:
        return self.session


def make_node(identifier: str, players: int = 0) -> fluxwave.Node:
    node = fluxwave.Node(
        "http://localhost:2333",
        password="password",
        user_id=123,
        identifier=identifier,
    )
    node.status = fluxwave.NodeStatus.CONNECTED
    for guild_id in range(players):
        node.players[guild_id] = fluxwave.LavalinkPlayer.from_payload(
            {
                "guildId": guild_id,
                "track": None,
                "volume": 100,
                "paused": False,
                "state": {"time": 0, "position": 0, "connected": True, "ping": 1},
                "voice": {},
                "filters": {},
            }
        )
    return node


def test_node_pool_selects_least_loaded_connected_node() -> None:
    pool = fluxwave.NodePool()
    busy = make_node("busy", players=2)
    idle = make_node("idle", players=0)
    pool.add(busy)
    pool.add(idle)

    assert pool.get_node() is idle


def test_node_pool_selects_healthiest_node_and_respects_blacklist() -> None:
    pool = fluxwave.NodePool()
    healthy = make_node("healthy", players=1)
    overloaded = make_node("overloaded", players=0)
    overloaded.stats = fluxwave.Stats.from_payload(
        {
            "players": 20,
            "playingPlayers": 20,
            "uptime": 10,
            "memory": {"free": 1, "used": 2, "allocated": 3, "reservable": 4},
            "cpu": {"cores": 4, "systemLoad": 0.9, "lavalinkLoad": 0.95},
            "frameStats": {"sent": 10, "nulled": 5, "deficit": 4},
        }
    )
    pool.add(overloaded)
    pool.add(healthy)

    assert overloaded.health_score > healthy.health_score
    assert pool.get_node() is healthy

    pool.blacklist_node(healthy, cooldown=30)
    assert pool.is_blacklisted(healthy)
    assert pool.get_node() is overloaded
    pool.unblacklist_node(healthy)
    assert pool.get_node() is healthy


def test_parse_voice_region_and_region_group_lookup() -> None:
    pool = fluxwave.NodePool()

    assert fluxwave.parse_voice_region("vip-us-east1234.discord.media") == "us-east"
    assert fluxwave.parse_voice_region("singapore55.discord.media") == "singapore"
    assert pool.get_region("vip-us-east1234.discord.media") == "us"
    assert pool.get_region("singapore55.discord.media") == "asia"


def test_node_pool_selects_by_voice_endpoint_region_before_usage() -> None:
    pool = fluxwave.NodePool()
    us = make_node("us", players=10)
    eu = make_node("eu", players=0)
    us.regions = ("us",)
    eu.regions = ("eu",)
    pool.add(us)
    pool.add(eu)

    assert pool.get_node(endpoint="vip-us-east1234.discord.media") is us
    assert pool.get_node(endpoint="rotterdam123.discord.media") is eu


def test_node_pool_falls_back_when_no_region_matches() -> None:
    pool = fluxwave.NodePool()
    busy = make_node("busy", players=10)
    idle = make_node("idle", players=0)
    busy.regions = ("asia",)
    idle.regions = ("eu",)
    pool.add(busy)
    pool.add(idle)

    assert pool.get_node(endpoint="unknown123.discord.media") is idle


def test_node_pool_selects_by_discord_shard() -> None:
    pool = fluxwave.NodePool()
    shard_zero = make_node("shard-zero", players=0)
    shard_two = make_node("shard-two", players=10)
    shard_zero.shard_ids = (0,)
    shard_two.shard_ids = (2,)
    pool.add(shard_zero)
    pool.add(shard_two)

    guild_id = 2 << 22

    assert fluxwave.calculate_shard_id(guild_id, 4) == 2
    assert pool.get_node(guild_id=guild_id, shard_count=4) is shard_two


def test_node_pool_selection_strategies_can_be_overridden() -> None:
    pool = fluxwave.NodePool()
    regional = make_node("regional", players=20)
    healthy = make_node("healthy", players=0)
    regional.regions = ("us",)
    healthy.regions = ("eu",)
    pool.add(regional)
    pool.add(healthy)

    assert pool.get_node(endpoint="us-east123.discord.media") is regional
    assert (
        pool.get_node(
            endpoint="us-east123.discord.media",
            strategies=[fluxwave.NodeSelectionStrategy.USAGE],
        )
        is healthy
    )


def test_node_pool_raises_invalid_node_for_missing_or_unavailable_node() -> None:
    pool = fluxwave.NodePool()
    disconnected = make_node("down")
    disconnected.status = fluxwave.NodeStatus.DISCONNECTED
    pool.add(disconnected)

    with pytest.raises(fluxwave.InvalidNodeError):
        pool.get_node("missing")

    with pytest.raises(fluxwave.InvalidNodeError):
        pool.get_node()


async def test_node_load_tracks_uses_optional_cache() -> None:
    node = make_node("cache")
    node.search_cache_capacity = 2
    fake_rest = FakeRest()
    node.rest = fake_rest  # type: ignore[assignment]

    first = await node.load_tracks("ytsearch:test")
    second = await node.load_tracks("ytsearch:test")

    assert first is second
    assert fake_rest.calls == 1


async def test_node_load_tracks_cache_evicts_least_frequently_used() -> None:
    node = make_node("cache-lfu")
    node.search_cache_capacity = 2
    fake_rest = FakeRest()
    node.rest = fake_rest  # type: ignore[assignment]

    first = await node.load_tracks("ytsearch:a")
    await node.load_tracks("ytsearch:b")
    assert await node.load_tracks("ytsearch:a") is first
    await node.load_tracks("ytsearch:c")
    assert await node.load_tracks("ytsearch:a") is first
    await node.load_tracks("ytsearch:b")

    assert fake_rest.calls == 4


async def test_node_decode_track_helpers() -> None:
    node = make_node("decode")
    node.rest = FakeRest()  # type: ignore[assignment]

    decoded = await node.decode_track("abc")
    decoded_many = await node.decode_tracks(["abc"])

    assert decoded.encoded == "abc"
    assert decoded_many[0].encoded == "abc"


async def test_node_fetch_version_and_single_player_helpers() -> None:
    node = make_node("helpers")
    node.session_id = "session"
    node.rest = FakeRest()  # type: ignore[assignment]

    version = await node.fetch_version()
    player = await node.fetch_player(123)

    assert version == "4.0.0"
    assert player.guild_id == 123
    assert node.get_player(123) is player


async def test_node_fetch_player_info_returns_none_for_404_and_send_alias() -> None:
    node = make_node("compat")
    node.session_id = "session"
    node.rest = MissingPlayerRest()  # type: ignore[assignment]

    assert await node.fetch_player_info(123) is None

    node.rest = FakeRest()  # type: ignore[assignment]
    response = await node.send("POST", path="/v4/plugin/example", data={"value": 1})

    assert response == {
        "method": "POST",
        "path": "/v4/plugin/example",
        "params": None,
        "json": {"value": 1},
    }


def test_lavalink_version_parser_handles_release_and_snapshot() -> None:
    stable = fluxwave.parse_lavalink_version("4.2.2")
    snapshot = fluxwave.parse_lavalink_version("4.2.3-SNAPSHOT")

    assert stable.base == (4, 2, 2)
    assert snapshot.base == (4, 2, 3)
    assert snapshot.is_snapshot


async def test_node_validate_lavalink_version_accepts_supported_v4() -> None:
    node = make_node("version-ok")
    rest = FakeRest()
    rest.version = "4.2.2"
    node.rest = rest  # type: ignore[assignment]

    check = await node.validate_lavalink_version()

    assert check.supported
    assert check.warning is None
    assert node.lavalink_version is not None
    assert node.lavalink_version.base == (4, 2, 2)


async def test_node_validate_lavalink_version_rejects_wrong_major() -> None:
    node = make_node("version-v3")
    rest = FakeRest()
    rest.version = "3.7.0"
    node.rest = rest  # type: ignore[assignment]

    with pytest.raises(fluxwave.UnsupportedLavalinkVersion):
        await node.validate_lavalink_version()


async def test_node_validate_lavalink_version_warns_for_newer_v4() -> None:
    node = make_node("version-newer")
    rest = FakeRest()
    rest.version = "4.99.0"
    node.rest = rest  # type: ignore[assignment]

    with pytest.warns(fluxwave.LavalinkVersionWarning):
        check = await node.validate_lavalink_version()

    assert check.supported
    assert check.warning is not None


async def test_node_validate_lavalink_version_strict_rejects_newer_v4() -> None:
    node = make_node("version-strict")
    node.strict_version_check = True
    rest = FakeRest()
    rest.version = "4.99.0"
    node.rest = rest  # type: ignore[assignment]

    with pytest.raises(fluxwave.UnsupportedLavalinkVersion):
        await node.validate_lavalink_version()


async def test_node_validate_lavalink_version_rejects_unparseable_version() -> None:
    node = make_node("version-bad")
    rest = FakeRest()
    rest.version = "definitely not semver"
    node.rest = rest  # type: ignore[assignment]

    with pytest.raises(fluxwave.UnsupportedLavalinkVersion):
        await node.validate_lavalink_version()


async def test_node_pool_cache_reuses_load_results() -> None:
    pool = fluxwave.NodePool()
    node = make_node("pool-cache")
    fake_rest = FakeRest()
    node.rest = fake_rest  # type: ignore[assignment]
    pool.add(node)
    pool.cache(2)

    first = await pool.load_tracks("ytsearch:test")
    second = await pool.load_tracks("ytsearch:test")

    assert first is second
    assert pool.has_cache
    assert fake_rest.calls == 1


async def test_node_pool_cache_evicts_least_frequently_used() -> None:
    pool = fluxwave.NodePool()
    node = make_node("pool-cache-lfu")
    fake_rest = FakeRest()
    node.rest = fake_rest  # type: ignore[assignment]
    pool.add(node)
    pool.cache(2)

    first = await pool.load_tracks("ytsearch:a")
    await pool.load_tracks("ytsearch:b")
    assert await pool.load_tracks("ytsearch:a") is first
    await pool.load_tracks("ytsearch:c")
    assert await pool.load_tracks("ytsearch:a") is first
    await pool.load_tracks("ytsearch:b")

    assert fake_rest.calls == 4


async def test_node_pool_search_uses_pool_cache() -> None:
    pool = fluxwave.NodePool()
    node = make_node("pool-search-cache")
    fake_rest = FakeRest()
    node.rest = fake_rest  # type: ignore[assignment]
    pool.add(node)
    pool.cache(2)

    first = await pool.search("test")
    second = await pool.search("test")

    assert first == second
    assert fake_rest.calls == 1


async def test_node_pool_search_can_bypass_cache() -> None:
    pool = fluxwave.NodePool()
    node = make_node("pool-search-no-cache")
    fake_rest = FakeRest()
    node.rest = fake_rest  # type: ignore[assignment]
    pool.add(node)
    pool.cache(2)

    await pool.search("test", use_cache=False)
    await pool.search("test", use_cache=False)

    assert fake_rest.calls == 2


async def test_node_pool_migrates_live_players_to_connected_node() -> None:
    pool = fluxwave.NodePool()
    source = make_node("source")
    target = make_node("target")
    player = MigratablePlayer()
    source.register_player(player)  # type: ignore[arg-type]
    pool.add(source)
    pool.add(target)

    migrated = await pool.handle_node_failure(source)

    assert migrated == 1
    assert source.status is fluxwave.NodeStatus.DISCONNECTED
    assert player.nodes == [target]
    assert player.allow_disconnected_source


async def test_node_pool_migration_allows_disconnected_source() -> None:
    pool = fluxwave.NodePool()
    source = make_node("source-disconnected")
    target = make_node("target-disconnected")
    player = MigratablePlayer()
    source.register_player(player)  # type: ignore[arg-type]
    pool.add(source)
    pool.add(target)
    source.status = fluxwave.NodeStatus.DISCONNECTED

    migrated = await pool.migrate_players(source)

    assert migrated == 1
    assert player.nodes == [target]
    assert player.allow_disconnected_source


async def test_node_pool_schedules_migration_on_node_disconnect_event() -> None:
    pool = fluxwave.NodePool()
    source = make_node("source-event")
    target = make_node("target-event")
    player = MigratablePlayer()
    source.register_player(player)  # type: ignore[arg-type]
    pool.add(source)
    pool.add(target)

    source.dispatch("node_disconnected", fluxwave.NodeDisconnectedEvent("source-event"))
    for _ in range(3):
        await asyncio.sleep(0)

    assert player.nodes == [target]


async def test_node_pool_returns_players_to_recovered_home_node() -> None:
    pool = fluxwave.NodePool()
    source = make_node("home")
    target = make_node("backup")
    player = ConnectBackPlayer()
    player._node = source
    source.register_player(player)  # type: ignore[arg-type]
    pool.add(source)
    pool.add(target)

    migrated = await pool.handle_node_failure(source)

    assert migrated == 1
    assert player._node is target
    assert player._home_node is source
    assert target._live_players.get(player.guild.id) is player
    assert player.guild.id not in source._live_players

    source.status = fluxwave.NodeStatus.CONNECTED
    returned = await pool.return_players(source)

    assert returned == 1
    assert player._node is source
    assert player._home_node is None
    assert player.nodes == [target, source]
    assert source._live_players.get(player.guild.id) is player
    assert player.guild.id not in target._live_players


async def test_node_pool_schedules_return_on_node_ready_event() -> None:
    pool = fluxwave.NodePool()
    source = make_node("home-event")
    target = make_node("backup-event")
    player = ConnectBackPlayer()
    player._node = source
    source.register_player(player)  # type: ignore[arg-type]
    pool.add(source)
    pool.add(target)

    await pool.handle_node_failure(source)
    source.status = fluxwave.NodeStatus.CONNECTED

    source.dispatch("node_ready", fluxwave.NodeReadyEvent("home-event", "session", False))
    for _ in range(3):
        await asyncio.sleep(0)

    assert player._node is source
    assert player._home_node is None


async def test_node_pool_skips_return_when_auto_return_disabled() -> None:
    pool = fluxwave.NodePool()
    pool.auto_return_players = False
    source = make_node("home-off")
    target = make_node("backup-off")
    player = ConnectBackPlayer()
    player._node = source
    source.register_player(player)  # type: ignore[arg-type]
    pool.add(source)
    pool.add(target)

    await pool.handle_node_failure(source)

    assert player._node is target
    assert player._home_node is None

    source.status = fluxwave.NodeStatus.CONNECTED
    returned = await pool.return_players(source)

    assert returned == 0
    assert player._node is target


async def test_node_close_disconnects_live_players() -> None:
    node = make_node("close-live")
    player = ClosablePlayer()
    node.register_player(player)  # type: ignore[arg-type]

    await node.close()

    assert player.disconnects == [True]
    assert node.status is fluxwave.NodeStatus.CLOSED
    assert node._live_players == {}


async def test_node_close_dispatches_public_node_closed_event() -> None:
    node = make_node("close-event")
    player = ClosablePlayer()
    node.register_player(player)  # type: ignore[arg-type]
    received: list[object] = []

    fluxwave.listen("wavelink_node_closed")(received.append)
    try:
        await node.close()
        await asyncio.sleep(0)
    finally:
        fluxwave.remove_listener("wavelink_node_closed", received.append)

    assert len(received) == 1
    event = received[0]
    assert isinstance(event, fluxwave.NodeClosedEvent)
    assert event.identifier == "close-event"
    assert event.disconnected_guild_ids == (123,)
    assert event.disconnected_players == (player,)


async def test_websocket_ready_and_stats_events_update_node_state() -> None:
    node = make_node("ws")
    node.resume_timeout = 0
    node.status = fluxwave.NodeStatus.CONNECTING
    websocket = WebSocketClient(node=node)
    received: list[object] = []
    node.on("node_ready", received.append)
    node.on("stats_update", received.append)

    await websocket.handle_payload({"op": "ready", "sessionId": "session", "resumed": False})
    await websocket.handle_payload(
        {
            "op": "stats",
            "players": 1,
            "playingPlayers": 0,
            "uptime": 10,
            "memory": {"free": 1, "used": 2, "allocated": 3, "reservable": 4},
            "cpu": {"cores": 4, "systemLoad": 0.1, "lavalinkLoad": 0.2},
        }
    )

    assert node.status is fluxwave.NodeStatus.CONNECTED
    assert node.session_id == "session"
    assert isinstance(received[0], fluxwave.NodeReadyEvent)
    assert isinstance(received[1], fluxwave.StatsUpdateEvent)
    assert node.stats is not None
    assert node.stats.players == 1


async def test_websocket_ready_configures_resume_when_enabled() -> None:
    node = make_node("resume")
    node.resume_timeout = 42
    fake_rest = FakeRest()
    node.rest = fake_rest  # type: ignore[assignment]
    websocket = WebSocketClient(node=node)

    await websocket.handle_payload({"op": "ready", "sessionId": "session", "resumed": True})

    assert fake_rest.sessions == [("session", fluxwave.SessionUpdate(resuming=True, timeout=42))]


async def test_websocket_ready_recovers_live_players_when_not_resumed() -> None:
    node = make_node("recover")
    node.rest = FakeRest()  # type: ignore[assignment]
    player = RecoverablePlayer()
    node.register_player(player)  # type: ignore[arg-type]
    websocket = WebSocketClient(node=node)

    await websocket.handle_payload({"op": "ready", "sessionId": "session", "resumed": False})

    assert player.recovered == 1


async def test_websocket_ready_does_not_recover_when_resumed() -> None:
    node = make_node("recover-resumed")
    node.rest = FakeRest()  # type: ignore[assignment]
    player = RecoverablePlayer()
    node.register_player(player)  # type: ignore[arg-type]
    websocket = WebSocketClient(node=node)

    await websocket.handle_payload({"op": "ready", "sessionId": "session", "resumed": True})

    assert player.recovered == 0


async def test_websocket_stats_records_health_sample() -> None:
    node = make_node("health")
    websocket = WebSocketClient(node=node)

    await websocket.handle_payload(
        {
            "op": "stats",
            "players": 1,
            "playingPlayers": 1,
            "uptime": 100,
            "memory": {"free": 1, "used": 2, "allocated": 3, "reservable": 4},
            "cpu": {"cores": 2, "systemLoad": 0.1, "lavalinkLoad": 0.2},
            "frameStats": {"sent": 1, "nulled": 0, "deficit": 0},
        }
    )

    assert len(node._health_samples) == 1


async def test_websocket_disconnect_dispatches_after_reconnect_exhaustion() -> None:
    node = make_node("disconnect-race")
    node.retries = 0
    node.retry_base_delay = 0
    node.connect_timeout = 0.001
    node.rest = FailingWebSocketRest()  # type: ignore[assignment]
    websocket = WebSocketClient(node=node)
    received: list[object] = []
    node.on("node_disconnected", received.append)

    await websocket._handle_disconnect()

    assert node.status is fluxwave.NodeStatus.DISCONNECTED
    assert len(received) == 1


async def test_websocket_disconnect_does_not_dispatch_when_reconnect_succeeds() -> None:
    node = make_node("disconnect-recovers")
    node.retries = 1
    node.retry_base_delay = 0
    node.connect_timeout = 0.05
    rest = EventuallyConnectingRest()
    node.rest = rest  # type: ignore[assignment]
    websocket = WebSocketClient(node=node)
    received: list[object] = []
    node.on("node_disconnected", received.append)

    async def ready_soon() -> None:
        await rest.session.connected.wait()
        await websocket.handle_payload({"op": "ready", "sessionId": "session", "resumed": True})

    ready_task = asyncio.create_task(ready_soon())
    try:
        await websocket._handle_disconnect()
    finally:
        await ready_task
        await websocket.close(dispatch=False)

    assert rest.session.calls == 2
    assert node.status is fluxwave.NodeStatus.CONNECTED
    assert received == []


async def test_node_connect_is_noop_when_already_connected() -> None:
    node = make_node("connected")
    await node.connect()

    assert node.websocket is None


async def test_websocket_track_start_event_is_typed() -> None:
    node = make_node("events")
    player = EventPlayer()
    node.register_player(player)  # type: ignore[arg-type]
    websocket = WebSocketClient(node=node)
    received: list[object] = []
    node.on("track_start", received.append)

    await websocket.handle_payload(
        {
            "op": "event",
            "type": "TrackStartEvent",
            "guildId": "123",
            "track": track_payload(),
        }
    )

    event = received[0]
    assert isinstance(event, fluxwave.TrackStartEvent)
    assert event.guild_id == 123
    assert event.track.title == "song"
    assert event.node_identifier == "events"
    assert event.player is player
    assert event.original is player.current


async def test_websocket_unknown_event_dispatches_extra_and_plugin_events() -> None:
    node = make_node("plugin")
    websocket = WebSocketClient(node=node)
    received: list[object] = []
    node.on(fluxwave.EventType.EXTRA_EVENT, received.append)
    node.on(fluxwave.EventType.PLUGIN_EVENT, received.append)

    await websocket.handle_payload(
        {
            "op": "event",
            "type": "PluginThingEvent",
            "guildId": "123",
            "custom": True,
        }
    )

    assert len(received) == 2
    assert isinstance(received[0], fluxwave.ExtraEvent)
    assert received[0].event_type == "PluginThingEvent"
    assert received[0].node_identifier == "plugin"


async def test_websocket_raw_event_fires_for_every_payload() -> None:
    node = make_node("raw")
    node.resume_timeout = 0
    node.status = fluxwave.NodeStatus.CONNECTING
    websocket = WebSocketClient(node=node)
    received: list[fluxwave.RawWebSocketEvent] = []
    node.on(fluxwave.EventType.WEBSOCKET_RAW, received.append)

    await websocket.handle_payload({"op": "ready", "sessionId": "session", "resumed": False})
    await websocket.handle_payload(
        {
            "op": "event",
            "type": "PluginThingEvent",
            "guildId": "123",
            "custom": True,
        }
    )
    await websocket.handle_payload({"weird": "shape"})

    assert len(received) == 3
    assert all(isinstance(event, fluxwave.RawWebSocketEvent) for event in received)
    assert [event.op for event in received] == ["ready", "event", None]
    assert received[0].payload == {"op": "ready", "sessionId": "session", "resumed": False}
    assert all(event.node_identifier == "raw" for event in received)


async def test_websocket_raw_event_payload_is_isolated_copy() -> None:
    node = make_node("raw-copy")
    websocket = WebSocketClient(node=node)
    received: list[fluxwave.RawWebSocketEvent] = []
    node.on(fluxwave.EventType.WEBSOCKET_RAW, received.append)

    payload = {"op": "pong", "extra": {"nested": 1}}
    await websocket.handle_payload(payload)
    payload["mutated"] = True

    assert received[0].payload == {"op": "pong", "extra": {"nested": 1}}


async def test_websocket_connect_raises_connection_error_after_retries() -> None:
    node = make_node("fail")
    node.status = fluxwave.NodeStatus.CONNECTING
    node.retries = 1
    node.retry_base_delay = 0
    node.rest = FailingWebSocketRest()  # type: ignore[assignment]
    websocket = WebSocketClient(node=node)

    with pytest.raises(fluxwave.NodeConnectionError):
        await websocket.connect()

    assert node.status is fluxwave.NodeStatus.DISCONNECTED
