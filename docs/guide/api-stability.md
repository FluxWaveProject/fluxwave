# API Stability

FluxWave is currently `0.2.2`, which means it is pre-release software.

The API is usable for beta bots, testing, and feedback, but public names may
still change before `1.0`.

## Quick Links

- [What Is Intended To Stay Stable](#what-is-intended-to-stay-stable)
- [What May Change Before 1.0](#what-may-change-before-10)
- [Compatibility Goals](#compatibility-goals)
- [Release Guidance](#release-guidance)

## What Is Intended To Stay Stable

These names are intended to be treated carefully:

- `Node`, `NodePool`, and `Pool`.
- `FluxPlayer`.
- `Track`, `Playlist`, `LoadResult`.
- `Queue`, `QueueMode`.
- `Filters`.
- `SearchSource`, `AutoPlayMode`.
- Public event payloads such as `TrackStartEvent` and `TrackEndEvent`.
- Command-friendly helpers such as `enqueue`, `play_search`, and `play_next`.
- Reliability helpers such as `PersistedState`, `VoiceWatchdog`, `SourceRouter`,
  `metrics`, and `tracer`.

Breaking these names should be avoided unless there is a strong reason.

## What May Change Before 1.0

These areas may still evolve:

- exact plugin helper method names and response parsing;
- autoplay recommendation internals;
- advanced node migration/failover tuning;
- event payload additions;
- exception hierarchy refinements;
- docs examples and recommended bot structure;
- package metadata and final project URLs.

Where possible, FluxWave should add aliases/deprecations before removing public
names.

## Compatibility Goals

FluxWave is not a Wavelink copy, but it intentionally keeps familiar migration
names where they help:

- `Pool.connect(nodes=[...])`
- `Pool.fetch_tracks(...)`
- `Pool.get_tracks(...)`
- `Pool.get_playlist(...)`
- `Track.search(...)`
- `track.length`
- `track.artwork`
- `track.extras`
- `playlist.extras = {...}`
- `player.skip(force=True)`
- Discord event aliases like `on_wavelink_track_start`

FluxWave-specific helpers are preferred for new bots:

```python
await player.enqueue("song")  # add to the queue (preferred for commands)
await player.play_next("song")  # add to the front of the queue
await player.play_search("song")  # search and play immediately
```

## Release Guidance

Before publishing a stable release:

1. Run unit, mocked, integration, and real Discord soak tests.
2. Verify examples against a real Lavalink node.
3. Freeze public names for `1.0`.
4. Update changelog and migration notes.
5. Publish docs online.
6. Tag a release and build distributions.
