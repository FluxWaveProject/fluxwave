# FluxWave

[![CI](https://github.com/FluxWaveProject/fluxwave/actions/workflows/ci.yml/badge.svg)](https://github.com/FluxWaveProject/fluxwave/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docs](https://readthedocs.org/projects/fluxwave/badge/?version=latest)](https://fluxwave.readthedocs.io/en/latest/)
[![Typed](https://img.shields.io/badge/typing-strict-informational)](https://peps.python.org/pep-0561/)

FluxWave is a typed, async Lavalink v4 client for Python Discord music bots.
It provides the Lavalink REST and websocket client, Discord voice integration,
node pooling, queueing, filters, events, plugin helpers, autoplay, persistence,
and production-oriented recovery tools.

FluxWave is `0.2.1` (beta). It is usable in real bots today; being pre-`1.0`,
some public APIs may still change before `1.0`.

## Features

- **Async Lavalink v4** REST + websocket client, fully typed (`py.typed`).
- **Library-agnostic** — works with discord.py, py-cord, nextcord, or disnake;
  depends only on `aiohttp`.
- **Multi-node pooling** (`NodePool` / `Pool`) with health-aware selection,
  blacklist/cooldown, automatic failover and return-to-home, hot-node draining,
  and parallel multi-node search.
- **Players** — full playback controls, voice-state recovery, a tagged filter
  stack, opt-in crossfade (smooth volume fades between tracks), and a voice
  watchdog for stalled-playback recovery.
- **Queue** — history, loop modes, shuffle/move/dedupe, capacity limits, and
  serialization.
- **Filters** — equalizer, karaoke, timescale, a 30+ effect preset library
  (nightcore, 8D, slowed + reverb, lo-fi, genre EQs…), interpolation, and
  `set_filters(..., seek=True)`.
- **Search** — `ytsearch:`/`ytmsearch:`/URLs/playlists, default sources, LFU
  caching, and in-flight request coalescing.
- **Events** — typed payloads with `fluxwave_*` and Wavelink-style aliases, plus
  a raw-websocket event for debugging.
- **Plugins** — LavaSrc, LavaLyrics, SponsorBlock, and custom REST routes.
- **Lyrics** — fetch full/plain lyrics, plus `live_lyrics()` to stream synced
  lines as the track plays for karaoke-style now-playing messages.
- **Autoplay** — recommendation providers with duplicate filtering.
- **Persistence & observability** — in-memory and crash-safe on-disk state
  stores, metrics, and structured tracing.

## Comparison

This table compares built-in, publicly documented features checked on
2026-06-02. A `✅` means the project advertises or ships the feature directly;
a `❌` means it is not advertised as a built-in feature in the linked public
docs/README and may still be possible with custom bot code.

| Feature | FluxWave | Wavelink | Pomice | Mafic | Lavalink.py |
| --- | :---: | :---: | :---: | :---: | :---: |
| Lavalink wrapper/client | ✅ | ✅ | ✅ | ✅ | ✅ |
| Supports discord.py, py-cord, nextcord, and disnake | ✅ | ❌ | ❌ | ✅ | ✅ |
| Typed public API | ✅ | ✅ | ❌ | ✅ | ❌ |
| Node pool / multi-node management | ✅ | ✅ | ✅ | ✅ | ✅ |
| Automatic player failover and return-to-home recovery | ✅ | ❌ | ❌ | ❌ | ✅ |
| Built-in queue | ✅ | ✅ | ✅ | ❌ | ✅ |
| Advanced queue controls: history, move, dedupe, capacity | ✅ | ❌ | ❌ | ❌ | ❌ |
| Autoplay / recommendation mode | ✅ | ✅ | ❌ | ❌ | ❌ |
| 30+ named filter presets | ✅ | ❌ | ❌ | ❌ | ❌ |
| Tagged filters / remove by tag | ✅ | ❌ | ✅ | ❌ | ❌ |
| In-flight duplicate search coalescing | ✅ | ❌ | ❌ | ❌ | ❌ |
| Parallel multi-node search helper | ✅ | ❌ | ❌ | ❌ | ❌ |
| Source routing by query glob | ✅ | ❌ | ❌ | ❌ | ❌ |
| Crossfade / smooth fade-volume helper | ✅ | ❌ | ❌ | ❌ | ❌ |
| Live synced lyrics iterator | ✅ | ❌ | ❌ | ❌ | ❌ |
| On-disk player state persistence | ✅ | ❌ | ❌ | ❌ | ❌ |
| Voice watchdog for stalled-audio recovery | ✅ | ❌ | ❌ | ❌ | ❌ |
| Built-in app metrics counters and trace ring buffer | ✅ | ❌ | ❌ | ❌ | ❌ |

Sources checked: [Wavelink](https://github.com/PythonistaGuild/Wavelink),
[Pomice](https://pypi.org/project/pomice/),
[Mafic](https://github.com/ooliver1/mafic), and
[Lavalink.py](https://github.com/devoxin/Lavalink.py), plus the
[official Lavalink client list](https://lavalink.dev/clients.html).

## Documentation

Full documentation is hosted at **[fluxwave.readthedocs.io](https://fluxwave.readthedocs.io)**
(source in [`docs/`](docs/)). Good starting points:

- [Getting Started](https://fluxwave.readthedocs.io/en/latest/getting-started.html) — your first bot, step by step.
- [Basic Bot](examples/basic_bot.py) and [Advanced Bot](examples/advanced_bot.py) — runnable examples.
- [API Reference](https://fluxwave.readthedocs.io/en/latest/api/index.html) · [FAQ](https://fluxwave.readthedocs.io/en/latest/guide/faq.html) · [Migration](https://fluxwave.readthedocs.io/en/latest/guide/migration.html) · [Changelog](CHANGELOG.md)

The [`docs/guide/`](https://fluxwave.readthedocs.io/en/latest/) folder covers players, nodes & pools, search &
autoplay, queues & filters, events, plugins, persistence & observability, and
troubleshooting.

## Requirements

- Python `3.11` or newer.
- One supported Discord library, which you install yourself: `discord.py` `2.4+`,
  `py-cord` `2.4+`, `nextcord` `2.6+`, or `disnake` `2.9+`. Like mafic and
  lavalink.py, FluxWave does not depend on a specific one — it detects whichever
  is installed.
- `aiohttp`.
- A Lavalink v4 server.

## Installation

FluxWave needs two things: FluxWave itself, plus **any one** Discord library
(discord.py, py-cord, nextcord, or disnake — your choice). FluxWave auto-detects
whichever one is installed, so there is nothing to configure.

**If you already have a Discord library installed**, just install FluxWave:

```bash
python -m pip install fluxwave
```

**If you are starting fresh**, install FluxWave and a Discord library together
(discord.py shown here — swap in `py-cord`, `nextcord`, or `disnake` if you
prefer):

```bash
python -m pip install fluxwave discord.py
```

Or pull a Discord library in automatically with an extra
(`discordpy`, `pycord`, `nextcord`, or `disnake`):

```bash
python -m pip install "fluxwave[discordpy]"
```

That is the whole setup. Once a Discord library is importable, `import fluxwave`
just works.

> **Why isn't the Discord library bundled?** FluxWave itself depends only on
> `aiohttp`. It deliberately does not install a Discord library for you, because
> discord.py and py-cord share the same `discord` import name — bundling one would
> overwrite and break users of the other. Bringing your own library (the same
> approach as mafic and lavalink.py) keeps every install clash-free.

If you happen to have **more than one** supported library installed at once, tell
FluxWave which to use with the `FLUXWAVE_DISCORD_LIBRARY` environment variable
(`discord`, `nextcord`, or `disnake`).

For local development:

```bash
git clone https://github.com/FluxWaveProject/fluxwave.git
cd fluxwave
python -m pip install -e ".[dev,docs]"
```

## Quick Start

Create a Lavalink node and use `FluxPlayer` as the Discord voice client:

```python
import os

import discord
from discord.ext import commands

import fluxwave

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())


@bot.event
async def setup_hook() -> None:
    node = fluxwave.Node(  # describe one Lavalink server
        uri=os.getenv("LAVALINK_URI", "http://127.0.0.1:2333"),
        password=os.getenv("LAVALINK_PASSWORD", "youshallnotpass"),
        user_id=bot.user.id,  # the bot's own Discord user id
        identifier="main",
    )
    await fluxwave.Pool.connect(nodes=[node], cache_capacity=256)  # register + connect the node(s)


@bot.command()
async def play(ctx: commands.Context, *, query: str) -> None:
    if ctx.author.voice is None or ctx.author.voice.channel is None:  # caller must be in a voice channel
        await ctx.reply("Join a voice channel first.")
        return

    player = ctx.voice_client  # existing voice connection, if any
    if not isinstance(player, fluxwave.FluxPlayer):
        player = await ctx.author.voice.channel.connect(cls=fluxwave.FluxPlayer)  # join voice as a FluxPlayer

    result = await player.enqueue(query)  # search and add tracks to the queue
    if result.added == 0:  # nothing matched the query
        await ctx.reply("No tracks found.")
        return

    if player.current is None:  # nothing playing yet
        await player.skip(force=True)  # start the first queued track

    await ctx.reply(result.message)  # human-friendly summary of what was added


bot.run(os.environ["DISCORD_TOKEN"])
```

See [`examples/basic_bot.py`](examples/basic_bot.py) for a fuller command set.
See [`examples/advanced_bot.py`](examples/advanced_bot.py) for autoplay,
filters, lyrics, persistence, metrics, and watchdog usage.

## Core Concepts

### Node

`Node` represents one Lavalink server. It owns REST, websocket, authentication,
session resume, route planner helpers, known Lavalink players, live Discord
players, and optional node-local search caching.

Read more: [Nodes and Pools](https://fluxwave.readthedocs.io/en/latest/guide/nodes.html), [API Reference: Node API](https://fluxwave.readthedocs.io/en/latest/api/index.html#node-api).

```python
node = fluxwave.Node(  # describe one Lavalink server
    uri="http://127.0.0.1:2333",
    password="youshallnotpass",
    user_id=1234567890,  # the bot's own Discord user id
    identifier="main",
    search_cache_capacity=256,  # per-node search result cache size
)
await node.connect()  # open REST + websocket to Lavalink
```

### Pool

`NodePool` is instance-based. `Pool` is the global facade for bot code that
prefers Wavelink-style helpers.

Read more: [Nodes and Pools](https://fluxwave.readthedocs.io/en/latest/guide/nodes.html), [API Reference: Node API](https://fluxwave.readthedocs.io/en/latest/api/index.html#node-api).

```python
await fluxwave.Pool.connect(nodes=[node], cache_capacity=512)  # register + connect the node(s)
tracks = await fluxwave.Pool.search("never gonna give you up")  # search the default source
```

For multiple nodes:

```python
results = await fluxwave.Pool.search_all("ytsearch:lofi")  # search every node in parallel
degraded = fluxwave.Pool.get_degraded_nodes()  # nodes currently unhealthy
await fluxwave.Pool.drain(old_node, cooldown=300)  # stop using a node, cooldown in seconds
```

### Player

`FluxPlayer` is a Discord voice protocol (compatible with discord.py, py-cord,
nextcord, and disnake). It handles Discord voice updates, sends voice state to
Lavalink, owns queues, controls playback, dispatches public events, and can
persist/restore playback state.

Read more: [Player Guide](https://fluxwave.readthedocs.io/en/latest/guide/player.html), [API Reference: Player API](https://fluxwave.readthedocs.io/en/latest/api/index.html#player-api).

```python
player = await voice_channel.connect(cls=fluxwave.FluxPlayer)  # join voice as a FluxPlayer
await player.enqueue("ytsearch:lofi beats")  # search and add tracks to the queue
await player.skip(force=True)  # advance to the next track now
await player.set_volume(80)  # volume as a percentage
await player.set_filters(fluxwave.Filters().nightcore(), seek=True)  # nightcore effect, re-seek so it applies now
```

### Queue

Read more: [Queues and Filters](https://fluxwave.readthedocs.io/en/latest/guide/queue-filters.html), [API Reference: Queue API](https://fluxwave.readthedocs.io/en/latest/api/index.html#queue-api).

```python
player.queue.put(track)  # add a track to the end of the queue
player.queue.move(4, 0)  # move the track at index 4 to the front
player.queue.dedupe()  # remove duplicate tracks
next_ten = player.queue.clear_next(10)  # remove and return the next 10 tracks
duration_ms = player.queue.total_duration  # total queue length in milliseconds
next_track = player.queue.get(bypass_loop=True)  # pop next track, ignoring loop mode
snapshot = player.queue.to_raw_data()  # serialize the queue for persistence
```

### Events

FluxWave dispatches both FluxWave-prefixed and Wavelink-style Discord event
names for easier migration:

Read more: [Events](https://fluxwave.readthedocs.io/en/latest/guide/events.html), [API Reference: Events](https://fluxwave.readthedocs.io/en/latest/api/index.html#events).

```python
@bot.event
async def on_fluxwave_track_start(event: fluxwave.TrackStartEvent) -> None:
    print(f"Started {event.track.title} in guild {event.guild_id}")


@fluxwave.listen("track_end")
async def on_track_end(event: fluxwave.TrackEndEvent) -> None:
    print(event.reason)
```

### Persistence

Read more: [Persistence and Observability](https://fluxwave.readthedocs.io/en/latest/guide/persistence-observability.html).

```python
store = fluxwave.MemoryStore()  # in-memory state store
state = player.save_state(extra={"source": "shutdown"})  # snapshot player + queue
await store.save(player.guild.id, state)  # persist keyed by guild id

restored = await store.load(player.guild.id)  # load any saved snapshot
if restored is not None:
    await player.restore_state(restored)  # rebuild queue and playback
```

### Watchdog

Read more: [Persistence and Observability](https://fluxwave.readthedocs.io/en/latest/guide/persistence-observability.html#voice-watchdog).

```python
watchdog = player.start_watchdog(  # monitor for stalled playback
    fluxwave.WatchdogConfig(check_interval=5.0, stagnation_threshold=12.0)  # poll every 5s, recover after 12s stalled
)
```

## Common Bot Commands

FluxWave is not a command framework, but it is designed to make common commands
simple:

```python
await player.enqueue("song name")  # search and add to the queue
await player.play_next("song name")  # queue a track to play next
await player.skip(force=True)  # advance to the next track now
await player.stop(force=True)  # stop and clear the queue
await player.stop(clear_queue=False)  # stop current track but keep queue
await player.set_filters(fluxwave.Filters().bass_boost(), seek=True)  # bass boost, re-seek so it applies now
lyrics = await player.current_lyrics()  # fetch lyrics for the current track
state = player.save_state()  # snapshot player + queue
```

## Security Notes

- Never hardcode Discord bot tokens in examples or committed code.
- Read tokens/passwords from environment variables or a secret manager.
- Treat Lavalink plugin endpoints as trusted-server APIs; validate user input
  before passing it to custom routes.

## Lavalink Configuration

FluxWave expects a Lavalink v4 server reachable over HTTP or HTTPS.

Common environment variables used by examples and integration tests:

```bash
export DISCORD_TOKEN="your bot token"
export LAVALINK_URI="http://127.0.0.1:2333"
export LAVALINK_HOST="127.0.0.1"
export LAVALINK_PORT="2333"
export LAVALINK_PASSWORD="youshallnotpass"
export LAVALINK_SECURE="false"
```

## Development

```bash
python -m pip install -e ".[dev,docs]"
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest
```

Run integration tests against your own Lavalink server:

```bash
LAVALINK_HOST=127.0.0.1 \
LAVALINK_PORT=2333 \
LAVALINK_PASSWORD=youshallnotpass \
LAVALINK_SECURE=false \
.venv/bin/python -m pytest -m integration tests/test_integration_lavalink.py
```

Build docs locally:

```bash
.venv/bin/python -m sphinx -b html docs docs/_build/html
```

Build a wheel/sdist locally:

```bash
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

## Project Status

FluxWave is beta-quality and pre-`1.0`. On top of a heavy unit-test suite, it has
been validated end-to-end against live Discord and Lavalink — playback,
multi-node failover, every plugin integration, and an extended stress soak.
Public APIs may still change before `1.0`.

## Support

- Bugs and feature requests: [GitHub Issues](https://github.com/FluxWaveProject/fluxwave/issues)
- Before opening an issue, see [Troubleshooting](https://fluxwave.readthedocs.io/en/latest/guide/troubleshooting.html) and the [FAQ](https://fluxwave.readthedocs.io/en/latest/guide/faq.html).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the dev
setup and the lint/type/test checks. Security issues: see [SECURITY.md](SECURITY.md).

## License

FluxWave is distributed under the MIT License. See [`LICENSE`](LICENSE).
