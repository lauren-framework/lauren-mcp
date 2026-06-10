"""Unit tests for McpToolContext changes across all PRDs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, TypedDict

import pytest

from lauren_mcp._server._context import (
    _LEVEL_RANK,
    VALID_LOG_LEVELS,
    LogLevelState,
    McpSamplingLoopError,
    McpToolContext,
    _coerce_tools,
    _scalar_schema,
    build_elicitation_schema,
)
from lauren_mcp._types import ClientCapabilities, McpSamplingNotAvailable, ToolSchema

# ---------------------------------------------------------------------------
# 1. Progress message field
# ---------------------------------------------------------------------------


class TestProgressMessageField:
    async def test_progress_with_message_sends_message_field(self):
        sent: list[dict[str, Any]] = []

        async def send(msg: dict) -> None:
            sent.append(msg)

        ctx = McpToolContext(
            tool_name="t",
            _progress_token="tok-1",
            _send_notification=send,
        )
        await ctx.report_progress(5, 10, "half done")
        assert len(sent) == 1
        params = sent[0]["params"]
        assert params["progress"] == 5
        assert params["total"] == 10
        assert params["message"] == "half done"

    async def test_progress_without_message_omits_field(self):
        sent: list[dict[str, Any]] = []

        async def send(msg: dict) -> None:
            sent.append(msg)

        ctx = McpToolContext(
            tool_name="t",
            _progress_token="tok-1",
            _send_notification=send,
        )
        await ctx.report_progress(5)
        params = sent[0]["params"]
        assert "message" not in params

    async def test_progress_message_none_omits_field(self):
        sent: list[dict[str, Any]] = []

        async def send(msg: dict) -> None:
            sent.append(msg)

        ctx = McpToolContext(
            tool_name="t",
            _progress_token="tok-1",
            _send_notification=send,
        )
        await ctx.report_progress(3, message=None)
        params = sent[0]["params"]
        assert "message" not in params


# ---------------------------------------------------------------------------
# 2. 8-level log severity
# ---------------------------------------------------------------------------


class TestLogSeverityLevels:
    def test_level_rank_ordering(self):
        assert _LEVEL_RANK["debug"] < _LEVEL_RANK["info"]
        assert _LEVEL_RANK["info"] < _LEVEL_RANK["notice"]
        assert _LEVEL_RANK["notice"] < _LEVEL_RANK["warning"]
        assert _LEVEL_RANK["warning"] < _LEVEL_RANK["error"]
        assert _LEVEL_RANK["error"] < _LEVEL_RANK["critical"]
        assert _LEVEL_RANK["critical"] < _LEVEL_RANK["alert"]
        assert _LEVEL_RANK["alert"] < _LEVEL_RANK["emergency"]

    def test_level_rank_has_8_entries(self):
        assert len(_LEVEL_RANK) == 8

    def test_valid_log_levels_has_all_8(self):
        assert {
            "debug",
            "info",
            "notice",
            "warning",
            "error",
            "critical",
            "alert",
            "emergency",
        } == VALID_LOG_LEVELS

    def test_log_level_state_blocks_below_threshold(self):
        state = LogLevelState("notice")
        assert state.allows("info") is False
        assert state.allows("debug") is False

    def test_log_level_state_allows_at_and_above_threshold(self):
        state = LogLevelState("notice")
        assert state.allows("notice") is True
        assert state.allows("warning") is True
        assert state.allows("error") is True
        assert state.allows("critical") is True
        assert state.allows("alert") is True
        assert state.allows("emergency") is True

    async def test_ctx_notice_sends_notice_level(self):
        sent: list[dict[str, Any]] = []

        async def send(msg: dict) -> None:
            sent.append(msg)

        ctx = McpToolContext(tool_name="t", _send_notification=send)
        await ctx.notice("msg")
        assert len(sent) == 1
        assert sent[0]["params"]["level"] == "notice"

    async def test_ctx_critical_sends_critical_level(self):
        sent: list[dict[str, Any]] = []

        async def send(msg: dict) -> None:
            sent.append(msg)

        ctx = McpToolContext(tool_name="t", _send_notification=send)
        await ctx.critical("crash")
        assert len(sent) == 1
        assert sent[0]["params"]["level"] == "critical"

    async def test_notice_suppressed_below_warning_threshold(self):
        sent: list[dict[str, Any]] = []

        async def send(msg: dict) -> None:
            sent.append(msg)

        state = LogLevelState("warning")
        ctx = McpToolContext(tool_name="t", _send_notification=send, _log_level_state=state)
        await ctx.notice("ignored")
        assert len(sent) == 0

    async def test_critical_passes_warning_threshold(self):
        sent: list[dict[str, Any]] = []

        async def send(msg: dict) -> None:
            sent.append(msg)

        state = LogLevelState("warning")
        ctx = McpToolContext(tool_name="t", _send_notification=send, _log_level_state=state)
        await ctx.critical("visible")
        assert len(sent) == 1


# ---------------------------------------------------------------------------
# 3. list[str] in elicitation schema
# ---------------------------------------------------------------------------


class TestElicitationListStr:
    def test_scalar_schema_list_str(self):
        result = _scalar_schema(list[str])
        assert result == {"type": "array", "items": {"type": "string"}}

    def test_build_elicitation_schema_list_str(self):
        schema = build_elicitation_schema(list[str])
        assert schema == {
            "type": "object",
            "properties": {"value": {"type": "array", "items": {"type": "string"}}},
            "required": ["value"],
        }

    def test_build_elicitation_schema_list_int_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            build_elicitation_schema(list[int])

    def test_build_elicitation_schema_bare_list_raises(self):
        with pytest.raises(ValueError):
            build_elicitation_schema(list)

    def test_build_elicitation_schema_list_bool_raises(self):
        with pytest.raises(ValueError):
            build_elicitation_schema(list[bool])

    def test_dataclass_with_list_str_field(self):
        @dataclass
        class Form:
            title: str
            tags: list[str]

        schema = build_elicitation_schema(Form)
        assert schema is not None
        assert schema["properties"]["tags"] == {"type": "array", "items": {"type": "string"}}
        assert "tags" in schema["required"]

    def test_typeddict_with_list_str_field(self):
        class Form(TypedDict):
            name: str
            labels: list[str]

        schema = build_elicitation_schema(Form)
        assert schema is not None
        assert schema["properties"]["labels"] == {"type": "array", "items": {"type": "string"}}


# ---------------------------------------------------------------------------
# 4. elicit_url
# ---------------------------------------------------------------------------


class TestElicitUrl:
    async def test_raises_without_client_rpc(self):
        caps = ClientCapabilities(elicitation={"urlElicitation": True})
        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=None,
            _client_capabilities=caps,
        )
        # Import lazily as the type is added by another agent
        try:
            from lauren_mcp._types import McpUrlElicitationNotAvailable
        except ImportError:
            pytest.skip("McpUrlElicitationNotAvailable not yet in _types.py")
        with pytest.raises(McpUrlElicitationNotAvailable):
            await ctx.elicit_url("Login", "https://example.com/auth")

    async def test_raises_without_elicitation_capability(self):
        try:
            from lauren_mcp._types import McpUrlElicitationNotAvailable
        except ImportError:
            pytest.skip("McpUrlElicitationNotAvailable not yet in _types.py")

        async def rpc(method: str, params: dict) -> dict:
            return {}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(),  # no elicitation
        )
        with pytest.raises(McpUrlElicitationNotAvailable):
            await ctx.elicit_url("Login", "https://example.com/auth")

    async def test_raises_without_url_elicitation_flag(self):
        try:
            from lauren_mcp._types import McpUrlElicitationNotAvailable
        except ImportError:
            pytest.skip("McpUrlElicitationNotAvailable not yet in _types.py")

        async def rpc(method: str, params: dict) -> dict:
            return {}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(elicitation={}),  # no urlElicitation
        )
        with pytest.raises(McpUrlElicitationNotAvailable, match="urlElicitation"):
            await ctx.elicit_url("Login", "https://example.com/auth")

    async def test_sends_correct_wire_format(self):
        try:
            from lauren_mcp._types import UrlElicitResult  # noqa: F401
        except ImportError:
            pytest.skip("UrlElicitResult not yet in _types.py")

        sent: list[tuple[str, dict]] = []

        async def rpc(method: str, params: dict) -> dict:
            sent.append((method, params))
            return {"action": "accept"}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(elicitation={"urlElicitation": True}),
        )
        result = await ctx.elicit_url(
            "Login with GitHub",
            "https://github.com/login/oauth/authorize?state=abc",
            elicitation_id="id-123",
        )
        assert result.action == "accept"
        assert len(sent) == 1
        method, params = sent[0]
        assert method == "elicitation/create"
        assert params["message"] == "Login with GitHub"
        assert params["requestedUrl"] == "https://github.com/login/oauth/authorize?state=abc"
        assert params["elicitationId"] == "id-123"
        assert "requestedSchema" not in params

    async def test_auto_generates_elicitation_id(self):
        try:
            from lauren_mcp._types import UrlElicitResult  # noqa: F401
        except ImportError:
            pytest.skip("UrlElicitResult not yet in _types.py")

        sent: list[tuple[str, dict]] = []

        async def rpc(method: str, params: dict) -> dict:
            sent.append((method, params))
            return {"action": "cancel"}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(elicitation={"urlElicitation": True}),
        )
        await ctx.elicit_url("Login", "https://example.com/auth")
        _, params = sent[0]
        assert "elicitationId" in params
        assert len(params["elicitationId"]) == 32  # UUID4 hex, no dashes


# ---------------------------------------------------------------------------
# 5. cancel_requested property
# ---------------------------------------------------------------------------


class TestCancelRequested:
    def test_cancel_event_created_lazily(self):
        ctx = McpToolContext(tool_name="t")
        assert ctx._cancel_event is None
        ev = ctx.cancel_requested
        assert isinstance(ev, asyncio.Event)
        assert not ev.is_set()

    def test_cancel_event_singleton_on_repeated_access(self):
        ctx = McpToolContext(tool_name="t")
        ev1 = ctx.cancel_requested
        ev2 = ctx.cancel_requested
        assert ev1 is ev2

    def test_cancel_event_settable(self):
        ctx = McpToolContext(tool_name="t")
        ev = ctx.cancel_requested
        assert not ev.is_set()
        ev.set()
        assert ctx.cancel_requested.is_set()


# ---------------------------------------------------------------------------
# 6. ctx.sample() with tools= / tool_choice= / max_tool_iterations=
# ---------------------------------------------------------------------------


class TestSampleToolsParameter:
    async def test_raises_when_sampling_has_no_tools_key(self):
        async def rpc(method: str, params: dict) -> Any:
            return {}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(sampling={}),
        )
        tool = ToolSchema(name="f", description="d", inputSchema={})
        with pytest.raises(McpSamplingNotAvailable, match="tool-enabled sampling"):
            await ctx.sample("hello", tools=[tool])

    async def test_raises_when_sampling_tools_false(self):
        async def rpc(method: str, params: dict) -> Any:
            return {}

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(sampling={"tools": False}),
        )
        tool = ToolSchema(name="f", description="d", inputSchema={})
        with pytest.raises(McpSamplingNotAvailable):
            await ctx.sample("hello", tools=[tool])

    async def test_passes_when_sampling_tools_true(self):
        sent: list[dict] = []

        async def rpc(method: str, params: dict) -> Any:
            sent.append(params)
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "ok"},
                "model": "m",
            }

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(sampling={"tools": True}),
        )
        tool = ToolSchema(name="f", description="d", inputSchema={})
        result = await ctx.sample("hello", tools=[tool])
        assert result.text == "ok"
        assert "tools" in sent[0]
        assert sent[0]["tools"] == [{"name": "f", "description": "d", "inputSchema": {}}]

    async def test_tool_choice_included_in_wire_params(self):
        sent: list[dict] = []

        async def rpc(method: str, params: dict) -> Any:
            sent.append(params)
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "ok"},
                "model": "m",
            }

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(sampling={"tools": True}),
        )
        tool = ToolSchema(name="f", description="d", inputSchema={})
        await ctx.sample("hello", tools=[tool], tool_choice={"type": "any"})
        assert sent[0]["toolChoice"] == {"type": "any"}

    async def test_no_tools_does_not_check_tools_capability(self):
        sent: list[dict] = []

        async def rpc(method: str, params: dict) -> Any:
            sent.append(params)
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "ok"},
                "model": "m",
            }

        # sampling={} (no tools key) — fine when tools= is not passed
        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(sampling={}),
        )
        result = await ctx.sample("hello")  # no tools= — should not raise
        assert result.text == "ok"
        assert "tools" not in sent[0]

    async def test_max_tool_iterations_in_metadata(self):
        sent: list[dict] = []

        async def rpc(method: str, params: dict) -> Any:
            sent.append(params)
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "ok"},
                "model": "m",
            }

        ctx = McpToolContext(
            tool_name="t",
            _client_rpc=rpc,
            _client_capabilities=ClientCapabilities(sampling={"tools": True}),
        )
        tool = ToolSchema(name="f", description="d", inputSchema={})
        await ctx.sample("hello", tools=[tool], max_tool_iterations=5)
        assert sent[0]["metadata"]["max_tool_iterations"] == 5


class TestCoerceTools:
    def test_dict_passthrough(self):
        raw = {"name": "f", "description": "d", "inputSchema": {}}
        result = _coerce_tools([raw])
        assert result == [raw]

    def test_tool_schema_conversion(self):
        ts = ToolSchema(name="f", description="desc", inputSchema={"type": "object"})
        result = _coerce_tools([ts])
        assert result == [{"name": "f", "description": "desc", "inputSchema": {"type": "object"}}]

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError, match="Unsupported tool descriptor"):
            _coerce_tools([42])

    def test_mcp_tool_meta_duck_type(self):
        class FakeMeta:
            name = "g"
            description = "a tool"
            input_schema = {"type": "object"}

        result = _coerce_tools([FakeMeta()])
        assert result[0]["name"] == "g"
        assert result[0]["inputSchema"] == {"type": "object"}


class TestMcpSamplingLoopError:
    def test_is_runtime_error(self):
        err = McpSamplingLoopError("exceeded 10 iterations")
        assert isinstance(err, RuntimeError)
        assert "exceeded" in str(err)
