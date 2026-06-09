"""Unit tests for McpDispatcher — instantiated directly, bypassing Lauren DI."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

# McpDispatcher uses @injectable and @post_construct from lauren.
# For unit tests we instantiate it directly and manually call _register_builtins
# so the ping handler is registered without needing the full DI container.
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._types import (
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcErrorResponse,
    McpErrorCode,
)


def make_dispatcher() -> McpDispatcher:
    """Instantiate McpDispatcher and run its post_construct initialiser."""
    d = McpDispatcher()
    d._register_builtins()
    return d


def make_request(method: str, id_=1, params=None) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, id=id_, params=params)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestDispatchMethodNotFound:
    @pytest.mark.asyncio
    async def test_dispatch_method_not_found(self):
        d = make_dispatcher()
        req = make_request("nonexistent_method", id_=1)
        result = await d.dispatch(req)
        assert isinstance(result, JsonRpcErrorResponse)
        assert result.error.code == McpErrorCode.METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_method_not_found_message_contains_method_name(self):
        d = make_dispatcher()
        req = make_request("unknown/method", id_=2)
        result = await d.dispatch(req)
        assert isinstance(result, JsonRpcErrorResponse)
        assert "unknown/method" in result.error.message


class TestDispatchHandlerBehavior:
    @pytest.mark.asyncio
    async def test_registered_handler_called_with_request_params(self):
        d = make_dispatcher()
        received_params = []

        async def my_handler(params):
            received_params.append(params)
            return {}

        d.register("my/method", my_handler)
        await d.dispatch(make_request("my/method", id_=1, params={"key": "val"}))
        assert received_params == [{"key": "val"}]

    @pytest.mark.asyncio
    async def test_handler_return_value_becomes_result(self):
        d = make_dispatcher()

        async def my_handler(params):
            return {"tools": ["tool_a", "tool_b"]}

        d.register("tools/list", my_handler)
        result = await d.dispatch(make_request("tools/list", id_=3))
        assert isinstance(result, JsonRpcResponse)
        assert result.result == {"tools": ["tool_a", "tool_b"]}

    @pytest.mark.asyncio
    async def test_handler_exception_returns_internal_error(self):
        d = make_dispatcher()

        async def bad_handler(params):
            raise RuntimeError("something broke")

        d.register("bad/method", bad_handler)
        result = await d.dispatch(make_request("bad/method", id_=4))
        assert isinstance(result, JsonRpcErrorResponse)
        assert result.error.code == McpErrorCode.INTERNAL_ERROR
        assert "something broke" in result.error.message

    @pytest.mark.asyncio
    async def test_dispatch_handler_receives_exact_request_object_params(self):
        d = make_dispatcher()
        seen = []

        async def handler(params):
            seen.append(params)
            return "ok"

        d.register("echo", handler)
        req = make_request("echo", id_=7, params={"text": "hello"})
        await d.dispatch(req)
        assert seen == [{"text": "hello"}]

    @pytest.mark.asyncio
    async def test_dispatch_with_none_id_works(self):
        d = make_dispatcher()

        async def handler(params):
            return {"done": True}

        d.register("no_id_method", handler)
        req = JsonRpcRequest(method="no_id_method", id=None)
        result = await d.dispatch(req)
        assert isinstance(result, JsonRpcResponse)
        assert result.result == {"done": True}

    @pytest.mark.asyncio
    async def test_register_overwrites_existing_handler(self):
        d = make_dispatcher()

        async def first_handler(params):
            return "first"

        async def second_handler(params):
            return "second"

        d.register("my/method", first_handler)
        d.register("my/method", second_handler)
        result = await d.dispatch(make_request("my/method", id_=5))
        assert result.result == "second"


class TestDispatchInFlight:
    @pytest.mark.asyncio
    async def test_dispatch_tracks_in_flight_task(self):
        d = make_dispatcher()
        started = asyncio.Event()
        unblock = asyncio.Event()

        async def slow_handler(params):
            started.set()
            await unblock.wait()
            return {}

        d.register("slow/op", slow_handler)
        req = make_request("slow/op", id_=10)

        # Start dispatch in background
        task = asyncio.create_task(d.dispatch(req))
        await started.wait()
        # While running, the request id should be in _in_flight
        assert 10 in d._in_flight
        unblock.set()
        await task
        # After completion, should be cleaned up
        assert 10 not in d._in_flight

    @pytest.mark.asyncio
    async def test_dispatch_removes_from_in_flight_after_completion(self):
        d = make_dispatcher()

        async def fast_handler(params):
            return "done"

        d.register("fast/op", fast_handler)
        req = make_request("fast/op", id_=11)
        await d.dispatch(req)
        assert 11 not in d._in_flight


class TestDispatchCancel:
    @pytest.mark.asyncio
    async def test_cancel_returns_true_for_in_flight_request(self):
        d = make_dispatcher()
        started = asyncio.Event()

        async def slow_handler(params):
            started.set()
            await asyncio.sleep(60)

        d.register("slow", slow_handler)
        task = asyncio.create_task(d.dispatch(make_request("slow", id_=20)))
        await started.wait()
        result = d.cancel(20)
        assert result is True
        await task  # let it complete (with cancel)

    @pytest.mark.asyncio
    async def test_cancel_returns_false_for_unknown_id(self):
        d = make_dispatcher()
        result = d.cancel(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_causes_dispatch_to_return_request_cancelled(self):
        d = make_dispatcher()
        started = asyncio.Event()

        async def slow_handler(params):
            started.set()
            await asyncio.sleep(60)

        d.register("slow2", slow_handler)
        dispatch_task = asyncio.create_task(d.dispatch(make_request("slow2", id_=21)))
        await started.wait()
        d.cancel(21)
        result = await dispatch_task
        assert isinstance(result, JsonRpcErrorResponse)
        assert result.error.code == McpErrorCode.REQUEST_CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_task_returns_false(self):
        d = make_dispatcher()

        async def fast_handler(params):
            return {}

        d.register("fast2", fast_handler)
        await d.dispatch(make_request("fast2", id_=22))
        # Already done — cancel should return False
        result = d.cancel(22)
        assert result is False


class TestBuiltinHandlers:
    @pytest.mark.asyncio
    async def test_ping_builtin_returns_empty_dict(self):
        d = make_dispatcher()
        result = await d.dispatch(make_request("ping", id_=30))
        assert isinstance(result, JsonRpcResponse)
        assert result.result == {}

    @pytest.mark.asyncio
    async def test_ping_handler_present_after_construct(self):
        d = make_dispatcher()
        assert "ping" in d._handlers


class TestConcurrentDispatches:
    @pytest.mark.asyncio
    async def test_multiple_concurrent_dispatches_run_independently(self):
        d = make_dispatcher()
        results_order: list[int] = []
        gates = {i: asyncio.Event() for i in range(3)}

        async def make_handler(n: int):
            async def handler(params):
                await gates[n].wait()
                results_order.append(n)
                return n

            return handler

        for i in range(3):
            d.register(f"op_{i}", await make_handler(i))

        tasks = [
            asyncio.create_task(d.dispatch(make_request(f"op_{i}", id_=i + 100)))
            for i in range(3)
        ]

        # Release in reverse order to verify independence
        gates[2].set()
        gates[1].set()
        gates[0].set()

        responses = await asyncio.gather(*tasks)

        assert len(responses) == 3
        for i, resp in enumerate(responses):
            assert isinstance(resp, JsonRpcResponse)
            assert resp.result == i
