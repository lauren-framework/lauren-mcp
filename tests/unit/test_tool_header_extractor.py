"""Unit tests for Header[T] extractor on @mcp_tool methods."""

# NOTE: No 'from __future__ import annotations' — it would stringify annotations
# and break typing.get_type_hints() for locally-defined classes.

from typing import Any

import pytest
from lauren import Header

from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._decorators import (
    _is_header_annotation,
    _param_to_header_name,
    mcp_tool,
)
from lauren_mcp.server._handlers import _coerce_header_value, make_tools_call_handler
from lauren_mcp.server._meta import McpToolMeta

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_req(name: str, arguments: dict | None = None) -> JsonRpcRequest:
    return JsonRpcRequest(
        jsonrpc="2.0",
        id=1,
        method="tools/call",
        params={"name": name, "arguments": arguments or {}},
    )


def _meta_for_fn(fn: Any) -> McpToolMeta:
    return fn.__mcp_tool_meta__


# ---------------------------------------------------------------------------
# Module-level fake headers helper
# ---------------------------------------------------------------------------


class FakeHeaders:
    """Simple dict-backed headers mock."""

    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def get(self, name: str, default: Any = None) -> Any:
        return self._data.get(name, default)


# ---------------------------------------------------------------------------
# Module-level server stubs
# ---------------------------------------------------------------------------


class SrvUserIdHeader:
    @mcp_tool()
    async def search(self, query: str, x_user_id: Header[str] = "anon") -> list:
        return []


class SrvAuthHeader:
    @mcp_tool()
    async def auth_endpoint(self, authorization: Header[str] = "") -> str:
        return authorization


class SrvTwoHeaders:
    @mcp_tool()
    async def search(
        self,
        query: str,
        user_id: Header[str] = "anon",
        lang: Header[str] = "en",
    ) -> list:
        return []


class SrvIntHeader:
    @mcp_tool()
    async def my_tool(self, x_count: Header[int] = 0) -> int:
        return x_count


class SrvOptionalHeader:
    @mcp_tool()
    async def my_tool(self, token: Header[str] | None = None) -> str:
        return str(token)


class SrvDefaultHeader:
    @mcp_tool()
    async def my_tool(self, user_id: Header[str] = "guest") -> str:
        return user_id


class SrvLangHeader:
    @mcp_tool()
    async def my_tool(self, lang: Header[str] = "en") -> str:
        return lang


# ---------------------------------------------------------------------------
# _is_header_annotation
# ---------------------------------------------------------------------------


