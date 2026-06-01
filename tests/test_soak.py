import asyncio

import pytest

import fluxwave


def track(encoded: str) -> fluxwave.Track:
    return fluxwave.Track.from_payload(
        {
            "encoded": encoded,
            "info": {
                "identifier": encoded,
                "isSeekable": True,
                "author": "artist",
                "length": 1000,
                "isStream": False,
                "position": 0,
                "title": encoded,
            },
        }
    )


class SoakGuild:
    def __init__(self) -> None:
        self.id = 123
        self.voice_states: list[object] = []

    async def change_voice_state(self, **kwargs: object) -> None:
        self.voice_states.append(kwargs.get("channel"))


class SoakMember:
    def __init__(self, *, bot: bool = False) -> None:
        self.bot = bot


class SoakChannel:
    def __init__(self, channel_id: int = 456, guild: SoakGuild | None = None) -> None:
        self.id = channel_id
        self.guild = guild or SoakGuild()
        self.members: list[SoakMember] = []


class SoakClient:
    def __init__(self, channel: SoakChannel) -> None:
        self.user = object()
        self.channels: dict[int, SoakChannel] = {channel.id: channel}
        self.events: list[tuple[str, object]] = []

    def get_channel(self, channel_id: int) -> SoakChannel | None:
        return self.channels.get(channel_id)

    def dispatch(self, event: str, payload: object) -> None:
        self.events.append((event, payload))


class SoakNode:
    def __init__(self) -> None:
        self.identifier = "soak"
        self.status = fluxwave.NodeStatus.CONNECTED
        self.player_count = 0
        self.inactive_player_timeout = 300.0
        self.inactive_channel_tokens = 3
        self.updates: list[fluxwave.PlayerUpdate] = []
        self.destroyed: list[int] = []
        self.listeners: dict[str, list[object]] = {}
        self.live_players: dict[int, object] = {}

    def on(self, event: str, callback: object) -> None:
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event: str, callback: object) -> None:
        self.listeners.get(event, []).remove(callback)

    def dispatch(self, event: str, payload: object) -> None:
        for callback in tuple(self.listeners.get(event, [])):
            callback(payload)

    def register_player(self, player: object) -> None:
        self.live_players[123] = player

    def unregister_player(self, guild_id: int) -> None:
        self.live_players.pop(guild_id, None)

    async def update_player(
        self,
        guild_id: int,
        update: fluxwave.PlayerUpdate,
        *,
        replace: bool = False,
    ) -> fluxwave.LavalinkPlayer:
        self.updates.append(update)
        return fluxwave.LavalinkPlayer.from_payload(
            {
                "guildId": guild_id,
                "track": None,
                "volume": update.volume or 100,
                "paused": bool(update.paused),
                "state": {
                    "time": 0,
                    "position": update.position or 0,
                    "connected": True,
                    "ping": 1,
                },
                "voice": {},
                "filters": {},
            }
        )

    async def destroy_player(self, guild_id: int) -> None:
        self.destroyed.append(guild_id)


def soak_player(node: SoakNode | None = None) -> tuple[fluxwave.FluxPlayer, SoakClient]:
    channel = SoakChannel()
    client = SoakClient(channel)
    player = fluxwave.FluxPlayer(
        client,  # type: ignore[arg-type]
        channel,  # type: ignore[arg-type]
        node=node or SoakNode(),  # type: ignore[arg-type]
    )
    return player, client


async def connect_voice(player: fluxwave.FluxPlayer) -> None:
    await player.on_voice_state_update({"channel_id": "456", "session_id": "session"})  # type: ignore[arg-type]
    await player.on_voice_server_update(  # type: ignore[arg-type]
        {"token": "token", "endpoint": "voice.example", "guild_id": "123"}
    )


def test_soak_large_queue_primitive_flow() -> None:
    queue = fluxwave.Queue()
    tracks = [track(f"track-{index}") for index in range(75)]

    assert queue(tracks) == 75
    for expected in tracks[:50]:
        assert queue.get() is expected

    assert queue.count == 25
    assert queue.history is not None
    assert queue.history.count == 50


def test_soak_playlist_and_auto_queue_ordering_primitives() -> None:
    playlist_tracks = [track(f"playlist-{index}") for index in range(50)]
    playlist = fluxwave.Playlist(
        info=fluxwave.tracks.PlaylistInfo(name="mix"),
        tracks=playlist_tracks,
    )
    queue = fluxwave.Queue()
    auto_queue = fluxwave.Queue()

    queue(playlist)
    auto_queue([track("auto-1"), track("auto-2")])

    assert queue.get() is playlist_tracks[0]
    queue.clear()
    assert auto_queue.get().encoded == "auto-1"


