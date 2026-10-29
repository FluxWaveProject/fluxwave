import base64
import json

import pytest

import fluxwave


def payload(*, encoded: str | None = "abc", title: str = "song") -> dict[str, object]:
    data: dict[str, object] = {
        "info": {
            "identifier": encoded or "abc",
            "isSeekable": True,
            "author": "artist",
            "length": 120_000,
            "isStream": False,
            "position": 0,
            "title": title,
            "sourceName": "youtube",
        },
        "userData": {"requester": 1},
    }
    if encoded is not None:
        data["encoded"] = encoded
    return data


def encode(data: dict[str, object], *, strip_padding: bool = False) -> str:
    raw = base64.b64encode(json.dumps(data).encode()).decode()
    return raw.rstrip("=") if strip_padding else raw


def test_encode_returns_the_encoded_string() -> None:
    track = fluxwave.Track.from_payload(payload(encoded="abc"))

    assert track.encode() == "abc"


def test_decode_round_trips_base64_json() -> None:
    track = fluxwave.Track.decode(encode(payload(encoded="abc")))

    assert track.identifier == "abc"
    assert track.title == "song"
    assert track.encoded == "abc"


def test_decode_accepts_unpadded_strings_and_backfills_encoded() -> None:
    track = fluxwave.Track.decode(encode(payload(encoded=None), strip_padding=True))

    assert track.title == "song"
    assert track.encoded


def test_decode_rejects_empty_strings() -> None:
    with pytest.raises(fluxwave.TrackDecodeError):
        fluxwave.Track.decode("   ")


def test_decode_rejects_invalid_base64_json() -> None:
    with pytest.raises(fluxwave.TrackDecodeError):
        fluxwave.Track.decode("!!!not-valid@@@")


def test_decode_rejects_non_object_payloads() -> None:
    with pytest.raises(fluxwave.TrackDecodeError):
        fluxwave.Track.decode(base64.b64encode(b"[1, 2, 3]").decode())


LAVALINK_TRACK = (
    "QAAAjQIAJVJpY2sgQXN0bGV5IC0gTmV2ZXIgR29ubmEgR2l2ZSBZb3UgVXAADlJpY2tBc3Rs"
    "ZXlWRVZPAAAAAAADPCAAC2RRdzR3OVdnWGNRAAEAK2h0dHBzOi8vd3d3LnlvdXR1YmUuY29t"
    "L3dhdGNoP3Y9ZFF3NHc5V2dYY1EAB3lvdXR1YmUAAAAAAAAAAA=="
)


def test_decode_real_lavalink_binary_track() -> None:
    track = fluxwave.Track.decode(LAVALINK_TRACK)

    assert track.title == "Rick Astley - Never Gonna Give You Up"
    assert track.author == "RickAstleyVEVO"
    assert track.identifier == "dQw4w9WgXcQ"
    assert track.duration == 212_000
    assert track.is_stream is False
    assert track.uri == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert track.source == "youtube"
    assert track.position == 0
    assert track.encoded == LAVALINK_TRACK
    assert track.raw_data["encoded"] == LAVALINK_TRACK


def test_decode_real_lavalink_v3_track_includes_artwork() -> None:
    encoded = (
        "QAAA3wMAPFJpY2sgQXN0bGV5IC0gTmV2ZXIgR29ubmEgR2l2ZSBZb3UgVXAgKE9mZmljaWFs"
        "IE11c2ljIFZpZGVvKQALUmljayBBc3RsZXkAAAAAAAM8IAALZFF3NHc5V2dYY1EAAQAraHR0"
        "cHM6Ly93d3cueW91dHViZS5jb20vd2F0Y2g/dj1kUXc0dzlXZ1hjUQEAOmh0dHBzOi8vaS55"
        "dGltZy5jb20vdmlfd2VicC9kUXc0dzlXZ1hjUS9tYXhyZXNkZWZhdWx0LndlYnAAAAd5b3V0"
        "dWJlAAAAAAAAAAA="
    )

    track = fluxwave.Track.decode(encoded)

    assert track.title.endswith("(Official Music Video)")
    assert track.artwork_url == ("https://i.ytimg.com/vi_webp/dQw4w9WgXcQ/maxresdefault.webp")
    assert track.isrc is None


def test_decode_real_lavalink_binary_track_with_cesu8_title() -> None:
    # NodeLink/SoundCloud title containing an emoji encoded as a Java
    # surrogate pair (CESU-8).
    encoded = (
        "QAAA5wMANzQgQS5NIFN0dWR5IFNlc3Npb24g7aC97bOaIC0gW2xvZmkgaGlwIGhvcC9jaGls"
        "bCBiZWF0c10ACUxvZmkgR2lybAAAAAAAOIc1AAoxMDM1ODQxOTQyAAEAMmh0dHBzOi8vc291"
        "bmRjbG91ZC5jb20vbG9maV9naXJsLzQtYW0tc3R1ZHlzZXNzaW9uAQBAaHR0cHM6Ly9pMS5z"
        "bmRjZG4uY29tL2FydHdvcmtzLUFZcFVCbXpIRmRWU2QwUnktMGZSU1F3LWxhcmdlLmpwZwAA"
        "CnNvdW5kY2xvdWQAAAAAAAAAAA=="
    )

    track = fluxwave.Track.decode(encoded)

    assert "📚" in track.title
    assert track.author == "Lofi Girl"


def test_decode_rejects_truncated_binary_track() -> None:
    raw = base64.b64decode(LAVALINK_TRACK)
    truncated = base64.b64encode(raw[: len(raw) // 2]).decode()

    with pytest.raises(fluxwave.TrackDecodeError):
        fluxwave.Track.decode(truncated)
