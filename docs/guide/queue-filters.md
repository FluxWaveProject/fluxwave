# Queues and Filters

## Quick Links

- [Queue Basics](#queue-basics)
- [Queue Tools](#queue-tools)
- [Loop Modes](#loop-modes)
- [Serialization](#serialization)
- [Filters](#filters)

## Queue Basics

```python
queue = fluxwave.Queue()
queue.put(track)  # add a single track
queue.put(playlist)  # add all tracks from a playlist
queue.put([track_a, track_b])  # add multiple tracks at once
```

Call syntax is also supported:

```python
added = queue([track_a, track_b])  # calling the queue is shorthand for put()
```

Bounded queues protect public bots from unlimited request spam:

```python
queue = fluxwave.Queue(max_size=100, overflow=True)  # cap at 100, drop oldest when full
queue.put(playlist)
```

With `overflow=True`, new tracks are accepted and the oldest queued tracks are
dropped when the queue is full. Use `overflow=False` when you want strict
failure instead:

```python
queue = fluxwave.Queue(max_size=100, overflow=False)  # reject new tracks when full

try:
    queue.put(track)
except fluxwave.QueueFull:  # raised when the queue is at max_size
    print("Queue is full")
```

## Queue Tools

```python
queue.move(5, 0)  # move the 6th track to the front
queue.swap(0, 1)  # swap the first two tracks
queue.shuffle()  # randomize the queue order
queue.dedupe()  # remove duplicate tracks
removed = queue.clear_next(10)  # remove the next 10 tracks
found = queue.find("song title")  # first track matching the text
matches = queue.find_all("artist")  # all tracks matching the text
```

## Loop Modes

```python
queue.mode = fluxwave.QueueMode.NORMAL  # play through once, no looping
queue.mode = fluxwave.QueueMode.LOOP  # repeat the current track
queue.mode = fluxwave.QueueMode.LOOP_ALL  # repeat the whole queue
```

`queue.get()` intentionally obeys loop mode. In `LOOP`, it can return the loaded
track again. Use `queue.get(bypass_loop=True)` for skip-style commands that must
advance to a different queued track instead of replaying the loaded one.

## Serialization

```python
raw = queue.to_raw_data()  # serialize the queue to plain data
restored = fluxwave.Queue.from_payloads(**raw)  # rebuild the queue from saved data
```

This uses stored Lavalink track payloads, so it can restore tracks without
decoding them through a live node.

## Filters

```python
filters = fluxwave.Filters().bass_boost()  # build a bass-boost filter
await player.set_filters(filters, seek=True)  # apply now (seek re-applies to current audio)
```

### Presets

FluxWave ships a library of ready-to-use effects. Apply one by name with
`Filters.from_preset` (a fresh, single-effect payload — ideal for a `/filter`
command) or chain the fluent methods to combine effects:

```python
await player.set_filters(fluxwave.Filters.from_preset("8d"))  # apply a preset by name
await player.set_filters(fluxwave.Filters.from_preset(fluxwave.FilterPreset.NIGHTCORE))

fluxwave.Filters().bass_boost().eight_d()  # presets compose with each other
fluxwave.Filters().clear()  # remove all filters
```

Every member of `fluxwave.FilterPreset` is also available as a fluent method.
The string values are slash-command friendly, so user input maps straight onto a
preset:

```python
@bot.tree.command()
async def filter(interaction, effect: str):
    await player.set_filters(fluxwave.Filters.from_preset(effect))  # e.g. "slowed_reverb"
```

Available presets:

| Group | Presets |
| --- | --- |
| Speed / pitch | `nightcore`, `vaporwave`, `daycore`, `slowed`, `sped_up`, `chipmunk`, `deep`, `double_time` |
| Spatial | `8d`, `rotation`, `party` |
| Modulation | `tremolo`, `vibrato` |
| Vocals | `karaoke` |
| Texture | `distortion`, `soft`, `muffled`, `lofi`, `slowed_reverb`, `mono` |
| Tone (equalizer) | `bass_boost`, `bass_boost_extreme`, `treble_boost`, `pop`, `rock`, `metal`, `jazz`, `classical`, `electronic`, `vocal`, `flat` |

Some presets accept options — the bass-boost presets take a `gain`, and `8d`
takes a `rotation_hz`:

```python
fluxwave.Filters.from_preset("bass_boost", gain=0.4)  # stronger low end
fluxwave.Filters().eight_d(rotation_hz=0.3)  # faster panning
```

`Filters.from_preset` raises `ValueError` for an unknown name, with the valid
preset names listed in the message.

Manual filters:

```python
filters = (
    fluxwave.Filters()
    .set_volume(0.8)  # 80% volume
    .set_timescale(speed=1.1, pitch=1.0, rate=1.0)  # speed up 10%, keep pitch
    .set_low_pass(smoothing=20.0)  # muffle high frequencies
)
await player.set_filters(filters)  # apply the combined filters
```

Tagged filter stack:

```python
await player.add_filter(fluxwave.Filters().bass_boost(), filter_tag="bass")  # stack a filter under a tag
await player.add_filter(fluxwave.Filters().nightcore(), filter_tag="nightcore")  # stack another tagged filter

if player.has_filter("bass"):  # check if the tag is active
    await player.remove_filter("bass")  # remove just that tagged filter
```

Use tags when bot commands need to toggle effects independently. Removing
`"bass"` leaves `"nightcore"` active. Use `preload=True` to prepare filters for
future playback without sending an immediate Lavalink update when nothing is
loaded:

```python
await player.add_filter(
    fluxwave.Filters().vaporwave(),
    filter_tag="startup",
    preload=True,  # stage the filter without sending an update now
)
```

Interpolate between filter states:

```python
start = fluxwave.Filters().bass_boost()
end = fluxwave.Filters().nightcore()
mid = fluxwave.Filters.interpolate(start, end, t=0.5)  # blend halfway between the two
```
