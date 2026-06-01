"""Smooth volume-fade transitions between tracks (opt-in crossfade)."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .metrics import metrics
from .tracing import TraceCategory, tracer

if TYPE_CHECKING:
    from .player import FluxPlayer
    from .tracks import Track

logger = logging.getLogger(__name__)

# Re-check cadence for the fade-out watcher. Capped so a pause or seek that
# changes the remaining time is noticed within a few seconds instead of the
# watcher sleeping straight through a stale deadline.
_WATCH_RECHECK = 3.0


class FadeCurve(StrEnum):
    """Shape of a volume fade over its duration."""

    LINEAR = "linear"
    SMOOTH = "smooth"
    EQUAL_POWER = "equal_power"


def fade_fraction(curve: FadeCurve, progress: float) -> float:
    """Map fade progress in ``[0, 1]`` to a completed fraction in ``[0, 1]``."""

    progress = max(0.0, min(1.0, progress))
    if curve is FadeCurve.LINEAR:
        return progress
    if curve is FadeCurve.EQUAL_POWER:
        return math.sin(progress * math.pi / 2)
    return progress * progress * (3.0 - 2.0 * progress)


@dataclass(slots=True)
class CrossfadeConfig:
    """Tuning knobs for :class:`Crossfade`."""

    duration: float = 4.0
    """Fade length in seconds for both the fade-out and the next fade-in."""

    fade_in: bool = True
    """Whether new tracks ramp up from ``floor_volume`` to the player volume."""

    fade_out: bool = True
    """Whether tracks ramp down to ``floor_volume`` as they approach their end."""

    curve: FadeCurve = FadeCurve.SMOOTH
    """Fade shape applied to each ramp."""

    floor_volume: int = 0
    """Volume a fade starts from and ends at (``0`` is silent)."""

    update_interval: float = 0.2
    """Seconds between volume updates during a fade (smaller is smoother but
    sends more requests to Lavalink)."""

    min_track_duration: float = 10.0
    """Tracks shorter than this (seconds) are played without fading."""


@dataclass(slots=True)
class CrossfadeStats:
    """Runtime counters exposed by :class:`Crossfade`."""

    transitions: int = 0
    fade_ins: int = 0
    fade_outs: int = 0


class Crossfade:
    """Drives smooth volume transitions for a :class:`~fluxwave.FluxPlayer`.

    Lavalink plays one track per player, so this is a fade-out of the ending
    track followed by a fade-in of the next one (not a true overlapping mix). The
    seam is smooth because the outgoing track reaches ``floor_volume`` just as the
    incoming track starts from it.

    Attach it through the player rather than constructing it directly::

        player.enable_crossfade(duration=5)
    """

    __slots__ = ("_player", "_watch_task", "config", "stats")

    def __init__(self, player: FluxPlayer, config: CrossfadeConfig | None = None) -> None:
        self._player = player
        self.config = config or CrossfadeConfig()
        self.stats = CrossfadeStats()
        self._watch_task: asyncio.Task[None] | None = None

    def initial_play_volume(self, track: Track | None, target: int, *, paused: bool) -> int:
        """Volume a freshly loaded track should start at before any fade-in."""

        if self.config.fade_in and not paused and self._eligible(track):
            return self.config.floor_volume
        return target

    def on_track_loaded(self, track: Track | None, target: int, *, paused: bool) -> None:
        """Begin the fade-in for a newly loaded track and arm its fade-out."""

        self._cancel_watch()
        if paused or not self._eligible(track):
            return

        if self.config.fade_in:
            self.stats.transitions += 1
            self.stats.fade_ins += 1
            metrics.crossfade_count += 1
            tracer.trace(TraceCategory.FADE, "fade_in", guild_id=self._player.guild.id)
            self._player._start_volume_fade(
                self.config.floor_volume,
                target,
                duration=self.config.duration,
                curve=self.config.curve,
                update_interval=self.config.update_interval,
                commit=False,
            )

        if self.config.fade_out:
            self._schedule_watch()

    def start_for_current(self) -> None:
        """Arm the fade-out for the already-playing track (used when enabling mid-song)."""

        if self.config.fade_out:
            self._schedule_watch()

    async def on_seek(self) -> None:
        """Recompute the fade-out and undo a fade-out interrupted by a backward seek."""

        if self.config.duration <= 0:
            return
        if self._player._fade_active:
            self._player._cancel_volume_fade()
            await self._player._restore_volume()
        if self.config.fade_out:
            self._schedule_watch()

    def cancel(self) -> None:
        """Stop the fade-out watcher (the player owns and cancels the fade task)."""

        self._cancel_watch()

    def _eligible(self, track: Track | None) -> bool:
        if self.config.duration <= 0 or track is None:
            return False
        if track.is_stream or track.duration <= 0:
            return False
        return track.duration >= self.config.min_track_duration * 1000

    def _schedule_watch(self) -> None:
        self._cancel_watch()
        if not self._eligible(self._player.current):
            return
        self._watch_task = asyncio.create_task(
            self._watch(),
            name=f"fluxwave:crossfade:{self._player.guild.id}",
        )

    def _cancel_watch(self) -> None:
        if self._watch_task is not None and not self._watch_task.done():
            self._watch_task.cancel()
        self._watch_task = None

    async def _watch(self) -> None:
        player = self._player
        config = self.config
        fade_ms = config.duration * 1000.0
        try:
            while True:
                if player.destroyed:
                    return
                current = player.current
                if current is None or current.is_stream or current.duration <= 0:
                    return

                remaining = current.duration - player.position
                lead = remaining - fade_ms
                if lead > 0:
                    await asyncio.sleep(min(lead / 1000.0, _WATCH_RECHECK))
                    continue

                fade_seconds = min(config.duration, max(0.0, remaining / 1000.0))
                if fade_seconds <= 0:
                    return

                self.stats.fade_outs += 1
                tracer.trace(TraceCategory.FADE, "fade_out", guild_id=player.guild.id)
                player._start_volume_fade(
                    player.volume,
                    config.floor_volume,
                    duration=fade_seconds,
                    curve=config.curve,
                    update_interval=config.update_interval,
                    commit=False,
                )
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Crossfade watcher failed for guild %s.", player.guild.id)
