"""Unit tests for EventStore and InMemoryEventStore."""

from __future__ import annotations

from lauren_mcp._server._event_store import InMemoryEventStore
from lauren_mcp._server._streamable import StreamableSession

# ---------------------------------------------------------------------------
# InMemoryEventStore — basic round-trip
# ---------------------------------------------------------------------------


async def test_in_memory_event_store_basic_replay():
    store = InMemoryEventStore()
    await store.store_event("s1", "s1:0", '{"a":1}')
    await store.store_event("s1", "s1:1", '{"a":2}')
    await store.store_event("s1", "s1:2", '{"a":3}')

    replayed: list[tuple[str, str]] = []

    async def _collect(eid: str, d: str) -> None:
        replayed.append((eid, d))

    await store.replay_events_after("s1", "s1:0", _collect)
    assert [e for e, _ in replayed] == ["s1:1", "s1:2"]


async def test_replay_from_start():
    store = InMemoryEventStore()
    await store.store_event("s1", "s1:0", "x")
    await store.store_event("s1", "s1:1", "y")

    replayed: list[str] = []

    async def _collect(eid: str, d: str) -> None:
        replayed.append(eid)

    await store.replay_events_after("s1", None, _collect)
    assert replayed == ["s1:0", "s1:1"]


async def test_replay_last_event_id_replays_events_after():
    store = InMemoryEventStore()
    for i in range(5):
        await store.store_event("sess", f"sess:{i}", f"data-{i}")

    replayed: list[str] = []

    async def _collect(eid: str, d: str) -> None:
        replayed.append(eid)

    await store.replay_events_after("sess", "sess:2", _collect)
    assert replayed == ["sess:3", "sess:4"]


async def test_replay_empty_session_returns_nothing():
    store = InMemoryEventStore()
    replayed: list[str] = []

    async def _collect(eid: str, d: str) -> None:
        replayed.append(eid)

    await store.replay_events_after("nonexistent", None, _collect)
    assert replayed == []


# ---------------------------------------------------------------------------
# max_events cap
# ---------------------------------------------------------------------------


async def test_max_events_cap():
    store = InMemoryEventStore(max_events=2)
    for i in range(5):
        await store.store_event("s1", f"s1:{i}", f"data-{i}")

    replayed: list[str] = []

    async def _collect(eid: str, d: str) -> None:
        replayed.append(eid)

    await store.replay_events_after("s1", None, _collect)
    assert len(replayed) == 2
    assert replayed == ["s1:3", "s1:4"]


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


async def test_session_isolation():
    store = InMemoryEventStore()
    await store.store_event("s1", "s1:0", "session-1-event")
    await store.store_event("s2", "s2:0", "session-2-event")

    s1_events: list[str] = []
    s2_events: list[str] = []

    async def _collect_s1(eid: str, d: str) -> None:
        s1_events.append(d)

    async def _collect_s2(eid: str, d: str) -> None:
        s2_events.append(d)

    await store.replay_events_after("s1", None, _collect_s1)
    await store.replay_events_after("s2", None, _collect_s2)

    assert s1_events == ["session-1-event"]
    assert s2_events == ["session-2-event"]


# ---------------------------------------------------------------------------
# evict_session
# ---------------------------------------------------------------------------


async def test_evict_session():
    store = InMemoryEventStore()
    await store.store_event("s1", "s1:0", "x")
    store.evict_session("s1")

    replayed: list[str] = []

    async def _collect(eid: str, d: str) -> None:
        replayed.append(eid)

    await store.replay_events_after("s1", None, _collect)
    assert replayed == []


def test_evict_nonexistent_session_is_noop():
    store = InMemoryEventStore()
    # Should not raise
    store.evict_session("nonexistent")


# ---------------------------------------------------------------------------
# Unrecognized event_id format falls back to replay all
# ---------------------------------------------------------------------------


async def test_unrecognized_last_event_id_replays_all():
    store = InMemoryEventStore()
    await store.store_event("s1", "s1:0", "first")
    await store.store_event("s1", "s1:1", "second")

    replayed: list[str] = []

    async def _collect(eid: str, d: str) -> None:
        replayed.append(eid)

    # Unrecognized format: no ":" separator
    await store.replay_events_after("s1", "nocolon", _collect)
    assert replayed == ["s1:0", "s1:1"]


# ---------------------------------------------------------------------------
# StreamableSession next_event_id counter
# ---------------------------------------------------------------------------


def test_streamable_session_event_id_counter():
    session = StreamableSession(session_id="abc", protocol_version="2025-03-26")
    assert session.next_event_id == 0

    eid_0 = f"{session.session_id}:{session.next_event_id}"
    session.next_event_id += 1
    eid_1 = f"{session.session_id}:{session.next_event_id}"

    assert eid_0 == "abc:0"
    assert eid_1 == "abc:1"


def test_streamable_session_next_event_id_default_zero():
    session = StreamableSession(session_id="test", protocol_version="2025-11-25")
    assert session.next_event_id == 0
