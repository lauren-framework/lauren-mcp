"""Unit tests for ResourceSubscriptionManager."""

from __future__ import annotations

import json

import pytest

from lauren_mcp._server._subscriptions import ResourceSubscriptionManager


@pytest.fixture
def manager() -> ResourceSubscriptionManager:
    return ResourceSubscriptionManager()


async def test_subscribe_and_notify(manager: ResourceSubscriptionManager) -> None:
    received: list[str] = []

    async def send(raw: str) -> None:
        received.append(raw)

    manager.subscribe("file:///a.txt", "sess-1", send)
    await manager.notify_updated("file:///a.txt")
    assert len(received) == 1
    msg = json.loads(received[0])
    assert msg["method"] == "notifications/resources/updated"
    assert msg["params"]["uri"] == "file:///a.txt"


async def test_notify_with_no_subscribers_is_noop(manager: ResourceSubscriptionManager) -> None:
    # Should not raise
    await manager.notify_updated("file:///nonexistent.txt")


async def test_unsubscribe_stops_notifications(manager: ResourceSubscriptionManager) -> None:
    received: list[str] = []

    async def send(raw: str) -> None:
        received.append(raw)

    manager.subscribe("file:///a.txt", "sess-1", send)
    manager.unsubscribe("file:///a.txt", "sess-1")
    await manager.notify_updated("file:///a.txt")
    assert received == []


async def test_unsubscribe_all_removes_all_uris(manager: ResourceSubscriptionManager) -> None:
    received: list[str] = []

    async def send(raw: str) -> None:
        received.append(raw)

    manager.subscribe("file:///a.txt", "sess-1", send)
    manager.subscribe("file:///b.txt", "sess-1", send)
    assert manager.subscription_count == 2
    manager.unsubscribe_all("sess-1")
    assert manager.subscription_count == 0


async def test_multiple_subscribers_same_uri(manager: ResourceSubscriptionManager) -> None:
    results: list[tuple[str, str]] = []

    async def send1(raw: str) -> None:
        results.append(("1", raw))

    async def send2(raw: str) -> None:
        results.append(("2", raw))

    manager.subscribe("file:///x.txt", "sess-1", send1)
    manager.subscribe("file:///x.txt", "sess-2", send2)
    await manager.notify_updated("file:///x.txt")
    assert len(results) == 2
    sessions = {r[0] for r in results}
    assert sessions == {"1", "2"}


async def test_failed_send_does_not_block_others(manager: ResourceSubscriptionManager) -> None:
    received: list[str] = []

    async def failing_send(raw: str) -> None:
        raise RuntimeError("dead connection")

    async def good_send(raw: str) -> None:
        received.append(raw)

    manager.subscribe("file:///x.txt", "bad", failing_send)
    manager.subscribe("file:///x.txt", "good", good_send)
    # Should not raise
    await manager.notify_updated("file:///x.txt")
    assert len(received) == 1


def test_unsubscribe_noop_for_unknown_session(manager: ResourceSubscriptionManager) -> None:
    # Should not raise
    manager.unsubscribe("file:///nonexistent.txt", "ghost-session")


def test_get_subscribers_returns_copy(manager: ResourceSubscriptionManager) -> None:
    async def send(raw: str) -> None:
        pass

    manager.subscribe("file:///a.txt", "sess-1", send)
    subs = manager.get_subscribers("file:///a.txt")
    assert "sess-1" in subs
    # Modifying the returned dict should not affect the manager
    subs.clear()
    assert manager.subscription_count == 1


def test_subscription_count_empty(manager: ResourceSubscriptionManager) -> None:
    assert manager.subscription_count == 0


async def test_unsubscribe_cleans_up_empty_uri(manager: ResourceSubscriptionManager) -> None:
    """When the last subscriber for a URI unsubscribes, the URI entry is removed."""

    async def send(raw: str) -> None:
        pass

    manager.subscribe("file:///sole.txt", "sess-1", send)
    assert manager.subscription_count == 1
    manager.unsubscribe("file:///sole.txt", "sess-1")
    assert manager.subscription_count == 0
    # URI should be completely gone
    assert manager.get_subscribers("file:///sole.txt") == {}
