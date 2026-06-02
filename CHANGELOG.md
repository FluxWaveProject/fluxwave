# Changelog

All notable changes to FluxWave are documented in this file. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/) once it reaches `1.0`.

## [Unreleased]

## [0.2.1] — 2026-06-02

### Changed

- Re-published package metadata so PyPI points at the new
  `FluxWaveProject/fluxwave` GitHub organization repository.

## [0.2.0] — 2026-06-02

### Added

- `player.live_lyrics()` streams synced lyric lines as the track plays, for
  karaoke-style live now-playing messages. It is an async iterator that yields
  each `LyricsLine` at its timestamp, re-syncs on seek, holds on pause, and ends
  cleanly when the track finishes or changes. Raises the new `LyricsError` when
  the current track has no time-synced lyrics. Builds on the existing
  `fetch_lyrics()` / `LyricsResult.at()` support.
- Opt-in crossfade for smooth volume transitions between tracks, via
  `player.enable_crossfade(...)` / `set_crossfade(config)` / `disable_crossfade()`
  and the new `Crossfade`, `CrossfadeConfig`, `CrossfadeStats`, and `FadeCurve`
  types. Each track fades up from silence as it starts and fades back down as it
  nears its end (Lavalink plays one track per player, so this is a fade-out then
  fade-in, not an overlapping mix). Configurable fade duration, direction, curve
  (linear / smooth / equal-power), floor volume, update interval, and a minimum
  track length below which fades are skipped. Also adds a standalone
  `player.fade_volume(target, duration=...)` primitive; an explicit `set_volume`
  always supersedes an in-progress fade. Playback is unchanged unless enabled.
- Expanded the audio filter preset library from 3 to 31 named effects, exposed
  through a new `FilterPreset` enum, `Filters.from_preset(name)`, and
  `Filters.apply_preset(name)`. Presets cover speed/pitch (`nightcore`,
  `vaporwave`, `daycore`, `slowed`, `sped_up`, `chipmunk`, `deep`,
  `double_time`), spatial (`8d`, `rotation`, `party`), modulation (`tremolo`,
  `vibrato`), vocals (`karaoke`), texture (`distortion`, `soft`, `muffled`,
  `lofi`, `slowed_reverb`, `mono`), and genre equalizers (`bass_boost`,
  `bass_boost_extreme`, `treble_boost`, `pop`, `rock`, `metal`, `jazz`,
  `classical`, `electronic`, `vocal`, `flat`). Each is also a fluent method on
  `Filters`, and presets compose with the existing builder. Preset string values
  are slash-command friendly so user input maps straight onto an effect.

## [0.1.1] — 2026-05-29

Documentation and packaging polish; no code or API changes.

- Host the documentation at <https://fluxwave.readthedocs.io> and point the
  README and project-metadata doc links at the hosted site.
- Tidy the README (condensed feature list, shorter docs section) and correct
  stale version/status references.
- Rewrite the product-design page as an architecture overview.

## [0.1.0] — 2026-05-29

First public pre-release. The core API is usable for beta bots and testing;
public APIs may still change before `1.0`. Requires Python 3.11+, `aiohttp`, a
Lavalink v4 server, and any one of discord.py / py-cord / nextcord / disnake.

### Core

- Async Lavalink v4 client with a typed REST layer and a websocket event layer
  (ready / stats / playerUpdate / events, session resume, jittered reconnect).
- Library-agnostic: FluxWave depends only on `aiohttp` and auto-detects whichever
  Discord library is installed (discord.py, py-cord, nextcord, or disnake).
  `FLUXWAVE_DISCORD_LIBRARY` / `FLUXWAVE_IGNORE_LIBRARY_CHECK` override detection.
- Strict typing throughout with a `py.typed` marker.
- Connect-time Lavalink version validation with clear unsupported/newer warnings.

### Nodes and pools

- `Node` owns one Lavalink server; `NodePool` is instance-first and the global
  `Pool` facade offers wavelink-style helpers (every `Pool` member is a classmethod,
  called as `Pool.x(...)`).
- Health-aware selection with region/shard awareness (`NodeSelectionStrategy`),
  blacklist/cooldowns, degraded-node detection, parallel multi-node `search_all`,
  and graceful `drain`.
- Automatic player migration on node failure and return-to-home-node once a failed
  node recovers.
- LFU search cache plus in-flight request coalescing so concurrent identical
  searches share a single Lavalink request.

### Players and playback

- `FluxPlayer` is a Discord `VoiceProtocol`: `channel.connect(cls=fluxwave.FluxPlayer)`
  resolves a node from the connected `Pool` automatically.
- `play`, `enqueue`, `play_search`, `play_next`, `skip`, `stop`, `pause`, `resume`,
  `seek`, `set_volume`, `move_to`, `switch_node`, `disconnect`/`destroy`.
- Position tracking, voice-state recovery, empty-channel auto-pause/resume/disconnect,
  and Pomice-style state aliases (`is_connected`, `is_playing`, `is_paused`, `is_dead`).

### Queue and filters

- Queue with history, loop modes, async waiters, move/shuffle/dedupe, range clearing,
  search, total duration, capacity limits, and raw serialization round-trips.
- Lavalink filters with ergonomic components, presets (nightcore, vaporwave,
  bass boost), `set_filters(..., seek=True)`, a tagged filter stack, and interpolation.

### Search, events, and plugins

- Search helpers for `ytsearch:`/`ytmsearch:`/`scsearch:`/etc., direct URLs,
  playlists, empty results, and load errors, with default-source prefixing.
- Typed public events with both `fluxwave_*` and wavelink-style aliases, a raw
  websocket event, and global `listen`/`dispatch` helpers.
- Plugin helpers for LavaLyrics, LavaSrc, and SponsorBlock, plus custom REST routes.

### Autoplay, persistence, and observability

- Autoplay with provider-based recommendations, duplicate filtering, and a partial
  mode (`AutoPlayMode`).
- Player state persistence via `save_state`/`restore_state`, a `MemoryStore`, and a
  crash-safe on-disk `FileStore`.
- `VoiceWatchdog` for stalled-playback recovery, `WrapperMetrics` operation counters,
  and an `EventTracer` — all wired into live operations.
- `SourceRouter` for glob-based per-source node routing.

### Tooling

- `python -m fluxwave --version` diagnostics CLI.
- Library-agnostic display helpers (`progress_bar`, `format_duration`,
  `paginate_queue`).
- Documentation site, beginner and advanced example bots, and a `release.yml`
  publish pipeline.
