"""SSE event store for Streamable HTTP resumability.

Defines the :class:`EventStore` ABC and the built-in
:class:`InMemoryEventStore` implementation.  When an event store is
configured on ``mcp_streamable_http_controller``, each SSE event emitted
on the GET push channel receives a sequential ``id:`` field so that a
reconnecting client can send ``Last-Event-ID`` to replay missed events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable


class EventStore(ABC):
    """Abstract store for SSE event persistence and replay.

    Implementations must be thread-safe if the event loop runs in a
    thread pool; for asyncio single-loop deployments this is not required.
    """

    @abstractmethod
    async def store_event(self, session_id: str, event_id: str, data: str) -> None:
        """Persist a single SSE event for *session_id*.

        Parameters
        ----------
        session_id:
            The Streamable HTTP session identifier.
        event_id:
            The assigned ``id:`` field value, e.g. ``"sess123:7"``.
        data:
            The raw ``data:`` payload (JSON string).
        """

    @abstractmethod
    async def replay_events_after(
        self,
        session_id: str,
        last_event_id: str | None,
        send: Callable[[str, str], Awaitable[None]],
    ) -> None:
        """Replay all stored events after *last_event_id* for *session_id*.

        Calls ``send(event_id, data)`` for each replayed event in order.

        Parameters
        ----------
        session_id:
            The session whose events should be replayed.
        last_event_id:
            The last event ID the client received, or ``None`` to replay
            all stored events from the beginning.
        send:
            Async callback invoked once per replayed event.
        """


class InMemoryEventStore(EventStore):
    """In-memory event store for single-process deployments.

    Events are stored in a per-session bounded deque.  Older events are
    dropped when the deque reaches *max_events* to prevent unbounded
    memory growth.

    Parameters
    ----------
    max_events:
        Maximum number of events retained per session.  Defaults to 1000.
    """

    def __init__(self, *, max_events: int = 1000) -> None:
        self._max_events = max_events
        # session_id -> deque of (event_id, data) tuples
        self._store: dict[str, deque[tuple[str, str]]] = {}

    async def store_event(self, session_id: str, event_id: str, data: str) -> None:
        if session_id not in self._store:
            self._store[session_id] = deque(maxlen=self._max_events)
        self._store[session_id].append((event_id, data))

    async def replay_events_after(
        self,
        session_id: str,
        last_event_id: str | None,
        send: Callable[[str, str], Awaitable[None]],
    ) -> None:
        events = list(self._store.get(session_id, []))
        if not events:
            return
        if last_event_id is None:
            # Replay everything
            for eid, data in events:
                await send(eid, data)
            return
        # Find the index after the last known event.
        # event_id format: "{session_id}:{sequence_number}"
        try:
            last_seq = int(last_event_id.split(":", 1)[1])
        except (IndexError, ValueError):
            # Unrecognized format — replay all events as a safe fallback.
            for eid, data in events:
                await send(eid, data)
            return
        for eid, data in events:
            try:
                seq = int(eid.split(":", 1)[1])
            except (IndexError, ValueError):
                continue
            if seq > last_seq:
                await send(eid, data)

    def evict_session(self, session_id: str) -> None:
        """Remove all events for *session_id* (call when the session ends)."""
        self._store.pop(session_id, None)
