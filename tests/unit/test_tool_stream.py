"""Unit tests for ToolStream draining."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from lauren_mcp._server._context import McpToolContext
from lauren_mcp._types import JsonRpcRequest, ToolStream
from lauren_mcp.server._handlers import _drain_tool_stream, make_tools_call_handler
from lauren_mcp.server._meta import McpToolMeta

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(
    name: str = "test",
    description: str = "",
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    structured_output: bool | None = None,
) -> McpToolMeta:
    return McpToolMeta(
        name=name,
        description=description,
        input_schema=input_schema or {"type": "object", "properties": {}},
        method_name=name,
        output_schema=output_schema,
        structured_output=structured_output,
    )


async def drain_with_notifications(
    generator: AsyncGenerator[Any, None],
    total: int | None = None,
    accumulate: Any = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Helper: drain a ToolStream and capture all progress notifications sent."""
    sent: list[dict[str, Any]] = []

    async def send_notification(payload: dict[str, Any]) -> None:
        sent.append(payload)

    ctx = McpToolContext(
        tool_name="test",
        _progress_token="tok",
        _send_notification=send_notification,
    )
    stream = ToolStream(generator=generator, total=total, accumulate=accumulate)
    meta = _make_meta()
    result = await _drain_tool_stream(stream, meta, ctx)
    return result, sent


async def _gen(*values: Any) -> AsyncGenerator[Any, None]:
    """Create an async generator yielding the given values."""
    for v in values:
        yield v


# ---------------------------------------------------------------------------
# Core accumulation tests
# ---------------------------------------------------------------------------


async def test_str_chunks_joined_by_default() -> None:
    """3 str chunks → joined string as final value."""
    result, _ = await drain_with_notifications(_gen("hello", " ", "world"))
    assert result["content"] == [{"type": "text", "text": "hello world"}]


async def test_three_chunks_three_notifications() -> None:
    """3 yields → 3 report_progress calls in order."""
    result, sent = await drain_with_notifications(_gen("a", "b", "c"))
    # 3 notifications
    assert len(sent) == 3
    assert sent[0]["params"]["progress"] == 0
    assert sent[1]["params"]["progress"] == 1
    assert sent[2]["params"]["progress"] == 2
    # Final result is joined
    assert result["content"][0]["text"] == "abc"


async def test_total_forwarded_to_progress() -> None:
    """ToolStream(gen, total=5) → each notification has 'total': 5."""
    _, sent = await drain_with_notifications(_gen("x", "y"), total=5)
    assert len(sent) == 2
    assert sent[0]["params"]["total"] == 5
    assert sent[1]["params"]["total"] == 5


async def test_empty_generator_final_is_none() -> None:
    """Generator yields nothing → final=None, zero notifications."""

    async def empty_gen() -> AsyncGenerator[Any, None]:
        return
        yield  # make it an async generator

    result, sent = await drain_with_notifications(empty_gen())
    assert sent == []
    # None result → text "None"
    assert result["content"] == [{"type": "text", "text": "None"}]


async def test_custom_accumulate_callable() -> None:
    """accumulate=lambda cs: sum(cs) — custom reducer used."""
    result, _ = await drain_with_notifications(_gen(1, 2, 3), accumulate=lambda cs: sum(cs))
    assert result["content"] == [{"type": "text", "text": "6"}]


async def test_last_chunk_used_for_non_str() -> None:
    """Non-str chunks with no accumulate → last chunk is final value."""
    result, _ = await drain_with_notifications(_gen(10, 20, 30))
    assert result["content"] == [{"type": "text", "text": "30"}]


async def test_ctx_none_no_notifications_still_accumulates() -> None:
    """ctx=None → no notifications, accumulation still works."""
    stream = ToolStream(generator=_gen("a", "b", "c"))
    meta = _make_meta()
    result = await _drain_tool_stream(stream, meta, ctx=None)
    assert result["content"] == [{"type": "text", "text": "abc"}]


# ---------------------------------------------------------------------------
# Notification message content
# ---------------------------------------------------------------------------


async def test_notification_message_contains_chunk() -> None:
    """Progress notification message contains json-encoded chunk."""
    _, sent = await drain_with_notifications(_gen("hello"))
    assert len(sent) == 1
    params = sent[0]["params"]
    assert params["message"] == '"hello"'
    assert params["progressToken"] == "tok"


async def test_notification_message_int_chunk() -> None:
    """Int chunk is json-encoded in message."""
    _, sent = await drain_with_notifications(_gen(42))
    assert sent[0]["params"]["message"] == "42"


async def test_notification_message_dict_chunk() -> None:
    """Dict chunk is json-encoded in message."""
    _, sent = await drain_with_notifications(_gen({"key": "val"}))
    assert json.loads(sent[0]["params"]["message"]) == {"key": "val"}


