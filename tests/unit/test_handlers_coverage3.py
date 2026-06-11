"""More coverage tests for _handlers.py — targeting remaining uncovered code paths."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lauren_mcp._types import (
    JsonRpcRequest,
    ResourceResult,
    TextContent,
    ToolOutput,
    ToolStream,
)
from lauren_mcp.server._handlers import (
    McpCallHandler,
    _coerce_header_value,
    _coerce_tool_result,
    _resolve_depends,
    _run_pipe_chain,
    _run_tool_exception_handlers,
    make_resources_read_handler,
    make_tools_call_handler,
)
from lauren_mcp.server._meta import (
    HeaderParamSpec,
    McpResourceMeta,
    McpToolMeta,
)


def _req(method: str, params: dict | None = None, req_id: Any = 1) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, params=params, id=req_id)


def _make_tool_meta(name: str, method_name: str, **kwargs: Any) -> McpToolMeta:
    defaults: dict[str, Any] = {
        "description": "test",
        "input_schema": {"type": "object", "properties": {}},
    }
    defaults.update(kwargs)
    return McpToolMeta(name=name, method_name=method_name, **defaults)


def _make_resource_meta(
    uri_template: str, name: str, method_name: str, **kwargs: Any
) -> McpResourceMeta:
    defaults: dict[str, Any] = {
        "description": None,
        "mime_type": None,
    }
    defaults.update(kwargs)
    return McpResourceMeta(
        uri_template=uri_template, name=name, method_name=method_name, **defaults
    )


# ---------------------------------------------------------------------------
# _coerce_header_value — custom type (line 209)
# ---------------------------------------------------------------------------


class TestCoerceHeaderValueCustomType:
    def test_custom_callable_type(self):
        """_coerce_header_value calls T(raw) for unknown types."""

        class MyType:
            def __init__(self, value: str):
                self.value = value

        result = _coerce_header_value("hello", MyType)
        assert isinstance(result, MyType)
        assert result.value == "hello"


# ---------------------------------------------------------------------------
# _resolve_depends — async generator with no yield (StopAsyncIteration)
# ---------------------------------------------------------------------------


class TestResolveDependsStopAsyncIteration:
    async def test_async_generator_no_yield_returns_none(self):
        """Async generator that never yields returns None."""

        async def empty_provider():
            return
            yield  # pragma: no cover

        resolved: dict[int, Any] = {}
        cleanup: list[Any] = []
        result = await _resolve_depends(empty_provider, resolved, cleanup)
        assert result is None


# ---------------------------------------------------------------------------
# _run_pipe_chain — sync pipe that returns a coroutine (line 107)
# ---------------------------------------------------------------------------


class TestRunPipeChainCoroutineResult:
    async def test_sync_pipe_returning_coroutine(self):
        """When a sync function pipe returns a coroutine, it should be awaited."""
        try:
            from lauren.extractors import PipeContext  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")

        async def inner_coro(v: Any) -> Any:
            return v * 3

        # A sync function that returns a coroutine — iscoroutine check triggered
        def sync_pipe_returns_coro(v: Any) -> Any:
            return inner_coro(v)

        result = await _run_pipe_chain("x", 5, [sync_pipe_returns_coro])
        assert result == 15


# ---------------------------------------------------------------------------
# _run_tool_exception_handlers — various paths
# ---------------------------------------------------------------------------


class TestRunToolExceptionHandlers:
    async def test_no_handlers_returns_none(self):
        result = await _run_tool_exception_handlers(ValueError("test"), (), exec_ctx=None)
        assert result is None

    async def test_handler_with_meta_matches_exception(self):
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class MyHandler:
            def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [{"type": "text", "text": "handled"}], "isError": True}

        setattr(MyHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        result = await _run_tool_exception_handlers(ValueError("err"), (MyHandler,), exec_ctx=None)
        assert result is not None
        assert result["isError"] is True

    async def test_handler_returns_none_tries_next(self):
        """Handler returning None causes the next handler to be tried."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class NullHandler:
            def catch(self, exc: Exception, ctx: Any) -> None:
                return None  # type: ignore[return-value]

        class RealHandler:
            def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [{"type": "text", "text": "real"}], "isError": True}

        for cls in (NullHandler, RealHandler):
            setattr(cls, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        result = await _run_tool_exception_handlers(
            ValueError("err"), (NullHandler, RealHandler), exec_ctx=None
        )
        assert result is not None
        assert result["content"][0]["text"] == "real"

    async def test_handler_with_container(self):
        """Handler resolved via DI container."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class ContainerHandler:
            async def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [{"type": "text", "text": "container"}], "isError": True}

        setattr(ContainerHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        container = AsyncMock()
        container.resolve = AsyncMock(return_value=ContainerHandler())

        result = await _run_tool_exception_handlers(
            ValueError("err"),
            (ContainerHandler,),
            exec_ctx=None,
            container=container,
        )
        assert result is not None
        assert "container" in result["content"][0]["text"]

    async def test_handler_with_no_meta_skipped(self):
        """Handler without EXCEPTION_HANDLER_META is skipped."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")

        class NoMetaHandler:
            def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [], "isError": True}

        result = await _run_tool_exception_handlers(
            ValueError("err"), (NoMetaHandler,), exec_ctx=None
        )
        assert result is None

    async def test_exception_type_mismatch_skipped(self):
        """Handler that handles only TypeError is skipped for ValueError."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (TypeError,)  # Only handles TypeError

        class TypeErrHandler:
            def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [], "isError": True}

        setattr(TypeErrHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        result = await _run_tool_exception_handlers(
            ValueError("err"), (TypeErrHandler,), exec_ctx=None
        )
        assert result is None

    async def test_async_handler_is_awaited(self):
        """Async handler.catch() is awaited."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class AsyncHandler:
            async def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [{"type": "text", "text": "async_handled"}], "isError": True}

        setattr(AsyncHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        result = await _run_tool_exception_handlers(
            ValueError("err"), (AsyncHandler,), exec_ctx=None
        )
        assert result["content"][0]["text"] == "async_handled"

    async def test_handler_returns_malformed_dict_skipped(self):
        """Handler returning dict without 'content' key is treated as unhandled."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class BadHandler:
            def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"isError": True}  # Missing "content"!

        setattr(BadHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        result = await _run_tool_exception_handlers(ValueError("err"), (BadHandler,), exec_ctx=None)
        # Malformed dict — treated as unhandled → None
        assert result is None

    async def test_function_form_handler(self):
        """Function-form handler (not a class) is called directly."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        def fn_handler(exc: Exception, ctx: Any) -> dict:
            return {"content": [{"type": "text", "text": "fn_handled"}], "isError": True}

        # Attach meta to the function so it passes the meta check
        setattr(fn_handler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        result = await _run_tool_exception_handlers(ValueError("err"), (fn_handler,), exec_ctx=None)
        assert result is not None
        assert result["content"][0]["text"] == "fn_handled"

    async def test_handler_instantiation_fails_logs_warning(self):
        """Handler class that requires DI arguments is skipped with a warning."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class RequiresDI:
            def __init__(self, required_arg):  # No default → TypeError on construction
                pass

            def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [], "isError": True}

        setattr(RequiresDI, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        # No container provided — bare construction fails → should be skipped
        result = await _run_tool_exception_handlers(ValueError("err"), (RequiresDI,), exec_ctx=None)
        assert result is None


# ---------------------------------------------------------------------------
# make_resources_read_handler — with pipe_chains, state_params
# ---------------------------------------------------------------------------


class FakeResServer:
    async def get_item(self, item_id: str) -> str:
        return f"item:{item_id}"

    async def get_with_state(self, item_id: str, state_val: Any = None) -> str:
        return f"item:{item_id}"


FAKE_RES_SERVER = FakeResServer()


class TestResourceReadHandlerPipeChains:
    async def test_resource_with_pipe_chain(self):
        """Resource with pipe_chains transforms params."""
        try:
            from lauren.extractors import PipeContext  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")

        def upper_pipe(v: Any) -> Any:
            return str(v).upper()

        meta = _make_resource_meta(
            "/items/{item_id}",
            "items",
            "get_item",
            pipe_chains={"item_id": [upper_pipe]},
        )
        handler = make_resources_read_handler(FAKE_RES_SERVER, [meta])
        result = await handler(_req("resources/read", {"uri": "/items/hello"}))
        # The pipe uppercases the item_id
        assert result["contents"][0]["text"] == "item:HELLO"

    async def test_resource_with_state_params(self):
        """Resource with state_params injects state."""

        class MyState:
            data: str = "state"

        meta = _make_resource_meta(
            "/items/{item_id}",
            "items",
            "get_with_state",
            state_params={"state_val": MyState},
        )
        handler = make_resources_read_handler(FAKE_RES_SERVER, [meta])
        result = await handler(_req("resources/read", {"uri": "/items/42"}))
        assert result["contents"][0]["text"] == "item:42"


# ---------------------------------------------------------------------------
# make_tools_call_handler — pipe_chains with ValueError
# ---------------------------------------------------------------------------


class FakePipeServer:
    async def pipe_tool(self, value: int) -> int:
        return value


class TestToolsCallHandlerPipeChains:
    async def test_pipe_chain_transforms_arg(self):
        """Pipe chain is applied to arguments before method call."""
        try:
            from lauren.extractors import PipeContext  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")

        def add_ten(v: Any) -> Any:
            return int(v) + 10

        meta = _make_tool_meta(
            "pipe_tool",
            "pipe_tool",
            pipe_chains={"value": [add_ten]},
        )
        server = FakePipeServer()
        handler = make_tools_call_handler(server, [meta])
        result = await handler(_req("tools/call", {"name": "pipe_tool", "arguments": {"value": 5}}))
        # Method receives 15 (5 + 10) and returns it
        assert "15" in result["content"][0]["text"]

    async def test_pipe_chain_value_error_raises_invalid_params(self):
        """A ValueError from a pipe chain raises McpInvalidParamsError."""
        try:
            from lauren.extractors import PipeContext  # noqa: F401
            from lauren_mcp._server._dispatcher import McpInvalidParamsError
        except ImportError:
            pytest.skip("lauren not installed")

        def failing_pipe(v: Any) -> Any:
            raise ValueError("Invalid value")

        meta = _make_tool_meta(
            "pipe_tool",
            "pipe_tool",
            pipe_chains={"value": [failing_pipe]},
        )
        server = FakePipeServer()
        handler = make_tools_call_handler(server, [meta])
        with pytest.raises(McpInvalidParamsError):
            await handler(_req("tools/call", {"name": "pipe_tool", "arguments": {"value": 5}}))


# ---------------------------------------------------------------------------
# make_resources_read_handler — with depends params
# ---------------------------------------------------------------------------


class FakeResWithDepends:
    async def get_item(self, item_id: str, db: Any = None) -> str:
        return f"item:{item_id}:db={db}"


class TestResourceReadWithDepends:
    async def test_resource_with_depends_param(self):
        """Depends[callable] is resolved and injected into resource method."""

        async def get_db():
            return "db_conn"

        meta = _make_resource_meta(
            "/items/{item_id}",
            "items",
            "get_item",
            depends_params={"db": get_db},
        )
        server = FakeResWithDepends()
        handler = make_resources_read_handler(server, [meta])
        result = await handler(_req("resources/read", {"uri": "/items/42"}))
        assert "db_conn" in result["contents"][0]["text"]


# ---------------------------------------------------------------------------
# make_resources_read_handler — with header_params
# ---------------------------------------------------------------------------


class FakeResWithHeader:
    async def get_item(self, item_id: str, auth: str = "none") -> str:
        return f"item:{item_id}:auth={auth}"


class TestResourceReadWithHeaderParams:
    async def test_resource_with_header_param_missing(self):
        """Header param missing from binding → uses default or None."""
        from lauren_mcp.server._meta import _HEADER_NO_DEFAULT

        meta = _make_resource_meta(
            "/items/{item_id}",
            "items",
            "get_item",
        )
        meta.header_params = {
            "auth": HeaderParamSpec(
                header_name="authorization",
                coerce_to=str,
                default="default_auth",
                is_optional=False,
            )
        }

        server = FakeResWithHeader()
        handler = make_resources_read_handler(server, [meta])
        result = await handler(_req("resources/read", {"uri": "/items/99"}))
        # No binding present, so default value is used
        assert "99" in result["contents"][0]["text"]
        assert "default_auth" in result["contents"][0]["text"]


# ---------------------------------------------------------------------------
# make_tools_call_handler — BackgroundTasks injection
# ---------------------------------------------------------------------------


class FakeBgServer:
    async def bg_tool(self, bg=None) -> str:
        if bg is not None:
            # Queue a background task
            async def task():
                pass

            try:
                bg.add_task(task)
            except Exception:
                pass  # In case add_task is not available
        return "done"


class TestToolsCallHandlerBackgroundTasks:
    async def test_bg_tasks_injected(self):
        """BackgroundTasks param is injected into tool method."""
        try:
            from lauren import BackgroundTasks  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")

        meta = _make_tool_meta("bg_tool", "bg_tool", bg_tasks_param="bg")
        server = FakeBgServer()
        handler = make_tools_call_handler(server, [meta])
        result = await handler(_req("tools/call", {"name": "bg_tool", "arguments": {}}))
        assert result["content"][0]["text"] == "done"


# ---------------------------------------------------------------------------
# make_tools_call_handler — server_metadata merging
# ---------------------------------------------------------------------------


class FakeMetaServer:
    async def tool(self) -> str:
        return "ok"


class TestToolsCallHandlerServerMetadata:
    async def test_server_metadata_used_in_exec_ctx(self):
        """server_metadata is passed to make_tools_call_handler and included in context."""
        from lauren_mcp.server._meta import McpToolMeta

        meta = _make_tool_meta("tool", "tool")
        # Add interceptors to trigger exec_ctx creation
        from unittest.mock import AsyncMock

        class PassThrough:
            async def intercept(self, ctx: Any, handler: Any) -> Any:
                return await handler.handle()

        meta.interceptors = (PassThrough,)

        container = AsyncMock()
        container.resolve = AsyncMock(return_value=PassThrough())

        server = FakeMetaServer()
        handler = make_tools_call_handler(
            server,
            [meta],
            container=container,
            server_metadata={"role": "admin"},
        )
        result = await handler(_req("tools/call", {"name": "tool", "arguments": {}}))
        assert result["content"][0]["text"] == "ok"
