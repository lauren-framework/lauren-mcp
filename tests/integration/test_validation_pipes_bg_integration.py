"""Integration tests: FieldDescriptor validation, pipe transformations, and
BackgroundTasks support through the full Lauren DI + WS MCP stack.

All tests use:
  - LaurenFactory.create(AppModule) — real Lauren DI container
  - TestClient(app)                — triggers @post_construct / handler registration
  - WsTestClient(app)              — in-process WebSocket (no subprocess)

Coverage:
  - tools/list advertises JSON Schema keywords (minimum, maximum, minLength)
    derived from QueryField constraints in Annotated[T, QueryField(...)] params
  - tools/call with an invalid value returns INVALID_PARAMS (-32602)
  - tools/call with a valid value returns the correct result
  - Pipe-transformed tool: server receives the transformed value
  - BackgroundTasks tool: side effects run in the same event loop after the
    tools/call response arrives (verified with asyncio.sleep(0))
  - BackgroundTasks tool that also raises: tasks run; error propagates
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

import pytest
from lauren import BackgroundTasks, LaurenFactory, QueryField, module, pipe
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Module-level pipe functions (must be at module level with future annotations)
# ---------------------------------------------------------------------------


@pipe()
def _double_int(v: int, ctx) -> int:  # type: ignore[no-untyped-def]
    return v * 2


# ---------------------------------------------------------------------------
# Server definitions (module-level so future annotations resolve)
# ---------------------------------------------------------------------------

# Side-effect log shared across tests (reset per test via fixture)
_BG_LOG: list[str] = []


@mcp_server("/mcp-validation")
class ValidationServer:
    """Server with tools that use QueryField constraints."""

    @mcp_tool()
    async def place_order(self, qty: Annotated[int, QueryField(ge=1)]) -> str:
        """Place an order.

        Args:
            qty: Quantity — must be >= 1.
        """
        return f"ordered {qty}"

    @mcp_tool()
    async def rate_item(
        self,
        item_id: str,
        score: Annotated[int, QueryField(ge=1, le=5)],
    ) -> str:
        """Rate an item 1-5.

        Args:
            item_id: Item identifier.
            score: Star rating (1-5).
        """
        return f"rated {item_id}: {score}/5"

    @mcp_tool()
    async def search(self, query: Annotated[str, QueryField(min_length=2)]) -> list:
        """Search for items.

        Args:
            query: Search terms (min 2 characters).
        """
        return [{"name": "result", "query": query}]


@mcp_server("/mcp-pipe")
class PipeServer:
    """Server with tools that use pipe transformations."""

    @mcp_tool()
    async def doubled(self, x: Annotated[int, QueryField(ge=0) | pipe(_double_int)]) -> str:
        """Return double of x.

        Args:
            x: Input integer (non-negative).
        """
        return str(x)


@mcp_server("/mcp-bg")
class BgTaskServer:
    """Server with tools that use BackgroundTasks."""

    @mcp_tool()
    async def process(self, name: str, bg: BackgroundTasks) -> str:
        """Process a name and schedule a background task.

        Args:
            name: Name to process.
        """
        bg.add_task(lambda: _BG_LOG.append(f"processed:{name}"))
        return f"scheduled:{name}"

    @mcp_tool()
    async def process_multiple(self, name: str, bg: BackgroundTasks) -> str:
        """Schedule two background tasks.

        Args:
            name: Name to process.
        """
        bg.add_task(lambda: _BG_LOG.append(f"task1:{name}"))
        bg.add_task(lambda: _BG_LOG.append(f"task2:{name}"))
        return f"ok:{name}"

    @mcp_tool()
    async def raise_after_schedule(self, name: str, bg: BackgroundTasks) -> str:
        """Schedule a bg task then raise.

        Args:
            name: Name to process.
        """
        bg.add_task(lambda: _BG_LOG.append(f"bg_ran:{name}"))
        raise ValueError(f"deliberate error: {name}")


# ---------------------------------------------------------------------------
# Lauren app fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def validation_app():
    @module(imports=[McpServerModule.for_root(ValidationServer)])
    class App:
        pass

    app = LaurenFactory.create(App)
    TestClient(app)
    return app


@pytest.fixture(scope="module")
def pipe_app():
    @module(imports=[McpServerModule.for_root(PipeServer)])
    class App:
        pass

    app = LaurenFactory.create(App)
    TestClient(app)
    return app


@pytest.fixture(scope="module")
def bg_app():
    @module(imports=[McpServerModule.for_root(BgTaskServer)])
    class App:
        pass

    app = LaurenFactory.create(App)
    TestClient(app)
    return app


@pytest.fixture(autouse=True)
def clear_bg_log() -> None:
    """Reset the shared background-task log before each test."""
    _BG_LOG.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _handshake(conn) -> dict:  # type: ignore[no-untyped-def]
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return resp


async def _rpc(conn, method: str, req_id: int, params: dict | None = None) -> dict:  # type: ignore[no-untyped-def]
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    await conn.send_json(msg)
    return await asyncio.wait_for(conn.receive_json(), timeout=5.0)


# ---------------------------------------------------------------------------
# Schema keyword tests (tools/list → inputSchema)
# ---------------------------------------------------------------------------


class TestSchemaKeywords:
    """tools/list must reflect QueryField constraints as JSON Schema keywords."""

    async def test_place_order_schema_has_minimum_1(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 10)
            tool = next(t for t in resp["result"]["tools"] if t["name"] == "place_order")
            assert tool["inputSchema"]["properties"]["qty"]["minimum"] == 1

    async def test_rate_item_score_schema_has_minimum_and_maximum(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 10)
            tool = next(t for t in resp["result"]["tools"] if t["name"] == "rate_item")
            score_schema = tool["inputSchema"]["properties"]["score"]
            assert score_schema["minimum"] == 1
            assert score_schema["maximum"] == 5

    async def test_search_schema_has_min_length(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 10)
            tool = next(t for t in resp["result"]["tools"] if t["name"] == "search")
            assert tool["inputSchema"]["properties"]["query"]["minLength"] == 2

    async def test_bg_param_not_in_input_schema(self, bg_app):
        """BackgroundTasks parameters must be excluded from inputSchema."""
        async with WsTestClient(bg_app).connect("/mcp-bg/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 10)
            tool = next(t for t in resp["result"]["tools"] if t["name"] == "process")
            assert "bg" not in tool["inputSchema"].get("properties", {})
            assert "name" in tool["inputSchema"]["properties"]


# ---------------------------------------------------------------------------
# Validation error tests (tools/call → INVALID_PARAMS)
# ---------------------------------------------------------------------------


class TestValidationErrors:
    """tools/call with invalid arguments returns INVALID_PARAMS (-32602)."""

    async def test_qty_zero_returns_invalid_params(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                20,
                {"name": "place_order", "arguments": {"qty": 0}},
            )
            assert "error" in resp, f"Expected error, got: {resp}"
            assert resp["error"]["code"] == -32602  # INVALID_PARAMS

    async def test_qty_negative_returns_invalid_params(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                21,
                {"name": "place_order", "arguments": {"qty": -5}},
            )
            assert resp["error"]["code"] == -32602

    async def test_error_message_contains_field_name(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                22,
                {"name": "place_order", "arguments": {"qty": 0}},
            )
            assert "qty" in resp["error"]["message"]

    async def test_score_above_max_returns_invalid_params(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                23,
                {"name": "rate_item", "arguments": {"item_id": "x", "score": 6}},
            )
            assert resp["error"]["code"] == -32602

    async def test_score_below_min_returns_invalid_params(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                24,
                {"name": "rate_item", "arguments": {"item_id": "x", "score": 0}},
            )
            assert resp["error"]["code"] == -32602

    async def test_query_too_short_returns_invalid_params(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                25,
                {"name": "search", "arguments": {"query": "x"}},
            )
            assert resp["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# Valid call tests
# ---------------------------------------------------------------------------


class TestValidCalls:
    """tools/call with valid arguments returns the correct result."""

    async def test_valid_qty_returns_ordered_text(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                30,
                {"name": "place_order", "arguments": {"qty": 3}},
            )
            assert "result" in resp, f"Expected result, got: {resp}"
            assert resp["result"]["isError"] is False
            text = resp["result"]["content"][0]["text"]
            assert "ordered 3" in text

    async def test_boundary_qty_1_passes(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                31,
                {"name": "place_order", "arguments": {"qty": 1}},
            )
            assert "result" in resp
            assert "ordered 1" in resp["result"]["content"][0]["text"]

    async def test_valid_rating_returns_rated_text(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                32,
                {"name": "rate_item", "arguments": {"item_id": "abc", "score": 4}},
            )
            assert "result" in resp
            assert "rated abc: 4/5" in resp["result"]["content"][0]["text"]

    async def test_valid_search_returns_results(self, validation_app):
        async with WsTestClient(validation_app).connect("/mcp-validation/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                33,
                {"name": "search", "arguments": {"query": "ab"}},
            )
            assert "result" in resp
            content_text = resp["result"]["content"][0]["text"]
            data = json.loads(content_text)
            assert isinstance(data, list)
            assert data[0]["query"] == "ab"


# ---------------------------------------------------------------------------
# Pipe transformation tests
# ---------------------------------------------------------------------------


class TestPipeTransformation:
    """Pipe functions applied to params transform the value before dispatch."""

    async def test_doubled_tool_returns_double_of_input(self, pipe_app):
        async with WsTestClient(pipe_app).connect("/mcp-pipe/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                40,
                {"name": "doubled", "arguments": {"x": 5}},
            )
            assert "result" in resp, f"Expected result, got: {resp}"
            assert resp["result"]["content"][0]["text"] == "10"

    async def test_doubled_tool_x_zero_returns_zero(self, pipe_app):
        async with WsTestClient(pipe_app).connect("/mcp-pipe/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                41,
                {"name": "doubled", "arguments": {"x": 0}},
            )
            assert resp["result"]["content"][0]["text"] == "0"

    async def test_pipe_schema_still_shows_minimum_constraint(self, pipe_app):
        """Schema shows the QueryField constraint, not the pipe result."""
        async with WsTestClient(pipe_app).connect("/mcp-pipe/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 42)
            tool = next(t for t in resp["result"]["tools"] if t["name"] == "doubled")
            assert tool["inputSchema"]["properties"]["x"]["minimum"] == 0

    async def test_invalid_input_to_pipe_tool_returns_invalid_params(self, pipe_app):
        """Validation runs before the pipe; invalid values return INVALID_PARAMS."""
        async with WsTestClient(pipe_app).connect("/mcp-pipe/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                43,
                {"name": "doubled", "arguments": {"x": -1}},
            )
            assert "error" in resp
            assert resp["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# BackgroundTasks tests
# ---------------------------------------------------------------------------


class TestBackgroundTasks:
    """BackgroundTasks: side effects run in the same event loop as the call."""

    async def test_process_returns_scheduled_text(self, bg_app):
        async with WsTestClient(bg_app).connect("/mcp-bg/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                50,
                {"name": "process", "arguments": {"name": "alice"}},
            )
            assert "result" in resp
            assert "scheduled:alice" in resp["result"]["content"][0]["text"]

    async def test_bg_task_side_effect_visible_after_sleep(self, bg_app):
        """After one event-loop turn the bg task has run."""
        async with WsTestClient(bg_app).connect("/mcp-bg/ws") as conn:
            await _handshake(conn)
            await _rpc(
                conn,
                "tools/call",
                51,
                {"name": "process", "arguments": {"name": "bob"}},
            )
        # Background tasks run synchronously inside the handler before the
        # response is sent, so by the time we get the response they are done.
        await asyncio.sleep(0)
        assert "processed:bob" in _BG_LOG

    async def test_multiple_bg_tasks_all_run(self, bg_app):
        async with WsTestClient(bg_app).connect("/mcp-bg/ws") as conn:
            await _handshake(conn)
            await _rpc(
                conn,
                "tools/call",
                52,
                {"name": "process_multiple", "arguments": {"name": "carol"}},
            )
        await asyncio.sleep(0)
        assert "task1:carol" in _BG_LOG
        assert "task2:carol" in _BG_LOG

    async def test_bg_tasks_order_preserved(self, bg_app):
        async with WsTestClient(bg_app).connect("/mcp-bg/ws") as conn:
            await _handshake(conn)
            await _rpc(
                conn,
                "tools/call",
                53,
                {"name": "process_multiple", "arguments": {"name": "dave"}},
            )
        await asyncio.sleep(0)
        task1_idx = _BG_LOG.index("task1:dave")
        task2_idx = _BG_LOG.index("task2:dave")
        assert task1_idx < task2_idx, "task1 must run before task2"

    async def test_tool_that_raises_still_propagates_error(self, bg_app):
        """When the tool raises, the client gets INTERNAL_ERROR (-32603)."""
        async with WsTestClient(bg_app).connect("/mcp-bg/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn,
                "tools/call",
                54,
                {"name": "raise_after_schedule", "arguments": {"name": "eve"}},
            )
        # The tool raised, so we expect an error response.
        assert "error" in resp, f"Expected error response, got: {resp}"
        assert resp["error"]["code"] == -32603  # INTERNAL_ERROR

    async def test_bg_not_in_input_schema(self, bg_app):
        """BackgroundTasks param must be absent from the wire schema."""
        async with WsTestClient(bg_app).connect("/mcp-bg/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 55)
            tool = next(t for t in resp["result"]["tools"] if t["name"] == "process")
            assert "bg" not in tool["inputSchema"].get("properties", {})
            assert "name" in tool["inputSchema"]["properties"]
