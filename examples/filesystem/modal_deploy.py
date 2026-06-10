"""
Deploy the Filesystem MCP server on Modal with a persistent Volume.

The server exposes full CRUD filesystem operations over the MCP protocol.
All files are stored in a Modal Volume — shared persistent storage that
survives container restarts and scales across replicas.

Quick start
-----------
    pip install modal
    modal setup                      # authenticate once

    # Serve locally (hot-reload, no deploy)
    modal serve examples/filesystem/modal_deploy.py

    # Deploy to production
    modal deploy examples/filesystem/modal_deploy.py

    # Connect from Python
    from lauren_mcp import McpServer
    client = McpServer.streamable_http("https://<your-app>.modal.run/mcp/")
    await client.connect()
    await client.call_tool("write_file", {"path": "hello.txt", "content": "hi"})

    # Or use the lmcp CLI
    lmcp inspect --url https://<your-app>.modal.run/mcp/

    # Tool discovery — open in a browser or fetch with curl
    curl https://<your-app>.modal.run/tools.json

Tool discovery
--------------
Once deployed, agents discover available tools automatically via MCP's
``tools/list`` on connect.  Three additional ways to explore the API:

* ``GET /``           — human-readable HTML page listing all tools
* ``GET /tools.json`` — machine-readable JSON catalogue (no MCP client needed)
* ``lmcp inspect``   — CLI tool that prints tools/resources/prompts

Claude Desktop integration
--------------------------
Add to ``~/Library/Application Support/Claude/claude_desktop_config.json``:

    {
      "mcpServers": {
        "filesystem": {
          "command": "uvx",
          "args": ["mcp-remote", "https://<your-app>.modal.run/mcp/"]
        }
      }
    }

Volume durability
-----------------
Modal Volumes use a network filesystem.  Writes are immediately visible
within the same container instance.  To guarantee visibility across freshly
started containers (e.g. after a cold start), call ``commit_volume()``:

    modal run examples/filesystem/modal_deploy.py::commit_volume

Authentication
--------------
By default the endpoint is public.  To restrict access, add an auth guard
to the server class or set the MCP_REQUIRE_TOKEN env var below and attach
a Modal Secret containing your bearer token.

    modal secret create mcp-auth MCP_REQUIRE_TOKEN=my-secret-token
    # then uncomment secrets=[modal.Secret.from_name("mcp-auth")] below
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import modal

# ---------------------------------------------------------------------------
# Configuration — tweak these as needed
# ---------------------------------------------------------------------------

APP_NAME = "lauren-mcp-filesystem"  # Modal app name (appears in your dashboard)
VOLUME_NAME = "mcp-filesystem-data"  # persistent volume name
VOLUME_MOUNT = "/mnt/mcp-fs"  # mount point inside each container

# ---------------------------------------------------------------------------
# Modal resources
# ---------------------------------------------------------------------------

app = modal.App(APP_NAME)

# Persistent Volume — created on first deploy, shared by all replicas.
# modal.Volume.from_name() references or creates the volume by name.
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

# Container image: Python 3.12 + lauren-mcp + server module.
# add_local_file copies server.py into the image at build time so it is
# available in every container without a network round-trip.
_server_src = Path(__file__).parent / "server.py"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "lauren-mcp[all]",  # core + all transport extras
    )
    .add_local_file(str(_server_src), "/app/server.py")
)

# ---------------------------------------------------------------------------
# ASGI endpoint — serves Streamable HTTP (MCP 2025-03-26) + WebSocket
# ---------------------------------------------------------------------------


@app.function(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    # Allow many concurrent MCP connections per container.
    allow_concurrent_inputs=100,
    # Keep one warm instance to avoid cold-start latency for interactive use.
    keep_warm=1,
    # Uncomment to add auth:
    # secrets=[modal.Secret.from_name("mcp-auth")],
)
@modal.asgi_app()
def serve() -> Any:
    """Return the Lauren ASGI app for Modal to serve, with a discovery root.

    The function body runs once when the container initialises.
    Setting MCP_FS_ROOT before importing server.py ensures the
    lifespan hook creates/validates the correct sandbox directory.

    An agent discovers tools via MCP's ``tools/list`` once connected.
    A Lauren ``@controller`` also serves ``GET /`` (HTML) and
    ``GET /tools.json`` (JSON) so the server self-describes without
    requiring a full MCP connection.
    """
    # Make the bundled server module importable.
    sys.path.insert(0, "/app")

    # Set before importing — server.py reads MCP_FS_ROOT at import time.
    os.environ["MCP_FS_ROOT"] = VOLUME_MOUNT

    # Optionally reject connections without a bearer token.
    token = os.environ.get("MCP_REQUIRE_TOKEN")
    if token:
        os.environ.setdefault("MCP_AUTH_TOKEN", token)

    from lauren import LaurenFactory, controller, get, module  # noqa: PLC0415
    from lauren.types import Headers, Response  # noqa: PLC0415
    from server import FilesystemServer, McpFilesystemGuard  # noqa: PLC0415

    from lauren_mcp import McpServerModule  # noqa: PLC0415
    from lauren_mcp.server._meta import (  # noqa: PLC0415
        MCP_PROMPT_META,
        MCP_RESOURCE_META,
        MCP_TOOL_META,
    )

    # ------------------------------------------------------------------
    # Tool catalogue — built once at container startup from MCP metadata.
    # ------------------------------------------------------------------
    _tools, _resources, _prompts = [], [], []
    for _attr in dir(FilesystemServer):
        _obj = getattr(FilesystemServer, _attr, None)
        if _obj is None:
            continue
        if tm := getattr(_obj, MCP_TOOL_META, None):
            _tools.append(
                {
                    "name": tm.name,
                    "description": tm.description,
                    "inputSchema": tm.input_schema,
                    **({"annotations": tm.annotations.to_dict()} if tm.annotations else {}),
                }
            )
        if rm := getattr(_obj, MCP_RESOURCE_META, None):
            _resources.append(
                {
                    "uri": rm.uri_template,
                    "name": rm.name,
                    "description": rm.description,
                    "mimeType": rm.mime_type,
                }
            )
        if pm := getattr(_obj, MCP_PROMPT_META, None):
            _prompts.append({"name": pm.name, "description": pm.description})

    _catalogue = {
        "tools": _tools,
        "resources": _resources,
        "prompts": _prompts,
        "mcp_endpoint": "/mcp/",
        "websocket_endpoint": "/filesystem/ws",
        "protocol_versions": ["2024-11-05", "2025-03-26", "2025-11-25"],
        "transport": ["streamable_http", "websocket"],
        "connect_example": (
            "from lauren_mcp import McpServer; "
            "client = McpServer.streamable_http('<url>/mcp/'); "
            "await client.connect()"
        ),
    }

    _base_url = os.environ.get("MODAL_SERVE_URL", "https://&lt;your-app&gt;.modal.run")
    _tool_rows = "".join(
        f'<div class="tool"><strong>{t["name"]}</strong> '
        f'<span class="badge">tool</span><p>{t["description"]}</p></div>'
        for t in _tools
    )
    _res_rows = "".join(
        f'<div class="tool"><strong>{r["uri"]}</strong> '
        f'<span class="badge">resource</span><p>{r.get("description", "")}</p></div>'
        for r in _resources
    )
    _prompt_rows = "".join(
        f'<div class="tool"><strong>{p["name"]}</strong> '
        f'<span class="badge">prompt</span><p>{p.get("description", "")}</p></div>'
        for p in _prompts
    )
    _DISCOVERY_HTML = (
        "<!DOCTYPE html><html lang='en'>"
        "<head><meta charset='utf-8'><title>Lauren MCP Filesystem</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem}"  # noqa: E501
        "h1{color:#1a1a2e}pre{background:#f4f4f4;padding:1rem;overflow:auto;border-radius:6px}"
        ".tool{border:1px solid #ddd;border-radius:6px;padding:1rem;margin:.5rem 0}"
        ".badge{background:#e8f4fd;color:#0366d6;padding:2px 8px;border-radius:4px;font-size:.8em}"
        "</style></head><body>"
        "<h1>🗂 Lauren MCP Filesystem</h1>"
        "<p>An MCP server exposing CRUD filesystem operations over a Modal Volume.</p>"
        f"<h2>Connect</h2><pre><code>"
        f"from lauren_mcp import McpServer\n"
        f'client = McpServer.streamable_http("{_base_url}/mcp/")\n'
        "await client.connect()\ntools = await client.list_tools()</code></pre>"
        "<h2>Claude Desktop</h2><pre><code>"
        '{"mcpServers": {"filesystem": {\n'
        f'  "command": "uvx",\n  "args": ["mcp-remote", "{_base_url}/mcp/"]\n'
        "}}}</code></pre>"
        f"<h2>Tools ({len(_tools)})</h2>{_tool_rows}"
        f"<h2>Resources ({len(_resources)})</h2>{_res_rows}"
        f"<h2>Prompts ({len(_prompts)})</h2>{_prompt_rows}"
        "<p><small><a href='/tools.json'>tools.json</a> · "
        "MCP endpoint: <code>/mcp/</code> (Streamable HTTP) · "
        "<code>/filesystem/ws</code> (WebSocket)</small></p>"
        "</body></html>"
    )

    # ------------------------------------------------------------------
    # Discovery controller — pure Lauren, no Starlette needed.
    # ------------------------------------------------------------------
    @controller("/")
    class _DiscoveryController:
        @get("/")
        async def index(self) -> Response:
            """Human-readable HTML listing all tools."""
            return Response(
                body=_DISCOVERY_HTML.encode(),
                status=200,
                headers=Headers([("content-type", "text/html; charset=utf-8")]),
            )

        @get("/tools.json")
        async def tools_json(self) -> dict:
            """Machine-readable tool catalogue — no MCP client required."""
            return _catalogue

    # ------------------------------------------------------------------
    # Compose: discovery controller + MCP server in one Lauren app.
    # ------------------------------------------------------------------
    mcp_module = McpServerModule.for_root(
        FilesystemServer,
        transport="all",
        log_level="info",
        providers=[McpFilesystemGuard],
    )

    @module(imports=[mcp_module], controllers=[_DiscoveryController])
    class _DeployedApp:
        pass

    return LaurenFactory.create(_DeployedApp)


# ---------------------------------------------------------------------------
# Volume management helpers (run with `modal run modal_deploy.py::fn`)
# ---------------------------------------------------------------------------


@app.function(image=image, volumes={VOLUME_MOUNT: volume})
def commit_volume() -> str:
    """Flush all pending writes to Modal's durable storage layer.

    Run after bulk write operations or before scaling down:

        modal run examples/filesystem/modal_deploy.py::commit_volume
    """
    volume.commit()
    return f"✓ Volume '{VOLUME_NAME}' committed."


@app.function(image=image, volumes={VOLUME_MOUNT: volume})
def list_volume(path: str = ".") -> list[str]:
    """List the contents of *path* inside the volume.

    modal run examples/filesystem/modal_deploy.py::list_volume
    modal run examples/filesystem/modal_deploy.py::list_volume --path docs
    """
    import os as _os  # noqa: PLC0415

    safe_path = VOLUME_MOUNT + "/" + path.strip("/")
    resolved = _os.path.normpath(safe_path)
    if not resolved.startswith(VOLUME_MOUNT):
        return ["error: path traversal detected"]
    try:
        entries = sorted(
            ("📁 " if _os.path.isdir(_os.path.join(resolved, e)) else "📄 ") + e
            for e in _os.listdir(resolved)
        )
        return entries or ["(empty)"]
    except FileNotFoundError:
        return [f"error: {path!r} not found in volume"]


@app.function(image=image, volumes={VOLUME_MOUNT: volume})
def wipe_volume(confirm: str = "") -> str:
    """Delete **all** files from the volume.  Pass confirm='yes' to proceed.

    modal run examples/filesystem/modal_deploy.py::wipe_volume --confirm yes
    """
    if confirm.lower() != "yes":
        return "Aborted — pass --confirm yes to wipe the volume."
    import shutil as _shutil  # noqa: PLC0415

    root = Path(VOLUME_MOUNT)
    for child in root.iterdir():
        if child.is_dir():
            _shutil.rmtree(child)
        else:
            child.unlink()
    volume.commit()
    return f"✓ Volume '{VOLUME_NAME}' wiped and committed."


# ---------------------------------------------------------------------------
# Local entrypoint — shown when you run `modal run modal_deploy.py`
# ---------------------------------------------------------------------------


@app.local_entrypoint()
def main() -> None:
    """Print usage instructions."""
    name = Path(__file__).name
    print()
    print("  Lauren MCP Filesystem — Modal deployment")
    print()
    print(f"  Serve locally:   modal serve {name}")
    print(f"  Deploy:          modal deploy {name}")
    print()
    print(f"  List files:      modal run {name}::list_volume")
    print(f"  List subdir:     modal run {name}::list_volume --path my/subdir")
    print(f"  Commit writes:   modal run {name}::commit_volume")
    print(f"  Wipe volume:     modal run {name}::wipe_volume --confirm yes")
    print()
    print("  Discovery (no MCP client needed):")
    print("    curl https://<app>.modal.run/tools.json   # machine-readable")
    print("    open https://<app>.modal.run/            # human-readable HTML")
    print()
    print("  Claude Desktop — add to claude_desktop_config.json:")
    print('    {"mcpServers": {"filesystem": {"command": "uvx",')
    print('      "args": ["mcp-remote", "https://<app>.modal.run/mcp/"]}}}')
    print()
    print("  Python client:")
    print("    from lauren_mcp import McpServer")
    print('    client = McpServer.streamable_http("https://<app>.modal.run/mcp/")')
    print("    await client.connect()")
    print("    tools = await client.list_tools()")
