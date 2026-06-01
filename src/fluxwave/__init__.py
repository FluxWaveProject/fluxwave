"""FluxWave — modern async Lavalink wrapper for Python Discord bots."""

from ._libraries import library as discord_library
from ._meta import (  # noqa: F401
    __author__,
    __license__,
    __url__,
    __version__,
    __version_info__,
)
from .autoplay import AutoPlayMode, RecommendationProvider, SearchRecommendationProvider
from .backoff import Backoff
from .cache import LFUCache
from .crossfade import Crossfade, CrossfadeConfig, CrossfadeStats, FadeCurve
from .events import (
    EventDispatcher,
    EventPayload,
    EventType,
    ExtraEvent,
    InactivePlayerEvent,
    NodeClosedEvent,
    NodeDisconnectedEvent,
    NodeReadyEvent,
    PlayerUpdateEvent,
    PluginEvent,
    RawWebSocketEvent,
    StatsUpdateEvent,
    TrackEndEvent,
    TrackExceptionEvent,
    TrackStartEvent,
    TrackStuckEvent,
    WebSocketClosedEvent,
    close_listeners,
    dispatch,
    listen,
    remove_listener,
)
from .exceptions import (
    AuthorizationError,
    ChannelTimeoutError,
    FluxWaveError,
    InvalidChannelError,
    InvalidNodeError,
    LavalinkError,
    LavalinkErrorResponse,
    LyricsError,
    MultipleDiscordLibrariesError,
    NodeConnectionError,
    NodeError,
    NoDiscordLibraryError,
    PlayerError,
    QueueEmpty,
    QueueError,
    QueueFull,
    TrackLoadError,
    UnsupportedLavalinkVersion,
)
from .filters import (
    ChannelMixFilter,
    DistortionFilter,
    EqualizerFilter,
    FilterPreset,
    Filters,
    KaraokeFilter,
    LowPassFilter,
    PluginFiltersComponent,
    RotationFilter,
    TimescaleFilter,
    TremoloFilter,
    VibratoFilter,
)
from .formatting import QueuePage, format_duration, paginate_queue, progress_bar
from .metrics import WrapperMetrics, metrics
from .node import (
    DEFAULT_REGION_GROUPS,
    Node,
    NodePool,
    NodeSelectionStrategy,
    NodeStatus,
    calculate_shard_id,
    parse_voice_region,
)
from .persistence import FileStore, MemoryStore, PersistedState, PersistenceBackend, capture
from .player import FluxPlayer, Player
from .plugins import (
    LavaSrcClient,
    LyricsClient,
    PluginClient,
    PluginHelpers,
    SponsorBlockClient,
)
from .pool import Pool
from .queue import Queue, QueueMode
from .rest import PlayerUpdate, RestClient, SessionUpdate
from .results import EnqueueResult, LyricsLine, LyricsResult
from .routeplanner import RoutePlannerStatus
from .router import SourceRoute, SourceRouter
from .search import SearchQuery, SearchSource, build_search_query
from .tracing import EventTracer, TraceCategory, TraceEvent, tracer
from .tracks import (
    Album,
    Artist,
    ExtrasNamespace,
    LavalinkPlayer,
    LoadError,
    LoadResult,
    LoadType,
    NodeInfo,
    PlayerState,
    Playlist,
    Stats,
    Track,
    TrackInfo,
    VoiceState,
)
from .versioning import (
    LavalinkVersion,
    LavalinkVersionCheck,
    LavalinkVersionWarning,
    check_lavalink_version,
    parse_lavalink_version,
)
from .watchdog import VoiceWatchdog, WatchdogConfig, WatchdogStats
from .websocket import WebSocketClient

__all__ = (
    "DEFAULT_REGION_GROUPS",
    # models
    "Album",
    "Artist",
    # exceptions
    "AuthorizationError",
    # autoplay
    "AutoPlayMode",
    "Backoff",
    # filters
    "ChannelMixFilter",
    "ChannelTimeoutError",
    # crossfade
    "Crossfade",
    "CrossfadeConfig",
    "CrossfadeStats",
    "DistortionFilter",
    # results
    "EnqueueResult",
    "EqualizerFilter",
    # events
    "EventDispatcher",
    "EventPayload",
    # tracing
    "EventTracer",
    "EventType",
    "ExtraEvent",
    "ExtrasNamespace",
    "FadeCurve",
    # persistence backends
    "FileStore",
    "FilterPreset",
    "Filters",
    # player
    "FluxPlayer",
    "FluxWaveError",
    "InactivePlayerEvent",
    "InvalidChannelError",
    "InvalidNodeError",
    "KaraokeFilter",
    # cache
    "LFUCache",
    # plugins
    "LavaSrcClient",
    "LavalinkError",
    "LavalinkErrorResponse",
    "LavalinkPlayer",
    "LavalinkVersion",
    "LavalinkVersionCheck",
    "LavalinkVersionWarning",
    "LoadError",
    "LoadResult",
    "LoadType",
    "LowPassFilter",
    "LyricsClient",
    "LyricsError",
    "LyricsLine",
    "LyricsResult",
    # persistence
    "MemoryStore",
    "MultipleDiscordLibrariesError",
    "NoDiscordLibraryError",
    # node
    "Node",
    "NodeClosedEvent",
    "NodeConnectionError",
    "NodeDisconnectedEvent",
    "NodeError",
    "NodeInfo",
    "NodePool",
    "NodeReadyEvent",
    "NodeSelectionStrategy",
    "NodeStatus",
    "PersistedState",
    "PersistenceBackend",
    "Player",
    "PlayerError",
    "PlayerState",
    # REST
    "PlayerUpdate",
    "PlayerUpdateEvent",
    "Playlist",
    "PluginClient",
    "PluginEvent",
    "PluginFiltersComponent",
    "PluginHelpers",
    # pool
    "Pool",
    # queue
    "Queue",
    "QueueEmpty",
    "QueueError",
    "QueueFull",
    "QueueMode",
    "QueuePage",
    "RawWebSocketEvent",
    "RecommendationProvider",
    "RestClient",
    "RotationFilter",
    "RoutePlannerStatus",
    # search
    "SearchQuery",
    "SearchRecommendationProvider",
    "SearchSource",
    "SessionUpdate",
    # routing
    "SourceRoute",
    "SourceRouter",
    "SponsorBlockClient",
    "Stats",
    "StatsUpdateEvent",
    "TimescaleFilter",
    "TraceCategory",
    "TraceEvent",
    "Track",
    "TrackEndEvent",
    "TrackExceptionEvent",
    "TrackInfo",
    "TrackLoadError",
    "TrackStartEvent",
    "TrackStuckEvent",
    "TremoloFilter",
    "UnsupportedLavalinkVersion",
    "VibratoFilter",
    "VoiceState",
    # watchdog (voice resilience)
    "VoiceWatchdog",
    "WatchdogConfig",
    "WatchdogStats",
    "WebSocketClient",
    "WebSocketClosedEvent",
    # metrics
    "WrapperMetrics",
    # meta
    "__version__",
    "build_search_query",
    "calculate_shard_id",
    "capture",
    "check_lavalink_version",
    "close_listeners",
    "discord_library",
    "dispatch",
    "format_duration",
    "listen",
    "metrics",
    "paginate_queue",
    "parse_lavalink_version",
    "parse_voice_region",
    "progress_bar",
    "remove_listener",
    "tracer",
)
