"""Internal wrapper metrics for monitoring and observability."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NodeMetrics:
    """Per-node counters."""

    identifier: str
    connect_count: int = 0
    reconnect_count: int = 0
    disconnect_count: int = 0
    search_count: int = 0
    search_cache_hits: int = 0
    rest_request_count: int = 0
    rest_error_count: int = 0
    websocket_messages_received: int = 0
    player_migrations_out: int = 0
    player_migrations_in: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "connect_count": self.connect_count,
            "reconnect_count": self.reconnect_count,
            "disconnect_count": self.disconnect_count,
            "search_count": self.search_count,
            "search_cache_hits": self.search_cache_hits,
            "rest_request_count": self.rest_request_count,
            "rest_error_count": self.rest_error_count,
            "websocket_messages_received": self.websocket_messages_received,
            "player_migrations_out": self.player_migrations_out,
            "player_migrations_in": self.player_migrations_in,
        }


@dataclass(slots=True)
class WrapperMetrics:
    """Aggregate wrapper statistics.

    Access via the module-level :data:`metrics` singleton::

        from fluxwave.metrics import metrics
        print(metrics.to_dict())
    """

    _started_at: float = field(default_factory=time.monotonic, init=False)
    _node_metrics: dict[str, NodeMetrics] = field(default_factory=dict, init=False)

    track_play_count: int = 0
    track_error_count: int = 0
    track_stuck_count: int = 0
    voice_timeout_count: int = 0
    watchdog_recovery_count: int = 0
    crossfade_count: int = 0
    node_switch_count: int = 0
    total_reconnects: int = 0
    total_searches: int = 0
    total_search_cache_hits: int = 0

    @property
    def uptime(self) -> float:
        """Seconds since the metrics object was created."""
        return time.monotonic() - self._started_at

    def node(self, identifier: str) -> NodeMetrics:
        """Return (or create) per-node metrics for *identifier*."""
        if identifier not in self._node_metrics:
            self._node_metrics[identifier] = NodeMetrics(identifier=identifier)
        return self._node_metrics[identifier]

    def reset(self) -> None:
        """Zero out all counters and restart the uptime clock."""
        self._started_at = time.monotonic()
        self._node_metrics.clear()
        self.track_play_count = 0
        self.track_error_count = 0
        self.track_stuck_count = 0
        self.voice_timeout_count = 0
        self.watchdog_recovery_count = 0
        self.node_switch_count = 0
        self.total_reconnects = 0
        self.total_searches = 0
        self.total_search_cache_hits = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot."""
        return {
            "uptime_seconds": round(self.uptime, 2),
            "track_play_count": self.track_play_count,
            "track_error_count": self.track_error_count,
            "track_stuck_count": self.track_stuck_count,
            "voice_timeout_count": self.voice_timeout_count,
            "watchdog_recovery_count": self.watchdog_recovery_count,
            "node_switch_count": self.node_switch_count,
            "total_reconnects": self.total_reconnects,
            "total_searches": self.total_searches,
            "total_search_cache_hits": self.total_search_cache_hits,
            "nodes": {k: v.to_dict() for k, v in self._node_metrics.items()},
        }

    def __repr__(self) -> str:
        return (
            f"WrapperMetrics(uptime={self.uptime:.1f}s, "
            f"plays={self.track_play_count}, errors={self.track_error_count})"
        )


metrics: WrapperMetrics = WrapperMetrics()
"""Module-level metrics singleton. Reset with ``fluxwave.metrics.metrics.reset()``."""
