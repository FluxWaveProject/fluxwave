# Advanced Features

## Quick Links

- [Plugin Helpers](#plugin-helpers)
- [Autoplay](#autoplay)
- [Metrics](#metrics)
- [Tracing](#tracing)
- [Persistence Backends](#persistence-backends)
- [Custom Search Routing](#custom-search-routing)
- [Real Soak Testing](#real-soak-testing)
- [Low-Level REST Access](#low-level-rest-access)

## Plugin Helpers

Each node exposes `node.plugins`.

```python
lyrics_payload = await node.plugins.lyrics.current(guild_id)  # fetch lyrics for the playing track
await node.plugins.sponsorblock.set_categories(guild_id, ["sponsor", "intro"])  # auto-skip these segments
```

For custom plugin routes:

```python
response = await node.send("GET", path="/v4/plugin/custom")  # call any custom Lavalink REST route
```

## Autoplay

```python
player.autoplay = fluxwave.AutoPlayMode.ENABLED  # keep playing recommended tracks when queue empties
await player.populate_autoplay(limit=5)  # pre-fill the queue with up to 5 recommendations
```

FluxWave uses a recommendation provider, duplicate filtering across queues and
history, weighted seed selection, and source-specific recommendation queries.

## Metrics

```python
from fluxwave import metrics

print(metrics.to_dict())  # snapshot of wrapper-level counters
metrics.reset()  # clear all counters back to zero
```

Metrics are lightweight counters for wrapper-level observability.

## Tracing

```python
from fluxwave import tracer

tracer.enable()  # start recording debug events
events = tracer.recent(20)  # read the last 20 captured events
tracer.disable()  # stop recording
```

Tracing stores structured debug events in an in-memory ring buffer.

## Persistence Backends

`MemoryStore` is useful for development. Production bots should implement
`PersistenceBackend` with Redis, Postgres, SQLite, or another durable store.

```python
class RedisStore:
    async def save(self, guild_id: int, state: fluxwave.PersistedState) -> None:  # persist a guild's state
        ...

    async def load(self, guild_id: int) -> fluxwave.PersistedState | None:  # read it back (or None)
        ...

    async def delete(self, guild_id: int) -> None:  # remove the stored state
        ...
```

## Custom Search Routing

Use `SourceRouter` when some Lavalink nodes support different sources/plugins:

```python
router = fluxwave.SourceRouter()
router.add("spsearch:*", "spotify-node", priority=10)  # route Spotify queries to this node
router.add("ytsearch:*", "youtube-node", priority=5)  # route YouTube queries to this node

node = router.resolve("spsearch:artist track", fluxwave.Pool.nodes())  # pick the node for this query
```

## Real Soak Testing

Before public production use, test these flows with a real bot and real
Lavalink nodes:

- Restart Lavalink while music is playing.
- Move the bot between voice channels repeatedly.
- Kick the bot while playing.
- Spam skip/stop while loop modes are active.
- Queue large playlists.
- Use autoplay and playlists together.

## Low-Level REST Access

Most bots should use `Node`, but advanced integrations can use `RestClient`
directly:

```python
async with fluxwave.RestClient(
    "http://127.0.0.1:2333",
    password="youshallnotpass",
    user_id=1234567890,
) as rest:
    info = await rest.fetch_info()  # query Lavalink server info directly via REST
```

Use `Node.send` for custom routes when you already have a node.
