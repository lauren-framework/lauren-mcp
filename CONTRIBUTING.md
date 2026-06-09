# Contributing to Lauren MCP

Thank you for your interest in contributing! This document covers everything you need
to know to make a great contribution.

---

## Setup

1. Fork the repository on GitHub and clone your fork:

   ```bash
   git clone https://github.com/YOUR_USERNAME/lauren-mcp
   cd lauren-mcp
   ```

2. Clone `lauren-framework` as a sibling directory (required for the editable install):

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
   nox -s lint
   ```

---

## Design philosophy

These five principles guide every decision in `lauren-mcp`. New code must comply with
all of them:

1. **Zero magic at import time.** Decorators register metadata; they never run IO,
   open network connections, or start threads. All side effects happen at application
   startup through `McpServerModule.for_root()` or on the first `async with client`.

2. **Type annotations are the source of truth.** JSON Schemas for tools, resources, and
   prompts are generated from Python annotations. Manually authored schemas are a last
   resort, not the default.

3. **Transports are interchangeable.** The same `@mcp_server` class works over
   WebSocket, HTTP+SSE, and stdio without code changes. Transport selection is a
   deployment concern, not an application concern.

4. **Optional deps stay optional.** `websockets` and `httpx` are never imported at
   module level. Import guards raise a clear `ImportError` with an install hint when
   a transport is used without its extra installed.

5. **Tests must not require a running server by default.** Unit tests mock
   `McpClientProtocol`. Integration tests use the echo server subprocess. Live-network
   tests carry `@pytest.mark.eval` and are excluded from the default pytest run.

---

## Branching strategy

| Branch | Purpose |
|---|---|
| `main` | Stable, always releasable |
| `dev` | Integration branch for in-progress features |
| `feat/<name>` | Feature branches (branch from `dev`) |
| `fix/<name>` | Bug fixes (branch from `main` for hotfixes, `dev` otherwise) |
| `docs/<name>` | Documentation-only changes |

Open PRs against `dev` for features; against `main` for critical hotfixes only.

---

## Commit message format

```
<type>(<scope>): <short summary in present tense>

<optional body — explain the why, not the what>

Refs: #<issue-number>
```

**Types**: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`

**Examples**:
```
feat(server): add @mcp_resource decorator with URI template support
fix(client): handle reconnect during in-flight call_tool await
docs(guides): add authentication headers section to client guide
test(server): add dispatcher routing tests for unknown methods
```

---

## Running tests

```bash
# Unit tests only (fast, no subprocesses)
uv run pytest tests/unit -q

# Integration tests (uses echo server subprocess)
uv run pytest tests/integration -q

# Full suite via nox
nox -s tests

# Coverage report
nox -s coverage
```

---

## Docs requirements

- Every public symbol must have a docstring (Google format with `Args:` section).
- New guides must be linked from `docs/guides/index.md`.
- New public symbols must be added to `llms-full.txt` and `src/lauren_mcp/llms-full.txt`.
- Run `nox -s docs` to ensure the docs build without warnings before submitting a PR.
- Run `nox -s llms_check` to verify `llms-full.txt` coverage.

---

## Definition of done

A PR is ready to merge when ALL of the following are true:

- [ ] All unit and integration tests pass (`nox -s tests tests_integration`)
- [ ] Coverage is >= 80% (`nox -s coverage`)
- [ ] Lint and format pass (`nox -s lint format`)
- [ ] Type check passes (`nox -s typecheck`)
- [ ] `llms-full.txt` is up to date (`nox -s llms_check`)
- [ ] Docs build without warnings (`nox -s docs`)
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`
- [ ] PR description explains the *why*, not just the *what*
- [ ] Reviewer approval from at least one maintainer

---

## Reporting bugs

Please open a GitHub issue with:
- Python version and OS
- `lauren-mcp` version (`python -c "import lauren_mcp; print(lauren_mcp.__version__)"`)
- Minimal reproducible example
- Full traceback

## Requesting features

Open a GitHub Discussion or issue describing:
- The use case (not just the feature)
- Which of the five design principles it aligns with
- Whether you are willing to implement it yourself
