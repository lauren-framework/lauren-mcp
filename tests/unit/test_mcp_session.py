"""Unit tests for lauren_mcp._server._session.SseSessionStore."""
from __future__ import annotations

import asyncio
import pytest

from lauren_mcp._server._session import SseSessionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_store() -> SseSessionStore:
    """Instantiate SseSessionStore bypassing Lauren DI."""
    return SseSessionStore()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSseSessionStore:
    def test_store_starts_empty(self):
        """A freshly created store has no sessions."""
        store = make_store()
        assert store._sessions == {}

    def test_create_returns_asyncio_queue(self):
        store = make_store()
        q = store.create("session-a")
        assert isinstance(q, asyncio.Queue)

    def test_get_returns_same_queue_after_create(self):
        store = make_store()
        q_created = store.create("session-b")
        q_fetched = store.get("session-b")
        assert q_created is q_fetched

    def test_get_returns_none_for_unknown_session_id(self):
        store = make_store()
        assert store.get("does-not-exist") is None

    def test_remove_makes_get_return_none(self):
        store = make_store()
        store.create("session-c")
        store.remove("session-c")
        assert store.get("session-c") is None

    def test_remove_is_noop_for_unknown_id(self):
        """remove() on a non-existent id must not raise."""
        store = make_store()
        store.remove("ghost-session")  # should not raise

    def test_creating_two_sessions_gives_independent_queues(self):
        store = make_store()
        q1 = store.create("s1")
        q2 = store.create("s2")
        assert q1 is not q2

    def test_removing_one_session_does_not_remove_another(self):
        store = make_store()
        store.create("keep")
        store.create("remove-me")
        store.remove("remove-me")
        assert store.get("keep") is not None
        assert store.get("remove-me") is None

    def test_session_id_is_case_sensitive(self):
        """'ABC' and 'abc' are different session IDs."""
        store = make_store()
        store.create("ABC")
        assert store.get("ABC") is not None
        assert store.get("abc") is None

    async def test_queue_can_put_and_get_items(self):
        store = make_store()
        q = store.create("async-s")
        await q.put("hello")
        item = await q.get()
        assert item == "hello"

    async def test_queue_sentinel_none_can_be_put_and_received(self):
        """None is a valid sentinel value that the SSE generator relies on."""
        store = make_store()
        q = store.create("sentinel-s")
        await q.put(None)
        item = await q.get()
        assert item is None

    async def test_create_overwrites_existing_session_queue(self):
        """Re-creating a session_id replaces the queue."""
        store = make_store()
        q_old = store.create("dup")
        q_new = store.create("dup")
        assert q_new is not q_old
        # The store now returns the new queue
        assert store.get("dup") is q_new
