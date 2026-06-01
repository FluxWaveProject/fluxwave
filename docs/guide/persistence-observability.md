# Persistence and Observability

FluxWave includes small production helpers for saving playback state and
debugging runtime behavior.

## Quick Links

- [Persisted State](#persisted-state)
- [Backends](#backends)
- [Metrics](#metrics)
- [Tracing](#tracing)
- [Voice Watchdog](#voice-watchdog)

## Persisted State

Capture a player:

```python
state = player.save_state(extra={"reason": "shutdown"})  # snapshot current playback
```

The snapshot includes:

- Guild ID and channel ID.
- Current track raw payload.
- Current position.
- Pause state.
- Volume.
- Queue mode.
- Queued track payloads.
- Queue history payloads.
- Autoplay mode.
- Autoplay queue payloads and autoplay queue history payloads.
- Recommendation seed payloads and recently used seed IDs.
- Filter payload.
- Caller-defined `extra` metadata.

Serialize:

```python
text = state.to_json(indent=2)  # serialize snapshot to JSON
restored = fluxwave.PersistedState.from_json(text)  # rebuild snapshot from JSON
```

Restore:

```python
await player.restore_state(restored, seek=True)  # reload state and seek to saved position
```

The player must already be connected to a voice channel before restore.

## Backends

`MemoryStore` is for development and single-process bots:

```python
store = fluxwave.MemoryStore()  # in-memory persistence backend
await store.save(player.guild.id, player.save_state())  # persist the snapshot by guild
state = await store.load(player.guild.id)  # read it back later
await store.delete(player.guild.id)  # drop the saved snapshot
```

Production bots should implement `PersistenceBackend` against Redis, Postgres,
SQLite, or another durable system.

## Metrics

```python
fluxwave.metrics.track_play_count  # global count of tracks played
fluxwave.metrics.node("main").search_count  # per-node search counter
snapshot = fluxwave.metrics.to_dict()  # export all counters as a dict
fluxwave.metrics.reset()  # zero out all counters
```

Metrics are in-process counters. They do not export Prometheus/OpenTelemetry by
themselves, but `to_dict()` is easy to bridge.

## Tracing

```python
fluxwave.tracer.enable()  # start recording trace events
fluxwave.tracer.trace(
    fluxwave.TraceCategory.PLAYER,
    "custom event",
    guild_id=123,
    command="play",
)  # record a custom trace event
recent = fluxwave.tracer.recent(20)  # fetch the 20 latest events
fluxwave.tracer.disable()  # stop recording
```

Useful filters:

```python
fluxwave.tracer.by_category(fluxwave.TraceCategory.VOICE)  # only voice events
fluxwave.tracer.for_guild(123)  # only events for this guild
fluxwave.tracer.for_node("main")  # only events for this node
fluxwave.tracer.clear()  # discard all recorded events
```

## Voice Watchdog

```python
watchdog = fluxwave.VoiceWatchdog(
    player,
    fluxwave.WatchdogConfig(
        check_interval=5,  # seconds between health checks
        stagnation_threshold=12,  # seconds of frozen position before a strike
        max_strikes=3,  # strikes before recovery action
        auto_restart_track=True,  # restart the track when stalled
    ),
)
watchdog.start()  # begin monitoring playback
```

Or from the player:

```python
watchdog = player.start_watchdog()  # auto-recover stalled playback
```

Stop it during shutdown:

```python
watchdog.stop()  # stop monitoring during shutdown
```
