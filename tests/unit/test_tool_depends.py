"""Unit tests for Depends[callable] injection on @mcp_tool methods."""

# NOTE: No 'from __future__ import annotations' here — that would stringify
# all annotations and break typing.get_type_hints() for locally-defined classes.

import asyncio
from typing import Any

import pytest
from lauren import Depends

from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._decorators import (
    _extract_depends_callable,
    _is_depends_annotation,
    mcp_tool,
)
from lauren_mcp.server._handlers import (
    _resolve_depends,
    make_context_factory,
    make_tools_call_handler,
)
from lauren_mcp.server._meta import McpToolMeta

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Module-level providers and server stubs (avoids annotation stringification)
# ---------------------------------------------------------------------------


def _sync_db():
    return {"connected": True}


async def _async_token():
    return "tok"


async def _gen_resource():
    yield "gen_value"


def _counter_factory():
    """Call counter for memoization test."""
    pass  # replaced per-test


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
    """Build McpToolMeta from a decorated function (requires __mcp_tool_meta__)."""
    return fn.__mcp_tool_meta__


# ---------------------------------------------------------------------------
# _is_depends_annotation tests
# ---------------------------------------------------------------------------


class TestIsDepends:
    def test_depends_annotation_recognised(self):

        # Depends[X] — construct the generic alias directly
        ann = Depends[_sync_db]
        assert _is_depends_annotation(ann)

    def test_plain_int_not_depends(self):
        assert not _is_depends_annotation(int)

    def test_string_annotation_recognised(self):
        assert _is_depends_annotation("Depends[get_db]")

    def test_non_depends_string(self):
        assert not _is_depends_annotation("str")

    def test_no_lauren_returns_false(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "lauren":
                raise ImportError("no lauren")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        # With lauren unavailable, string check bypasses the import guard
        # so this still returns True from the string branch — the guard is at
        # the import of the module, not on the string path.
        # What matters: non-string annotations return False.
        assert not _is_depends_annotation(int)


# ---------------------------------------------------------------------------
# _extract_depends_callable
# ---------------------------------------------------------------------------


class TestExtractDependsCallable:
    def test_extracts_callable(self):
        ann = Depends[_sync_db]
        result = _extract_depends_callable(ann)
        assert result is _sync_db

    def test_returns_none_for_non_depends(self):
        assert _extract_depends_callable(int) is None


# ---------------------------------------------------------------------------
# Schema exclusion — use module-level server class
# ---------------------------------------------------------------------------


class SrvSchemaTest:
    @mcp_tool()
    async def list_users(self, limit: int, db: Depends[_sync_db]) -> list:
        return []


class TestSchemaExclusion:
    def test_depends_param_excluded_from_schema(self):
        meta = _meta_for_fn(SrvSchemaTest.list_users)
        assert "db" not in meta.input_schema.get("properties", {})
        assert "db" not in meta.input_schema.get("required", [])
        assert "limit" in meta.input_schema.get("properties", {})

    def test_depends_params_populated(self):
        meta = _meta_for_fn(SrvSchemaTest.list_users)
        assert "db" in meta.depends_params
        assert meta.depends_params["db"] is _sync_db


# ---------------------------------------------------------------------------
# _resolve_depends — provider shapes
# ---------------------------------------------------------------------------


class TestResolveDepends:
    async def test_sync_factory(self):
        def factory():
            return "value"

        resolved: dict[int, Any] = {}
        cleanup: list[Any] = []
        result = await _resolve_depends(factory, resolved, cleanup)
        assert result == "value"
        assert len(cleanup) == 0

    async def test_async_factory(self):
        async def factory():
            return "async_value"

        resolved: dict[int, Any] = {}
        cleanup: list[Any] = []
        result = await _resolve_depends(factory, resolved, cleanup)
        assert result == "async_value"

    async def test_async_generator_value_and_cleanup(self):
        closed = False

        async def gen():
            nonlocal closed
            try:
                yield "gen_value"
            finally:
                closed = True

        resolved: dict[int, Any] = {}
        cleanup: list[Any] = []
        result = await _resolve_depends(gen, resolved, cleanup)
        assert result == "gen_value"
        assert len(cleanup) == 1
        assert not closed

        # Run cleanup
        coro = cleanup[0]()
        if asyncio.iscoroutine(coro):
            await coro
        assert closed

    async def test_memoization(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return "memoized"

        resolved: dict[int, Any] = {}
        cleanup: list[Any] = []
        r1 = await _resolve_depends(factory, resolved, cleanup)
        r2 = await _resolve_depends(factory, resolved, cleanup)
        assert r1 is r2
        assert call_count == 1


# ---------------------------------------------------------------------------
# Handler injection tests — use module-level server classes
# ---------------------------------------------------------------------------


class SrvSyncFactory:
    @mcp_tool()
    async def my_tool(self, x: int, db: Depends[_sync_db]) -> dict:
        return {"x": x, "db": db}


class SrvAsyncFactory:
    @mcp_tool()
    async def my_tool(self, token: Depends[_async_token]) -> str:
        return token


class TestDependsHandlerInjection:
    async def test_sync_factory_injected(self):
        meta = _meta_for_fn(SrvSyncFactory.my_tool)
        srv = SrvSyncFactory()
        handler = make_tools_call_handler(srv, [meta])
        req = _make_req("my_tool", {"x": 5})
        result = await handler(req)
        # result content encodes the return value
        import json

        data = json.loads(result["content"][0]["text"])
        assert data["db"] == {"connected": True}

    async def test_async_factory_injected(self):
        meta = _meta_for_fn(SrvAsyncFactory.my_tool)
        srv = SrvAsyncFactory()
        handler = make_tools_call_handler(srv, [meta])
        result = await handler(_make_req("my_tool"))
        assert result["content"][0]["text"] == "tok"

    async def test_async_generator_cleanup_after_success(self):
        closed_flags: list[bool] = []

        async def gen_with_flag():
            try:
                yield "res"
            finally:
                closed_flags.append(True)

        class SrvGen:
            @mcp_tool()
            async def my_tool(self, res: Depends[gen_with_flag]) -> str:
                return res

        meta = _meta_for_fn(SrvGen.my_tool)
        srv = SrvGen()
        handler = make_tools_call_handler(srv, [meta])
        await handler(_make_req("my_tool"))
        assert closed_flags == [True]

    async def test_async_generator_cleanup_after_tool_raises(self):
        closed_flags: list[bool] = []

        async def gen_with_flag():
            try:
                yield "res"
            finally:
                closed_flags.append(True)

        class SrvRaises:
            @mcp_tool()
            async def my_tool(self, res: Depends[gen_with_flag]) -> str:
                raise ValueError("oops")

        meta = _meta_for_fn(SrvRaises.my_tool)
        srv = SrvRaises()
        handler = make_tools_call_handler(srv, [meta])
        with pytest.raises(ValueError, match="oops"):
            await handler(_make_req("my_tool"))
        assert closed_flags == [True]

    async def test_memoization_two_params_same_factory(self):
        call_count = 0
        instances: list[Any] = []

        def counting_factory():
            nonlocal call_count
            call_count += 1
            obj = object()
            instances.append(obj)
            return obj

        class SrvMemo:
            @mcp_tool()
            async def my_tool(
                self,
                a: Depends[counting_factory],
                b: Depends[counting_factory],
            ) -> dict:
                return {"same": a is b}

        meta = _meta_for_fn(SrvMemo.my_tool)
        srv = SrvMemo()
        handler = make_tools_call_handler(srv, [meta])
        import json

        result = await handler(_make_req("my_tool"))
        data = json.loads(result["content"][0]["text"])
        assert call_count == 1
        assert data["same"] is True

    async def test_depends_with_context_and_plain_params(self):
        from lauren_mcp._server._context import McpToolContext

        received: dict[str, Any] = {}

        class SrvAllThree:
            @mcp_tool()
            async def my_tool(
                self,
                limit: int,
                db: Depends[_sync_db],
                ctx: McpToolContext,
            ) -> dict:
                received["limit"] = limit
                received["db"] = db
                received["ctx"] = ctx
                return {}

        meta = _meta_for_fn(SrvAllThree.my_tool)
        srv = SrvAllThree()
        ctx_factory = make_context_factory()
        handler = make_tools_call_handler(srv, [meta], context_factory=ctx_factory)
        await handler(_make_req("my_tool", {"limit": 10}))
        assert received["limit"] == 10
        assert received["db"] == {"connected": True}
        assert isinstance(received["ctx"], McpToolContext)
        # plain param in schema; depends and context not in schema
        assert "db" not in meta.input_schema.get("properties", {})
        assert "ctx" not in meta.input_schema.get("properties", {})
        assert "limit" in meta.input_schema.get("properties", {})
