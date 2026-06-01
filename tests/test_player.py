import asyncio

import pytest

import fluxwave


def track(encoded: str = "abc") -> fluxwave.Track:
    return fluxwave.Track.from_payload(
        {
            "encoded": encoded,
            "info": {
                "identifier": encoded,
                "isSeekable": True,
                "author": "artist",
                "length": 120_000,
                "isStream": False,
                "position": 0,
                "title": "song",
                "sourceName": "youtube",
            },
            "userData": {"requester": 1},
        }
    )


class FakeGuild:
    def __init__(self) -> None:
        self.id = 123
        self.voice_states: list[object] = []

    async def change_voice_state(self, **kwargs: object) -> None:
        self.voice_states.append(kwargs.get("channel"))


class FakeMember:
    def __init__(self, *, bot: bool = False) -> None:
        self.bot = bot


class FakeChannel:
    def __init__(self) -> None:
        self.id = 456
        self.guild = FakeGuild()
        self.members: list[FakeMember] = []


class InvalidChannel:
    id = "not-an-int"


class FakeClient:
    def __init__(self, channel: FakeChannel | None = None) -> None:
        self.user = object()
        self.channel = channel
        self.events: list[tuple[str, object]] = []

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        if self.channel and self.channel.id == channel_id:
            return self.channel

        return None

    def dispatch(self, event: str, payload: object) -> None:
        self.events.append((event, payload))


class FakeNode:
    def __init__(self) -> None:
        self.identifier = "node"
        self.status = fluxwave.NodeStatus.CONNECTED
        self.player_count = 0
        self.updates: list[fluxwave.PlayerUpdate] = []
        self.replaces: list[bool] = []
        self.destroyed: list[int] = []
        self.listeners: dict[str, list[object]] = {}
        self.search_results: list[fluxwave.Track] | fluxwave.Playlist = []
        self.search_calls: list[tuple[str, object]] = []
        self.live_players: dict[int, object] = {}
        self.inactive_player_timeout = 300.0
        self.inactive_channel_tokens = 3
        self.lyrics_payload: dict[str, object] = {
            "provider": "test",
            "lines": [{"line": "hello", "timestamp": 1000}],
        }

    @property
    def plugins(self) -> object:
        return FakePluginHelpers(self)

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
        self.replaces.append(replace)
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

    async def search(
        self,
        query: str,
        *,
        source: object = None,
        use_cache: bool = True,
    ) -> list[fluxwave.Track] | fluxwave.Playlist:
        self.search_calls.append((query, source))
        return self.search_results


class FailingDestroyNode(FakeNode):
    async def destroy_player(self, guild_id: int) -> None:
        self.destroyed.append(guild_id)
        response = fluxwave.LavalinkErrorResponse(
            timestamp=None,
            status=500,
            error="Server Error",
            message="failed",
        )
        raise fluxwave.LavalinkError(response)


class FailingNode(FakeNode):
    async def update_player(
        self,
        guild_id: int,
        update: fluxwave.PlayerUpdate,
        *,
        replace: bool = False,
    ) -> fluxwave.LavalinkPlayer:
        response = fluxwave.LavalinkErrorResponse(
            timestamp=None,
            status=500,
            error="Server Error",
            message="failed",
        )
        raise fluxwave.LavalinkError(response)


class BlockingRecommendationProvider:
    def __init__(self, recommendation: fluxwave.Track) -> None:
        self.recommendation = recommendation
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def recommendations(
        self,
        seed: fluxwave.Track,
        *,
        limit: int = 5,
    ) -> list[fluxwave.Track]:
        self.started.set()
        await self.release.wait()
        return [self.recommendation]


class FakeLyricsClient:
    def __init__(self, node: FakeNode) -> None:
        self.node = node

    async def current(self, guild_id: int) -> dict[str, object]:
        assert guild_id == 123
        return self.node.lyrics_payload


class FakePluginHelpers:
    def __init__(self, node: FakeNode) -> None:
        self.lyrics = FakeLyricsClient(node)


def player(node: FakeNode | None = None) -> fluxwave.FluxPlayer:
    channel = FakeChannel()
    return fluxwave.FluxPlayer(
        FakeClient(channel),  # type: ignore[arg-type]
        channel,  # type: ignore[arg-type]
        node=node,  # type: ignore[arg-type]
    )


def player_with_client(node: FakeNode | None = None) -> tuple[fluxwave.FluxPlayer, FakeClient]:
    channel = FakeChannel()
    client = FakeClient(channel)
    return (
        fluxwave.FluxPlayer(
            client,  # type: ignore[arg-type]
            channel,  # type: ignore[arg-type]
            node=node,  # type: ignore[arg-type]
        ),
        client,
    )


def test_player_requires_valid_channel() -> None:
    with pytest.raises(fluxwave.InvalidChannelError):
        fluxwave.FluxPlayer(  # type: ignore[arg-type]
            FakeClient(),
            InvalidChannel(),  # type: ignore[arg-type]
            node=FakeNode(),  # type: ignore[arg-type]
        )


