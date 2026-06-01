"""Lavalink audio filter payload builder."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .types import JsonObject


class FilterPreset(StrEnum):
    """Named, ready-to-use audio effects built on Lavalink's raw filters.

    Pass any member (or its string value) to :meth:`Filters.from_preset` or
    :meth:`Filters.apply_preset`.  The string values are slash-command friendly,
    so a bot can map a user's choice straight onto a preset::

        await player.set_filters(fluxwave.Filters.from_preset("8d"))
    """

    # Speed / pitch (timescale)
    NIGHTCORE = "nightcore"
    VAPORWAVE = "vaporwave"
    DAYCORE = "daycore"
    SLOWED = "slowed"
    SPED_UP = "sped_up"
    CHIPMUNK = "chipmunk"
    DEEP = "deep"
    DOUBLE_TIME = "double_time"
    # Spatial / movement
    EIGHT_D = "8d"
    PARTY = "party"
    ROTATION = "rotation"
    # Modulation
    TREMOLO = "tremolo"
    VIBRATO = "vibrato"
    # Vocals
    KARAOKE = "karaoke"
    # Texture
    DISTORTION = "distortion"
    SOFT = "soft"
    MUFFLED = "muffled"
    LOFI = "lofi"
    SLOWED_REVERB = "slowed_reverb"
    MONO = "mono"
    # Tone / equalizer
    BASS_BOOST = "bass_boost"
    BASS_BOOST_EXTREME = "bass_boost_extreme"
    TREBLE_BOOST = "treble_boost"
    POP = "pop"
    ROCK = "rock"
    METAL = "metal"
    JAZZ = "jazz"
    CLASSICAL = "classical"
    ELECTRONIC = "electronic"
    VOCAL = "vocal"
    FLAT = "flat"


# 15-band equalizer curves (band 0 ≈ 25 Hz … band 14 ≈ 16 kHz). Gains are kept in
# a conservative range so presets stay musical rather than clipping. Values are
# our own tuning, informed by the genre curves common to graphic equalizers.
_EQ_BASS_EXTREME = (
    0.30,
    0.28,
    0.26,
    0.22,
    0.16,
    0.10,
    0.05,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
)
_EQ_TREBLE = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.03, 0.06, 0.09, 0.12, 0.14, 0.14, 0.12)
_EQ_POP = (
    -0.02,
    -0.01,
    0.0,
    0.02,
    0.05,
    0.08,
    0.09,
    0.09,
    0.07,
    0.04,
    0.02,
    0.0,
    -0.01,
    -0.02,
    -0.02,
)
_EQ_ROCK = (
    0.10,
    0.08,
    0.06,
    0.03,
    0.0,
    -0.03,
    -0.03,
    0.0,
    0.02,
    0.05,
    0.07,
    0.09,
    0.10,
    0.09,
    0.08,
)
_EQ_METAL = (
    0.0,
    0.05,
    0.08,
    0.08,
    0.04,
    0.0,
    0.02,
    0.04,
    0.05,
    0.06,
    0.08,
    0.09,
    0.08,
    0.06,
    0.04,
)
_EQ_JAZZ = (
    0.05,
    0.04,
    0.03,
    0.02,
    0.02,
    0.03,
    0.02,
    0.02,
    0.03,
    0.03,
    0.02,
    0.02,
    0.03,
    0.02,
    0.0,
)
_EQ_CLASSICAL = (
    0.05,
    0.04,
    0.03,
    0.02,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    -0.02,
    -0.03,
    -0.04,
    -0.05,
    -0.06,
)
_EQ_ELECTRONIC = (
    0.12,
    0.10,
    0.07,
    0.0,
    -0.04,
    -0.04,
    0.0,
    0.03,
    0.04,
    0.05,
    0.07,
    0.09,
    0.11,
    0.11,
    0.10,
)
_EQ_VOCAL = (
    -0.06,
    -0.06,
    -0.05,
    -0.03,
    0.02,
    0.06,
    0.10,
    0.11,
    0.09,
    0.05,
    0.0,
    -0.02,
    -0.03,
    -0.03,
    -0.03,
)
_EQ_LOFI = (
    0.10,
    0.08,
    0.05,
    0.02,
    0.0,
    0.0,
    -0.02,
    -0.03,
    -0.05,
    -0.07,
    -0.10,
    -0.12,
    -0.14,
    -0.16,
    -0.18,
)


@dataclass(slots=True)
class Filters:
    """Mutable Lavalink filter builder.

    Methods return `self` so callers can build payloads fluently.
    """

    _payload: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: JsonObject) -> Filters:
        """Create filters from an existing Lavalink payload."""

        return cls(_payload=_clean_mapping(payload))

    @classmethod
    def copy(cls, other: Filters) -> Filters:
        """Return an independent copy of another :class:`Filters` instance."""

        return cls.from_payload(other.to_payload())

    @classmethod
    def interpolate(cls, start: Filters, end: Filters, t: float) -> Filters:
        """Return a linearly interpolated filter state between *start* and *end*.

        *t* is a blend factor where ``0.0`` returns a copy of *start* and
        ``1.0`` returns a copy of *end*.  Values outside ``[0, 1]`` are clamped.

        Only scalar numeric fields that exist in both payloads are interpolated.
        Dict sections (e.g. ``timescale``, ``karaoke``) are recursively blended.
        Fields present only in one side take the value from whichever side is
        dominant based on *t*::

            mid = Filters.interpolate(bass_boost, nightcore, t=0.5)
            await player.set_filters(mid)
        """

        t = max(0.0, min(1.0, t))
        a = start.to_payload()
        b = end.to_payload()
        blended = _blend_payloads(a, b, t)
        return cls(_payload=blended)

    @classmethod
    def from_filters(
        cls,
        *,
        volume: float | None = None,
        equalizer: list[dict[str, float | int]] | None = None,
        karaoke: JsonObject | None = None,
        timescale: JsonObject | None = None,
        tremolo: JsonObject | None = None,
        vibrato: JsonObject | None = None,
        rotation: JsonObject | None = None,
        distortion: JsonObject | None = None,
        channel_mix: JsonObject | None = None,
        low_pass: JsonObject | None = None,
        plugin_filters: JsonObject | None = None,
    ) -> Filters:
        """Create a filter payload from Wavelink-style keyword sections."""

        filters = cls()
        return filters.set_filters(
            volume=volume,
            equalizer=equalizer,
            karaoke=karaoke,
            timescale=timescale,
            tremolo=tremolo,
            vibrato=vibrato,
            rotation=rotation,
            distortion=distortion,
            channel_mix=channel_mix,
            low_pass=low_pass,
            plugin_filters=plugin_filters,
        )

    def to_payload(self) -> JsonObject:
        """Return a copy of the raw Lavalink filters payload."""

        return _clean_mapping(self._payload)

    @property
    def payload(self) -> JsonObject:
        """Alias for `to_payload`."""

        return self.to_payload()

    def __call__(self) -> JsonObject:
        """Return a Lavalink filter payload."""

        return self.to_payload()

    def __repr__(self) -> str:
        return f"Filters({self.to_payload()!r})"

    def __bool__(self) -> bool:
        return bool(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    @property
    def volume(self) -> float | None:
        """Current volume filter value, if set."""

        value = self._payload.get("volume")
        return float(value) if isinstance(value, int | float) else None

    @volume.setter
    def volume(self, value: float | None) -> None:
        self.set_volume(value)

    @property
    def equalizer(self) -> EqualizerFilter:
        """Ergonomic equalizer filter component."""

        return EqualizerFilter(self)

    @property
    def karaoke(self) -> KaraokeFilter:
        """Ergonomic karaoke filter component."""

        return KaraokeFilter(self, "karaoke", self.set_karaoke)

    @property
    def timescale(self) -> TimescaleFilter:
        """Ergonomic timescale filter component."""

        return TimescaleFilter(self, "timescale", self.set_timescale)

    @property
    def tremolo(self) -> TremoloFilter:
        """Ergonomic tremolo filter component."""

        return TremoloFilter(self, "tremolo", self.set_tremolo)

    @property
    def vibrato(self) -> VibratoFilter:
        """Ergonomic vibrato filter component."""

        return VibratoFilter(self, "vibrato", self.set_vibrato)

    @property
    def rotation(self) -> RotationFilter:
        """Ergonomic rotation filter component."""

        return RotationFilter(self, "rotation", self.set_rotation)

    @property
    def distortion(self) -> DistortionFilter:
        """Ergonomic distortion filter component."""

        return DistortionFilter(self, "distortion", self.set_distortion)

    @property
    def channel_mix(self) -> ChannelMixFilter:
        """Ergonomic channel-mix filter component."""

        return ChannelMixFilter(self, "channelMix", self.set_channel_mix)

    @property
    def low_pass(self) -> LowPassFilter:
        """Ergonomic low-pass filter component."""

        return LowPassFilter(self, "lowPass", self.set_low_pass)

    @property
    def plugin_filters(self) -> PluginFiltersComponent:
        """Ergonomic plugin filter component."""

        return PluginFiltersComponent(self)

    def reset(self) -> Filters:
        """Clear all filters."""

        self._payload.clear()
        return self

    def clear(self) -> Filters:
        """Clear all filters."""

        return self.reset()

    def nightcore(self) -> Filters:
        """Apply a nightcore-style preset."""

        return self.set_timescale(speed=1.25, pitch=1.2, rate=1.0)

    def vaporwave(self) -> Filters:
        """Apply a vaporwave-style preset."""

        return self.set_timescale(speed=0.85, pitch=0.8, rate=1.0)

    def bass_boost(self, *, gain: float = 0.25) -> Filters:
        """Apply a bass boost equalizer preset."""

        return self.set_equalizer(
            [
                {"band": 0, "gain": gain},
                {"band": 1, "gain": gain * 0.8},
                {"band": 2, "gain": gain * 0.6},
                {"band": 3, "gain": gain * 0.35},
                {"band": 4, "gain": gain * 0.15},
            ]
        )

    def apply_preset(self, preset: FilterPreset | str, /, **options: float) -> Filters:
        """Apply a named :class:`FilterPreset` onto this builder.

        Presets only touch the Lavalink sections they need, so they compose with
        the fluent builder and with each other (``Filters().bass_boost().eight_d()``).
        ``options`` are forwarded to the underlying preset (currently only the
        bass-boost and 8D presets accept keywords); unrelated presets ignore them::

            filters.apply_preset("bass_boost", gain=0.4)
        """

        try:
            resolved = preset if isinstance(preset, FilterPreset) else FilterPreset(preset)
        except ValueError:
            valid = ", ".join(sorted(member.value for member in FilterPreset))
            msg = f"Unknown filter preset {preset!r}. Valid presets: {valid}."
            raise ValueError(msg) from None

        builder = _PRESET_BUILDERS[resolved]
        builder(self, **options)
        return self

    @classmethod
    def from_preset(cls, preset: FilterPreset | str, /, **options: float) -> Filters:
        """Build a fresh :class:`Filters` carrying only the given preset."""

        return cls().apply_preset(preset, **options)

    def daycore(self) -> Filters:
        """Apply a daycore preset (slowed and pitched down — nightcore's opposite)."""

        return self.set_timescale(speed=0.8, pitch=0.9, rate=1.0)

    def slowed(self) -> Filters:
        """Apply a gentle "slowed" preset (the popular slowed-down edit feel)."""

        return self.set_timescale(speed=0.85, pitch=0.95, rate=1.0)

    def sped_up(self) -> Filters:
        """Apply a "sped up" preset (the popular faster edit feel)."""

        return self.set_timescale(speed=1.15, pitch=1.08, rate=1.0)

    def chipmunk(self) -> Filters:
        """Apply a high, chipmunk-style pitch preset."""

        return self.set_timescale(speed=1.05, pitch=1.5, rate=1.0)

    def deep(self) -> Filters:
        """Apply a deep, demonic low-pitch preset."""

        return self.set_timescale(speed=0.95, pitch=0.7, rate=1.0)

    def double_time(self) -> Filters:
        """Apply a double-time tempo preset without changing pitch."""

        return self.set_timescale(speed=1.4, pitch=1.0, rate=1.0)

    def eight_d(self, *, rotation_hz: float = 0.2) -> Filters:
        """Apply an 8D audio preset (audio panning around the listener)."""

        return self.set_rotation(rotation_hz=rotation_hz)

    def party(self) -> Filters:
        """Apply a party preset (bass lift plus gentle spatial movement)."""

        self.bass_boost(gain=0.2)
        return self.set_rotation(rotation_hz=0.15)

    def soft(self) -> Filters:
        """Apply a soft, mellow preset that rolls off harsh highs."""

        return self.set_low_pass(smoothing=20.0)

    def muffled(self) -> Filters:
        """Apply a heavy muffled / underwater preset."""

        return self.set_low_pass(smoothing=40.0)

    def lofi(self) -> Filters:
        """Apply a lo-fi preset (slight slow-down, rolled-off highs, warm low end)."""

        self.set_timescale(speed=0.9, pitch=0.95, rate=1.0)
        self.set_low_pass(smoothing=15.0)
        return self._set_eq_curve(_EQ_LOFI)

    def slowed_reverb(self) -> Filters:
        """Apply a "slowed + reverb"-style preset (slowed-down, spacious low pass).

        Lavalink has no true reverb filter, so this approximates the trend with a
        slowed timescale and a smoothing low pass for a roomier, mellow sound.
        """

        self.set_timescale(speed=0.82, pitch=0.92, rate=1.0)
        return self.set_low_pass(smoothing=12.0)

    def mono(self) -> Filters:
        """Collapse stereo to mono via the channel-mix filter."""

        return self.set_channel_mix(
            left_to_left=0.5,
            left_to_right=0.5,
            right_to_left=0.5,
            right_to_right=0.5,
        )

    def bass_boost_extreme(self) -> Filters:
        """Apply a heavy, full bass boost preset."""

        return self._set_eq_curve(_EQ_BASS_EXTREME)

    def treble_boost(self) -> Filters:
        """Apply a treble / brightness boost preset."""

        return self._set_eq_curve(_EQ_TREBLE)

    def pop(self) -> Filters:
        """Apply a pop equalizer preset (forward vocals and mids)."""

        return self._set_eq_curve(_EQ_POP)

    def rock(self) -> Filters:
        """Apply a rock equalizer preset (scooped mids, lifted lows and highs)."""

        return self._set_eq_curve(_EQ_ROCK)

    def metal(self) -> Filters:
        """Apply a metal equalizer preset (tight low-mids and presence)."""

        return self._set_eq_curve(_EQ_METAL)

    def jazz(self) -> Filters:
        """Apply a warm jazz equalizer preset."""

        return self._set_eq_curve(_EQ_JAZZ)

    def classical(self) -> Filters:
        """Apply a classical equalizer preset (warm lows, gentle treble roll-off)."""

        return self._set_eq_curve(_EQ_CLASSICAL)

    def electronic(self) -> Filters:
        """Apply an electronic / EDM equalizer preset (sub-bass and air)."""

        return self._set_eq_curve(_EQ_ELECTRONIC)

    def vocal(self) -> Filters:
        """Apply a vocal-clarity equalizer preset (presence boost, trimmed extremes)."""

        return self._set_eq_curve(_EQ_VOCAL)

    def flat(self) -> Filters:
        """Reset the equalizer to a neutral, flat response."""

        return self.set_equalizer()

    # Routed through presets because the names collide with the component
    # properties (``tremolo``/``vibrato``/``karaoke``/``distortion``).
    def _preset_tremolo(self) -> Filters:
        return self.set_tremolo(frequency=4.0, depth=0.6)

    def _preset_vibrato(self) -> Filters:
        return self.set_vibrato(frequency=4.0, depth=0.6)

    def _preset_karaoke(self) -> Filters:
        return self.set_karaoke(
            level=1.0,
            mono_level=1.0,
            filter_band=220.0,
            filter_width=100.0,
        )

    def _preset_distortion(self) -> Filters:
        return self.set_distortion(
            sin_scale=1.5,
            cos_scale=1.5,
            tan_scale=1.5,
            scale=1.0,
        )

    def _set_eq_curve(self, gains: Sequence[float]) -> Filters:
        return self.set_equalizer(_eq_curve(gains))

    def set_volume(self, value: float | None) -> Filters:
        """Set Lavalink filter volume, or remove it with `None`."""

        self._set_or_remove("volume", value)
        return self

    def set_equalizer(
        self,
        bands: list[dict[str, float | int]] | None = None,
        /,
        **gains: float,
    ) -> Filters:
        """Set equalizer bands.

        Accepts either Lavalink-style band dictionaries or keyword gains like
        `band_0=0.2`.
        """

        if bands is None and not gains:
            self._payload.pop("equalizer", None)
            return self

        payload = bands.copy() if bands is not None else []
        for name, gain in gains.items():
            if not name.startswith("band_"):
                raise ValueError(f"Equalizer keyword must look like band_0, got {name!r}.")
            payload.append({"band": int(name.removeprefix("band_")), "gain": gain})

        self._payload["equalizer"] = payload
        return self

    def set_karaoke(
        self,
        *,
        level: float | None = None,
        mono_level: float | None = None,
        filter_band: float | None = None,
        filter_width: float | None = None,
    ) -> Filters:
        """Set karaoke filter options."""

        return self._set_filter(
            "karaoke",
            {
                "level": level,
                "monoLevel": mono_level,
                "filterBand": filter_band,
                "filterWidth": filter_width,
            },
        )

    def set_timescale(
        self,
        *,
        speed: float | None = None,
        pitch: float | None = None,
        rate: float | None = None,
    ) -> Filters:
        """Set timescale filter options."""

        return self._set_filter("timescale", {"speed": speed, "pitch": pitch, "rate": rate})

    def set_tremolo(self, *, frequency: float | None = None, depth: float | None = None) -> Filters:
        """Set tremolo filter options."""

        return self._set_filter("tremolo", {"frequency": frequency, "depth": depth})

    def set_vibrato(self, *, frequency: float | None = None, depth: float | None = None) -> Filters:
        """Set vibrato filter options."""

        return self._set_filter("vibrato", {"frequency": frequency, "depth": depth})

    def set_rotation(self, *, rotation_hz: float | None = None) -> Filters:
        """Set rotation filter options."""

        return self._set_filter("rotation", {"rotationHz": rotation_hz})

    def set_distortion(
        self,
        *,
        sin_offset: float | None = None,
        sin_scale: float | None = None,
        cos_offset: float | None = None,
        cos_scale: float | None = None,
        tan_offset: float | None = None,
        tan_scale: float | None = None,
        offset: float | None = None,
        scale: float | None = None,
    ) -> Filters:
        """Set distortion filter options."""

        return self._set_filter(
            "distortion",
            {
                "sinOffset": sin_offset,
                "sinScale": sin_scale,
                "cosOffset": cos_offset,
                "cosScale": cos_scale,
                "tanOffset": tan_offset,
                "tanScale": tan_scale,
                "offset": offset,
                "scale": scale,
            },
        )

    def set_channel_mix(
        self,
        *,
        left_to_left: float | None = None,
        left_to_right: float | None = None,
        right_to_left: float | None = None,
        right_to_right: float | None = None,
    ) -> Filters:
        """Set channel-mix filter options."""

        return self._set_filter(
            "channelMix",
            {
                "leftToLeft": left_to_left,
                "leftToRight": left_to_right,
                "rightToLeft": right_to_left,
                "rightToRight": right_to_right,
            },
        )

    def set_low_pass(self, *, smoothing: float | None = None) -> Filters:
        """Set low-pass filter options."""

        return self._set_filter("lowPass", {"smoothing": smoothing})

    def set_plugin_filters(self, filters: JsonObject | None = None, /, **kwargs: object) -> Filters:
        """Set plugin-specific filter payloads."""

        if filters is None and not kwargs:
            self._payload.pop("pluginFilters", None)
            return self

        payload = _clean_mapping(filters or {})
        payload.update(_clean_mapping(kwargs))
        self._payload["pluginFilters"] = payload
        return self

    def set_filters(
        self,
        *,
        volume: float | None = None,
        equalizer: list[dict[str, float | int]] | None = None,
        karaoke: JsonObject | None = None,
        timescale: JsonObject | None = None,
        tremolo: JsonObject | None = None,
        vibrato: JsonObject | None = None,
        rotation: JsonObject | None = None,
        distortion: JsonObject | None = None,
        channel_mix: JsonObject | None = None,
        low_pass: JsonObject | None = None,
        plugin_filters: JsonObject | None = None,
        reset: bool = False,
    ) -> Filters:
        """Bulk set filter sections using Wavelink-style names."""

        if reset:
            self.reset()
        if volume is not None:
            self.set_volume(volume)
        if equalizer is not None:
            self.set_equalizer(equalizer)
        self._set_named_payload("karaoke", karaoke)
        self._set_named_payload("timescale", timescale)
        self._set_named_payload("tremolo", tremolo)
        self._set_named_payload("vibrato", vibrato)
        self._set_named_payload("rotation", rotation)
        self._set_named_payload("distortion", distortion)
        self._set_named_payload("channelMix", channel_mix)
        self._set_named_payload("lowPass", low_pass)
        if plugin_filters is not None:
            self.set_plugin_filters(plugin_filters)
        return self

    def remove(self, name: str) -> Filters:
        """Remove a filter by Lavalink payload key."""

        self._payload.pop(name, None)
        return self

    def _set_filter(self, name: str, payload: JsonObject) -> Filters:
        cleaned = _clean_mapping(payload)
        if cleaned:
            self._payload[name] = cleaned
        else:
            self._payload.pop(name, None)
        return self

    def _set_or_remove(self, name: str, value: object | None) -> None:
        if value is None:
            self._payload.pop(name, None)
        else:
            self._payload[name] = value

    def _set_named_payload(self, name: str, payload: JsonObject | None) -> None:
        if payload is not None:
            self._set_filter(name, payload)


def _clean_mapping(payload: JsonObject) -> JsonObject:
    return {key: value for key, value in payload.items() if value is not None}


def _eq_curve(gains: Sequence[float]) -> list[dict[str, float | int]]:
    """Turn a sequence of per-band gains into Lavalink equalizer bands.

    Bands whose gain is zero are omitted to keep the payload compact.
    """

    return [{"band": index, "gain": round(gain, 4)} for index, gain in enumerate(gains) if gain]


# Maps every :class:`FilterPreset` to the builder that applies it. Members whose
# names would clash with the typed component properties (``tremolo``, ``vibrato``,
# ``karaoke``, ``distortion``, ``rotation``) are routed to private preset methods.
_PRESET_BUILDERS: dict[FilterPreset, Callable[..., Filters]] = {
    FilterPreset.NIGHTCORE: lambda f, **_: f.nightcore(),
    FilterPreset.VAPORWAVE: lambda f, **_: f.vaporwave(),
    FilterPreset.DAYCORE: lambda f, **_: f.daycore(),
    FilterPreset.SLOWED: lambda f, **_: f.slowed(),
    FilterPreset.SPED_UP: lambda f, **_: f.sped_up(),
    FilterPreset.CHIPMUNK: lambda f, **_: f.chipmunk(),
    FilterPreset.DEEP: lambda f, **_: f.deep(),
    FilterPreset.DOUBLE_TIME: lambda f, **_: f.double_time(),
    FilterPreset.EIGHT_D: lambda f, **kw: f.eight_d(**kw),
    FilterPreset.PARTY: lambda f, **_: f.party(),
    FilterPreset.ROTATION: lambda f, **kw: f.eight_d(**kw),
    FilterPreset.TREMOLO: lambda f, **_: f._preset_tremolo(),
    FilterPreset.VIBRATO: lambda f, **_: f._preset_vibrato(),
    FilterPreset.KARAOKE: lambda f, **_: f._preset_karaoke(),
    FilterPreset.DISTORTION: lambda f, **_: f._preset_distortion(),
    FilterPreset.SOFT: lambda f, **_: f.soft(),
    FilterPreset.MUFFLED: lambda f, **_: f.muffled(),
    FilterPreset.LOFI: lambda f, **_: f.lofi(),
    FilterPreset.SLOWED_REVERB: lambda f, **_: f.slowed_reverb(),
    FilterPreset.MONO: lambda f, **_: f.mono(),
    FilterPreset.BASS_BOOST: lambda f, **kw: f.bass_boost(**kw),
    FilterPreset.BASS_BOOST_EXTREME: lambda f, **_: f.bass_boost_extreme(),
    FilterPreset.TREBLE_BOOST: lambda f, **_: f.treble_boost(),
    FilterPreset.POP: lambda f, **_: f.pop(),
    FilterPreset.ROCK: lambda f, **_: f.rock(),
    FilterPreset.METAL: lambda f, **_: f.metal(),
    FilterPreset.JAZZ: lambda f, **_: f.jazz(),
    FilterPreset.CLASSICAL: lambda f, **_: f.classical(),
    FilterPreset.ELECTRONIC: lambda f, **_: f.electronic(),
    FilterPreset.VOCAL: lambda f, **_: f.vocal(),
    FilterPreset.FLAT: lambda f, **_: f.flat(),
}


@dataclass(slots=True)
class FilterComponent:
    """Mutable view over one Lavalink filter payload section."""

    filters: Filters
    key: str
    setter: Callable[..., Filters]

    @property
    def payload(self) -> JsonObject:
        """Return this component's current payload."""

        value = self.filters.to_payload().get(self.key)
        return value.copy() if isinstance(value, dict) else {}

    def reset(self) -> Filters:
        """Remove this component from the parent filters."""

        return self.filters.remove(self.key)


@dataclass(slots=True)
class KaraokeFilter(FilterComponent):
    """Typed view over Lavalink karaoke options."""

    def set(
        self,
        *,
        level: float | None = None,
        mono_level: float | None = None,
        filter_band: float | None = None,
        filter_width: float | None = None,
    ) -> Filters:
        """Set karaoke options."""

        return self.filters.set_karaoke(
            level=level,
            mono_level=mono_level,
            filter_band=filter_band,
            filter_width=filter_width,
        )


@dataclass(slots=True)
class TimescaleFilter(FilterComponent):
    """Typed view over Lavalink timescale options."""

    def set(
        self,
        *,
        speed: float | None = None,
        pitch: float | None = None,
        rate: float | None = None,
    ) -> Filters:
        """Set timescale options."""

        return self.filters.set_timescale(speed=speed, pitch=pitch, rate=rate)


@dataclass(slots=True)
class TremoloFilter(FilterComponent):
    """Typed view over Lavalink tremolo options."""

    def set(self, *, frequency: float | None = None, depth: float | None = None) -> Filters:
        """Set tremolo options."""

        return self.filters.set_tremolo(frequency=frequency, depth=depth)


@dataclass(slots=True)
class VibratoFilter(FilterComponent):
    """Typed view over Lavalink vibrato options."""

    def set(self, *, frequency: float | None = None, depth: float | None = None) -> Filters:
        """Set vibrato options."""

        return self.filters.set_vibrato(frequency=frequency, depth=depth)


@dataclass(slots=True)
class RotationFilter(FilterComponent):
    """Typed view over Lavalink rotation options."""

    def set(self, *, rotation_hz: float | None = None) -> Filters:
        """Set rotation options."""

        return self.filters.set_rotation(rotation_hz=rotation_hz)


@dataclass(slots=True)
class DistortionFilter(FilterComponent):
    """Typed view over Lavalink distortion options."""

    def set(
        self,
        *,
        sin_offset: float | None = None,
        sin_scale: float | None = None,
        cos_offset: float | None = None,
        cos_scale: float | None = None,
        tan_offset: float | None = None,
        tan_scale: float | None = None,
        offset: float | None = None,
        scale: float | None = None,
    ) -> Filters:
        """Set distortion options."""

        return self.filters.set_distortion(
            sin_offset=sin_offset,
            sin_scale=sin_scale,
            cos_offset=cos_offset,
            cos_scale=cos_scale,
            tan_offset=tan_offset,
            tan_scale=tan_scale,
            offset=offset,
            scale=scale,
        )


@dataclass(slots=True)
class ChannelMixFilter(FilterComponent):
    """Typed view over Lavalink channel-mix options."""

    def set(
        self,
        *,
        left_to_left: float | None = None,
        left_to_right: float | None = None,
        right_to_left: float | None = None,
        right_to_right: float | None = None,
    ) -> Filters:
        """Set channel-mix options."""

        return self.filters.set_channel_mix(
            left_to_left=left_to_left,
            left_to_right=left_to_right,
            right_to_left=right_to_left,
            right_to_right=right_to_right,
        )


@dataclass(slots=True)
class LowPassFilter(FilterComponent):
    """Typed view over Lavalink low-pass options."""

    def set(self, *, smoothing: float | None = None) -> Filters:
        """Set low-pass options."""

        return self.filters.set_low_pass(smoothing=smoothing)


@dataclass(slots=True)
class EqualizerFilter:
    """Mutable view over the Lavalink equalizer payload."""

    filters: Filters

    @property
    def payload(self) -> list[dict[str, float | int]]:
        """Return the current equalizer band payload."""

        value = self.filters.to_payload().get("equalizer")
        return [band.copy() for band in value] if isinstance(value, list) else []

    def set(
        self,
        bands: list[dict[str, float | int]] | None = None,
        /,
        **gains: float,
    ) -> Filters:
        """Set equalizer bands."""

        return self.filters.set_equalizer(bands, **gains)

    def reset(self) -> Filters:
        """Remove equalizer bands."""

        return self.filters.remove("equalizer")


@dataclass(slots=True)
class PluginFiltersComponent:
    """Mutable view over Lavalink plugin filter payloads."""

    filters: Filters

    @property
    def payload(self) -> JsonObject:
        """Return the current plugin filter payload."""

        value = self.filters.to_payload().get("pluginFilters")
        return value.copy() if isinstance(value, dict) else {}

    def set(self, filters: JsonObject | None = None, /, **kwargs: object) -> Filters:
        """Set plugin filter payloads."""

        return self.filters.set_plugin_filters(filters, **kwargs)

    def reset(self) -> Filters:
        """Remove plugin filter payloads."""

        return self.filters.remove("pluginFilters")


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _blend_payloads(
    a: dict[str, object],
    b: dict[str, object],
    t: float,
) -> dict[str, object]:
    result: dict[str, object] = {}
    all_keys = set(a) | set(b)
    for key in all_keys:
        av = a.get(key)
        bv = b.get(key)
        if av is None:
            result[key] = bv
        elif bv is None:
            result[key] = av
        elif (
            isinstance(av, (int, float))
            and not isinstance(av, bool)
            and isinstance(bv, (int, float))
            and not isinstance(bv, bool)
        ):
            result[key] = _lerp(float(av), float(bv), t)
        elif isinstance(av, dict) and isinstance(bv, dict):
            result[key] = _blend_payloads(av, bv, t)
        elif isinstance(av, list) and isinstance(bv, list):
            result[key] = _blend_eq_bands(av, bv, t)
        else:
            result[key] = bv if t >= 0.5 else av
    return result


def _blend_eq_bands(
    a: list[object],
    b: list[object],
    t: float,
) -> list[object]:
    """Interpolate equalizer band lists."""
    a_bands = {
        int(item["band"]): float(item["gain"])
        for item in a
        if isinstance(item, dict) and "band" in item and "gain" in item
    }
    b_bands = {
        int(item["band"]): float(item["gain"])
        for item in b
        if isinstance(item, dict) and "band" in item and "gain" in item
    }
    all_bands = sorted(set(a_bands) | set(b_bands))
    return [
        {"band": band, "gain": _lerp(a_bands.get(band, 0.0), b_bands.get(band, 0.0), t)}
        for band in all_bands
    ]
