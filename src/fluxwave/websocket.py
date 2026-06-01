"""Lavalink websocket event layer."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import aiohttp

from .backoff import Backoff
from .events import (
    EventType,
    ExtraEvent,
    NodeDisconnectedEvent,
    NodeReadyEvent,
    PlayerUpdateEvent,
    RawWebSocketEvent,
    StatsUpdateEvent,
    TrackEndEvent,
    TrackExceptionEvent,
    TrackStartEvent,
    TrackStuckEvent,
    WebSocketClosedEvent,
)
from .exceptions import AuthorizationError, NodeConnectionError
from .metrics import metrics
from .node import NodeStatus
from .tracing import TraceCategory, tracer
from .tracks import PlayerState, Stats, Track
from .types import JsonObject

if TYPE_CHECKING:
    from .node import Node


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WebSocketClient:
    """Transport boundary for Lavalink websocket events."""

    node: Node
    socket: aiohttp.ClientWebSocketResponse | None = None
    listener_task: asyncio.Task[None] | None = None
    _ready: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _closing: bool = field(default=False, init=False)

    async def connect(self) -> None:
        """Connect to Lavalink and wait for the ready websocket payload."""

        self._closing = False
        self._ready.clear()
        session = self.node.rest._ensure_session()
        url = f"{self.node.uri}/v4/websocket"
        attempts = self._attempt_count()
        backoff = self._new_backoff()

        for attempt in range(attempts):
            if self.node._closed:
                return

            try:
                self._closing = False
                self.socket = await asyncio.wait_for(
                    session.ws_connect(
                        url,
                        headers=self.node.headers,
                        heartbeat=self.node.heartbeat,
                    ),
                    timeout=self.node.connect_timeout,
                )
                self.listener_task = asyncio.create_task(self._listen())
                await asyncio.wait_for(self._ready.wait(), timeout=self.node.connect_timeout)
                return
            except (aiohttp.ClientError, TimeoutError) as exc:
                await self.close(dispatch=False)
                if attempt >= attempts - 1:
                    self.node.status = NodeStatus.DISCONNECTED
                    if isinstance(exc, aiohttp.WSServerHandshakeError) and exc.status == 401:
                        msg = f"Lavalink rejected credentials for node {self.node.identifier!r}."
                        raise AuthorizationError(msg) from exc

                    msg = f"Could not connect node {self.node.identifier!r} to Lavalink websocket."
                    raise NodeConnectionError(msg) from exc

                delay = backoff.calculate()
                logger.warning(
                    "FluxWave node %s websocket connect failed; retrying in %.2fs.",
                    self.node.identifier,
                    delay,
                )
                await asyncio.sleep(delay)

    async def close(self, *, dispatch: bool = True) -> None:
        """Close the websocket and listener task."""

        self._closing = True
        task = self.listener_task
        # Never cancel/await the task we are running inside: the reconnect path
        # (_listen -> finally -> _handle_disconnect -> connect -> close on a failed
        # attempt) executes within the listener task, so self-cancelling here would
        # have the task await itself. The listener task ends on its own in that case.
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with suppress_cancelled():
                await task

        if self.socket and not self.socket.closed:
            await self.socket.close()

        if dispatch and self.node.status is not NodeStatus.CLOSED:
            metrics.node(self.node.identifier or "").disconnect_count += 1
            self.node.dispatch(
                EventType.NODE_DISCONNECTED,
                NodeDisconnectedEvent(identifier=self.node.identifier or ""),
            )

        self.socket = None
        self.listener_task = None

    async def _listen(self) -> None:
        assert self.socket is not None

        try:
            async for message in self.socket:
                if message.type is aiohttp.WSMsgType.TEXT:
                    try:
                        payload = message.json()
                    except ValueError:
                        logger.warning(
                            "FluxWave node %s received a malformed websocket frame; ignoring.",
                            self.node.identifier,
                        )
                        continue
                    if not isinstance(payload, dict):
                        logger.warning(
                            "FluxWave node %s received a non-object websocket payload; ignoring.",
                            self.node.identifier,
                        )
                        continue
                    await self.handle_payload(payload)
                elif message.type in {
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                }:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.node.dispatch(
                EventType.EXTRA_EVENT,
                ExtraEvent(
                    guild_id=None,
                    payload={"error": repr(exc)},
                    node_identifier=self.node.identifier,
                    event_type="listener_error",
                ),
            )
        finally:
            await self._handle_disconnect()

    async def _handle_disconnect(self) -> None:
        if self._closing or self.node._closed:
            return

        self.node.status = NodeStatus.RECONNECTING
        metrics.total_reconnects += 1
        metrics.node(self.node.identifier or "").reconnect_count += 1
        tracer.trace(TraceCategory.RECONNECT, "reconnect", node_id=self.node.identifier)
        try:
            await self.connect()
        except NodeConnectionError:
            logger.warning(
                "FluxWave node %s reconnect failed after exhausting retries.",
                self.node.identifier,
            )
            self.node.status = NodeStatus.DISCONNECTED
            self.node.dispatch(
                EventType.NODE_DISCONNECTED,
                NodeDisconnectedEvent(identifier=self.node.identifier or ""),
            )

    async def handle_payload(self, payload: JsonObject) -> None:
        """Parse one Lavalink websocket payload and dispatch events."""

        op = payload.get("op")
        metrics.node(self.node.identifier or "").websocket_messages_received += 1

        self.node.dispatch(
            EventType.WEBSOCKET_RAW,
            RawWebSocketEvent(
                payload=payload.copy(),
                op=op if isinstance(op, str) else None,
                node_identifier=self.node.identifier,
            ),
        )

        if op == "ready":
            await self._handle_ready(payload)
            return

        if op == "stats":
            stats = Stats.from_payload(payload)
            self.node.stats = stats
            self.node.record_health_sample()
            self.node.dispatch(
                EventType.STATS_UPDATE,
                StatsUpdateEvent(stats=stats, node_identifier=self.node.identifier),
            )
            return

        if op == "playerUpdate":
            guild_id = _int(payload.get("guildId"))
            state = PlayerState.from_payload(_dict(payload.get("state")))
            player = self._player_for(guild_id)
            self.node.dispatch(
                EventType.PLAYER_UPDATE,
                PlayerUpdateEvent(
                    guild_id=guild_id,
                    state=state,
                    node_identifier=self.node.identifier,
                    player=player,
                ),
            )
            return

        if op == "event":
            self._handle_event(payload)
            return

        self.node.dispatch(
            EventType.EXTRA_EVENT,
            ExtraEvent(
                guild_id=None,
                payload=payload.copy(),
                node_identifier=self.node.identifier,
                event_type=_str(payload.get("op"), default="unknown"),
            ),
        )

    async def _handle_ready(self, payload: JsonObject) -> None:
        session_id = _str(payload.get("sessionId"))
        resumed = _bool(payload.get("resumed"))

        self.node.session_id = session_id
        self.node.status = NodeStatus.CONNECTED
        metrics.node(self.node.identifier or "").connect_count += 1
        tracer.trace(TraceCategory.NODE, "ready", node_id=self.node.identifier, resumed=resumed)
        try:
            await self.node.configure_resume()
        except Exception:
            logger.exception(
                "Failed to configure Lavalink resume for node %s.",
                self.node.identifier,
            )
        self.node.dispatch(
            EventType.NODE_READY,
            NodeReadyEvent(
                identifier=self.node.identifier or "",
                session_id=session_id,
                resumed=resumed,
            ),
        )
        self._ready.set()
        await self.node.recover_players(resumed=resumed)

    def _handle_event(self, payload: JsonObject) -> None:
        event_type = _str(payload.get("type"))
        guild_id = _int(payload.get("guildId"))
        player = self._player_for(guild_id)
        original = getattr(player, "current", None)

        if event_type == "TrackStartEvent":
            self.node.dispatch(
                EventType.TRACK_START,
                TrackStartEvent(
                    guild_id=guild_id,
                    track=Track.from_payload(_dict(payload.get("track"))),
                    node_identifier=self.node.identifier,
                    player=player,
                    original=original,
                ),
            )
            return

        if event_type == "TrackEndEvent":
            self.node.dispatch(
                EventType.TRACK_END,
                TrackEndEvent(
                    guild_id=guild_id,
                    track=Track.from_payload(_dict(payload.get("track"))),
                    reason=_str(payload.get("reason")),
                    node_identifier=self.node.identifier,
                    player=player,
                    original=original,
                ),
            )
            return

        if event_type == "TrackExceptionEvent":
            metrics.track_error_count += 1
            self.node.dispatch(
                EventType.TRACK_EXCEPTION,
                TrackExceptionEvent(
                    guild_id=guild_id,
                    track=Track.from_payload(_dict(payload.get("track"))),
                    exception=_dict(payload.get("exception")),
                    node_identifier=self.node.identifier,
                    player=player,
                    original=original,
                ),
            )
            return

        if event_type == "TrackStuckEvent":
            metrics.track_stuck_count += 1
            self.node.dispatch(
                EventType.TRACK_STUCK,
                TrackStuckEvent(
                    guild_id=guild_id,
                    track=Track.from_payload(_dict(payload.get("track"))),
                    threshold_ms=_int(payload.get("thresholdMs")),
                    node_identifier=self.node.identifier,
                    player=player,
                    original=original,
                ),
            )
            return

        if event_type == "WebSocketClosedEvent":
            self.node.dispatch(
                EventType.WEBSOCKET_CLOSED,
                WebSocketClosedEvent(
                    guild_id=guild_id,
                    code=_int(payload.get("code")),
                    reason=_str(payload.get("reason")),
                    by_remote=_bool(payload.get("byRemote")),
                    node_identifier=self.node.identifier,
                    player=player,
                ),
            )
            return

        extra = ExtraEvent(
            guild_id=guild_id,
            payload=payload.copy(),
            node_identifier=self.node.identifier,
            event_type=event_type,
            player=player,
        )
        self.node.dispatch(EventType.EXTRA_EVENT, extra)
        self.node.dispatch(EventType.PLUGIN_EVENT, extra)

    def _player_for(self, guild_id: int) -> object | None:
        return self.node._live_players.get(guild_id)

    def _attempt_count(self) -> int:
        if self.node.retries is None:
            return 1_000_000_000

        return max(self.node.retries, 0) + 1

    def _new_backoff(self) -> Backoff:
        return Backoff(
            base=self.node.retry_base_delay,
            # The per-attempt connect timeout bounds each attempt independently
            # (via asyncio.wait_for), so the inter-attempt delay should honour the
            # configured retry_max_delay rather than being clamped down to it.
            maximum_time=self.node.retry_max_delay,
            maximum_tries=self.node.retries,
            jitter=self.node.retry_jitter,
        )


class suppress_cancelled:
    """Suppress task cancellation while closing websocket resources."""

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        return exc_type is not None and issubclass(exc_type, asyncio.CancelledError)


def _dict(value: object) -> JsonObject:
    return value.copy() if isinstance(value, dict) else {}


def _str(value: object, *, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int(value: object, *, default: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default

    return default


def _bool(value: object, *, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default
