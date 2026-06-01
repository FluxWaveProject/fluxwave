"""Lavalink version parsing and compatibility validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SUPPORTED_LAVALINK_MAJOR = 4
MINIMUM_LAVALINK_VERSION = (4, 0, 0)
TESTED_LAVALINK_VERSION = (4, 2, 2)

_VERSION_RE = re.compile(
    r"^\s*(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?"
    r"(?:[-+](?P<label>[0-9A-Za-z][0-9A-Za-z.-]*))?\s*$"
)


class LavalinkVersionWarning(RuntimeWarning):
    """Warning emitted when Lavalink is newer than FluxWave's tested target."""


@dataclass(frozen=True, slots=True, order=True)
class LavalinkVersion:
    """Parsed Lavalink semantic version."""

    major: int
    minor: int = 0
    patch: int = 0
    label: str | None = field(default=None, compare=False)
    raw: str = field(default="", compare=False)

    @property
    def base(self) -> tuple[int, int, int]:
        """Return comparable major/minor/patch values."""

        return (self.major, self.minor, self.patch)

    @property
    def is_snapshot(self) -> bool:
        """Whether this version string describes a snapshot build."""

        return bool(self.label and "snapshot" in self.label.lower())

    @property
    def is_prerelease(self) -> bool:
        """Whether this version has a non-build label."""

        return self.label is not None and not self.label.startswith("build.")

    def __str__(self) -> str:
        return self.raw or ".".join(str(part) for part in self.base)


@dataclass(frozen=True, slots=True)
class LavalinkVersionCheck:
    """Result of a Lavalink compatibility check."""

    version: LavalinkVersion
    supported: bool
    warning: str | None = None


def parse_lavalink_version(version: str) -> LavalinkVersion:
    """Parse Lavalink `/version` text into a comparable object."""

    cleaned = version.strip()
    if cleaned.upper() == "SNAPSHOT":
        return LavalinkVersion(4, 0, 0, label="SNAPSHOT", raw=version)

    match = _VERSION_RE.match(cleaned)
    if match is None:
        msg = f"Could not parse Lavalink version {version!r}."
        raise ValueError(msg)

    return LavalinkVersion(
        major=int(match.group("major")),
        minor=int(match.group("minor") or 0),
        patch=int(match.group("patch") or 0),
        label=match.group("label"),
        raw=version,
    )


def check_lavalink_version(
    version: LavalinkVersion,
    *,
    minimum: tuple[int, int, int] = MINIMUM_LAVALINK_VERSION,
    tested: tuple[int, int, int] = TESTED_LAVALINK_VERSION,
    supported_major: int = SUPPORTED_LAVALINK_MAJOR,
) -> LavalinkVersionCheck:
    """Validate a parsed Lavalink version against FluxWave's support policy."""

    if version.major != supported_major:
        return LavalinkVersionCheck(
            version=version,
            supported=False,
            warning=(
                f"FluxWave targets Lavalink v{supported_major}.x, but the node reports {version}."
            ),
        )

    if version.base < minimum:
        return LavalinkVersionCheck(
            version=version,
            supported=False,
            warning=(
                "FluxWave requires Lavalink "
                f"{_format_version(minimum)} or newer; the node reports {version}."
            ),
        )

    if version.base > tested:
        return LavalinkVersionCheck(
            version=version,
            supported=True,
            warning=(
                "This Lavalink version is newer than FluxWave's tested target "
                f"{_format_version(tested)}. It may work, but verify playback and plugins."
            ),
        )

    if version.is_prerelease:
        return LavalinkVersionCheck(
            version=version,
            supported=True,
            warning=(
                f"Lavalink {version} appears to be a pre-release/snapshot build. "
                "Verify behavior before production use."
            ),
        )

    return LavalinkVersionCheck(version=version, supported=True)


def _format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)
