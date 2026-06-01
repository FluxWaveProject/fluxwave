# Player Guide

`FluxPlayer` is the Discord voice protocol used by FluxWave. It owns the guild
voice connection, the Lavalink player, queues, playback state, and recovery
helpers.

## Quick Links

- [Connecting](#connecting)
- [Playback](#playback)
- [Command Helpers](#command-helpers)
- [Queue Advancement](#queue-advancement)
- [Lyrics](#lyrics)
- [Voice Safety](#voice-safety)
- [Persistence](#persistence)
- [Crossfade](#crossfade)
- [Watchdog](#watchdog)

## Connecting

```python
player = await voice_channel.connect(cls=fluxwave.FluxPlayer)  # join voice using FluxPlayer
```

The player selects a connected node from `Pool.default()` unless you pass a
specific node when constructing it manually.

## Playback

```python
await player.play(track)  # start playing a track
await player.pause()  # pause playback
await player.resume()  # resume playback
await player.seek(30_000)  # jump to 30 seconds (milliseconds)
await player.set_volume(80)  # set volume to 80%
await player.stop()  # stop playback
```

`player.play(track, replace=False)` uses Lavalink no-replace semantics. If a
track is already loaded, FluxWave returns the existing current track because the
new track was not actually accepted as current playback. If Lavalink rejects the
request, FluxWave rolls back local current/previous state.

## Command Helpers

Use these in bot commands:

```python
await player.enqueue("ytsearch:lofi beats")  # search and add to the queue
await player.play_search("direct search and play")  # search and play immediately
await player.play_next(track_or_playlist)  # insert at front of the queue
```

Plain text queries use the default source. Direct URLs are passed through without
adding a source prefix.

## Queue Advancement

```python
await player.skip()  # advance to the next track
await player.skip(force=True)  # skip even when looping the current track
await player.stop(force=True)  # stop and clear, bypassing loop
```

`skip()` is for current-track advancement. It can move into the normal queue,
the auto queue, or autoplay recommendations.

`force=True` bypasses looped loaded tracks so `QueueMode.LOOP` does not replay
the same track during a forced skip. `force=False` still advances normally; it
only leaves loop bypassing disabled.

`stop()` is the queue-clearing stop operation. By default it stops playback,
clears the normal queue, clears generated autoplay recommendations, and cancels
pending autoplay tasks. Use `await player.stop(clear_queue=False)` when you need
to stop only the current track while keeping queued user requests.

## Lyrics

If a lyrics plugin is available on the Lavalink server:

```python
lyrics = await player.fetch_lyrics()  # full lyrics result for current track
text = await player.current_lyrics()  # plain lyrics text only
```

`LyricsResult.synced` is true when timestamped lines are available.

When lyrics are synced, stream them line-by-line as the track plays to drive a
live karaoke-style now-playing message:

```python
async for line in player.live_lyrics():  # yields each line at its timestamp
    await message.edit(content=line.text)
```

Iteration ends cleanly when the track finishes or changes. A seek re-syncs to the
right line and a pause holds on the current one. `live_lyrics()` raises
`fluxwave.LyricsError` if the current track has no synced lyrics, so commands can
fall back to `current_lyrics()`:

```python
try:
    async for line in player.live_lyrics():
        await message.edit(content=line.text)
except fluxwave.LyricsError:
    await message.edit(content=await player.current_lyrics() or "No lyrics found.")
```

## Voice Safety

Useful options:

```python
player.auto_pause_on_empty = True  # pause when the channel empties
player.auto_resume_on_member_join = True  # resume when someone joins
player.auto_disconnect = True  # leave after the empty timeout
player.voice_empty_timeout = 60  # seconds to wait before disconnecting
player.inactive_channel_tokens = 3  # idle checks tolerated before action
```

Call `await player.check_voice_channel_safety()` if your bot wants to evaluate
channel membership after custom events.

## Persistence

```python
state = player.save_state(extra={"reason": "shutdown"})  # snapshot current playback
await store.save(player.guild.id, state)  # persist the snapshot by guild

restored = await store.load(player.guild.id)  # load any saved snapshot
if restored:
    await player.restore_state(restored)  # rebuild playback from the snapshot
```

State captures current track, position, pause state, volume, queue, history,
queue mode, filters, and custom metadata.

## Crossfade

Crossfade smooths the transition between tracks instead of cutting volume
instantly. It is fully opt-in — playback is unchanged until you enable it:

```python
player.enable_crossfade(5)  # 5-second fades between tracks
```

Each track fades up from silence as it starts and fades back down as it nears its
end, so the seam between songs is smooth. Lavalink plays one track per player, so
this is a fade-out followed by a fade-in rather than a true overlapping mix.

Tune it with keyword options (or a `CrossfadeConfig`):

```python
player.enable_crossfade(
    duration=6,  # fade length in seconds
    fade_in=True,  # ramp new tracks up from the floor
    fade_out=True,  # ramp tracks down before they end
    curve=fluxwave.FadeCurve.EQUAL_POWER,  # linear / smooth / equal_power
    min_track_duration=10,  # skip fades on clips shorter than this
)

player.disable_crossfade()  # turn it back off
```

`set_volume` always takes effect immediately and supersedes an in-progress fade.
You can also fade the volume manually, with or without crossfade enabled:

```python
await player.fade_volume(0, duration=3)  # gentle fade to silence
await player.fade_volume(100, duration=3)  # and back up
```

## Watchdog

```python
watchdog = player.start_watchdog(
    fluxwave.WatchdogConfig(check_interval=5, stagnation_threshold=12)  # check every 5s, stall after 12s frozen
)
```

The watchdog detects frozen playback position while a player reports active
playback. After enough strikes it attempts to restart the current track from the
last known position.
