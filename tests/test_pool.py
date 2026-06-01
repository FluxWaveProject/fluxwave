import fluxwave


def track_payload(encoded: str) -> dict[str, object]:
    return {
        "encoded": encoded,
        "info": {
            "identifier": encoded,
            "isSeekable": True,
            "author": "artist",
            "length": 1234,
            "isStream": False,
            "position": 0,
            "title": encoded,
            "sourceName": "youtube",
        },
    }


class FakePool:
    def __init__(self) -> None:
        self.connected: tuple[object, ...] = ()
        self.cache_capacity: int | bool | None = None

    @property
    def nodes(self) -> dict[str, object]:
        return {}

    @property
    def has_cache(self) -> bool:
        return self.cache_capacity is not None

    def cache(self, capacity: int | bool | None = None) -> None:
        self.cache_capacity = capacity

    async def connect(self, *nodes: object) -> dict[str, object]:
        self.connected = nodes
        return {"connected": nodes[0]} if nodes else {}


def test_global_pool_default_helpers() -> None:
    pool = fluxwave.NodePool()

    fluxwave.Pool.set_default(pool)
    try:
        assert fluxwave.Pool.default() is pool
        fluxwave.Pool.cache(2)
        assert fluxwave.Pool.has_cache()
    finally:
        fluxwave.Pool.reset()


async def test_global_pool_connect_accepts_wavelink_style_keywords() -> None:
    pool = FakePool()
    node = object()

    fluxwave.Pool.set_default(pool)  # type: ignore[arg-type]
    try:
        result = await fluxwave.Pool.connect(nodes=[node], client=object(), cache_capacity=5)
    finally:
        fluxwave.Pool.reset()

    assert result == {"connected": node}
    assert pool.connected == (node,)
    assert pool.cache_capacity == 5


class RoutingRest:
    def __init__(self, label: str) -> None:
        self.label = label
        self.identifiers: list[str] = []

    async def load_tracks(self, identifier: str) -> fluxwave.LoadResult:
        self.identifiers.append(identifier)
        return fluxwave.LoadResult.from_payload(
            {"loadType": "search", "data": [track_payload(f"{self.label}:{identifier}")]}
        )


def make_routing_node(identifier: str) -> tuple[fluxwave.Node, RoutingRest]:
    node = fluxwave.Node(
        "http://localhost:2333",
        password="password",
        user_id=123,
        identifier=identifier,
    )
    node.status = fluxwave.NodeStatus.CONNECTED
    rest = RoutingRest(identifier)
    node.rest = rest  # type: ignore[assignment]
    return node, rest


async def test_global_pool_search_uses_source_router() -> None:
    default, default_rest = make_routing_node("default")
    spotify, spotify_rest = make_routing_node("spotify")
    pool = fluxwave.NodePool()
    pool.add(default)
    pool.add(spotify)

    router = fluxwave.SourceRouter()
    router.add("spsearch:*", "spotify", priority=10)

    fluxwave.Pool.set_default(pool)
    fluxwave.Pool.set_router(router)
    try:
        result = await fluxwave.Pool.search("artist track", source="spsearch")
    finally:
        fluxwave.Pool.reset()

    assert isinstance(result, list)
    assert result[0].encoded.startswith("spotify:")
    assert spotify_rest.identifiers == ["spsearch:artist track"]
    assert default_rest.identifiers == []


def test_global_pool_reset_clears_router() -> None:
    router = fluxwave.SourceRouter()
    router.add("ytsearch:*", "missing")
    fluxwave.Pool.set_router(router)

    fluxwave.Pool.reset()

    assert not fluxwave.Pool.router()
