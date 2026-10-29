"""Protocol typing namespace for Lavalink payload definitions."""

from typing import Any, TypeAlias

JsonObject: TypeAlias = dict[str, Any]
JsonValue: TypeAlias = str | int | float | bool | JsonObject | list[Any] | None
JsonPayload: TypeAlias = JsonObject | list[Any]
