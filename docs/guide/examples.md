# Examples and Commands

FluxWave ships prefix-command examples, and this page shows how to adapt the
same patterns to slash commands and cogs.

## Quick Links

- [Prefix Examples](#prefix-examples)
- [Slash Command Example](#slash-command-example)
- [Cog Structure](#cog-structure)
- [Basic Bot Commands](#basic-bot-commands)
- [Advanced Bot Commands](#advanced-bot-commands)

## Prefix Examples

- [`examples/basic_bot.py`](../../examples/basic_bot.py): small beginner bot.
- [`examples/advanced_bot.py`](../../examples/advanced_bot.py): large command
  sample covering advanced FluxWave features.

Both examples use `discord.ext.commands` prefix commands because they are easy
to read and copy. The same FluxWave calls work inside slash commands and cogs.

## Slash Command Example

```python
import os

import discord
from discord import app_commands

import fluxwave


class MusicClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True  # required so FluxWave can track voice connections
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        node = fluxwave.Node(  # describe one Lavalink server to connect to
            uri=os.getenv("LAVALINK_URI", "http://127.0.0.1:2333"),
            password=os.getenv("LAVALINK_PASSWORD", "youshallnotpass"),
            user_id=self.user.id,  # the bot's own Discord user id
            identifier="main",
            search_cache_capacity=256,  # cache up to 256 search results on this node
        )
        await fluxwave.Pool.connect(nodes=[node], cache_capacity=512)  # register nodes with the pool
        await self.tree.sync()


client = MusicClient()


async def ensure_player(interaction: discord.Interaction) -> fluxwave.FluxPlayer | None:
    if interaction.guild is None:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return None

    user = interaction.user
    voice = getattr(user, "voice", None)
    channel = getattr(voice, "channel", None)
    if channel is None:
        await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
        return None

    player = interaction.guild.voice_client
    if isinstance(player, fluxwave.FluxPlayer):  # already connected with a FluxPlayer
        return player

    return await channel.connect(cls=fluxwave.FluxPlayer)  # connect using FluxWave's player class


@client.tree.command(name="play", description="Queue a song or playlist.")
async def play(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer()

    player = await ensure_player(interaction)
    if player is None:
        return

    result = await player.enqueue(query)  # search and add matching tracks to the queue
    if result.empty:  # query matched nothing
        await interaction.followup.send("No tracks found.")
        return

    if player.current is None:  # nothing playing yet
        await player.skip(force=True)  # start the first queued track

    await interaction.followup.send(result.message)  # human-readable summary of what was queued


@client.tree.command(name="skip", description="Skip the current track.")
async def skip(interaction: discord.Interaction) -> None:
    player = interaction.guild.voice_client if interaction.guild else None
    if not isinstance(player, fluxwave.FluxPlayer):  # bot not playing in this guild
        await interaction.response.send_message("Not connected.", ephemeral=True)
        return

    skipped = await player.skip(force=True)  # returns the track that was skipped, if any
    message = f"Skipped {skipped.title}." if skipped else "Nothing to skip."
    await interaction.response.send_message(message)


client.run(os.environ["DISCORD_TOKEN"])
```

## Cog Structure

For real bots, keep FluxWave setup in one place and commands in a cog:

```text
bot.py
cogs/
  music.py
```

`bot.py`:

```python
import os

import discord
from discord.ext import commands

import fluxwave


class MyBot(commands.Bot):
    async def setup_hook(self) -> None:
        node = fluxwave.Node(  # describe the Lavalink server
            uri=os.getenv("LAVALINK_URI", "http://127.0.0.1:2333"),
            password=os.getenv("LAVALINK_PASSWORD", "youshallnotpass"),
            user_id=self.user.id,  # the bot's own Discord user id
            identifier="main",
        )
        await fluxwave.Pool.connect(nodes=[node], cache_capacity=512)  # register nodes with the pool
        await self.load_extension("cogs.music")  # load the commands cog


intents = discord.Intents.default()
intents.message_content = True  # needed to read prefix command text
intents.voice_states = True  # needed for voice connection tracking

bot = MyBot(command_prefix="!", intents=intents)
bot.run(os.environ["DISCORD_TOKEN"])
```

`cogs/music.py`:

```python
from discord.ext import commands

import fluxwave


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def ensure_player(self, ctx: commands.Context) -> fluxwave.FluxPlayer | None:
        voice = getattr(ctx.author, "voice", None)
        channel = getattr(voice, "channel", None)
        if channel is None:
            await ctx.reply("Join a voice channel first.")
            return None

        if isinstance(ctx.voice_client, fluxwave.FluxPlayer):  # already connected
            return ctx.voice_client

        return await channel.connect(cls=fluxwave.FluxPlayer)  # connect using FluxWave's player class

    @commands.command()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        player = await self.ensure_player(ctx)
        if player is None:
            return

        result = await player.enqueue(query)  # search and add matching tracks to the queue
        if player.current is None:  # nothing playing yet
            await player.skip(force=True)  # start the first queued track
        await ctx.reply(result.message if result.added else "No tracks found.")  # report the outcome


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
```

## Basic Bot Commands

`examples/basic_bot.py` includes:

| Command | Purpose |
| --- | --- |
| `!join` | Connect to the caller's voice channel. |
| `!play <query>` | Queue a track or playlist and start playback if idle. |
| `!playnext <query>` | Queue a track next. |
| `!skip` | Skip the current track. |
| `!stop` | Stop playback and clear the queue. |
| `!pause` | Pause playback. |
| `!resume` | Resume playback. |
| `!volume <value>` | Set player volume. |
| `!queue` | Show the next queued tracks. |
| `!now` | Show the current track. |
| `!leave` | Disconnect from voice. |

## Advanced Bot Commands

`examples/advanced_bot.py` includes:

| Area | Commands |
| --- | --- |
| Connection | `join`, `disconnect` (`leave`, `dc`) |
| Playback | `play`, `playnow`, `playnext`, `pause`, `resume`, `seek`, `volume` (`vol`), `skip`, `stop`, `now` |
| Search | `search`, `searchall`, `cachetest` |
| Queue | `queue` (`q`), `shuffle`, `qmove`, `qremove`, `qdedupe`, `qclear`, `qfind`, `loop`, `rawqueue` |
| Filters | `bass`, `nightcore`, `vaporwave`, `lowpass`, `clearfilters` |
| Plugins | `lyrics`, `lyricline`, `lavasrc`, `sponsor`, `customget` |
| Autoplay | `autoplay`, `populateauto` |
| Persistence | `save`, `restore` |
| Reliability | `watchdog` |
| Observability | `metrics`, `resetmetrics`, `trace` |
| Nodes | `nodeinfo`, `nodestats`, `poolinfo`, `routeplanner`, `freeroute`, `router`, `reconnectnode` |
| Metadata | `extras` |
| Help | `helpadvanced` |
