"""Small cache utilities used by FluxWave internals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


@dataclass(slots=True)
class _LFUEntry(Generic[ValueT]):
    value: ValueT
    frequency: int
    sequence: int


class LFUCache(Generic[KeyT, ValueT]):
    """Least-frequently-used cache with oldest-entry tie breaking."""

    def __init__(self, capacity: int) -> None:
        if capacity < 0:
            msg = "Cache capacity cannot be negative."
            raise ValueError(msg)

        self._capacity = capacity
        self._entries: dict[KeyT, _LFUEntry[ValueT]] = {}
        self._sequence = 0

    @property
    def capacity(self) -> int:
        """Maximum number of values this cache can hold."""

        return self._capacity

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def clear(self) -> None:
        """Remove all cached values."""

        self._entries.clear()

    def get(self, key: KeyT) -> ValueT | None:
        """Return a cached value and increase its usage count."""

        entry = self._entries.get(key)
        if entry is None:
            return None

        self._touch(entry)
        return entry.value

    def put(self, key: KeyT, value: ValueT) -> None:
        """Cache a value, evicting the least-used entry when full."""

        if self._capacity <= 0:
            return

        existing = self._entries.get(key)
        if existing is not None:
            existing.value = value
            self._touch(existing)
            return

        if len(self._entries) >= self._capacity:
            self._evict()

        self._sequence += 1
        self._entries[key] = _LFUEntry(value=value, frequency=1, sequence=self._sequence)

    def _touch(self, entry: _LFUEntry[ValueT]) -> None:
        self._sequence += 1
        entry.frequency += 1
        entry.sequence = self._sequence

    def _evict(self) -> None:
        victim = min(
            self._entries,
            key=lambda key: (self._entries[key].frequency, self._entries[key].sequence),
        )
        del self._entries[victim]
