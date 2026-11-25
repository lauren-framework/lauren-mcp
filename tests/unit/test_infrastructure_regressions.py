"""Regression tests for shared remote-client lifecycle helpers."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from lauren_mcp._client._base_remote import _McpBaseRemoteClient
from lauren_mcp._client._stdio import McpCallError
from lauren_mcp.server._decorators import mcp_lifespan


class _RemoteClient(_McpBaseRemoteClient):
    """Minimal concrete client for exercising transport-independent behaviour."""

    async def _send_raw(self, obj: dict[str, Any]) -> None:
        return None

    async def _start_connection(self) -> None:
        return None

    async def _close_connection(self) -> None:
        return None


class TestRemotePendingRequests:
    def test_fail_all_pending_clears_registry(self) -> None:
        client = _RemoteClient()
        loop = asyncio.new_event_loop()
        try:
            abandoned = loop.create_future()
            client._pending[1] = abandoned

            client._fail_all_pending("server disconnected")

            assert client._pending == {}
            assert abandoned.cancelled()
        finally:
            loop.close()

    def test_fail_all_pending_sets_exception_for_active_waiter(self) -> None:
        client = _RemoteClient()
        loop = asyncio.new_event_loop()
        try:
            active = loop.create_future()
            active.add_done_callback(lambda _: None)
            client._pending[2] = active

            client._fail_all_pending("server disconnected")

            assert client._pending == {}
            with pytest.raises(McpCallError, match="server disconnected"):
                active.result()
        finally:
            loop.close()

    def test_fail_all_pending_is_safe_for_completed_futures(self) -> None:
        client = _RemoteClient()
        loop = asyncio.new_event_loop()
        try:
            completed = loop.create_future()
            completed.set_result({"ok": True})
            client._pending[3] = completed

            client._fail_all_pending()

            assert completed.result() == {"ok": True}
            assert client._pending == {}
        finally:
            loop.close()


class TestMcpLifespanDecorator:
    def test_rejects_regular_function(self) -> None:
        def invalid_lifespan():
            return None

        with pytest.raises(TypeError, match="async generator"):
            mcp_lifespan(invalid_lifespan)

    def test_marks_async_generator(self) -> None:
        async def lifespan():
            yield {"resource": "ready"}

        decorated = mcp_lifespan(lifespan)

        assert decorated is lifespan
        assert hasattr(decorated, "__mcp_lifespan_meta__") or any(
            key.endswith("lifespan_meta") for key in vars(decorated)
        )
