"""SSE session store — maps session_id to asyncio.Queue[str]."""

from __future__ import annotations

import asyncio

from lauren import Scope, injectable


@injectable(scope=Scope.SINGLETON)
class SseSessionStore:
    """SINGLETON store that maps ``session_id`` → ``asyncio.Queue[str]``.

    Each SSE client connection is identified by an opaque ``session_id``
    token generated at stream-open time.  The corresponding queue is the
    channel through which the HTTP RPC endpoint delivers serialised
    JSON-RPC response payloads back to the long-running SSE response.

    A sentinel value of ``None`` pushed onto the queue signals the SSE
    generator to close the stream gracefully.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, asyncio.Queue[str | None]] = {}

    def create(self, session_id: str) -> asyncio.Queue[str | None]:
        """Create and register a fresh queue for *session_id*.

        If a queue already exists for that id (e.g. from a stale
        connection) it is replaced and the old queue is left for its
        consumer to drain naturally.

        Returns the new queue so the caller can pass it directly to the
        SSE generator without a second lookup.
        """
        q: asyncio.Queue[str | None] = asyncio.Queue()
        self._sessions[session_id] = q
        return q

    def get(self, session_id: str) -> asyncio.Queue[str | None] | None:
        """Return the queue for *session_id*, or ``None`` if not found."""
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        """Remove *session_id* from the store.

        Safe to call even if the session does not exist; the operation is
        idempotent so ``finally`` blocks in SSE generators can call it
        unconditionally.
        """
        self._sessions.pop(session_id, None)
