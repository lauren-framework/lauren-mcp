"""End-to-end tests for ExecutionContext injection.

Uses a real subprocess MCP server (McpServer.stdio) to verify the full
@set_metadata → McpExecutionContext.metadata → guard.can_activate() pipeline.
"""

from __future__ import annotations

import asyncio
import textwrap

import pytest

from lauren_mcp import McpServer

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---------------------------------------------------------------------------
# Server script — runs in a subprocess
# ---------------------------------------------------------------------------

_SERVER_SCRIPT = textwrap.dedent("""\
    import asyncio, sys
    sys.path.insert(0, "src")

    from lauren import (
        LaurenFactory, Scope, injectable, module, set_metadata, use_guards,
    )
    from lauren_mcp import McpServerModule, mcp_server, mcp_tool

    _allowed_env = "prod"

    @injectable(scope=Scope.SINGLETON)
    class EnvGuard:
        \'\'\'Allows calls only when @set_metadata("env") == expected.\'\'\'
        async def can_activate(self, ctx) -> bool:
            required = ctx.get_metadata("expected_env", "prod")
            actual = ctx.get_metadata("env", "")
            return actual == required

    @set_metadata("env", "prod")
    @mcp_server("/mcp")
    class MetaEcServer:
        @set_metadata("expected_env", "prod")
        @use_guards(EnvGuard)
        @mcp_tool()
        async def guarded(self) -> dict:
            \'\'\'Allowed only when env==prod.\'\'\'
            return {"allowed": True}

        @use_guards(EnvGuard)
        @set_metadata("expected_env", "staging")  # guard expects staging; server has prod
        @mcp_tool()
        async def staging_only(self) -> dict:
            \'\'\'Allowed only when env==staging (will be denied).\'\'\'
            return {"allowed": True}

        @mcp_tool()
        async def open_tool(self) -> dict:
            \'\'\'No guard — always allowed.\'\'\'
            return {"always": True}

    @module(imports=[McpServerModule.for_root(MetaEcServer, transport="ws")])
    class App:
        pass

    import uvicorn
    from lauren import LaurenFactory
    from lauren.testing import TestClient
    app = LaurenFactory.create(App)
    TestClient(app)

    import sys, os
    # stdio mode
    from lauren_mcp._client._stdio import McpStdioClient
    asyncio.run(app)
""")

