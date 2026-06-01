import asyncio

import pytest

import fluxwave


def track(encoded: str) -> fluxwave.Track:
    return fluxwave.Track.from_payload(
        {
            "encoded": encoded,
            "info": {
                "identifier": encoded,
                "isSeekable": True,
                "author": "artist",
                "length": 1000,
                "isStream": False,
                "position": 0,
                "title": encoded,
            },
        }
    )


def test_queue_put_get_history_and_loaded() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")

    assert queue([first, second]) == 2
    assert queue.peek() is first
    assert queue.get() is first

    assert queue.loaded is first
    assert queue.current is first
    assert queue.history is not None
    assert queue.history.peek() is first
    assert queue.get() is second
    assert str(queue) == "Queue(count=0, mode=normal)"
    assert "Queue(items=0" in repr(queue)


def test_queue_put_playlist_tracks() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")
    playlist = fluxwave.Playlist(
        info=fluxwave.tracks.PlaylistInfo(name="mix"),
        tracks=[first, second],
    )

    assert queue.put(playlist) == 2
    assert queue.get() is first
    assert queue.get() is second


def test_queue_loop_modes() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")
    queue.put([first, second])

    assert queue.get() is first
    queue.mode = fluxwave.QueueMode.LOOP
    assert queue.get() is first
    assert queue.get(bypass_loop=True) is second

    queue.put(first)
    queue.mode = fluxwave.QueueMode.LOOP_ALL
    assert queue.get() is first
    assert queue.peek() is second


def test_queue_bypass_loop_does_not_replay_loaded_track() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")
    queue.put([first, second])

    assert queue.get() is first
    queue.mode = fluxwave.QueueMode.LOOP

    assert queue.get(bypass_loop=True) is second


def test_queue_remove_swap_shuffle_clear_reset() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")
    third = track("third")
    queue.put([first, second, third])

    queue.swap(0, 2)
    assert queue.peek() is third
    assert queue.index(second) == 1
    queue[1] = second
    assert queue[1] is second
    del queue[1]
    assert next(reversed(queue)) is first
    assert queue.remove(first) == 1
    queue.shuffle()
    assert len(queue) == 1
    queue.clear()
    assert queue.is_empty
    queue.loaded = first
    queue.mode = fluxwave.QueueMode.LOOP
    queue.reset()
    assert queue.loaded is None
    assert queue.mode is fluxwave.QueueMode.NORMAL
    assert fluxwave.QueueMode.normal is fluxwave.QueueMode.NORMAL
    assert fluxwave.QueueMode.loop is fluxwave.QueueMode.LOOP
    assert fluxwave.QueueMode.loop_all is fluxwave.QueueMode.LOOP_ALL


def test_queue_move_dedupe_find_and_clear_next() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")
    duplicate = track("second")
    third = track("third")
    queue.put([first, second, duplicate, third])

    moved = queue.move(3, 1)
    assert moved is third
    assert queue[1] is third
    assert queue.find("thi") is third
    assert queue.find_all("artist") == [first, third, second, duplicate]
    assert queue.dedupe() == 1
    assert queue.clear_next(2) == [first, third]
    assert list(queue) == [second]


def test_queue_put_at_accepts_multiple_tracks() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")
    third = track("third")
    queue.put(first)

    assert queue.put_at(0, [second, third]) == 2
    assert list(queue) == [second, third, first]


def test_queue_max_size_overflow_drops_oldest_on_append() -> None:
    queue = fluxwave.Queue(max_size=2, overflow=True)
    first = track("first")
    second = track("second")
    third = track("third")

    assert queue.put([first, second, third]) == 3

    assert list(queue) == [second, third]
    assert queue.max_size == 2
    assert queue.overflow is True


def test_queue_max_size_overflow_keeps_front_insertions() -> None:
    queue = fluxwave.Queue(max_size=3)
    first = track("first")
    second = track("second")
    third = track("third")
    next_track = track("next")
    queue.put([first, second, third])

    assert queue.put_at(0, next_track) == 1

    assert list(queue) == [next_track, first, second]


def test_queue_max_size_strict_raises_without_mutating_atomic_put() -> None:
    queue = fluxwave.Queue(max_size=2, overflow=False)
    first = track("first")
    second = track("second")
    third = track("third")
    queue.put([first, second])

    with pytest.raises(fluxwave.QueueFull):
        queue.put(third)

    assert list(queue) == [first, second]


def test_queue_max_size_strict_allows_partial_non_atomic_put() -> None:
    queue = fluxwave.Queue(max_size=2, overflow=False)
    first = track("first")
    second = track("second")
    third = track("third")

    with pytest.raises(fluxwave.QueueFull):
        queue.put([first, second, third], atomic=False)

    assert list(queue) == [first, second]


def test_queue_raw_data_and_copy_preserve_capacity_settings() -> None:
    queue = fluxwave.Queue(max_size=2, overflow=False)
    first = track("first")
    queue.put(first)

    data = queue.to_raw_data()
    restored = fluxwave.Queue.from_payloads(**data)
    copied = queue.copy()

    assert restored.max_size == 2
    assert restored.overflow is False
    assert restored.peek().encoded == "first"
    assert copied.max_size == 2
    assert copied.overflow is False


def test_queue_rejects_invalid_max_size() -> None:
    with pytest.raises(ValueError):
        fluxwave.Queue(max_size=0)

    queue = fluxwave.Queue(max_size=3, overflow=False)
    queue.put([track("first"), track("second"), track("third")])

    with pytest.raises(fluxwave.QueueFull):
        queue.max_size = 2


async def test_queue_get_wait_receives_next_track() -> None:
    queue = fluxwave.Queue()
    pending = asyncio.create_task(queue.get_wait())
    await asyncio.sleep(0)

    first = track("first")
    queue.put(first)

    assert await pending is first
    assert queue.loaded is first


async def test_queue_get_wait_waits_for_real_item_in_loop_mode() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")
    queue.loaded = first
    queue.mode = fluxwave.QueueMode.LOOP

    pending = asyncio.create_task(queue.get_wait())
    await asyncio.sleep(0)

    assert not pending.done()
    queue.put(second)

    assert await pending is second
    assert queue.loaded is second


async def test_queue_reset_cancels_pending_waiters() -> None:
    queue = fluxwave.Queue()
    pending = asyncio.create_task(queue.get_wait())
    await asyncio.sleep(0)

    queue.reset()

    with pytest.raises(asyncio.CancelledError):
        await pending


def test_queue_copy_preserves_items_loaded_history_and_mode() -> None:
    queue = fluxwave.Queue()
    first = track("first")
    second = track("second")
    queue.put([first, second])
    assert queue.get() is first
    queue.mode = fluxwave.QueueMode.LOOP_ALL

    copied = queue.copy()

    assert copied is not queue
    assert copied.loaded is first
    assert copied.mode is fluxwave.QueueMode.LOOP_ALL
    assert copied.peek() is second
    assert copied.history is not None
    assert copied.history.peek() is first


def test_queue_validation_and_empty_errors() -> None:
    queue = fluxwave.Queue()

    with pytest.raises(fluxwave.QueueEmpty):
        queue.get()

    with pytest.raises(TypeError):
        queue.put([object()])  # type: ignore[list-item]
