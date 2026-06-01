"""Basic Discord music bot using FluxWave.

Environment:
    DISCORD_TOKEN       Discord bot token.
    LAVALINK_URI        Lavalink base URI, e.g. http://127.0.0.1:2333.
    LAVALINK_PASSWORD   Lavalink password.

Run:
    python examples/basic_bot.py
"""

from __future__ import annotations

import os

import discord
from discord.ext import commands

import fluxwave


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook() -> None:
    node = fluxwave.Node(
        uri=os.getenv("LAVALINK_URI", "http://127.0.0.1:2333"),
        password=required_env("LAVALINK_PASSWORD"),
        user_id=bot.user.id,
        identifier="main",
        search_cache_capacity=256,
    )
    await fluxwave.Pool.connect(nodes=[node], cache_capacity=512)


@bot.event
async def on_ready() -> None:
    assert bot.user is not None
    print(f"Logged in as {bot.user} | FluxWave {fluxwave.__version__}")


@bot.event
async def on_fluxwave_track_start(event: fluxwave.TrackStartEvent) -> None:
    print(f"Started: {event.track.title} in guild {event.guild_id}")


@bot.event
async def on_fluxwave_track_end(event: fluxwave.TrackEndEvent) -> None:
    print(f"Ended: {event.track.title} ({event.reason})")


async def get_player(ctx: commands.Context) -> fluxwave.FluxPlayer | None:
    voice = getattr(ctx.author, "voice", None)
    channel = getattr(voice, "channel", None)
    if channel is None:
        await ctx.reply("Join a voice channel first.")
        return None

    if isinstance(ctx.voice_client, fluxwave.FluxPlayer):
        return ctx.voice_client

    return await channel.connect(cls=fluxwave.FluxPlayer)


@bot.command()
async def join(ctx: commands.Context) -> None:
    player = await get_player(ctx)
    if player is not None:
        await ctx.reply(f"Connected to {player.channel}.")


@bot.command()
async def play(ctx: commands.Context, *, query: str) -> None:
    player = await get_player(ctx)
    if player is None:
        return

    result = await player.enqueue(query)
    if result.added == 0:
        await ctx.reply("No tracks found.")
        return

    if player.current is None:
        await player.skip(force=True)

    await ctx.reply(result.message)


@bot.command()
async def playnext(ctx: commands.Context, *, query: str) -> None:
    player = await get_player(ctx)
    if player is None:
        return

    result = await player.play_next(query)
    await ctx.reply(result.message if result.added else "No tracks found.")


@bot.command()
async def skip(ctx: commands.Context) -> None:
    player = ctx.voice_client
    if not isinstance(player, fluxwave.FluxPlayer):
        await ctx.reply("Not connected.")
        return

    skipped = await player.skip(force=True)
    await ctx.reply(f"Skipped {skipped.title}." if skipped else "Nothing to skip.")


@bot.command()
async def stop(ctx: commands.Context) -> None:
    player = ctx.voice_client
    if not isinstance(player, fluxwave.FluxPlayer):
        await ctx.reply("Not connected.")
        return

    await player.stop(force=True)
    await ctx.reply("Stopped playback and cleared the queue and autoplay recommendations.")


@bot.command()
async def pause(ctx: commands.Context) -> None:
    player = ctx.voice_client
    if isinstance(player, fluxwave.FluxPlayer):
        await player.pause()
        await ctx.reply("Paused.")


@bot.command()
async def resume(ctx: commands.Context) -> None:
    player = ctx.voice_client
    if isinstance(player, fluxwave.FluxPlayer):
        await player.resume()
        await ctx.reply("Resumed.")


@bot.command()
async def volume(ctx: commands.Context, value: int) -> None:
    player = ctx.voice_client
    if isinstance(player, fluxwave.FluxPlayer):
        await player.set_volume(value)
        await ctx.reply(f"Volume set to {player.volume}.")


@bot.command(name="queue")
async def queue_command(ctx: commands.Context) -> None:
    player = ctx.voice_client
    if not isinstance(player, fluxwave.FluxPlayer):
        await ctx.reply("Not connected.")
        return

    if not player.queue:
        await ctx.reply("Queue is empty.")
        return

    lines = [
        f"{index}. {track.title} - {track.author}"
        for index, track in enumerate(player.queue[:10], start=1)
    ]
    await ctx.reply("\n".join(lines))


@bot.command()
async def now(ctx: commands.Context) -> None:
    player = ctx.voice_client
    if not isinstance(player, fluxwave.FluxPlayer) or player.current is None:
        await ctx.reply("Nothing is playing.")
        return

    track = player.current
    await ctx.reply(f"Now playing: {track.title} - {track.author} [{track.length_display}]")


@bot.command()
async def leave(ctx: commands.Context) -> None:
    player = ctx.voice_client
    if isinstance(player, fluxwave.FluxPlayer):
        await player.disconnect(force=True)
        await ctx.reply("Disconnected.")


if __name__ == "__main__":
    bot.run(required_env("DISCORD_TOKEN"))
