# Product and API Design

## Scope

FluxWave is a Python library for building Discord music bots on top of Lavalink.
It owns the client-side connection to Lavalink, Discord voice integration, player state,
track loading, queues, filters, event payloads, and plugin escape hatches.

FluxWave is not a Lavalink server, bot framework, command framework, audio decoder, or
drop-in clone of another Lavalink client.

## Supported Runtime

- Python: 3.11, 3.12, 3.13, and 3.14.
- Async runtime: `asyncio`.
- HTTP/WebSocket transport: `aiohttp`.
- Discord library: any one of discord.py, py-cord, nextcord, or disnake. FluxWave
  depends only on `aiohttp` and auto-detects the installed library at import time;
  it does not bundle one.
- Lavalink target: v4 REST and websocket protocol.

## Architecture

FluxWave is organized in layers, from the Lavalink wire protocol up to the
Discord-facing player API. Each layer is independently typed and testable.

### Transport

`fluxwave.rest` is the low-level Lavalink REST boundary (`/v4/info`, `/v4/stats`,
`/version`, `/v4/loadtracks`, session updates, and player fetch/update/delete),
with structured error parsing and bounded retries. `fluxwave.websocket` owns the
`/v4/websocket` connection: it uses `aiohttp` heartbeats, configures session
resume after `ready`, and parses `ready`/`stats`/`playerUpdate`/track/voice-close
and unknown plugin messages into typed events. `fluxwave.backoff` provides the
jittered reconnect delay used when a connection drops.

### Models

`fluxwave.tracks` holds Discord-independent models — `Track`, `TrackInfo`,
`Playlist`, `LoadResult`, `NodeInfo`, `Stats`, `PlayerState`, `VoiceState`,
`LavalinkPlayer` — plus structured Lavalink error responses. Higher layers
consume these models rather than raw Lavalink dictionaries; raw payloads remain
available through explicit escape hatches.

### Nodes and pools

`fluxwave.node` defines `Node` (one Lavalink server: REST + websocket ownership,
auth, session tracking, live-player registry, optional LFU search cache, and
in-flight request coalescing) and `NodePool` (registration, lifecycle, and
selection). The global `Pool` facade in `fluxwave.pool` offers wavelink-style
class-level helpers over a default `NodePool`.

### Player

`fluxwave.player` defines `FluxPlayer`, a Discord `VoiceProtocol`. It receives
Discord voice state/server updates, forwards `token`/`endpoint`/`sessionId`/
`channelId` to Lavalink (required for Lavalink 4.2/DAVE), and exposes the playback
surface: `play`, `pause`, `resume`, `seek`, `set_volume`, `set_filters`, `stop`,
`skip`, `enqueue`, `play_search`, `play_next`, `move_to`, `switch_node`,
`connect`/`disconnect`/`destroy`. It estimates playback position, tracks
current/previous state, and rolls local state back if a play request fails.

### Queue and filters

`fluxwave.queue` provides `Queue` with validation, sync/async retrieval, history,
`NORMAL`/`LOOP`/`LOOP_ALL` modes, capacity limits, and raw serialization.
`fluxwave.filters` builds Lavalink filter payloads (volume, equalizer, karaoke,
timescale, tremolo, vibrato, rotation, distortion, channel mix, low pass, and
plugin filters), with presets, a tagged filter stack on the player, and
interpolation.

### Search

`fluxwave.search` (`build_search_query`) preserves direct URLs and explicit
source prefixes, applies an optional default source (e.g. `ytsearch`), and passes
raw identifiers through when the source is `None`. Searches return `list[Track]`
or `Playlist`; empty Lavalink results become an empty list and load errors raise
`TrackLoadError`.

### Events

`fluxwave.events` exposes typed payloads for node, stats, player-update, track,
websocket-close, raw-websocket, inactive-player, and plugin events. Track events
carry the owning player, original/current context, guild ID, and node identifier.

### Plugins

`fluxwave.plugins` provides best-effort helpers for LavaSrc search prefixes,
LavaLyrics, and SponsorBlock, plus a low-level custom-REST escape hatch.

### Autoplay

`fluxwave.autoplay` provides provider-based recommendations with weighted seed
selection, duplicate filtering across the queue/history/autoplay queue, and
source-specific recommendation query shapes.

