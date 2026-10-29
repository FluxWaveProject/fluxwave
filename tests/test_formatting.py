from collections.abc import Iterator

import fluxwave


def track(encoded: str = "abc", *, stream: bool = False) -> fluxwave.Track:
    return fluxwave.Track.from_payload(
        {
            "encoded": encoded,
            "info": {
                "identifier": encoded,
                "isSeekable": True,
                "author": "artist",
                "length": 180_000,
                "isStream": stream,
                "position": 0,
                "title": f"song-{encoded}",
                "sourceName": "youtube",
                "uri": f"https://example.test/{encoded}",
            },
            "userData": {"requester": 42},
        }
    )


class FakeQueue:
    def __init__(self, tracks: list[fluxwave.Track], mode: object = None) -> None:
        self._tracks = tracks
        self.mode = mode
        self.total_duration = sum(t.duration for t in tracks)

    def __iter__(self) -> Iterator[fluxwave.Track]:
        return iter(self._tracks)

    def __len__(self) -> int:
        return len(self._tracks)


class FakePlayer:
    def __init__(
        self,
        current: fluxwave.Track | None = None,
        queue: FakeQueue | None = None,
    ) -> None:
        self.current = current
        self.queue = queue if queue is not None else FakeQueue([])
        self.position = 60_000
        self.volume = 80
        self.paused = False
        self.autoplay = "disabled"


def test_now_playing_snapshot_from_player() -> None:
    current = track("now")
    queue = FakeQueue([track("a"), track("b")], mode=fluxwave.QueueMode.NORMAL)
    player = FakePlayer(current, queue)

    view = fluxwave.NowPlaying.from_player(player)

    assert view.title == "song-now"
    assert view.duration == 180_000
    assert view.queue_length == 2
    assert view.volume == 80
    assert view.loop_mode == "normal"
    assert view.requester == 42
    assert view.to_dict()["title"] == "song-now"


def test_now_playing_progress_and_fields() -> None:
    player = FakePlayer(track("now"), FakeQueue([track("a")]))

    view = fluxwave.NowPlaying.from_player(player)

    assert view.progress(length=10)
    fields = {name: value for name, value, _ in view.fields()}
    assert fields["Volume"] == "80%"
    assert fields["Queue"] == "1"
    assert fields["Requested by"] == "42"


def test_now_playing_idle_state() -> None:
    view = fluxwave.NowPlaying.from_player(FakePlayer())

    assert view.title == "Nothing playing"
    assert view.progress() == ""
    assert view.fields()[0][0] == "Playback"
    assert view.to_dict()["queue_length"] == 0


def test_queue_view_from_queue_renders_pages() -> None:
    queue = FakeQueue([track(f"t{i}") for i in range(23)])

    view = fluxwave.QueueView.from_queue(queue, current=track("now"), per_page=10)

    assert view.page_count == 3
    assert view.total_duration == 23 * 180_000
    assert len(view.page(0).items) == 10
    assert len(view.page(2).items) == 3
    assert view.page(5) is view.page(2)


def test_queue_view_fields_include_header_and_totals() -> None:
    queue = FakeQueue([track("a"), track("b")])
    view = fluxwave.QueueView.from_queue(queue, current=track("now"))

    fields = {name: value for name, value, _ in view.fields()}
    header = next(name for name in fields if name.startswith("Queue"))
    assert "Now:" in fields[header]

    payload = view.to_dict()
    assert payload["total"] == 2
    assert payload["lines"][0].startswith("1. song-a")
