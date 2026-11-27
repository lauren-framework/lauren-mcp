**PRD:** [`prd-json-schema-2020-12.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-json-schema-2020-12.md)
**Priority:** P2 — JSON Schema is built by hand rather than asked of Pydantic, so `2020-12` keywords and `$ref` handling drift from what a host validates
**Theme:** Schemas and tools
**Key evidence:** E-13, E-30, E-223 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` is the only surveyed Python framework that builds JSON Schema by hand instead of asking
Pydantic for it, a consequence of the dependency posture: Pydantic is an optional extra, so
`pydantic.TypeAdapter` cannot sit on the schema path (inventory §1; `pyproject.toml:27-30` declares only
`lauren` and `anyio`).

The hand-rolled builder works, but never says **which dialect** it writes. MCP made JSON Schema 2020-12
the default dialect for schema definitions in `2025-11-25` (SEP-1613, **E-13**), and `2026-07-28`
tightens `inputSchema`/`outputSchema` conformance and bounds `$ref` composition resources (**E-30**;
§6.2/§8.10 — see Q1 for what I could not verify). The dialect is no longer "whatever a library emits
for us"; it is a wire-level field we declare or leave to the client's guess.

## Goals

1. **Every emitted object schema declares its dialect** — `inputSchema` (`_decorators.py:633-641`),
   all three `outputSchema` routes (`:656-685`, `:687-735`, wrapper `:717-721`), and elicitation
   `requestedSchema` (`_server/_context.py:181-184`) carry
   `"$schema": "https://json-schema.org/draft/2020-12/schema"` at the root and **nowhere inside `$defs`**.
2. **No dialect-dependent spelling survives** — `format: "byte"` gone from `src/`; `definitions` gone
   from `_schema.py:230` (rewritten, not tolerated).
3. **One spelling per type** — `str | None` yields the same JSON in a parameter, an `$defs` entry and
   an elicitation schema under one `nullable` policy (default: omit the null branch).
4. **Recursive structured types terminate** — a model whose root is a `$ref` emits a definition with
   real content.
5. **`$ref` graphs are bounded** — no non-annotation siblings beside `$ref`; every target exists
   in-document; resolution depth capped; cycles reported at decoration time.
6. **Object schemas close on request** — `close_objects=True` emits `additionalProperties: false` on
   structured-type objects and `unevaluatedProperties: false` beside `allOf`, never on `dict[K,V]`.
7. **Cross-field constraints are expressible** — `dependentRequired`/`dependentSchemas` reach the wire
   via `lauren_mcp.schema.object_schema(...)` and `Field(json_schema_extra=…)` passthrough in
   `_apply_metadata` (`_schema.py:324-352`).
8. **Validation is optional and fail-open, with zero new runtime dependencies** — `[jsonschema]`
   installs the validator; without it the server starts; `strict` refuses to boot on an invalid schema,
   default `warn` logs and emits an OTel event; `pyproject.toml:27-30` unchanged.
10. **No behaviour change for a client that ignores `$schema`** — every delta but the recursive `$defs`
    fix and `format: byte` is additive (§7).

### 2.1 Acceptance criteria

- [ ] `grep -rn 'json-schema.org' src/ | wc -l` ≥ 1 (was 0).
- [ ] `python -c "from lauren_mcp.server._dialect import JSON_SCHEMA_DIALECT as D; print(D)"` prints `https://json-schema.org/draft/2020-12/schema`.
- [ ] `grep -rn '"format": "byte"' src/ | wc -l` returns 0 (was 1 — `server/_schema.py:60`).
- [ ] `grep -c 'definitions' src/lauren_mcp/server/_schema.py` returns 0 (was 1, `:230`).
- [ ] `pytest tests/unit/test_schema_dialect.py -q` passes, incl. `test_inputschema_declares_dialect`, `test_defs_entries_have_no_schema_key`, `test_recursive_pydantic_model_terminates`, `test_bytes_uses_content_encoding`.
- [ ] `pytest tests/unit/test_schema_builder.py tests/unit/test_schema_builder_pydantic.py tests/unit/test_schema_structured_types.py -q` passes.
- [ ] `pytest tests/integration/test_schema_dialect_integration.py -q` passes; every `inputSchema` in a `tools/list` response has `$schema`.
- [ ] `python -c "import sys, lauren_mcp.server._schema; print('jsonschema' in sys.modules)"` prints `False`.
- [ ] `LAUREN_MCP_SCHEMA_VALIDATION=strict pytest tests/integration/test_schema_dialect_integration.py -q` passes (the strict gate does not fire on our own schemas).

## Acceptance criteria

- [ ] `grep -rn 'json-schema.org' src/ | wc -l` ≥ 1 (was 0).
- [ ] `python -c "from lauren_mcp.server._dialect import JSON_SCHEMA_DIALECT as D; print(D)"` prints `https://json-schema.org/draft/2020-12/schema`.
- [ ] `grep -rn '"format": "byte"' src/ | wc -l` returns 0 (was 1 — `server/_schema.py:60`).
- [ ] `grep -c 'definitions' src/lauren_mcp/server/_schema.py` returns 0 (was 1, `:230`).
- [ ] `pytest tests/unit/test_schema_dialect.py -q` passes, incl. `test_inputschema_declares_dialect`, `test_defs_entries_have_no_schema_key`, `test_recursive_pydantic_model_terminates`, `test_bytes_uses_content_encoding`.
- [ ] `pytest tests/unit/test_schema_builder.py tests/unit/test_schema_builder_pydantic.py tests/unit/test_schema_structured_types.py -q` passes.
- [ ] `pytest tests/integration/test_schema_dialect_integration.py -q` passes; every `inputSchema` in a `tools/list` response has `$schema`.
- [ ] `python -c "import sys, lauren_mcp.server._schema; print('jsonschema' in sys.modules)"` prints `False`.
- [ ] `LAUREN_MCP_SCHEMA_VALIDATION=strict pytest tests/integration/test_schema_dialect_integration.py -q` passes (the strict gate does not fire on our own schemas).

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