async def test_player_raises_invalid_node_when_node_disconnected() -> None:
    node = FakeNode()
    node.status = fluxwave.NodeStatus.DISCONNECTED
    p = player(node)

    with pytest.raises(fluxwave.InvalidNodeError):
        await p.play(track())


def test_player_autoplay_property_validates_mode() -> None:
    p = player(FakeNode())
    p.autoplay = fluxwave.AutoPlayMode.ENABLED

    assert p.autoplay is fluxwave.AutoPlayMode.ENABLED
    with pytest.raises(ValueError):
        p.autoplay = "enabled"  # type: ignore[assignment]


async def test_voice_updates_dispatch_to_lavalink() -> None:
    node = FakeNode()
    p = player(node)

    await p.on_voice_state_update({"channel_id": "456", "session_id": "session"})  # type: ignore[arg-type]
    await p.on_voice_server_update(  # type: ignore[arg-type]
        {"token": "token", "endpoint": "example.test", "guild_id": "123"}
    )

    assert p.connected
    assert node.updates[-1].voice is not None
    assert node.updates[-1].voice.session_id == "session"
    assert node.updates[-1].voice.channel_id == "456"


async def test_connect_timeout_cleanup_does_not_mask_timeout_error() -> None:
    node = FailingDestroyNode()
    p = player(node)

    with pytest.raises(fluxwave.ChannelTimeoutError):
        await p.connect(timeout=0.001)

    assert node.destroyed == [123]


async def test_move_to_rolls_back_channel_on_timeout() -> None:
    node = FakeNode()
    p = player(node)
    old_channel = p.channel
    new_channel = FakeChannel()
    new_channel.id = 789
    new_channel.guild = p.guild

    with pytest.raises(fluxwave.ChannelTimeoutError):
        await p.move_to(new_channel, timeout=0.001)  # type: ignore[arg-type]

    assert p.channel is old_channel


async def test_player_dispatches_discord_style_events() -> None:
    node = FakeNode()
    p, client = player_with_client(node)
    seed = track("seed")

    p._on_node_track_start(fluxwave.TrackStartEvent(123, seed))
    p._on_node_player_update(
        fluxwave.PlayerUpdateEvent(
            guild_id=123,
            state=fluxwave.PlayerState(time=1, position=500, connected=True, ping=42),
        )
    )
    p._on_node_websocket_closed(
        fluxwave.WebSocketClosedEvent(123, code=4014, reason="closed", by_remote=True)
    )

    names = [name for name, _payload in client.events]
    assert "fluxwave_track_start" in names
    assert "wavelink_track_start" in names
    assert "fluxwave_player_update" in names
    assert "fluxwave_websocket_closed" in names
    assert client.events[0][1].player is p
    assert client.events[0][1].original is seed


async def test_voice_state_disconnect_invalidates_player() -> None:
    node = FakeNode()
    p = player(node)

    await p.on_voice_state_update({"channel_id": None, "session_id": "session"})  # type: ignore[arg-type]

    assert p.destroyed
    assert node.destroyed == [123]


async def test_inactive_channel_tokens_dispatch_event_without_listener_members() -> None:
    node = FakeNode()
    p, client = player_with_client(node)
    seed = track("seed")
    received: list[object] = []
    node.on("inactive_player", received.append)
    p.inactive_channel_tokens = 1

    p._on_node_track_end(fluxwave.TrackEndEvent(123, seed, "finished"))
    await asyncio.sleep(0)

    assert len(received) == 1
    assert isinstance(received[0], fluxwave.InactivePlayerEvent)
    assert received[0].guild_id == 123
    assert ("fluxwave_inactive_player", received[0]) in client.events
    assert ("wavelink_inactive_player", received[0]) in client.events


async def test_inactive_channel_tokens_reset_when_real_member_present() -> None:
    node = FakeNode()
    p = player(node)
    p.inactive_channel_tokens = 1
    p.channel.members = [FakeMember(bot=False)]  # type: ignore[attr-defined]

    p._on_node_track_end(fluxwave.TrackEndEvent(123, track("seed"), "finished"))
    await asyncio.sleep(0)

    assert node.listeners.get("inactive_player") is None


async def test_voice_websocket_closed_marks_player_disconnected() -> None:
    node = FakeNode()
    p = player(node)
    p._connected = True

    p._on_node_websocket_closed(
        fluxwave.WebSocketClosedEvent(123, code=4014, reason="closed", by_remote=True)
    )

    assert not p.connected


