"""Unit tests for McpToolContext injection and its messaging APIs."""

from __future__ import annotations

from typing import Any

import pytest

from lauren_mcp import (
    McpElicitationNotAvailable,
    McpSamplingNotAvailable,
    McpToolContext,
    mcp_tool,
)
from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding
from lauren_mcp._server._context import (
    LogLevelState,
    build_elicitation_schema,
)
from lauren_mcp._types import ClientCapabilities, JsonRpcRequest
from lauren_mcp.server._handlers import (
    make_context_factory,
    make_tools_call_handler,
)
from lauren_mcp.server._meta import MCP_TOOL_META


class TestContextDetection:
    def test_context_param_excluded_from_schema(self):
        @mcp_tool()
        async def search(self, query: str, ctx: McpToolContext) -> list:
            """Search."""

        meta = getattr(search, MCP_TOOL_META)
        assert "ctx" not in meta.input_schema["properties"]
        assert meta.context_param_name == "ctx"
        assert meta.reads_context is True

    def test_optional_context_param_detected(self):
        @mcp_tool()
        async def search(self, query: str, ctx: McpToolContext | None = None) -> list:
            """Search."""

        meta = getattr(search, MCP_TOOL_META)
        assert meta.context_param_name == "ctx"
        assert "ctx" not in meta.input_schema["properties"]

    def test_any_param_name_works(self):
        @mcp_tool()
        async def op(self, data: str, tool_ctx: McpToolContext) -> str:
            """Op."""

        meta = getattr(op, MCP_TOOL_META)
        assert meta.context_param_name == "tool_ctx"

    def test_no_context_param(self):
        @mcp_tool()
        async def plain(self, x: int) -> int:
            """Plain."""

        meta = getattr(plain, MCP_TOOL_META)
        assert meta.context_param_name is None
        assert meta.reads_context is False


class _Server:
    @mcp_tool()
    async def whoami(self, ctx: McpToolContext) -> dict:
        """Return context facts."""
        return {
            "tool_name": ctx.tool_name,
            "tool_use_id": ctx.tool_use_id,
            "session_id": ctx.session_id,
            "metadata": ctx.metadata,
            "lifespan": ctx.lifespan_context,
        }


class TestContextInjection:
    async def test_tool_receives_context(self):
        meta = getattr(_Server.whoami, MCP_TOOL_META)
        factory = make_context_factory({"team": "core"}, lifespan_getter=lambda: {"db": "conn"})
        handler = make_tools_call_handler(_Server(), [meta], context_factory=factory)

        binding = TransportBinding(session_id="sess-1")
        token = CURRENT_BINDING.set(binding)
        try:
            req = JsonRpcRequest(method="tools/call", id=7, params={"name": "whoami"})
            result = await handler(req)
        finally:
            CURRENT_BINDING.reset(token)

        facts = result["structuredContent"]
        assert facts["tool_name"] == "whoami"
        assert facts["tool_use_id"] == 7
        assert facts["session_id"] == "sess-1"
        assert facts["metadata"] == {"team": "core"}
        assert facts["lifespan"] == {"db": "conn"}


class TestProgress:
    async def test_report_progress_sends_notification(self):
        sent: list[dict[str, Any]] = []

        async def send(payload: dict[str, Any]) -> None:
            sent.append(payload)

        ctx = McpToolContext(tool_name="t", _progress_token="tok-1", _send_notification=send)
        await ctx.report_progress(5, total=10)
        assert sent == [
            {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progressToken": "tok-1", "progress": 5, "total": 10},
            }
        ]

    async def test_no_token_is_noop(self):
        sent: list[dict[str, Any]] = []

        async def send(payload: dict[str, Any]) -> None:
            sent.append(payload)

        ctx = McpToolContext(tool_name="t", _send_notification=send)
        await ctx.report_progress(5)
        assert sent == []

    async def test_progress_token_extracted_from_meta(self):
        class Server:
            @mcp_tool()
            async def slow(self, ctx: McpToolContext) -> str:
                await ctx.report_progress(1, total=2)
                return "ok"

        sent: list[dict[str, Any]] = []

        async def send(payload: dict[str, Any]) -> None:
            sent.append(payload)

        meta = getattr(Server.slow, MCP_TOOL_META)
        handler = make_tools_call_handler(Server(), [meta], context_factory=make_context_factory())
        binding = TransportBinding(send_notification=send)
        token = CURRENT_BINDING.set(binding)
        try:
            req = JsonRpcRequest(
                method="tools/call",
                id=1,
                params={"name": "slow", "_meta": {"progressToken": "p-9"}},
            )
            await handler(req)
        finally:
            CURRENT_BINDING.reset(token)
        assert sent[0]["params"]["progressToken"] == "p-9"


