"""Unit tests for lauren_mcp._server._handshake."""
from __future__ import annotations

import pytest

from lauren_mcp._server._handshake import build_initialize_result, negotiate_version
from lauren_mcp._types import (
    ClientCapabilities,
    Implementation,
    InitializeParams,
    InitializeResult,
    ServerCapabilities,
)
from lauren_mcp._version import LATEST, STABLE, SUPPORTED


# ---------------------------------------------------------------------------
# negotiate_version
# ---------------------------------------------------------------------------


class TestNegotiateVersion:
    def test_returns_client_version_when_in_supported_latest(self):
        """LATEST is in SUPPORTED, so it is echoed back."""
        assert negotiate_version(LATEST) == LATEST

    def test_returns_client_version_when_in_supported_stable(self):
        """STABLE is in SUPPORTED, so it is echoed back."""
        assert negotiate_version(STABLE) == STABLE

    def test_returns_latest_for_unknown_future_version(self):
        """An unknown/future version not in SUPPORTED falls back to LATEST."""
        result = negotiate_version("2099-01-01")
        assert result == LATEST

    def test_returns_latest_for_empty_string(self):
        """An empty string is not in SUPPORTED, so falls back to LATEST."""
        result = negotiate_version("")
        assert result == LATEST

    def test_returns_latest_for_old_draft_version(self):
        """An old version like 2024-01-01 is not in SUPPORTED → LATEST."""
        result = negotiate_version("2024-01-01")
        assert result == LATEST

    def test_returns_latest_for_arbitrary_garbage(self):
        """Garbage input is not in SUPPORTED → LATEST."""
        result = negotiate_version("notaversion")
        assert result == LATEST

    def test_all_supported_versions_are_echoed_back(self):
        """Every member of SUPPORTED should be echoed back unchanged."""
        for version in SUPPORTED:
            assert negotiate_version(version) == version

    def test_version_constants_latest_is_newer_than_stable(self):
        """LATEST > STABLE as date strings (lexicographic ordering)."""
        assert LATEST > STABLE

    def test_supported_has_exactly_two_members(self):
        """SUPPORTED currently tracks exactly 2 protocol versions."""
        assert len(SUPPORTED) == 2

    def test_supported_contains_latest(self):
        assert LATEST in SUPPORTED

    def test_supported_contains_stable(self):
        assert STABLE in SUPPORTED


# ---------------------------------------------------------------------------
# build_initialize_result
# ---------------------------------------------------------------------------


def _make_params(version: str = LATEST) -> InitializeParams:
    return InitializeParams(
        protocolVersion=version,
        capabilities=ClientCapabilities(),
        clientInfo=Implementation(name="test-client", version="0.0.1"),
    )


def _make_server_info() -> Implementation:
    return Implementation(name="test-server", version="1.2.3")


def _make_caps(**kwargs) -> ServerCapabilities:
    return ServerCapabilities(**kwargs)


class TestBuildInitializeResult:
    def test_returns_initialize_result_instance(self):
        params = _make_params()
        result = build_initialize_result(
            params,
            server_info=_make_server_info(),
            capabilities=_make_caps(),
        )
        assert isinstance(result, InitializeResult)

    def test_uses_negotiated_version_not_raw_client_version(self):
        """When client sends an unknown version, result uses LATEST (not the raw input)."""
        params = _make_params(version="9999-99-99")
        result = build_initialize_result(
            params,
            server_info=_make_server_info(),
            capabilities=_make_caps(),
        )
        assert result.protocolVersion == LATEST
        assert result.protocolVersion != "9999-99-99"

    def test_uses_supported_client_version_verbatim(self):
        """When client sends STABLE, result keeps STABLE."""
        params = _make_params(version=STABLE)
        result = build_initialize_result(
            params,
            server_info=_make_server_info(),
            capabilities=_make_caps(),
        )
        assert result.protocolVersion == STABLE

    def test_stores_server_info(self):
        server_info = _make_server_info()
        params = _make_params()
        result = build_initialize_result(params, server_info=server_info, capabilities=_make_caps())
        assert result.serverInfo.name == "test-server"
        assert result.serverInfo.version == "1.2.3"

    def test_stores_capabilities(self):
        caps = ServerCapabilities(tools={"listChanged": True})
        params = _make_params()
        result = build_initialize_result(params, server_info=_make_server_info(), capabilities=caps)
        assert result.capabilities.tools == {"listChanged": True}

    def test_instructions_defaults_to_none(self):
        params = _make_params()
        result = build_initialize_result(params, server_info=_make_server_info(), capabilities=_make_caps())
        assert result.instructions is None

    def test_works_with_minimal_capabilities(self):
        """ServerCapabilities() with all None fields should not raise."""
        params = _make_params()
        result = build_initialize_result(
            params,
            server_info=_make_server_info(),
            capabilities=ServerCapabilities(),
        )
        assert result.capabilities.tools is None
        assert result.capabilities.resources is None
        assert result.capabilities.prompts is None

    def test_protocol_version_is_string(self):
        params = _make_params()
        result = build_initialize_result(params, server_info=_make_server_info(), capabilities=_make_caps())
        assert isinstance(result.protocolVersion, str)

    def test_server_info_name_propagated(self):
        server_info = Implementation(name="my-great-server", version="3.0.0")
        params = _make_params()
        result = build_initialize_result(params, server_info=server_info, capabilities=_make_caps())
        assert result.serverInfo.name == "my-great-server"

    def test_empty_string_client_version_falls_back_to_latest(self):
        params = _make_params(version="")
        result = build_initialize_result(params, server_info=_make_server_info(), capabilities=_make_caps())
        assert result.protocolVersion == LATEST

    def test_full_capabilities_all_fields_preserved(self):
        caps = ServerCapabilities(
            tools={"listChanged": False},
            resources={"listChanged": True},
            prompts={"listChanged": False},
            logging={"level": "debug"},
        )
        params = _make_params()
        result = build_initialize_result(params, server_info=_make_server_info(), capabilities=caps)
        assert result.capabilities.resources == {"listChanged": True}
        assert result.capabilities.logging == {"level": "debug"}

    def test_latest_version_client_gets_latest_back(self):
        params = _make_params(version=LATEST)
        result = build_initialize_result(params, server_info=_make_server_info(), capabilities=_make_caps())
        assert result.protocolVersion == LATEST