async def test_dave_websocket_close_schedules_voice_recovery() -> None:
    node = FakeNode()
    p = player(node)
    p._voice_token = "token"
    p._voice_endpoint = "endpoint"
    p._voice_session_id = "session"
    p._voice_channel_id = "456"
    p._current = track("current")
    node.updates.clear()

    p._on_node_websocket_closed(
        fluxwave.WebSocketClosedEvent(123, code=4017, reason="DAVE required", by_remote=True)
    )
    for _ in range(4):
        await asyncio.sleep(0)

    assert node.updates[0].voice is not None
    assert node.updates[0].voice.channel_id == "456"
    assert node.updates[-1].encoded_track == "current"


async def test_voice_recovery_waits_for_active_operation() -> None:
    node = FakeNode()
    p = player(node)
    p._voice_token = "token"
    p._voice_endpoint = "endpoint"
    p._voice_session_id = "session"
    p._voice_channel_id = "456"
    p._current = track("current")
    p._operation_ready.clear()
    node.updates.clear()

    p._on_node_websocket_closed(
        fluxwave.WebSocketClosedEvent(123, code=4006, reason="closed", by_remote=True)
    )
    await asyncio.sleep(0)
    assert node.updates == []

    p._operation_ready.set()
    for _ in range(4):
        await asyncio.sleep(0)

    assert node.updates[0].voice is not None


async def test_play_sets_current_state() -> None:
    node = FakeNode()
    p = player(node)
    t = track()

    result = await p.play(t, start=500, volume=250, paused=True)

    assert result is t
    assert p.current is t
    assert p.volume == 250
    assert p.paused
    assert not p.playing
    assert p.position >= 500
    assert node.updates[-1].encoded_track == "abc"


async def test_playing_is_true_for_paused_loaded_track_when_connected() -> None:
    node = FakeNode()
    p = player(node)
    p._connected = True

    await p.play(track(), paused=True)

    assert p.paused
    assert p.playing


async def test_player_pomice_style_state_aliases() -> None:
    node = FakeNode()
    p = player(node)
    p._connected = True

    await p.play(track(), paused=True)

    assert p.is_connected is p.connected
    assert p.is_playing is p.playing
    assert p.is_paused is p.paused
    assert p.is_dead is p.destroyed


async def test_set_filters_can_seek_to_current_position() -> None:
    node = FakeNode()
    p = player(node)
    t = track()

    await p.play(t, start=1000)
    await p.set_filters(fluxwave.Filters().set_timescale(speed=1.1), seek=True)

    assert node.updates[-1].filters == {"timescale": {"speed": 1.1}}
    assert node.updates[-1].position is not None
    assert node.updates[-1].position >= 1000


async def test_player_tagged_filter_stack_add_edit_remove() -> None:
    node = FakeNode()
    p = player(node)

    bass = fluxwave.Filters().bass_boost(gain=0.2)
    nightcore = fluxwave.Filters().nightcore()
    await p.add_filter(bass, filter_tag="bass")
    await p.add_filter(nightcore, filter_tag="nightcore")

    assert p.has_filter("bass")
    assert p.filter_tags == ("bass", "nightcore")
    assert node.updates[-1].filters == {
        "equalizer": bass.to_payload()["equalizer"],
        "timescale": {"speed": 1.25, "pitch": 1.2, "rate": 1.0},
    }

    edited = fluxwave.Filters().vaporwave()
    await p.edit_filter("nightcore", edited)
    assert node.updates[-1].filters["timescale"] == {
        "speed": 0.85,
        "pitch": 0.8,
        "rate": 1.0,
    }

    await p.remove_filter("bass")
    assert not p.has_filter("bass")
    assert node.updates[-1].filters == edited.to_payload()


async def test_player_preloaded_filter_stack_applies_on_future_play() -> None:
    node = FakeNode()
    p = player(node)
    filters = fluxwave.Filters().set_timescale(speed=1.1)

    await p.add_filter(filters, filter_tag="preload", preload=True)

    assert p.preload_filter_tags == ("preload",)
    assert node.updates == []

    await p.play(track())

    assert node.updates[-1].filters == {"timescale": {"speed": 1.1}}


async def test_set_filters_clears_tagged_filter_stack() -> None:
    node = FakeNode()
    p = player(node)

    await p.add_filter(fluxwave.Filters().nightcore(), filter_tag="nightcore")
    await p.set_filters(fluxwave.Filters().bass_boost())

    assert p.filter_tags == ()
    assert not p.has_filter("nightcore")
    assert "equalizer" in node.updates[-1].filters


async def test_player_fetch_lyrics_parses_synced_lines() -> None:
    node = FakeNode()
    p = player(node)
    await p.play(track())

    lyrics = await p.fetch_lyrics()

    assert lyrics is not None
    assert lyrics.provider == "test"
    assert lyrics.synced
    assert lyrics.text == "hello"
    assert lyrics.at(1000).text == "hello"
    assert await p.current_lyrics() == "hello"


