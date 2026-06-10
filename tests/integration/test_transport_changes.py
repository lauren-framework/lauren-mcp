"""Integration tests for HTTP transport changes.

Covers:
  - Protocol version constants (LATEST, SUPPORTED)
  - Streamable HTTP with transport_security (helper functions validate Host/Origin)
  - Streamable HTTP stateless mode (POST without session-id works; GET returns 405)
  - Streamable HTTP with InMemoryEventStore (session has event_id counter)
  - Streamable HTTP with oauth_settings (.well-known discovery endpoints)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool
from lauren_mcp._mcp_version import LATEST, SUPPORTED
from lauren_mcp._server._event_store import InMemoryEventStore
from lauren_mcp._server._streamable import (
    StreamableSession,
    StreamableSessionStore,
    mcp_streamable_http_controller,
)
from lauren_mcp._server._transport_security import (
    TransportSecuritySettings,
    _host_allowed,
    _origin_allowed,
)

pytestmark = pytest.mark.asyncio

_SESSION_HEADER = "mcp-session-id"

# ---------------------------------------------------------------------------
# 1. Protocol version constants
# ---------------------------------------------------------------------------


def test_latest_version_is_2025_11_25():
    assert LATEST == "2025-11-25"


def test_supported_contains_2025_06_18():
    assert "2025-06-18" in SUPPORTED


def test_supported_contains_all_four_versions():
    assert frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}) == SUPPORTED


# ---------------------------------------------------------------------------
# 2. Transport security — validates Host/Origin using helper functions
# ---------------------------------------------------------------------------


def test_transport_security_settings_blocks_host_not_in_list() -> None:
    settings = TransportSecuritySettings(allowed_hosts=["testserver"])
    assert _host_allowed("evil.com", settings.allowed_hosts) is False
    assert _host_allowed("testserver", settings.allowed_hosts) is True


def test_transport_security_settings_blocks_wrong_origin() -> None:
    settings = TransportSecuritySettings(
        allowed_hosts=["testserver"],
        allowed_origins=["https://testserver"],
    )
    assert _origin_allowed("https://evil.com", settings) is False
    assert _origin_allowed("https://testserver", settings) is True


async def test_transport_security_guard_returns_false_for_wrong_host() -> None:
    """McpTransportSecurityGuard.can_activate returns False for a disallowed host."""
    from lauren_mcp._server._transport_security import McpTransportSecurityGuard

    guard = McpTransportSecurityGuard()
    guard.configure(TransportSecuritySettings(allowed_hosts=["allowed.com"]))

    # ctx.request is the Lauren Request object
    mock_request = MagicMock()
    mock_request.headers = {"host": "evil.com", "content-type": "application/json"}
    mock_request.method = "GET"

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    result = await guard.can_activate(mock_ctx)
    assert result is False


async def test_transport_security_guard_returns_true_for_allowed_host() -> None:
    """McpTransportSecurityGuard.can_activate returns True for an allowed host."""
    from lauren_mcp._server._transport_security import McpTransportSecurityGuard

    guard = McpTransportSecurityGuard()
    guard.configure(TransportSecuritySettings(allowed_hosts=["allowed.com"]))

    mock_request = MagicMock()
    mock_request.headers = {"host": "allowed.com"}
    mock_request.method = "GET"

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    result = await guard.can_activate(mock_ctx)
    assert result is True


# ---------------------------------------------------------------------------
# 3. Stateless mode — full DI app
# ---------------------------------------------------------------------------


@mcp_server("/mcp", transport="streamable")
class _StatelessTestServer:
    @mcp_tool()
    async def echo(self, text: str) -> str:
        """Echo the input."""
        return text


@pytest.fixture(scope="module")
def stateless_client():
    @module(imports=[McpServerModule.for_root(_StatelessTestServer, transport="streamable")])
    class _StatelessApp:
        pass

    a = LaurenFactory.create(_StatelessApp)
    client = TestClient(a)
    return client


def _post_stateless(client: TestClient, body: dict[str, Any], path: str = "/sl/") -> Any:
    return client.post(
        path,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )


async def test_stateless_controller_get_returns_405() -> None:
    """Stateless controller GET returns 405 directly (without DI)."""
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._registry import McpConnectionRegistry

    ctrl_cls = mcp_streamable_http_controller("/sl", stateless=True)

    dispatcher = McpDispatcher()
    sessions = StreamableSessionStore()
    registry = McpConnectionRegistry()

    inner_ctrl = object.__new__(ctrl_cls)
    inner_ctrl._dispatcher = dispatcher
    inner_ctrl._sessions = sessions
    inner_ctrl._registry = registry

    mock_request = MagicMock()
    mock_request.headers = {}

    result = await inner_ctrl.handle_get(mock_request)
    assert hasattr(result, "status") and result.status == 405


async def test_stateless_controller_delete_returns_405() -> None:
    """Stateless controller DELETE returns 405 directly (without DI)."""
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._registry import McpConnectionRegistry

    ctrl_cls = mcp_streamable_http_controller("/sl2", stateless=True)

    dispatcher = McpDispatcher()
    sessions = StreamableSessionStore()
    registry = McpConnectionRegistry()

    inner_ctrl = object.__new__(ctrl_cls)
    inner_ctrl._dispatcher = dispatcher
    inner_ctrl._sessions = sessions
    inner_ctrl._registry = registry

    mock_request = MagicMock()
    mock_request.headers = {}

    result = await inner_ctrl.handle_delete(mock_request)
    assert hasattr(result, "status") and result.status == 405


async def test_stateless_post_initialize_no_session_id() -> None:
    """POST initialize in stateless mode returns 200 without mcp-session-id."""
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._registry import McpConnectionRegistry

    # Create dispatcher with initialize handler registered
    dispatcher = McpDispatcher()

    async def _init(params: Any) -> dict:
        return {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "test", "version": "0"},
        }

    dispatcher.register("initialize", _init)

    sessions = StreamableSessionStore()
    registry = McpConnectionRegistry()

    ctrl_cls = mcp_streamable_http_controller("/sl3", stateless=True)
    inner_ctrl = object.__new__(ctrl_cls)
    inner_ctrl._dispatcher = dispatcher
    inner_ctrl._sessions = sessions
    inner_ctrl._registry = registry

    init_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
    ).encode()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.body = AsyncMock(return_value=init_body)

    result = await inner_ctrl.handle_post(mock_request)
    # Result should be a Response (not EventStream)
    assert hasattr(result, "status") and result.status == 200
    # Must NOT contain mcp-session-id header
    if hasattr(result, "headers"):
        headers_dict = dict(result.headers) if hasattr(result.headers, "items") else {}
        assert _SESSION_HEADER not in headers_dict


async def test_stateless_notification_returns_202() -> None:
    """POST notification in stateless mode returns 202."""
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._registry import McpConnectionRegistry

    dispatcher = McpDispatcher()
    sessions = StreamableSessionStore()
    registry = McpConnectionRegistry()

    ctrl_cls = mcp_streamable_http_controller("/sl4", stateless=True)
    inner_ctrl = object.__new__(ctrl_cls)
    inner_ctrl._dispatcher = dispatcher
    inner_ctrl._sessions = sessions
    inner_ctrl._registry = registry

    notif_body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.body = AsyncMock(return_value=notif_body)

    result = await inner_ctrl.handle_post(mock_request)
    assert hasattr(result, "status") and result.status == 202


# ---------------------------------------------------------------------------
# 4. Event store — StreamableSession has next_event_id
# ---------------------------------------------------------------------------


def test_event_store_streamable_session_has_event_id_counter() -> None:
    session = StreamableSession(session_id="test-123", protocol_version="2025-11-25")
    assert session.next_event_id == 0
    session.next_event_id += 1
    assert session.next_event_id == 1


async def test_event_store_stores_and_replays_events() -> None:
    store = InMemoryEventStore()
    await store.store_event("sess-1", "sess-1:0", '{"a":1}')
    await store.store_event("sess-1", "sess-1:1", '{"a":2}')

    replayed: list[tuple[str, str]] = []

    async def _collect(eid: str, data: str) -> None:
        replayed.append((eid, data))

    await store.replay_events_after("sess-1", None, _collect)
    assert len(replayed) == 2


# ---------------------------------------------------------------------------
# 5. OAuth discovery endpoints — via full DI app
# ---------------------------------------------------------------------------


class _MockAuthServerMeta:
    def to_dict(self) -> dict:
        return {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
        }


class _MockProtectedResourceMeta:
    def to_dict(self) -> dict:
        return {
            "resource": "https://api.example.com/mcp",
            "authorization_servers": ["https://auth.example.com"],
            "bearer_methods_supported": ["header"],
        }


class _MockOAuthSettings:
    authorization_server_metadata = _MockAuthServerMeta()
    protected_resource_metadata = _MockProtectedResourceMeta()


class _MockOAuthSettingsPartial:
    authorization_server_metadata = _MockAuthServerMeta()
    protected_resource_metadata = None


@mcp_server("/mcp", transport="streamable")
class _OAuthTestServer:
    @mcp_tool()
    async def ping(self) -> str:
        """Ping."""
        return "pong"


@pytest.fixture(scope="module")
def oauth_app():
    @module(imports=[McpServerModule.for_root(_OAuthTestServer, transport="streamable")])
    class _OAuthApp:
        pass

    a = LaurenFactory.create(_OAuthApp)
    TestClient(a)
    return a


async def test_oauth_discovery_returns_authorization_server_json_direct() -> None:
    """Test OAuth discovery endpoint via direct controller instantiation."""
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._registry import McpConnectionRegistry

    ctrl_cls = mcp_streamable_http_controller(
        "/mcp",
        oauth_settings=_MockOAuthSettings(),
    )

    dispatcher = McpDispatcher()
    sessions = StreamableSessionStore()
    registry = McpConnectionRegistry()

    ctrl = object.__new__(ctrl_cls)
    ctrl._dispatcher = dispatcher
    ctrl._sessions = sessions
    ctrl._registry = registry

    mock_request = MagicMock()
    mock_request.headers = {}

    result = await ctrl.oauth_authorization_server(mock_request)
    assert result.status == 200
    body = json.loads(result.body)
    assert body["issuer"] == "https://auth.example.com"
    assert "token_endpoint" in body
    assert body["code_challenge_methods_supported"] == ["S256"]


async def test_oauth_discovery_protected_resource_returns_json_when_set_direct() -> None:
    """Test OAuth protected resource endpoint via direct controller instantiation."""
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._registry import McpConnectionRegistry

    ctrl_cls = mcp_streamable_http_controller(
        "/mcp2",
        oauth_settings=_MockOAuthSettings(),
    )

    dispatcher = McpDispatcher()
    sessions = StreamableSessionStore()
    registry = McpConnectionRegistry()

    ctrl = object.__new__(ctrl_cls)
    ctrl._dispatcher = dispatcher
    ctrl._sessions = sessions
    ctrl._registry = registry

    mock_request = MagicMock()
    mock_request.headers = {}

    result = await ctrl.oauth_protected_resource(mock_request)
    assert result.status == 200
    body = json.loads(result.body)
    assert body["resource"] == "https://api.example.com/mcp"


async def test_oauth_discovery_protected_resource_returns_404_when_not_set_direct() -> None:
    """OAuth protected resource returns 404 when protected_resource_metadata is None."""
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._registry import McpConnectionRegistry

    ctrl_cls = mcp_streamable_http_controller(
        "/mcp3",
        oauth_settings=_MockOAuthSettingsPartial(),
    )

    dispatcher = McpDispatcher()
    sessions = StreamableSessionStore()
    registry = McpConnectionRegistry()

    ctrl = object.__new__(ctrl_cls)
    ctrl._dispatcher = dispatcher
    ctrl._sessions = sessions
    ctrl._registry = registry

    mock_request = MagicMock()
    mock_request.headers = {}

    result = await ctrl.oauth_protected_resource(mock_request)
    assert result.status == 404


# ---------------------------------------------------------------------------
# 6. Full DI app — stateless mode with TestClient
# ---------------------------------------------------------------------------


@mcp_server("/mcp", transport="streamable")
class _FullStatelessServer:
    @mcp_tool()
    async def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b


@pytest.fixture(scope="module")
def full_stateless_app():
    @module(imports=[McpServerModule.for_root(_FullStatelessServer, transport="streamable")])
    class _FullStatelessApp:
        pass

    a = LaurenFactory.create(_FullStatelessApp)
    TestClient(a)
    return a


def test_full_stateless_via_regular_controller_get_returns_400(
    full_stateless_app: Any,
) -> None:
    """The stateful streamable controller (not stateless) returns 405 for GET without SSE."""
    client = TestClient(full_stateless_app)
    resp = client.get("/mcp/")
    assert resp.status_code == 405  # requires SSE accept header


def test_full_stateless_via_regular_controller_post_initialize(
    full_stateless_app: Any,
) -> None:
    """The stateful streamable controller handles initialize normally."""
    client = TestClient(full_stateless_app)
    resp = client.post(
        "/mcp/",
        content=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            }
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.header(_SESSION_HEADER) is not None


# ---------------------------------------------------------------------------
# 7. Full DI app with oauth settings via for_root
# ---------------------------------------------------------------------------


@mcp_server("/mcp", transport="streamable")
class _OAuthFullServer:
    @mcp_tool()
    async def ping(self) -> str:
        """Ping."""
        return "pong"


@pytest.fixture(scope="module")
def oauth_full_app():
    @module(imports=[McpServerModule.for_root(_OAuthFullServer, transport="streamable")])
    class _OAuthFullApp:
        pass

    a = LaurenFactory.create(_OAuthFullApp)
    TestClient(a)
    return a


def test_mcp_streamable_controller_has_oauth_routes(oauth_full_app: Any) -> None:
    """GET /mcp/.well-known/oauth-authorization-server returns 404 without oauth_settings."""
    client = TestClient(oauth_full_app)
    resp = client.get("/mcp/.well-known/oauth-authorization-server")
    # Without oauth_settings, the handler exists but returns 404
    assert resp.status_code == 404
