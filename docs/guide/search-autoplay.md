# Search and Autoplay

FluxWave separates low-level Lavalink loading from command-friendly search.

## Quick Links

- [Query Rules](#query-rules)
- [`search` vs `search_result`](#search-vs-search-result)
- [Track-Level Search](#track-level-search)
- [Playlist Handling](#playlist-handling)
- [Cache](#cache)
- [Autoplay Modes](#autoplay-modes)
- [Populate Recommendations](#populate-recommendations)
- [Custom Recommendation Provider](#custom-recommendation-provider)

## Query Rules

Plain text uses a default source:

```python
tracks = await fluxwave.Pool.search("lofi beats")  # search with the default source
```

Explicit prefixes are preserved:

```python
tracks = await fluxwave.Pool.search("ytsearch:lofi beats", source=None)  # YouTube search
tracks = await fluxwave.Pool.search("ytmsearch:lofi beats", source=None)  # YouTube Music search
tracks = await fluxwave.Pool.search("spsearch:artist track", source=None)  # Spotify search
```

Direct URLs pass through unchanged:

```python
result = await fluxwave.Pool.search("https://www.youtube.com/watch?v=...")  # load a direct URL
```

Raw Lavalink identifiers can be loaded with `source=None`:

```python
result = await fluxwave.Pool.search_result("encoded-or-plugin-id", source=None)  # load a raw Lavalink identifier
```

(search-vs-search-result)=
## `search` vs `search_result`

`search` unwraps Lavalink responses for bot commands:

- Track/search results become `list[Track]`.
- Playlist results become `Playlist`.
- Empty results become `[]`.
- Load errors raise `TrackLoadError`.

`search_result` returns the normalized `LoadResult` when you need exact
Lavalink response information:

```python
result = await fluxwave.Pool.search_result("ytsearch:lofi")  # get the raw LoadResult
if result.load_type is fluxwave.LoadType.SEARCH:  # check how Lavalink interpreted the query
    ...
```

## Track-Level Search

```python
tracks = await fluxwave.Track.search("lofi", source="ytmsearch")  # search YouTube Music for tracks
```

Pass a node or pool-like object when you do not want the global pool:

```python
tracks = await fluxwave.Track.search("lofi", node=my_node)  # search using a specific node instead of the pool
```

## Playlist Handling

```python
result = await player.enqueue(playlist_or_url, shuffle=True, limit=50)  # queue a playlist, shuffled and capped at 50 tracks
```

Playlists preserve metadata:

```python
playlist.name  # the playlist's title
playlist.selected  # index of the track Lavalink marked as selected
playlist.metadata  # extra playlist info from the source
playlist.playable_tracks(shuffle=True, limit=25)  # get up to 25 tracks, shuffled, selected track first
```

Selected tracks are moved first by default when queueing through
`Playlist.playable_tracks`.

## Cache

Node and pool search/load caches use LFU eviction, which keeps repeated searches
hotter than one-off queries.

```python
node = fluxwave.Node(..., search_cache_capacity=256)  # set this node's search cache size
fluxwave.Pool.cache(512)  # set the pool-wide search cache size
```

Disable cache for a specific search:

```python
tracks = await fluxwave.Pool.search("lofi", use_cache=False)  # bypass the cache for this search
```

Attach filters to searched tracks:

```python
filters = fluxwave.Filters().nightcore()  # build a nightcore audio filter
result = await player.enqueue("artist song", filters=filters)  # search and queue with filters attached
```

When the queued track plays later, FluxWave applies the attached filters
automatically. `play_search(..., filters=filters)` applies them immediately.

## Autoplay Modes

```python
player.autoplay = fluxwave.AutoPlayMode.DISABLED  # use only the normal queue
player.autoplay = fluxwave.AutoPlayMode.PARTIAL  # advance the queue but don't auto-fill it
player.autoplay = fluxwave.AutoPlayMode.ENABLED  # auto-queue recommended tracks when empty
```

Lowercase aliases are available for Wavelink-style command code:

```python
player.autoplay = fluxwave.AutoPlayMode.disabled
player.autoplay = fluxwave.AutoPlayMode.partial
player.autoplay = fluxwave.AutoPlayMode.enabled
```

`player.autoplay` validates values. Pass an `AutoPlayMode`, not a raw string.

Behavior:

- `DISABLED`: only the normal queue is used.
- `PARTIAL`: normal queue is advanced, but autoplay is not populated when empty.
- `ENABLED`: normal queue is used first, then auto queue, then recommendations.

## Populate Recommendations

```python
added = await player.populate_autoplay(limit=5)  # fetch up to 5 recommended tracks into the auto queue
```

FluxWave uses:

- Weighted current/previous/history seed selection.
- Duplicate filtering across normal queue, auto queue, history, current, and
  previous tracks.
- YouTube radio-style recommendation queries where possible.
- Spotify/LavaSrc-style `sprec:` seed queries where possible.

Manual skips also respect enabled autoplay. When `player.autoplay` is
`AutoPlayMode.ENABLED`, `await player.skip(force=True)` checks the normal queue,
then the auto queue, then tries to populate recommendations before stopping.

User playback commands cancel older pending autoplay work. If a recommendation
lookup is still running and a user calls `play`, `enqueue`, `play_search`,
`play_next`, `skip`, or `stop`, the older autoplay task is ignored so it cannot
replace the user's newer choice.

## Custom Recommendation Provider

Implement `RecommendationProvider`:

```python
class MyProvider:
    async def recommendations(
        self,
        seed: fluxwave.Track,
        *,
        limit: int,
    ) -> list[fluxwave.Track]:  # return recommendations for the given seed track
        return []


player.recommendation_provider = MyProvider()  # use this provider for autoplay recommendations
```
