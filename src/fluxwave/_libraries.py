"""Discord-library compatibility layer.

FluxWave works with any discord.py-compatible library: discord.py, py-cord,
nextcord, and disnake.  This module detects which one is installed at import
time and re-exports the small set of names FluxWave needs, so the rest of the
package never imports a specific library directly.

discord.py and py-cord both provide the top-level ``discord`` module and share
the same public API, so they are detected as a single ``discord`` backend.

The re-exported names are resolved dynamically, so type checkers see them as
``Any`` here. ``player.py`` imports the concrete discord.py types under
``TYPE_CHECKING`` for accurate static analysis while binding these at runtime.

Environment variables
---------------------
``FLUXWAVE_DISCORD_LIBRARY``
    Force a backend (``discord``, ``nextcord``, or ``disnake``) when more than
    one is installed, or to override auto-detection.
``FLUXWAVE_IGNORE_LIBRARY_CHECK``
    Skip the "no/multiple libraries" guard and fall back to the first match
    (or ``discord``).  Mainly useful for documentation builds.
"""

from __future__ import annotations

import importlib
import importlib.util
from os import getenv
from typing import TYPE_CHECKING, Any

from .exceptions import MultipleDiscordLibrariesError, NoDiscordLibraryError

if TYPE_CHECKING:
    from types import ModuleType

__all__ = (
    "Client",
    "Connectable",
    "Guild",
    "Snowflake",
    "VoiceProtocol",
    "library",
    "version_info",
)

SUPPORTED_LIBRARIES = ("discord", "nextcord", "disnake")

_ALIASES = {
    "discord.py": "discord",
    "discordpy": "discord",
    "py-cord": "discord",
    "pycord": "discord",
}


def _detect_library() -> str:
    forced = getenv("FLUXWAVE_DISCORD_LIBRARY")
    if forced:
        choice = forced.strip().lower()
        choice = _ALIASES.get(choice, choice)
        if choice not in SUPPORTED_LIBRARIES:
            msg = (
                f"FLUXWAVE_DISCORD_LIBRARY={forced!r} is not supported; choose one of "
                f"{', '.join(SUPPORTED_LIBRARIES)}."
            )
            raise NoDiscordLibraryError(msg)
        if importlib.util.find_spec(choice) is None:
            msg = f"FLUXWAVE_DISCORD_LIBRARY={forced!r} is set but {choice!r} is not installed."
            raise NoDiscordLibraryError(msg)
        return choice

    found = [name for name in SUPPORTED_LIBRARIES if importlib.util.find_spec(name) is not None]

    if getenv("FLUXWAVE_IGNORE_LIBRARY_CHECK"):
        return found[0] if found else "discord"
    if not found:
        raise NoDiscordLibraryError
    if len(found) > 1:
        raise MultipleDiscordLibrariesError(found)
    return found[0]


library: str = _detect_library()

_module: ModuleType = importlib.import_module(library)
_abc: ModuleType = importlib.import_module(f"{library}.abc")

Client: Any = _module.Client
Guild: Any = _module.Guild
VoiceProtocol: Any = _module.VoiceProtocol
version_info: Any = _module.version_info

Connectable: Any = _abc.Connectable
Snowflake: Any = _abc.Snowflake

if getattr(version_info, "major", 0) < 2:
    _found_major = getattr(version_info, "major", "?")
    _msg = f"FluxWave requires {library} v2.0 or newer, but found {_found_major}.x."
    raise NoDiscordLibraryError(_msg)