class _RaisingLyricsClient:
    async def current(self, guild_id: int, *, skip_track_source: bool = False) -> object:
        response = fluxwave.LavalinkErrorResponse(
            timestamp=None,
            status=500,
            error="Internal Server Error",
            message="Spotify spDc must be set",
        )
        raise fluxwave.LavalinkError(response)


class _LyricsErrorHelpers:
    def __init__(self, node: "FakeNode") -> None:
        self.lyrics = _RaisingLyricsClient()


class LyricsErrorNode(FakeNode):
    @property
    def plugins(self) -> object:
        return _LyricsErrorHelpers(self)


async def test_fetch_lyrics_returns_none_when_server_errors() -> None:
    # Lyrics are best-effort: a server-side error (e.g. unconfigured lyrics
    # source) must not blow up the current_lyrics()/fetch_lyrics() helpers.
    p = player(LyricsErrorNode())
    await p.play(track())

    assert await p.fetch_lyrics() is None
    assert await p.current_lyrics() is None


def test_player_uses_node_inactivity_defaults() -> None:
    node = FakeNode()
    node.inactive_player_timeout = 42.0
    node.inactive_channel_tokens = 2
    p = player(node)

    assert p.inactivity_timeout == 42.0
    assert p.inactive_channel_tokens == 2
    assert fluxwave.AutoPlayMode.enabled is fluxwave.AutoPlayMode.ENABLED
    assert fluxwave.AutoPlayMode.partial is fluxwave.AutoPlayMode.PARTIAL
    assert fluxwave.AutoPlayMode.disabled is fluxwave.AutoPlayMode.DISABLED


async def test_player_public_helper_return_types() -> None:
    p = player(FakeNode())

    state = p.save_state()
    watchdog = p.start_watchdog()
    watchdog.stop()

    assert isinstance(state, fluxwave.PersistedState)
    assert isinstance(watchdog, fluxwave.VoiceWatchdog)


async def test_inactive_timeout_and_channel_token_properties_reset_state() -> None:
    node = FakeNode()
    p = player(node)
    p.auto_disconnect = True
    p._connected = True
    p.inactive_timeout = 10

    assert p.inactivity_timeout == 10
    assert p._inactivity_task is not None

    p.inactive_timeout = None
    assert p.inactivity_timeout is None
    assert p._inactivity_task is None

    p.inactive_channel_tokens = 2
    assert p.inactive_channel_tokens == 2
    assert p._inactive_channel_count == 2

    p.inactive_channel_tokens = 0
    assert p.inactive_channel_tokens is None
    assert p._inactive_channel_count is None


async def test_play_rolls_back_on_lavalink_error() -> None:
    p = player(FailingNode())
    old = track("old")
    p._current = old

    with pytest.raises(fluxwave.LavalinkError):
        await p.play(track("new"))

    assert p.current is old


async def test_pause_resume_seek_volume_skip_and_destroy() -> None:
    node = FakeNode()
    p = player(node)
    t = track()

    await p.play(t)
    await p.pause()
    await p.resume()
    await p.seek(10_000)
    await p.set_volume(2_000)
    skipped = await p.skip(play_next=False)
    await p.destroy()

    assert skipped is t
    assert p.current is None
    assert p.volume == 1000
    assert node.updates[-1].clear_track
    assert node.replaces[-1]
    assert node.destroyed == [123]
    assert all(not callbacks for callbacks in node.listeners.values())


async def test_skip_plays_next_queued_track() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    second = track("second")

    await p.play(first)
    p.queue.put(second)
    skipped = await p.skip()

    assert skipped is first
    assert p.current is second
    assert node.updates[-1].encoded_track == "second"


async def test_skip_accepts_force_alias() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    second = track("second")

    await p.play(first)
    p.queue.put(second)
    skipped = await p.skip(force=True)

    assert skipped is first
    assert p.current is second


async def test_manual_skip_uses_auto_queue_when_autoplay_enabled() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    recommended = track("recommended")
    p.autoplay = fluxwave.AutoPlayMode.ENABLED

    await p.play(first)
    p.auto_queue.put(recommended)
    skipped = await p.skip(force=True)

    assert skipped is first
    assert p.current is recommended
    assert node.updates[-1].encoded_track == "recommended"


async def test_manual_skip_populates_autoplay_when_queue_empty() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    recommended = track("recommended")
    p.autoplay = fluxwave.AutoPlayMode.ENABLED
    node.search_results = [recommended]

    await p.play(first)
    skipped = await p.skip(force=True)

    assert skipped is first
    assert p.current == recommended.as_recommended()
    assert p.current.recommended
    assert node.updates[-1].encoded_track == "recommended"


async def test_skip_force_bypasses_queue_loop_loaded_track() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    second = track("second")

    await p.play(first)
    p.queue.put(second)
    p.queue.mode = fluxwave.QueueMode.LOOP
    skipped = await p.skip(force=True)

    assert skipped is first
    assert p.current is second
    assert p.queue.loaded is second
    assert node.updates[-1].encoded_track == "second"


