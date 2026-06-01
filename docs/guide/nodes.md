# Nodes and Pools

FluxWave can run one node or a multi-node Lavalink cluster.

## Quick Links

- [Single Node](#single-node)
- [Multiple Nodes](#multiple-nodes)
- [Region and Shard Selection](#region-and-shard-selection)
- [Version Validation](#version-validation)
- [Health and Failover](#health-and-failover)
- [Search Across Nodes](#search-across-nodes)
- [Source Routing](#source-routing)
- [Route Planner](#route-planner)

## Single Node

```python
node = fluxwave.Node(
    uri="http://127.0.0.1:2333",  # Lavalink server base URL
    password="youshallnotpass",  # Lavalink server password
    user_id=bot.user.id,  # Discord bot user ID
    identifier="main",  # stable name to reference this node
    resume_timeout=60,  # seconds Lavalink keeps the session for resuming
    search_cache_capacity=256,  # node-local search result cache size
)
await fluxwave.Pool.connect(nodes=[node])  # register and connect the node
```

## Multiple Nodes

```python
nodes = [
    fluxwave.Node("http://127.0.0.1:2333", "pass", bot.user.id, identifier="a"),  # first node
    fluxwave.Node("http://127.0.0.1:2334", "pass", bot.user.id, identifier="b"),  # second node
]
await fluxwave.Pool.connect(nodes=nodes, cache_capacity=512)  # connect cluster with shared cache
```

`Pool.get_node()` chooses the best connected node using health score and
blacklist state.

## Region and Shard Selection

Nodes can be tagged with Discord voice regions and shard IDs:

```python
us_node = fluxwave.Node(
    "http://us-lavalink:2333",
    "pass",
    bot.user.id,
    identifier="us",
    regions=["us", "us-east", "us-west"],  # Discord voice regions this node serves
    shard_ids=[0, 1],  # shard IDs this node handles
)
eu_node = fluxwave.Node(
    "http://eu-lavalink:2333",
    "pass",
    bot.user.id,
    identifier="eu",
    regions=["eu", "rotterdam"],  # Discord voice regions this node serves
    shard_ids=[2, 3],  # shard IDs this node handles
)
await fluxwave.Pool.connect(nodes=[us_node, eu_node])  # connect both regional nodes
```

When you know the Discord voice endpoint, FluxWave can prefer the closest
matching node and still fall back to the healthiest available node:

```python
node = fluxwave.Pool.select_node(  # pick the best node for this guild/endpoint
    guild_id=ctx.guild.id,
    shard_count=bot.shard_count,
    endpoint="vip-us-east123.discord.media",  # Discord voice endpoint to match region
)
```

The default strategy order is location, shard, then usage. You can override it:

```python
node = fluxwave.Pool.select_node(
    guild_id=ctx.guild.id,
    shard_count=bot.shard_count,
    strategies=[fluxwave.NodeSelectionStrategy.SHARD, fluxwave.NodeSelectionStrategy.USAGE],  # custom selection order: shard match then least usage
)
```

Search helpers also accept the same selection context:

```python
tracks = await fluxwave.Pool.search(  # search using node selection context
    "lofi",
    guild_id=ctx.guild.id,
    shard_count=bot.shard_count,
)
```

## Version Validation

FluxWave validates Lavalink compatibility before opening the node websocket.
The library targets Lavalink v4 and rejects v3/v5 or unparseable version text
with `UnsupportedLavalinkVersion`.

```python
node = fluxwave.Node(
    "http://127.0.0.1:2333",
    "pass",
    bot.user.id,
    validate_version=True,  # check Lavalink version before opening the websocket
)
await node.connect()  # connect this single node directly
```

Newer v4 builds than FluxWave's tested target emit `LavalinkVersionWarning` by
default. For locked-down production deployments, make that warning fatal:

```python
node = fluxwave.Node(
    "http://127.0.0.1:2333",
    "pass",
    bot.user.id,
    strict_version_check=True,  # fail instead of warning on newer-than-tested v4 builds
)
```

You can manually inspect the result:

```python
check = await node.validate_lavalink_version()  # inspect version compatibility result
print(check.version, check.supported, check.warning)  # version string, supported flag, any warning
```

Only disable validation for known-compatible custom builds:

```python
node = fluxwave.Node(..., validate_version=False)  # skip version checking entirely
```

## Health and Failover

```python
degraded = fluxwave.Pool.get_degraded_nodes()  # nodes with poor health scores
fluxwave.Pool.blacklist_node("a", cooldown=60)  # stop using node "a" for 60 seconds
fluxwave.Pool.unblacklist_node("a")  # re-enable node "a" immediately
```

When a node fails, FluxWave can migrate live players to another connected node:

```python
await fluxwave.Pool.handle_node_failure(node)  # migrate live players off the failed node
```

Before planned maintenance:

```python
await fluxwave.Pool.drain(node, cooldown=300)  # move players off node and blacklist it during maintenance
await node.close()  # disconnect the drained node
```

## Search Across Nodes

```python
results = await fluxwave.Pool.search_all("ytsearch:lofi")  # query every node, one result per node
tracks = [track for result in results for track in result.tracks]  # flatten all tracks into one list
```

This is useful when nodes have different source-manager plugins.

## Source Routing

```python
router = fluxwave.SourceRouter()  # create a rule set mapping search prefixes to nodes
router.add("spsearch:*", node_identifier="spotify-node", priority=10)  # route Spotify searches to spotify-node
router.add("ytsearch:*", node_identifier="youtube-node", priority=5)  # route YouTube searches to youtube-node
fluxwave.Pool.set_router(router)  # make the pool use this router for searches
```

`Pool.search(...)` and `Pool.search_result(...)` use the configured router
automatically when you do not pass `node=`. This lets Spotify, YouTube,
SoundCloud, and plugin-specific searches prefer different Lavalink nodes.

```python
spotify_tracks = await fluxwave.Pool.search("artist track", source="spsearch")  # routed to spotify-node
youtube_tracks = await fluxwave.Pool.search("artist track", source="ytsearch")  # routed to youtube-node
```

You can also resolve routes manually for custom workflows:

```python
node = fluxwave.Pool.router().resolve("spsearch:artist track", fluxwave.Pool.nodes())  # manually pick the node for a query
```

## Route Planner

```python
status = await node.fetch_routeplanner_status()  # current route planner IP rotation state
await node.free_routeplanner_address("1.2.3.4")  # unmark a single failing IP address
await node.free_all_routeplanner_addresses()  # unmark all failing IP addresses
```

These helpers wrap Lavalink route planner/admin endpoints.
