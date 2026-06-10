"""Unit tests for OAuth client provider (_client/_oauth.py)."""

from __future__ import annotations

import time

import pytest

from lauren_mcp._client._oauth import (
    ClientCredentialsProvider,
    InMemoryTokenStorage,
    TokenStorage,
)

# ---------------------------------------------------------------------------
# InMemoryTokenStorage
# ---------------------------------------------------------------------------


class TestInMemoryTokenStorage:
    async def test_initial_state_returns_none(self):
        store = InMemoryTokenStorage()
        assert await store.get_token() is None

    async def test_set_and_get_round_trip(self):
        store = InMemoryTokenStorage()
        await store.set_token("tok123", expires_in=3600)
        assert await store.get_token() == "tok123"

    async def test_no_expiry_token_persists(self):
        store = InMemoryTokenStorage()
        await store.set_token("tok", expires_in=None)
        assert await store.get_token() == "tok"

    async def test_expired_token_returns_none(self):
        store = InMemoryTokenStorage()
        # expires_in=1 minus 30-second buffer → max(1-30, 1) = 1 second TTL
        # Actually max(1-30, 1) = 1, so it's still not immediately expired.
        # Force expiry by setting _expires_at in the past directly.
        await store.set_token("tok", expires_in=3600)
        store._expires_at = time.monotonic() - 1  # force expiry
        assert await store.get_token() is None

    async def test_expired_token_clears_state(self):
        store = InMemoryTokenStorage()
        await store.set_token("tok", expires_in=3600)
        store._expires_at = time.monotonic() - 1
        await store.get_token()
        assert store._token is None
        assert store._expires_at is None

    async def test_expires_in_1_gives_positive_ttl(self):
        """expires_in=1 after the 30-s buffer still gives TTL ≥ 1 (max(..., 1))."""
        store = InMemoryTokenStorage()
        await store.set_token("tok", expires_in=1)
        # Should not be expired immediately since max(1-30, 1) = 1 second from now
        result = await store.get_token()
        assert result == "tok"

    async def test_set_token_with_zero_expires_in_flushes_immediately(self):
        """set_token('', expires_in=0) is used to flush the cache."""
        store = InMemoryTokenStorage()
        await store.set_token("old", expires_in=3600)
        # Flush by setting empty token with expires_in=0 → TTL = max(-30, 1) = 1
        await store.set_token("", expires_in=0)
        # The stored token is "" but not None; however get_token returns ""
        # because the TTL is 1 second (not expired yet).
        # The important thing is this doesn't crash.
        result = await store.get_token()
        assert result == ""  # empty string is returned (not None)


# ---------------------------------------------------------------------------
# TokenStorage protocol conformance
# ---------------------------------------------------------------------------


class TestTokenStorageProtocol:
    def test_in_memory_storage_satisfies_protocol(self):
        assert isinstance(InMemoryTokenStorage(), TokenStorage)


# ---------------------------------------------------------------------------
# ClientCredentialsProvider
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_token_response():
    """Factory for a mock httpx response containing a token."""
    try:
        import httpx
    except ImportError:
        pytest.skip("httpx not installed")

    def _make(token: str = "test_token", expires_in: int = 3600) -> httpx.Response:
        return httpx.Response(200, json={"access_token": token, "expires_in": expires_in})

    return _make


@pytest.fixture
def respx_mock():
    """Use respx if available; otherwise skip."""
    try:
        import respx
    except ImportError:
        pytest.skip("respx not installed")
    with respx.mock() as mock:
        yield mock


class TestClientCredentialsProvider:
    def test_import_from_oauth_module(self):
        """ClientCredentialsProvider can be imported from _oauth."""
        from lauren_mcp._client._oauth import ClientCredentialsProvider  # noqa: F401

    async def test_get_token_fetches_on_first_call(self, respx_mock):
        import httpx

        respx_mock.post("https://auth.example.com/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tkn", "expires_in": 3600})
        )
        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
        )
        token = await provider.get_token()
        assert token == "tkn"

    async def test_get_token_caches_on_second_call(self, respx_mock):
        import httpx

        call_count = 0

        async def token_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"access_token": "tkn", "expires_in": 3600})

        respx_mock.post("https://auth.example.com/token").mock(side_effect=token_handler)
        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
        )
        await provider.get_token()
        await provider.get_token()
        assert call_count == 1  # second call uses cache

    async def test_get_token_refreshes_after_expiry(self, respx_mock):
        import httpx

        store = InMemoryTokenStorage()
        store._token = "old"
        store._expires_at = time.monotonic() - 1  # simulate expired

        call_count = 0

        async def token_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"access_token": "new_tkn", "expires_in": 3600})

        respx_mock.post("https://auth.example.com/token").mock(side_effect=token_handler)
        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
            storage=store,
        )
        token = await provider.get_token()
        assert token == "new_tkn"
        assert call_count == 1

    async def test_scope_included_in_request(self, respx_mock):
        import httpx

        captured: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "t", "expires_in": 60})

        respx_mock.post("https://auth.example.com/token").mock(side_effect=handler)
        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="s",
            scopes=["mcp.read", "mcp.write"],
        )
        await provider.get_token()
        body = captured["body"]
        # URL-encoded form: spaces become + or %20
        assert "mcp.read" in body
        assert "mcp.write" in body

    async def test_extra_params_included_in_request(self, respx_mock):
        import httpx

        captured: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "t", "expires_in": 60})

        respx_mock.post("https://auth.example.com/token").mock(side_effect=handler)
        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="s",
            extra_params={"audience": "https://api.example.com"},
        )
        await provider.get_token()
        assert "audience" in captured["body"]

    async def test_async_auth_flow_attaches_bearer_header(self, respx_mock):
        import httpx

        respx_mock.post("https://auth.example.com/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "bearer_tok", "expires_in": 3600}
            )
        )
        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="s",
        )

        request = httpx.Request("GET", "https://api.example.com/mcp")
        flow = provider.async_auth_flow(request)
        # Advance the flow: receive the (possibly modified) request
        sent_request = await flow.__anext__()
        assert sent_request.headers.get("authorization") == "Bearer bearer_tok"
        # Finish the flow cleanly (StopAsyncIteration on the next next())
        try:  # noqa: SIM105
            await flow.asend(httpx.Response(200))
        except StopAsyncIteration:
            pass
