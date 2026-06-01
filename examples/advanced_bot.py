"""Advanced Discord music bot using FluxWave.

This example is intentionally feature-rich so users can copy specific command
patterns into their own bots. It demonstrates:

- command-friendly playback helpers
- queue tools and loop modes
- filters and presets
- LavaSrc, LavaLyrics, SponsorBlock, and custom plugin routes
- autoplay and recommendation population
- multi-node pooling with health-aware selection, automatic failover/migration,
  hot-node draining, and per-player node switching
- node stats, route planner, and source routing helpers
- persistence, metrics, tracing, watchdog, and public events

Environment:
    DISCORD_TOKEN         Discord bot token.
    LAVALINK_URI          Lavalink base URI, e.g. http://127.0.0.1:2333.
    LAVALINK_PASSWORD     Lavalink password.
    LAVALINK_EXTRA_NODES  Optional. Extra nodes for a multi-node pool, as a
                          comma-separated list of "identifier|uri|password", e.g.
                          "eu|http://eu:2333|pw1,us|http://us:2333|pw2".

Run:
    python examples/advanced_bot.py
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable

import discord
from discord.ext import commands

import fluxwave

DEFAULT_VOLUME = 100
QUEUE_PREVIEW_LIMIT = 10
MESSAGE_LIMIT = 1900

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    description="Advanced FluxWave example bot",
    intents=intents,
)
store = fluxwave.MemoryStore()
watchdogs: dict[int, fluxwave.VoiceWatchdog] = {}


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def require_guild(ctx: commands.Context[commands.Bot]) -> discord.Guild | None:
    if ctx.guild is None:
        return None
    return ctx.guild


def format_track(track: fluxwave.Track) -> str:
    return f"{track.title} - {track.author} [{track.length_display}]"


def short_json(payload: object, *, limit: int = MESSAGE_LIMIT) -> str:
    text = json.dumps(payload, indent=2, default=str)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return f"```json\n{text}\n```"


async def send_lines(
    ctx: commands.Context[commands.Bot],
    lines: Iterable[str],
    *,
    empty: str = "Nothing to show.",
) -> None:
    text = "\n".join(lines)
    await ctx.reply(text[:MESSAGE_LIMIT] if text else empty)


def active_player(ctx: commands.Context[commands.Bot]) -> fluxwave.FluxPlayer | None:
    player = ctx.voice_client
    return player if isinstance(player, fluxwave.FluxPlayer) else None


async def ensure_player(ctx: commands.Context[commands.Bot]) -> fluxwave.FluxPlayer | None:
    voice = getattr(ctx.author, "voice", None)
    channel = getattr(voice, "channel", None)
    if channel is None:
        await ctx.reply("Join a voice channel first.")
        return None

    player = active_player(ctx)
    if player is None:
        player = await channel.connect(cls=fluxwave.FluxPlayer)
        configure_player(player)
    elif player.channel != channel:
        await player.move_to(channel)

    return player


def configure_player(player: fluxwave.FluxPlayer) -> None:
    player.auto_pause_on_empty = True
    player.auto_resume_on_member_join = True
    player.auto_disconnect = True
    player.voice_empty_timeout = 90
    player.inactive_timeout = 180
    player.inactive_channel_tokens = 2
    player.autoplay = fluxwave.AutoPlayMode.DISABLED

    guild_id = player.guild.id
    if guild_id not in watchdogs:
        watchdogs[guild_id] = player.start_watchdog(
            fluxwave.WatchdogConfig(
                check_interval=5,
                stagnation_threshold=12,
                max_strikes=3,
            )
        )


def node_specs() -> list[tuple[str, str, str]]:
    """Return (identifier, uri, password) for every Lavalink node to connect.

    The primary node comes from LAVALINK_URI / LAVALINK_PASSWORD. Add more nodes
    for a multi-node pool via LAVALINK_EXTRA_NODES, a comma-separated list of
    "identifier|uri|password" entries.
    """

    specs = [("main", env("LAVALINK_URI", "http://127.0.0.1:2333"), env("LAVALINK_PASSWORD"))]
    for raw in (part.strip() for part in os.getenv("LAVALINK_EXTRA_NODES", "").split(",")):
        if not raw:
            continue
        fields = [field.strip() for field in raw.split("|", 2)]
        if len(fields) != 3:
            msg = f"Invalid LAVALINK_EXTRA_NODES entry {raw!r}; expected 'identifier|uri|password'."
            raise RuntimeError(msg)
        specs.append((fields[0], fields[1], fields[2]))
    return specs


@bot.event
async def setup_hook() -> None:
    assert bot.user is not None
    fluxwave.tracer.enable()
    fluxwave.Pool.cache(512)  # shared LFU search cache for the whole pool

    connected: list[str] = []
    for identifier, uri, password in node_specs():
        node = fluxwave.Node(
            uri=uri,
            password=password,
            user_id=bot.user.id,
            identifier=identifier,
            resume_timeout=60,
            request_timeout=15,
            search_cache_capacity=512,
            inactive_player_timeout=180,
            inactive_channel_tokens=2,
        )
        try:
            await fluxwave.Pool.connect(node)  # add + connect this node to the default pool
            connected.append(identifier)
        except Exception as exc:  # keep starting even if one node is unreachable
            print(f"Node {identifier!r} failed to connect: {exc}")

    # With 2+ nodes connected, the pool load-balances new players across them and
    # automatically migrates live players off a node that fails (and returns them
    # when it recovers). See the !switchnode, !drainnode, and !failover commands.
    print(f"Connected Lavalink node(s): {', '.join(connected) or 'none'}")


@bot.event
async def on_ready() -> None:
    assert bot.user is not None
    print(f"Logged in as {bot.user} | FluxWave {fluxwave.__version__}")


@bot.event
async def on_command_error(
    ctx: commands.Context[commands.Bot],
    error: commands.CommandError,
) -> None:
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(f"Missing argument: `{error.param.name}`.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.reply(f"Bad argument: {error}.")
        return
    if isinstance(error, commands.CommandNotFound):
        return

    original = getattr(error, "original", error)
    await ctx.reply(f"{type(original).__name__}: {original}")


@bot.event
async def on_fluxwave_track_start(event: fluxwave.TrackStartEvent) -> None:
    print(f"[track_start] guild={event.guild_id} track={event.track.title}")


@bot.event
async def on_fluxwave_track_end(event: fluxwave.TrackEndEvent) -> None:
    print(f"[track_end] guild={event.guild_id} reason={event.reason}")


@bot.event
async def on_fluxwave_track_exception(event: fluxwave.TrackExceptionEvent) -> None:
    print(f"[track_exception] guild={event.guild_id} exception={event.exception}")


@bot.event
async def on_fluxwave_inactive_player(event: fluxwave.InactivePlayerEvent) -> None:
    print(f"[inactive_player] guild={event.guild_id}")


@bot.command()
async def join(ctx: commands.Context[commands.Bot]) -> None:
    player = await ensure_player(ctx)
    if player is not None:
        await ctx.reply(f"Connected to {player.channel}.")


@bot.command(aliases=["leave", "dc"])
async def disconnect(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return

    watchdog = watchdogs.pop(player.guild.id, None)
    if watchdog is not None:
        watchdog.stop()
    await player.disconnect(force=True)
    await ctx.reply("Disconnected.")


@bot.command()
async def play(ctx: commands.Context[commands.Bot], *, query: str) -> None:
    player = await ensure_player(ctx)
    if player is None:
        return

    result = await player.enqueue(query, limit=100)
    if result.empty:
        await ctx.reply("No tracks found.")
        return

    if player.current is None:
        await player.skip(force=True)

    await ctx.reply(result.message)


@bot.command()
async def playnow(ctx: commands.Context[commands.Bot], *, query: str) -> None:
    player = await ensure_player(ctx)
    if player is None:
        return

    result = await player.play_search(query)
    await ctx.reply(result.message if result.added else "No tracks found.")


@bot.command()
async def playnext(ctx: commands.Context[commands.Bot], *, query: str) -> None:
    player = await ensure_player(ctx)
    if player is None:
        return

    result = await player.play_next(query)
    await ctx.reply(result.message if result.added else "No tracks found.")


@bot.command()
async def search(ctx: commands.Context[commands.Bot], *, query: str) -> None:
    results = await fluxwave.Pool.search(query)
    if isinstance(results, fluxwave.Playlist):
        await ctx.reply(f"Playlist: {results.name} ({len(results.tracks)} tracks)")
        return

    await send_lines(
        ctx,
        (f"{index}. {format_track(track)}" for index, track in enumerate(results[:10], 1)),
        empty="No tracks found.",
    )


@bot.command()
async def searchall(ctx: commands.Context[commands.Bot], *, query: str) -> None:
    results = await fluxwave.Pool.search_all(query)
    lines = [f"{result.load_type.value}: {len(result.tracks)} tracks" for result in results]
    await send_lines(ctx, lines, empty="No nodes returned tracks.")


@bot.command(name="queue", aliases=["q"])
async def queue_command(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return

    lines: list[str] = []
    if player.current is not None:
        lines.append(f"Now: {format_track(player.current)}")
    lines.extend(
        f"{index}. {format_track(track)}"
        for index, track in enumerate(player.queue[:QUEUE_PREVIEW_LIMIT], 1)
    )
    lines.append(f"Queued: {len(player.queue)} | Duration: {player.queue.total_duration // 1000}s")
    await send_lines(ctx, lines, empty="Queue is empty.")


@bot.command()
async def shuffle(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    player.queue.shuffle()
    await ctx.reply("Queue shuffled.")


@bot.command()
async def qmove(ctx: commands.Context[commands.Bot], source: int, destination: int) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    moved = player.queue.move(source - 1, destination - 1)
    await ctx.reply(f"Moved: {format_track(moved)}")


@bot.command()
async def qremove(ctx: commands.Context[commands.Bot], index: int) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    removed = player.queue[index - 1]
    player.queue.delete(index - 1)
    await ctx.reply(f"Removed: {format_track(removed)}")


@bot.command()
async def qdedupe(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    removed = player.queue.dedupe()
    await ctx.reply(f"Removed {removed} duplicate track(s).")


@bot.command()
async def qclear(ctx: commands.Context[commands.Bot], count: int | None = None) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    removed = player.queue.clear_next(count) if count is not None else player.queue.drain()
    await ctx.reply(f"Removed {len(removed)} queued track(s).")


@bot.command()
async def qfind(ctx: commands.Context[commands.Bot], *, query: str) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    matches = player.queue.find_all(query)
    await send_lines(
        ctx,
        (f"{index}. {format_track(track)}" for index, track in enumerate(matches[:10], 1)),
        empty="No queue matches.",
    )


@bot.command()
async def loop(ctx: commands.Context[commands.Bot], mode: str) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return

    try:
        player.queue.mode = fluxwave.QueueMode(mode.lower())
    except ValueError:
        await ctx.reply("Use `normal`, `loop`, or `loop_all`.")
        return
    await ctx.reply(f"Queue mode: {player.queue.mode.value}")


@bot.command()
async def pause(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is not None:
        await player.pause()
        await ctx.reply("Paused.")


@bot.command()
async def resume(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is not None:
        await player.resume()
        await ctx.reply("Resumed.")


@bot.command()
async def seek(ctx: commands.Context[commands.Bot], seconds: int) -> None:
    player = active_player(ctx)
    if player is not None:
        await player.seek(seconds * 1000)
        await ctx.reply(f"Seeked to {seconds}s.")


@bot.command(aliases=["vol"])
async def volume(ctx: commands.Context[commands.Bot], value: int = DEFAULT_VOLUME) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    value = max(0, min(value, 1000))
    await player.set_volume(value)
    await ctx.reply(f"Volume set to {player.volume}.")


@bot.command()
async def skip(ctx: commands.Context[commands.Bot], force: bool = True) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    skipped = await player.skip(force=force)
    await ctx.reply(f"Skipped {skipped.title}." if skipped else "Nothing to skip.")


@bot.command()
async def stop(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    await player.stop(force=True)
    await ctx.reply("Stopped playback and cleared the queue and autoplay recommendations.")


@bot.command()
async def now(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None or player.current is None:
        await ctx.reply("Nothing is playing.")
        return
    track = player.current
    await ctx.reply(
        f"Now playing: {format_track(track)}\n"
        f"Position: {player.position // 1000}s | Volume: {player.volume} | "
        f"Paused: {player.paused}"
    )


async def apply_filter(ctx: commands.Context[commands.Bot], filters: fluxwave.Filters) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    await player.set_filters(filters, seek=True)
    await ctx.reply("Filters applied.")


@bot.command()
async def bass(ctx: commands.Context[commands.Bot]) -> None:
    await apply_filter(ctx, fluxwave.Filters().bass_boost())


@bot.command()
async def nightcore(ctx: commands.Context[commands.Bot]) -> None:
    await apply_filter(ctx, fluxwave.Filters().nightcore())


@bot.command()
async def vaporwave(ctx: commands.Context[commands.Bot]) -> None:
    await apply_filter(ctx, fluxwave.Filters().vaporwave())


@bot.command()
async def lowpass(ctx: commands.Context[commands.Bot], smoothing: float = 20.0) -> None:
    await apply_filter(ctx, fluxwave.Filters().low_pass(smoothing=smoothing))


@bot.command()
async def clearfilters(ctx: commands.Context[commands.Bot]) -> None:
    await apply_filter(ctx, fluxwave.Filters().clear())


@bot.command()
async def lyrics(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return

    result = await player.fetch_lyrics()
    if result is None or not result.text:
        await ctx.reply("No lyrics available.")
        return
    await ctx.reply(result.text[:MESSAGE_LIMIT])


@bot.command()
async def lyricline(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return

    result = await player.fetch_lyrics()
    line = result.at(player.position) if result is not None and result.synced else None
    await ctx.reply(line.text if line is not None else "No synced lyric line available.")


@bot.command()
async def lavasrc(ctx: commands.Context[commands.Bot], source: str, *, query: str) -> None:
    node = fluxwave.Pool.get_node()
    helpers = node.plugins.lavasrc
    lookup = {
        "spotify": helpers.spotify,
        "apple": helpers.apple_music,
        "deezer": helpers.deezer,
        "yandex": helpers.yandex_music,
    }
    searcher = lookup.get(source.lower())
    if searcher is None:
        await ctx.reply("Use source: spotify, apple, deezer, yandex.")
        return
    result = await searcher(query)
    tracks = result.tracks if isinstance(result, fluxwave.Playlist) else result
    await send_lines(
        ctx,
        (f"{index}. {format_track(track)}" for index, track in enumerate(tracks[:8], 1)),
        empty="No tracks found.",
    )


@bot.command()
async def sponsor(ctx: commands.Context[commands.Bot], *, categories: str | None = None) -> None:
    guild = require_guild(ctx)
    player = active_player(ctx)
    if guild is None or player is None:
        await ctx.reply("Connect and start a Lavalink player first.")
        return

    helper = player.node.plugins.sponsorblock
    if categories is None:
        response = await helper.categories(guild.id)
    elif categories.lower() in {"off", "clear", "none", "disable", "disabled"}:
        response = await helper.clear_categories(guild.id)
    else:
        selected = [item.strip() for item in categories.replace(",", " ").split() if item.strip()]
        response = await helper.set_categories(guild.id, selected)
    await ctx.reply(short_json(response))


@bot.command()
async def customget(ctx: commands.Context[commands.Bot], path: str) -> None:
    response = await fluxwave.Pool.get_node().send("GET", path=path)
    await ctx.reply(short_json(response))


@bot.command()
async def autoplay(ctx: commands.Context[commands.Bot], mode: str = "enabled") -> None:
    player = await ensure_player(ctx)
    if player is None:
        return

    aliases = {
        "on": fluxwave.AutoPlayMode.ENABLED,
        "true": fluxwave.AutoPlayMode.ENABLED,
        "enabled": fluxwave.AutoPlayMode.ENABLED,
        "partial": fluxwave.AutoPlayMode.PARTIAL,
        "off": fluxwave.AutoPlayMode.DISABLED,
        "false": fluxwave.AutoPlayMode.DISABLED,
        "disabled": fluxwave.AutoPlayMode.DISABLED,
    }
    selected = aliases.get(mode.lower())
    if selected is None:
        await ctx.reply("Use `enabled`, `partial`, or `disabled`.")
        return
    player.autoplay = selected
    await ctx.reply(f"Autoplay: {player.autoplay.value}")


@bot.command()
async def populateauto(ctx: commands.Context[commands.Bot], limit: int = 5) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    added = await player.populate_autoplay(limit=limit)
    await ctx.reply(f"Added {added} autoplay recommendation(s).")


@bot.command()
async def save(ctx: commands.Context[commands.Bot]) -> None:
    guild = require_guild(ctx)
    player = active_player(ctx)
    if guild is None or player is None:
        await ctx.reply("Not connected.")
        return
    await store.save(guild.id, player.save_state(extra={"saved_by": ctx.author.id}))
    await ctx.reply("Saved player state.")


@bot.command()
async def restore(ctx: commands.Context[commands.Bot], seek: bool = True) -> None:
    guild = require_guild(ctx)
    player = await ensure_player(ctx)
    if guild is None or player is None:
        return
    state = await store.load(guild.id)
    if state is None:
        await ctx.reply("No saved state.")
        return
    await player.restore_state(state, seek=seek)
    await ctx.reply("Restored player state.")


@bot.command()
async def watchdog(ctx: commands.Context[commands.Bot], action: str = "status") -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return

    existing = watchdogs.get(player.guild.id)
    if action == "start":
        if existing is None or not existing.running:
            watchdogs[player.guild.id] = player.start_watchdog()
        await ctx.reply("Watchdog started.")
    elif action == "stop":
        if existing is not None:
            existing.stop()
        watchdogs.pop(player.guild.id, None)
        await ctx.reply("Watchdog stopped.")
    else:
        await ctx.reply(
            short_json(
                {
                    "running": existing.running if existing is not None else False,
                    "stats": existing.stats if existing is not None else None,
                }
            )
        )


@bot.command()
async def metrics(ctx: commands.Context[commands.Bot]) -> None:
    await ctx.reply(short_json(fluxwave.metrics.to_dict()))


@bot.command()
async def resetmetrics(ctx: commands.Context[commands.Bot]) -> None:
    fluxwave.metrics.reset()
    await ctx.reply("Metrics reset.")


@bot.command()
async def trace(ctx: commands.Context[commands.Bot], action: str = "recent") -> None:
    if action == "on":
        fluxwave.tracer.enable()
        await ctx.reply("Tracing enabled.")
    elif action == "off":
        fluxwave.tracer.disable()
        await ctx.reply("Tracing disabled.")
    elif action == "clear":
        fluxwave.tracer.clear()
        await ctx.reply("Trace buffer cleared.")
    else:
        events = fluxwave.tracer.recent(10)
        lines = [
            f"{event.category.value}: {event.message} guild={event.guild_id} node={event.node_id}"
            for event in events
        ]
        await send_lines(ctx, lines, empty="No trace events.")


@bot.command()
async def nodeinfo(ctx: commands.Context[commands.Bot]) -> None:
    node = fluxwave.Pool.get_node()
    info = await node.fetch_info()
    await ctx.reply(
        short_json(
            {
                "identifier": node.identifier,
                "version": info.version.semver,
                "sources": info.source_managers,
                "filters": info.filters,
                "plugins": [f"{plugin.name}:{plugin.version}" for plugin in info.plugins],
            }
        )
    )


@bot.command()
async def nodestats(ctx: commands.Context[commands.Bot]) -> None:
    node = fluxwave.Pool.get_node()
    stats = await node.fetch_stats()
    await ctx.reply(
        short_json(
            {
                "players": stats.players,
                "playing": stats.playing_players,
                "uptime_ms": stats.uptime,
                "cpu_load": stats.cpu.lavalink_load,
                "memory_used": stats.memory.used,
                "health_score": node.health_score,
                "latency": node.latency,
            }
        )
    )


@bot.command()
async def poolinfo(ctx: commands.Context[commands.Bot]) -> None:
    await ctx.reply(
        short_json(
            {
                "nodes": list(fluxwave.Pool.nodes()),
                "node_count": fluxwave.Pool.node_count(),
                "active_nodes": [node.identifier for node in fluxwave.Pool.active_nodes()],
                "degraded": [node.identifier for node in fluxwave.Pool.get_degraded_nodes()],
                "has_cache": fluxwave.Pool.has_cache(),
                "router_rules": len(fluxwave.Pool.router().routes),
            }
        )
    )


@bot.command()
async def routeplanner(ctx: commands.Context[commands.Bot]) -> None:
    status = await fluxwave.Pool.fetch_routeplanner_status()
    await ctx.reply(short_json(status.raw if status is not None else {"routePlanner": None}))


@bot.command()
async def freeroute(ctx: commands.Context[commands.Bot], address: str) -> None:
    await fluxwave.Pool.free_routeplanner_address(address)
    await ctx.reply(f"Freed route planner address `{address}`.")


@bot.command()
async def router(ctx: commands.Context[commands.Bot], pattern: str = "spsearch:*") -> None:
    router_obj = fluxwave.SourceRouter()
    router_obj.add(pattern, fluxwave.Pool.get_node().identifier, priority=10)
    fluxwave.Pool.set_router(router_obj)
    await ctx.reply(f"Router set: `{pattern}` -> `{fluxwave.Pool.get_node().identifier}`.")


@bot.command()
async def reconnectnode(ctx: commands.Context[commands.Bot]) -> None:
    nodes = await fluxwave.Pool.reconnect()
    await ctx.reply(f"Reconnected nodes: {', '.join(nodes) or 'none'}.")


@bot.command()
async def switchnode(ctx: commands.Context[commands.Bot], identifier: str) -> None:
    """Move the current player to another node; playback continues there."""
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    try:
        target = fluxwave.Pool.get_node(identifier)  # look up the node by identifier
    except fluxwave.InvalidNodeError:
        await ctx.reply(f"No node named `{identifier}`.")
        return
    try:
        await player.switch_node(target)  # migrate this player to another Lavalink node
    except (fluxwave.PlayerError, fluxwave.InvalidNodeError) as exc:
        await ctx.reply(f"Could not switch node: {exc}")
        return
    await ctx.reply(f"Player is now on node `{player.node.identifier}`.")


@bot.command()
async def drainnode(
    ctx: commands.Context[commands.Bot], identifier: str, cooldown: float = 60.0
) -> None:
    """Evacuate all players off a node before maintenance."""
    try:
        node = fluxwave.Pool.get_node(identifier)
    except fluxwave.InvalidNodeError:
        await ctx.reply(f"No node named `{identifier}`.")
        return
    moved = await fluxwave.Pool.drain(node, cooldown=cooldown)  # migrate players off + blacklist
    await ctx.reply(f"Drained `{identifier}`: migrated {moved} player(s).")


@bot.command()
async def failover(ctx: commands.Context[commands.Bot], identifier: str) -> None:
    """Simulate a node failure: migrate its players away (they return on recovery)."""
    try:
        node = fluxwave.Pool.get_node(identifier)
    except fluxwave.InvalidNodeError:
        await ctx.reply(f"No node named `{identifier}`.")
        return
    moved = await fluxwave.Pool.handle_node_failure(node)  # blacklist + migrate players
    await ctx.reply(f"Handled failure of `{identifier}`: migrated {moved} player(s).")


@bot.command()
async def extras(ctx: commands.Context[commands.Bot], key: str, *, value: str) -> None:
    player = active_player(ctx)
    if player is None or player.current is None:
        await ctx.reply("Nothing is playing.")
        return
    player.current.extras[key] = value
    await ctx.reply(f"Set current track extra `{key}`.")


@bot.command()
async def cachetest(ctx: commands.Context[commands.Bot], *, query: str) -> None:
    first = await fluxwave.Pool.search(query, use_cache=True)
    second = await fluxwave.Pool.search(query, use_cache=True)
    first_count = len(first.tracks) if isinstance(first, fluxwave.Playlist) else len(first)
    second_count = len(second.tracks) if isinstance(second, fluxwave.Playlist) else len(second)
    await ctx.reply(f"Cache test complete: first={first_count}, second={second_count}.")


@bot.command()
async def rawqueue(ctx: commands.Context[commands.Bot]) -> None:
    player = active_player(ctx)
    if player is None:
        await ctx.reply("Not connected.")
        return
    await ctx.reply(short_json(player.queue.to_raw_data()))


@bot.command()
async def helpadvanced(ctx: commands.Context[commands.Bot]) -> None:
    commands_list = sorted(command.name for command in bot.commands)
    await send_lines(ctx, commands_list)


if __name__ == "__main__":
    bot.run(env("DISCORD_TOKEN"))
