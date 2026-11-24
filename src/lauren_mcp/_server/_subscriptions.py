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

    Session keys are opaque ``TransportBinding.subscription_key`` values:
    connection-registry keys for WebSocket and protocol session IDs for HTTP.
    """

    def __init__(self) -> None:
        # uri -> {session_key -> send_fn}
        self._subscriptions: dict[str, dict[str, SendFn]] = {}
        # URI-scoped locks preserve notification order for concurrent updates.
        # The integer tracks callers waiting on or holding each lock.
        self._notification_locks: dict[str, tuple[asyncio.Lock, int]] = {}

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
        """Notify each active subscriber once, preserving same-URI call order.

        Delivery is best-effort: failed sends are logged and are not retried.
        Concurrent updates for the same URI are serialized; updates for
        different URIs may be delivered concurrently.
        """
        if not self._subscriptions.get(uri):
            return

        lock, users = self._notification_locks.get(uri, (asyncio.Lock(), 0))
        self._notification_locks[uri] = (lock, users + 1)
        try:
            async with lock:
                # Take the snapshot after acquiring the lock so a completed
                # unsubscribe is respected by updates waiting behind this one.
                subscribers = list(self._subscriptions.get(uri, {}).values())
                if not subscribers:
                    return

                payload = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/resources/updated",
                        "params": {"uri": uri},
                    }
                )
                results = await asyncio.gather(
                    *(fn(payload) for fn in subscribers),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, Exception):
                        _logger.warning("ResourceSubscription: send failed — %s", result)
        finally:
            current_lock, current_users = self._notification_locks[uri]
            if current_users == 1 and uri not in self._subscriptions:
                del self._notification_locks[uri]
            else:
                self._notification_locks[uri] = (current_lock, current_users - 1)

    @property
    def subscription_count(self) -> int:
        """Total number of active subscriptions across all URIs."""
        return sum(len(v) for v in self._subscriptions.values())
