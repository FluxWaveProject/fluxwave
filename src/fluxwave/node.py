"""Lavalink node and node-pool system."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
import time
import warnings
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

import aiohttp

from .cache import LFUCache
from .events import (
    EventCallback,
    EventDispatcher,
    EventName,
    EventType,
    NodeClosedEvent,
    NodeDisconnectedEvent,
    NodeReadyEvent,
)
from .events import (
    dispatch as dispatch_global_event,
)
from .exceptions import InvalidNodeError, LavalinkError, NodeError, UnsupportedLavalinkVersion
from .metrics import metrics
from .plugins import PluginHelpers
from .rest import HttpMethod, PlayerUpdate, RestClient, RestResponse, SessionUpdate
from .routeplanner import RoutePlannerStatus
from .search import Search, SearchSource, build_search_query, unwrap_load_result
from .tracing import TraceCategory, tracer
from .tracks import LavalinkPlayer, LoadResult, NodeInfo, Stats, Track
from .types import JsonPayload
from .versioning import (
    LavalinkVersion,
    LavalinkVersionCheck,
    LavalinkVersionWarning,
    check_lavalink_version,
    parse_lavalink_version,
)

if TYPE_CHECKING:
    from .player import FluxPlayer
    from .websocket import WebSocketClient


logger = logging.getLogger(__name__)


DEFAULT_REGION_GROUPS: dict[str, tuple[str, ...]] = {
    "asia": ("hongkong", "singapore", "sydney", "japan", "southafrica", "india"),
    "eu": ("rotterdam", "russia", "finland", "stockholm", "bucharest", "frankfurt", "europe"),
    "us": ("us-central", "us-east", "us-south", "us-west", "brazil", "atlanta"),
}
"""Default Discord voice endpoint groups used for region-aware node selection."""

_REGION_ENDPOINT_RE = re.compile(r"^(?:vip-)?(?P<region>[a-z-]+)\d*\.discord\.media", re.I)


class NodeStatus(StrEnum):
    """Connection state for a Lavalink node."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


class NodeSelectionStrategy(StrEnum):
    """Node selection filters used by :class:`NodePool.select_node`."""

    LOCATION = "location"
    SHARD = "shard"
    USAGE = "usage"
    RANDOM = "random"


