"""Protocol typing namespace for Lavalink payload definitions."""

from typing import Any, TypeAlias

JsonObject: TypeAlias = dict[str, Any]
JsonValue: TypeAlias = str | int | float | bool | None | JsonObject | list[Any]
JsonPayload: TypeAlias = JsonObject | list[Any]
