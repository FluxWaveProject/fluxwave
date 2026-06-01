import pytest

import fluxwave


def test_backoff_jitter_and_reset() -> None:
    backoff = fluxwave.Backoff(base=0.5, maximum_time=5.0, maximum_tries=3, jitter=True)
    values = [backoff.calculate() for _ in range(3)]

    assert all(0 <= value <= 5.0 for value in values)
    assert values[1] >= values[0]

    backoff.reset()
    assert 0 <= backoff.calculate() <= 5.0


def test_backoff_can_disable_jitter() -> None:
    backoff = fluxwave.Backoff(base=0.5, maximum_time=5.0, jitter=False)

    assert backoff.calculate() == 1.0
    assert backoff.calculate() == 4.0


def test_lfu_cache_reuses_hot_entry_and_evicts_cold_entry() -> None:
    cache = fluxwave.LFUCache[str, int](2)
    cache.put("a", 1)
    cache.put("b", 2)

    assert cache.get("a") == 1
    cache.put("c", 3)

    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_lfu_cache_rejects_negative_capacity() -> None:
    with pytest.raises(ValueError):
        fluxwave.LFUCache[str, int](-1)
