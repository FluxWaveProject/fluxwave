# FluxWave Documentation

FluxWave is a typed, async Lavalink v4 client for Python Discord music bots.
It provides Lavalink REST/websocket transport, Discord voice integration that
works with discord.py, py-cord, nextcord, or disnake, node pooling, queueing,
filters, events, plugin helpers, autoplay, persistence, metrics, tracing, and
voice recovery tools.

```{warning}
FluxWave `0.2.0` is pre-release software. It is suitable for beta bots and
library testing, but APIs may still change before `1.0`.
```

## Install

FluxWave auto-detects any one installed Discord library (discord.py, py-cord,
nextcord, or disnake). If you already have one, just install FluxWave:

```bash
python -m pip install fluxwave
```

Starting fresh, install both together:

```bash
python -m pip install fluxwave discord.py
```

See [Getting Started](getting-started.md) for the full setup.

## Minimal Bot Flow

1. Start a Lavalink v4 server.
2. Create one or more `fluxwave.Node` objects.
3. Connect them through `fluxwave.Pool.connect`.
4. Connect Discord voice with `cls=fluxwave.FluxPlayer`.
5. Use `enqueue`, `skip`, `pause`, `resume`, `set_filters`, and queue helpers.

```python
node = fluxwave.Node(  # describe one Lavalink server
    uri="http://127.0.0.1:2333",
    password="youshallnotpass",
    user_id=bot.user.id,  # the bot's own Discord user id
)
await fluxwave.Pool.connect(nodes=[node], cache_capacity=256)  # register + connect the node(s)
```

## Guide Index

**Getting started**

- [Getting Started](getting-started.md)
- [Player Guide](guide/player.md)
- [Nodes and Pools](guide/nodes.md)

**Feature guides**

- [Examples and Commands](guide/examples.md)
- [Search and Autoplay](guide/search-autoplay.md)
- [Queues and Filters](guide/queue-filters.md)
- [Plugins](guide/plugins.md)
- [Plugin Compatibility](guide/plugin-compatibility.md)
- [Events](guide/events.md)
- [Persistence and Observability](guide/persistence-observability.md)
- [Advanced Features](guide/advanced.md)

**Reference**

- [API Reference](api/index.md)
- [API Stability](guide/api-stability.md)

**Help**

- [FAQ](guide/faq.md)
- [Troubleshooting](guide/troubleshooting.md)
- [Migration Notes](guide/migration.md)

**Contributing**

- [Testing and Release](guide/testing-release.md)
- [Hosting Documentation Online](guide/hosting.md)
- [Product and API Design](product-design.md)

```{toctree}
:caption: Getting Started
:maxdepth: 2

getting-started
guide/player
guide/nodes
```

```{toctree}
:caption: Feature Guides
:maxdepth: 2

guide/examples
guide/search-autoplay
guide/queue-filters
guide/plugins
guide/plugin-compatibility
guide/events
guide/persistence-observability
guide/advanced
```

```{toctree}
:caption: Reference
:maxdepth: 2

api/index
guide/api-stability
```

```{toctree}
:caption: Help
:maxdepth: 2

guide/faq
guide/troubleshooting
guide/migration
```

```{toctree}
:caption: Contributing
:maxdepth: 2

guide/testing-release
guide/hosting
product-design
```