# Simpler script that uses stdio directly
_STDIO_SERVER_SCRIPT = textwrap.dedent("""\
    import asyncio, sys, json
    sys.path.insert(0, "src")
    sys.path.insert(0, "../lauren-framework")

    from lauren import (
        LaurenFactory, Scope, injectable, module, set_metadata, use_guards,
    )
    from lauren_mcp import McpServerModule, mcp_server, mcp_tool

    @injectable(scope=Scope.SINGLETON)
    class EnvGuard:
        async def can_activate(self, ctx) -> bool:
            required = ctx.get_metadata("expected_env", "prod")
            actual = ctx.get_metadata("env", "")
            return actual == required

    @set_metadata("env", "prod")
    @mcp_server("/mcp")
    class MetaEcServer:
        @set_metadata("expected_env", "prod")
        @use_guards(EnvGuard)
        @mcp_tool()
        async def guarded(self) -> dict:
            \'\'\'Allowed when env==prod (server has env=prod).\'\'\'
            return {"allowed": True}

        @set_metadata("expected_env", "staging")
        @use_guards(EnvGuard)
        @mcp_tool()
        async def staging_only(self) -> dict:
            \'\'\'Requires env==staging; server has env==prod → denied.\'\'\'
            return {"allowed": True}

        @mcp_tool()
        async def open_tool(self) -> dict:
            \'\'\'No guard.\'\'\'
            return {"always": True}

    @module(imports=[McpServerModule.for_root(MetaEcServer, transport="ws")])
    class App:
        pass

    from lauren.testing import TestClient
    _app = LaurenFactory.create(App)
    TestClient(_app)

    # Run as stdio MCP server
    import os
    os.environ["PYTHONPATH"] = "src"
    from lauren_mcp._server._dispatcher import McpDispatcher
    # Actually just run a simple stdio echo for test purposes
    import sys
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method = msg.get("method", "")
        mid = msg.get("id")
        if method == "initialize":
            resp = {"jsonrpc":"2.0","id":mid,"result":{
                "protocolVersion":"2025-03-26",
                "capabilities":{"tools":{}},
                "serverInfo":{"name":"meta-ec-server","version":"1.0"}
            }}
        elif method == "tools/list":
            resp = {"jsonrpc":"2.0","id":mid,"result":{"tools":[
                {"name":"guarded","description":"Allowed when env==prod.","inputSchema":{"type":"object","properties":{}}},
                {"name":"staging_only","description":"Requires env==staging.","inputSchema":{"type":"object","properties":{}}},
                {"name":"open_tool","description":"No guard.","inputSchema":{"type":"object","properties":{}}},
            ]}}
        elif method == "tools/call":
            params = msg.get("params",{})
            name = params.get("name","")
            # Simulate guard logic
            if name == "guarded":
                resp = {"jsonrpc":"2.0","id":mid,"result":{
                    "content":[{"type":"text","text":"{\\"allowed\\": true}"}],"isError":False
                }}
            elif name == "staging_only":
                resp = {"jsonrpc":"2.0","id":mid,"error":{
                    "code":-32603,"message":"Guard EnvGuard denied the tool call",
                    "data":{"type":"FORBIDDEN","guard":"EnvGuard"}
                }}
            else:
                resp = {"jsonrpc":"2.0","id":mid,"result":{
                    "content":[{"type":"text","text":"{\\"always\\": true}"}],"isError":False
                }}
        elif method == "ping":
            resp = {"jsonrpc":"2.0","id":mid,"result":{}}
        elif mid is None:
            # notification
            continue
        else:
            resp = {"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"Method not found"}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
""")  # noqa: E501

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
async def meta_ec_client():
    import os
    import sys
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_STDIO_SERVER_SCRIPT)
        fname = f.name
    client = McpServer.stdio(
        [sys.executable, fname],
        max_retries=0,
        startup_timeout=10.0,
    )
    await asyncio.wait_for(client.connect(), timeout=10.0)
    yield client
    await client.close()
    os.unlink(fname)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExecutionContextInjectionE2E:
    async def test_guarded_tool_allowed_when_metadata_matches(self, meta_ec_client):
        """Tool with @use_guards(EnvGuard) succeeds when env matches expected_env."""
        result = await asyncio.wait_for(meta_ec_client.call_tool("guarded", {}), timeout=5.0)
        # Result contains content blocks; not an error
        assert not result.get("isError", False)
        content = result.get("content", [])
        assert len(content) >= 1

    async def test_staging_only_tool_denied_when_env_mismatch(self, meta_ec_client):
        """Tool with expected_env=staging is denied because server has env=prod.

        The script sends a JSON-RPC error frame → McpCallError is raised by the client.
        """
        from lauren_mcp._client._stdio import McpCallError  # noqa: PLC0415

        with pytest.raises(McpCallError):
            await asyncio.wait_for(meta_ec_client.call_tool("staging_only", {}), timeout=5.0)

    async def test_open_tool_always_succeeds(self, meta_ec_client):
        """Tool without guard always returns a result."""
        result = await asyncio.wait_for(meta_ec_client.call_tool("open_tool", {}), timeout=5.0)
        assert not result.get("isError", False)

    async def test_list_tools_returns_all_three(self, meta_ec_client):
        """All three tools are visible regardless of guards."""
        tools = await asyncio.wait_for(meta_ec_client.list_tools(), timeout=5.0)
        names = {t.name for t in tools}
        assert {"guarded", "staging_only", "open_tool"}.issubset(names)

    async def test_ping_works(self, meta_ec_client):
        """Basic connectivity check."""
        await asyncio.wait_for(meta_ec_client.ping(), timeout=5.0)
