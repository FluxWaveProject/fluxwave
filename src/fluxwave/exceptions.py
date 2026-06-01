"""FluxWave exception hierarchy."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


class FluxWaveError(Exception):
    """Base exception for all FluxWave errors."""


class NoDiscordLibraryError(FluxWaveError):
    """Raised when no supported Discord library is installed."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or (
                "No supported Discord library found. Install one of discord.py, py-cord, "
                "nextcord, or disnake (for example `pip install fluxwave[discordpy]`)."
            )
        )


class MultipleDiscordLibrariesError(FluxWaveError):
    """Raised when more than one supported Discord library is installed."""

    def __init__(self, found: Sequence[str]) -> None:
        self.found = tuple(found)
        super().__init__(
            "Multiple supported Discord libraries found: "
            f"{', '.join(self.found)}. Set the FLUXWAVE_DISCORD_LIBRARY environment variable "
            "to choose one (discord, nextcord, or disnake)."
        )


class NodeError(FluxWaveError):
    """Raised when a Lavalink node operation fails before Lavalink returns a structured error."""


class NodeConnectionError(NodeError):
    """Raised when FluxWave cannot connect or reconnect to a Lavalink node."""


class AuthorizationError(NodeConnectionError):
    """Raised when Lavalink rejects FluxWave credentials."""


class UnsupportedLavalinkVersion(NodeConnectionError):
    """Raised when a Lavalink node reports an unsupported version."""


class InvalidNodeError(NodeError):
    """Raised when a node cannot be used for the requested operation."""


class LavalinkError(FluxWaveError):
    """Raised when Lavalink returns a structured error response."""

    def __init__(self, response: LavalinkErrorResponse) -> None:
        self.response = response
        super().__init__(str(response))


class PlayerError(FluxWaveError):
    """Raised when a player operation cannot be completed."""


class ChannelTimeoutError(PlayerError):
    """Raised when Discord voice connection or movement times out."""


class InvalidChannelError(PlayerError):
    """Raised when a Discord voice channel is invalid for playback."""


class TrackLoadError(FluxWaveError):
    """Raised when Lavalink returns a track loading error."""

    def __init__(
        self,
        message: str,
        *,
        severity: str | None = None,
        cause: str | None = None,
    ) -> None:
        self.severity = severity
        self.cause = cause
        super().__init__(message)


class LyricsError(FluxWaveError):
    """Raised when lyrics are unavailable or cannot be streamed for a track."""


class QueueError(FluxWaveError):
    """Base exception for FluxWave queue errors."""


class QueueEmpty(QueueError):
    """Raised when reading from an empty queue without waiting."""


class QueueFull(QueueError):
    """Raised when a bounded queue cannot accept more tracks."""


@dataclass(frozen=True, slots=True)
class LavalinkErrorResponse:
    """Structured Lavalink error response."""

    timestamp: int | None
    status: int
    error: str
    message: str
    path: str | None = None
    trace: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_status: int,
    ) -> LavalinkErrorResponse:
        """Create an error response from Lavalink's JSON error body."""

        return cls(
            timestamp=_optional_int(payload.get("timestamp")),
            status=_optional_int(payload.get("status")) or fallback_status,
            error=str(payload.get("error") or "Lavalink Error"),
            message=str(
                payload.get("message") or payload.get("error") or "Lavalink request failed."
            ),
            path=_optional_str(payload.get("path")),
            trace=_optional_str(payload.get("trace")),
            raw=payload.copy(),
        )

    def __str__(self) -> str:
        return f"{self.status} {self.error}: {self.message}"


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
