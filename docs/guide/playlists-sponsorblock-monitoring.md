# Playlists, SponsorBlock & Monitoring

This guide covers the storage, safety, and observability helpers added on top of
the core player/node API.

## Quick Links

- [Track Codec](#track-codec)
- [SponsorBlock](#sponsorblock)
- [REST Rate Limiting](#rest-rate-limiting)
- [Plugin Helpers](#plugin-helpers)
- [Saved Playlists](#saved-playlists)
- [Now Playing and Queue Views](#now-playing-and-queue-views)
- [Metrics and Trace Exporters](#metrics-and-trace-exporters)

## Track Codec

Lavalink tracks are base64-wrapped binary data (Lavaplayer's track frame).
FluxWave can encode and decode them locally, so tracks loaded from a database or
cache can be inspected and re-queued without a REST round-trip:

```python
stored = track.encode()  # the Lavalink encoded string
same = fluxwave.Track.decode(stored)  # rebuild it offline

try:
    fluxwave.Track.decode(user_input)
except fluxwave.TrackDecodeError:
    ...  # not a valid encoded track
```

## SponsorBlock

SponsorBlock is opt-in per player. Segments are read from the current track's
`pluginInfo` when present, otherwise from the node's SponsorBlock plugin, and
skipped as the playhead enters them:

```python
player.enable_sponsorblock()  # skip sponsor segments automatically
player.enable_sponsorblock(categories=["sponsor", "selfpromo"])  # custom set
player.disable_sponsorblock()

manager = player.sponsorblock  # the active SponsorBlockManager, or None
```

Configure the behaviour with `SponsorBlockConfig` and `SponsorBlockAction`
(`skip`, `notify`, or `disabled`). Each skip dispatches a
`SponsorBlockSkipEvent` and a `fluxwave_sponsorblock_skip` client event.

## REST Rate Limiting

`RateLimiter` combines a client-side sliding window with server-driven backoff.
Pass one to a node and every REST call respects it:

```python
limiter = fluxwave.RateLimiter(rate=10, per=1.0, burst=20)
node = fluxwave.Node(uri, password, user_id, rate_limiter=limiter)
```

`429` responses and `Retry-After` / `X-RateLimit-*` headers are handled
automatically. A limiter with `rate=None` only honours server penalties, so it
stays cheap for bots that never hit a limit.

## Plugin Helpers

Beyond `lyrics` and `sponsorblock`, each node exposes helpers for LavaSearch and
LavaDSPX:

```python
results = await node.plugins.lavasearch.tracks("lofi beats")
filters = node.plugins.lavadspx.filters(echo={"delay": 0.5})
```

## Saved Playlists

`PlaylistManager` provides named, per-user playlist CRUD over a pluggable
`PlaylistStore`:

```python
manager = fluxwave.PlaylistManager(fluxwave.FilePlaylistStore("data/playlists"))

await manager.create(guild.author.id, "Chill", tracks)
await manager.add_tracks(guild.author.id, "Chill", more_tracks)
playlist = await manager.require(guild.author.id, "Chill")

for track in playlist.tracks:
    await player.queue.put(track)
```

`MemoryPlaylistStore` and `FilePlaylistStore` ship in the box;
`PlaylistStore` is a runtime-checkable protocol, so a Redis or database backend
only needs `save`, `load`, `delete`, and `list_for`. Missing playlists raise
`PlaylistNotFound` and duplicate names raise `PlaylistAlreadyExists`.

## Now Playing and Queue Views

`NowPlaying` and `QueueView` turn a player or queue into data any Discord
library can render:

```python
view = fluxwave.NowPlaying.from_player(player)
embed = discord.Embed(title=view.title, description=view.progress())
for name, value, inline in view.fields():
    embed.add_field(name=name, value=value, inline=inline)

queue_view = fluxwave.QueueView.from_queue(player.queue, current=player.current)
embed.add_field(*queue_view.fields(page=0)[0])
```

Both expose `to_dict()` for caching or JSON APIs.

## Metrics and Trace Exporters

`PrometheusExporter` renders the wrapper metrics as Prometheus text;
`OpenTelemetryExporter` pushes them into any OpenTelemetry `Meter`:

```python
print(fluxwave.PrometheusExporter().render())

exporter = fluxwave.OpenTelemetryExporter(meter)
exporter.record_metrics()
exporter.record_traces(fluxwave.tracer.recent())
```

Neither exporter hard-depends on the target monitoring library.
