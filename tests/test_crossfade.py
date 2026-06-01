import pytest

import fluxwave
from fluxwave.crossfade import fade_fraction


def test_fade_fraction_endpoints() -> None:
    for curve in fluxwave.FadeCurve:
        assert fade_fraction(curve, 0.0) == pytest.approx(0.0, abs=1e-9)
        assert fade_fraction(curve, 1.0) == pytest.approx(1.0, abs=1e-9)


def test_fade_fraction_clamps_out_of_range() -> None:
    assert fade_fraction(fluxwave.FadeCurve.LINEAR, -1.0) == 0.0
    assert fade_fraction(fluxwave.FadeCurve.LINEAR, 2.0) == 1.0


def test_fade_fraction_is_monotonic() -> None:
    for curve in fluxwave.FadeCurve:
        values = [fade_fraction(curve, step / 20) for step in range(21)]
        assert values == sorted(values)


def test_fade_curves_have_distinct_shapes() -> None:
    progress = 0.25
    linear = fade_fraction(fluxwave.FadeCurve.LINEAR, progress)
    smooth = fade_fraction(fluxwave.FadeCurve.SMOOTH, progress)
    equal_power = fade_fraction(fluxwave.FadeCurve.EQUAL_POWER, progress)
    # smoothstep eases in slowly; equal-power rises quickly.
    assert smooth < linear < equal_power


def test_crossfade_config_defaults() -> None:
    config = fluxwave.CrossfadeConfig()
    assert config.duration == 4.0
    assert config.fade_in is True
    assert config.fade_out is True
    assert config.curve is fluxwave.FadeCurve.SMOOTH
    assert config.floor_volume == 0
