"""Discord voice protocol and playback controls."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections import deque
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from discord import Client, Guild, VoiceProtocol
    from discord.abc import Connectable, Snowflake
    from discord.types.voice import GuildVoiceState, VoiceServerUpdate
else:
    from ._libraries import Client, Connectable, Guild, Snowflake, VoiceProtocol

from .autoplay import AutoPlayMode, RecommendationProvider, SearchRecommendationProvider
from .crossfade import Crossfade, CrossfadeConfig, FadeCurve, fade_fraction
from .events import (
    EventType,
    InactivePlayerEvent,
    PlayerUpdateEvent,
    TrackEndEvent,
    TrackStartEvent,
    WebSocketClosedEvent,
)
from .events import (
    dispatch as dispatch_global_event,
)
from .exceptions import (
    ChannelTimeoutError,
    InvalidChannelError,
    InvalidNodeError,
    LavalinkError,
    LyricsError,
    PlayerError,
    QueueEmpty,
)
from .filters import Filters
from .metrics import metrics
from .node import DEFAULT_REGION_GROUPS, Node, NodeStatus, calculate_shard_id, parse_voice_region
from .persistence import PersistedState, capture
from .queue import Queue
from .rest import PlayerUpdate
from .results import EnqueueResult, LyricsLine, LyricsResult
from .search import SearchSource
from .tracing import TraceCategory, tracer
from .tracks import Playlist, Track, VoiceState
from .types import JsonObject
from .watchdog import VoiceWatchdog, WatchdogConfig

logger = logging.getLogger(__name__)
TRACK_FILTERS_USER_DATA_KEY = "fluxwaveFilters"


class GuildConnectable(Protocol):
    """Subset of Discord connectable channels FluxPlayer needs."""

    id: int
    guild: Guild


class FluxPlayer(VoiceProtocol):
    """Discord voice protocol backed by a Lavalink node."""

    def __init__(
        self,
        client: Client,
        channel: Connectable,
        *,
        node: Node | None = None,
        nodes: Sequence[Node] | None = None,
    ) -> None:
        super().__init__(client, channel)

        self.client: Client = client
        self.channel: Connectable = channel
        self._guild = self._validate_channel(channel).guild

        # Voice state must exist before node selection: _select_node reads
        # self._voice_endpoint for region-aware routing.
        self._voice_token: str | None = None
        self._voice_endpoint: str | None = None
        self._voice_session_id: str | None = None
        self._voice_channel_id: str | None = None

        self._node = node or self._select_node(nodes)
        self._home_node: Node | None = None

        self._connection_error: Exception | None = None
        self._connected = False
        self._connection_event = asyncio.Event()

        self._current: Track | None = None
        self._previous: Track | None = None
        self.queue = Queue()
        self.auto_queue = Queue()
        self._autoplay = AutoPlayMode.DISABLED
        self.recommendation_provider: RecommendationProvider = SearchRecommendationProvider(
            self.node
        )
        self.recommendation_limit = 5
        self.recommendation_seeds: list[Track] = []
        self._previous_seed_ids: deque[str] = deque(maxlen=64)
        self.autoplay_error_limit = 3
        self.auto_disconnect = False
        self.auto_pause_on_empty = False
        self.auto_resume_on_member_join = False
        self.voice_empty_timeout: float | None = None
        self._inactivity_timeout: float | None = None
        self._inactive_channel_tokens: int | None = None
        self._inactive_channel_count: int | None = None
        self._last_position = 0
        self._last_update_ms: int | None = None
        self._last_ping = -1
        self._volume = 100
        self._paused = False
        self._filters = Filters()
        self._filter_stack: dict[str, Filters] = {}
        self._preload_filter_tags: set[str] = set()
        self._destroyed = False
        self._listeners_registered = False
        self._operation_lock = asyncio.Lock()
        self._voice_update_lock = asyncio.Lock()
        self._operation_ready = asyncio.Event()
        self._operation_ready.set()
        self._autoplay_task: asyncio.Task[None] | None = None
        self._autoplay_generation = 0
        self._inactivity_task: asyncio.Task[None] | None = None
        self._voice_recovery_task: asyncio.Task[None] | None = None
        self._crossfade: Crossfade | None = None
        self._fade_task: asyncio.Task[None] | None = None
        self._suppress_next_end = False
        self._autoplay_errors = 0
        self.inactive_timeout = getattr(self.node, "inactive_player_timeout", None)
        self.inactive_channel_tokens = getattr(self.node, "inactive_channel_tokens", None)
        self._register_node_listeners()
        self.node.register_player(self)

    @property
    def node(self) -> Node:
        """Lavalink node used by this player."""

        return self._node

    @property
    def guild(self) -> Guild:
        """Discord guild owned by this voice protocol."""

        return self._guild

    @property
    def connected(self) -> bool:
        """Whether the Discord voice handshake has been sent to Lavalink."""

        return self._connected

    @property
    def is_connected(self) -> bool:
        """Compatibility alias for :attr:`connected`."""

        return self.connected

    @property
    def playing(self) -> bool:
        """Whether the player has a current loaded track."""

        return self._connected and self._current is not None

    @property
    def is_playing(self) -> bool:
        """Compatibility alias for :attr:`playing`."""

        return self.playing

    @property
    def ping(self) -> int:
        """Most recent Discord voice gateway ping from Lavalink."""

        return self._last_ping

    @property
    def state(self) -> dict[str, object]:
        """Basic serializable player state snapshot."""

        return {
            "voice": {
                "token": self._voice_token,
                "endpoint": self._voice_endpoint,
                "session_id": self._voice_session_id,
                "channel_id": self._voice_channel_id,
            },
            "connected": self._connected,
            "current": self._current,
            "position": self.position,
            "paused": self._paused,
            "volume": self._volume,
            "ping": self._last_ping,
        }

    @property
    def destroyed(self) -> bool:
        """Whether this player has been destroyed and should not be reused."""

        return self._destroyed

    @property
    def is_dead(self) -> bool:
        """Compatibility alias for :attr:`destroyed`."""

        return self.destroyed

    @property
    def current(self) -> Track | None:
        """Currently playing track, if known."""

        return self._current

    @property
    def previous(self) -> Track | None:
        """Previous track, if known."""

        return self._previous

    @property
    def volume(self) -> int:
        """Current volume value."""

        return self._volume

    @property
    def paused(self) -> bool:
        """Whether playback is paused."""

        return self._paused

    @property
    def is_paused(self) -> bool:
        """Compatibility alias for :attr:`paused`."""

        return self.paused

    @property
    def filters(self) -> Filters:
        """Current filter payload container."""

        return self._filters

    @property
    def filter_tags(self) -> tuple[str, ...]:
        """Tags currently stored in the player's filter stack."""

        return tuple(self._filter_stack)

    @property
    def preload_filter_tags(self) -> tuple[str, ...]:
        """Filter tags marked as preloaded for future playback."""

        return tuple(tag for tag in self._filter_stack if tag in self._preload_filter_tags)

    @property
    def autoplay(self) -> AutoPlayMode:
        """Current autoplay mode."""

        return self._autoplay

    @autoplay.setter
    def autoplay(self, value: AutoPlayMode) -> None:
        if not isinstance(value, AutoPlayMode):
            msg = "autoplay must be an AutoPlayMode value."
            raise ValueError(msg)

        self._autoplay = value

    @property
    def inactive_timeout(self) -> float | None:
        """Seconds before an inactive player disconnect timer can fire."""

        return self._inactivity_timeout

    @inactive_timeout.setter
    def inactive_timeout(self, value: float | None) -> None:
        if value is None or value <= 0:
            self._inactivity_timeout = None
            self._cancel_inactivity_timer()
            return

        self._inactivity_timeout = value
        self._cancel_inactivity_timer()
        if self.connected and self._current is None:
            self._schedule_inactivity_timer()

    @property
    def inactivity_timeout(self) -> float | None:
        """FluxWave alias for `inactive_timeout`."""

        return self.inactive_timeout

    @inactivity_timeout.setter
    def inactivity_timeout(self, value: float | None) -> None:
        self.inactive_timeout = value

    @property
    def inactive_channel_tokens(self) -> int | None:
        """Track-end token count before inactive-channel events are dispatched."""

        return self._inactive_channel_tokens

    @inactive_channel_tokens.setter
    def inactive_channel_tokens(self, value: int | None) -> None:
        if value is None or value <= 0:
            self._inactive_channel_tokens = None
            self._inactive_channel_count = None
            return

        self._inactive_channel_tokens = value
        self._inactive_channel_count = value

    @property
    def position(self) -> int:
        """Estimated playback position in milliseconds."""

        if self._paused or self._last_update_ms is None or self._current is None:
            return self._last_position

        elapsed = int(time.monotonic() * 1000) - self._last_update_ms
        return min(self._last_position + max(elapsed, 0), self._current.duration)

    @property
    def raw_position(self) -> int:
        """Last position reported by Lavalink, without client-side extrapolation.

        Unlike :attr:`position`, this only advances when a real Lavalink player
        update (or a play/seek) arrives, so it can be used to detect a stalled
        transport that the clock-based estimate would otherwise paper over.
        """

        return self._last_position

    async def on_voice_state_update(self, data: GuildVoiceState) -> None:
        """Handle Discord voice state updates."""

        channel_id = data.get("channel_id")
        if channel_id is None:
            self._connected = False
            with contextlib.suppress(Exception):
                await self.destroy()
            with contextlib.suppress(Exception):
                self.cleanup()
            return

        self._voice_channel_id = str(channel_id)
        channel = self.client.get_channel(int(channel_id))
        if channel is not None:
            self.channel = cast(Connectable, channel)
        session_id = data.get("session_id")
        if isinstance(session_id, str):
            self._voice_session_id = session_id

        await self._dispatch_voice_update()
        await self.check_voice_channel_safety()

    async def on_voice_server_update(self, data: VoiceServerUpdate) -> None:
        """Handle Discord voice server updates."""

        token = data.get("token")
        endpoint = data.get("endpoint")
        if isinstance(token, str):
            self._voice_token = token
        if isinstance(endpoint, str):
            self._voice_endpoint = endpoint
        elif endpoint is None:
            self._voice_endpoint = None
            self._connected = False

        await self._dispatch_voice_update()

    async def connect(
        self,
        *,
        timeout: float = 60.0,  # noqa: ASYNC109 - discord.py's VoiceProtocol API.
        reconnect: bool = False,
        self_deaf: bool = False,
        self_mute: bool = False,
    ) -> None:
        """Connect Discord voice and wait until Lavalink receives voice state."""

        async with self._operation_lock:
            self._operation_ready.clear()
            try:
                self._ensure_usable()
                self._validate_channel(self.channel)
                self._connection_event.clear()
                self._connection_error = None
                await self.guild.change_voice_state(
                    channel=cast(Snowflake, self.channel),
                    self_deaf=self_deaf,
                    self_mute=self_mute,
                )

                try:
                    async with asyncio.timeout(timeout):
                        await self._connection_event.wait()
                except TimeoutError as exc:
                    metrics.voice_timeout_count += 1
                    if not reconnect:
                        with contextlib.suppress(Exception):
                            await self.destroy()
                        with contextlib.suppress(Exception):
                            await self.guild.change_voice_state(channel=None)
                        with contextlib.suppress(AttributeError, KeyError):
                            self.cleanup()
                    msg = f"Timed out connecting player for guild {self.guild.id}."
                    raise ChannelTimeoutError(msg) from exc

                if self._connection_error is not None:
                    msg = f"Failed to connect player for guild {self.guild.id}."
                    raise PlayerError(msg) from self._connection_error

                tracer.trace(
                    TraceCategory.VOICE,
                    "connected",
                    guild_id=self.guild.id,
                    node_id=self.node.identifier,
                )
            finally:
                self._operation_ready.set()

    async def move_to(
        self,
        channel: Connectable,
        *,
        timeout: float = 60.0,  # noqa: ASYNC109 - public voice APIs commonly use this name.
    ) -> None:
        """Move this player to another voice channel."""

        async with self._operation_lock:
            self._operation_ready.clear()
            try:
                self._ensure_usable()
                validated = self._validate_channel(channel)
                if validated.guild.id != self.guild.id:
                    msg = "Cannot move a player to a channel from another guild."
                    raise InvalidChannelError(msg)

                old_channel = self.channel
                old_guild = self._guild
                self._connection_event.clear()
                self._connection_error = None
                await self.guild.change_voice_state(channel=cast(Snowflake, channel))

                try:
                    async with asyncio.timeout(timeout):
                        await self._connection_event.wait()
                except TimeoutError as exc:
                    self.channel = old_channel
                    self._guild = old_guild
                    msg = f"Timed out moving player for guild {self.guild.id}."
                    raise ChannelTimeoutError(msg) from exc

                if self._connection_error is not None:
                    self.channel = old_channel
                    self._guild = old_guild
                    msg = f"Failed to move player for guild {self.guild.id}."
                    raise PlayerError(msg) from self._connection_error

                self.channel = channel
                self._guild = validated.guild
            finally:
                self._operation_ready.set()

    async def disconnect(self, *, force: bool = False) -> None:
        """Disconnect from Discord voice and destroy the Lavalink player."""

        if self._destroyed and not force:
            return

        async with self._operation_lock:
            # Re-check under the lock: a racing disconnect (node close, inactivity
            # timer, explicit call) may have already torn the player down while we
            # were waiting, and the voice cleanup below is not safe to repeat.
            if self._destroyed and not force:
                return
            self._operation_ready.clear()
            try:
                await self.destroy()
            finally:
                try:
                    await self.guild.change_voice_state(channel=None)
                    with contextlib.suppress(AttributeError, KeyError):
                        self.cleanup()
                finally:
                    self._operation_ready.set()

    async def play(
        self,
        track: Track,
        *,
        replace: bool = True,
        start: int = 0,
        end: int | None = None,
        volume: int | None = None,
        paused: bool | None = None,
        filters: Filters | None = None,
        add_history: bool = True,
        populate: bool = False,
        max_populate: int = 5,
        cancel_autoplay: bool = True,
    ) -> Track:
        """Play a track through Lavalink."""

        self._ensure_usable()
        if cancel_autoplay:
            self._cancel_autoplay_task()

        old_current = self._current
        old_previous = self._previous
        old_position = self._last_position
        old_update_ms = self._last_update_ms
        old_volume = self._volume
        old_paused = self._paused
        old_filters = self._filters

        track_was_loaded = replace or self._current is None

        next_volume = self._clamp_volume(volume if volume is not None else self._volume)
        next_paused = self._paused if paused is None else paused
        if filters is not None:
            next_filters = filters
        elif track_was_loaded:
            # Only adopt the new track's preloaded filters when it actually loads.
            # With replace=False and a track already playing, Lavalink ignores the
            # new track, so deriving filters from it would wrongly mutate the
            # currently playing track's audio.
            next_filters = self._filters_for_track(track) or self._filters
        else:
            next_filters = self._filters

        if track_was_loaded:
            self._previous = self._current
            self._current = track

        self._volume = next_volume
        self._paused = next_paused
        self._filters = next_filters
        self._last_position = max(start, 0)
        self._last_update_ms = int(time.monotonic() * 1000)

        # With crossfade enabled, a newly loaded track starts at the fade floor so
        # the controller can ramp it up; self._volume stays at the real target.
        send_volume = next_volume
        if track_was_loaded and self._crossfade is not None:
            send_volume = self._crossfade.initial_play_volume(
                track, next_volume, paused=next_paused
            )

        try:
            await self.node.update_player(
                self.guild.id,
                PlayerUpdate(
                    encoded_track=track.encoded,
                    user_data=track.user_data,
                    position=max(start, 0),
                    end_time=end,
                    volume=send_volume,
                    paused=next_paused,
                    filters=next_filters.to_payload(),
                ),
                replace=replace,
            )
        except Exception:
            # Roll back the optimistic local state on any failure (Lavalink error,
            # lost session/node error, connection error, cancellation) so the
            # player never reports a phantom current track that Lavalink never got.
            self._current = old_current
            self._previous = old_previous
            self._last_position = old_position
            self._last_update_ms = old_update_ms
            self._volume = old_volume
            self._paused = old_paused
            self._filters = old_filters
            raise

        if not track_was_loaded:
            self._last_position = old_position
            self._last_update_ms = old_update_ms

        loaded_track = track if track_was_loaded else old_current
        if track_was_loaded:
            self.queue.loaded = track
            metrics.track_play_count += 1
            tracer.trace(
                TraceCategory.PLAYER,
                "play",
                guild_id=self.guild.id,
                node_id=self.node.identifier,
                track=track.title,
            )
        if track_was_loaded and add_history and self.queue.history is not None:
            self.queue.history.put(track)
        if track_was_loaded and populate:
            await self.populate_autoplay(track, limit=max_populate)
        if track_was_loaded and self._crossfade is not None:
            self._crossfade.on_track_loaded(track, next_volume, paused=next_paused)
        self._cancel_inactivity_timer()
        return loaded_track or track

    async def enqueue(
        self,
        item: str | Track | Iterable[Track] | Playlist,
        /,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        use_cache: bool = True,
        shuffle: bool = False,
        limit: int | None = None,
        filters: Filters | None = None,
    ) -> EnqueueResult:
        """Search or append tracks to the queue and return a command-friendly result."""

        self._ensure_usable()
        self._cancel_autoplay_task()
        tracks, playlist = await self._resolve_item(
            item,
            source=source,
            use_cache=use_cache,
            shuffle=shuffle,
            limit=limit,
            filters=filters,
        )
        if not tracks:
            return EnqueueResult(added=0, source=str(source) if source is not None else None)

        self.queue.put(tracks)
        return EnqueueResult(
            added=len(tracks),
            tracks=tracks,
            playlist=playlist,
            first_track=tracks[0],
            source=str(source) if source is not None else None,
            filters=filters,
            message=f"Queued {len(tracks)} track{'s' if len(tracks) != 1 else ''}.",
        )

    async def play_search(
        self,
        query: str,
        /,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        use_cache: bool = True,
        replace: bool = True,
        filters: Filters | None = None,
    ) -> EnqueueResult:
        """Search for a query and immediately play the first playable result."""

        self._ensure_usable()
        self._cancel_autoplay_task()
        tracks, playlist = await self._resolve_item(
            query,
            source=source,
            use_cache=use_cache,
            filters=filters,
        )
        if not tracks:
            return EnqueueResult(added=0, source=str(source) if source is not None else None)

        requested = tracks[0]
        played = await self.play(requested, replace=replace, filters=filters)
        was_loaded = played is requested
        message = (
            f"Playing {requested.title}."
            if was_loaded
            else f"Requested {requested.title}; current track was not replaced."
        )
        return EnqueueResult(
            added=1,
            tracks=[requested],
            playlist=playlist,
            first_track=requested,
            source=str(source) if source is not None else None,
            filters=filters,
            message=message,
        )

    async def play_next(
        self,
        item: str | Track | Iterable[Track] | Playlist,
        /,
        *,
        source: SearchSource | str | None = SearchSource.YOUTUBE,
        use_cache: bool = True,
        shuffle: bool = False,
        limit: int | None = None,
        filters: Filters | None = None,
    ) -> EnqueueResult:
        """Search or insert tracks at the front of the queue."""

        self._ensure_usable()
        self._cancel_autoplay_task()
        tracks, playlist = await self._resolve_item(
            item,
            source=source,
            use_cache=use_cache,
            shuffle=shuffle,
            limit=limit,
            filters=filters,
        )
        if not tracks:
            return EnqueueResult(added=0, source=str(source) if source is not None else None)

        self.queue.put_at(0, tracks)
        return EnqueueResult(
            added=len(tracks),
            tracks=tracks,
            playlist=playlist,
            first_track=tracks[0],
            source=str(source) if source is not None else None,
            filters=filters,
            message=f"Queued {len(tracks)} track{'s' if len(tracks) != 1 else ''} next.",
        )

    async def fetch_lyrics(self) -> LyricsResult | None:
        """Fetch lyrics for the current player when a lyrics plugin is installed."""

        self._ensure_usable()
        if self._current is None:
            return None

        try:
            payload = await self.node.plugins.lyrics.current(self.guild.id)
        except LavalinkError:
            # Lyrics are best-effort: the plugin may be absent, the track may have
            # no lyrics, or the server's lyrics source may be unconfigured. Return
            # None rather than surfacing a raw Lavalink error from a helper command.
            return None

        if not isinstance(payload, dict):
            return LyricsResult(text=str(payload or ""), raw={})

        return self._parse_lyrics_payload(payload)

    async def current_lyrics(self) -> str | None:
        """Return current-track lyrics text for simple bot commands."""

        result = await self.fetch_lyrics()
        return result.text if result is not None else None

    async def live_lyrics(
        self,
        *,
        lyrics: LyricsResult | None = None,
        poll_interval: float = 0.5,
    ) -> AsyncIterator[LyricsLine]:
        """Yield the current lyric line as the track plays, karaoke-style.

        Requires a lyrics plugin that returns time-synced lines. Iteration ends
        cleanly when the track finishes, changes, or the player is destroyed, so a
        bot can drive a live-updating now-playing message::

            async for line in player.live_lyrics():
                await message.edit(content=line.text)

        Pass an already-fetched ``lyrics`` result to skip a second request. A
        backward seek re-syncs to the correct line, and a pause simply holds on the
        current line until playback resumes. Raises
        :class:`~fluxwave.LyricsError` when the current track has no synced lyrics.
        """

        self._ensure_usable()
        track = self._current
        if track is None:
            return

        if lyrics is None:
            lyrics = await self.fetch_lyrics()
        if lyrics is None:
            msg = "No lyrics are available for the current track."
            raise LyricsError(msg)
        if not lyrics.synced:
            msg = "Lyrics for the current track are not time-synced."
            raise LyricsError(msg)

        interval = max(0.05, poll_interval)
        last_timestamp: int | None = None
        while not self._destroyed:
            current = self._current
            if current is None or current.identifier != track.identifier:
                return
            line = lyrics.at(self.position)
            if line is not None and line.timestamp != last_timestamp:
                last_timestamp = line.timestamp
                yield line
            await asyncio.sleep(interval)

    async def check_voice_channel_safety(self) -> None:
        """Apply configured empty-channel pause/resume/disconnect behavior."""

        members = self._non_bot_member_count()
        if members <= 0:
            if self.auto_pause_on_empty and self._current is not None and not self._paused:
                await self.pause(True)
            if self.auto_disconnect:
                # Use the empty-channel timeout for this timer only; do not
                # overwrite the player's general inactive_timeout, or it would
                # stay shortened forever after the channel first empties.
                self._schedule_inactivity_timer(self.voice_empty_timeout)
            return

        self._inactive_channel_count = self.inactive_channel_tokens
        self._cancel_inactivity_timer()
        if self.auto_resume_on_member_join and self._current is not None and self._paused:
            await self.resume()

    async def populate_autoplay(
        self,
        seed: Track | None = None,
        *,
        limit: int | None = None,
    ) -> int:
        """Populate the autoplay queue from a seed track."""

        self._ensure_usable()
        seed = seed or self._current or self._previous
        if seed is None:
            return 0

        added = 0
        max_tracks = limit if limit is not None else self.recommendation_limit
        seen = self._autoplay_exclusion_keys()

        for recommendation_seed in self._recommendation_seed_candidates(seed):
            if recommendation_seed.identifier in self._previous_seed_ids:
                continue

            self._previous_seed_ids.append(recommendation_seed.identifier)
            self.recommendation_seeds.append(recommendation_seed)
            recommendations = await self.recommendation_provider.recommendations(
                recommendation_seed,
                limit=max_tracks,
            )

            for track in recommendations:
                key = self._track_key(track)
                if key in seen:
                    continue
                seen.add(key)
                self.auto_queue.put(track, atomic=False)
                added += 1
                if added >= max_tracks:
                    return added

        return added

    async def switch_node(
        self,
        new_node: Node,
        *,
        allow_disconnected_source: bool = False,
    ) -> None:
        """Migrate this player to another connected node."""

        if self._destroyed:
            msg = "This player has been destroyed and cannot be reused."
            raise PlayerError(msg)
        if not allow_disconnected_source and self.node.status is not NodeStatus.CONNECTED:
            msg = "The player's Lavalink node is not connected."
            raise InvalidNodeError(msg)
        if new_node.status is not NodeStatus.CONNECTED:
            msg = "Cannot switch player to a node that is not connected."
            raise PlayerError(msg)

        if new_node.identifier == self.node.identifier:
            msg = "Cannot switch player to the same Lavalink node."
            raise PlayerError(msg)

        async with self._operation_lock:
            self._operation_ready.clear()
            try:
                old_node = self.node
                current = self._current
                position = self.position
                volume = self._volume
                paused = self._paused
                filters = self._filters

                self._unregister_node_listeners()
                old_node.unregister_player(self.guild.id)
                self._node = new_node
                self.recommendation_provider = SearchRecommendationProvider(self.node)
                self._register_node_listeners()
                self.node.register_player(self)

                try:
                    await self._dispatch_voice_update()
                    if current is not None:
                        await self.play(
                            current,
                            replace=True,
                            start=position,
                            volume=volume,
                            paused=paused,
                            filters=filters,
                            # The track is already in history from when it first
                            # started; a node switch must not duplicate it.
                            add_history=False,
                        )
                    else:
                        await self.set_filters(filters)
                        await self.set_volume(volume)
                        await self.pause(paused)
                except Exception as exc:
                    self._unregister_node_listeners()
                    self.node.unregister_player(self.guild.id)
                    # Tear down any half-created Lavalink player left on the target
                    # node (e.g. from the voice update) so it does not leak.
                    with contextlib.suppress(Exception):
                        await new_node.destroy_player(self.guild.id)
                    self._node = old_node
                    self.recommendation_provider = SearchRecommendationProvider(self.node)
                    self._register_node_listeners()
                    self.node.register_player(self)
                    msg = (
                        f"Failed to switch player for guild {self.guild.id} "
                        f"to node {new_node.identifier!r}."
                    )
                    raise PlayerError(msg) from exc

                with contextlib.suppress(Exception):
                    await old_node.destroy_player(self.guild.id)

                metrics.node_switch_count += 1
                tracer.trace(
                    TraceCategory.MIGRATION,
                    "switch_node",
                    guild_id=self.guild.id,
                    node_id=old_node.identifier,
                    target=new_node.identifier,
                )
            finally:
                self._operation_ready.set()

    def save_state(self, *, extra: dict[str, object] | None = None) -> PersistedState:
        """Capture the current player state as a serialisable
        :class:`~fluxwave.persistence.PersistedState`.

        Does not interact with Lavalink — pure in-memory snapshot::

            state = player.save_state()
            await store.save(player.guild.id, state)
        """

        return capture(self, extra=extra)

    async def restore_state(self, state: PersistedState, *, seek: bool = True) -> None:
        """Restore player state from a :class:`~fluxwave.persistence.PersistedState`.

        Restores: queue, history, volume, filters, paused state, and optionally
        resumes the current track from the saved position.

        The player must already be connected to a voice channel::

            state = await store.load(guild_id)
            if state:
                await player.restore_state(state)
        """

        if not isinstance(state, PersistedState):
            msg = "state must be a PersistedState instance."
            raise TypeError(msg)

        self._ensure_usable()

        self.queue = Queue.from_payloads(
            state.queue_payloads,
            history_payloads=state.history_payloads,
            mode=state.queue_mode,
        )

        self.auto_queue = Queue.from_payloads(
            state.auto_queue_payloads,
            history_payloads=state.auto_queue_history_payloads,
        )
        try:
            self.autoplay = AutoPlayMode(state.autoplay_mode)
        except ValueError:
            self.autoplay = AutoPlayMode.DISABLED
        self.recommendation_seeds = state.recommendation_seed_tracks
        self._previous_seed_ids.clear()
        self._previous_seed_ids.extend(state.previous_seed_ids)

        self._filter_stack = {
            tag: Filters.from_payload(payload)
            for tag, payload in state.filter_stack_payloads.items()
        }
        self._preload_filter_tags = {
            tag for tag in state.preload_filter_tags if tag in self._filter_stack
        }
        if self._filter_stack:
            self._filters = self._compose_filter_stack()
        elif state.filters_payload:
            self._filters = Filters.from_payload(state.filters_payload)

        await self.set_volume(state.volume)

        current = state.current_track
        if current is not None:
            start = state.current_position if seek else 0
            await self.play(
                current,
                replace=True,
                start=start,
                volume=state.volume,
                paused=state.is_paused,
                filters=self._filters,
            )
        elif state.is_paused:
            await self.pause(True)

    def start_watchdog(self, config: WatchdogConfig | None = None) -> VoiceWatchdog:
        """Attach and start a :class:`~fluxwave.watchdog.VoiceWatchdog` for this player.

        Returns the watchdog so callers can inspect its stats or stop it::

            watchdog = player.start_watchdog()
            # later:
            print(watchdog.stats.recoveries)
        """

        watchdog = VoiceWatchdog(self, config)
        watchdog.start()
        return watchdog

    async def recover_voice_state(self) -> None:
        """Re-send voice and playback state after a reconnect or resume miss."""

        self._ensure_usable()
        await self._dispatch_voice_update()
        if self._current is None:
            return

        await self.node.update_player(
            self.guild.id,
            PlayerUpdate(
                encoded_track=self._current.encoded,
                user_data=self._current.user_data,
                position=self.position,
                volume=self._volume,
                paused=self._paused,
                filters=self._filters.to_payload(),
            ),
            replace=True,
        )

    @property
    def crossfade(self) -> Crossfade | None:
        """The active :class:`~fluxwave.Crossfade` controller, if enabled."""

        return self._crossfade

    def enable_crossfade(
        self,
        duration: float = 4.0,
        *,
        fade_in: bool = True,
        fade_out: bool = True,
        curve: FadeCurve = FadeCurve.SMOOTH,
        floor_volume: int = 0,
        update_interval: float = 0.2,
        min_track_duration: float = 10.0,
    ) -> Crossfade:
        """Enable smooth volume transitions between tracks and return the controller.

        Crossfade is entirely opt-in; without calling this, playback behaves
        exactly as before. Lavalink plays one track per player, so this fades the
        ending track down and the next one up rather than overlapping them::

            player.enable_crossfade(5)  # 5-second fades
        """

        config = CrossfadeConfig(
            duration=duration,
            fade_in=fade_in,
            fade_out=fade_out,
            curve=curve,
            floor_volume=floor_volume,
            update_interval=update_interval,
            min_track_duration=min_track_duration,
        )
        return self.set_crossfade(config)

    def set_crossfade(self, config: CrossfadeConfig) -> Crossfade:
        """Enable crossfade from an explicit :class:`~fluxwave.CrossfadeConfig`."""

        self.disable_crossfade()
        self._crossfade = Crossfade(self, config)
        if self._current is not None and not self._paused:
            self._crossfade.start_for_current()
        return self._crossfade

    def disable_crossfade(self) -> None:
        """Disable crossfade and cancel any in-progress fade."""

        if self._crossfade is not None:
            self._crossfade.cancel()
            self._crossfade = None
        self._cancel_volume_fade()

    async def fade_volume(
        self,
        target: int,
        *,
        duration: float = 1.0,
        curve: FadeCurve = FadeCurve.SMOOTH,
        update_interval: float = 0.1,
    ) -> None:
        """Smoothly ramp the volume to *target* over *duration* seconds.

        A standalone primitive that works with or without crossfade enabled; it
        supersedes any fade already in progress::

            await player.fade_volume(0, duration=3)  # gentle fade to silence
        """

        self._ensure_usable()
        task = self._start_volume_fade(
            self._volume,
            self._clamp_volume(target),
            duration=duration,
            curve=curve,
            update_interval=update_interval,
            commit=True,
        )
        try:
            await task
        except asyncio.CancelledError:
            if task.cancelled():
                return
            raise

    @property
    def _fade_active(self) -> bool:
        return self._fade_task is not None and not self._fade_task.done()

    def _cancel_volume_fade(self) -> None:
        if self._fade_task is not None and not self._fade_task.done():
            self._fade_task.cancel()
        self._fade_task = None

    def _start_volume_fade(
        self,
        start: int,
        end: int,
        *,
        duration: float,
        curve: FadeCurve,
        update_interval: float,
        commit: bool,
    ) -> asyncio.Task[None]:
        self._cancel_volume_fade()
        self._fade_task = asyncio.create_task(
            self._volume_fade_loop(start, end, duration, curve, update_interval, commit),
            name=f"fluxwave:fade:{self.guild.id}",
        )
        return self._fade_task

    async def _volume_fade_loop(
        self,
        start: int,
        end: int,
        duration: float,
        curve: FadeCurve,
        update_interval: float,
        commit: bool,
    ) -> None:
        start = self._clamp_volume(start)
        end = self._clamp_volume(end)
        if duration <= 0 or start == end:
            if start != end:
                with contextlib.suppress(Exception):
                    await self.node.update_player(self.guild.id, PlayerUpdate(volume=end))
            if commit and not self._destroyed:
                self._volume = end
            return

        steps = max(1, round(duration / max(update_interval, 0.01)))
        last = start
        try:
            for index in range(1, steps + 1):
                if self._destroyed or self.node.status is not NodeStatus.CONNECTED:
                    return
                fraction = fade_fraction(curve, index / steps)
                volume = self._clamp_volume(round(start + (end - start) * fraction))
                if volume != last:
                    await self.node.update_player(self.guild.id, PlayerUpdate(volume=volume))
                    last = volume
                if commit:
                    self._volume = volume
                if index < steps:
                    await asyncio.sleep(update_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Volume fade aborted for guild %s.", self.guild.id, exc_info=True)
        finally:
            if commit and not self._destroyed:
                self._volume = end

    async def _restore_volume(self) -> None:
        with contextlib.suppress(Exception):
            await self.node.update_player(self.guild.id, PlayerUpdate(volume=self._volume))

    async def pause(self, value: bool = True) -> None:
        """Pause or resume playback."""

        self._ensure_usable()
        await self.node.update_player(self.guild.id, PlayerUpdate(paused=value))
        self._last_position = self.position
        self._last_update_ms = int(time.monotonic() * 1000)
        self._paused = value

    async def resume(self) -> None:
        """Resume playback."""

        await self.pause(False)

    async def seek(self, position: int = 0) -> None:
        """Seek the current track to a millisecond position."""

        self._ensure_usable()
        if self._current is None:
            return

        position = max(position, 0)
        await self.node.update_player(self.guild.id, PlayerUpdate(position=position))
        self._last_position = position
        self._last_update_ms = int(time.monotonic() * 1000)
        if self._crossfade is not None:
            await self._crossfade.on_seek()

    async def set_volume(self, value: int = 100) -> None:
        """Set playback volume between 0 and 1000."""

        self._ensure_usable()
        # An explicit volume change wins over any active fade.
        self._cancel_volume_fade()
        volume = self._clamp_volume(value)
        await self.node.update_player(self.guild.id, PlayerUpdate(volume=volume))
        self._volume = volume

    async def set_filters(self, filters: Filters | None = None, *, seek: bool = False) -> None:
        """Apply filters to the player and clear the tagged filter stack."""

        self._ensure_usable()
        filters = filters or Filters()
        self._filter_stack.clear()
        self._preload_filter_tags.clear()
        await self._apply_filters(filters, seek=seek)

    async def add_filter(
        self,
        filters: Filters,
        /,
        *,
        filter_tag: str = "default",
        seek: bool = False,
        preload: bool = False,
        apply: bool = True,
    ) -> Filters:
        """Add a tagged filter to the stack and optionally apply the composed result.

        Later tags override earlier tags when both set the same Lavalink filter
        section.  ``preload=True`` updates local filter state for future
        playback without requiring an immediate Lavalink update when no track is
        loaded.
        """

        self._ensure_usable()
        tag = self._validate_filter_tag(filter_tag)
        self._filter_stack[tag] = Filters.copy(filters)
        if preload:
            self._preload_filter_tags.add(tag)
        else:
            self._preload_filter_tags.discard(tag)

        composed = self._compose_filter_stack()
        if apply and (not preload or self.current is not None):
            await self._apply_filters(composed, seek=seek)
        else:
            self._filters = composed
        return composed

    async def edit_filter(
        self,
        filter_tag: str,
        filters: Filters,
        /,
        *,
        seek: bool = False,
        preload: bool | None = None,
        apply: bool = True,
    ) -> Filters:
        """Replace an existing tagged filter and optionally apply the stack."""

        tag = self._validate_filter_tag(filter_tag)
        if tag not in self._filter_stack:
            msg = f"No filter exists with tag {tag!r}."
            raise PlayerError(msg)

        keep_preload = tag in self._preload_filter_tags if preload is None else preload
        return await self.add_filter(
            filters,
            filter_tag=tag,
            seek=seek,
            preload=keep_preload,
            apply=apply,
        )

    async def remove_filter(
        self,
        filter_tag: str,
        /,
        *,
        seek: bool = False,
        apply: bool = True,
    ) -> Filters:
        """Remove a tagged filter and optionally apply the composed result."""

        self._ensure_usable()
        tag = self._validate_filter_tag(filter_tag)
        self._filter_stack.pop(tag, None)
        self._preload_filter_tags.discard(tag)

        composed = self._compose_filter_stack()
        if apply:
            await self._apply_filters(composed, seek=seek)
        else:
            self._filters = composed
        return composed

    def has_filter(self, filter_tag: str) -> bool:
        """Return whether a tagged filter is stored in the stack."""

        return self._validate_filter_tag(filter_tag) in self._filter_stack

    def get_filter(self, filter_tag: str) -> Filters | None:
        """Return a copy of a tagged filter, if present."""

        tag = self._validate_filter_tag(filter_tag)
        filters = self._filter_stack.get(tag)
        return Filters.copy(filters) if filters is not None else None

    async def clear_filters(self, *, seek: bool = False, apply: bool = True) -> Filters:
        """Clear all tagged and active filters."""

        self._ensure_usable()
        self._filter_stack.clear()
        self._preload_filter_tags.clear()
        filters = Filters()
        if apply:
            await self._apply_filters(filters, seek=seek)
        else:
            self._filters = filters
        return filters

    async def _apply_filters(self, filters: Filters, *, seek: bool = False) -> None:
        """Send a filter payload to Lavalink and update local state."""

        position = self.position if seek and self._current is not None else None
        await self.node.update_player(
            self.guild.id,
            PlayerUpdate(filters=filters.to_payload(), position=position),
        )
        self._filters = filters

    async def stop(
        self,
        *,
        force: bool = True,
        clear_queue: bool = True,
        clear_autoplay: bool = True,
    ) -> Track | None:
        """Stop playback, optionally clear pending queues, and return the stopped track."""

        # Validate before mutating: don't wipe the queue if the node is down and
        # the stop can't actually be sent.
        self._ensure_usable()
        if clear_queue:
            self.queue.clear()
            self.queue.loaded = None
        if clear_autoplay:
            self._clear_autoplay_state()
        return await self.skip(force=force, play_next=False)

    async def skip(
        self,
        *,
        force: bool | None = None,
        play_next: bool | None = None,
    ) -> Track | None:
        """Stop the current track and optionally play the next queued track."""

        self._ensure_usable()
        self._cancel_autoplay_task()
        self._cancel_volume_fade()
        old = self._current
        should_play_next = True if play_next is None else play_next
        if force:
            self.queue.loaded = None

        if should_play_next and self.queue:
            next_track = self.queue.get(bypass_loop=bool(force))
            await self.play(
                next_track,
                replace=True,
                add_history=False,
                cancel_autoplay=False,
            )
            return old

        if should_play_next and self.autoplay is AutoPlayMode.ENABLED and old is not None:
            autoplay_track = self._next_from_queue(self.auto_queue)
            if autoplay_track is not None:
                await self.play(
                    autoplay_track,
                    replace=True,
                    add_history=False,
                    cancel_autoplay=False,
                )
                return old

            try:
                await self.populate_autoplay(old)
            except Exception:
                logger.exception(
                    "Failed to populate autoplay during manual skip for guild %s.",
                    self.guild.id,
                )

            autoplay_track = self._next_from_queue(self.auto_queue)
            if autoplay_track is not None:
                await self.play(
                    autoplay_track,
                    replace=True,
                    add_history=False,
                    cancel_autoplay=False,
                )
                return old

        self._suppress_next_end = True
        await self.node.update_player(
            self.guild.id,
            PlayerUpdate(clear_track=True),
            replace=True,
        )
        self._previous = old
        self._current = None
        self._last_position = 0
        self._last_update_ms = None
        self._paused = False
        self._schedule_inactivity_timer()
        return old

    async def _resolve_item(
        self,
        item: str | Track | Iterable[Track] | Playlist,
        /,
        *,
        source: SearchSource | str | None,
        use_cache: bool,
        shuffle: bool = False,
        limit: int | None = None,
        filters: Filters | None = None,
    ) -> tuple[list[Track], Playlist | None]:
        if isinstance(item, Track):
            return self._attach_search_filters([item], filters), None

        if isinstance(item, Playlist):
            return self._attach_search_filters(
                item.playable_tracks(shuffle=shuffle, limit=limit),
                filters,
            ), item

        if isinstance(item, str):
            result = await self.node.search(item, source=source, use_cache=use_cache)
            if isinstance(result, Playlist):
                return self._attach_search_filters(
                    result.playable_tracks(shuffle=shuffle, limit=limit),
                    filters,
                ), result
            tracks = result[:1]
            return self._attach_search_filters(
                tracks if limit is None else tracks[:limit],
                filters,
            ), None

        tracks = list(item)
        if limit is not None:
            if limit < 0:
                msg = "Track limit cannot be negative."
                raise ValueError(msg)
            tracks = tracks[:limit]
        return self._attach_search_filters(tracks, filters), None

    @staticmethod
    def _attach_search_filters(tracks: list[Track], filters: Filters | None) -> list[Track]:
        if filters is None:
            return tracks

        payload = filters.to_payload()
        return [track.with_user_data(**{TRACK_FILTERS_USER_DATA_KEY: payload}) for track in tracks]

    @staticmethod
    def _filters_for_track(track: Track) -> Filters | None:
        payload = track.user_data.get(TRACK_FILTERS_USER_DATA_KEY)
        return Filters.from_payload(payload) if isinstance(payload, dict) else None

    @staticmethod
    def _parse_lyrics_payload(payload: JsonObject) -> LyricsResult:
        lines_payload = payload.get("lines") or payload.get("lyrics")
        lines: list[LyricsLine] = []
        text_parts: list[str] = []
        if isinstance(lines_payload, list):
            for item in lines_payload:
                if isinstance(item, dict):
                    line_text = str(item.get("line") or item.get("text") or "")
                    timestamp = item.get("timestamp") or item.get("time")
                    duration = item.get("duration")
                    line = LyricsLine(
                        text=line_text,
                        timestamp=timestamp if isinstance(timestamp, int) else None,
                        duration=duration if isinstance(duration, int) else None,
                        raw=item.copy(),
                    )
                else:
                    line = LyricsLine(text=str(item))
                if line.text:
                    text_parts.append(line.text)
                lines.append(line)

        text_value = payload.get("text") or payload.get("plainText")
        text = str(text_value) if isinstance(text_value, str) else "\n".join(text_parts)
        provider = payload.get("provider")
        source = payload.get("source")
        return LyricsResult(
            text=text,
            lines=lines,
            provider=provider if isinstance(provider, str) else None,
            source=source if isinstance(source, str) else None,
            synced=any(line.timestamp is not None for line in lines),
            raw=payload.copy(),
        )

    async def destroy(self) -> None:
        """Destroy the Lavalink player and invalidate local playback state."""

        if self._destroyed:
            return

        try:
            await self.node.destroy_player(self.guild.id)
        finally:
            self._unregister_node_listeners()
            self.node.unregister_player(self.guild.id)
            self._home_node = None
            self._destroyed = True
            self._connected = False
            self._connection_event.clear()
            self._current = None
            self.queue.reset()
            self.auto_queue.reset()
            self._cancel_inactivity_timer()
            self._cancel_volume_fade()
            if self._crossfade is not None:
                self._crossfade.cancel()
            self._clear_autoplay_state()
            self._last_position = 0
            self._last_update_ms = None
            self._paused = False
            self._suppress_next_end = False
            self._autoplay_errors = 0

    async def _dispatch_voice_update(self) -> None:
        if (
            not self._voice_token
            or not self._voice_endpoint
            or not self._voice_session_id
            or not self._voice_channel_id
        ):
            return

        async with self._voice_update_lock:
            if self._destroyed:
                return

            try:
                await self.node.update_player(
                    self.guild.id,
                    PlayerUpdate(
                        voice=VoiceState(
                            token=self._voice_token,
                            endpoint=self._voice_endpoint,
                            session_id=self._voice_session_id,
                            channel_id=self._voice_channel_id,
                        )
                    ),
                )
            except Exception as exc:
                self._connection_error = exc
                self._connected = False
                self._connection_event.set()
                return

            self._connection_error = None
            self._connected = True
            self._connection_event.set()

    def _on_node_track_start(self, event: object) -> None:
        if not isinstance(event, TrackStartEvent) or event.guild_id != self.guild.id:
            return

        event = cast(TrackStartEvent, self._enrich_track_event(event))
        self._current = event.track
        self._last_position = 0
        self._last_update_ms = int(time.monotonic() * 1000)
        self._paused = False
        self._cancel_inactivity_timer()
        self._dispatch_client_event("track_start", event)

    def _on_node_track_end(self, event: object) -> None:
        if not isinstance(event, TrackEndEvent) or event.guild_id != self.guild.id:
            return

        event = cast(TrackEndEvent, self._enrich_track_event(event))
        self._previous = event.track
        self._dispatch_client_event("track_end", event)
        if event.reason == "replaced":
            self._autoplay_errors = 0
            return

        self._current = None
        self._last_position = 0
        self._last_update_ms = None
        self._paused = False

        if self._suppress_next_end or event.reason in {"stopped", "cleanup"}:
            self._suppress_next_end = False
            self._schedule_inactivity_timer()
            return

        if event.reason == "loadFailed":
            self._autoplay_errors += 1
            if self._autoplay_errors >= self.autoplay_error_limit:
                logger.warning(
                    "Autoplay stopped for guild %s after %s consecutive load failures.",
                    self.guild.id,
                    self._autoplay_errors,
                )
                self._schedule_inactivity_timer()
                return
        else:
            self._autoplay_errors = 0

        self._handle_inactive_channel()
        if self.autoplay is AutoPlayMode.PARTIAL:
            if self._autoplay_task and not self._autoplay_task.done():
                # A partial-autoplay advance is already in flight; let it finish
                # instead of popping another track and racing it.
                return
            next_track = self._next_from_queue(self.queue)
            if next_track is not None:
                self._autoplay_generation += 1
                generation = self._autoplay_generation
                self._autoplay_task = asyncio.create_task(
                    self._play_next_partial(next_track, generation)
                )
                return
            self._schedule_inactivity_timer()
            return
        self._schedule_autoplay(event.track)

    def _on_node_player_update(self, event: object) -> None:
        if not isinstance(event, PlayerUpdateEvent) or event.guild_id != self.guild.id:
            return

        if event.player is None:
            event = replace(event, player=self)
        self._last_position = event.state.position
        self._last_update_ms = int(time.monotonic() * 1000)
        self._last_ping = event.state.ping
        self._dispatch_client_event("player_update", event)

    def _on_node_websocket_closed(self, event: object) -> None:
        if not isinstance(event, WebSocketClosedEvent) or event.guild_id != self.guild.id:
            return

        if event.player is None:
            event = replace(event, player=self)
        self._connected = False
        self._connection_event.clear()
        self._dispatch_client_event("websocket_closed", event)
        if event.by_remote and event.code in {4014, 4006, 4009, 4017}:
            logger.info(
                "Voice websocket closed for guild %s with code %s; scheduling recovery cleanup.",
                self.guild.id,
                event.code,
            )
            self._schedule_voice_recovery()
            self._schedule_inactivity_timer()

    def _enrich_track_event(
        self,
        event: TrackStartEvent | TrackEndEvent,
    ) -> TrackStartEvent | TrackEndEvent:
        return replace(
            event,
            player=event.player or self,
            original=event.original or self._current or event.track,
        )

    def _schedule_voice_recovery(self) -> None:
        if self._destroyed:
            return

        if self._voice_recovery_task and not self._voice_recovery_task.done():
            return

        self._voice_recovery_task = asyncio.create_task(self._recover_after_voice_close())

    async def _recover_after_voice_close(self) -> None:
        await self._operation_ready.wait()
        if self._destroyed:
            return

        with contextlib.suppress(Exception):
            await self.recover_voice_state()

    def _ensure_usable(self) -> None:
        if self._destroyed:
            msg = "This player has been destroyed and cannot be reused."
            raise PlayerError(msg)

        if self.node.status is not NodeStatus.CONNECTED:
            msg = "The player's Lavalink node is not connected."
            raise InvalidNodeError(msg)

    def _compose_filter_stack(self) -> Filters:
        payload: JsonObject = {}
        for filters in self._filter_stack.values():
            payload = _merge_filter_payloads(payload, filters.to_payload())

        return Filters.from_payload(payload)

    @staticmethod
    def _validate_filter_tag(filter_tag: str) -> str:
        if not isinstance(filter_tag, str):
            msg = "filter_tag must be a string."
            raise TypeError(msg)

        tag = filter_tag.strip()
        if not tag:
            msg = "filter_tag cannot be empty."
            raise ValueError(msg)

        return tag

    def _select_node(self, nodes: Sequence[Node] | None) -> Node:
        if not nodes:
            # discord.py instantiates a VoiceProtocol as cls(client, channel)
            # with no node, so the documented `channel.connect(cls=FluxPlayer)`
            # usage (after Pool.connect(...)) relies on falling back to the
            # globally-registered pool, wavelink-style.
            from .pool import Pool

            nodes = Pool.active_nodes() or list(Pool.nodes().values())

        if not nodes:
            msg = (
                "No Lavalink node available. Pass node=/nodes= to FluxPlayer, "
                "or connect a Pool (fluxwave.Pool.connect(...)) before connecting a player."
            )
            raise InvalidNodeError(msg)

        candidates = [node for node in nodes if node.status is NodeStatus.CONNECTED]
        if not candidates:
            msg = "No connected Lavalink nodes are available for this player."
            raise InvalidNodeError(msg)

        voice_region = parse_voice_region(self._voice_endpoint)
        if voice_region is not None:
            wanted = {voice_region}
            for group, aliases in DEFAULT_REGION_GROUPS.items():
                if voice_region in aliases:
                    wanted.add(group)
                    break
            regional = [
                node
                for node in candidates
                if node.regions is not None and not wanted.isdisjoint(node.regions)
            ]
            if regional:
                candidates = regional

        shard_id = calculate_shard_id(self.guild.id, getattr(self.client, "shard_count", None))
        sharded = [
            node for node in candidates if node.shard_ids is None or shard_id in node.shard_ids
        ]
        if sharded:
            candidates = sharded

        return min(candidates, key=lambda node: (node.health_score, node.identifier or ""))

    @staticmethod
    def _validate_channel(channel: Connectable) -> GuildConnectable:
        guild = getattr(channel, "guild", None)
        channel_id = getattr(channel, "id", None)
        if guild is None or not isinstance(channel_id, int):
            msg = "FluxPlayer requires a guild voice channel with an integer ID."
            raise InvalidChannelError(msg)

        guild_id = getattr(guild, "id", None)
        if not isinstance(guild_id, int) or not hasattr(guild, "change_voice_state"):
            msg = "FluxPlayer channel must belong to a valid Discord guild."
            raise InvalidChannelError(msg)

        return cast(GuildConnectable, channel)

    def _schedule_autoplay(self, seed: Track) -> None:
        if self._destroyed:
            return

        if self._autoplay_task and not self._autoplay_task.done():
            logger.debug("Autoplay advance already scheduled for guild %s.", self.guild.id)
            return

        self._autoplay_generation += 1
        generation = self._autoplay_generation
        self._autoplay_task = asyncio.create_task(self._advance_after_track_end(seed, generation))

    async def _advance_after_track_end(self, seed: Track, generation: int) -> None:
        if not self._autoplay_task_current(generation):
            return

        if await self._play_next_from_queue(self.queue, generation):
            return

        if self.autoplay is AutoPlayMode.ENABLED:
            if await self._play_next_from_queue(self.auto_queue, generation):
                return

            try:
                await self.populate_autoplay(seed)
            except Exception:
                logger.exception("Failed to populate autoplay for guild %s.", self.guild.id)

            if not self._autoplay_task_current(generation):
                return

            if await self._play_next_from_queue(self.auto_queue, generation):
                return

        logger.debug("No queued or autoplay track available for guild %s.", self.guild.id)
        self._schedule_inactivity_timer()

    async def _play_next_partial(self, track: Track, generation: int) -> None:
        if not self._autoplay_task_current(generation):
            return

        try:
            await self.play(
                track,
                replace=True,
                add_history=False,
                cancel_autoplay=False,
            )
        except Exception:
            logger.exception(
                "Failed to play next track in partial autoplay for guild %s.",
                self.guild.id,
            )
            self._schedule_inactivity_timer()

    def _cancel_autoplay_task(self) -> None:
        self._autoplay_generation += 1
        if self._autoplay_task and not self._autoplay_task.done():
            self._autoplay_task.cancel()
        self._autoplay_task = None

    def _clear_autoplay_state(self) -> None:
        self._cancel_autoplay_task()
        self.auto_queue.reset()
        self.recommendation_seeds.clear()
        self._previous_seed_ids.clear()
        self._autoplay_errors = 0

    def _autoplay_task_current(self, generation: int) -> bool:
        return not self._destroyed and generation == self._autoplay_generation

    async def _play_next_from_queue(self, queue: Queue, generation: int) -> bool:
        attempts = max(1, self.autoplay_error_limit)
        for _ in range(attempts):
            if not self._autoplay_task_current(generation):
                return True

            next_track = self._next_from_queue(queue)
            if next_track is None:
                return False

            try:
                await self.play(
                    next_track,
                    replace=True,
                    add_history=False,
                    cancel_autoplay=False,
                )
            except Exception:
                self._autoplay_errors += 1
                logger.exception(
                    "Failed to play automatically selected track for guild %s.",
                    self.guild.id,
                )
                if self._autoplay_errors >= self.autoplay_error_limit:
                    logger.warning(
                        "Autoplay stopped for guild %s after %s consecutive play failures.",
                        self.guild.id,
                        self._autoplay_errors,
                    )
                    self._schedule_inactivity_timer()
                    return True
                continue

            self._autoplay_errors = 0
            return True

        return False

    def _handle_inactive_channel(self) -> None:
        if self.inactive_channel_tokens is None or self.inactive_channel_tokens <= 0:
            return

        members = self._non_bot_member_count()
        if members > 0:
            self._inactive_channel_count = self.inactive_channel_tokens
            return

        current = self._inactive_channel_count
        if current is None:
            current = self.inactive_channel_tokens

        current -= 1
        self._inactive_channel_count = current
        if current > 0:
            return

        self._inactive_channel_count = self.inactive_channel_tokens
        self.node.dispatch(
            EventType.INACTIVE_PLAYER,
            event := InactivePlayerEvent(
                guild_id=self.guild.id,
                player=self,
                non_bot_members=members,
                remaining_tokens=current,
                node_identifier=self.node.identifier,
            ),
        )
        self._dispatch_client_event("inactive_player", event)

    def _non_bot_member_count(self) -> int:
        members = getattr(self.channel, "members", None)
        if not isinstance(members, list):
            return 0

        return sum(1 for member in members if not bool(getattr(member, "bot", False)))

    def _recommendation_seed_candidates(self, seed: Track) -> list[Track]:
        weighted: list[Track] = [seed, seed, seed]

        if self._current is not None:
            weighted.extend([self._current, self._current])
        if self._previous is not None:
            weighted.extend([self._previous, self._previous])
        if self.queue.history is not None:
            recent = list(reversed(self.queue.history[-10:]))
            for index, track in enumerate(recent):
                weighted.extend([track] * max(1, 5 - min(index, 4)))
        weighted.extend(self.auto_queue[:8])

        unique: dict[str, Track] = {}
        random.shuffle(weighted)
        for candidate in weighted:
            unique.setdefault(candidate.identifier, candidate)

        return list(unique.values())

    def _autoplay_exclusion_keys(self) -> set[str]:
        tracks: list[Track] = []
        tracks.extend(self.queue[:50])
        tracks.extend(self.auto_queue[:50])
        if self.queue.history is not None:
            tracks.extend(self.queue.history[:50])
        if self.auto_queue.history is not None:
            tracks.extend(self.auto_queue.history[:50])
        if self._current is not None:
            tracks.append(self._current)
        if self._previous is not None:
            tracks.append(self._previous)

        return {self._track_key(track) for track in tracks}

    @staticmethod
    def _track_key(track: Track) -> str:
        title = " ".join(track.title.casefold().split())
        author = " ".join(track.author.casefold().split())
        return f"{track.source or ''}:{track.identifier}:{title}:{author}"

    def _next_from_queue(self, queue: Queue, *, bypass_loop: bool = False) -> Track | None:
        try:
            return queue.get(bypass_loop=bypass_loop)
        except QueueEmpty:
            return None

    def _dispatch_client_event(self, name: str, payload: object) -> None:
        dispatch = getattr(self.client, "dispatch", None)
        if dispatch is None:
            return

        dispatch(f"fluxwave_{name}", payload)
        dispatch(f"wavelink_{name}", payload)
        dispatch_global_event(name, payload)

    def _schedule_inactivity_timer(self, timeout: float | None = None) -> None:
        duration = timeout if timeout is not None else self.inactive_timeout
        if not self.auto_disconnect or duration is None:
            return

        self._cancel_inactivity_timer()
        self._inactivity_task = asyncio.create_task(self._disconnect_after_inactivity(duration))

    def _cancel_inactivity_timer(self) -> None:
        if self._inactivity_task and not self._inactivity_task.done():
            self._inactivity_task.cancel()
        self._inactivity_task = None

    async def _disconnect_after_inactivity(self, delay: float) -> None:
        await asyncio.sleep(delay)
        if self._current is None and not self.queue and not self.auto_queue:
            await self.disconnect(force=True)

    @staticmethod
    def _clamp_volume(value: int) -> int:
        return max(0, min(value, 1000))

    def _register_node_listeners(self) -> None:
        if self._listeners_registered:
            return

        self.node.on("track_start", self._on_node_track_start)
        self.node.on("track_end", self._on_node_track_end)
        self.node.on("player_update", self._on_node_player_update)
        self.node.on("websocket_closed", self._on_node_websocket_closed)
        self._listeners_registered = True

    def _unregister_node_listeners(self) -> None:
        if not self._listeners_registered:
            return

        self.node.remove_listener("track_start", self._on_node_track_start)
        self.node.remove_listener("track_end", self._on_node_track_end)
        self.node.remove_listener("player_update", self._on_node_player_update)
        self.node.remove_listener("websocket_closed", self._on_node_websocket_closed)
        self._listeners_registered = False


Player = FluxPlayer


def _merge_filter_payloads(base: JsonObject, override: JsonObject) -> JsonObject:
    merged = base.copy()
    for key, value in override.items():
        if key == "pluginFilters" and isinstance(value, dict):
            current = merged.get(key)
            plugin_filters = current.copy() if isinstance(current, dict) else {}
            plugin_filters.update(value)
            if plugin_filters:
                merged[key] = plugin_filters
            else:
                merged.pop(key, None)
            continue

        merged[key] = value

    return merged
