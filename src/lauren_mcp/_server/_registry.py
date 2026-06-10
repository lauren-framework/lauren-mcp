"""Connection registry — fan-out channel for server-push notifications."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from lauren import Scope, injectable

_logger = logging.getLogger(__name__)

#: Sends one serialised JSON-RPC payload to a single connected client.
SendFn = Callable[[str], Awaitable[None]]


@injectable(scope=Scope.SINGLETON)
class McpConnectionRegistry:
    """SINGLETON registry of live client connections across all transports.

    Each transport registers a send function when a connection opens and
    unregisters it on close.  :meth:`broadcast` fans a notification out to
    every live connection; per-connection failures are logged and skipped so
    one dead socket cannot block the others.
    """

    def __init__(self) -> None:
        self._connections: dict[str, SendFn] = {}
        self._next_key = 0

    def register(self, send_fn: SendFn) -> str:
        """Register *send_fn*; returns an opaque key for unregistration."""
        key = f"conn-{self._next_key}"
        self._next_key += 1
        self._connections[key] = send_fn
        return key

    def unregister(self, key: str) -> None:
        """Remove a connection; idempotent."""
        self._connections.pop(key, None)

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send *payload* (a JSON-RPC notification dict) to every connection."""
        import json

        raw = json.dumps(payload)
        sends = list(self._connections.values())
        if not sends:
            return
        results = await asyncio.gather(*(send(raw) for send in sends), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                _logger.warning("MCP broadcast: send failed — %s", result)

    async def broadcast_method(self, method: str) -> None:
        """Broadcast a parameter-less notification with *method*."""
        await self.broadcast({"jsonrpc": "2.0", "method": method})