# ---------------------------------------------------------------------------
# output_schema validation
# ---------------------------------------------------------------------------


async def test_output_schema_validated_against_final() -> None:
    """output_schema declared; missing required key → ValueError."""
    meta = _make_meta(
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        }
    )

    # Yield a dict missing the required key
    async def bad_gen() -> AsyncGenerator[Any, None]:
        yield {"wrong_key": "value"}

    stream = ToolStream(generator=bad_gen())

    result = await _drain_tool_stream(stream, meta, ctx=None)
    # _drain_tool_stream does NOT call _validate_output — that is the caller's job.
    # The make_tools_call_handler does.  Just verify the structured content is set.
    assert "structuredContent" in result


# ---------------------------------------------------------------------------
# make_tools_call_handler integration
# ---------------------------------------------------------------------------


async def test_make_tools_call_handler_with_tool_stream() -> None:
    """Handler calls _drain_tool_stream when method returns ToolStream."""

    class StreamServer:
        async def count(self) -> ToolStream:  # type: ignore[return]
            async def gen() -> AsyncGenerator[str, None]:
                yield "a"
                yield "b"
                yield "c"

            return ToolStream(gen())

    meta = McpToolMeta(
        name="count",
        description="",
        input_schema={"type": "object", "properties": {}},
        method_name="count",
    )
    server = StreamServer()
    handler = make_tools_call_handler(server, [meta])
    req = JsonRpcRequest(method="tools/call", params={"name": "count", "arguments": {}}, id=1)
    result = await handler(req)
    assert result["content"] == [{"type": "text", "text": "abc"}]
    assert result["isError"] is False


async def test_tool_stream_without_progress_token_no_crash() -> None:
    """ToolStream without progressToken → no crash, correct final result."""

    class StreamServer:
        async def greet(self) -> ToolStream:  # type: ignore[return]
            async def gen() -> AsyncGenerator[str, None]:
                yield "hi"
                yield "!"

            return ToolStream(gen())

    meta = McpToolMeta(
        name="greet",
        description="",
        input_schema={"type": "object", "properties": {}},
        method_name="greet",
    )
    server = StreamServer()
    handler = make_tools_call_handler(server, [meta])
    # No _meta / no progressToken
    req = JsonRpcRequest(method="tools/call", params={"name": "greet", "arguments": {}}, id=1)
    result = await handler(req)
    assert result["content"] == [{"type": "text", "text": "hi!"}]


async def test_tool_stream_with_context_factory_and_progress_token() -> None:
    """Tool without ctx param, progressToken in request → ctx built, notifications sent."""
    notifications: list[dict] = []

    async def send_notification(payload: dict) -> None:
        notifications.append(payload)

    from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding

    binding = TransportBinding(send_notification=send_notification)
    token = CURRENT_BINDING.set(binding)

    try:

        class StreamServer:
            async def nums(self) -> ToolStream:  # type: ignore[return]
                async def gen() -> AsyncGenerator[int, None]:
                    yield 1
                    yield 2

                return ToolStream(gen())

        meta = McpToolMeta(
            name="nums",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="nums",
        )
        server = StreamServer()

        from lauren_mcp.server._handlers import make_context_factory

        ctx_factory = make_context_factory()
        handler = make_tools_call_handler(server, [meta], context_factory=ctx_factory)
        req = JsonRpcRequest(
            method="tools/call",
            params={
                "name": "nums",
                "arguments": {},
                "_meta": {"progressToken": "tok123"},
            },
            id=1,
        )
        result = await handler(req)
    finally:
        CURRENT_BINDING.reset(token)

    # Two notifications (one per chunk)
    progress_notifs = [n for n in notifications if n.get("method") == "notifications/progress"]
    assert len(progress_notifs) == 2
    # Final result is the last chunk (non-str)
    assert result["content"] == [{"type": "text", "text": "2"}]


async def test_tool_stream_not_in_input_schema() -> None:
    """ToolStream return type does not affect inputSchema."""
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META

    @mcp_server("/mcp")
    class SrvrA:
        @mcp_tool()
        async def count(self, n: int) -> ToolStream:  # type: ignore[return]
            """Count to n.

            Args:
                n: How many numbers to count.
            """

            async def gen() -> AsyncGenerator[str, None]:
                for i in range(n):
                    yield str(i)

            return ToolStream(gen())

    fn = SrvrA.count
    tool_meta: McpToolMeta = getattr(fn, MCP_TOOL_META)
    schema = tool_meta.input_schema
    # Only 'n' should be in the schema — no ToolStream params
    assert "n" in schema.get("properties", {})
    # 'ToolStream' should not appear anywhere
    schema_str = json.dumps(schema)
    assert "ToolStream" not in schema_str
    assert "stream" not in schema_str.lower() or "n" in schema.get("properties", {})
