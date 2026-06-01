"""Discord-independent Lavalink data models."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator, MutableMapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, overload

from .types import JsonObject, JsonValue

if TYPE_CHECKING:
    from .search import Search, SearchSource


class TrackSearchNode(Protocol):
    """Search-capable node or pool used by `Track.search`."""

    async def search(
        self,
        query: str,
        *,
        source: SearchSource | str | None = None,
        use_cache: bool = True,
    ) -> Search:
        """Search tracks or playlists."""
        ...


class ExtrasNamespace(MutableMapping[str, object]):
    """Dictionary wrapper that also exposes string keys as attributes."""

    _data: JsonObject
    _on_update: Callable[[JsonObject], None] | None

    def __init__(
        self,
        data: JsonObject | None = None,
        *,
        on_update: Callable[[JsonObject], None] | None = None,
    ) -> None:
        object.__setattr__(self, "_data", data if data is not None else {})
        object.__setattr__(self, "_on_update", on_update)

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __setitem__(self, key: str, value: object) -> None:
        self._data[key] = value
        self._notify()

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._notify()

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __getattr__(self, name: str) -> object:
        try:
            return self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"_data", "_on_update"}:
            object.__setattr__(self, name, value)
            return

        self._data[name] = value
        self._notify()

    def __delattr__(self, name: str) -> None:
        try:
            del self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        self._notify()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._data!r})"

    def to_dict(self) -> JsonObject:
        """Return a shallow copy of the underlying data."""

        return self._data.copy()

    def _notify(self) -> None:
        if self._on_update is not None:
            self._on_update(self._data)


class LoadType(StrEnum):
    """Normalized Lavalink load result types."""

    TRACK = "track"
    PLAYLIST = "playlist"
    SEARCH = "search"
    EMPTY = "empty"
    ERROR = "error"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class Album:
    """Source/plugin album metadata."""

    name: str | None = None
    url: str | None = None
    artwork_url: str | None = None

    @classmethod
    def from_payload(cls, payload: JsonObject) -> Album:
        album = payload.get("album")
        if isinstance(album, dict):
            return cls(
                name=_optional_str(album.get("name")),
                url=_optional_str(album.get("url")),
                artwork_url=_optional_str(album.get("artworkUrl")),
            )

        return cls(
            name=_optional_str(album) or _optional_str(payload.get("albumName")),
            url=_optional_str(payload.get("albumUrl")),
            artwork_url=_optional_str(payload.get("albumArtworkUrl")),
        )


@dataclass(frozen=True, slots=True)
class Artist:
    """Source/plugin artist metadata."""

    name: str | None = None
    url: str | None = None
    artwork_url: str | None = None

    @classmethod
    def from_payload(cls, payload: JsonObject) -> Artist:
        artist = payload.get("artist")
        if isinstance(artist, dict):
            return cls(
                name=_optional_str(artist.get("name")),
                url=_optional_str(artist.get("url")),
                artwork_url=_optional_str(artist.get("artworkUrl")),
            )

        return cls(
            name=_optional_str(artist) or _optional_str(payload.get("artistName")),
            url=_optional_str(payload.get("artistUrl")),
            artwork_url=_optional_str(payload.get("artistArtworkUrl")),
        )


@dataclass(frozen=True, slots=True)
class TrackInfo:
    """Metadata for a Lavalink track."""

    identifier: str
    is_seekable: bool
    author: str
    length: int
    is_stream: bool
    position: int
    title: str
    uri: str | None = None
    artwork_url: str | None = None
    isrc: str | None = None
    source_name: str | None = None
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: JsonObject) -> TrackInfo:
        """Build track metadata from Lavalink's `info` payload."""

        return cls(
            identifier=_str(payload.get("identifier")),
            is_seekable=_bool(payload.get("isSeekable")),
            author=_str(payload.get("author")),
            length=_int(payload.get("length")),
            is_stream=_bool(payload.get("isStream")),
            position=_int(payload.get("position")),
            title=_str(payload.get("title")),
            uri=_optional_str(payload.get("uri")),
            artwork_url=_optional_str(payload.get("artworkUrl")),
            isrc=_optional_str(payload.get("isrc")),
            source_name=_optional_str(payload.get("sourceName")),
            raw=payload.copy(),
        )


