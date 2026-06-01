import fluxwave


def track_payload() -> dict[str, object]:
    return {
        "encoded": "abc",
        "info": {
            "identifier": "id",
            "isSeekable": True,
            "author": "artist",
            "length": 1234,
            "isStream": False,
            "position": 0,
            "title": "song",
            "uri": "https://example.test/song",
            "artworkUrl": "https://example.test/art.png",
            "isrc": "US123",
            "sourceName": "youtube",
        },
        "pluginInfo": {"album": "album"},
        "userData": {"requester": 1},
    }


class SearchNode:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, bool]] = []

    async def search(
        self,
        query: str,
        *,
        source: object = None,
        use_cache: bool = True,
    ) -> list[fluxwave.Track]:
        self.calls.append((query, source, use_cache))
        return [fluxwave.Track.from_payload(track_payload())]


def test_track_from_lavalink_payload() -> None:
    track = fluxwave.Track.from_payload(track_payload())

    assert track.encoded == "abc"
    assert track.title == "song"
    assert track.author == "artist"
    assert track.duration == 1234
    assert track.length == 1234
    assert track.position == 0
    assert track.source == "youtube"
    assert track.plugin_info == {"album": "album"}
    assert track.plugin_value("album") == "album"
    assert track.plugin_value("missing", "fallback") == "fallback"
    assert track.user_data == {"requester": 1}
    assert track.info.raw["sourceName"] == "youtube"
    assert track.identifier == "id"
    assert track.artwork_url == "https://example.test/art.png"
    assert track.artwork == "https://example.test/art.png"
    assert track.raw_data["encoded"] == "abc"
    assert track.playlist is None
    assert track.is_seekable
    assert not track.is_stream
    assert track.album.name == "album"
    assert track.extras.requester == 1
    track.extras.reason = "test"
    assert track.user_data["reason"] == "test"
    assert track.raw_data["userData"] == {"requester": 1, "reason": "test"}
    track.extras = {"requester": 2}
    assert track.extras.requester == 2
    assert track.user_data == {"requester": 2}
    assert track.raw_data["userData"] == {"requester": 2}
    assert track.extras.to_dict()["requester"] == 2
    copied = track.with_user_data(extra=True)
    assert copied.user_data == {
        "requester": 2,
        "extra": True,
    }
    assert copied.raw_data["userData"] == {"requester": 2, "extra": True}
    assert track.as_recommended().recommended
    assert str(track) == "song — artist [0:01]"
    assert "Track(title='song'" in repr(track)
    assert track == fluxwave.Track.from_payload(track_payload())
    assert hash(track) == hash("abc")


def test_search_load_result_from_payload() -> None:
    result = fluxwave.LoadResult.from_payload({"loadType": "search", "data": [track_payload()]})

    assert result.load_type is fluxwave.LoadType.SEARCH
    assert len(result.tracks) == 1
    assert result.tracks[0].title == "song"


async def test_track_search_class_helper_uses_node_search() -> None:
    node = SearchNode()

    result = await fluxwave.Track.search(
        "hello",
        source=fluxwave.SearchSource.SOUNDCLOUD,
        node=node,
        use_cache=False,
    )

    assert isinstance(result, list)
    assert result[0].title == "song"
    assert node.calls == [("hello", fluxwave.SearchSource.SOUNDCLOUD, False)]


async def test_track_search_defaults_to_youtube_music() -> None:
    node = SearchNode()

    await fluxwave.Track.search("hello", node=node)

    assert node.calls == [("hello", "ytmsearch", True)]


def test_custom_load_result_preserves_plugin_payload() -> None:
    result = fluxwave.LoadResult.from_payload(
        {
            "loadType": "lyrics",
            "data": {
                "pluginInfo": {"provider": "test"},
                "lines": ["hello"],
            },
        }
    )

    assert result.load_type is fluxwave.LoadType.CUSTOM
    assert result.raw_load_type == "lyrics"
    assert result.plugin_info == {"provider": "test"}
    assert result.custom_data == {
        "pluginInfo": {"provider": "test"},
        "lines": ["hello"],
    }


def test_playlist_load_result_from_payload() -> None:
    result = fluxwave.LoadResult.from_payload(
        {
            "loadType": "playlist",
            "data": {
                "info": {"name": "mix", "selectedTrack": 0},
                "tracks": [track_payload()],
                "pluginInfo": {"source": "test"},
            },
        }
    )

    assert result.playlist is not None
    assert result.playlist.name == "mix"
    assert result.playlist.selected_track == 0
    assert result.playlist.info.raw["selectedTrack"] == 0
    assert result.playlist.info.tracks == 1
    assert result.plugin_info == {"source": "test"}
    assert len(result.playlist) == 1
    assert result.playlist[0].encoded == "abc"
    assert result.playlist[0].playlist == result.playlist.info
    assert next(iter(result.playlist)).encoded == "abc"
    assert result.playlist.with_user_data(requester=2)[0].user_data["requester"] == 2
    result.playlist.track_extras(guild_id=123)
    assert result.playlist[0].extras.guild_id == 123
    result.playlist.extras = {"requester": 99}
    assert result.playlist[0].extras.requester == 99
    assert result.playlist[0].user_data == {"requester": 99}
    assert result.playlist[0].raw_data["userData"] == {"requester": 99}
    result.playlist.extras.requester = 100
    assert result.playlist[0].extras.requester == 100
    assert result.playlist[0].raw_data["userData"] == {"requester": 100}
    assert result.tracks[0].encoded == "abc"
    assert str(result.playlist) == "mix"
    assert repr(result.playlist) == "Playlist(name='mix', tracks=1)"
    assert result.playlist.selected is result.playlist[0]
    assert result.playlist.metadata["track_count"] == 1
    assert result.playlist.artwork is None
    assert result.playlist.limited(1).tracks == result.playlist.tracks
    assert result.playlist.playable_tracks(limit=1) == result.playlist.tracks


def test_node_info_from_payload() -> None:
    info = fluxwave.NodeInfo.from_payload(
        {
            "version": {"semver": "4.0.0", "major": 4, "minor": 0, "patch": 0},
            "buildTime": 1,
            "git": {"branch": "main", "commit": "sha", "commitTime": 2},
            "jvm": "Java",
            "lavaplayer": "1.0",
            "sourceManagers": ["youtube"],
            "filters": ["timescale"],
            "plugins": [{"name": "plugin", "version": "1.0"}],
        }
    )

    assert info.version.major == 4
    assert info.git.commit == "sha"
    assert info.plugins[0].name == "plugin"


def test_stats_from_payload() -> None:
    stats = fluxwave.Stats.from_payload(
        {
            "players": 2,
            "playingPlayers": 1,
            "uptime": 100,
            "memory": {"free": 1, "used": 2, "allocated": 3, "reservable": 4},
            "cpu": {"cores": 8, "systemLoad": 0.2, "lavalinkLoad": 0.1},
            "frameStats": {"sent": 10, "nulled": 0, "deficit": 1},
        }
    )

    assert stats.players == 2
    assert stats.memory.used == 2
    assert stats.frame_stats is not None
    assert stats.frame_stats.deficit == 1
