"""Client-side rate limiting for Lavalink REST requests."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Mapping


class RateLimiter:
    """Sliding-window limiter with server-driven penalties.

    ``rate`` is the number of requests allowed per ``per`` seconds and ``burst``
    is the maximum number of requests allowed to happen back-to-back. When
    ``rate`` is ``None`` the limiter only honours server-driven penalties, so it
    stays cheap for bots that never hit a limit::

        limiter = fluxwave.RateLimiter(rate=10, per=1.0, burst=20)
        rest = fluxwave.RestClient(uri, password, user_id, rate_limiter=limiter)
    """

    __slots__ = ("_burst", "_lock", "_penalty_until", "_per", "_rate", "_timestamps", "max_delay")

    def __init__(
        self,
        *,
        rate: float | None = None,
        per: float = 1.0,
        burst: int | None = None,
        max_delay: float = 30.0,
    ) -> None:
        if rate is not None and rate <= 0:
            msg = "RateLimiter rate must be positive or None."
            raise ValueError(msg)
        if per <= 0:
            msg = "RateLimiter per must be positive."
            raise ValueError(msg)

        self._rate = rate
        self._per = per
        self._burst = max(int(burst), 1) if burst is not None else (int(rate) if rate else 1)
        self._lock = asyncio.Lock()
        self._timestamps: deque[float] = deque()
        self._penalty_until = 0.0
        self.max_delay = max(max_delay, 0.0)

    @property
    def rate(self) -> float | None:
        """Configured requests-per-``per`` window, or ``None`` for unthrottled."""

        return self._rate

    @property
    def burst(self) -> int:
        """Maximum number of requests allowed in a single burst."""

        return self._burst

    def penalize(self, seconds: float) -> None:
        """Block new requests for *seconds* (clamped to ``max_delay``)."""

        delay = max(min(seconds, self.max_delay), 0.0)
        self._penalty_until = max(self._penalty_until, time.monotonic() + delay)

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """React to Lavalink rate-limit response headers, if any are present.

        Only a fully-spent bucket (``remaining == 0``) triggers a penalty, so
        headers with activity remaining are treated as informational.
        """

        remaining = _optional_float(headers.get("X-RateLimit-Remaining"))
        if remaining is None or remaining > 0:
            return

        reset_after = _optional_float(headers.get("X-RateLimit-Reset-After"))
        if reset_after is not None:
            self.penalize(reset_after)

    async def acquire(self) -> None:
        """Wait until a request may be sent."""

        if self._rate is None and self._penalty_until <= 0:
            return

        while True:
            async with self._lock:
                now = time.monotonic()
                if now < self._penalty_until:
                    wait = self._penalty_until - now
                else:
                    self._penalty_until = 0.0
                    wait = self._reserve(now)
                    if wait <= 0:
                        return
            await asyncio.sleep(wait)

    def _reserve(self, now: float) -> float:
        """Reserve a slot, returning seconds to wait (0 when one is free)."""

        if self._rate is None:
            return 0.0

        window_start = now - self._per
        while self._timestamps and self._timestamps[0] <= window_start:
            self._timestamps.popleft()

        if len(self._timestamps) < self._burst:
            self._timestamps.append(now)
            return 0.0

        # Wait until the oldest reservation falls out of the window.
        return max(self._timestamps[0] + self._per - now, 0.0)

    def __repr__(self) -> str:
        return f"RateLimiter(rate={self._rate!r}, per={self._per!r}, burst={self._burst!r})"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str | int | float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None