async def test_skip_force_false_advances_without_bypassing_loop() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    second = track("second")

    await p.play(first)
    p.queue.put(second)
    skipped = await p.skip(force=False)

    assert skipped is first
    assert p.current is second
    assert node.updates[-1].encoded_track == "second"


async def test_enqueue_play_next_and_play_search_helpers() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    second = track("second")
    node.search_results = [first, second]

    enqueued = await p.enqueue("hello")
    next_track = await p.play_next(second)
    played = await p.play_search("hello")

    assert enqueued.first_track is first
    assert enqueued.added == 1
    assert enqueued.message == "Queued 1 track."
    assert next_track.first_track is second
    assert next_track.message == "Queued 1 track next."
    assert played.first_track is first
    assert played.message == "Playing song."
    assert list(p.queue) == [second, first]
    assert node.search_calls == [
        ("hello", fluxwave.SearchSource.YOUTUBE),
        ("hello", fluxwave.SearchSource.YOUTUBE),
    ]


async def test_play_search_replace_false_reports_requested_track() -> None:
    node = FakeNode()
    p = player(node)
    current = track("current")
    requested = track("requested")
    node.search_results = [requested]

    await p.play(current)
    result = await p.play_search("requested", replace=False)

    assert p.current is current
    assert result.first_track is requested
    assert result.tracks == [requested]
    assert result.message == "Requested song; current track was not replaced."


async def test_play_search_applies_search_filters() -> None:
    node = FakeNode()
    p = player(node)
    requested = track("requested")
    filters = fluxwave.Filters().nightcore()
    node.search_results = [requested]

    result = await p.play_search("requested", filters=filters)

    assert result.filters is filters
    assert result.first_track is not requested
    assert result.first_track is not None
    assert result.first_track.user_data["fluxwaveFilters"] == filters.to_payload()
    assert node.updates[-1].filters == filters.to_payload()


async def test_queued_search_filters_apply_when_track_is_played() -> None:
    node = FakeNode()
    p = player(node)
    requested = track("requested")
    filters = fluxwave.Filters().bass_boost()
    node.search_results = [requested]

    result = await p.enqueue("requested", filters=filters)
    queued = result.first_track
    assert queued is not None

    await p.play(queued)

    assert result.filters is filters
    assert queued.user_data["fluxwaveFilters"] == filters.to_payload()
    assert node.updates[-1].filters == filters.to_payload()


async def test_enqueue_playlist_adds_all_tracks() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    second = track("second")
    node.search_results = fluxwave.Playlist(
        info=fluxwave.tracks.PlaylistInfo(name="mix"),
        tracks=[first, second],
    )

    enqueued = await p.enqueue("playlist")

    assert enqueued.first_track is first
    assert enqueued.playlist is node.search_results
    assert enqueued.added == 2
    assert list(p.queue) == [first, second]


async def test_enqueue_playlist_can_limit_and_selected_first() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    second = track("second")
    third = track("third")
    playlist = fluxwave.Playlist(
        info=fluxwave.tracks.PlaylistInfo(name="mix", selected_track=1),
        tracks=[first, second, third],
    )

    result = await p.enqueue(playlist, limit=2)

    assert result.tracks == [second, first]
    assert list(p.queue) == [second, first]


async def test_play_replace_false_does_not_replace_current_local_track() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    second = track("second")

    await p.play(first)
    result = await p.play(second, replace=False)

    assert p.current is first
    assert result is first
    assert p.queue.loaded is first
    assert list(p.queue.history or []) == [first]
    assert node.updates[-1].encoded_track == "second"
    assert not node.replaces[-1]


async def test_switch_node_migrates_voice_and_current_track() -> None:
    old = FakeNode()
    new = FakeNode()
    new.identifier = "new"
    p = player(old)
    t = track("current")

    await p.on_voice_state_update({"channel_id": "456", "session_id": "session"})  # type: ignore[arg-type]
    await p.on_voice_server_update(  # type: ignore[arg-type]
        {"token": "token", "endpoint": "example.test", "guild_id": "123"}
    )
    await p.play(t)
    await p.switch_node(new)  # type: ignore[arg-type]

    assert p.node is new
    assert old.destroyed == [123]
    assert new.updates[-2].voice is not None
    assert new.updates[-1].encoded_track == "current"
    assert all(not callbacks for callbacks in old.listeners.values())
    assert all(callbacks for callbacks in new.listeners.values())


async def test_autoplay_uses_normal_queue_before_auto_queue() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    queued = track("queued")
    recommended = track("recommended")
    p.queue.put(queued)
    p.auto_queue.put(recommended)

    p._on_node_track_end(fluxwave.TrackEndEvent(123, first, "finished"))
    await asyncio.sleep(0)

    assert p.current is queued
    assert node.updates[-1].encoded_track == "queued"
    assert p.auto_queue.peek() is recommended


