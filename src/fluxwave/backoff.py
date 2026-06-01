"""Jittered reconnect backoff helpers."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class Backoff:
    """Randomized exponential backoff for reconnect loops."""

    base: float = 0.5
    maximum_time: float = 30.0
    maximum_tries: int | None = None
    jitter: bool = True
    _retries: int = field(default=1, init=False)
    _last_wait: float = field(default=0.0, init=False)
    _random: Callable[[float, float], float] = field(
        default_factory=lambda: random.Random().uniform,
        init=False,
        repr=False,
    )

    def calculate(self) -> float:
        """Return the next delay and advance internal retry state."""

        if self.base <= 0:
            return 0.0

        exponent = min(float(self._retries * self._retries), self.maximum_time)
        ceiling = min(self.maximum_time, self.base * 2 * exponent)
        wait = self._random(0.0, ceiling) if self.jitter else ceiling

        if self.jitter and wait <= self._last_wait:
            wait = min(self.maximum_time, self._last_wait * 2 if self._last_wait else ceiling)

        self._last_wait = wait
        if self.maximum_tries is not None and self._retries >= self.maximum_tries:
            self.reset()
        else:
            self._retries += 1

        return wait

    def reset(self) -> None:
        """Reset retry counters."""

        self._retries = 1
        self._last_wait = 0.0