### Persistence and observability

`fluxwave.persistence` snapshots and restores player state (`MemoryStore`,
crash-safe `FileStore`). `fluxwave.watchdog` detects stalled playback and
recovers it. `fluxwave.metrics` and `fluxwave.tracing` provide operation counters
and a structured trace ring buffer, both wired into live operations.

### Reliability and failover

Built on the layers above: health-aware node selection, blacklist/cooldown,
degraded-node detection, automatic player migration on failure, return-to-home
once a node recovers, hot-node draining, parallel multi-node search, websocket
reconnect with backoff, and player voice/playback recovery after reconnects.

### Discord-library compatibility

`fluxwave._libraries` detects the installed Discord library at import time so the
rest of the package never imports a specific one. `FLUXWAVE_DISCORD_LIBRARY` and
`FLUXWAVE_IGNORE_LIBRARY_CHECK` override detection.

## Public Class Names

- `Node`: one Lavalink server connection.
- `NodePool` / `Pool`: node registry, lifecycle manager, and node selector.
- `FluxPlayer` (alias `Player`): Discord guild voice player.
- `Track`: playable Lavalink track model.
- `Playlist`: playlist model.
- `LoadResult`: normalized load-tracks response.
- `Queue`: player queue abstraction.
- `Filters`: Lavalink filter payload builder.

## Package Layout

- `fluxwave.node`: node config, connection lifecycle, node pool.
- `fluxwave.pool`: global default-pool facade.
- `fluxwave.player`: Discord voice protocol and playback controls.
- `fluxwave.websocket`: Lavalink websocket handling.
- `fluxwave.rest`: Lavalink REST transport.
- `fluxwave.tracks`: track, playlist, and load result models.
- `fluxwave.queue`: queue primitives and loop modes.
- `fluxwave.filters`: audio filter builders.
- `fluxwave.search`: query building and search helpers.
- `fluxwave.results`: command-result and lyrics result models.
- `fluxwave.events`: typed event payloads and dispatch.
- `fluxwave.exceptions`: exception hierarchy.
- `fluxwave.plugins`: LavaSrc / LavaLyrics / SponsorBlock helpers.
- `fluxwave.autoplay`: recommendation providers and autoplay modes.
- `fluxwave.persistence`: player-state snapshot and restore backends.
- `fluxwave.watchdog`: stalled-playback detection and recovery.
- `fluxwave.metrics` / `fluxwave.tracing`: observability counters and traces.
- `fluxwave.router`: source-to-node routing rules.
- `fluxwave.cache` / `fluxwave.backoff` / `fluxwave.versioning`: LFU cache,
  reconnect backoff, and Lavalink version validation.
- `fluxwave.formatting`: library-agnostic display helpers.
- `fluxwave._libraries`: Discord-library detection (internal).
- `fluxwave.types`: protocol-level typed dictionaries.

## Event Names

FluxWave dispatches both internal/global events and Discord-facing events.
Discord-facing events use the `fluxwave_` prefix, and Wavelink-style aliases are
also emitted for migration friendliness:

- `on_fluxwave_node_ready`
- `on_fluxwave_node_disconnected`
- `on_fluxwave_node_closed`
- `on_fluxwave_player_update`
- `on_fluxwave_stats_update`
- `on_fluxwave_track_start`
- `on_fluxwave_track_end`
- `on_fluxwave_track_exception`
- `on_fluxwave_track_stuck`
- `on_fluxwave_websocket_closed`
- `on_fluxwave_extra_event`
- `on_fluxwave_inactive_player`

Global listeners can also be registered with `fluxwave.listen("track_start")`.

## Typing Policy

- The package ships `py.typed`.
- Public APIs are fully annotated.
- Internal protocol payloads use typed models or `TypedDict`.
- CI runs strict `mypy` for the package.
- Public payload classes prefer stable attributes over raw dictionaries.
- Raw Lavalink/plugin payloads remain available through explicit escape hatches.

## Compatibility Policy

- Pre-`1.0` versions may change public APIs while the API settles.
- After `1.0`, breaking changes require a major version bump (see
  [API Stability](guide/api-stability.md)).
- Lavalink v4 is the protocol target.
- discord.py, py-cord, nextcord, and disnake are all supported through the
  import-time detection layer; none is privileged over the others.
