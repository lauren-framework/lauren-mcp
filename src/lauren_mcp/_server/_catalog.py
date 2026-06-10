"""Mutable catalogue of tools / resources / prompts with change notifications."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from lauren import Scope, injectable

_logger = logging.getLogger(__name__)

#: Async callable invoked with the notification method name on each mutation.
BroadcastFn = Callable[[str], Awaitable[None]]


@injectable(scope=Scope.SINGLETON)
class McpCatalogManager:
    """SINGLETON holding the live tool / resource / prompt catalogue.

    The catalogue is seeded from decorator metadata at startup and can be
    mutated at runtime.  Every mutation after :meth:`set_broadcast_fn` fires
    the matching ``notifications/*/list_changed`` broadcast.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}
        self._resources: dict[str, Any] = {}
        self._prompts: dict[str, Any] = {}
        self._broadcast_fn: BroadcastFn | None = None

    def set_broadcast_fn(self, fn: BroadcastFn | None) -> None:
        """Attach the broadcast hook; mutations before this stay silent."""
        self._broadcast_fn = fn

    def _notify(self, method: str) -> None:
        broadcast_fn = self._broadcast_fn
        if broadcast_fn is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _logger.debug("MCP catalog: no running loop; skipping %s", method)
            return

        async def _run() -> None:
            try:
                await broadcast_fn(method)
            except Exception:
                _logger.warning("MCP catalog: broadcast %s failed", method, exc_info=True)

        loop.create_task(_run())

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def register_tool(self, meta: Any, *, on_conflict: str = "replace") -> None:
        if on_conflict == "error" and meta.name in self._tools:
            from lauren_mcp.server._composition import McpToolNameCollision

            raise McpToolNameCollision(
                f"Tool {meta.name!r} is already registered; use a different "
                "mount prefix to avoid the collision."
            )
        self._tools[meta.name] = meta
        self._notify("notifications/tools/list_changed")

    def unregister_tool(self, name: str) -> bool:
        removed = self._tools.pop(name, None) is not None
        if removed:
            self._notify("notifications/tools/list_changed")
        return removed

    def list_tools(self) -> list[Any]:
        return list(self._tools.values())

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    def register_resource(self, meta: Any) -> None:
        self._resources[meta.name] = meta
        self._notify("notifications/resources/list_changed")

    def unregister_resource(self, name: str) -> bool:
        removed = self._resources.pop(name, None) is not None
        if removed:
            self._notify("notifications/resources/list_changed")
        return removed

    def list_resources(self) -> list[Any]:
        return list(self._resources.values())

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    def register_prompt(self, meta: Any) -> None:
        self._prompts[meta.name] = meta
        self._notify("notifications/prompts/list_changed")

    def unregister_prompt(self, name: str) -> bool:
        removed = self._prompts.pop(name, None) is not None
        if removed:
            self._notify("notifications/prompts/list_changed")
        return removed

    def list_prompts(self) -> list[Any]:
        return list(self._prompts.values())
