# API Reference

This page is a human-written reference for the public API exported by
`import fluxwave`. It is intentionally stable and concise while the project is
pre-`1.0`.

## Quick Links

- [Node API](#node-api)
- [Player API](#player-api)
- [Models](#models)
- [Queue API](#queue-api)
- [Filters API](#filters-api)
- [Events](#events)
- [Advanced Helpers](#advanced-helpers)
- [Search API](#search-api)
- [REST API](#rest-api)
- [Plugin API](#plugin-api)
- [Result API](#result-api)
- [Route Planner](#route-planner)
- [Exceptions](#exceptions)

## Node API

### `Node`

Represents one Lavalink server.

Constructor highlights:

- `uri`: Lavalink base URL, for example `http://127.0.0.1:2333`.
- `password`: Lavalink password.
- `user_id`: Discord bot user ID.
- `identifier`: optional stable node name.
- `heartbeat`, `request_timeout`, `connect_timeout`, `retries`.
- `resume_timeout`: Lavalink session resume timeout in seconds.
- `search_cache_capacity`: optional node-local LFU cache size.
- `inactive_player_timeout`, `inactive_channel_tokens`: player defaults.
- `validate_version`: validate Lavalink compatibility before websocket connect.
- `strict_version_check`: fail instead of warning on newer-than-tested v4 nodes.

Common methods:

- `connect()`, `reconnect()`, `close()`.
- `fetch_info()`, `fetch_stats()`, `fetch_version()`.
- `validate_lavalink_version()`.
- `load_tracks(identifier)`, `search(query)`, `search_result(query)`.
- `decode_track(encoded)`, `decode_tracks(encoded_tracks)`.
- `fetch_players()`, `fetch_player(guild_id)`, `fetch_player_info(guild_id)`.
- `update_player(guild_id, update)`, `destroy_player(guild_id)`.
- `send(method, path, params=None, data=None)` for custom/plugin routes.
- `fetch_routeplanner_status()`, `free_routeplanner_address(address)`,
  `free_all_routeplanner_addresses()`.

Important properties:

- `status`, `session_id`, `players`, `info`, `stats`.
- `player_count`, `latency`, `health_score`, `is_degraded`.
- `plugins` for plugin helpers.

### `NodePool`

Instance-based node manager.

Common methods:

- `add(node)`, `connect(*nodes)`, `close()`, `reconnect()`.
- `get_node(identifier=None, guild_id=None, shard_count=None, endpoint=None)`.
- `select_node(...)`, `matching_nodes(...)`, `get_region(endpoint)`,
  `get_nodes_by_region(region)`.
- `blacklist_node(node, cooldown=30)`, `unblacklist_node(node)`.
- `migrate_players(source, target=None)`, `handle_node_failure(source)`,
  `drain(node, target=None, cooldown=0)`.
- `load_tracks`, `search`, `search_result`, `search_all`.
- `cache(capacity)`.

### `Pool`

Global class-level facade around a default `NodePool`.

Useful members:

- `Pool.connect(nodes=[...], cache_capacity=...)`.
- `Pool.nodes()`, `Pool.node_count()`, `Pool.active_nodes()`, `Pool.has_cache()`.
  Every `Pool` member is a classmethod, so always call it with `()`.
- `Pool.get_node(...)`, `Pool.select_node(...)`, `Pool.matching_nodes(...)`.
- `Pool.search`, `Pool.fetch_tracks`, `Pool.get_tracks`,
  `Pool.get_playlist`, `Pool.search_all`.
- `Pool.router()`, `Pool.set_router(router)`.
- `Pool.drain(node)`, `Pool.get_degraded_nodes()`.

When a `SourceRouter` is configured, `Pool.search(...)` and
`Pool.search_result(...)` automatically route through it unless an explicit
`node=` is supplied.

## Player API

### `FluxPlayer`

Discord voice protocol backed by Lavalink.

Connection and lifecycle:

- `connect(timeout=60, reconnect=False, self_deaf=False, self_mute=False)`.
- `move_to(channel, timeout=60)`.
- `disconnect(force=False)`.
- `destroy()`.
- `switch_node(new_node)`.
- `recover_voice_state()`.

Playback:

- `play(track, replace=True, start=0, end=None, volume=None, paused=None,
  filters=None, populate=False)`.
- `enqueue(item, source=SearchSource.YOUTUBE, shuffle=False, limit=None, filters=None)`.
- `play_search(query, source=SearchSource.YOUTUBE, replace=True, filters=None)`.
- `play_next(item, source=SearchSource.YOUTUBE, shuffle=False, limit=None, filters=None)`.
- `pause(value=True)`, `resume()`, `seek(position=0)`.
- `set_volume(value=100)`, `fade_volume(target, duration=1.0, curve=FadeCurve.SMOOTH)`.
- `set_filters(filters=None, seek=False)`.
- `add_filter(filters, filter_tag="default", preload=False)`.
- `edit_filter(filter_tag, filters)`, `remove_filter(filter_tag)`.
- `has_filter(filter_tag)`, `get_filter(filter_tag)`, `clear_filters()`.
- `skip(force=None, play_next=None)`.
- `stop(force=True, clear_queue=True, clear_autoplay=True)`.

Search helpers accept `filters=`. FluxWave stores the filter payload on the
returned/queued tracks and applies it automatically when those tracks play,
unless `play(..., filters=...)` supplies an explicit override.

`skip(force=False)` still advances playback; `force` only controls whether
queue loop mode is bypassed.

`stop()` is standardized as the queue-clearing stop operation by default. Pass
`clear_queue=False` to stop only the current track while keeping queued tracks.

Lyrics and plugins:

- `fetch_lyrics()`.
- `current_lyrics()`.
- `live_lyrics(lyrics=None, poll_interval=0.5)` — async iterator yielding the
  current synced lyric line as the track plays; raises `LyricsError` when the
  track has no synced lyrics.

Safety and reliability:

- `check_voice_channel_safety()`.
- `populate_autoplay(seed=None, limit=None)`.
- `save_state(extra=None) -> PersistedState`.
- `restore_state(state: PersistedState, seek=True)`.
- `start_watchdog(config=None) -> VoiceWatchdog`.
- `enable_crossfade(duration=4.0, fade_in=True, fade_out=True, curve=FadeCurve.SMOOTH, ...) -> Crossfade`.
- `set_crossfade(config: CrossfadeConfig) -> Crossfade`, `disable_crossfade()`.

Key properties:

- `node`, `guild`, `channel`, `connected`, `destroyed`.
- `current`, `previous`, `playing`, `paused`, `position`, `volume`, `ping`.
- Pomice-style aliases: `is_connected`, `is_playing`, `is_paused`, `is_dead`.
- `queue`, `auto_queue`, `autoplay`, `filters`, `crossfade`.
- `inactive_timeout`, `inactive_channel_tokens`.

## Models

### `Track`

Track shortcuts:

- `title`, `author`, `duration`, `length`, `length_display`.
- `identifier`, `uri`, `artwork_url`, `artwork`, `source`.
- `is_seekable`, `is_stream`, `position`.
- `album`, `artist`, `extras`, `plugin_info`, `raw_data`.

Helpers:

- `Track.from_payload(payload)`.
- `Track.search(query, node=None, source="ytmsearch")`.
- `track.with_user_data(...)`.
- `track.with_playlist(playlist_info)`.
- `track.as_recommended()`.

### `Playlist`

Useful members:

- `name`, `selected_track`, `selected`, `tracks`.
- `type`, `url`, `artwork_url`, `artwork`, `author`, `metadata`.
- `playable_tracks(shuffle=False, limit=None, selected_first=True)`.
- `shuffled()`, `limited(limit)`, `with_user_data(...)`.
- `extras` setter applies user data to every track.

### `LoadResult`

Represents Lavalink load-tracks output:

- `load_type`: `TRACK`, `PLAYLIST`, `SEARCH`, `EMPTY`, `ERROR`, or `CUSTOM`.
- `tracks`, `playlist`, `error`, `plugin_info`, `custom_data`.

## Queue API

`Queue` supports:

- `Queue(max_size=None, overflow=True)` for optional bounded queues.
- `put`, `put_at`, `get`, `get_wait`, `peek`, `get_at`.
- `get(bypass_loop=True)` for custom skip commands that must ignore loop mode.
- `remove`, `delete`, `swap`, `move`, `shuffle`.
- `find`, `find_all`, `dedupe`, `drain`, `clear_next`.
- `clear`, `reset`, `copy`.
- `max_size`, `overflow`, `count`, `is_empty`, `total_duration`.

When `overflow=True`, new tracks displace old queued tracks. When
`overflow=False`, adding past `max_size` raises `QueueFull`.
- `to_raw_data()`, `Queue.from_payloads(...)`, `Queue.from_tracks(...)`.
- `loaded`, `current`, `count`, `is_empty`, `total_duration`, `history`.

Loop modes:

- `QueueMode.NORMAL` / `"normal"`.
- `QueueMode.LOOP` / `"loop"`.
- `QueueMode.LOOP_ALL` / `"loop_all"`.

## Filters API

`Filters` creates Lavalink filter payloads.

Common helpers:

- `Filters.from_payload(payload)`.
- `Filters.from_filters(...)`.
- `Filters.from_preset(preset, **options)`, `apply_preset(preset, **options)`.
- `Filters.copy(other)`.
- `Filters.interpolate(start, end, t)`.
- `clear()`, `reset()`, `remove(name)`, `to_payload()`.
- `volume`, `equalizer`, `karaoke`, `timescale`, `tremolo`, `vibrato`,
  `rotation`, `distortion`, `channel_mix`, `low_pass`, `plugin_filters`.

`FilterPreset` enumerates the named effects, each also exposed as a fluent
method on `Filters`:

- Speed / pitch: `nightcore`, `vaporwave`, `daycore`, `slowed`, `sped_up`,
  `chipmunk`, `deep`, `double_time`.
- Spatial: `8d`, `rotation`, `party`.
- Modulation / vocals: `tremolo`, `vibrato`, `karaoke`.
- Texture: `distortion`, `soft`, `muffled`, `lofi`, `slowed_reverb`, `mono`.
- Equalizer: `bass_boost`, `bass_boost_extreme`, `treble_boost`, `pop`, `rock`,
  `metal`, `jazz`, `classical`, `electronic`, `vocal`, `flat`.

Players also provide a Pomice-style tagged filter stack for command UIs:

- `player.add_filter(...)`, `player.edit_filter(...)`,
  `player.remove_filter(...)`.
- `player.has_filter(...)`, `player.filter_tags`,
  `player.preload_filter_tags`.
- `preload=True` stores filters for future playback without forcing an update
  when no track is loaded.

## Events

Typed event payloads:

- `NodeReadyEvent`, `NodeDisconnectedEvent`, `NodeClosedEvent`.
- `PlayerUpdateEvent`, `StatsUpdateEvent`.
- `TrackStartEvent`, `TrackEndEvent`, `TrackExceptionEvent`,
  `TrackStuckEvent`.
- `WebSocketClosedEvent`, `InactivePlayerEvent`, `ExtraEvent`, `PluginEvent`.

Register global listeners:

```python
@fluxwave.listen("track_start")  # register a global listener for the track_start event
async def on_track_start(event: fluxwave.TrackStartEvent) -> None:
    ...
```

Discord clients receive names like `fluxwave_track_start` and
`wavelink_track_start`.

## Advanced Helpers

- `VoiceWatchdog`, `WatchdogConfig`, `WatchdogStats`.
- `Crossfade`, `CrossfadeConfig`, `CrossfadeStats`, `FadeCurve` — opt-in smooth
  volume transitions between tracks (`player.enable_crossfade(...)`).
- `PersistedState`, `capture`, `PersistenceBackend`, `MemoryStore`.
  `PersistedState` includes current playback, normal queue/history, autoplay
  mode, auto queue/history, recommendation seeds, filters, and caller `extra`.
- `EventTracer`, `TraceCategory`, `TraceEvent`, `tracer`.
- `WrapperMetrics`, `NodeMetrics`, `metrics`.
- `SourceRouter`, `SourceRoute`.
- `LFUCache`.

## Search API

### `SearchSource`

Common enum values:

- `YOUTUBE`: `ytsearch`.
- `YOUTUBE_MUSIC`: `ytmsearch`.
- `SOUNDCLOUD`: `scsearch`.

Lowercase compatibility aliases are also available:

- `youtube`: `ytsearch`.
- `youtube_music`: `ytmsearch`.
- `soundcloud`: `scsearch`.

Use strings for plugin-specific prefixes:

```python
await fluxwave.Pool.search("artist track", source="spsearch")  # use a plugin prefix to search Spotify
```

### `build_search_query`

Normalizes query/source input into `SearchQuery`.

Rules:

- URLs pass through unchanged.
- Explicit prefixes are preserved.
- `source=None` means raw query.
- Plain text gets the selected source prefix.

## REST API

`RestClient` is the low-level Lavalink HTTP client. Most bot users should use
`Node`, but direct REST access is available for integrations and tests.

Methods:

- `fetch_info()`, `fetch_stats()`, `fetch_version()`.
- `load_tracks(identifier)`.
- `decode_track(encoded_track)`, `decode_tracks(encoded_tracks)`.
- `fetch_players(session_id)`, `fetch_player(session_id, guild_id)`.
- `update_player(session_id, guild_id, update, replace=False)`.
- `destroy_player(session_id, guild_id)`.
- `update_session(session_id, update)`.
- Route planner helpers.
- `custom_request(method, path, params=None, json=None)`.

Payload classes:

- `PlayerUpdate`.
- `SessionUpdate`.

## Plugin API

- `PluginHelpers`: access point exposed as `node.plugins`.
- `LyricsClient`: lyrics plugin routes.
- `LavaSrcClient`: LavaSrc-style helper routes.
- `SponsorBlockClient`: SponsorBlock category routes plus best-effort
  segment/chapter helpers for compatible custom builds.
- `PluginClient`: custom plugin request helper.

Plugin responses are intentionally flexible because Lavalink plugins vary by
server.

## Result API

### `EnqueueResult`

Returned by command-friendly queue helpers.

Fields:

- `added`
- `tracks`
- `playlist`
- `first_track`
- `source`
- `message`

Properties:

- `track`: first track shortcut.
- `empty`: true when `added == 0`.

### `LyricsResult`

Fields:

- `text`
- `lines`
- `provider`
- `source`
- `synced`
- `raw`

Method:

- `at(position)`: returns the active timestamped line if available.

## Route Planner

`RoutePlannerStatus` wraps Lavalink route planner status:

- `class_name`
- `details`
- `raw`
- `has_route_planner`

## Exceptions

Base exception: `FluxWaveError`.

Common subclasses:

- `NodeError`, `NodeConnectionError`, `InvalidNodeError`.
- `PlayerError`, `ChannelTimeoutError`, `InvalidChannelError`.
- `LavalinkError`, `AuthorizationError`, `TrackLoadError`.
- `LyricsError`.
- `QueueError`, `QueueEmpty`.