class TestIsHeaderAnnotation:
    def test_header_str_recognised(self):
        # Construct the generic alias directly
        ann = Header[str]
        assert _is_header_annotation(ann)

    def test_optional_header_recognised(self):
        ann = Header[str] | None
        assert _is_header_annotation(ann)

    def test_plain_str_not_header(self):
        assert not _is_header_annotation(str)

    def test_no_lauren_returns_false(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "lauren":
                raise ImportError("no lauren")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        assert not _is_header_annotation(int)


# ---------------------------------------------------------------------------
# _param_to_header_name
# ---------------------------------------------------------------------------


class TestParamToHeaderName:
    def test_simple_name_unchanged(self):
        assert _param_to_header_name("authorization") == "authorization"

    def test_underscore_converted(self):
        assert _param_to_header_name("x_user_id") == "x-user-id"

    def test_multiple_underscores(self):
        assert _param_to_header_name("x_forwarded_for") == "x-forwarded-for"


# ---------------------------------------------------------------------------
# _coerce_header_value
# ---------------------------------------------------------------------------


class TestCoerceHeaderValue:
    def test_str_passthrough(self):
        assert _coerce_header_value("hello", str) == "hello"

    def test_int_coercion(self):
        assert _coerce_header_value("42", int) == 42
        assert isinstance(_coerce_header_value("42", int), int)

    def test_float_coercion(self):
        assert _coerce_header_value("3.14", float) == pytest.approx(3.14)

    def test_bool_true_values(self):
        for val in ("true", "True", "1", "yes", "on"):
            assert _coerce_header_value(val, bool) is True, f"Expected True for {val!r}"

    def test_bool_false_values(self):
        for val in ("false", "False", "0", "no", ""):
            assert _coerce_header_value(val, bool) is False, f"Expected False for {val!r}"


# ---------------------------------------------------------------------------
# Schema exclusion
# ---------------------------------------------------------------------------


class TestHeaderSchemaExclusion:
    def test_header_param_excluded_from_schema(self):
        meta = _meta_for_fn(SrvUserIdHeader.search)
        assert "x_user_id" not in meta.input_schema.get("properties", {})
        assert "query" in meta.input_schema.get("properties", {})

    def test_header_param_name_to_header_name(self):
        meta = _meta_for_fn(SrvUserIdHeader.search)
        assert "x_user_id" in meta.header_params
        assert meta.header_params["x_user_id"].header_name == "x-user-id"

    def test_authorization_header_name(self):
        meta = _meta_for_fn(SrvAuthHeader.auth_endpoint)
        assert meta.header_params["authorization"].header_name == "authorization"

    def test_two_header_params_one_plain(self):
        meta = _meta_for_fn(SrvTwoHeaders.search)
        props = meta.input_schema.get("properties", {})
        assert "query" in props
        assert "user_id" not in props
        assert "lang" not in props


# ---------------------------------------------------------------------------
# Injection via handler
# ---------------------------------------------------------------------------


class SrvInjectHeader:
    @mcp_tool()
    async def my_tool(self, x_user_id: Header[str] = "anon") -> str:
        return x_user_id


class TestHeaderInjection:
    async def test_header_injected_from_binding(self):
        from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding

        meta = _meta_for_fn(SrvInjectHeader.my_tool)
        srv = SrvInjectHeader()
        handler = make_tools_call_handler(srv, [meta])

        token = CURRENT_BINDING.set(TransportBinding(headers=FakeHeaders({"x-user-id": "alice"})))
        try:
            result = await handler(_make_req("my_tool"))
        finally:
            CURRENT_BINDING.reset(token)

        assert result["content"][0]["text"] == "alice"

    async def test_missing_header_uses_default(self):
        meta = _meta_for_fn(SrvDefaultHeader.my_tool)
        srv = SrvDefaultHeader()
        handler = make_tools_call_handler(srv, [meta])
        # No binding set — header absent
        result = await handler(_make_req("my_tool"))
        assert result["content"][0]["text"] == "guest"

    async def test_optional_header_absent_gives_none(self):
        meta = _meta_for_fn(SrvOptionalHeader.my_tool)
        srv = SrvOptionalHeader()
        handler = make_tools_call_handler(srv, [meta])
        result = await handler(_make_req("my_tool"))
        assert result["content"][0]["text"] == "None"

    async def test_header_int_coercion(self):
        from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding

        meta = _meta_for_fn(SrvIntHeader.my_tool)
        srv = SrvIntHeader()
        handler = make_tools_call_handler(srv, [meta])

        token = CURRENT_BINDING.set(TransportBinding(headers=FakeHeaders({"x-count": "42"})))
        try:
            result = await handler(_make_req("my_tool"))
        finally:
            CURRENT_BINDING.reset(token)

        # The return value is int 42, rendered as JSON number
        import json

        text = result["content"][0]["text"]
        assert json.loads(text) == 42

    async def test_no_binding_uses_default(self):
        """When CURRENT_BINDING is None (stdio path), default is used."""
        from lauren_mcp._server._binding import CURRENT_BINDING

        meta = _meta_for_fn(SrvLangHeader.my_tool)
        srv = SrvLangHeader()
        handler = make_tools_call_handler(srv, [meta])

        # Ensure binding is None
        token = CURRENT_BINDING.set(None)
        try:
            result = await handler(_make_req("my_tool"))
        finally:
            CURRENT_BINDING.reset(token)

        assert result["content"][0]["text"] == "en"
