"""MCP initialize handshake helpers — version negotiation and result building."""
from __future__ import annotations

from lauren_mcp._types import (
    InitializeParams,
    InitializeResult,
    ServerCapabilities,
    Implementation,
    ClientCapabilities,
)
from lauren_mcp._version import SUPPORTED, LATEST


def negotiate_version(client_version: str) -> str:
    """Return the best mutually-supported protocol version.

    If the client's requested version is in the server's supported set,
    that version is used as-is.  If the client requests a version the
    server does not recognise (e.g. a newer draft), the server falls back
    to :data:`~lauren_mcp._version.LATEST` — the most recent version the
    server is known to handle correctly.
    """
    if client_version in SUPPORTED:
        return client_version
    return LATEST


def build_initialize_result(
    params: InitializeParams,
    server_info: Implementation,
    capabilities: ServerCapabilities,
) -> InitializeResult:
    """Build a fully-populated :class:`InitializeResult` for the given params.

    Negotiates the protocol version, then composes the result that the
    server sends back to the client as the response to ``initialize``.
    """
    version = negotiate_version(params.protocolVersion)
    return InitializeResult(
        protocolVersion=version,
        capabilities=capabilities,
        serverInfo=server_info,
    )