@dataclass(slots=True, eq=False)
class Track:
    """A Lavalink track with encoded playback data, metadata, and user/plugin data."""

    encoded: str
    info: TrackInfo
    plugin_info: JsonObject = field(default_factory=dict)
    user_data: JsonObject = field(default_factory=dict)
    playlist: PlaylistInfo | None = None
    recommended: bool = False
    raw_data: JsonObject = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.title} — {self.author} [{self.length_display}]"

    def __repr__(self) -> str:
        return (
            f"Track(title={self.title!r}, author={self.author!r}, "
            f"source={self.source!r}, identifier={self.identifier!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Track):
            return NotImplemented

        return self.encoded == other.encoded

    def __hash__(self) -> int:
        return hash(self.encoded)

    @staticmethod
    def _format_duration(ms: int) -> str:
        """Format milliseconds as M:SS or H:MM:SS."""
        total_seconds = ms // 1000
        h, remainder = divmod(total_seconds, 3600)
        m, s = divmod(remainder, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @classmethod
    def from_payload(cls, payload: JsonObject, *, playlist: PlaylistInfo | None = None) -> Track:
        """Build a track from a Lavalink track payload."""

        info_payload = _dict(payload.get("info"))
        return cls(
            encoded=_str(payload.get("encoded")),
            info=TrackInfo.from_payload(info_payload),
            plugin_info=_dict(payload.get("pluginInfo")),
            user_data=_dict(payload.get("userData")),
            playlist=playlist,
            raw_data=payload.copy(),
        )

    @property
    def title(self) -> str:
        """Track title shortcut."""

        return self.info.title

    @property
    def author(self) -> str:
        """Track author shortcut."""

        return self.info.author

    @property
    def duration(self) -> int:
        """Track length in milliseconds."""

        return self.info.length

    @property
    def length(self) -> int:
        """Wavelink-style alias for `duration`."""

        return self.duration

    @property
    def position(self) -> int:
        """Initial track position from Lavalink metadata."""

        return self.info.position

    @property
    def uri(self) -> str | None:
        """Track URI shortcut."""

        return self.info.uri

    @property
    def source(self) -> str | None:
        """Track source name shortcut."""

        return self.info.source_name

    @property
    def identifier(self) -> str:
        """Track source identifier shortcut."""

        return self.info.identifier

    @property
    def artwork_url(self) -> str | None:
        """Track artwork URL shortcut."""

        return self.info.artwork_url

    @property
    def artwork(self) -> str | None:
        """Wavelink-style alias for `artwork_url`."""

        return self.artwork_url

    @property
    def isrc(self) -> str | None:
        """Track ISRC shortcut."""

        return self.info.isrc

    @property
    def is_seekable(self) -> bool:
        """Whether this track can be seeked."""

        return self.info.is_seekable

    @property
    def length_display(self) -> str:
        """Human-readable track duration. Returns ``LIVE`` for streams."""
        if self.is_stream:
            return "LIVE"
        return self._format_duration(self.duration)

    @property
    def is_stream(self) -> bool:
        """Whether this track is a live stream."""

        return self.info.is_stream

    @property
    def album(self) -> Album:
        """Source/plugin album metadata."""

        return Album.from_payload(self.plugin_info)

    @property
    def artist(self) -> Artist:
        """Source/plugin artist metadata."""

        return Artist.from_payload(self.plugin_info)

    @property
    def preview_url(self) -> str | None:
        """Source/plugin preview URL."""

        return _optional_str(self.plugin_info.get("previewUrl"))

    @property
    def is_preview(self) -> bool | None:
        """Whether this is a source/plugin preview track."""

        value = self.plugin_info.get("isPreview")
        return value if isinstance(value, bool) else None

    @property
    def extras(self) -> ExtrasNamespace:
        """Mutable attribute-style view over Lavalink user data."""

        return ExtrasNamespace(self.user_data, on_update=self._sync_user_data)

    @extras.setter
    def extras(self, value: ExtrasNamespace | JsonObject) -> None:
        self.user_data = value.to_dict() if isinstance(value, ExtrasNamespace) else value.copy()
        self._sync_user_data(self.user_data)

    def plugin_value(self, key: str, default: JsonValue = None) -> JsonValue:
        """Return a source/plugin-specific metadata value."""

        return self.plugin_info.get(key, default)

    def with_user_data(self, **data: object) -> Track:
        """Return a track copy with merged Lavalink user data."""

        user_data = self.user_data.copy()
        user_data.update(data)
        return replace(self, user_data=user_data, raw_data=self._raw_data_with_user_data(user_data))

    def with_playlist(self, playlist: PlaylistInfo | None) -> Track:
        """Return a copy with explicit playlist-origin metadata."""

        return replace(self, playlist=playlist)

    def as_recommended(self, value: bool = True) -> Track:
        """Return a copy marked as an autoplay recommendation."""

        return replace(self, recommended=value)

    def _sync_user_data(self, data: JsonObject) -> None:
        self.raw_data["userData"] = data.copy()

    def _raw_data_with_user_data(self, data: JsonObject) -> JsonObject:
        raw_data = self.raw_data.copy()
        raw_data["userData"] = data.copy()
        return raw_data

    @classmethod
    async def search(
        cls,
        query: str,
        *,
        source: SearchSource | str | None = "ytmsearch",
        node: TrackSearchNode | None = None,
        use_cache: bool = True,
    ) -> Search:
        """Search tracks through a node or the global pool."""

        from .pool import Pool

        if node is not None:
            return await node.search(query, source=source, use_cache=use_cache)

        return await Pool.search(query, source=source, use_cache=use_cache)


@dataclass(frozen=True, slots=True)
class PlaylistInfo:
    """Metadata for a Lavalink playlist."""

    name: str
    selected_track: int = -1
    tracks: int = 0
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: JsonObject) -> PlaylistInfo:
        """Build playlist metadata from Lavalink's `info` payload."""

        return cls(
            name=_str(payload.get("name")),
            selected_track=_int(payload.get("selectedTrack"), default=-1),
            tracks=_int(payload.get("tracks") or payload.get("trackCount")),
            raw=payload.copy(),
        )


@dataclass(slots=True, eq=False)
class Playlist:
    """A playlist returned by Lavalink."""

    info: PlaylistInfo
    tracks: list[Track] = field(default_factory=list)
    plugin_info: JsonObject = field(default_factory=dict)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"Playlist(name={self.name!r}, tracks={len(self.tracks)})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Playlist):
            return NotImplemented

        return self.info == other.info and self.tracks == other.tracks

    def __len__(self) -> int:
        return len(self.tracks)

    def __iter__(self) -> Iterator[Track]:
        return iter(tuple(self.tracks))

    def __reversed__(self) -> Iterator[Track]:
        return reversed(self.tracks)

    def __contains__(self, track: object) -> bool:
        return track in self.tracks

    @overload
    def __getitem__(self, index: int) -> Track: ...

    @overload
    def __getitem__(self, index: slice) -> list[Track]: ...

    def __getitem__(self, index: int | slice) -> Track | list[Track]:
        return self.tracks[index]

    @classmethod
    def from_payload(cls, payload: JsonObject) -> Playlist:
        """Build a playlist from a Lavalink playlist load result."""

        data = _dict(payload.get("data"))
        info = PlaylistInfo.from_payload(_dict(data.get("info")))
        tracks = [
            Track.from_payload(track, playlist=info) for track in _list_of_dicts(data.get("tracks"))
        ]
        info = replace(info, tracks=len(tracks))
        return cls(
            info=info,
            tracks=[track.with_playlist(info) for track in tracks],
            plugin_info=_dict(data.get("pluginInfo")),
        )

    @property
    def name(self) -> str:
        """Playlist name shortcut."""

        return self.info.name

    @property
    def selected_track(self) -> int:
        """Selected track index, or `-1` when none is selected."""

        return self.info.selected_track

    @property
    def type(self) -> str | None:
        """Source/plugin playlist type."""

        return _optional_str(self.plugin_info.get("type"))

    @property
    def url(self) -> str | None:
        """Source/plugin playlist URL."""

        return _optional_str(self.plugin_info.get("url"))

    @property
    def artwork_url(self) -> str | None:
        """Source/plugin playlist artwork URL."""

        return _optional_str(self.plugin_info.get("artworkUrl"))

    @property
    def artwork(self) -> str | None:
        """Alias for `artwork_url`."""

        return self.artwork_url

    @property
    def author(self) -> str | None:
        """Source/plugin playlist author."""

        return _optional_str(self.plugin_info.get("author"))

    @property
    def selected(self) -> Track | None:
        """Selected playlist track, if Lavalink provided one."""

        if self.selected_track < 0:
            return None

        try:
            return self.tracks[self.selected_track]
        except IndexError:
            return None

    @property
    def metadata(self) -> JsonObject:
        """Clean playlist metadata useful for bot command responses."""

        return {
            "name": self.name,
            "selected_track": self.selected_track,
            "track_count": len(self.tracks),
            "type": self.type,
            "url": self.url,
            "artwork": self.artwork_url,
            "author": self.author,
        }

    def pop(self, index: int = -1) -> Track:
        """Remove and return a track from the playlist."""

        return self.tracks.pop(index)

    def shuffled(self) -> Playlist:
        """Return a copy with tracks shuffled."""

        tracks = self.tracks.copy()
        random.shuffle(tracks)
        return replace(self, tracks=tracks)

    def limited(self, limit: int | None) -> Playlist:
        """Return a copy limited to at most `limit` tracks."""

        if limit is None:
            return replace(self, tracks=self.tracks.copy())
        if limit < 0:
            msg = "Playlist limit cannot be negative."
            raise ValueError(msg)
        return replace(self, tracks=self.tracks[:limit])

    def playable_tracks(
        self,
        *,
        shuffle: bool = False,
        limit: int | None = None,
        selected_first: bool = True,
    ) -> list[Track]:
        """Return tracks prepared for queueing."""

        tracks = self.tracks.copy()
        if selected_first and self.selected is not None:
            selected = self.selected
            tracks = [selected, *[track for track in tracks if track != selected]]
        if shuffle:
            random.shuffle(tracks)
        if limit is not None:
            if limit < 0:
                msg = "Playlist limit cannot be negative."
                raise ValueError(msg)
            tracks = tracks[:limit]
        return tracks

    def with_user_data(self, **data: object) -> Playlist:
        """Return a playlist copy where every track includes additional user data."""

        return replace(self, tracks=[track.with_user_data(**data) for track in self.tracks])

    def track_extras(self, **attrs: object) -> None:
        """Mutate user data on every track in this playlist."""

        for track in self.tracks:
            extras = track.extras
            for key, value in attrs.items():
                extras[key] = value

    @property
    def extras(self) -> ExtrasNamespace:
        """Attribute-style view over extras shared by every track."""

        shared: JsonObject = {}
        if self.tracks:
            shared.update(self.tracks[0].user_data)
        return ExtrasNamespace(shared, on_update=self._sync_track_extras)

    @extras.setter
    def extras(self, value: ExtrasNamespace | JsonObject) -> None:
        data = value.to_dict() if isinstance(value, ExtrasNamespace) else value.copy()
        self._sync_track_extras(data)

    def _sync_track_extras(self, data: JsonObject) -> None:
        for track in self.tracks:
            track.extras = data


@dataclass(frozen=True, slots=True)
class LoadError:
    """Track loading error returned by Lavalink."""

    message: str
    severity: str | None = None
    cause: str | None = None
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: JsonObject) -> LoadError:
        """Build a loading error from Lavalink's error payload."""

        data = _dict(payload.get("data"))
        return cls(
            message=_str(data.get("message"), default="Track loading failed."),
            severity=_optional_str(data.get("severity")),
            cause=_optional_str(data.get("cause")),
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Normalized response from Lavalink's load-tracks endpoint."""

    load_type: LoadType
    tracks: list[Track] = field(default_factory=list)
    playlist: Playlist | None = None
    error: LoadError | None = None
    raw_load_type: str | None = None
    plugin_info: JsonObject = field(default_factory=dict)
    custom_data: JsonValue = None

    @classmethod
    def from_payload(cls, payload: JsonObject) -> LoadResult:
        """Build a normalized load result from a Lavalink v4 payload."""

        raw_load_type = _str(payload.get("loadType"), default=LoadType.EMPTY.value)
        load_type = _load_type(raw_load_type)

        if load_type is LoadType.TRACK:
            return cls(
                load_type=load_type,
                tracks=[Track.from_payload(_dict(payload.get("data")))],
                raw_load_type=raw_load_type,
            )

        if load_type is LoadType.SEARCH:
            tracks = [Track.from_payload(track) for track in _list_of_dicts(payload.get("data"))]
            return cls(load_type=load_type, tracks=tracks, raw_load_type=raw_load_type)

        if load_type is LoadType.PLAYLIST:
            playlist = Playlist.from_payload(payload)
            return cls(
                load_type=load_type,
                tracks=playlist.tracks.copy(),
                playlist=playlist,
                raw_load_type=raw_load_type,
                plugin_info=playlist.plugin_info.copy(),
            )

        if load_type is LoadType.ERROR:
            return cls(
                load_type=load_type,
                error=LoadError.from_payload(payload),
                raw_load_type=raw_load_type,
            )

        if load_type is LoadType.CUSTOM:
            data = _json_value(payload.get("data"))
            plugin_info = _dict(data.get("pluginInfo")) if isinstance(data, dict) else {}
            return cls(
                load_type=LoadType.CUSTOM,
                raw_load_type=raw_load_type,
                plugin_info=plugin_info,
                custom_data=data,
            )

        return cls(load_type=LoadType.EMPTY, raw_load_type=raw_load_type)


@dataclass(frozen=True, slots=True)
class GitInfo:
    """Lavalink git build metadata."""

    branch: str
    commit: str
    commit_time: int

    @classmethod
    def from_payload(cls, payload: JsonObject) -> GitInfo:
        return cls(
            branch=_str(payload.get("branch")),
            commit=_str(payload.get("commit")),
            commit_time=_int(payload.get("commitTime")),
        )


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """Lavalink semantic version metadata."""

    semver: str
    major: int
    minor: int
    patch: int
    pre_release: str | None = None
    build: str | None = None

    @classmethod
    def from_payload(cls, payload: JsonObject) -> VersionInfo:
        return cls(
            semver=_str(payload.get("semver")),
            major=_int(payload.get("major")),
            minor=_int(payload.get("minor")),
            patch=_int(payload.get("patch")),
            pre_release=_optional_str(payload.get("preRelease")),
            build=_optional_str(payload.get("build")),
        )


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """Installed Lavalink plugin metadata."""

    name: str
    version: str

    @classmethod
    def from_payload(cls, payload: JsonObject) -> PluginInfo:
        return cls(name=_str(payload.get("name")), version=_str(payload.get("version")))


@dataclass(frozen=True, slots=True)
class NodeInfo:
    """Lavalink `/v4/info` response."""

    version: VersionInfo
    build_time: int
    git: GitInfo
    jvm: str
    lavaplayer: str
    source_managers: list[str]
    filters: list[str]
    plugins: list[PluginInfo]

    @classmethod
    def from_payload(cls, payload: JsonObject) -> NodeInfo:
        return cls(
            version=VersionInfo.from_payload(_dict(payload.get("version"))),
            build_time=_int(payload.get("buildTime")),
            git=GitInfo.from_payload(_dict(payload.get("git"))),
            jvm=_str(payload.get("jvm")),
            lavaplayer=_str(payload.get("lavaplayer")),
            source_managers=_list_of_str(payload.get("sourceManagers")),
            filters=_list_of_str(payload.get("filters")),
            plugins=[
                PluginInfo.from_payload(plugin) for plugin in _list_of_dicts(payload.get("plugins"))
            ],
        )


@dataclass(frozen=True, slots=True)
class MemoryStats:
    """Lavalink memory statistics."""

    free: int
    used: int
    allocated: int
    reservable: int

    @classmethod
    def from_payload(cls, payload: JsonObject) -> MemoryStats:
        return cls(
            free=_int(payload.get("free")),
            used=_int(payload.get("used")),
            allocated=_int(payload.get("allocated")),
            reservable=_int(payload.get("reservable")),
        )


@dataclass(frozen=True, slots=True)
class CpuStats:
    """Lavalink CPU statistics."""

    cores: int
    system_load: float
    lavalink_load: float

    @classmethod
    def from_payload(cls, payload: JsonObject) -> CpuStats:
        return cls(
            cores=_int(payload.get("cores")),
            system_load=_float(payload.get("systemLoad")),
            lavalink_load=_float(payload.get("lavalinkLoad")),
        )


@dataclass(frozen=True, slots=True)
class FrameStats:
    """Lavalink frame statistics."""

    sent: int
    nulled: int
    deficit: int

    @classmethod
    def from_payload(cls, payload: JsonObject | None) -> FrameStats | None:
        if payload is None:
            return None

        return cls(
            sent=_int(payload.get("sent")),
            nulled=_int(payload.get("nulled")),
            deficit=_int(payload.get("deficit")),
        )


@dataclass(frozen=True, slots=True)
class Stats:
    """Lavalink `/v4/stats` or websocket stats payload."""

    players: int
    playing_players: int
    uptime: int
    memory: MemoryStats
    cpu: CpuStats
    frame_stats: FrameStats | None = None

    @classmethod
    def from_payload(cls, payload: JsonObject) -> Stats:
        return cls(
            players=_int(payload.get("players")),
            playing_players=_int(payload.get("playingPlayers")),
            uptime=_int(payload.get("uptime")),
            memory=MemoryStats.from_payload(_dict(payload.get("memory"))),
            cpu=CpuStats.from_payload(_dict(payload.get("cpu"))),
            frame_stats=FrameStats.from_payload(_optional_dict(payload.get("frameStats"))),
        )


@dataclass(frozen=True, slots=True)
class VoiceState:
    """Voice state sent to Lavalink for a Discord guild."""

    token: str
    endpoint: str
    session_id: str
    channel_id: str | None = None

    def to_payload(self) -> JsonObject:
        return {
            "token": self.token,
            "endpoint": self.endpoint,
            "sessionId": self.session_id,
            "channelId": self.channel_id,
        }


@dataclass(frozen=True, slots=True)
class PlayerState:
    """Lavalink player state."""

    time: int
    position: int
    connected: bool
    ping: int

    @classmethod
    def from_payload(cls, payload: JsonObject) -> PlayerState:
        return cls(
            time=_int(payload.get("time")),
            position=_int(payload.get("position")),
            connected=_bool(payload.get("connected")),
            ping=_int(payload.get("ping")),
        )


@dataclass(frozen=True, slots=True)
class LavalinkPlayer:
    """Discord-independent Lavalink player response."""

    guild_id: int
    track: Track | None
    volume: int
    paused: bool
    state: PlayerState
    voice: JsonObject
    filters: JsonObject

    @classmethod
    def from_payload(cls, payload: JsonObject) -> LavalinkPlayer:
        track_payload = _optional_dict(payload.get("track"))
        # A present-but-empty/encoded-less track object (e.g. {"encoded": null}
        # from a plugin) must read as "no track", not a bogus Track(encoded="").
        track = (
            Track.from_payload(track_payload)
            if track_payload and track_payload.get("encoded")
            else None
        )
        return cls(
            guild_id=_int(payload.get("guildId")),
            track=track,
            volume=_int(payload.get("volume")),
            paused=_bool(payload.get("paused")),
            state=PlayerState.from_payload(_dict(payload.get("state"))),
            voice=_dict(payload.get("voice")),
            filters=_dict(payload.get("filters")),
        )


def _str(value: object, *, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: object, *, default: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default

    return default


def _float(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)

    return default


def _bool(value: object, *, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _dict(value: object) -> JsonObject:
    return value.copy() if isinstance(value, dict) else {}


def _optional_dict(value: object) -> JsonObject | None:
    return value.copy() if isinstance(value, dict) else None


def _list_of_dicts(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []

    return [item.copy() for item in value if isinstance(item, dict)]


def _list_of_str(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def _load_type(value: str) -> LoadType:
    try:
        return LoadType(value)
    except ValueError:
        return LoadType.CUSTOM


def _json_value(value: object) -> JsonValue:
    if isinstance(value, dict):
        return value.copy()
    if isinstance(value, list):
        return value.copy()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return None
