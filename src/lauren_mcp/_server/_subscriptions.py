"""Per-URI subscription manager for resources/subscribe notifications."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from lauren import Scope, injectable

_logger = logging.getLogger(__name__)

#: Sends one serialised JSON-RPC payload to a single connected client.
SendFn = Callable[[str], Awaitable[None]]


@injectable(scope=Scope.SINGLETON)
class ResourceSubscriptionManager:
    """SINGLETON that tracks per-URI subscriptions and broadcasts update events.

    Session keys come from :class:`~lauren_mcp._server._registry.McpConnectionRegistry`
    (WS transport) or the ``session_id`` allocated by
    :class:`~lauren_mcp._server._session.SseSessionStore` /
    :class:`~lauren_mcp._server._streamable.StreamableSessionStore`.
    """

    def __init__(self) -> None:
        # uri -> {session_key -> send_fn}
        self._subscriptions: dict[str, dict[str, SendFn]] = {}

    def subscribe(self, uri: str, session_key: str, send_fn: SendFn) -> None:
        """Register *send_fn* as the delivery channel for *session_key* on *uri*."""
        self._subscriptions.setdefault(uri, {})[session_key] = send_fn

    def unsubscribe(self, uri: str, session_key: str) -> None:
        """Remove one subscription.  No-op if not present."""
        uri_subs = self._subscriptions.get(uri)
        if uri_subs is not None:
            uri_subs.pop(session_key, None)
            if not uri_subs:
                del self._subscriptions[uri]

    def unsubscribe_all(self, session_key: str) -> None:
        """Remove all subscriptions for *session_key* (called on disconnect)."""
        empty: list[str] = []
        for uri, subs in self._subscriptions.items():
            subs.pop(session_key, None)
            if not subs:
                empty.append(uri)
        for uri in empty:
            del self._subscriptions[uri]

    def get_subscribers(self, uri: str) -> dict[str, SendFn]:
        """Return a snapshot of subscribers for *uri*."""
        return dict(self._subscriptions.get(uri, {}))

    async def notify_updated(self, uri: str) -> None:
        """Broadcast ``notifications/resources/updated`` to all subscribers of *uri*."""
        subs = self._subscriptions.get(uri)
        if not subs:
            return
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "notifications/resources/updated",
                "params": {"uri": uri},
            }
        )
        results = await asyncio.gather(
            *(fn(payload) for fn in list(subs.values())),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                _logger.warning("ResourceSubscription: send failed — %s", result)

    @property
    def subscription_count(self) -> int:
        """Total number of active subscriptions across all URIs."""
        return sum(len(v) for v in self._subscriptions.values())
