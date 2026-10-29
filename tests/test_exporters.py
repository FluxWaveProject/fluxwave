import pytest

import fluxwave
from fluxwave.metrics import WrapperMetrics


def snapshot() -> WrapperMetrics:
    metrics = WrapperMetrics()
    metrics.track_play_count = 3
    metrics.node("node-a").connect_count = 2
    metrics.node("node-a").rest_request_count = 5
    return metrics


def test_prometheus_render_includes_aggregate_gauges() -> None:
    exporter = fluxwave.PrometheusExporter(snapshot())

    text = exporter.render()

    assert "# TYPE fluxwave_track_play_count gauge" in text
    assert "fluxwave_track_play_count 3" in text
    assert "fluxwave_track_play_count 3" in str(exporter)
    assert exporter.metrics.track_play_count == 3


def test_prometheus_render_includes_labeled_node_counters() -> None:
    text = fluxwave.PrometheusExporter(snapshot()).render()

    assert "# TYPE fluxwave_node_connect_count_total counter" in text
    assert 'fluxwave_node_connect_count_total{node="node-a"} 2' in text
    assert 'fluxwave_node_rest_request_count_total{node="node-a"} 5' in text


def test_prometheus_namespace_is_configurable() -> None:
    text = fluxwave.PrometheusExporter(snapshot(), namespace="bot").render()

    assert "bot_track_play_count 3" in text


class FakeCounter:
    def __init__(self) -> None:
        self.values: list[tuple[float, dict[str, str] | None]] = []

    def add(self, value: float, attributes: dict[str, str] | None = None) -> None:
        self.values.append((value, attributes))


class FakeMeter:
    def __init__(self) -> None:
        self.counters: dict[str, FakeCounter] = {}

    def create_counter(self, name: str) -> FakeCounter:
        return self.counters.setdefault(name, FakeCounter())


def test_otel_exporter_requires_a_counter_factory() -> None:
    with pytest.raises(TypeError):
        fluxwave.OpenTelemetryExporter(object())


def test_otel_exporter_pushes_meter_snapshot() -> None:
    meter = FakeMeter()
    exporter = fluxwave.OpenTelemetryExporter(meter, metrics=snapshot())

    exporter.record_metrics()

    assert meter.counters["fluxwave.track_play_count"].values == [(3.0, None)]
    assert meter.counters["fluxwave.rest_request_count"].values == [(5.0, {"node": "node-a"})]
    assert "OpenTelemetryExporter" in repr(exporter)


def test_otel_exporter_only_adds_deltas_between_snapshots() -> None:
    metrics = snapshot()
    meter = FakeMeter()
    exporter = fluxwave.OpenTelemetryExporter(meter, metrics=metrics)

    exporter.record_metrics()
    exporter.record_metrics()
    metrics.track_play_count = 5
    exporter.record_metrics()

    assert meter.counters["fluxwave.track_play_count"].values == [(3.0, None), (2.0, None)]


def test_otel_exporter_registers_counters_even_when_snapshot_is_zero() -> None:
    meter = FakeMeter()
    exporter = fluxwave.OpenTelemetryExporter(meter, metrics=WrapperMetrics())

    exporter.record_metrics()

    assert "fluxwave.track_play_count" in meter.counters
    assert meter.counters["fluxwave.track_play_count"].values == []


def test_otel_exporter_records_trace_categories() -> None:
    meter = FakeMeter()
    exporter = fluxwave.OpenTelemetryExporter(meter, metrics=snapshot())
    events = [
        fluxwave.TraceEvent(fluxwave.TraceCategory.VOICE, "voice", {}),
        fluxwave.TraceEvent(fluxwave.TraceCategory.VOICE, "voice", {}),
        fluxwave.TraceEvent(fluxwave.TraceCategory.REST, "rest", {}),
    ]

    exporter.record_traces(events)

    assert meter.counters["fluxwave.trace.voice"].values == [(1, None), (1, None)]
    assert meter.counters["fluxwave.trace.rest"].values == [(1, None)]
