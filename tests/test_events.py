import asyncio

import fluxwave


async def test_dispatcher_runs_sync_and_async_listeners() -> None:
    dispatcher = fluxwave.EventDispatcher()
    received: list[object] = []

    async def async_listener(payload: object) -> None:
        received.append(("async", payload))

    dispatcher.on(fluxwave.EventType.NODE_READY, received.append)
    dispatcher.on(fluxwave.EventType.NODE_READY, async_listener)

    payload = fluxwave.NodeReadyEvent(identifier="node", session_id="session", resumed=False)
    dispatcher.dispatch(fluxwave.EventType.NODE_READY, payload)
    await asyncio.sleep(0)

    assert received == [payload, ("async", payload)]
    await dispatcher.close()


async def test_dispatcher_isolates_listener_errors() -> None:
    dispatcher = fluxwave.EventDispatcher()
    received: list[object] = []

    def broken_listener(_payload: object) -> None:
        raise RuntimeError("listener failed")

    dispatcher.on("track_start", broken_listener)
    dispatcher.on("track_start", received.append)

    payload = object()
    dispatcher.dispatch("track_start", payload)

    assert received == [payload]
    await dispatcher.close()


async def test_global_listen_decorator_receives_events() -> None:
    received: list[object] = []

    @fluxwave.listen("track_start")
    async def on_track_start(payload: object) -> None:
        received.append(payload)

    payload = object()
    fluxwave.dispatch("track_start", payload)
    await asyncio.sleep(0)

    assert received == [payload]
    fluxwave.remove_listener("track_start", on_track_start)
    await fluxwave.close_listeners()


def test_new_lifecycle_event_types_are_available() -> None:
    assert fluxwave.EventType.PLAYER_CONNECT == "connect"
    assert fluxwave.EventType.PLAYER_DISCONNECT == "disconnect"
    assert fluxwave.EventType.SPONSORBLOCK_SKIP == "sponsorblock_skip"


async def test_connect_and_disconnect_events_reach_listeners() -> None:
    received: list[object] = []
    dispatcher = fluxwave.EventDispatcher()
    dispatcher.on(fluxwave.EventType.PLAYER_CONNECT, received.append)
    dispatcher.on(fluxwave.EventType.PLAYER_DISCONNECT, received.append)

    dispatcher.dispatch(
        fluxwave.EventType.PLAYER_CONNECT,
        fluxwave.PlayerConnectEvent(1, channel_id=2),
    )
    dispatcher.dispatch(
        fluxwave.EventType.PLAYER_DISCONNECT,
        fluxwave.PlayerDisconnectEvent(1, reason="destroyed"),
    )
    await asyncio.sleep(0)

    assert [type(event).__name__ for event in received] == [
        "PlayerConnectEvent",
        "PlayerDisconnectEvent",
    ]
    await dispatcher.close()


async def test_sponsorblock_skip_event_reaches_listeners() -> None:
    received: list[object] = []
    dispatcher = fluxwave.EventDispatcher()
    dispatcher.on(fluxwave.EventType.SPONSORBLOCK_SKIP, received.append)

    segment = fluxwave.SponsorSegment(category="sponsor", start=0, end=5000)
    dispatcher.dispatch(
        fluxwave.EventType.SPONSORBLOCK_SKIP,
        fluxwave.SponsorBlockSkipEvent(1, segment=segment, position=1000, skipped=True),
    )
    await asyncio.sleep(0)

    assert received == [
        fluxwave.SponsorBlockSkipEvent(1, segment=segment, position=1000, skipped=True)
    ]
    await dispatcher.close()
