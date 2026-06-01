# Migration Notes

FluxWave is not a copy of Wavelink, but it intentionally provides familiar
names where they make bot code easier to migrate.

## Quick Links

- [Familiar Names](#familiar-names)
- [Player Differences](#player-differences)
- [Pool Style](#pool-style)
- [Search Behavior](#search-behavior)
- [Queue Modes](#queue-modes)
- [Events](#events)
- [Not Drop-In](#not-drop-in)

## Familiar Names

Examples:

```python
track.length  # duration in ms (Wavelink-style alias for track.duration)
track.artwork  # cover art URL (Wavelink-style alias)
track.extras.requester  # custom data attached to the track
playlist.extras = {"requester": user_id}  # attach custom data to a playlist
await player.skip(force=True)  # skip current track, bypassing loop mode
await fluxwave.Pool.fetch_tracks("query")  # Wavelink-style track lookup
await fluxwave.Pool.get_tracks("query")  # Pomice-style track lookup
await fluxwave.Pool.get_playlist("url")  # load a playlist from a URL
```

Enum aliases are available in both uppercase and lowercase styles:

```python
fluxwave.SearchSource.YOUTUBE  # uppercase style
fluxwave.SearchSource.youtube  # lowercase alias, same value
fluxwave.AutoPlayMode.ENABLED  # uppercase style
fluxwave.AutoPlayMode.enabled  # lowercase alias, same value
```

Discord-style event aliases are also emitted:

```python
@bot.event
async def on_wavelink_track_start(event: fluxwave.TrackStartEvent) -> None:  # Wavelink-style event alias
    ...
```

Preferred FluxWave names use `fluxwave_`:

```python
@bot.event
async def on_fluxwave_track_start(event: fluxwave.TrackStartEvent) -> None:  # preferred FluxWave event name
    ...
```

## Player Differences

FluxWave command-friendly helpers separate queueing from direct replacement:

```python
await player.enqueue("song")  # add to the queue (use this for commands)
await player.play_search("song")  # search and play immediately
await player.play_next("song")  # add to the front of the queue
```

`player.play(track)` directly updates Lavalink playback and defaults to
`replace=True`. Bot commands should usually use `enqueue`.

## Pool Style

FluxWave supports both styles:

```python
pool = fluxwave.NodePool()  # instance style, good for tests/multi-client
await pool.connect(node)  # connect a node to this pool
```

```python
await fluxwave.Pool.connect(nodes=[node], cache_capacity=256)  # global style, convenient for simple bots
```

The instance style is better for tests and applications with multiple bot
clients. The global `Pool` style is convenient for simple bots.

## Search Behavior

Plain text defaults to YouTube search unless you pass another source:

```python
await fluxwave.Pool.search("song")  # defaults to YouTube search
await fluxwave.Pool.search("song", source=fluxwave.SearchSource.YOUTUBE_MUSIC)  # search a specific source
```

Use `source=None` when passing an explicit prefix or raw identifier:

```python
await fluxwave.Pool.search("spsearch:artist track", source=None)  # source=None keeps your explicit prefix
```

## Queue Modes

Names are string-compatible:

```python
fluxwave.QueueMode.NORMAL.value == "normal"  # enum value is a plain string
fluxwave.QueueMode.LOOP.value == "loop"  # repeat current track
fluxwave.QueueMode.LOOP_ALL.value == "loop_all"  # repeat the whole queue
```

`skip(force=True)` clears the loaded queue track so loop mode is bypassed.
`skip(force=False)` still advances to the next available track; it only keeps
loop bypassing disabled.

## Events

FluxWave event payloads include `player` on player/track/websocket events where
available. Track events also include `original` context for replacement/recovery
flows.

## Not Drop-In

Expect to update imports, setup code, and some command logic. FluxWave uses its
own models, exceptions, plugin helpers, and reliability tools.
