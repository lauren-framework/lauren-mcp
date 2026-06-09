# AGENTS.md — Agent guidance for lauren-mcp

## File ownership

| Path | Owns what |
|---|---|
| `src/lauren_mcp/_types.py` | All MCP wire types; `parse_message`; `build_error_response` |
| `src/lauren_mcp/__init__.py` | Public `__all__`; re-exports including `McpCallError` |
| `src/lauren_mcp/server/_decorators.py` | `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt` |
| `src/lauren_mcp/server/_module.py` | `McpServerModule.for_root()`, `_McpHandlerRegistrar` |
| `src/lauren_mcp/server/_handlers.py` | Handler factory functions |
| `src/lauren_mcp/_server/_dispatcher.py` | `McpDispatcher` (routes method → handler) |
| `src/lauren_mcp/_server/_ws.py` | `mcp_ws_controller()` (Lauren WS gateway) |
| `src/lauren_mcp/_server/_sse.py` | `mcp_http_sse_controller()` (Lauren HTTP+SSE gateway) |
| `src/lauren_mcp/_server/_session.py` | `SseSessionStore` |
| `src/lauren_mcp/_client/_stdio.py` | `McpStdioClient`, `McpCallError` |
| `src/lauren_mcp/_client/_base_remote.py` | `_McpBaseRemoteClient` (shared WS+SSE logic) |
| `src/lauren_mcp/_bridge.py` | `McpServerConfig`, `McpToolBridge` |
| `llms-full.txt` | Full API reference for LLMs — keep in sync with `__all__` |
| `llms.txt` | Short overview — update when public API changes |
| `docs/` | User-facing documentation |
| `skills/` | Agent skill packs |
| `tests/docs/` | E2E tests for every doc code example |
| `tests/integration/test_mcp_lauren_*.py` | Lauren DI + WsTestClient + TestClient integration |

## By-task lookup

### Adding a new public symbol
1. Add to `src/lauren_mcp/__init__.py` imports + `__all__`
2. Add a `### SymbolName` section to `llms-full.txt`
3. Run `uv run --no-sync nox -s llms_check` — must pass with 0 missing symbols

### Adding a new @mcp_* decorator option
1. Update `server/_decorators.py` and `server/_meta.py`
2. Update `server/_handlers.py` if dispatch logic changes
3. Update `docs/guides/decorators.md` and `docs/reference/server.md`
4. Add test in `tests/docs/test_decorators.py` (subprocess e2e)

### Adding a new client transport
1. Create `_client/_newtransport.py` extending `_McpBaseRemoteClient`
2. Add `McpServer.newtransport()` factory in `_client/_factory.py`
3. Add optional-dep guard (`try: import ...; _AVAIL=True except ImportError: _AVAIL=False`)
4. Add extra to `pyproject.toml` and document in `docs/reference/client.md`

### Changing McpServerModule.for_root()
- The handler registrar must be an `@injectable(Singleton)` in `providers=[...]`
- After creating the registrar class, set `__init__.__annotations__["server_instance"] = server_cls`
  to work around `from __future__ import annotations` stringification
- `_McpModule._handler_registrar_cls = _McpHandlerRegistrar` exposes it for direct testing

### Testing Lauren integration
- Always call `TestClient(app)` after `LaurenFactory.create()` to trigger `@post_construct`
- Two `McpServerModule.for_root()` in the same `@module` will raise `ModuleExportViolation`
  (McpDispatcher can only be in one module) — use separate apps

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `Method not found: 'initialize'` | `_register_handlers` `@post_construct` didn't run | Call `TestClient(app)` to trigger lifecycle |
| `UnresolvableParameterError: 'ws'` | `handle_connect` used `ws: Any` | Use `ws: WebSocket` from `from lauren import WebSocket` |
| `websocket_validation_error: frame missing 'event' field` | Lauren's routing loop consumed message | `handle_connect` must `await ws.accept()` then `await _message_loop(ws)` |
| `ModuleExportViolation: McpDispatcher declared in both…` | Two `for_root()` in same app | Use two separate `LaurenFactory.create()` apps |
| `MissingProviderError: No provider for server_cls` | PEP 563 stringifies `server_cls` annotation | Patch annotation at runtime (already done in `_module.py`) |
| Subprocess test hangs | `max_retries > 0` causes reconnects on crash | Set `max_retries=0` in all test fixtures |
| `prek run` fails: `git write-tree: insufficient permission` | Root-owned `.git/objects` dirs | `noxfile.py` runs `prek run --all-files`; also rewrite root-owned files with `python3 -c "import shutil; ..."` |

## Definition of done

A change is complete when ALL of the following pass:

```bash
uv run --no-sync nox -s lint          # ruff: 0 errors
uv run --no-sync nox -s typecheck     # mypy: 0 errors  
uv run --no-sync nox -s llms_check   # all 43 public symbols documented
uv run --no-sync nox -s prek         # pre-release hooks pass
uv run --no-sync pytest tests/ -q    # all tests pass
```

If you add a public symbol, `llms_check` will fail — add a `### SymbolName` section
to `llms-full.txt` to fix it.

If you change an API signature, update:
1. `docs/reference/server.md` or `docs/reference/client.md`
2. The corresponding `skills/*/SKILL.md`
3. `llms-full.txt` (same section)
4. Any `tests/docs/` tests that check the old signature

## Key invariants

- `McpStdioClient._message_loop` uses `await ws.receive_text()` — no `asyncio.create_task`
  competing loop because `handle_connect` awaits `_message_loop` directly.
- `ws.accept()` is called explicitly in `handle_connect` before the loop — Lauren
  only auto-accepts after `@on_connect` returns, but our loop never returns.
- `McpCallError` is the only exception raised by client methods on server-side errors.
  It is exported from the top-level `lauren_mcp` package.
- `McpServerConfig` has exactly two fields: `alias: str` and `client: Any`.
  No `description`, `tool_filter`, or other fields.
- `call_tool()` / `read_resource()` / `get_prompt()` all return raw `dict` (the JSON-RPC
  `result` field), not typed dataclasses.