async def test_partial_autoplay_uses_queue_but_not_auto_queue() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    queued = track("queued")
    recommended = track("recommended")
    p.autoplay = fluxwave.AutoPlayMode.PARTIAL
    p.queue.put(queued)
    p.auto_queue.put(recommended)

    p._on_node_track_end(fluxwave.TrackEndEvent(123, first, "finished"))
    await asyncio.sleep(0)

    assert p.current is queued
    assert p.auto_queue.peek() is recommended


async def test_partial_autoplay_does_not_populate_when_queue_empty() -> None:
    node = FakeNode()
    p = player(node)
    p.autoplay = fluxwave.AutoPlayMode.PARTIAL
    node.search_results = [track("recommended")]

    p._on_node_track_end(fluxwave.TrackEndEvent(123, track("first"), "finished"))
    await asyncio.sleep(0)

    assert p.current is None
    assert p.auto_queue.is_empty


async def test_autoplay_disabled_does_not_consume_auto_queue() -> None:
    node = FakeNode()
    p = player(node)
    seed = track("seed")
    recommended = track("recommended")
    p.auto_queue.put(recommended)

    p._on_node_track_end(fluxwave.TrackEndEvent(123, seed, "finished"))
    await asyncio.sleep(0)

    assert p.current is None
    assert p.auto_queue.peek() is recommended


async def test_manual_stop_end_event_does_not_advance_queue() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    queued = track("queued")

    await p.play(first)
    p.queue.put(queued)
    await p.skip(play_next=False)
    p._on_node_track_end(fluxwave.TrackEndEvent(123, first, "stopped"))
    await asyncio.sleep(0)

    assert p.current is None
    assert p.queue.peek() is queued


async def test_stop_clears_auto_queue_and_recommendation_state() -> None:
    node = FakeNode()
    p = player(node)
    first = track("first")
    recommended = track("recommended")
    queued = track("queued")
    p.autoplay = fluxwave.AutoPlayMode.ENABLED
    p.queue.put(queued)
    p.auto_queue.put(recommended)
    p.recommendation_seeds.append(first)
    p._previous_seed_ids.append(first.identifier)

    await p.play(first)
    stopped = await p.stop()

    assert stopped is first
    assert p.current is None
    assert p.queue.is_empty
    assert p.auto_queue.is_empty
    assert p.recommendation_seeds == []
    assert list(p._previous_seed_ids) == []


