import time

import fluxwave
from fluxwave.watchdog import VoiceWatchdog, WatchdogConfig


def make_track(
    identifier: str = "id", *, is_stream: bool = False, length: int = 120_000
) -> fluxwave.Track:
    return fluxwave.Track.from_payload(
        {
            "encoded": identifier,
            "info": {
                "identifier": identifier,
                "isSeekable": True,
                "author": "artist",
                "length": length,
                "isStream": is_stream,
                "position": 0,
                "title": "song",
                "sourceName": "youtube",
            },
        }
    )


def test_backoff_holds_at_maximum_instead_of_resetting() -> None:
    backoff = fluxwave.Backoff(base=1.0, maximum_time=5.0, jitter=False)

    values = [backoff.calculate() for _ in range(4)]

    assert values[0] == 2.0
    assert values[1] == 5.0
    assert values[2] == 5.0
    assert values[3] == 5.0


def test_search_does_not_treat_plain_colon_query_as_source_prefix() -> None:
    query = fluxwave.build_search_query("artist:song")

    assert not query.has_prefix
    assert query.identifier == "ytsearch:artist:song"


def test_search_still_preserves_real_source_prefix() -> None:
    query = fluxwave.build_search_query("scsearch:some song")

    assert query.has_prefix
    assert query.identifier == "scsearch:some song"


def test_search_preserves_timestamp_like_query() -> None:
    query = fluxwave.build_search_query("3:45 song")

    assert not query.has_prefix
    assert query.identifier == "ytsearch:3:45 song"


def test_version_parses_bare_snapshot() -> None:
    version = fluxwave.parse_lavalink_version("SNAPSHOT")

    assert version.base == (4, 0, 0)
    assert version.is_snapshot


def test_version_comparison_with_labels_does_not_raise() -> None:
    plain = fluxwave.parse_lavalink_version("4.0.0")
    labelled = fluxwave.parse_lavalink_version("4.0.0-rc1")
    newer = fluxwave.parse_lavalink_version("4.1.0")

    assert not (plain < labelled)
    assert not (labelled < plain)
    assert plain < newer
    assert sorted([newer, plain]) == [plain, newer]


def test_tracer_recent_zero_returns_empty() -> None:
    tracer = fluxwave.EventTracer()
    tracer.enable()
    tracer.trace(fluxwave.TraceCategory.NODE, "one")
    tracer.trace(fluxwave.TraceCategory.NODE, "two")

    assert tracer.recent(0) == []
    assert len(tracer.recent(1)) == 1


def test_lyrics_at_returns_latest_by_timestamp_when_unsorted() -> None:
    result = fluxwave.LyricsResult(
        text="",
        lines=[
            fluxwave.LyricsLine(text="late", timestamp=5000),
            fluxwave.LyricsLine(text="early", timestamp=1000),
        ],
    )

    assert result.at(2000).text == "early"
    assert result.at(6000).text == "late"


def test_loop_all_does_not_grow_history_unboundedly() -> None:
    queue = fluxwave.Queue()
    queue.put([make_track("a"), make_track("b")])
    queue.mode = fluxwave.QueueMode.LOOP_ALL

    for _ in range(25):
        queue.get()

    assert queue.history is not None
    assert len(queue.history) <= 2
    assert len(queue) == 1


class _WatchdogPlayer:
    def __init__(self, current: fluxwave.Track, position: int) -> None:
        self.destroyed = False
        self.paused = False
        self.playing = True
        self.position = position
        self.raw_position = position
        self.current = current
        self.played: list[fluxwave.Track] = []

        class _Guild:
            id = 1

        self.guild = _Guild()

    async def play(self, track: fluxwave.Track, **kwargs: object) -> fluxwave.Track:
        self.played.append(track)
        return track


async def test_watchdog_does_not_recover_live_stream() -> None:
    stream = make_track("live", is_stream=True, length=0)
    player = _WatchdogPlayer(stream, position=0)
    watchdog = VoiceWatchdog(player, WatchdogConfig(stagnation_threshold=0.0, max_strikes=1))  # type: ignore[arg-type]
    watchdog._last_position = 0
    watchdog._last_change_at = time.monotonic() - 100

    await watchdog._tick()

    assert watchdog.stats.strikes == 0
    assert watchdog.stats.recoveries == 0
    assert player.played == []


async def test_watchdog_does_not_recover_track_at_end() -> None:
    finished = make_track("done", length=1000)
    player = _WatchdogPlayer(finished, position=1000)
    watchdog = VoiceWatchdog(player, WatchdogConfig(stagnation_threshold=0.0, max_strikes=1))  # type: ignore[arg-type]
    watchdog._last_position = 1000
    watchdog._last_change_at = time.monotonic() - 100

    await watchdog._tick()

    assert watchdog.stats.strikes == 0
    assert watchdog.stats.recoveries == 0
    assert player.played == []
