"""Source-aware node routing: send specific sources/prefixes to preferred nodes."""

from __future__ import annotations

import contextlib
import fnmatch
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import Node


@dataclass(slots=True)
class SourceRoute:
    """One routing rule: queries matching *pattern* prefer *node_identifier*."""

    pattern: str
    """Glob pattern matched against the full query string (case-insensitive).

    Examples:
        - ``"ytsearch:*"``   → YouTube prefix
        - ``"spsearch:*"``   → Spotify prefix
        - ``"*.local"``      → local file extension
        - ``"youtube"``      → exact source name match inside node info
    """

    node_identifier: str
    """Identifier of the preferred :class:`~fluxwave.Node`."""

    fallback: bool = True
    """If ``True`` and the preferred node is unavailable, fall through to default
    selection. If ``False``, raise :exc:`~fluxwave.InvalidNodeError`."""

    priority: int = 0
    """Higher priority routes are checked first (default 0)."""


class SourceRouter:
    """Routes search queries and track identifiers to preferred nodes.

    Register rules with :meth:`add`, then install the router on
    :class:`~fluxwave.Pool` for global searches::

        router = SourceRouter()
        router.add("ytsearch:*", node_identifier="yt-node")
        router.add("spsearch:*", node_identifier="sp-node", fallback=True)
        fluxwave.Pool.set_router(router)

        result = await fluxwave.Pool.search("lo-fi chill", source="ytsearch")

    :meth:`resolve` remains public for advanced routing flows.
    """

    __slots__ = ("_routes",)

    def __init__(self) -> None:
        self._routes: list[SourceRoute] = []

    def add(
        self,
        pattern: str,
        node_identifier: str,
        *,
        fallback: bool = True,
        priority: int = 0,
    ) -> SourceRoute:
        """Register a routing rule and return it."""
        route = SourceRoute(
            pattern=pattern.lower(),
            node_identifier=node_identifier,
            fallback=fallback,
            priority=priority,
        )
        self._routes.append(route)
        self._routes.sort(key=lambda r: r.priority, reverse=True)
        return route

    def remove(self, pattern: str) -> None:
        """Remove all rules whose pattern equals *pattern* (case-insensitive)."""
        needle = pattern.lower()
        self._routes = [r for r in self._routes if r.pattern != needle]

    def remove_route(self, route: SourceRoute) -> None:
        """Remove a specific :class:`SourceRoute` instance."""
        with contextlib.suppress(ValueError):
            self._routes.remove(route)

    def clear(self) -> None:
        """Remove all routing rules."""
        self._routes.clear()

    @property
    def routes(self) -> list[SourceRoute]:
        """Current routing rules in priority order (highest first)."""
        return list(self._routes)

    def resolve(self, query: str, nodes: dict[str, Node]) -> Node | None:
        """Return the preferred node for *query*, or ``None`` to use default selection.

        Iterates rules in priority order. The first matching rule whose node is
        connected is returned. If the matching node is unavailable and
        ``route.fallback`` is ``True``, iteration continues; otherwise ``None``
        is returned immediately.
        """
        from .node import NodeStatus

        query_lower = query.lower()
        for route in self._routes:
            if not fnmatch.fnmatch(query_lower, route.pattern):
                continue
            node = nodes.get(route.node_identifier)
            if node is not None and node.status is NodeStatus.CONNECTED:
                return node
            if not route.fallback:
                return None

        return None

    def __len__(self) -> int:
        return len(self._routes)

    def __bool__(self) -> bool:
        return bool(self._routes)

    def __repr__(self) -> str:
        return f"SourceRouter(rules={len(self._routes)})"
