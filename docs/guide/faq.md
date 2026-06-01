# FAQ

Short answers for common beginner questions.

## Quick Links

- [Why does a new song skip the current song?](#why-does-a-new-song-skip-the-current-song)
- [Why does a playlist only play one track?](#why-does-a-playlist-only-play-one-track)
- [Why do lyrics time out?](#why-do-lyrics-time-out)
- [Why does SponsorBlock return `null`?](#why-does-sponsorblock-return-null)
- [How do I disable autoplay?](#how-do-i-disable-autoplay)
- [Why does SponsorBlock say guild not found?](#why-does-sponsorblock-say-guild-not-found)
- [What does watchdog do?](#what-does-watchdog-do)

## Why does a new song skip the current song?

Use `enqueue(...)` for normal play commands:

```python
result = await player.enqueue(query)  # add the track(s) to the queue
if player.current is None:  # nothing playing yet
    await player.skip(force=True)  # start playback by advancing the queue
```

`play_search(...)` means "search and play immediately", so it can replace the
current track.

## Why does a playlist only play one track?

`player.play(track)` plays one `Track`.

For playlists and user commands, use:

```python
await player.enqueue(playlist_url_or_query)  # queues every playable track in the playlist
```

FluxWave will queue all playable playlist tracks.

## Why do lyrics time out?

Lyrics flow:

```text
FluxWave -> Lavalink -> lyrics plugin -> external lyrics provider
```

If you see:

```text
500 Internal Server Error
java.net.SocketTimeoutException: Read timed out
```

the plugin/provider timed out. Try another track, another source, or adjust the
Lavalink plugin/provider configuration.

## Why does SponsorBlock return `null`?

For `PUT` and `DELETE`, Lavalink may return no response body. FluxWave parses
that as `None`, which JSON displays as:

```json
null
```

That usually means the request was accepted. Check enabled categories with:

```python
await node.plugins.sponsorblock.categories(guild_id)  # list enabled SponsorBlock categories for the guild
```

## How do I disable autoplay?

```python
player.autoplay = fluxwave.AutoPlayMode.DISABLED  # turn autoplay off
```

Lowercase compatibility alias:

```python
player.autoplay = fluxwave.AutoPlayMode.disabled  # lowercase alias, same effect
```

For a command:

```text
!autoplay disabled
```

## Does `skip` continue autoplay?

Yes, when `player.autoplay` is `AutoPlayMode.ENABLED`.

Manual skip order:

1. normal queue;
2. auto queue;
3. newly populated recommendations;
4. stop if nothing is available.

```python
player.autoplay = fluxwave.AutoPlayMode.ENABLED  # turn autoplay on
await player.skip(force=True)  # skip; autoplay picks the next track if the queue is empty
```

`stop()` is different from `skip()`: by default it stops playback, clears the
normal queue, and clears generated autoplay recommendations so old queued work
cannot restart later.

## Why does SponsorBlock say guild not found?

SponsorBlock category routes need an active Lavalink player for that guild.

Run it after the bot is connected and playback has started:

```text
!join
!play never gonna give you up
!sponsor sponsor intro outro
```

## What does watchdog do?

Watchdog checks whether playback is reported as active but the position is
stuck for too long:

```python
watchdog = player.start_watchdog()  # begin monitoring for stuck playback
```

If the song is silent/frozen, it tries to restart the current track from the
last known position.
