"""Unit tests for Phase 4 per-tool exception handlers.

Covers:
- _run_tool_exception_handlers core logic (T-U01 through T-U08)
- McpToolMeta.exception_handlers field (T-U09 through T-U11)
- Integration with make_tools_call_handler (T-U12 through T-U16)

Note: In unit tests we bypass McpServerModule.for_root(), which normally populates
meta.exception_handlers from the fully-decorated method at startup. Here we set
exception_handlers directly on the meta (simulating what for_root() would do).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from lauren import exception_handler, use_exception_handlers
from lauren.decorators import USE_EXCEPTION_HANDLERS

from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._decorators import mcp_tool
from lauren_mcp.server._handlers import (
    _run_tool_exception_handlers,
    _tool_list_entry,
    make_tools_call_handler,
)
from lauren_mcp.server._meta import MCP_TOOL_META

pytestmark = pytest.mark.asyncio


def _apply_exception_handlers(cls: type) -> None:
    """Simulate what McpServerModule.for_root() does: read USE_EXCEPTION_HANDLERS
    from each decorated method and store them on the McpToolMeta object.

    In production, for_root() does this after all class-level decorators are applied.
    In unit tests, we call this helper manually.
    """
    for attr_name in dir(cls):
        try:
            attr = getattr(cls, attr_name)
        except AttributeError:
            continue
        tool_meta = getattr(attr, MCP_TOOL_META, None)
        if tool_meta is not None:
            exc_handlers = tuple(getattr(attr, USE_EXCEPTION_HANDLERS, ()))
            if exc_handlers:
                tool_meta.exception_handlers = exc_handlers


# ---------------------------------------------------------------------------
# Test group 1: _run_tool_exception_handlers core logic
# ---------------------------------------------------------------------------


async def test_matching_handler_returns_result_dict():
    """T-U01: Handler matches exception type → returns result dict."""

    @exception_handler(ValueError)
    class VEHandler:
        async def catch(self, exc, ctx):
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}

    exc = ValueError("bad")
    ctx = SimpleNamespace(tool_name="test", metadata={})
    result = await _run_tool_exception_handlers(exc, (VEHandler,), ctx)
    assert result == {"content": [{"type": "text", "text": "bad"}], "isError": True}


async def test_handler_returning_none_tries_next():
    """T-U02: Handler returns None → next handler tried."""

    @exception_handler(ValueError)
    class H1:
        async def catch(self, exc, ctx):
            return None  # skip

    @exception_handler(Exception)
    class H2:
        async def catch(self, exc, ctx):
            return {"content": [{"type": "text", "text": "H2 caught"}], "isError": True}

    result = await _run_tool_exception_handlers(ValueError("x"), (H1, H2), SimpleNamespace())
    assert result is not None
    assert result["content"][0]["text"] == "H2 caught"


async def test_no_matching_handler_returns_none():
    """T-U03: No handler matches → returns None."""

    @exception_handler(ValueError)
    class VEHandler:
        async def catch(self, exc, ctx):
            return {"content": [], "isError": True}

    result = await _run_tool_exception_handlers(
        TypeError("bad type"), (VEHandler,), SimpleNamespace()
    )
    assert result is None


async def test_handler_reraise_propagates():
    """T-U04: Handler re-raises → exception propagates."""

    @exception_handler(Exception)
    class RaisingHandler:
        async def catch(self, exc, ctx):
            raise exc

    with pytest.raises(RuntimeError):
        await _run_tool_exception_handlers(
            RuntimeError("oops"), (RaisingHandler,), SimpleNamespace()
        )


async def test_first_match_wins():
    """T-U05: Two handlers, first matches → second never called."""
    calls: list[str] = []

    @exception_handler(ValueError)
    class H1:
        async def catch(self, exc, ctx):
            calls.append("H1")
            return {"content": [], "isError": True}

    @exception_handler(Exception)
    class H2:
        async def catch(self, exc, ctx):
            calls.append("H2")
            return {"content": [], "isError": True}

    await _run_tool_exception_handlers(ValueError("x"), (H1, H2), SimpleNamespace())
    assert calls == ["H1"]


async def test_exception_in_handler_propagates():
    """T-U06: Exception in handler itself propagates as-is (not swallowed)."""

    @exception_handler(Exception)
    class BrokenHandler:
        async def catch(self, exc, ctx):
            raise RuntimeError("handler bug")

    with pytest.raises(RuntimeError, match="handler bug"):
        await _run_tool_exception_handlers(ValueError("input"), (BrokenHandler,), SimpleNamespace())


async def test_sync_catch_method():
    """T-U07: Sync catch method is supported."""

    @exception_handler(ValueError)
    class SyncHandler:
        def catch(self, exc, ctx):
            return {"content": [{"type": "text", "text": "sync"}], "isError": True}

    result = await _run_tool_exception_handlers(ValueError("x"), (SyncHandler,), SimpleNamespace())
    assert result is not None
    assert result["content"][0]["text"] == "sync"


async def test_empty_handlers_returns_none():
    """T-U08: Empty handlers tuple → returns None immediately."""
    result = await _run_tool_exception_handlers(ValueError("x"), (), SimpleNamespace())
    assert result is None


# ---------------------------------------------------------------------------
# Test group 2: McpToolMeta.exception_handlers field
# ---------------------------------------------------------------------------


def test_exception_handlers_stored_in_meta():
    """T-U09: @use_exception_handlers on @mcp_tool stores handlers in meta
    after _apply_exception_handlers (simulating for_root() behavior)."""

    @exception_handler(ValueError)
    class VEHandler:
        async def catch(self, exc, ctx): ...

    class Server:
        @use_exception_handlers(VEHandler)
        @mcp_tool()
        async def my_tool(self) -> dict: ...

    _apply_exception_handlers(Server)
    meta = getattr(Server.my_tool, MCP_TOOL_META)
    assert VEHandler in meta.exception_handlers


def test_no_exception_handlers_empty_tuple():
    """T-U10: No @use_exception_handlers → meta.exception_handlers is empty tuple."""

    class Server:
        @mcp_tool()
        async def my_tool(self) -> dict: ...

    meta = getattr(Server.my_tool, MCP_TOOL_META)
    assert meta.exception_handlers == ()


def test_multiple_use_exception_handlers_accumulate():
    """T-U11: Multiple @use_exception_handlers accumulate in order."""

    @exception_handler(ValueError)
    class H1:
        async def catch(self, exc, ctx): ...

    @exception_handler(TypeError)
    class H2:
        async def catch(self, exc, ctx): ...

    class Server:
        @use_exception_handlers(H2)
        @use_exception_handlers(H1)
        @mcp_tool()
        async def my_tool(self) -> dict: ...

    _apply_exception_handlers(Server)
    meta = getattr(Server.my_tool, MCP_TOOL_META)
    assert list(meta.exception_handlers) == [H1, H2]


# ---------------------------------------------------------------------------
# Test group 3: Integration with make_tools_call_handler
# ---------------------------------------------------------------------------


async def test_handler_called_on_matching_exception():
    """T-U12: Handler called when method raises matching exception."""

    @exception_handler(ValueError)
    class VEHandler:
        async def catch(self, exc, ctx):
            return {"content": [{"type": "text", "text": f"caught: {exc}"}], "isError": True}

    class Server:
        @use_exception_handlers(VEHandler)
        @mcp_tool()
        async def bad_tool(self) -> dict:
            raise ValueError("intentional")

    _apply_exception_handlers(Server)
    server = Server()
    tool_meta = getattr(Server.bad_tool, MCP_TOOL_META)
    handler = make_tools_call_handler(server, [tool_meta])
    req = JsonRpcRequest(method="tools/call", id=1, params={"name": "bad_tool", "arguments": {}})
    result = await handler(req)
    assert result["isError"] is True
    assert "caught: intentional" in result["content"][0]["text"]


async def test_unmatched_exception_propagates():
    """T-U13: No handler for exception → exception propagates."""

    @exception_handler(ValueError)
    class VEHandler:
        async def catch(self, exc, ctx):
            return {"content": [], "isError": True}

    class Server:
        @use_exception_handlers(VEHandler)
        @mcp_tool()
        async def bad_tool(self) -> dict:
            raise TypeError("wrong type")

    _apply_exception_handlers(Server)
    server = Server()
    tool_meta = getattr(Server.bad_tool, MCP_TOOL_META)
    handler = make_tools_call_handler(server, [tool_meta])
    req = JsonRpcRequest(method="tools/call", id=1, params={"name": "bad_tool", "arguments": {}})
    with pytest.raises(TypeError, match="wrong type"):
        await handler(req)


async def test_handler_not_called_on_success():
    """T-U15: Tool succeeds → handler never called."""
    calls: list[Exception] = []

    @exception_handler(Exception)
    class CatchAll:
        async def catch(self, exc, ctx):
            calls.append(exc)
            return {"content": [], "isError": True}

    class Server:
        @use_exception_handlers(CatchAll)
        @mcp_tool()
        async def good_tool(self) -> dict:
            return {"status": "ok"}

    _apply_exception_handlers(Server)
    server = Server()
    tool_meta = getattr(Server.good_tool, MCP_TOOL_META)
    handler = make_tools_call_handler(server, [tool_meta])
    req = JsonRpcRequest(method="tools/call", id=1, params={"name": "good_tool", "arguments": {}})
    result = await handler(req)
    assert result["isError"] is False
    assert calls == []


def test_tools_list_excludes_exception_handlers():
    """T-U16: tools/list entry has no trace of exception_handlers."""

    @exception_handler(ValueError)
    class VEHandler:
        async def catch(self, exc, ctx): ...

    class Server:
        @use_exception_handlers(VEHandler)
        @mcp_tool(description="A tool")
        async def my_tool(self, x: int) -> dict: ...

    _apply_exception_handlers(Server)
    meta = getattr(Server.my_tool, MCP_TOOL_META)
    entry = _tool_list_entry(meta)
    assert "exception_handlers" not in entry
    assert "exceptionHandlers" not in entry
    assert "VEHandler" not in str(entry)


async def test_multiple_tools_correct_routing():
    """Two tools each with different handlers — correct routing."""

    @exception_handler(ValueError)
    class VEHandler:
        async def catch(self, exc, ctx):
            return {"content": [{"type": "text", "text": f"VE: {exc}"}], "isError": True}

    @exception_handler(PermissionError)
    class PEHandler:
        async def catch(self, exc, ctx):
            return {"content": [{"type": "text", "text": "PE caught"}], "isError": True}

    class Server:
        @use_exception_handlers(VEHandler)
        @mcp_tool()
        async def value_tool(self) -> dict:
            raise ValueError("bad value")

        @use_exception_handlers(PEHandler)
        @mcp_tool()
        async def perm_tool(self) -> dict:
            raise PermissionError("no access")

    _apply_exception_handlers(Server)
    server = Server()
    value_meta = getattr(Server.value_tool, MCP_TOOL_META)
    perm_meta = getattr(Server.perm_tool, MCP_TOOL_META)
    handler = make_tools_call_handler(server, [value_meta, perm_meta])

    req_ve = JsonRpcRequest(
        method="tools/call", id=1, params={"name": "value_tool", "arguments": {}}
    )
    req_pe = JsonRpcRequest(
        method="tools/call", id=2, params={"name": "perm_tool", "arguments": {}}
    )

    result_ve = await handler(req_ve)
    assert result_ve["isError"] is True
    assert "VE:" in result_ve["content"][0]["text"]

    result_pe = await handler(req_pe)
    assert result_pe["isError"] is True
    assert result_pe["content"][0]["text"] == "PE caught"


async def test_handler_chain_priority_by_type():
    """Two handlers: more-specific exception type wins when listed first."""

    @exception_handler(ValueError)
    class Specific:
        async def catch(self, exc, ctx):
            return {"content": [{"type": "text", "text": "specific"}], "isError": True}

    @exception_handler(Exception)
    class Fallback:
        async def catch(self, exc, ctx):
            return {"content": [{"type": "text", "text": "fallback"}], "isError": True}

    class Server:
        @use_exception_handlers(Fallback)
        @use_exception_handlers(Specific)
        @mcp_tool()
        async def my_tool(self) -> dict:
            raise ValueError("oops")

    _apply_exception_handlers(Server)
    server = Server()
    meta = getattr(Server.my_tool, MCP_TOOL_META)
    handler = make_tools_call_handler(server, [meta])
    req = JsonRpcRequest(method="tools/call", id=1, params={"name": "my_tool", "arguments": {}})
    result = await handler(req)
    assert result["content"][0]["text"] == "specific"


async def test_no_exception_handlers_exception_propagates():
    """Tool with no handlers — exceptions propagate normally."""

    class Server:
        @mcp_tool()
        async def crashing_tool(self) -> dict:
            raise RuntimeError("crash")

    server = Server()
    meta = getattr(Server.crashing_tool, MCP_TOOL_META)
    handler = make_tools_call_handler(server, [meta])
    req = JsonRpcRequest(
        method="tools/call", id=1, params={"name": "crashing_tool", "arguments": {}}
    )
    with pytest.raises(RuntimeError, match="crash"):
        await handler(req)
