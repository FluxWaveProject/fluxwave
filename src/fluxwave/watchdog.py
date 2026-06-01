"""Voice connection watchdog: detects silent/stalled audio and triggers recovery."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .metrics import metrics
from .tracing import TraceCategory, tracer

if TYPE_CHECKING:
    from .player import FluxPlayer

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WatchdogConfig:
    """Tuning knobs for :class:`VoiceWatchdog`."""

    check_interval: float = 5.0
    """Seconds between health checks."""

    stagnation_threshold: float = 12.0
    """Seconds of position freeze before a strike is registered."""

    max_strikes: int = 3
    """Consecutive strikes before recovery is attempted."""

    auto_restart_track: bool = True
    """Whether to restart the current track from its last known position on recovery."""

    backoff_after_recovery: float = 10.0
    """Seconds to skip checks after a recovery attempt to avoid tight loops."""


@dataclass(slots=True)
class WatchdogStats:
    """Runtime counters exposed by :class:`VoiceWatchdog`."""

    strikes: int = 0
    recoveries: int = 0
    last_recovery_at: float = 0.0


class VoiceWatchdog:
    """Monitors a :class:`~fluxwave.FluxPlayer` for silent-audio / frozen-transport conditions.

    Position stagnation detection: if ``player.raw_position`` (the last
    Lavalink-reported position) does not advance while the player reports active
    playback, strikes accumulate. On reaching ``config.max_strikes`` a recovery is
    attempted (restart track from last position).

    Typical usage::

        watchdog = VoiceWatchdog(player)
        watchdog.start()
        # ...
        watchdog.stop()
    """

    __slots__ = (
        "_backoff_until",
        "_config",
        "_last_change_at",
        "_last_position",
        "_player",
        "_task",
        "stats",
    )

    def __init__(
        self,
        player: FluxPlayer,
        config: WatchdogConfig | None = None,
    ) -> None:
        self._player = player
        self._config = config or WatchdogConfig()
        self._task: asyncio.Task[None] | None = None
        self._last_position: int = -1
        self._last_change_at: float = 0.0
        self._backoff_until: float = 0.0
        self.stats = WatchdogStats()

    def start(self) -> None:
        """Start the background watchdog task."""
        if self._task is None or self._task.done():
            guild_id = self._player.guild.id
            self._task = asyncio.create_task(
                self._run(),
                name=f"fluxwave:watchdog:{guild_id}",
            )

    def stop(self) -> None:
        """Cancel the background watchdog task."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._reset_counters()

    @property
    def running(self) -> bool:
        """Whether the watchdog task is active."""
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._config.check_interval)
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Watchdog tick raised for guild %s.",
                    self._player.guild.id,
                )

    async def _tick(self) -> None:
        player = self._player
        if player.destroyed:
            self.stop()
            return

        now = time.monotonic()
        if now < self._backoff_until:
            return

        if not player.playing or player.paused:
            self._reset_counters()
            return

        # Use the raw server-reported position, NOT player.position: the latter is
        # extrapolated from a monotonic clock and keeps advancing every tick even
        # when Lavalink has stopped sending updates, which would make a freeze
        # undetectable. raw_position only moves when a real player update arrives.
        position = player.raw_position
        current = player.current
        if current is not None and (
            current.is_stream or (current.duration > 0 and position >= current.duration)
        ):
            self._reset_counters()
            return

        if position != self._last_position:
            self._last_position = position
            self._last_change_at = now
            self.stats.strikes = 0
            return

        frozen_for = now - self._last_change_at
        if self._last_change_at == 0.0:
            self._last_change_at = now
            return

        if frozen_for >= self._config.stagnation_threshold:
            self.stats.strikes += 1
            logger.warning(
                "Watchdog: position frozen %.1fs for guild %s (strike %d/%d).",
                frozen_for,
                player.guild.id,
                self.stats.strikes,
                self._config.max_strikes,
            )
            if self.stats.strikes >= self._config.max_strikes:
                await self._recover(position)

    async def _recover(self, last_position: int) -> None:
        player = self._player
        logger.warning(
            "Watchdog: attempting recovery for guild %s at position %dms.",
            player.guild.id,
            last_position,
        )
        self._reset_counters()
        self._backoff_until = time.monotonic() + self._config.backoff_after_recovery
        self.stats.recoveries += 1
        self.stats.last_recovery_at = time.monotonic()
        metrics.watchdog_recovery_count += 1
        tracer.trace(
            TraceCategory.WATCHDOG, "recover", guild_id=player.guild.id, position=last_position
        )

        if not self._config.auto_restart_track:
            return

        current = player.current
        if current is None:
            return

        try:
            await player.play(current, start=last_position, replace=True)
            logger.info(
                "Watchdog: recovery succeeded for guild %s.",
                player.guild.id,
            )
        except Exception:
            logger.exception(
                "Watchdog: recovery failed for guild %s.",
                player.guild.id,
            )

    def _reset_counters(self) -> None:
        self.stats.strikes = 0
        self._last_position = -1
        self._last_change_at = 0.0
