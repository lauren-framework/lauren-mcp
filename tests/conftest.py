"""Shared fixtures for all tests."""

from __future__ import annotations

import pytest

# Echo MCP server script — used by stdio integration tests.
# Responds to initialize, tools/list, tools/call("echo"), ping.
ECHO_MCP_SERVER_SCRIPT = """
import sys, json

def respond(id_, result):
    print(json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}), flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method = msg.get("method")
    id_ = msg.get("id")
    if method == "initialize":
        respond(id_, {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "echo-server", "version": "1.0.0"}
        })
    elif method == "tools/list":
        respond(id_, {"tools": [
            {"name": "echo", "description": "Echo input back.",
             "inputSchema": {"type": "object",
                             "properties": {"text": {"type": "string"}},
                             "required": ["text"]}}
        ]})
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments", {})
        respond(id_, {"content": [{"type": "text", "text": args.get("text", "")}],
                      "isError": False})
    elif method == "ping":
        respond(id_, {})
    elif method == "resources/list":
        respond(id_, {"resources": []})
    elif method == "prompts/list":
        respond(id_, {"prompts": []})
    sys.stdout.flush()
"""


@pytest.fixture(scope="session")
def echo_server_command():
    """Return argv list for the echo MCP server subprocess."""
    import os
    import sys
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(ECHO_MCP_SERVER_SCRIPT)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)
