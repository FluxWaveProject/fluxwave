import pytest

import fluxwave


def test_filters_build_lavalink_payload() -> None:
    filters = (
        fluxwave.Filters()
        .set_volume(0.8)
        .set_equalizer(band_0=0.1, band_1=-0.1)
        .set_karaoke(level=1.0, mono_level=0.5)
        .set_timescale(speed=1.2, pitch=1.1, rate=0.9)
        .set_tremolo(frequency=2.0, depth=0.4)
        .set_vibrato(frequency=3.0, depth=0.5)
        .set_rotation(rotation_hz=0.2)
        .set_distortion(sin_offset=0.1, scale=0.8)
        .set_channel_mix(left_to_left=1.0, right_to_right=1.0)
        .set_low_pass(smoothing=20.0)
        .set_plugin_filters({"custom": {"enabled": True}})
    )

    payload = filters.to_payload()

    assert payload["volume"] == 0.8
    assert payload["equalizer"] == [{"band": 0, "gain": 0.1}, {"band": 1, "gain": -0.1}]
    assert payload["karaoke"] == {"level": 1.0, "monoLevel": 0.5}
    assert payload["timescale"] == {"speed": 1.2, "pitch": 1.1, "rate": 0.9}
    assert payload["tremolo"] == {"frequency": 2.0, "depth": 0.4}
    assert payload["vibrato"] == {"frequency": 3.0, "depth": 0.5}
    assert payload["rotation"] == {"rotationHz": 0.2}
    assert payload["distortion"] == {"sinOffset": 0.1, "scale": 0.8}
    assert payload["channelMix"] == {"leftToLeft": 1.0, "rightToRight": 1.0}
    assert payload["lowPass"] == {"smoothing": 20.0}
    assert payload["pluginFilters"] == {"custom": {"enabled": True}}


def test_filters_remove_and_reset() -> None:
    filters = fluxwave.Filters().set_volume(1.0).set_timescale(speed=1.5)

    filters.set_volume(None)
    filters.set_timescale()
    assert filters.to_payload() == {}

    filters.set_plugin_filters(test=True)
    filters.remove("pluginFilters")
    assert filters.to_payload() == {}

    filters.set_low_pass(smoothing=10).reset()
    assert filters.to_payload() == {}

    filters.nightcore().clear()
    assert filters.to_payload() == {}


def test_filter_presets() -> None:
    assert fluxwave.Filters().nightcore().to_payload()["timescale"] == {
        "speed": 1.25,
        "pitch": 1.2,
        "rate": 1.0,
    }
    assert fluxwave.Filters().vaporwave().to_payload()["timescale"] == {
        "speed": 0.85,
        "pitch": 0.8,
        "rate": 1.0,
    }
    assert fluxwave.Filters().bass_boost(gain=0.2).to_payload()["equalizer"][0] == {
        "band": 0,
        "gain": 0.2,
    }


def test_filters_from_payload_returns_clean_copies() -> None:
    source = {"volume": 0.5, "timescale": {"speed": 1.2}, "empty": None}
    filters = fluxwave.Filters.from_payload(source)

    source["volume"] = 1.0
    payload = filters.to_payload()
    payload["volume"] = 2.0

    assert filters.to_payload() == {"volume": 0.5, "timescale": {"speed": 1.2}}


def test_filters_from_filters_bulk_set_and_repr() -> None:
    filters = fluxwave.Filters.from_filters(
        volume=0.7,
        timescale={"speed": 1.1},
        channel_mix={"leftToLeft": 1.0},
        low_pass={"smoothing": 12.0},
        plugin_filters={"custom": {"enabled": True}},
    )

    assert filters.to_payload() == {
        "volume": 0.7,
        "timescale": {"speed": 1.1},
        "channelMix": {"leftToLeft": 1.0},
        "lowPass": {"smoothing": 12.0},
        "pluginFilters": {"custom": {"enabled": True}},
    }
    assert repr(filters).startswith("Filters(")

    filters.set_filters(reset=True, volume=0.5, equalizer=[{"band": 0, "gain": 0.2}])
    assert filters.to_payload() == {"volume": 0.5, "equalizer": [{"band": 0, "gain": 0.2}]}


def test_filter_components_are_ergonomic_views() -> None:
    filters = fluxwave.Filters()

    filters.volume = 0.75
    filters.timescale.set(speed=1.1, pitch=1.2)
    filters.rotation.set(rotation_hz=0.3)
    filters.equalizer.set(band_0=0.2)
    filters.plugin_filters.set({"lyrics": {"enabled": True}})

    assert filters() == {
        "volume": 0.75,
        "timescale": {"speed": 1.1, "pitch": 1.2},
        "rotation": {"rotationHz": 0.3},
        "equalizer": [{"band": 0, "gain": 0.2}],
        "pluginFilters": {"lyrics": {"enabled": True}},
    }
    assert filters.volume == 0.75
    assert isinstance(filters.timescale, fluxwave.TimescaleFilter)
    assert isinstance(filters.rotation, fluxwave.RotationFilter)
    assert filters.timescale.payload == {"speed": 1.1, "pitch": 1.2}

    filters.timescale.reset()
    filters.equalizer.reset()
    filters.plugin_filters.reset()

    assert filters.to_payload() == {"volume": 0.75, "rotation": {"rotationHz": 0.3}}


def test_filter_preset_covers_every_member() -> None:
    for preset in fluxwave.FilterPreset:
        payload = fluxwave.Filters.from_preset(preset).to_payload()
        if preset is fluxwave.FilterPreset.FLAT:
            assert payload == {}
        else:
            assert payload, f"preset {preset.value} produced an empty payload"


def test_filter_preset_accepts_string_value() -> None:
    by_enum = fluxwave.Filters.from_preset(fluxwave.FilterPreset.EIGHT_D).to_payload()
    by_value = fluxwave.Filters.from_preset("8d").to_payload()

    assert by_enum == by_value == {"rotation": {"rotationHz": 0.2}}


def test_filter_preset_forwards_options() -> None:
    payload = fluxwave.Filters.from_preset("bass_boost", gain=0.4).to_payload()

    assert payload["equalizer"][0] == {"band": 0, "gain": 0.4}


def test_filter_presets_compose_without_resetting() -> None:
    filters = fluxwave.Filters().bass_boost().eight_d()
    payload = filters.to_payload()

    assert "equalizer" in payload
    assert payload["rotation"] == {"rotationHz": 0.2}


def test_filter_preset_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown filter preset"):
        fluxwave.Filters.from_preset("not_a_preset")


def test_filter_preset_equalizer_omits_zero_bands() -> None:
    bands = fluxwave.Filters.from_preset("treble_boost").to_payload()["equalizer"]

    assert all(band["gain"] != 0 for band in bands)
    assert {band["band"] for band in bands} == {8, 9, 10, 11, 12, 13, 14}
