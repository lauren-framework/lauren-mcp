"""Unit tests for McpDispatcher cancel event registry."""

from __future__ import annotations

import asyncio

from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._types import JsonRpcRequest


class _FakeContext:
    """Minimal context stub with a _cancel_event attribute."""

    def __init__(self) -> None:
        self._cancel_event: asyncio.Event | None = None


async def test_dispatcher_sets_event_on_cancel() -> None:
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    ctx = _FakeContext()
    ctx._cancel_event = asyncio.Event()

    dispatcher.register_context(42, ctx)
    dispatcher._in_flight[42] = asyncio.create_task(asyncio.sleep(100))

    result = dispatcher.cancel(42)
    assert result is True
    assert ctx._cancel_event is not None
    assert ctx._cancel_event.is_set()


async def test_dispatcher_cancel_no_event_if_none() -> None:
    """cancel() should not crash when _cancel_event is None."""
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    ctx = _FakeContext()
    # _cancel_event is None (never accessed)

    dispatcher.register_context(99, ctx)
    dispatcher._in_flight[99] = asyncio.create_task(asyncio.sleep(100))

    result = dispatcher.cancel(99)
    assert result is True  # task was cancelled; no error


async def test_dispatcher_cancel_no_context_registered() -> None:
    """cancel() should not crash when no context was registered for the id."""
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    dispatcher._in_flight[7] = asyncio.create_task(asyncio.sleep(100))

    result = dispatcher.cancel(7)
    assert result is True


async def test_dispatcher_cancel_no_task() -> None:
    """cancel() returns False when there is no in-flight task."""
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    result = dispatcher.cancel(999)
    assert result is False


async def test_dispatcher_cleans_up_context_after_dispatch() -> None:
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    async def fake_handler(params: dict | None) -> dict:
        return {}

    dispatcher.register("tools/call", fake_handler)
    req = JsonRpcRequest(method="tools/call", id=7)
    await dispatcher.dispatch(req)

    assert 7 not in dispatcher._contexts


async def test_register_context_stores_context() -> None:
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    ctx = _FakeContext()
    dispatcher.register_context(5, ctx)
    assert dispatcher._contexts[5] is ctx


async def test_dispatcher_cancel_missing_cancel_event_attribute() -> None:
    """cancel() is safe when the context has no _cancel_event attribute at all."""
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    # Use an object with no _cancel_event attribute
    class _BareContext:
        pass

    dispatcher.register_context(11, _BareContext())
    dispatcher._in_flight[11] = asyncio.create_task(asyncio.sleep(100))

    # Should not raise AttributeError
    result = dispatcher.cancel(11)
    assert result is True
