"""Global default node pool helpers."""

from __future__ import annotations

from collections.abc import Iterable

from .node import Node, NodePool, NodeSelectionStrategy, NodeStatus
from .routeplanner import RoutePlannerStatus
from .router import SourceRouter
from .search import Search, SearchSource, build_search_query
from .tracks import LoadResult, Track


class Pool:
    """Class-level facade around a default :class:`NodePool`.

    FluxWave keeps `NodePool` instance-first for explicit ownership. This facade
    exists for users who prefer the global helper style common in Discord music
    bot libraries. Every member is a classmethod, so the whole surface is called
    uniformly as ``Pool.x(...)`` — e.g. ``Pool.node_count()``, ``Pool.active_nodes()``,
    ``Pool.router()``.
    """

    _default: NodePool = NodePool()
    _router: SourceRouter = SourceRouter()

    def __new__(cls) -> Pool:
        msg = "Pool is a class-level helper and should not be instantiated."
        raise TypeError(msg)

    @classmethod
    def default(cls) -> NodePool:
        """Return the active default node pool."""

        return cls._default

    @classmethod
    def nodes(cls) -> dict[str, Node]:
        """Return registered nodes on the default pool, keyed by identifier."""

        return cls._default.nodes

    @classmethod
    def node_count(cls) -> int:
        """Number of registered nodes on the default pool."""

        return len(cls._default.nodes)

    @classmethod
    def active_nodes(cls) -> list[Node]:
        """Nodes currently connected on the default pool."""

        return [n for n in cls._default.nodes.values() if n.status is NodeStatus.CONNECTED]

    @classmethod
    def has_cache(cls) -> bool:
        """Whether default-pool search caching is enabled."""

        return cls._default.has_cache

    @classmethod
    def set_default(cls, pool: NodePool) -> None:
        """Replace the active default node pool."""

        cls._default = pool

    @classmethod
    def reset(cls) -> None:
        """Reset the active default node pool to a new empty pool."""

        cls._default = NodePool()
        cls._router = SourceRouter()

    @classmethod
    def add(cls, node: Node) -> None:
        """Register a node on the default pool without connecting it."""

        cls._default.add(node)

    @classmethod
    async def connect(
        cls,
        *connect_nodes: Node,
        nodes: Iterable[Node] | None = None,
        nodes_iterable: Iterable[Node] | None = None,
        client: object | None = None,
        cache_capacity: int | None = None,
    ) -> dict[str, Node]:
        """Register and connect nodes on the default pool.

        `nodes`, `client`, and `cache_capacity` are accepted for Wavelink-style
        call sites. FluxWave nodes already own their Discord/client state, so
        `client` is intentionally ignored.
        """

        del client
        selected_iterable = nodes_iterable if nodes_iterable is not None else nodes
        selected = tuple(selected_iterable) if selected_iterable is not None else connect_nodes
        if cache_capacity is not None:
            cls.cache(cache_capacity)
        return await cls._default.connect(*selected)

    @classmethod
    async def close(cls) -> None:
        """Close and clear the default pool."""

        await cls._default.close()

    @classmethod
    async def reconnect(cls) -> dict[str, Node]:
        """Reconnect all nodes in the default pool."""

        return await cls._default.reconnect()

    @classmethod
    async def migrate_players(cls, source: Node, *, target: Node | None = None) -> int:
        """Move live players from one default-pool node to another."""

        return await cls._default.migrate_players(source, target=target)

    @classmethod
    async def handle_node_failure(cls, source: Node) -> int:
        """Mark a default-pool node unavailable and migrate its live players."""

        return await cls._default.handle_node_failure(source)

    @classmethod
    async def return_players(cls, node: Node) -> int:
        """Move players displaced by a failure back to their recovered home node."""

        return await cls._default.return_players(node)

    @classmethod
    def blacklist_node(cls, node: Node | str, *, cooldown: float = 30.0) -> None:
        """Temporarily exclude a default-pool node from automatic selection."""

        cls._default.blacklist_node(node, cooldown=cooldown)

    @classmethod
    def unblacklist_node(cls, node: Node | str) -> None:
        """Remove a default-pool node from the selection blacklist."""

        cls._default.unblacklist_node(node)

    @classmethod
    def get_node(
        cls,
        identifier: str | None = None,
        *,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
        strategies: Iterable[NodeSelectionStrategy | str] | None = None,
    ) -> Node:
        """Return a node by identifier or choose the best connected node."""

        return cls._default.get_node(
            identifier,
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
            strategies=strategies,
        )

    @classmethod
    def select_node(
        cls,
        *,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
        strategies: Iterable[NodeSelectionStrategy | str] | None = None,
        excluding: Iterable[Node | str] | None = None,
    ) -> Node:
        """Select a default-pool node using region/shard/usage strategies."""

        return cls._default.select_node(
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
            strategies=strategies,
            excluding=excluding,
        )

    @classmethod
    def matching_nodes(
        cls,
        *,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
        strategies: Iterable[NodeSelectionStrategy | str] | None = None,
    ) -> list[Node]:
        """Return matching default-pool nodes after strategy filtering."""

        return cls._default.matching_nodes(
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
            strategies=strategies,
        )

    @classmethod
    async def load_tracks(
        cls,
        identifier: str,
        *,
        node: Node | None = None,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
    ) -> LoadResult:
        """Load tracks through the default pool."""

        return await cls._default.load_tracks(
            identifier,
            node=node,
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
        )

    @classmethod
    async def fetch_tracks(cls, query: str, *, node: Node | None = None) -> Search:
        """Alias for high-level search through the default pool."""

        return await cls._default.search(query, source=None, node=node)

    @classmethod
    async def get_tracks(cls, query: str, *, node: Node | None = None) -> Search:
        """Wavelink-style alias for `fetch_tracks`."""

        return await cls.fetch_tracks(query, node=node)

    @classmethod
    async def get_playlist(cls, query: str, *, node: Node | None = None) -> Search:
        """Wavelink-style playlist/search alias through the default pool."""

        return await cls.fetch_tracks(query, node=node)

    @classmethod
    async def search(
        cls,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        node: Node | None = None,
        use_cache: bool = True,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
    ) -> Search:
        """Search through the default pool."""

        selected = node or cls._route_node(query, source=source)
        return await cls._default.search(
            query,
            source=source,
            node=selected,
            use_cache=use_cache,
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
        )

    @classmethod
    async def search_result(
        cls,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        node: Node | None = None,
        use_cache: bool = True,
        guild_id: int | None = None,
        shard_count: int | None = None,
        endpoint: str | None = None,
    ) -> LoadResult:
        """Search through the default pool and return the normalized load result."""

        selected = node or cls._route_node(query, source=source)
        return await cls._default.search_result(
            query,
            source=source,
            node=selected,
            use_cache=use_cache,
            guild_id=guild_id,
            shard_count=shard_count,
            endpoint=endpoint,
        )

    @classmethod
    async def decode_track(cls, encoded_track: str, *, node: Node | None = None) -> Track:
        """Decode one track through the default pool."""

        return await cls._default.decode_track(encoded_track, node=node)

    @classmethod
    async def decode_tracks(
        cls,
        encoded_tracks: list[str],
        *,
        node: Node | None = None,
    ) -> list[Track]:
        """Decode multiple tracks through the default pool."""

        return await cls._default.decode_tracks(encoded_tracks, node=node)

    @classmethod
    async def fetch_routeplanner_status(
        cls,
        *,
        node: Node | None = None,
    ) -> RoutePlannerStatus | None:
        """Fetch route planner status through the default pool."""

        return await cls._default.fetch_routeplanner_status(node=node)

    @classmethod
    async def free_routeplanner_address(cls, address: str, *, node: Node | None = None) -> None:
        """Free one failing route planner address through the default pool."""

        await cls._default.free_routeplanner_address(address, node=node)

    @classmethod
    async def free_all_routeplanner_addresses(cls, *, node: Node | None = None) -> None:
        """Free all failing route planner addresses through the default pool."""

        await cls._default.free_all_routeplanner_addresses(node=node)

    @classmethod
    def cache(cls, capacity: int | bool | None = None) -> None:
        """Configure default-pool search caching."""

        cls._default.cache(capacity)

    @classmethod
    def router(cls) -> SourceRouter:
        """Return the default pool's :class:`~fluxwave.SourceRouter`."""

        return cls._router

    @classmethod
    def set_router(cls, router: SourceRouter) -> None:
        """Replace the default pool's source router."""

        cls._router = router

    @classmethod
    async def search_all(
        cls,
        query: str,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        use_cache: bool = True,
    ) -> list[LoadResult]:
        """Search all connected nodes simultaneously and return all results.

        Each connected node is queried in parallel.  Nodes that fail are
        silently skipped.  Use this when you have multiple nodes with different
        source-manager configurations and want the broadest result set::

            results = await Pool.search_all("chill beats")
            tracks = [t for r in results for t in r.tracks]
        """

        return await cls._default.search_all(query, source=source, use_cache=use_cache)

    @classmethod
    def get_degraded_nodes(cls) -> list[Node]:
        """Return connected default-pool nodes showing a worsening health trend."""

        return cls._default.get_degraded_nodes()

    @classmethod
    async def drain(
        cls,
        node: Node,
        *,
        target: Node | None = None,
        cooldown: float = 0.0,
    ) -> int:
        """Gracefully evacuate players from *node* before maintenance.

        Returns the number of successfully migrated players::

            await Pool.drain(old_node, cooldown=300.0)
            await old_node.close()
        """

        return await cls._default.drain(node, target=target, cooldown=cooldown)

    @classmethod
    def _route_node(cls, query: str, *, source: SearchSource | str | None) -> Node | None:
        if not cls._router:
            return None

        search_query = build_search_query(query, source=source)
        return cls._router.resolve(search_query.identifier, cls._default.nodes)
