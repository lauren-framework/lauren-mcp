"""OAuth 2.0 client-credentials token provider for MCP HTTP clients."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any, Protocol, runtime_checkable

_logger = logging.getLogger(__name__)

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False


@runtime_checkable
class TokenStorage(Protocol):
    """Protocol for token persistence backends."""

    async def get_token(self) -> str | None:
        """Return the current cached token, or ``None`` if absent/expired."""
        ...

    async def set_token(self, token: str, expires_in: int | None = None) -> None:
        """Persist *token*; *expires_in* is seconds from now (``None`` = no expiry)."""
        ...


class InMemoryTokenStorage:
    """Simple in-process token cache with TTL tracking."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float | None = None  # absolute monotonic seconds

    async def get_token(self) -> str | None:
        if self._token is None:
            return None
        if self._expires_at is not None and time.monotonic() >= self._expires_at:
            self._token = None
            self._expires_at = None
            return None
        return self._token

    async def set_token(self, token: str, expires_in: int | None = None) -> None:
        self._token = token
        if expires_in is not None:
            # Subtract a 30-second buffer to refresh before the server rejects it.
            self._expires_at = time.monotonic() + max(expires_in - 30, 1)
        else:
            self._expires_at = None


class ClientCredentialsProvider:
    """``httpx.AsyncAuth``-compatible OAuth 2.0 client-credentials token provider.

    Fetches a bearer token from *token_endpoint* using the
    ``client_credentials`` grant, caches it in *storage*, and automatically
    refreshes it when the cache misses (or is about to expire).  On a ``401``
    response the provider invalidates the cache and retries the request once.

    Usage::

        auth = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/oauth/token",
            client_id="my-service",
            client_secret="s3cr3t",
            scopes=["mcp.read", "mcp.write"],
        )
        client = McpServer.streamable_http("https://api.example.com/mcp", auth=auth)
        await client.connect()

    Parameters
    ----------
    token_endpoint:
        Full URL of the token endpoint.
    client_id:
        OAuth client identifier.
    client_secret:
        OAuth client secret.
    scopes:
        Optional list of scope strings to request.
    storage:
        Token cache backend.  Defaults to :class:`InMemoryTokenStorage`.
    extra_params:
        Additional form fields to include in the token request body
        (e.g. ``{"audience": "https://api.example.com"}`` for Auth0).
    """

    def __init__(
        self,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
        scopes: list[str] | None = None,
        storage: TokenStorage | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> None:
        if not _HTTPX_AVAILABLE:
            raise ImportError(
                "Install lauren-mcp[sse] to use ClientCredentialsProvider: "
                "pip install 'lauren-mcp[sse]'"
            )
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes or []
        self._storage: TokenStorage = storage or InMemoryTokenStorage()
        self._extra_params = extra_params or {}
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a valid bearer token, fetching a new one if necessary."""
        cached = await self._storage.get_token()
        if cached is not None:
            return cached
        async with self._lock:
            # Double-checked locking: another coroutine may have fetched it.
            cached = await self._storage.get_token()
            if cached is not None:
                return cached
            return await self._fetch_token()

    async def _fetch_token(self) -> str:
        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scopes:
            data["scope"] = " ".join(self._scopes)
        data.update(self._extra_params)

        async with httpx.AsyncClient() as client:
            resp = await client.post(self._token_endpoint, data=data)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

        token: str = body["access_token"]
        expires_in: int | None = body.get("expires_in")
        await self._storage.set_token(token, expires_in)
        return token

    # ------------------------------------------------------------------
    # httpx.AsyncAuth interface
    # ------------------------------------------------------------------

    async def async_auth_flow(self, request: Any) -> AsyncGenerator[Any, Any]:
        """Attach a Bearer token; on ``401`` invalidate and retry once."""
        token = await self.get_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        # On 401, flush the cache and retry once with a fresh token.
        if response is not None and response.status_code == 401:
            await self._storage.set_token("", expires_in=0)
            token = await self._fetch_token()
            request.headers["Authorization"] = f"Bearer {token}"
            yield request
