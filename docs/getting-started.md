# Getting Started

This guide shows the shortest path from a running Lavalink server to a Discord
music bot using FluxWave.

## 1. Install

FluxWave works with any one Discord library — discord.py, py-cord, nextcord, or
disnake — and auto-detects whichever is installed.

If you already have a Discord library installed, just add FluxWave:

```bash
python -m pip install fluxwave
```

Starting fresh? Install FluxWave and a Discord library together (swap `discord.py`
for `py-cord`, `nextcord`, or `disnake` if you prefer):

```bash
python -m pip install fluxwave discord.py
```

FluxWave itself depends only on `aiohttp`; it does not bundle a Discord library,
so installs never clash with the one you already use. If more than one supported
library is installed, set `FLUXWAVE_DISCORD_LIBRARY` (`discord`, `nextcord`, or
`disnake`) to pick one.

For development:

```bash
python -m pip install -e ".[dev,docs]"
```

## 2. Configure Environment

```bash
export DISCORD_TOKEN="your bot token"
export LAVALINK_URI="http://127.0.0.1:2333"
export LAVALINK_PASSWORD="youshallnotpass"
```

For integration tests you can also use:

```bash
export LAVALINK_HOST="127.0.0.1"
export LAVALINK_PORT="2333"
export LAVALINK_SECURE="false"
```

## 3. Connect a Node

```python
@bot.event
async def setup_hook() -> None:
    node = fluxwave.Node(  # describe one Lavalink server
        uri=os.environ["LAVALINK_URI"],
        password=os.environ["LAVALINK_PASSWORD"],
        user_id=bot.user.id,  # the bot's own Discord user id
        identifier="main",
    )
    await fluxwave.Pool.connect(nodes=[node], cache_capacity=256)  # register + connect the node(s)
```

`Pool.connect(nodes=[...])` is the global helper style. If your app needs
explicit ownership, create and keep a `NodePool` instance instead.

## 4. Connect Voice

```python
player = ctx.voice_client  # existing voice connection, if any
if not isinstance(player, fluxwave.FluxPlayer):
    player = await ctx.author.voice.channel.connect(cls=fluxwave.FluxPlayer)  # join voice as a FluxPlayer
```

## 5. Queue and Play

```python
result = await player.enqueue("never gonna give you up")  # search and add tracks to the queue
if result.added == 0:  # nothing matched the query
    await ctx.reply("No tracks found.")
    return

if player.current is None:  # nothing playing yet
    await player.skip(force=True)  # start the first queued track
```

`enqueue` queues tracks and returns an `EnqueueResult` with `added`, `tracks`,
`playlist`, `first_track`, `source`, and a command-friendly `message`.

## 6. Listen for Events

```python
@bot.event
async def on_fluxwave_track_start(event: fluxwave.TrackStartEvent) -> None:
    print(f"Started {event.track.title}")
```

FluxWave also dispatches `wavelink_*` aliases to make migration easier.

## 7. Run the Example

```bash
DISCORD_TOKEN="..." \
LAVALINK_URI="http://127.0.0.1:2333" \
LAVALINK_PASSWORD="youshallnotpass" \
python examples/basic_bot.py
```
