"""Typed FluxWave event payloads and dispatching."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from .tracks import PlayerState, Stats, Track
from .types import JsonObject

EventCallback = Callable[[object], object | Awaitable[object]]
EventName: TypeAlias = "str | EventType"
logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """Stable public event names emitted by FluxWave."""

    NODE_READY = "node_ready"
    NODE_DISCONNECTED = "node_disconnected"
    NODE_CLOSED = "node_closed"
    PLAYER_UPDATE = "player_update"
    STATS_UPDATE = "stats_update"
    TRACK_START = "track_start"
    TRACK_END = "track_end"
    TRACK_EXCEPTION = "track_exception"
    TRACK_STUCK = "track_stuck"
    WEBSOCKET_CLOSED = "websocket_closed"
    WEBSOCKET_RAW = "websocket_raw"
    EXTRA_EVENT = "extra_event"
    PLUGIN_EVENT = "plugin_event"
    INACTIVE_PLAYER = "inactive_player"


class EventDispatcher:
    """Small async-aware event dispatcher used before Discord integration exists."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[EventCallback]] = defaultdict(list)
        self._tasks: set[asyncio.Task[object]] = set()

    def on(self, event: EventName, callback: EventCallback) -> None:
        """Register a callback for an event name."""

        self._listeners[_event_name(event)].append(callback)

    def remove(self, event: EventName, callback: EventCallback) -> None:
        """Remove a previously registered callback."""

        name = _event_name(event)
        listeners = self._listeners.get(name)
        if not listeners:
            return

        with contextlib.suppress(ValueError):
            listeners.remove(callback)

        if not listeners:
            self._listeners.pop(name, None)

    def dispatch(self, event: EventName, payload: object) -> None:
        """Dispatch an event to registered callbacks."""

        name = _event_name(event)
        for callback in tuple(self._listeners.get(name, [])):
            try:
                result = callback(payload)
            except Exception:
                logger.exception("FluxWave event listener failed for %s.", name)
                continue

            if inspect.iscoroutine(result):
                self._schedule(result, name)

    async def close(self) -> None:
        """Cancel pending async listener tasks and clear all listeners."""

        for task in tuple(self._tasks):
            task.cancel()

        for task in tuple(self._tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._tasks.clear()
        self._listeners.clear()

    def _schedule(self, coroutine: Coroutine[object, object, object], event: str) -> None:
        try:
            task = asyncio.create_task(coroutine)
        except RuntimeError:
            # dispatch() was called without a running event loop (e.g. from a
            # synchronous context). Close the coroutine to avoid an "was never
            # awaited" warning rather than letting it abort the whole dispatch.
            coroutine.close()
            logger.error(
                "Cannot schedule FluxWave async listener for %s without a running event loop.",
                event,
            )
            return

        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda done: _log_task_exception(done, event))


@dataclass(frozen=True, slots=True)
class NodeReadyEvent:
    """Dispatched when a node becomes ready."""

    identifier: str
    session_id: str
    resumed: bool


@dataclass(frozen=True, slots=True)
class NodeDisconnectedEvent:
    """Dispatched when a node disconnects."""

    identifier: str
    code: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class NodeClosedEvent:
    """Dispatched when a node is intentionally closed."""

    identifier: str
    disconnected_guild_ids: tuple[int, ...] = ()
    disconnected_players: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class PlayerUpdateEvent:
    """Dispatched when Lavalink sends a player state update."""

    guild_id: int
    state: PlayerState
    node_identifier: str | None = None
    player: object | None = None


@dataclass(frozen=True, slots=True)
class StatsUpdateEvent:
    """Dispatched when Lavalink sends node stats."""

    stats: Stats
    node_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class TrackStartEvent:
    """Dispatched when a track starts."""

    guild_id: int
    track: Track
    node_identifier: str | None = None
    player: object | None = None
    original: Track | None = None


@dataclass(frozen=True, slots=True)
class TrackEndEvent:
    """Dispatched when a track ends."""

    guild_id: int
    track: Track
    reason: str
    node_identifier: str | None = None
    player: object | None = None
    original: Track | None = None


@dataclass(frozen=True, slots=True)
class TrackExceptionEvent:
    """Dispatched when Lavalink reports a track exception."""

    guild_id: int
    track: Track
    exception: JsonObject
    node_identifier: str | None = None
    player: object | None = None
    original: Track | None = None


@dataclass(frozen=True, slots=True)
class TrackStuckEvent:
    """Dispatched when Lavalink reports a stuck track."""

    guild_id: int
    track: Track
    threshold_ms: int
    node_identifier: str | None = None
    player: object | None = None
    original: Track | None = None


@dataclass(frozen=True, slots=True)
class WebSocketClosedEvent:
    """Dispatched when a Discord voice websocket closes."""

    guild_id: int
    code: int
    reason: str
    by_remote: bool
    node_identifier: str | None = None
    player: object | None = None


@dataclass(frozen=True, slots=True)
class RawWebSocketEvent:
    """Dispatched for every raw payload received on the Lavalink websocket.

    Fired before FluxWave parses the payload into a typed event, so listeners
    see every message verbatim. Useful for debugging and for custom Lavalink
    server plugins that introduce new websocket ops or message shapes.
    """

    payload: JsonObject
    op: str | None = None
    node_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class ExtraEvent:
    """Dispatched for unknown or plugin-specific Lavalink events."""

    guild_id: int | None
    payload: JsonObject
    node_identifier: str | None = None
    event_type: str | None = None
    player: object | None = None


@dataclass(frozen=True, slots=True)
class InactivePlayerEvent:
    """Dispatched when a player is active while no real listeners remain."""

    guild_id: int
    player: object
    non_bot_members: int
    remaining_tokens: int | None
    node_identifier: str | None = None


PluginEvent = ExtraEvent
EventPayload = (
    NodeReadyEvent
    | NodeDisconnectedEvent
    | NodeClosedEvent
    | PlayerUpdateEvent
    | StatsUpdateEvent
    | TrackStartEvent
    | TrackEndEvent
    | TrackExceptionEvent
    | TrackStuckEvent
    | WebSocketClosedEvent
    | RawWebSocketEvent
    | ExtraEvent
    | InactivePlayerEvent
)


def _event_name(event: EventName) -> str:
    return event.value if isinstance(event, EventType) else event


def _log_task_exception(task: asyncio.Task[object], event: str) -> None:
    if task.cancelled():
        return

    try:
        exception = task.exception()
    except asyncio.CancelledError:
        return

    if exception is not None:
        logger.error(
            "FluxWave async event listener failed for %s.",
            event,
            exc_info=(type(exception), exception, exception.__traceback__),
        )


_default_dispatcher = EventDispatcher()


def listen(event: EventName) -> Callable[[EventCallback], EventCallback]:
    """Register a global FluxWave event listener as a decorator."""

    def decorator(callback: EventCallback) -> EventCallback:
        _default_dispatcher.on(event, callback)
        return callback

    return decorator


def remove_listener(event: EventName, callback: EventCallback) -> None:
    """Remove a global FluxWave event listener."""

    _default_dispatcher.remove(event, callback)


def dispatch(event: EventName, payload: object) -> None:
    """Dispatch a payload to global FluxWave event listeners."""

    _default_dispatcher.dispatch(event, payload)


async def close_listeners() -> None:
    """Cancel pending global listener tasks and clear listeners."""

    await _default_dispatcher.close()