@dataclass(slots=True)
class Node:
    """Configuration and lifecycle owner for one Lavalink node."""

    uri: str
    password: str
    user_id: int | str
    identifier: str | None = None
    client_name: str = "FluxWave/0.1"
    session: aiohttp.ClientSession | None = None
    heartbeat: float = 15.0
    request_timeout: float = 15.0
    connect_timeout: float = 15.0
    retries: int | None = 3
    retry_base_delay: float = 0.5
    retry_max_delay: float = 30.0
    retry_jitter: bool = True
    resume_timeout: int = 60
    search_cache_capacity: int | None = None
    region: str | None = None
    regions: Iterable[str] | None = None
    shard_ids: Iterable[int] | None = None
    validate_version: bool = True
    strict_version_check: bool = False
    auto_recover_players: bool = True
    inactive_player_timeout: float | None = 300.0
    inactive_channel_tokens: int | None = 3
    status: NodeStatus = field(default=NodeStatus.DISCONNECTED, init=False)
    session_id: str | None = field(default=None, init=False)
    players: dict[int, LavalinkPlayer] = field(default_factory=dict, init=False)
    info: NodeInfo | None = field(default=None, init=False)
    lavalink_version: LavalinkVersion | None = field(default=None, init=False)
    version_check: LavalinkVersionCheck | None = field(default=None, init=False)
    stats: Stats | None = field(default=None, init=False)
    rest: RestClient = field(init=False)
    websocket: WebSocketClient | None = field(default=None, init=False)
    events: EventDispatcher = field(default_factory=EventDispatcher, init=False)
    _closed: bool = field(default=False, init=False)
    _search_cache: LFUCache[str, LoadResult] | None = field(default=None, init=False)
    _inflight_loads: dict[str, asyncio.Future[LoadResult]] = field(default_factory=dict, init=False)
    _live_players: dict[int, FluxPlayer] = field(default_factory=dict, init=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _player_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _health_samples: deque[float] = field(default_factory=lambda: deque(maxlen=10), init=False)

    def __post_init__(self) -> None:
        self.identifier = self.identifier or secrets.token_urlsafe(8)
        self.uri = self.uri.rstrip("/")
        self.regions = _normalize_regions(self.region, self.regions)
        self.shard_ids = _normalize_shard_ids(self.shard_ids)
        self.rest = RestClient(
            self.uri,
            password=self.password,
            user_id=self.user_id,
            client_name=self.client_name,
            session=self.session,
            request_timeout=self.request_timeout,
            retries=0 if self.retries is None else self.retries,
            retry_base_delay=self.retry_base_delay,
        )

    @property
    def headers(self) -> dict[str, str]:
        """Headers used for Lavalink REST and websocket requests."""

        return self.rest.headers

    @property
    def player_count(self) -> int:
        """Number of known players on this node."""

        return len(self.players)

    @property
    def latency(self) -> float:
        """Approximate node latency/pressure score from available stats."""

        if self.stats is None:
            return 0.0

        frame_penalty = 0.0
        if self.stats.frame_stats is not None:
            frame_penalty = float(self.stats.frame_stats.deficit + self.stats.frame_stats.nulled)

        return (self.stats.cpu.lavalink_load * 100.0) + frame_penalty

    @property
    def health_score(self) -> float:
        """Lower score means the node is a better candidate for new players."""

        if self.status is not NodeStatus.CONNECTED:
            return float("inf")

        load = self.stats.cpu.lavalink_load if self.stats is not None else 0.0
        playing = self.stats.playing_players if self.stats is not None else self.player_count
        return self.latency + (load * 100.0) + (playing * 10.0) + self.player_count

    @property
    def is_degraded(self) -> bool:
        """``True`` when recent health scores show a worsening trend.

        Requires at least 4 samples (collected each time stats arrive).
        A node is considered degraded when the average of the most recent half
        of samples is worse (higher) than the average of the older half.
        """

        samples = list(self._health_samples)
        n = len(samples)
        if n < 4:
            return False
        mid = n // 2
        old_avg = sum(samples[:mid]) / mid
        new_avg = sum(samples[mid:]) / (n - mid)
        return new_avg > old_avg * 1.25

    def record_health_sample(self) -> None:
        """Record the current health score; called automatically on stats updates."""

        self._health_samples.append(self.health_score)

    @property
    def plugins(self) -> PluginHelpers:
        """Convenience helpers for common Lavalink plugins."""

        return PluginHelpers(self)

    def on(self, event: EventName, callback: EventCallback) -> None:
        """Register an internal node event listener."""

        self.events.on(event, callback)

    def remove_listener(self, event: EventName, callback: EventCallback) -> None:
        """Remove an internal node event listener."""

        self.events.remove(event, callback)

    def dispatch(self, event: EventName, payload: object) -> None:
        """Dispatch an internal node event."""

        self.events.dispatch(event, payload)

    async def connect(self) -> None:
        """Connect the node websocket and wait for Lavalink's ready payload."""

        async with self._lifecycle_lock:
            if self.status is NodeStatus.CONNECTED:
                return

            self._closed = False
            self.status = NodeStatus.CONNECTING
            from .websocket import WebSocketClient

            try:
                if self.validate_version:
                    await self.validate_lavalink_version()

                self.websocket = WebSocketClient(node=self)
                logger.debug("Connecting FluxWave node %s.", self.identifier)
                await self.websocket.connect()
            except Exception:
                self.status = NodeStatus.DISCONNECTED
                await self.rest.close()
                raise

    async def reconnect(self) -> None:
        """Close the active websocket and establish a new connection."""

        async with self._lifecycle_lock:
            self.status = NodeStatus.RECONNECTING
            if self.websocket:
                await self.websocket.close(dispatch=False)

            self.status = NodeStatus.CONNECTING
            from .websocket import WebSocketClient

            logger.debug("Reconnecting FluxWave node %s.", self.identifier)
            try:
                if self.validate_version:
                    await self.validate_lavalink_version()

                self.websocket = WebSocketClient(node=self)
                await self.websocket.connect()
            except Exception:
                self.status = NodeStatus.DISCONNECTED
                logger.exception("Failed to reconnect FluxWave node %s.", self.identifier)
                raise

    async def close(self) -> None:
        """Close websocket and REST resources."""

        async with self._lifecycle_lock:
            if self.status is NodeStatus.CLOSED and self._closed:
                return

            self._closed = True
            disconnected: list[int] = []
            disconnected_players: list[FluxPlayer] = []
            for player in tuple(self._live_players.values()):
                if player.destroyed:
                    self.unregister_player(player.guild.id)
                    continue

                try:
                    await player.disconnect(force=True)
                    disconnected.append(player.guild.id)
                    disconnected_players.append(player)
                except Exception:
                    logger.exception(
                        "Failed to disconnect FluxWave player %s while closing node %s.",
                        player.guild.id,
                        self.identifier,
                    )

            if self.websocket:
                await self.websocket.close(dispatch=True)
                self.websocket = None

            self.status = NodeStatus.CLOSED
            self.session_id = None
            self.players.clear()
            self._live_players.clear()
            event = NodeClosedEvent(
                identifier=self.identifier or "",
                disconnected_guild_ids=tuple(disconnected),
                disconnected_players=tuple(disconnected_players),
            )
            self.dispatch(EventType.NODE_CLOSED, event)
            dispatch_global_event(EventType.NODE_CLOSED, event)
            dispatch_global_event("fluxwave_node_closed", event)
            dispatch_global_event("wavelink_node_closed", event)
            await self.rest.close()
            await self.events.close()
            logger.debug(
                "Closed FluxWave node %s after disconnecting players %s.",
                self.identifier,
                disconnected,
            )

    async def configure_resume(self) -> None:
        """Configure Lavalink session resume if enabled."""

        if self.session_id is None or self.resume_timeout <= 0:
            return

        await self.rest.update_session(
            self.session_id,
            SessionUpdate(resuming=True, timeout=self.resume_timeout),
        )

    async def fetch_info(self) -> NodeInfo:
        """Fetch and store Lavalink node info."""

        self.info = await self.rest.fetch_info()
        return self.info

    async def fetch_stats(self) -> Stats:
        """Fetch and store Lavalink node stats."""

        self.stats = await self.rest.fetch_stats()
        return self.stats

    async def fetch_version(self) -> str:
        """Fetch Lavalink version text for this node."""

        return await self.rest.fetch_version()

    async def validate_lavalink_version(self) -> LavalinkVersionCheck:
        """Fetch and validate the Lavalink server version.

        FluxWave is a Lavalink v4 client. Unsupported major versions raise
        :class:`UnsupportedLavalinkVersion`. Newer-than-tested v4 builds emit a
        warning by default, or raise when `strict_version_check=True`.
        """

        try:
            raw_version = await self.fetch_version()
            parsed = parse_lavalink_version(raw_version)
        except Exception as exc:
            msg = (
                f"Could not validate Lavalink version for node {self.identifier!r}. "
                "Disable Node(validate_version=False) only if you know this server is Lavalink v4."
            )
            raise UnsupportedLavalinkVersion(msg) from exc

        check = check_lavalink_version(parsed)
        self.lavalink_version = parsed
        self.version_check = check

        if not check.supported:
            raise UnsupportedLavalinkVersion(check.warning or f"Unsupported Lavalink {parsed}.")

        if check.warning is not None:
            message = f"Node {self.identifier!r}: {check.warning}"
            if self.strict_version_check:
                raise UnsupportedLavalinkVersion(message)
            warnings.warn(message, LavalinkVersionWarning, stacklevel=2)

        return check

    async def fetch_routeplanner_status(self) -> RoutePlannerStatus | None:
        """Fetch Lavalink route planner status for this node."""

        return await self.rest.fetch_routeplanner_status()

    async def free_routeplanner_address(self, address: str) -> None:
        """Free one failing route planner address on this node."""

        await self.rest.free_routeplanner_address(address)

    async def free_all_routeplanner_addresses(self) -> None:
        """Free all failing route planner addresses on this node."""

        await self.rest.free_all_routeplanner_addresses()

    async def load_tracks(self, identifier: str, *, use_cache: bool = True) -> LoadResult:
        """Load tracks through this node with caching and request coalescing.

        Concurrent calls for the same identifier share a single Lavalink request,
        so a burst of identical searches only hits the node once.
        """

        node_id = self.identifier or ""
        cache = self._search_lfu_cache() if use_cache else None
        if cache is not None:
            cached = cache.get(identifier)
            if cached is not None:
                metrics.total_search_cache_hits += 1
                metrics.node(node_id).search_cache_hits += 1
                return cached

        pending = self._inflight_loads.get(identifier)
        if pending is not None:
            return await asyncio.shield(pending)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[LoadResult] = loop.create_future()
        self._inflight_loads[identifier] = future
        try:
            result = await self.rest.load_tracks(identifier)
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()
            raise
        else:
            if cache is not None:
                cache.put(identifier, result)
            metrics.total_searches += 1
            metrics.node(node_id).search_count += 1
            tracer.trace(
                TraceCategory.SEARCH, "load_tracks", node_id=self.identifier, identifier=identifier
            )
            future.set_result(result)
            return result
        finally:
            self._inflight_loads.pop(identifier, None)

    async def decode_track(self, encoded_track: str) -> Track:
        """Decode one Lavalink encoded track."""

        return await self.rest.decode_track(encoded_track)

    async def decode_tracks(self, encoded_tracks: list[str]) -> list[Track]:
        """Decode multiple Lavalink encoded tracks."""

        return await self.rest.decode_tracks(encoded_tracks)

    async def search(
        self,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        use_cache: bool = True,
    ) -> Search:
        """Search tracks or playlists with source-prefix and URL handling."""

        result = await self.search_result(query, source=source, use_cache=use_cache)
        return unwrap_load_result(result)

    async def search_result(
        self,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        use_cache: bool = True,
    ) -> LoadResult:
        """Search and return the normalized `LoadResult`."""

        search_query = build_search_query(query, source=source)
        return await self.load_tracks(search_query.identifier, use_cache=use_cache)

    async def fetch_players(self) -> list[LavalinkPlayer]:
        """Fetch all Lavalink players for the active session."""

        session_id = self._require_session()
        players = await self.rest.fetch_players(session_id)
        self.players = {player.guild_id: player for player in players}
        return players

    async def fetch_player(self, guild_id: int) -> LavalinkPlayer:
        """Fetch one Lavalink player for the active session."""

        player = await self.rest.fetch_player(self._require_session(), guild_id)
        self.players[guild_id] = player
        return player

    async def fetch_player_info(self, guild_id: int) -> LavalinkPlayer | None:
        """Fetch one Lavalink player, returning `None` when Lavalink reports 404."""

        try:
            return await self.fetch_player(guild_id)
        except LavalinkError as exc:
            if exc.response.status == 404:
                return None
            raise

    async def update_player(
        self,
        guild_id: int,
        update: PlayerUpdate,
        *,
        replace: bool = False,
    ) -> LavalinkPlayer:
        """Update a Lavalink player and store the latest response."""

        async with self._player_lock:
            player = await self.rest.update_player(
                self._require_session(),
                guild_id,
                update,
                replace=replace,
            )
            self.players[guild_id] = player
            return player

    async def destroy_player(self, guild_id: int) -> None:
        """Destroy a Lavalink player and remove it from the registry."""

        async with self._player_lock:
            await self.rest.destroy_player(self._require_session(), guild_id)
            self.players.pop(guild_id, None)

    async def custom_request(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonPayload | None = None,
    ) -> RestResponse:
        """Call a Lavalink plugin/core REST endpoint through this node."""

        return await self.rest.custom_request(method, path, params=params, json=json)

    async def send(
        self,
        method: HttpMethod = "GET",
        *,
        path: str,
        data: JsonPayload | None = None,
        params: dict[str, str] | None = None,
    ) -> RestResponse:
        """Wavelink-style alias for custom Lavalink/plugin requests."""

        return await self.custom_request(method, path, params=params, json=data)

    def get_player(self, guild_id: int) -> LavalinkPlayer | None:
        """Return a known player by guild ID."""

        return self.players.get(guild_id)

    def register_player(self, player: FluxPlayer) -> None:
        """Register a live Discord player for reconnect recovery."""

        self._live_players[player.guild.id] = player

    def unregister_player(self, guild_id: int) -> None:
        """Remove a live Discord player from reconnect recovery."""

        self._live_players.pop(guild_id, None)

    async def recover_players(self, *, resumed: bool) -> None:
        """Recover live Discord players after a node reconnect if Lavalink did not resume."""

        if not self.auto_recover_players or resumed or not self._live_players:
            return

        await self.fetch_players()
        for player in tuple(self._live_players.values()):
            if player.destroyed:
                self.unregister_player(player.guild.id)
                continue

            try:
                await player.recover_voice_state()
                logger.debug(
                    "Recovered FluxWave player %s on node %s.",
                    player.guild.id,
                    self.identifier,
                )
            except Exception:
                logger.exception(
                    "Failed to recover FluxWave player %s on node %s.",
                    player.guild.id,
                    self.identifier,
                )

    def _require_session(self) -> str:
        if self.session_id is None:
            msg = "Node does not have an active Lavalink session."
            raise NodeError(msg)

        return self.session_id

    def _search_lfu_cache(self) -> LFUCache[str, LoadResult] | None:
        capacity = self.search_cache_capacity
        if capacity is None or capacity <= 0:
            self._search_cache = None
            return None

        if self._search_cache is None or self._search_cache.capacity != capacity:
            self._search_cache = LFUCache(capacity)

        return self._search_cache


class NodePool:
    """Registry, lifecycle manager, and selector for Lavalink nodes."""

    def __init__(
        self,
        *,
        selection_strategies: Iterable[NodeSelectionStrategy | str] | None = None,
    ) -> None:
        self._nodes: dict[str, Node] = {}
        self._cache_capacity: int | None = None
        self._cache: LFUCache[str, LoadResult] | None = None
        self.auto_migrate_players = True
        self.auto_return_players = True
        self._migration_tasks: set[asyncio.Task[int]] = set()
        self._blacklisted_until: dict[str, float] = {}
        self.selection_strategies = (
            _normalize_strategies(selection_strategies)
            if selection_strategies is not None
            else (
                NodeSelectionStrategy.LOCATION,
                NodeSelectionStrategy.SHARD,
                NodeSelectionStrategy.USAGE,
            )
        )

    @property
    def nodes(self) -> dict[str, Node]:
        """Return a shallow copy of registered nodes."""

        return self._nodes.copy()

    def add(self, node: Node) -> None:
        """Register a node without connecting it."""

        if node.identifier is None:
            msg = "Node identifier was not initialized."
            raise NodeError(msg)

        if node.identifier in self._nodes:
            msg = f"Node {node.identifier!r} is already registered."
            raise NodeError(msg)

        self._nodes[node.identifier] = node
        node.on("node_disconnected", self._schedule_player_migration)
        node.on("node_ready", self._schedule_player_return)

    async def connect(self, *nodes: Node) -> dict[str, Node]:
        """Register and connect provided nodes."""

        for node in nodes:
            self.add(node)

        for node in nodes:
            await node.connect()

        return self.nodes

    async def close(self) -> None:
        """Close all registered nodes."""

        for task in tuple(self._migration_tasks):
            task.cancel()

        for task in tuple(self._migration_tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await asyncio.gather(*(node.close() for node in list(self._nodes.values())))
        self._nodes.clear()

    async def reconnect(self) -> dict[str, Node]:
        """Reconnect all registered nodes."""

        await asyncio.gather(*(node.reconnect() for node in self._nodes.values()))
        return self.nodes

    async def migrate_players(
        self,
        source: Node,
        *,
        target: Node | None = None,
        record_home: bool = False,
    ) -> int:
        """Move live players from one node to another connected node.

        When ``record_home`` is true, each migrated player remembers ``source``
        as its home node so the pool can move it back automatically once that
        node recovers (see :meth:`return_players`).
        """

        migrated = 0
        for player in tuple(source._live_players.values()):
            destination = target
            if player.destroyed:
                source.unregister_player(player.guild.id)
                continue

            try:
                if destination is None:
                    destination = self._migration_target(
                        excluding=source,
                        guild_id=player.guild.id,
                        shard_count=getattr(
                            getattr(player, "client", None),
                            "shard_count",
                            None,
                        ),
                        endpoint=getattr(player, "_voice_endpoint", None),
                    )
                await player.switch_node(destination, allow_disconnected_source=True)
                # Preserve the original home across chained failures: if A fails and
                # the player moves to B, then B fails, the player should still return
                # to A (its first home), not B. Only record a home if none is set.
                if record_home and getattr(player, "_home_node", None) is None:
                    player._home_node = source
                metrics.node(source.identifier or "").player_migrations_out += 1
                metrics.node(destination.identifier or "").player_migrations_in += 1
                tracer.trace(
                    TraceCategory.MIGRATION,
                    "migrate_player",
                    guild_id=player.guild.id,
                    node_id=source.identifier,
                    target=destination.identifier,
                )
            except Exception:
                logger.exception(
                    "Failed to migrate FluxWave player %s from node %s to node %s.",
                    player.guild.id,
                    source.identifier,
                    destination.identifier if destination is not None else None,
                )
                continue

            migrated += 1

        return migrated

    async def handle_node_failure(self, source: Node, *, cooldown: float = 30.0) -> int:
        """Mark a node unavailable and migrate its live players when possible."""

        self.blacklist_node(source, cooldown=cooldown)
        migrated = await self.migrate_players(source, record_home=self.auto_return_players)
        source.status = NodeStatus.DISCONNECTED
        return migrated

    async def return_players(self, node: Node) -> int:
        """Move players displaced by a failure back to their recovered home node.

        Players are returned only when ``node`` is connected and they still name
        it as their home node. Returns the number of players moved back.
        """

        if node.status is not NodeStatus.CONNECTED:
            return 0

        returned = 0
        for other in tuple(self._nodes.values()):
            if other.identifier == node.identifier:
                continue

            for player in tuple(other._live_players.values()):
                home = player._home_node
                if home is None or home.identifier != node.identifier:
                    continue

                if player.destroyed:
                    player._home_node = None
                    continue

                try:
                    await player.switch_node(node, allow_disconnected_source=True)
                except Exception:
                    logger.exception(
                        "Failed to return FluxWave player %s to recovered node %s.",
                        player.guild.id,
                        node.identifier,
                    )
                    continue

                player._home_node = None
                returned += 1

        return returned

    def get_node(
        self,
        identifier: str | None = None,
        *,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
        strategies: Iterable[NodeSelectionStrategy | str] | None = None,
    ) -> Node:
        """Get a node by identifier or choose the least-loaded connected node."""

        if identifier is not None:
            try:
                return self._nodes[identifier]
            except KeyError as exc:
                msg = f"Node {identifier!r} is not registered."
                raise InvalidNodeError(msg) from exc

        return self.select_node(
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
            strategies=strategies,
        )

    def select_node(
        self,
        *,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
        strategies: Iterable[NodeSelectionStrategy | str] | None = None,
        excluding: Iterable[Node | str] | None = None,
    ) -> Node:
        """Select the best connected node for a guild/voice endpoint.

        Strategy order defaults to location, shard, then usage. If a strategy
        cannot narrow the set, FluxWave keeps the previous candidates and falls
        back to health score so selection remains reliable.
        """

        excluded = _node_identifier_set(excluding)
        candidates = [
            node
            for node in self._nodes.values()
            if node.status is NodeStatus.CONNECTED
            and not self.is_blacklisted(node)
            and node.identifier not in excluded
        ]
        if not candidates:
            msg = "No connected Lavalink nodes are available."
            raise InvalidNodeError(msg)

        selected = self._apply_selection_strategies(
            candidates,
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
            strategies=strategies,
        )

        return min(selected, key=lambda node: (node.health_score, node.identifier or ""))

    def matching_nodes(
        self,
        *,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
        strategies: Iterable[NodeSelectionStrategy | str] | None = None,
    ) -> list[Node]:
        """Return connected nodes after region/shard strategy filtering."""

        candidates = [
            node
            for node in self._nodes.values()
            if node.status is NodeStatus.CONNECTED and not self.is_blacklisted(node)
        ]
        if not candidates:
            return []

        return self._apply_selection_strategies(
            candidates,
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
            strategies=strategies,
        )

    def get_region(self, endpoint: str | None) -> str | None:
        """Return the configured region group matching a Discord voice endpoint."""

        voice_region = parse_voice_region(endpoint)
        if voice_region is None:
            return None

        for group, aliases in DEFAULT_REGION_GROUPS.items():
            if voice_region in aliases:
                return group

        return voice_region

    def get_nodes_by_region(self, region: str) -> list[Node]:
        """Return all registered nodes tagged for a region or voice endpoint alias."""

        normalized = _normalize_region(region)
        return [
            node
            for node in self._nodes.values()
            if node.regions is not None and normalized in node.regions
        ]

    def _apply_selection_strategies(
        self,
        candidates: Sequence[Node],
        *,
        guild_id: int | None,
        shard_count: int | None,
        endpoint: str | None,
        strategies: Iterable[NodeSelectionStrategy | str] | None,
    ) -> list[Node]:
        narrowed = list(candidates)
        selected_strategies = (
            _normalize_strategies(strategies)
            if strategies is not None
            else self.selection_strategies
        )
        for strategy in selected_strategies:
            next_nodes = self._filter_by_strategy(
                strategy,
                narrowed,
                guild_id=guild_id,
                shard_count=shard_count,
                endpoint=endpoint,
            )
            if next_nodes:
                narrowed = next_nodes

        return narrowed

    def _filter_by_strategy(
        self,
        strategy: NodeSelectionStrategy,
        candidates: Sequence[Node],
        *,
        guild_id: int | None,
        shard_count: int | None,
        endpoint: str | None,
    ) -> list[Node]:
        if strategy is NodeSelectionStrategy.USAGE:
            if not candidates:
                return []
            best_score = min(node.health_score for node in candidates)
            return [node for node in candidates if node.health_score == best_score]

        if strategy is NodeSelectionStrategy.RANDOM:
            return [secrets.choice(list(candidates))] if candidates else []

        if strategy is NodeSelectionStrategy.SHARD:
            if guild_id is None:
                return list(candidates)
            shard_id = calculate_shard_id(guild_id, shard_count)
            return [
                node for node in candidates if node.shard_ids is None or shard_id in node.shard_ids
            ]

        if strategy is NodeSelectionStrategy.LOCATION:
            voice_region = parse_voice_region(endpoint)
            if voice_region is None:
                return list(candidates)

            region_group = self.get_region(endpoint)
            wanted = {voice_region}
            if region_group is not None:
                wanted.add(region_group)

            return [
                node
                for node in candidates
                if node.regions is not None and not wanted.isdisjoint(node.regions)
            ]

        return list(candidates)

    def blacklist_node(self, node: Node | str, *, cooldown: float = 30.0) -> None:
        """Temporarily exclude a node from automatic selection."""

        identifier = node if isinstance(node, str) else node.identifier
        if identifier is None:
            msg = "Cannot blacklist a node without an identifier."
            raise NodeError(msg)

        self._blacklisted_until[identifier] = time.monotonic() + max(cooldown, 0.0)

    def unblacklist_node(self, node: Node | str) -> None:
        """Remove a node from the selection blacklist."""

        identifier = node if isinstance(node, str) else node.identifier
        if identifier is not None:
            self._blacklisted_until.pop(identifier, None)

    def is_blacklisted(self, node: Node | str) -> bool:
        """Whether a node is currently excluded from automatic selection."""

        identifier = node if isinstance(node, str) else node.identifier
        if identifier is None:
            return False

        until = self._blacklisted_until.get(identifier)
        if until is None:
            return False

        if until <= time.monotonic():
            self._blacklisted_until.pop(identifier, None)
            return False

        return True

    def _migration_target(
        self,
        *,
        excluding: Node,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
    ) -> Node:
        try:
            return self.select_node(
                guild_id=guild_id,
                shard_count=shard_count,
                endpoint=endpoint,
                excluding=[excluding],
            )
        except InvalidNodeError as exc:
            msg = "No connected Lavalink nodes are available for player migration."
            raise InvalidNodeError(msg) from exc

    def _schedule_player_migration(self, event: object) -> None:
        if not self.auto_migrate_players or not isinstance(event, NodeDisconnectedEvent):
            return

        source = self._nodes.get(event.identifier)
        if source is None or not source._live_players:
            return

        try:
            task = asyncio.create_task(self.handle_node_failure(source))
        except RuntimeError:
            logger.warning(
                "Cannot schedule FluxWave player migration for node %s without a running loop.",
                event.identifier,
            )
            return

        self._migration_tasks.add(task)
        task.add_done_callback(self._migration_tasks.discard)

    def _schedule_player_return(self, event: object) -> None:
        if not self.auto_return_players or not isinstance(event, NodeReadyEvent):
            return

        node = self._nodes.get(event.identifier)
        if node is None:
            return

        has_displaced = any(
            player._home_node is not None and player._home_node.identifier == node.identifier
            for other in tuple(self._nodes.values())
            if other.identifier != node.identifier
            for player in tuple(other._live_players.values())
        )
        if not has_displaced:
            return

        try:
            task = asyncio.create_task(self.return_players(node))
        except RuntimeError:
            logger.warning(
                "Cannot schedule FluxWave player return for node %s without a running loop.",
                event.identifier,
            )
            return

        self._migration_tasks.add(task)
        task.add_done_callback(self._migration_tasks.discard)

    async def load_tracks(
        self,
        identifier: str,
        *,
        node: Node | None = None,
        use_cache: bool = True,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
    ) -> LoadResult:
        """Load tracks using a provided node or the least-loaded connected node."""

        if use_cache and self._cache is not None:
            cached = self._cache.get(identifier)
            if cached is not None:
                return cached

        selected = node or self.get_node(
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
        )
        result = await selected.load_tracks(identifier, use_cache=use_cache)
        if use_cache:
            self._store_cache(identifier, result)
        return result

    async def decode_track(
        self,
        encoded_track: str,
        *,
        node: Node | None = None,
    ) -> Track:
        """Decode one track using a provided node or the least-loaded connected node."""

        selected = node or self.get_node()
        return await selected.decode_track(encoded_track)

    async def decode_tracks(
        self,
        encoded_tracks: list[str],
        *,
        node: Node | None = None,
    ) -> list[Track]:
        """Decode multiple tracks using a provided node or the least-loaded connected node."""

        selected = node or self.get_node()
        return await selected.decode_tracks(encoded_tracks)

    async def search(
        self,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        node: Node | None = None,
        use_cache: bool = True,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
    ) -> Search:
        """Search using a provided node or the least-loaded connected node."""

        result = await self.search_result(
            query,
            source=source,
            node=node,
            use_cache=use_cache,
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
        )
        return unwrap_load_result(result)

    async def search_result(
        self,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        node: Node | None = None,
        use_cache: bool = True,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
    ) -> LoadResult:
        """Search and return the normalized `LoadResult`."""

        selected = node or self.get_node(
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
        )
        search_query = build_search_query(query, source=source)
        if node is None:
            return await self.load_tracks(
                search_query.identifier,
                node=selected,
                use_cache=use_cache,
                guild_id=guild_id,
                shard_count=shard_count,
                endpoint=endpoint,
            )

        return await selected.load_tracks(search_query.identifier, use_cache=use_cache)

    async def fetch_routeplanner_status(
        self,
        *,
        node: Node | None = None,
    ) -> RoutePlannerStatus | None:
        """Fetch route planner status using a provided node or the least-loaded connected node."""

        selected = node or self.get_node()
        return await selected.fetch_routeplanner_status()

    async def free_routeplanner_address(self, address: str, *, node: Node | None = None) -> None:
        """Free one failing route planner address using a provided or selected node."""

        selected = node or self.get_node()
        await selected.free_routeplanner_address(address)

    async def free_all_routeplanner_addresses(self, *, node: Node | None = None) -> None:
        """Free all failing route planner addresses using a provided or selected node."""

        selected = node or self.get_node()
        await selected.free_all_routeplanner_addresses()

    def cache(self, capacity: int | bool | None = None) -> None:
        """Configure the pool-level load result cache."""

        if capacity is None or capacity is False:
            self._cache_capacity = None
            self._cache = None
            return

        if not isinstance(capacity, int):
            msg = "Cache capacity must be a positive integer, False, or None."
            raise ValueError(msg)

        if capacity <= 0:
            self._cache_capacity = None
            self._cache = None
            return

        self._cache_capacity = capacity
        self._cache = LFUCache(capacity)

    @property
    def has_cache(self) -> bool:
        """Whether the pool-level cache is enabled."""

        return self._cache is not None

    def get_degraded_nodes(self) -> list[Node]:
        """Return all connected nodes currently showing a degrading health trend."""

        return [
            node
            for node in self._nodes.values()
            if node.status is NodeStatus.CONNECTED and node.is_degraded
        ]

    async def drain(
        self,
        node: Node,
        *,
        target: Node | None = None,
        cooldown: float = 0.0,
    ) -> int:
        """Gracefully evacuate all live players from *node* before it goes down.

        Migrates players to *target* (or the best available node) and optionally
        blacklists *node* for *cooldown* seconds. Returns the number of
        successfully migrated players::

            # before maintenance:
            migrated = await pool.drain(old_node, cooldown=300.0)
            await old_node.close()
        """

        if cooldown > 0:
            self.blacklist_node(node, cooldown=cooldown)

        migrated = await self.migrate_players(node, target=target)
        logger.info(
            "NodePool: drained %d players from node %s.",
            migrated,
            node.identifier,
        )
        return migrated

    async def search_all(
        self,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        use_cache: bool = True,
    ) -> list[LoadResult]:
        """Search all connected nodes simultaneously and return all results.

        Useful for redundant search or aggregating results across nodes with
        different source-manager configurations.  Results are returned in the
        same order as the connected nodes (by identifier).

        Nodes that fail or are not connected are silently skipped::

            results = await pool.search_all("lo-fi beats")
            all_tracks = [t for r in results for t in r.tracks]
        """

        search_query = build_search_query(query, source=source)
        connected = [
            node
            for node in self._nodes.values()
            if node.status is NodeStatus.CONNECTED and not self.is_blacklisted(node)
        ]
        if not connected:
            msg = "No connected Lavalink nodes are available."
            raise InvalidNodeError(msg)

        async def _fetch(node: Node) -> LoadResult | None:
            try:
                return await node.load_tracks(search_query.identifier, use_cache=use_cache)
            except Exception:
                logger.debug(
                    "NodePool.search_all: node %s failed for query %r.",
                    node.identifier,
                    query,
                )
                return None

        raw = await asyncio.gather(*(_fetch(n) for n in connected))
        return [r for r in raw if r is not None]

    def _store_cache(self, identifier: str, result: LoadResult) -> None:
        if self._cache is None:
            return

        self._cache.put(identifier, result)


def parse_voice_region(endpoint: str | None) -> str | None:
    """Extract a Discord voice region alias from an endpoint."""

    if not endpoint:
        return None

    cleaned = endpoint.removeprefix("wss://").removeprefix("ws://").lower()
    cleaned = cleaned.split("/", 1)[0]
    match = _REGION_ENDPOINT_RE.match(cleaned)
    if match is not None:
        return _normalize_region(match.group("region"))

    return _normalize_region(cleaned.split(".", 1)[0])


def calculate_shard_id(guild_id: int, shard_count: int | None) -> int:
    """Return Discord's shard ID for a guild ID."""

    count = shard_count if shard_count and shard_count > 0 else 1
    return (int(guild_id) >> 22) % count


def _normalize_region(region: str) -> str:
    return region.strip().lower().replace("_", "-")


def _normalize_regions(
    region: str | None,
    regions: Iterable[str] | None,
) -> tuple[str, ...] | None:
    values: set[str] = set()
    if region:
        values.add(_normalize_region(region))
    if regions is not None:
        values.update(_normalize_region(value) for value in regions if str(value).strip())

    return tuple(sorted(values)) if values else None


def _normalize_shard_ids(shard_ids: Iterable[int] | None) -> tuple[int, ...] | None:
    if shard_ids is None:
        return None

    return tuple(sorted({int(shard_id) for shard_id in shard_ids}))


def _normalize_strategies(
    strategies: Iterable[NodeSelectionStrategy | str],
) -> tuple[NodeSelectionStrategy, ...]:
    return tuple(
        strategy
        if isinstance(strategy, NodeSelectionStrategy)
        else NodeSelectionStrategy(str(strategy).lower())
        for strategy in strategies
    )


def _node_identifier_set(nodes: Iterable[Node | str] | None) -> set[str]:
    if nodes is None:
        return set()

    identifiers: set[str] = set()
    for node in nodes:
        identifier = node if isinstance(node, str) else node.identifier
        if identifier is not None:
            identifiers.add(identifier)

    return identifiers
