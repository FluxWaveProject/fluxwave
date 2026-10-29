import time

import pytest

import fluxwave


def test_rate_limiter_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        fluxwave.RateLimiter(rate=0)
    with pytest.raises(ValueError):
        fluxwave.RateLimiter(per=0)


def test_rate_limiter_exposes_configuration() -> None:
    limiter = fluxwave.RateLimiter(rate=5, per=2.0, burst=3)

    assert limiter.rate == 5
    assert limiter.burst == 3
    assert "RateLimiter" in repr(limiter)


async def test_unthrottled_limiter_does_not_wait() -> None:
    limiter = fluxwave.RateLimiter(rate=None)

    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()

    assert time.monotonic() - start < 0.05


async def test_limiter_enforces_requests_per_window() -> None:
    limiter = fluxwave.RateLimiter(rate=1, per=0.05, burst=1)

    await limiter.acquire()
    start = time.monotonic()
    await limiter.acquire()

    assert time.monotonic() - start >= 0.03


async def test_penalize_blocks_until_delay_elapses() -> None:
    limiter = fluxwave.RateLimiter(rate=None, max_delay=0.05)
    limiter.penalize(10.0)

    start = time.monotonic()
    await limiter.acquire()

    assert 0.04 <= time.monotonic() - start <= 0.3


async def test_update_from_headers_penalizes_only_when_spent() -> None:
    limiter = fluxwave.RateLimiter(rate=None, max_delay=0.05)
    limiter.update_from_headers({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset-After": "10"})

    start = time.monotonic()
    await limiter.acquire()
    assert time.monotonic() - start < 0.05

    limiter.update_from_headers({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "0.05"})
    start = time.monotonic()
    await limiter.acquire()
    assert time.monotonic() - start >= 0.03