async def test_user_play_cancels_pending_autoplay_advance() -> None:
    node = FakeNode()
    p = player(node)
    seed = track("seed")
    auto = track("auto")
    manual = track("manual")
    provider = BlockingRecommendationProvider(auto)
    p.autoplay = fluxwave.AutoPlayMode.ENABLED
    p.recommendation_provider = provider

    p._on_node_track_end(fluxwave.TrackEndEvent(123, seed, "finished"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)

    await p.play(manual)
    provider.release.set()
    await asyncio.sleep(0)

    assert p.current is manual
    assert node.updates[-1].encoded_track == "manual"
    assert p.auto_queue.is_empty


async def test_user_enqueue_cancels_pending_autoplay_advance() -> None:
    node = FakeNode()
    p = player(node)
    seed = track("seed")
    auto = track("auto")
    queued = track("queued")
    provider = BlockingRecommendationProvider(auto)
    p.autoplay = fluxwave.AutoPlayMode.ENABLED
    p.recommendation_provider = provider

    p._on_node_track_end(fluxwave.TrackEndEvent(123, seed, "finished"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)

    await p.enqueue(queued)
    provider.release.set()
    await asyncio.sleep(0)

    assert p.current is None
    assert p.queue.peek() is queued
    assert p.auto_queue.is_empty


async def test_autoplay_advance_catches_failed_play_and_tries_next_track() -> None:
    class OneFailureNode(FakeNode):
        def __init__(self) -> None:
            super().__init__()
            self.failures_remaining = 1

        async def update_player(
            self,
            guild_id: int,
            update: fluxwave.PlayerUpdate,
            *,
            replace: bool = False,
        ) -> fluxwave.LavalinkPlayer:
            if self.failures_remaining:
                self.failures_remaining -= 1
                response = fluxwave.LavalinkErrorResponse(
                    timestamp=None,
                    status=500,
                    error="Server Error",
                    message="failed",
                )
                raise fluxwave.LavalinkError(response)
            return await super().update_player(guild_id, update, replace=replace)

    node = OneFailureNode()
    p = player(node)
    seed = track("seed")
    failed = track("failed")
    fallback = track("fallback")
    p.queue.put([failed, fallback])

    p._on_node_track_end(fluxwave.TrackEndEvent(123, seed, "finished"))
    await asyncio.sleep(0)

    assert p.current is fallback
    assert node.updates[-1].encoded_track == "fallback"


async def test_load_failed_stops_autoplay_after_error_limit() -> None:
    node = FakeNode()
    p = player(node)
    p.autoplay = fluxwave.AutoPlayMode.ENABLED
    p.autoplay_error_limit = 1
    node.search_results = [track("recommended")]
    failed = track("failed")

    p._on_node_track_end(fluxwave.TrackEndEvent(123, failed, "loadFailed"))
    await asyncio.sleep(0)

    assert p.current is None


async def test_autoplay_populates_recommendations_when_enabled() -> None:
    node = FakeNode()
    seed = track("seed")
    recommended = track("recommended")
    node.search_results = [seed, recommended]
    p = player(node)
    p.autoplay = fluxwave.AutoPlayMode.ENABLED

    p._on_node_track_end(fluxwave.TrackEndEvent(123, seed, "finished"))
    await asyncio.sleep(0)

    assert p.current == recommended.as_recommended()
    assert p.recommendation_seeds == [seed]
    assert p.current.recommended


async def test_autoplay_dedupes_existing_queue_and_uses_youtube_radio_query() -> None:
    node = FakeNode()
    seed = track("seed")
    duplicate = track("duplicate")
    recommended = track("recommended")
    node.search_results = [duplicate, recommended]
    p = player(node)
    p.queue.put(duplicate)

    added = await p.populate_autoplay(seed, limit=2)

    assert added == 1
    assert p.auto_queue.peek() == recommended.as_recommended()
    assert node.search_calls[0][0].startswith("https://music.youtube.com/watch")
    assert node.search_calls[0][1] is None


async def test_persistence_round_trips_autoplay_state() -> None:
    node = FakeNode()
    p = player(node)
    seed = track("seed")
    recommended = track("recommended")
    p.autoplay = fluxwave.AutoPlayMode.ENABLED
    p.auto_queue.put(recommended)
    p.recommendation_seeds.append(seed)
    p._previous_seed_ids.append(seed.identifier)

    state = fluxwave.PersistedState.from_dict(p.save_state().to_dict())

    assert state.autoplay_mode == "enabled"
    assert state.auto_queue_tracks == [recommended]
    assert state.recommendation_seed_tracks == [seed]
    assert state.previous_seed_ids == [seed.identifier]

    restored = player(FakeNode())
    await restored.restore_state(state)

    assert restored.autoplay is fluxwave.AutoPlayMode.ENABLED
    assert restored.auto_queue.peek() == recommended
    assert restored.recommendation_seeds == [seed]
    assert list(restored._previous_seed_ids) == [seed.identifier]


async def test_persistence_round_trips_filter_stack_state() -> None:
    node = FakeNode()
    p = player(node)
    await p.add_filter(fluxwave.Filters().bass_boost(), filter_tag="bass", apply=False)
    await p.add_filter(
        fluxwave.Filters().nightcore(),
        filter_tag="nightcore",
        preload=True,
        apply=False,
    )

    state = fluxwave.PersistedState.from_dict(p.save_state().to_dict())

    assert set(state.filter_stack_payloads) == {"bass", "nightcore"}
    assert state.preload_filter_tags == ["nightcore"]

    restored = player(FakeNode())
    await restored.restore_state(state)

    assert restored.filter_tags == ("bass", "nightcore")
    assert restored.preload_filter_tags == ("nightcore",)
    assert "equalizer" in restored.filters.to_payload()
    assert restored.filters.to_payload()["timescale"] == {
        "speed": 1.25,
        "pitch": 1.2,
        "rate": 1.0,
    }


async def test_restore_state_restores_empty_queue_mode() -> None:
    p = player(FakeNode())
    p.queue.mode = fluxwave.QueueMode.LOOP_ALL
    state = fluxwave.PersistedState.from_dict(p.save_state().to_dict())

    restored = player(FakeNode())
    await restored.restore_state(state)

    assert restored.queue.mode is fluxwave.QueueMode.LOOP_ALL
    assert list(restored.queue) == []


async def test_player_update_tracks_ping_and_state() -> None:
    node = FakeNode()
    p = player(node)
    event = fluxwave.PlayerUpdateEvent(
        guild_id=123,
        state=fluxwave.PlayerState(time=1, position=500, connected=True, ping=42),
    )

    p._on_node_player_update(event)

    assert p.ping == 42
    assert p.state["ping"] == 42


async def test_inactivity_auto_disconnects_after_empty_track_end() -> None:
    node = FakeNode()
    p = player(node)
    seed = track("seed")
    p.auto_disconnect = True
    p.inactivity_timeout = 0.001
    p.cleanup = lambda: None  # type: ignore[method-assign]

    p._on_node_track_end(fluxwave.TrackEndEvent(123, seed, "finished"))
    await asyncio.sleep(0.01)

    assert p.destroyed
    assert node.destroyed == [123]


async def test_voice_channel_safety_pauses_resumes_and_disconnects() -> None:
    node = FakeNode()
    p = player(node)
    await p.play(track("current"))
    p.auto_pause_on_empty = True
    p.auto_resume_on_member_join = True
    p.auto_disconnect = True
    p.voice_empty_timeout = 0.001
    p.cleanup = lambda: None  # type: ignore[method-assign]

    await p.check_voice_channel_safety()
    assert p.paused

    p.channel.members = [FakeMember(bot=False)]  # type: ignore[attr-defined]
    await p.check_voice_channel_safety()
    assert not p.paused

    p.channel.members = []  # type: ignore[attr-defined]
    p._current = None
    await p.check_voice_channel_safety()
    await asyncio.sleep(0.01)

    assert p.destroyed


def _sized_track(length: int) -> fluxwave.Track:
    return fluxwave.Track.from_payload(
        {
            "encoded": "sized",
            "info": {
                "identifier": "sized",
                "isSeekable": True,
                "author": "artist",
                "length": length,
                "isStream": False,
                "position": 0,
                "title": "song",
                "sourceName": "youtube",
            },
        }
    )


async def test_fade_volume_ramps_to_target() -> None:
    node = FakeNode()
    p = player(node)
    node.updates.clear()

    await p.fade_volume(0, duration=0.2, update_interval=0.05)

    volumes = [u.volume for u in node.updates if u.volume is not None]
    assert volumes, "expected volume updates during the fade"
    assert volumes[-1] == 0
    assert volumes == sorted(volumes, reverse=True)  # non-increasing ramp
    assert p.volume == 0


async def test_crossfade_play_starts_at_floor_then_ramps_up() -> None:
    node = FakeNode()
    p = player(node)
    p.enable_crossfade(duration=0.2, fade_out=False, update_interval=0.05)
    node.updates.clear()

    await p.play(track())

    # The track loads at the fade floor; the logical target volume is unchanged.
    assert node.updates[0].volume == 0
    assert p.volume == 100

    await asyncio.sleep(0.4)
    volumes = [u.volume for u in node.updates if u.volume is not None]
    assert volumes[-1] == 100  # ramped up to the target
    p.disable_crossfade()


async def test_crossfade_skips_short_tracks() -> None:
    node = FakeNode()
    p = player(node)
    p.enable_crossfade(duration=0.2, min_track_duration=10.0)
    node.updates.clear()

    await p.play(_sized_track(5_000))  # 5s < min_track_duration

    assert node.updates[0].volume == 100  # no fade floor for short tracks
    p.disable_crossfade()


async def test_crossfade_fades_out_near_end() -> None:
    node = FakeNode()
    p = player(node)
    p.enable_crossfade(
        duration=0.2,
        fade_in=False,
        fade_out=True,
        min_track_duration=0.0,
        update_interval=0.05,
    )
    node.updates.clear()

    await p.play(_sized_track(600))  # short clip so the end arrives quickly
    await asyncio.sleep(1.0)

    assert p.crossfade is not None
    assert p.crossfade.stats.fade_outs == 1
    volumes = [u.volume for u in node.updates if u.volume is not None]
    assert volumes[-1] == 0  # faded down to the floor
    p.disable_crossfade()


async def test_disable_crossfade_clears_controller() -> None:
    node = FakeNode()
    p = player(node)
    p.enable_crossfade()
    assert p.crossfade is not None

    p.disable_crossfade()
    assert p.crossfade is None


def _synced_lyrics() -> fluxwave.LyricsResult:
    return fluxwave.LyricsResult(
        text="a\nb",
        lines=[
            fluxwave.LyricsLine(text="a", timestamp=0),
            fluxwave.LyricsLine(text="b", timestamp=1_000),
        ],
        synced=True,
    )


async def test_live_lyrics_yields_current_line_then_advances() -> None:
    p = player(FakeNode())
    p._current = track()

    agen = p.live_lyrics(lyrics=_synced_lyrics(), poll_interval=0.01)
    first = await agen.__anext__()
    assert first.text == "a"

    p._last_position = 1_000  # simulate playback advancing
    second = await agen.__anext__()
    assert second.text == "b"
    await agen.aclose()


async def test_live_lyrics_stops_when_track_changes() -> None:
    p = player(FakeNode())
    p._current = track("abc")

    agen = p.live_lyrics(lyrics=_synced_lyrics(), poll_interval=0.01)
    await agen.__anext__()

    p._current = track("xyz")  # a different track ends the stream
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


async def test_live_lyrics_empty_when_nothing_playing() -> None:
    p = player(FakeNode())
    p._current = None

    agen = p.live_lyrics(lyrics=_synced_lyrics())
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


async def test_live_lyrics_raises_for_unsynced_lyrics() -> None:
    node = FakeNode()
    node.lyrics_payload = {"lines": [{"line": "no timestamps here"}]}
    p = player(node)
    p._current = track()

    agen = p.live_lyrics(poll_interval=0.01)
    with pytest.raises(fluxwave.LyricsError):
        await agen.__anext__()
