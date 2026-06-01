# Troubleshooting

## Quick Links

- [Bot Connects but No Audio Plays](#bot-connects-but-no-audio-plays)
- [`Timed out connecting player`](#timed-out-connecting-player)
- [Search Returns Empty](#search-returns-empty)
- [Playlist Only Plays One Track](#playlist-only-plays-one-track)
- [New Song Skips Current Song](#new-song-skips-current-song)
- [Stop or Skip Does Nothing](#stop-or-skip-does-nothing)
- [Filters Do Not Take Effect Immediately](#filters-do-not-take-effect-immediately)
- [Node Fails or Becomes Overloaded](#node-fails-or-becomes-overloaded)
- [Restoring State Fails](#restoring-state-fails)
- [Lyrics or SponsorBlock Plugin Errors](#lyrics-or-sponsorblock-plugin-errors)
- [How to Report Bugs](#how-to-report-bugs)

## Bot Connects but No Audio Plays

Check:

- Lavalink is running and reachable from the bot host.
- The node URI uses the right scheme: `http://` or `https://`.
- `LAVALINK_PASSWORD` matches Lavalink config.
- The bot has `Connect` and `Speak` permissions.
- Lavalink has a source manager that can load your query/source.
- Your Discord library has voice dependencies installed.

For Lavalink 4.2/DAVE, FluxWave sends `channelId` in voice updates. If you still
see DAVE protocol errors, verify your Lavalink and Discord voice dependencies
are current.

## `Timed out connecting player`

This usually means Discord voice state/server updates did not complete or
Lavalink rejected the voice update.

Try:

- Confirm the bot is in the requested voice channel.
- Check Lavalink logs for voice update errors.
- Verify bot gateway intents include voice states.
- Try moving the bot out and back into the channel.
- Check region/network reachability.

## Search Returns Empty

Use `search_result` to inspect the raw normalized load result:

```python
result = await fluxwave.Pool.search_result("ytsearch:test")  # raw normalized load result
print(result.load_type, result.error)  # inspect how Lavalink classified the query
```

Common causes:

- Missing source plugin.
- Wrong prefix for the installed plugin.
- Lavalink rate limit or source failure.
- Passing a raw identifier with a default source by accident.

Use `source=None` for explicit prefixes:

```python
await fluxwave.Pool.search("spsearch:artist track", source=None)  # source=None keeps the explicit prefix
```

## Playlist Only Plays One Track

For bot commands, use:

```python
await player.enqueue(playlist_or_url)  # adds all tracks from a playlist or URL to the queue
```

`player.play(track)` is direct playback for one `Track`, not playlist queueing.

## New Song Skips Current Song

Use `enqueue` for normal play commands:

```python
result = await player.enqueue(query)  # queue the track without interrupting playback
if player.current is None:  # nothing playing yet
    await player.skip(force=True)  # start the first queued track
```

`play_search` is intentionally “search and immediately play”.

## Stop or Skip Does Nothing

Check that `ctx.voice_client` is a `FluxPlayer`:

```python
if not isinstance(ctx.voice_client, fluxwave.FluxPlayer):  # ensure the bot uses a FluxPlayer
    return
```

Use forced skip to bypass loop mode:

```python
await player.skip(force=True)  # force=True skips even when loop mode is on
```

## Filters Do Not Take Effect Immediately

Some Lavalink filters refresh better when seeking to the current position:

```python
await player.set_filters(filters, seek=True)  # seek=True forces filters to apply right away
```

## Node Fails or Becomes Overloaded

Use health and migration helpers:

```python
degraded = fluxwave.Pool.get_degraded_nodes()  # list nodes performing poorly
await fluxwave.Pool.drain(node, cooldown=300)  # move players off a node and pause its use
await fluxwave.Pool.handle_node_failure(node)  # migrate players away from a failed node
```

## Restoring State Fails

The player must already be connected before restore:

```python
player = await voice_channel.connect(cls=fluxwave.FluxPlayer)  # connect first
await player.restore_state(state)  # then reload queue/position from saved state
```

Raw track payloads must be present for offline reconstruction. FluxWave
preserves `track.raw_data` from Lavalink load/decode responses.

## Lyrics or SponsorBlock Plugin Errors

See [Plugin Compatibility](plugin-compatibility.md) and [FAQ](faq.md) for exact
LavaLyrics, SponsorBlock, and LavaSrc notes.

Common meanings:

- `404 Not Found`: plugin missing, route differs, or no active Lavalink player.
- `400 Bad Request`: payload shape is wrong for the plugin route.
- `500 Internal Server Error`: the plugin or external provider failed.

## How to Report Bugs

Include:

- FluxWave version.
- Python version.
- `discord.py` version.
- Lavalink version and plugins.
- The query or source prefix used.
- Relevant Lavalink logs.
- A minimal command or script reproducing the issue.

Collect local FluxWave, Python, system, and Java details with:

```bash
python -m fluxwave --version
```
