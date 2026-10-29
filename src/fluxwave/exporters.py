"""Exporters that expose FluxWave metrics and traces to monitoring systems."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, cast

from .metrics import WrapperMetrics
from .metrics import metrics as default_metrics
from .tracing import TraceEvent


class _Counter(Protocol):
    def add(self, value: float, attributes: dict[str, str] | None = None) -> None: ...


class _Meter(Protocol):
    def create_counter(self, name: str) -> _Counter: ...


_AGGREGATE_GAUGES: tuple[tuple[str, str], ...] = (
    ("uptime_seconds", "Wrapper uptime in seconds."),
    ("track_play_count", "Tracks successfully started."),
    ("track_error_count", "Track exceptions reported by Lavalink."),
    ("track_stuck_count", "Stuck-track events reported by Lavalink."),
    ("voice_timeout_count", "Discord voice connection timeouts."),
    ("watchdog_recovery_count", "Playback recoveries performed by the watchdog."),
    ("crossfade_count", "Completed crossfades."),
    ("node_switch_count", "Player node switches."),
    ("total_reconnects", "Websocket reconnections."),
    ("total_searches", "Search/load operations."),
    ("total_search_cache_hits", "Searches served from cache."),
)

_NODE_COUNTERS: tuple[tuple[str, str], ...] = (
    ("connect_count", "Successful node connects."),
    ("reconnect_count", "Node websocket reconnects."),
    ("disconnect_count", "Node websocket disconnects."),
    ("search_count", "Node-level searches."),
    ("search_cache_hits", "Node-level search cache hits."),
    ("rest_request_count", "REST requests issued to the node."),
    ("rest_error_count", "REST requests that returned an error."),
    ("websocket_messages_received", "Websocket messages received from the node."),
    ("player_migrations_out", "Players migrated away from the node."),
    ("player_migrations_in", "Players migrated onto the node."),
)


class PrometheusExporter:
    """Render :class:`~fluxwave.WrapperMetrics` as Prometheus text.

    The default metrics singleton is used when none is passed::

        from fluxwave import PrometheusExporter
        print(PrometheusExporter().render())
    """

    def __init__(
        self,
        metrics: WrapperMetrics | None = None,
        *,
        namespace: str = "fluxwave",
    ) -> None:
        self._metrics = metrics if metrics is not None else default_metrics
        self._namespace = namespace

    @property
    def metrics(self) -> WrapperMetrics:
        """Metrics object being exported."""

        return self._metrics

    def render(self) -> str:
        """Return a Prometheus text-exposition document."""

        snapshot = self._metrics.to_dict()
        lines: list[str] = []

        for name, description in _AGGREGATE_GAUGES:
            metric = f"{self._namespace}_{name}"
            _emit_help_type(lines, metric, description, "gauge")
            lines.append(f"{metric} {_number(snapshot.get(name, 0))}")

        for name, description in _NODE_COUNTERS:
            metric = f"{self._namespace}_node_{name}_total"
            _emit_help_type(lines, metric, description, "counter")
            nodes = snapshot.get("nodes", {})
            if not isinstance(nodes, dict):
                continue
            for identifier in sorted(nodes):
                node = nodes[identifier]
                if not isinstance(node, dict):
                    continue
                value = _number(node.get(name, 0))
                lines.append(f'{metric}{{node="{_escape(str(identifier))}"}} {value}')

        return "\n".join(lines) + "\n"

    def __str__(self) -> str:
        return self.render()


class OpenTelemetryExporter:
    """Bridge :class:`~fluxwave.WrapperMetrics` into an OpenTelemetry meter.

    *meter* is any object implementing ``create_counter`` and
    ``create_histogram`` (e.g. an ``opentelemetry.metrics.Meter``). Counters are
    created lazily on first use, so importing this class never requires the
    OpenTelemetry SDK::

        exporter = OpenTelemetryExporter(meter)
        exporter.record_metrics()  # push a snapshot
    """

    def __init__(
        self,
        meter: object,
        *,
        metrics: WrapperMetrics | None = None,
        namespace: str = "fluxwave",
    ) -> None:
        if not hasattr(meter, "create_counter"):
            msg = "OpenTelemetryExporter requires an object with create_counter()."
            raise TypeError(msg)

        self._meter = cast("_Meter", meter)
        self._metrics = metrics if metrics is not None else default_metrics
        self._namespace = namespace
        self._counters: dict[str, _Counter] = {}
        self._last_values: dict[str, float] = {}

    def _counter(self, name: str) -> _Counter:
        counter = self._counters.get(name)
        if counter is None:
            counter = self._meter.create_counter(f"{self._namespace}.{name}")
            self._counters[name] = counter
        return counter

    def _add_delta(
        self, key: str, name: str, value: float, attributes: dict[str, str] | None = None
    ) -> None:
        """Add only the change since the previous snapshot.

        OpenTelemetry counters are additive, while FluxWave's metrics snapshot
        contains cumulative totals. Pushing the same snapshot repeatedly must not
        double-count in the backend.
        """

        previous = self._last_values.get(key, 0.0)
        delta = value - previous
        if delta < 0:
            # The process restarted or the metric was reset.
            delta = value
        self._last_values[key] = value
        counter = self._counter(name)
        if delta:
            counter.add(delta, attributes)

    def record_metrics(self) -> None:
        """Push the current metrics snapshot to the meter."""

        snapshot = self._metrics.to_dict()
        for name, _ in _AGGREGATE_GAUGES:
            if name == "uptime_seconds":
                continue
            self._add_delta(name, name, _float(snapshot.get(name, 0)))

        nodes = snapshot.get("nodes", {})
        if not isinstance(nodes, dict):
            return
        for identifier, node in nodes.items():
            if not isinstance(node, dict):
                continue
            attributes = {"node": str(identifier)}
            for name, _ in _NODE_COUNTERS:
                self._add_delta(
                    f"node:{identifier}:{name}",
                    name,
                    _float(node.get(name, 0)),
                    attributes,
                )

    def record_traces(self, events: Iterable[TraceEvent]) -> None:
        """Count buffered trace events by category."""

        for event in events:
            self._counter(f"trace.{event.category.value}").add(1)

    def __repr__(self) -> str:
        return (
            f"OpenTelemetryExporter(namespace={self._namespace!r}, counters={len(self._counters)})"
        )


def _emit_help_type(
    lines: list[str],
    metric: str,
    description: str,
    kind: str,
) -> None:
    lines.append(f"# HELP {metric} {description}")
    lines.append(f"# TYPE {metric} {kind}")


def _number(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(round(value, 4))
    return "0"


def _float(value: object) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


__all__ = ["OpenTelemetryExporter", "PrometheusExporter"]
