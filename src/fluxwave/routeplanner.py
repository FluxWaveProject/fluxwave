"""Typed Lavalink route planner models."""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import JsonObject


@dataclass(frozen=True, slots=True)
class RoutePlannerStatus:
    """Status returned by Lavalink's route planner admin endpoint."""

    class_name: str | None = None
    details: JsonObject = field(default_factory=dict)
    raw: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: JsonObject) -> RoutePlannerStatus:
        """Build route planner status from Lavalink's JSON payload."""

        class_name = payload.get("class")
        details = payload.get("details")
        return cls(
            class_name=class_name if isinstance(class_name, str) else None,
            details=details.copy() if isinstance(details, dict) else {},
            raw=payload.copy(),
        )

    @property
    def has_route_planner(self) -> bool:
        """Whether Lavalink reports an active route planner."""

        return self.class_name is not None
