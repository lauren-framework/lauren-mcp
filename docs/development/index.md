# Contributing to Lauren MCP

Thank you for considering a contribution to `lauren-mcp`! This page covers everything
you need to go from a fresh clone to a merged PR.

---

## Setup

1. Fork and clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/lauren-mcp
cd lauren-mcp
```

2. Clone the framework side by side (required for editable install):

```bash
git clone https://github.com/lauren-framework/lauren-framework ../lauren-framework
```

3. Install all dev dependencies:

```bash
uv sync --extra all --extra dev --active
```

4. Verify the setup:

```bash
uv run pytest tests/unit -q
```

---

## Design philosophy

These five rules guide every decision in `lauren-mcp`:

1. **Zero magic at import time.** Decorators register metadata; they do not run IO,
   open connections, or start threads. All side effects happen at application startup
   via `McpServerModule.for_root()` or on the first `async with client`.

2. **Type annotations are the source of truth.** JSON Schemas for tools, resources, and
   prompts are derived automatically from Python type annotations. Manually authored
   schemas are a last resort, not the default.

3. **Transports are interchangeable.** The same `@mcp_server` class works over
   WebSocket, HTTP+SSE, and stdio without any code changes. The transport choice is
   a deployment detail, not an application concern.

4. **Optional deps stay optional.** The `websockets` and `httpx` packages are never
   imported at module level. Import guards raise a clear `ImportError` with an
   install hint when a transport is used without its extra.

5. **Tests must not require a running server by default.** Unit tests mock the
   `McpClientProtocol`; integration tests use the echo server subprocess pattern.
   Live-network tests are `@pytest.mark.eval` and excluded from `pytest` default runs.

---

## Branching strategy

| Branch | Purpose |
|---|---|
| `main` | Stable, always releasable |
| `dev` | Integration branch for in-progress features |
| `feat/<name>` | Feature branches (from `dev`) |
| `fix/<name>` | Bug fix branches (from `main` for hotfixes, `dev` otherwise) |
| `docs/<name>` | Documentation-only changes |

Open PRs against `dev` for features and against `main` for critical hotfixes.

---

## Commit message format

```
<type>(<scope>): <short summary>

<optional longer description>

Refs: #<issue>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`

Examples:

```
feat(server): add @mcp_resource decorator with URI template support
fix(client): handle reconnect during in-flight call_tool
docs(guides): add authentication headers section to client guide
```

---

## How to add a new MCP primitive

Use this checklist when implementing a new MCP primitive (e.g. a new decorator or
message type):

1. **Add wire types** in `src/lauren_mcp/_types.py` — dataclasses matching the MCP spec.
2. **Add to `__all__`** in `src/lauren_mcp/__init__.py`.
3. **Write unit tests** in `tests/unit/` covering serialisation, schema generation,
   and dispatch — no subprocesses, no network.
4. **Implement the server-side handler** in `src/lauren_mcp/_server/` and register it
   in `_dispatcher.py`.
5. **Implement the client-side method** on `McpClientProtocol` and all three transport
   implementations.
6. **Update the echo server fixture** at `tests/fixtures/echo_server.py` to exercise
   the new primitive.
7. **Write an integration test** in `tests/integration/` using the echo server.
8. **Update docs**: add a section to the relevant guide, update `reference/types.md`
   or `reference/server.md`/`reference/client.md`, update `llms-full.txt`, and run
   `nox -s llms_check` to verify coverage.

---

## Tests requirements

- All new code must have unit tests.
- Coverage must not drop below 80% (`nox -s coverage`).
- Integration tests must pass locally before opening a PR.
- `pytest.mark.eval` tests are optional for contributors but required for maintainers
  before a release.

---

## Docs requirements

- Every public symbol must have a docstring.
- New guides must be linked from `docs/guides/index.md`.
- Run `nox -s docs` locally to ensure the docs build without warnings.

---

## Definition of done

A PR is ready to merge when:

- [ ] All unit and integration tests pass (`nox -s tests tests_integration`)
- [ ] Coverage is >= 80% (`nox -s coverage`)
- [ ] Lint and format pass (`nox -s lint format`)
- [ ] Type check passes (`nox -s typecheck`)
- [ ] `llms-full.txt` is up to date (`nox -s llms_check`)
- [ ] Docs build without warnings (`nox -s docs`)
- [ ] `CHANGELOG.md` has an entry in `[Unreleased]`
- [ ] PR description explains the *why*, not just the *what*
