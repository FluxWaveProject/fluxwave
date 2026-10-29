from pathlib import Path

import pytest

import fluxwave


def track(encoded: str = "abc") -> fluxwave.Track:
    return fluxwave.Track.from_payload(
        {
            "encoded": encoded,
            "info": {
                "identifier": encoded,
                "isSeekable": True,
                "author": "artist",
                "length": 120_000,
                "isStream": False,
                "position": 0,
                "title": f"song-{encoded}",
                "sourceName": "youtube",
            },
            "userData": {"requester": 1},
        }
    )


def test_saved_playlist_serialises_tracks_round_trip() -> None:
    playlist = fluxwave.SavedPlaylist.from_tracks(1, "Chill", [track("a"), track("b")])

    restored = fluxwave.SavedPlaylist.from_json(playlist.to_json())

    assert restored.name == "Chill"
    assert restored.size == 2
    assert [t.identifier for t in restored.tracks] == ["a", "b"]
    assert restored.renamed("New").name == "New"
    assert restored.with_tracks([track("c")]).size == 1


def test_saved_playlist_key_is_case_insensitive() -> None:
    playlist = fluxwave.SavedPlaylist.from_tracks(1, "Chill Mix", [])

    assert playlist.key == "chill mix"


def test_from_dict_ignores_non_dict_track_entries() -> None:
    playlist = fluxwave.SavedPlaylist.from_dict(
        {"name": "x", "owner_id": 1, "track_payloads": [{}, "junk", 5]}
    )

    assert playlist.size == 1


async def test_manager_create_get_and_duplicate_guard() -> None:
    manager = fluxwave.PlaylistManager()

    created = await manager.create(1, "Chill", [track("a")])
    assert created.owner_id == 1
    assert (await manager.get(1, "chill")) is not None

    with pytest.raises(fluxwave.PlaylistAlreadyExists):
        await manager.create(1, "Chill")

    overwritten = await manager.create(1, "Chill", [track("b")], overwrite=True)
    assert [t.identifier for t in overwritten.tracks] == ["b"]


async def test_manager_requires_existing_playlists() -> None:
    manager = fluxwave.PlaylistManager()

    with pytest.raises(fluxwave.PlaylistNotFound):
        await manager.require(1, "missing")


async def test_manager_lists_only_owner_playlists_sorted() -> None:
    manager = fluxwave.PlaylistManager()
    await manager.create(1, "Zed")
    await manager.create(1, "alpha")
    await manager.create(2, "other")

    assert [p.name for p in await manager.list(1)] == ["alpha", "Zed"]


async def test_manager_rename_rejects_taken_names() -> None:
    manager = fluxwave.PlaylistManager()
    await manager.create(1, "first")
    await manager.create(1, "second")

    with pytest.raises(fluxwave.PlaylistAlreadyExists):
        await manager.rename(1, "first", "second")

    renamed = await manager.rename(1, "first", "third")
    assert renamed.name == "third"
    assert await manager.get(1, "first") is None
    assert await manager.get(1, "third") is not None


async def test_manager_add_and_remove_tracks() -> None:
    manager = fluxwave.PlaylistManager()
    await manager.create(1, "mix", [track("a")])

    updated = await manager.add_tracks(1, "mix", [track("b"), track("c")])
    assert updated.size == 3

    removed = await manager.remove_index(1, "mix", 1)
    assert removed.identifier == "b"
    assert (await manager.require(1, "mix")).size == 2

    with pytest.raises(fluxwave.PlaylistError):
        await manager.remove_index(1, "mix", 99)


async def test_manager_delete_reports_whether_it_existed() -> None:
    manager = fluxwave.PlaylistManager()
    await manager.create(1, "temp")

    assert await manager.delete(1, "temp") is True
    assert await manager.delete(1, "temp") is False


async def test_manager_rejects_empty_names() -> None:
    manager = fluxwave.PlaylistManager()

    with pytest.raises(fluxwave.PlaylistError):
        await manager.create(1, "   ")


async def test_file_store_persists_across_instances(tmp_path: Path) -> None:
    store = fluxwave.FilePlaylistStore(tmp_path / "playlists")
    manager = fluxwave.PlaylistManager(store)
    await manager.create(1, "Chill", [track("a")])

    reloaded = fluxwave.PlaylistManager(fluxwave.FilePlaylistStore(tmp_path / "playlists"))
    playlist = await reloaded.require(1, "Chill")

    assert [t.identifier for t in playlist.tracks] == ["a"]

    assert await reloaded.delete(1, "Chill") is True
    assert await reloaded.get(1, "Chill") is None
