"""Structured event tracing for debugging Lavalink / Discord voice internals."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TraceCategory(StrEnum):
    """Category tag for a :class:`TraceEvent`."""

    VOICE = "voice"
    WEBSOCKET = "websocket"
    REST = "rest"
    NODE = "node"
    PLAYER = "player"
    RECONNECT = "reconnect"
    WATCHDOG = "watchdog"
    MIGRATION = "migration"
    SEARCH = "search"
    FADE = "fade"


@dataclass(slots=True)
class TraceEvent:
    """Single captured trace entry."""

    category: TraceCategory
    message: str
    data: dict[str, Any]
    guild_id: int | None = None
    node_id: str | None = None
    timestamp: float = field(default_factory=time.monotonic)


class EventTracer:
    """Collects and emits structured debug traces.

    Disabled by default. Enable with :meth:`enable` or by constructing with
    ``enabled=True``.  Traces are stored in a ring buffer and also forwarded
    to the ``fluxwave.trace`` logger at DEBUG level.

    Example::

        from fluxwave.tracing import tracer
        tracer.enable()
        # ... run your bot ...
        for event in tracer.recent(20):
            print(event)
    """

    __slots__ = ("_buffer", "_enabled", "_log")

    def __init__(self, *, enabled: bool = False, buffer_size: int = 2000) -> None:
        self._enabled = enabled
        self._buffer: deque[TraceEvent] = deque(maxlen=buffer_size)
        self._log = logging.getLogger("fluxwave.trace")

    @property
    def enabled(self) -> bool:
        """Whether tracing is currently active."""
        return self._enabled

    def enable(self) -> None:
        """Activate tracing."""
        self._enabled = True

    def disable(self) -> None:
        """Deactivate tracing."""
        self._enabled = False

    def trace(
        self,
        category: TraceCategory,
        message: str,
        *,
        guild_id: int | None = None,
        node_id: str | None = None,
        **data: object,
    ) -> None:
        """Record a trace event (no-op when disabled)."""
        if not self._enabled:
            return
        event = TraceEvent(
            category=category,
            message=message,
            data=data,
            guild_id=guild_id,
            node_id=node_id,
        )
        self._buffer.append(event)
        self._log.debug(
            "[%s] %s guild=%s node=%s %s",
            category,
            message,
            guild_id,
            node_id,
            data or "",
        )

    def recent(self, limit: int = 50) -> list[TraceEvent]:
        """Return the most recent *limit* events."""
        events = list(self._buffer)
        if limit <= 0:
            return []
        return events[-limit:]

    def by_category(self, category: TraceCategory) -> list[TraceEvent]:
        """Return all buffered events matching *category*."""
        return [e for e in self._buffer if e.category is category]

    def for_guild(self, guild_id: int) -> list[TraceEvent]:
        """Return all buffered events associated with *guild_id*."""
        return [e for e in self._buffer if e.guild_id == guild_id]

    def for_node(self, node_id: str) -> list[TraceEvent]:
        """Return all buffered events associated with *node_id*."""
        return [e for e in self._buffer if e.node_id == node_id]

    def clear(self) -> None:
        """Discard all buffered events."""
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)

    def __repr__(self) -> str:
        return f"EventTracer(enabled={self._enabled}, buffered={len(self._buffer)})"


tracer: EventTracer = EventTracer()
"""Module-level tracer. Enable with ``fluxwave.tracing.tracer.enable()``."""