class TestLogging:
    async def test_log_sends_notification(self):
        sent: list[dict[str, Any]] = []

        async def send(payload: dict[str, Any]) -> None:
            sent.append(payload)

        ctx = McpToolContext(tool_name="audit", _send_notification=send)
        await ctx.info("hello", {"k": 1})
        assert sent[0]["method"] == "notifications/message"
        assert sent[0]["params"]["level"] == "info"
        assert sent[0]["params"]["logger"] == "audit"
        assert sent[0]["params"]["data"] == {"message": "hello", "extra": {"k": 1}}

    async def test_level_filtering(self):
        sent: list[dict[str, Any]] = []

        async def send(payload: dict[str, Any]) -> None:
            sent.append(payload)

        state = LogLevelState("warning")
        ctx = McpToolContext(tool_name="t", _send_notification=send, _log_level_state=state)
        await ctx.debug("dropped")
        await ctx.info("dropped")
        await ctx.warning("kept")
        await ctx.error("kept")
        assert [p["params"]["level"] for p in sent] == ["warning", "error"]

    async def test_no_transport_is_noop(self):
        ctx = McpToolContext(tool_name="t")
        await ctx.info("nothing happens")  # must not raise


class TestSampling:
    async def test_sample_requires_client_rpc(self):
        ctx = McpToolContext(tool_name="t")
        with pytest.raises(McpSamplingNotAvailable, match="transport"):
            await ctx.sample("hello")

    async def test_sample_requires_capability(self):
        async def rpc(method: str, params: dict) -> Any:
            return {}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(),  # no sampling
        )
        with pytest.raises(McpSamplingNotAvailable, match="capability"):
            await ctx.sample("hello")

    async def test_sample_round_trip(self):
        calls: list[tuple[str, dict]] = []

        async def rpc(method: str, params: dict) -> Any:
            calls.append((method, params))
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "The answer"},
                "model": "claude-fable-5",
            }

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(sampling={}),
        )
        result = await ctx.sample("Summarise this", max_tokens=64, system_prompt="Be brief")
        assert result.text == "The answer"
        assert result.model == "claude-fable-5"
        method, params = calls[0]
        assert method == "sampling/createMessage"
        assert params["maxTokens"] == 64
        assert params["systemPrompt"] == "Be brief"
        assert params["messages"][0]["content"]["text"] == "Summarise this"


class TestElicitation:
    async def test_elicit_requires_capability(self):
        async def rpc(method: str, params: dict) -> Any:
            return {}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(),
        )
        with pytest.raises(McpElicitationNotAvailable):
            await ctx.elicit("Proceed?")

    async def test_elicit_round_trip(self):
        calls: list[tuple[str, dict]] = []

        async def rpc(method: str, params: dict) -> Any:
            calls.append((method, params))
            return {"action": "accept", "content": {"value": "yes"}}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(elicitation={}),
        )
        result = await ctx.elicit("Pick one", str)
        assert result.action == "accept"
        assert result.content == {"value": "yes"}
        assert calls[0][0] == "elicitation/create"
        assert calls[0][1]["requestedSchema"]["properties"]["value"] == {"type": "string"}


class TestElicitationSchema:
    def test_none_means_approval_only(self):
        assert build_elicitation_schema(None) is None

    def test_scalars(self):
        assert build_elicitation_schema(bool)["properties"]["value"] == {"type": "boolean"}
        assert build_elicitation_schema(int)["properties"]["value"] == {"type": "integer"}

    def test_literal_options(self):
        from typing import Literal

        schema = build_elicitation_schema(Literal["a", "b"])
        assert schema["properties"]["value"]["enum"] == ["a", "b"]

    def test_unsupported_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            build_elicitation_schema(list)
