# Events

FluxWave has two event surfaces:

- Node/global listeners through `fluxwave.listen`.
- Discord client dispatch events such as `on_fluxwave_track_start`.

## Quick Links

- [Discord Events](#discord-events)
- [Global Listeners](#global-listeners)
- [Event Payloads](#event-payloads)

## Discord Events

```python
@bot.event
async def on_fluxwave_track_start(
    event: fluxwave.TrackStartEvent,
) -> None:  # fires when a track starts playing
    print(event.player, event.track.title)


@bot.event
async def on_fluxwave_track_end(
    event: fluxwave.TrackEndEvent,
) -> None:  # fires when a track stops playing
    print(event.reason)  # why the track ended (finished, replaced, stopped, ...)
```

Wavelink-style aliases are also dispatched:

```python
@bot.event
async def on_wavelink_track_start(
    event: fluxwave.TrackStartEvent,
) -> None:  # Wavelink-style alias for track start
    ...
```

Voice connect and disconnect have their own events:

```python
@bot.event
async def on_fluxwave_connect(
    event: fluxwave.PlayerConnectEvent,
) -> None:  # fires once the voice handshake reaches Lavalink
    print(event.channel_id)


@bot.event
async def on_fluxwave_disconnect(
    event: fluxwave.PlayerDisconnectEvent,
) -> None:  # fires when the player is destroyed or leaves voice
    print(event.reason)  # e.g. "destroyed"
```

When SponsorBlock skipping is enabled, each time the playhead enters a segment
you get a `SponsorBlockSkipEvent`:

```python
@bot.event
async def on_fluxwave_sponsorblock_skip(
    event: fluxwave.SponsorBlockSkipEvent,
) -> None:
    print(event.segment.category, event.skipped)
```

## Global Listeners

```python
@fluxwave.listen("track_exception")  # global listener for track playback errors
async def on_track_exception(event: fluxwave.TrackExceptionEvent) -> None:
    print(event.exception)  # the error raised while playing
```

Node shutdown is available as a global/Wavelink-style event because it is not
owned by a single Discord player:

```python
@fluxwave.listen("wavelink_node_closed")  # global listener for when a node disconnects
async def on_node_closed(event: fluxwave.NodeClosedEvent) -> None:
    print(
        event.identifier, event.disconnected_guild_ids
    )  # which node closed and the guilds it dropped
```

Node lifecycle events (`node_ready`, `node_disconnected`, `node_closed`, and
`stats_update`) are forwarded to the global dispatcher under their plain name,
`fluxwave_node_ready`, and `wavelink_node_ready` (and so on), so they can be
heard without holding a node reference.

Remove listeners when needed:

```python
fluxwave.remove_listener("track_exception", on_track_exception)  # unregister a global listener
```

## Event Payloads

Track events include:

- `guild_id`
- `track`
- `player`
- `original`
- `node_identifier`

Websocket closed events include:

- `guild_id`
- `code`
- `reason`
- `by_remote`
- `player`

Unknown Lavalink/plugin events are exposed as `ExtraEvent`/`PluginEvent` with
the raw payload preserved.

`NodeClosedEvent` includes the node `identifier`, disconnected guild IDs, and
the disconnected player objects for shutdown logging or migration cleanup.
