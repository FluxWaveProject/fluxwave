# Plugin Compatibility

Lavalink plugins do not all expose the same endpoints. FluxWave keeps plugin
helpers best-effort and exposes `Node.send(...)` for custom routes.

## Quick Links

- [Check Installed Plugins](#check-installed-plugins)
- [LavaLyrics](#lavalyrics)
- [SponsorBlock](#sponsorblock)
- [LavaSrc Prefixes](#lavasrc-prefixes)
- [Common Plugin Errors](#common-plugin-errors)
- [Custom Routes](#custom-routes)

## Check Installed Plugins

```python
info = await node.fetch_info()  # query the Lavalink node's info
print(info.source_managers)  # available search/source backends
print([(plugin.name, plugin.version) for plugin in info.plugins])  # installed plugins and versions
```

If a helper returns `404`, first confirm the plugin is installed and that the
server version exposes the same route.

## LavaLyrics

FluxWave supports LavaLyrics-style current-track lyrics:

```python
payload = await node.plugins.lyrics.current(guild_id)  # lyrics for the guild's current track
```

This calls:

```text
GET /v4/sessions/{sessionId}/players/{guildId}/track/lyrics
```

The player must exist in Lavalink for that guild. In bot commands, use:

```python
result = await player.fetch_lyrics()  # full lyrics result for current track
text = await player.current_lyrics()  # plain lyrics text only
```

Encoded-track lyrics use:

```python
payload = await node.plugins.lyrics.track(encoded_track)  # lyrics by encoded track string
```

This calls:

```text
GET /v4/lyrics?track={encodedTrack}
```

`LyricsClient.search(...)` is only for custom lyrics plugins that expose:

```text
GET /v4/lyrics/search
```

LavaLyrics itself may not provide that search route.

## SponsorBlock

SponsorBlock category routes are player-scoped:

```python
await node.plugins.sponsorblock.set_categories(
    guild_id,
    ["sponsor", "intro", "outro"],
)  # set segment categories to skip
categories = await node.plugins.sponsorblock.categories(guild_id)  # read active categories
await node.plugins.sponsorblock.clear_categories(guild_id)  # remove all categories
```

These helpers call:

```text
GET    /v4/sessions/{sessionId}/players/{guildId}/sponsorblock/categories
PUT    /v4/sessions/{sessionId}/players/{guildId}/sponsorblock/categories
DELETE /v4/sessions/{sessionId}/players/{guildId}/sponsorblock/categories
```

`set_categories(...)` sends the raw JSON array expected by the plugin:

```json
["sponsor", "intro", "outro"]
```

Not:

```json
{"categories": ["sponsor", "intro", "outro"]}
```

Typical categories include `sponsor`, `intro`, `outro`, `selfpromo`,
`interaction`, `preview`, `music_offtopic`, and `filler`.

## LavaSrc Prefixes

FluxWave can search LavaSrc-compatible prefixes as strings:

```python
await fluxwave.Pool.search("artist track", source="spsearch")  # Spotify search prefix
await fluxwave.Pool.search("artist track", source="amsearch")  # Apple Music search prefix
await fluxwave.Pool.search("artist track", source="dzsearch")  # Deezer search prefix
await fluxwave.Pool.search("artist track", source="ymsearch")  # Yandex Music search prefix
```

Convenience helpers:

```python
await node.plugins.lavasrc.spotify("artist track")  # search Spotify via LavaSrc
await node.plugins.lavasrc.apple_music("artist track")  # search Apple Music via LavaSrc
await node.plugins.lavasrc.deezer("artist track")  # search Deezer via LavaSrc
await node.plugins.lavasrc.yandex_music("artist track")  # search Yandex Music via LavaSrc
```

Exact prefixes depend on your Lavalink plugin configuration.

## Common Plugin Errors

### `404 Not Found`

Usually means one of these:

- the plugin is not installed;
- the plugin route changed between versions;
- the player/guild does not exist yet;
- the endpoint is only available after playback starts.

For SponsorBlock, `Guild not found` means the guild has no active Lavalink
player yet. Start playback before calling category routes.

### `400 Bad Request`

Usually means the route exists but the payload shape is wrong. SponsorBlock
category updates expect a raw JSON array.

### `500 Internal Server Error`

Usually means the plugin reached an external provider and the provider failed.
For lyrics, a common example is:

```text
java.net.SocketTimeoutException: Read timed out
```

That is a Lavalink/plugin/provider failure, not a FluxWave route failure.

## Custom Routes

Use `Node.send(...)` when FluxWave does not model a plugin endpoint:

```python
response = await node.send(
    "POST",  # HTTP method
    path="/v4/plugin/example",  # custom plugin route
    data={"enabled": True},  # JSON body sent to the plugin
)
```

`data` can be a JSON object or a top-level JSON array.