async def test_soak_node_restart_recovers_voice_and_current_track() -> None:
    node = SoakNode()
    player, _client = soak_player(node)
    await connect_voice(player)
    seed = track("restart-seed")
    await player.play(seed)
    node.updates.clear()

    await player.recover_voice_state()

    assert node.updates[0].voice is not None
    assert node.updates[-1].encoded_track == "restart-seed"


async def test_soak_voice_move_spam_serializes_voice_updates() -> None:
    node = SoakNode()
    player, client = soak_player(node)
    await connect_voice(player)

    for index in range(20):
        channel = SoakChannel(500 + index, player.guild)  # type: ignore[arg-type]
        client.channels[channel.id] = channel
        move_task = asyncio.create_task(
            player.move_to(  # type: ignore[arg-type]
                channel,
                timeout=1,
            )
        )
        await asyncio.sleep(0)
        await player.on_voice_state_update(  # type: ignore[arg-type]
            {"channel_id": str(channel.id), "session_id": f"session-{index}"}
        )
        await move_task

    assert player.channel.id == 519
    assert node.updates[-1].voice is not None
    assert node.updates[-1].voice.channel_id == "519"


async def test_soak_skip_spam_in_loop_mode_does_not_replay_forced_track() -> None:
    node = SoakNode()
    player, _client = soak_player(node)
    await connect_voice(player)
    current = track("current")
    queued = [track(f"queued-{index}") for index in range(12)]
    await player.play(current)
    player.queue.put(queued)
    player.queue.mode = fluxwave.QueueMode.LOOP

    for expected in queued:
        await player.skip(force=True)
        assert player.current is expected

    await player.skip(force=True)
    assert player.current is None


async def test_soak_fifty_track_playlist_enqueue_selected_first() -> None:
    player, _client = soak_player()
    playlist_tracks = [track(f"playlist-{index}") for index in range(60)]
    playlist = fluxwave.Playlist(
        info=fluxwave.tracks.PlaylistInfo(name="long mix", selected_track=25),
        tracks=playlist_tracks,
    )

    result = await player.enqueue(playlist, limit=50)

    assert result.added == 50
    assert player.queue.count == 50
    assert player.queue.peek() is playlist_tracks[25]


async def test_soak_bot_kicked_while_playing_destroys_player() -> None:
    node = SoakNode()
    player, _client = soak_player(node)
    await connect_voice(player)
    await player.play(track("kick-seed"))

    await player.on_voice_state_update({"channel_id": None, "session_id": "session"})  # type: ignore[arg-type]

    assert player.destroyed
    assert node.destroyed == [123]
    assert player.current is None


async def test_soak_playlist_queue_takes_priority_over_autoplay_queue() -> None:
    node = SoakNode()
    player, _client = soak_player(node)
    await connect_voice(player)
    player.autoplay = fluxwave.AutoPlayMode.ENABLED
    seed = track("seed")
    playlist_tracks = [track("playlist-1"), track("playlist-2")]
    player.queue.put(playlist_tracks)
    player.auto_queue.put(track("auto-1"))
    await player.play(seed)

    player._on_node_track_end(fluxwave.TrackEndEvent(123, seed, "finished"))
    assert player._autoplay_task is not None
    await player._autoplay_task

    assert player.current is playlist_tracks[0]
    assert player.auto_queue.peek().encoded == "auto-1"


@pytest.mark.skip(reason="Manual Discord/Lavalink soak test requires live guild control.")
async def test_soak_lavalink_restart_while_playing() -> None:
    """Restart Lavalink during playback and verify resume or player recovery."""


@pytest.mark.skip(reason="Manual Discord soak test requires a connected bot and voice channel.")
async def test_soak_large_queue_and_skip_spam() -> None:
    """Play a 50+ track queue while rapidly skipping tracks."""


@pytest.mark.skip(reason="Manual Discord soak test requires guild voice control.")
async def test_soak_channel_moves_and_bot_kicked() -> None:
    """Move the bot across channels, then kick it from voice and verify cleanup."""


@pytest.mark.skip(reason="Manual Discord/Lavalink soak test requires live playback.")
async def test_soak_playlist_with_autoplay_enabled() -> None:
    """Queue a playlist with autoplay enabled and verify queue/autoplay ordering."""
