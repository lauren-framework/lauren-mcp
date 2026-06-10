"""Unit tests for client features — version, handlers, roots, server requests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from lauren_mcp import LATEST, Root
from lauren_mcp._client._features import _ClientFeaturesMixin
from lauren_mcp._types import JsonRpcNotification, JsonRpcRequest


class FakeClient(_ClientFeaturesMixin):
    """Minimal client exposing the mixin with a captured _send_raw."""

    def __init__(self, **kwargs: Any) -> None:
        self.sent: list[dict[str, Any]] = []
        self._init_features(**kwargs)

    async def _send_raw(self, obj: dict[str, Any]) -> None:
        self.sent.append(obj)


class TestProtocolVersion:
    def test_default_requested_version_is_latest(self):
        client = FakeClient()
        assert client._requested_protocol_version == LATEST

    def test_explicit_version_respected(self):
        client = FakeClient(protocol_version="2024-11-05")
        assert client._requested_protocol_version == "2024-11-05"

    def test_property_raises_before_connect(self):
        client = FakeClient()
        with pytest.raises(RuntimeError, match="after connect"):
            _ = client.protocol_version

    def test_property_after_negotiation(self):
        client = FakeClient()
        client._negotiated_protocol_version = "2025-03-26"
        assert client.protocol_version == "2025-03-26"


class TestNotificationHandlers:
    def test_progress_routing(self):
        seen: list[dict] = []
        client = FakeClient(progress_handler=seen.append)
        client._route_notification(
            JsonRpcNotification(
                method="notifications/progress",
                params={"progressToken": "t", "progress": 0.5},
            )
        )
        assert seen == [{"progressToken": "t", "progress": 0.5}]

    def test_log_routing(self):
        seen: list[dict] = []
        client = FakeClient(log_handler=seen.append)
        client._route_notification(
            JsonRpcNotification(
                method="notifications/message", params={"level": "info", "data": {}}
            )
        )
        assert seen[0]["level"] == "info"

    def test_list_changed_routing(self):
        seen: list[str] = []
        client = FakeClient(list_changed_handler=seen.append)
        client._route_notification(JsonRpcNotification(method="notifications/tools/list_changed"))
        client._route_notification(
            JsonRpcNotification(method="notifications/resources/list_changed")
        )
        assert seen == ["tools", "resources"]

    def test_dynamic_registration_and_unsubscribe(self):
        client = FakeClient()
        seen: list[dict] = []
        unsubscribe = client.on_progress(seen.append)
        notification = JsonRpcNotification(method="notifications/progress", params={"p": 1})
        client._route_notification(notification)
        unsubscribe()
        client._route_notification(notification)
        assert len(seen) == 1

    def test_unsubscribe_idempotent(self):
        client = FakeClient()
        unsubscribe = client.on_log(lambda p: None)
        unsubscribe()
        unsubscribe()  # must not raise

    def test_handler_error_does_not_propagate(self):
        def boom(params: dict) -> None:
            raise RuntimeError("boom")

        client = FakeClient(progress_handler=boom)
        client._route_notification(
            JsonRpcNotification(method="notifications/progress", params={})
        )  # must not raise

    async def test_async_handler_scheduled(self):
        seen: list[dict] = []

        async def handler(params: dict) -> None:
            seen.append(params)

        client = FakeClient(progress_handler=handler)
        client._route_notification(
            JsonRpcNotification(method="notifications/progress", params={"x": 1})
        )
        await asyncio.sleep(0)
        assert seen == [{"x": 1}]


class TestCapabilities:
    def test_no_features_no_capabilities(self):
        assert FakeClient()._build_client_capabilities() == {}

    def test_static_roots_capability(self):
        client = FakeClient(roots=[Root("file:///workspace")])
        assert client._build_client_capabilities() == {"roots": {"listChanged": False}}

    def test_dynamic_roots_capability(self):
        client = FakeClient(roots=lambda: [Root("file:///x")])
        assert client._build_client_capabilities() == {"roots": {"listChanged": True}}

    def test_sampling_and_elicitation_capabilities(self):
        client = FakeClient(sampling_handler=lambda p: {}, elicitation_handler=lambda p: {})
        caps = client._build_client_capabilities()
        assert caps["sampling"] == {}
        assert caps["elicitation"] == {}


class TestServerRequests:
    async def test_roots_list_request(self):
        client = FakeClient(roots=[Root("file:///ws", name="Workspace")])
        await client._reply_server_request(JsonRpcRequest(method="roots/list", id="srv-1"))
        reply = client.sent[0]
        assert reply["id"] == "srv-1"
        assert reply["result"] == {"roots": [{"uri": "file:///ws", "name": "Workspace"}]}

    async def test_dynamic_roots_resolved(self):
        async def get_roots() -> list[Root]:
            return [Root("file:///dynamic")]

        client = FakeClient(roots=get_roots)
        await client._reply_server_request(JsonRpcRequest(method="roots/list", id=1))
        assert client.sent[0]["result"]["roots"][0]["uri"] == "file:///dynamic"

    async def test_sampling_handler_invoked(self):
        async def sampler(params: dict) -> dict:
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "reply"},
                "model": "test",
            }

        client = FakeClient(sampling_handler=sampler)
        await client._reply_server_request(
            JsonRpcRequest(method="sampling/createMessage", id="srv-2", params={})
        )
        assert client.sent[0]["result"]["content"]["text"] == "reply"

    async def test_unknown_request_gets_method_not_found(self):
        client = FakeClient()
        await client._reply_server_request(
            JsonRpcRequest(method="sampling/createMessage", id=9, params={})
        )
        assert client.sent[0]["error"]["code"] == -32601

    async def test_handler_exception_becomes_error_response(self):
        def bad(params: dict) -> dict:
            raise RuntimeError("nope")

        client = FakeClient(elicitation_handler=bad)
        await client._reply_server_request(
            JsonRpcRequest(method="elicitation/create", id=2, params={})
        )
        assert client.sent[0]["error"]["code"] == -32603

    async def test_ping_handled(self):
        client = FakeClient()
        await client._reply_server_request(JsonRpcRequest(method="ping", id=3))
        assert client.sent[0]["result"] == {}


class TestRootsChanged:
    async def test_notify_roots_changed(self):
        client = FakeClient(roots=lambda: [])
        await client.notify_roots_changed()
        assert client.sent[0]["method"] == "notifications/roots/list_changed"

    async def test_notify_without_roots_raises(self):
        client = FakeClient()
        with pytest.raises(RuntimeError, match="roots"):
            await client.notify_roots_changed()
