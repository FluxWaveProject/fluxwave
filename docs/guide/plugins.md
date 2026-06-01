# Plugins

FluxWave keeps plugin support flexible because Lavalink plugins differ in their
payloads and endpoints.

For version-specific endpoint behavior and common `404`/`500` plugin failures,
see [Plugin Compatibility](plugin-compatibility.md).

## Quick Links

- [Plugin Metadata](#plugin-metadata)
- [User Data and Extras](#user-data-and-extras)
- [Lyrics](#lyrics)
- [LavaSrc-Style Helpers](#lavasrc-style-helpers)
- [SponsorBlock Helpers](#sponsorblock-helpers)
- [Custom Plugin Routes](#custom-plugin-routes)
- [Custom Events](#custom-events)
- [Plugin Filters](#plugin-filters)

## Plugin Metadata

Track and playlist models preserve plugin fields:

```python
track.plugin_info  # raw plugin metadata dict
track.plugin_value("previewUrl")  # read a single plugin field
track.album
track.artist
track.preview_url  # short preview clip URL, if provided
track.is_preview  # True if this track is only a preview
playlist.plugin_info  # plugin metadata for the playlist
playlist.metadata
```

Raw Lavalink payloads are preserved for reconstruction:

```python
track.raw_data  # original Lavalink payload for this track
```

## User Data and Extras

`userData` is exposed as both a dict and an attribute-style namespace:

```python
track.user_data["requester"] = user_id  # store custom data via dict access
track.extras.requester = user_id  # same data via attribute access
track.extras = {"requester": user_id}  # replace all extras at once
```

Playlist extras apply to all tracks:

```python
playlist.extras = {"requester": user_id}  # set extras on every track in the playlist
```

## Lyrics

If your Lavalink server has a lyrics plugin:

```python
result = await player.fetch_lyrics()  # fetch lyrics for the current track
if result and result.synced:  # synced lyrics have timestamps
    line = result.at(player.position)  # lyric line at the current playback position
```

Simple command helper:

```python
text = await player.current_lyrics()  # plain-text lyrics for the current track
```

Lower-level LavaLyrics helpers are also available:

```python
lyrics = await node.plugins.lyrics.current(guild_id)  # lyrics for a guild's current track
lyrics = await node.plugins.lyrics.track(encoded_track)  # lyrics for a specific encoded track
```

## LavaSrc-Style Helpers

FluxWave exposes LavaSrc helpers through `node.plugins`:

```python
payload = await node.plugins.lavasrc.search("artist track", source="spsearch")  # search via LavaSrc (spsearch = Spotify)
```

The exact response depends on the plugin installed on your Lavalink server.

## SponsorBlock Helpers

```python
await node.plugins.sponsorblock.set_categories(
    guild_id,
    ["sponsor", "intro", "outro"],  # segment types to skip automatically
)
categories = await node.plugins.sponsorblock.categories(guild_id)  # read the active categories
await node.plugins.sponsorblock.clear_categories(guild_id)  # stop skipping any segments
```

SponsorBlock category routes are player-scoped, so the node needs an active
Lavalink session and a guild player.

## Custom Plugin Routes

Use `Node.send` for plugin endpoints FluxWave does not model yet:

```python
response = await node.send(
    "POST",  # HTTP method
    path="/v4/plugin/example",  # custom plugin endpoint
    data={"enabled": True},  # JSON body sent to the plugin
)
```

`Node.custom_request` is the lower-level alias.

## Custom Events

Unknown Lavalink websocket events are emitted as `ExtraEvent` and `PluginEvent`.
The raw payload is preserved:

```python
@fluxwave.listen("plugin_event")  # register a handler for unknown plugin events
async def on_plugin_event(event: fluxwave.PluginEvent) -> None:
    print(event.event_type, event.payload)  # event name and raw payload
```

## Plugin Filters

```python
filters = fluxwave.Filters().set_plugin_filters(
    {
        "myPlugin": {  # filter data keyed by plugin name
            "enabled": True,
        }
    }
)
await player.set_filters(filters)  # send the plugin filter to Lavalink
```
