"""Unit tests for new client-side changes:
- set_logging_level
- subscribe_resource / unsubscribe_resource
- _route_notification for resources/updated
- on_resource_updated
- complete()
- _build_client_capabilities with sampling_tools
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from lauren_mcp._client._base_remote import _McpBaseRemoteClient
from lauren_mcp._client._features import (
    _VALID_LOG_LEVELS,
    _ClientFeaturesMixin,
)
from lauren_mcp._client._protocol import McpClientProtocol
from lauren_mcp._client._stdio import McpStdioClient
from lauren_mcp._types import JsonRpcNotification

# ---------------------------------------------------------------------------
# Concrete subclass for testing _McpBaseRemoteClient
# ---------------------------------------------------------------------------


class _FakeRemoteClient(_McpBaseRemoteClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sent: list[dict] = []

    async def _send_raw(self, obj: dict) -> None:
        self._sent.append(obj)

    async def _start_connection(self) -> None:
        pass

    async def _close_connection(self) -> None:
        pass

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        self._fail_all_pending("closed")


def _make_response(req_id: int, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


def _deliver_response(client: _FakeRemoteClient, req_id: int, result: Any) -> None:
    """Schedule a response delivery as a background task."""

    async def _do():
        await asyncio.sleep(0)
        client._dispatch_message(_make_response(req_id, result))

    asyncio.create_task(_do())


# ---------------------------------------------------------------------------
# Tests: set_logging_level on remote client
# ---------------------------------------------------------------------------


class TestSetLoggingLevelRemote:
    async def test_valid_level_sends_correct_rpc(self):
        client = _FakeRemoteClient()
        _deliver_response(client, 0, {})
        await client.set_logging_level("info")
        sent = client._sent[0]
        assert sent["method"] == "logging/setLevel"
        assert sent["params"] == {"level": "info"}

    @pytest.mark.parametrize("level", sorted(_VALID_LOG_LEVELS))
    async def test_all_valid_levels_accepted(self, level: str):
        client = _FakeRemoteClient()
        _deliver_response(client, 0, {})
        await client.set_logging_level(level)  # must not raise

    async def test_invalid_level_raises_value_error_before_send(self):
        client = _FakeRemoteClient()
        with pytest.raises(ValueError, match="Invalid log level"):
            await client.set_logging_level("verbose")
        # Nothing was sent
        assert client._sent == []

    async def test_invalid_level_does_not_increment_id(self):
        client = _FakeRemoteClient()
        initial_id = client._next_id
        with pytest.raises(ValueError):
            await client.set_logging_level("trace")
        assert client._next_id == initial_id


# ---------------------------------------------------------------------------
# Tests: set_logging_level on stdio client
# ---------------------------------------------------------------------------


class TestSetLoggingLevelStdio:
    async def test_invalid_level_raises_before_send(self):
        # We only need to check validation logic — no subprocess needed.
        client = McpStdioClient(["echo", "test"])
        with pytest.raises(ValueError, match="Invalid log level"):
            await client.set_logging_level("badlevel")

    async def test_valid_log_levels_constant_non_empty(self):
        assert len(_VALID_LOG_LEVELS) > 0
        assert "info" in _VALID_LOG_LEVELS
        assert "error" in _VALID_LOG_LEVELS


# ---------------------------------------------------------------------------
# Tests: subscribe_resource / unsubscribe_resource
# ---------------------------------------------------------------------------


class TestSubscribeResource:
    async def test_subscribe_sends_correct_rpc(self):
        client = _FakeRemoteClient()
        _deliver_response(client, 0, {})
        await client.subscribe_resource("items://42")
        sent = client._sent[0]
        assert sent["method"] == "resources/subscribe"
        assert sent["params"] == {"uri": "items://42"}

    async def test_unsubscribe_sends_correct_rpc(self):
        client = _FakeRemoteClient()
        _deliver_response(client, 0, {})
        await client.unsubscribe_resource("items://42")
        sent = client._sent[0]
        assert sent["method"] == "resources/unsubscribe"
        assert sent["params"] == {"uri": "items://42"}


# ---------------------------------------------------------------------------
# Tests: _route_notification for notifications/resources/updated
# ---------------------------------------------------------------------------


class FakeClient(_ClientFeaturesMixin):
    def __init__(self, **kwargs: Any) -> None:
        self.sent: list[dict[str, Any]] = []
        self._init_features(**kwargs)

    async def _send_raw(self, obj: dict[str, Any]) -> None:
        self.sent.append(obj)


class TestResourceUpdatedRouting:
    def test_route_notification_calls_handler_with_uri(self):
        received: list[str] = []
        client = FakeClient(resource_updated_handler=received.append)
        client._route_notification(
            JsonRpcNotification(
                method="notifications/resources/updated",
                params={"uri": "items://42"},
            )
        )
        assert received == ["items://42"]

    def test_route_notification_missing_uri_sends_empty_string(self):
        received: list[str] = []
        client = FakeClient(resource_updated_handler=received.append)
        client._route_notification(
            JsonRpcNotification(
                method="notifications/resources/updated",
                params={},
            )
        )
        assert received == [""]

    def test_route_notification_no_handler_is_silent(self):
        client = FakeClient()
        # Should not raise even with no handlers registered
        client._route_notification(
            JsonRpcNotification(
                method="notifications/resources/updated",
                params={"uri": "items://99"},
            )
        )

    async def test_async_handler_scheduled(self):
        received: list[str] = []

        async def async_handler(uri: str) -> None:
            received.append(uri)

        client = FakeClient(resource_updated_handler=async_handler)
        client._route_notification(
            JsonRpcNotification(
                method="notifications/resources/updated",
                params={"uri": "items://7"},
            )
        )
        await asyncio.sleep(0)
        assert received == ["items://7"]


# ---------------------------------------------------------------------------
# Tests: on_resource_updated dynamic registration
# ---------------------------------------------------------------------------


class TestOnResourceUpdated:
    def test_register_handler_fires_on_notification(self):
        client = FakeClient()
        received: list[str] = []
        client.on_resource_updated(received.append)
        client._route_notification(
            JsonRpcNotification(
                method="notifications/resources/updated",
                params={"uri": "items://1"},
            )
        )
        assert received == ["items://1"]

    def test_unsubscribe_removes_handler(self):
        client = FakeClient()
        received: list[str] = []
        unsubscribe = client.on_resource_updated(received.append)
        unsubscribe()
        client._route_notification(
            JsonRpcNotification(
                method="notifications/resources/updated",
                params={"uri": "items://1"},
            )
        )
        assert received == []

    def test_unsubscribe_idempotent(self):
        client = FakeClient()
        unsubscribe = client.on_resource_updated(lambda uri: None)
        unsubscribe()
        unsubscribe()  # must not raise

    def test_multiple_handlers_all_called(self):
        client = FakeClient()
        a: list[str] = []
        b: list[str] = []
        client.on_resource_updated(a.append)
        client.on_resource_updated(b.append)
        client._route_notification(
            JsonRpcNotification(
                method="notifications/resources/updated",
                params={"uri": "items://5"},
            )
        )
        assert a == ["items://5"]
        assert b == ["items://5"]


# ---------------------------------------------------------------------------
# Tests: complete()
# ---------------------------------------------------------------------------


class TestComplete:
    async def test_complete_sends_correct_rpc(self):
        client = _FakeRemoteClient()
        ref = {"type": "ref/prompt", "name": "greet"}
        argument = {"name": "nam", "value": "Jo"}
        _deliver_response(client, 0, {"completion": {"values": ["John", "Jones"]}})
        result = await client.complete(ref, argument)
        sent = client._sent[0]
        assert sent["method"] == "completion/complete"
        assert sent["params"] == {"ref": ref, "argument": argument}
        assert result == {"completion": {"values": ["John", "Jones"]}}


# ---------------------------------------------------------------------------
# Tests: _build_client_capabilities with sampling_tools
# ---------------------------------------------------------------------------


class TestSamplingToolsCapability:
    def test_sampling_handler_without_tools_flag_emits_empty_dict(self):
        client = FakeClient(sampling_handler=lambda p: {})
        caps = client._build_client_capabilities()
        assert caps["sampling"] == {}

    def test_sampling_handler_with_tools_flag_emits_tools_true(self):
        client = FakeClient(sampling_handler=lambda p: {}, sampling_tools=True)
        caps = client._build_client_capabilities()
        assert caps["sampling"] == {"tools": True}

    def test_no_sampling_handler_no_sampling_key(self):
        client = FakeClient(sampling_tools=True)  # tools flag without handler
        caps = client._build_client_capabilities()
        assert "sampling" not in caps

    def test_sampling_tools_false_emits_empty_dict(self):
        client = FakeClient(sampling_handler=lambda p: {}, sampling_tools=False)
        caps = client._build_client_capabilities()
        assert caps["sampling"] == {}


# ---------------------------------------------------------------------------
# Tests: McpClientProtocol ABC enforces abstract methods
# ---------------------------------------------------------------------------


class TestProtocolAbstractMethods:
    def test_incomplete_class_missing_new_methods_raises_type_error(self):
        """A class missing any abstract method cannot be instantiated."""

        class _IncompleteClient(McpClientProtocol):
            # Only implements connect and close; missing everything else
            async def connect(self) -> None:
                pass

            async def close(self) -> None:
                pass

        with pytest.raises(TypeError):
            _IncompleteClient()  # type: ignore[abstract]
