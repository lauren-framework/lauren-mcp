"""Integration tests for dispatcher cancel signal (cancel_requested event)."""

from __future__ import annotations

import asyncio

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp.server._decorators import mcp_server, mcp_tool

# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class _CancelServer:
    @mcp_tool()
    async def slow_work(self) -> str:
        """Runs for a long time."""
        await asyncio.sleep(100)
        return "done"


@module(imports=[McpServerModule.for_root(_CancelServer, transport="ws")])
class _CancelApp:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app():
    a = LaurenFactory.create(_CancelApp)
    TestClient(a)  # trigger @post_construct hooks
    return a


@pytest.fixture(scope="session")
def ws(app):
    return WsTestClient(app)


# ---------------------------------------------------------------------------
# Helper: WS handshake
# ---------------------------------------------------------------------------


async def _handshake(conn) -> None:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
    )
    await asyncio.wait_for(conn.receive_json(), timeout=3.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_dispatcher_can_cancel_in_flight_request() -> None:
    """McpDispatcher.cancel() produces REQUEST_CANCELLED on a dispatched request."""
    from lauren_mcp._types import JsonRpcErrorResponse, McpErrorCode

    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    started = asyncio.Event()

    async def _slow(params: dict | None) -> dict:
        started.set()
        await asyncio.sleep(60)
        return {}

    dispatcher.register("tools/call", _slow)

    from lauren_mcp._types import JsonRpcRequest

    req = JsonRpcRequest(method="tools/call", id=100)
    dispatch_task = asyncio.create_task(dispatcher.dispatch(req))

    await started.wait()
    dispatcher.cancel(100)

    resp = await dispatch_task
    assert isinstance(resp, JsonRpcErrorResponse)
    assert resp.error.code == McpErrorCode.REQUEST_CANCELLED


async def test_dispatcher_register_context_method_exists() -> None:
    """McpDispatcher.register_context() is callable."""
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()
    assert callable(dispatcher.register_context)


async def test_dispatcher_contexts_dict_exists() -> None:
    """McpDispatcher._contexts is an empty dict at init."""
    dispatcher = McpDispatcher()
    assert hasattr(dispatcher, "_contexts")
    assert isinstance(dispatcher._contexts, dict)
    assert len(dispatcher._contexts) == 0


async def test_cancel_sets_context_event() -> None:
    """cancel() sets the _cancel_event on registered context."""
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()

    cancel_event = asyncio.Event()

    class _FakeCtx:
        pass

    ctx = _FakeCtx()
    ctx._cancel_event = cancel_event  # type: ignore[attr-defined]
    dispatcher.register_context(5, ctx)

    # Put a dummy task so cancel() finds something to cancel
    dispatcher._in_flight[5] = asyncio.create_task(asyncio.sleep(100))
    result = dispatcher.cancel(5)

    assert result is True
    assert cancel_event.is_set()
