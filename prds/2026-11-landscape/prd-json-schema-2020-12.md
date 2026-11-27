# PRD — JSON Schema 2020-12 alignment for emitted schemas

**Status:** Draft
**Date:** 2026-11-26
**Priority:** **P2**
**Issue:** _pending_
**Scope:** `server/_schema.py`, the schema-emitting sites in `server/_decorators.py`, `_server/_context.py`, `server/_handlers.py`; new `server/_dialect.py`, `server/_validate.py`, public `schema.py`; the `jsonschema` extra in `pyproject.toml`

---

## 1. Problem Statement

`lauren-mcp` is the only surveyed Python framework that builds JSON Schema by hand instead of asking
Pydantic for it, a consequence of the dependency posture: Pydantic is an optional extra, so
`pydantic.TypeAdapter` cannot sit on the schema path (inventory §1; `pyproject.toml:27-30` declares only
`lauren` and `anyio`).

The hand-rolled builder works, but never says **which dialect** it writes. MCP made JSON Schema 2020-12
the default dialect for schema definitions in `2025-11-25` (SEP-1613, **E-13**), and `2026-07-28`
tightens `inputSchema`/`outputSchema` conformance and bounds `$ref` composition resources (**E-30**;
§6.2/§8.10 — see Q1 for what I could not verify). The dialect is no longer "whatever a library emits
for us"; it is a wire-level field we declare or leave to the client's guess.

### 1.1 What the builders emit today — verified, not assumed

The dialect keyword appears **nowhere** in the package:

```
$ grep -rn 'json-schema.org' src/ | wc -l          # 0
$ grep -rn '"\$schema"' src/lauren_mcp --include=*.py | wc -l   # 0
```

Shapes read off the code, confirmed by calling the builder:

| Feature | Where | Emitted today | 2020-12 verdict |
|---|---|---|---|
| Primitives | `server/_schema.py:47-56` | `{"type":"string"}`, `{"type":"null"}` | fine |
| `uuid.UUID`, `datetime`, `date`, `time`, `timedelta` | `_schema.py:54-58` | `format` = `uuid`/`date-time`/`date`/`time`/`duration` | fine (annotations; `duration` is new in 2020-12) |
| `pathlib.Path` | `_schema.py:59` | `format: "path"` | non-canonical; legal annotation, ignored by validators |
| `bytes` | `_schema.py:60` | `{"type":"string","format":"byte"}` | **wrong dialect** — `byte` is an OpenAPI format; 2020-12 wants `contentEncoding`/`contentMediaType` |
| `Optional[X]` | `_schema.py:175-181` | `X`, null dropped ("absence of `required` is the optionality signal") | **diverges** from Pydantic's `anyOf:[X,{"type":"null"}]` |
| `list[X]` | `_schema.py:117-122` | `{"type":"array","items":X}` | fine |
| `set[X]` | `_schema.py:125-129` | `{"type":"array","uniqueItems":true,"items":X}` | fine |
| `dict[K,V]` | `_schema.py:136-139` | `additionalProperties: V` | fine — the **only** `additionalProperties` the builder ever writes |
| `tuple[X,Y]` | `_schema.py:203-208` | `prefixItems:[…]` + `minItems`/`maxItems` | already 2020-12 (`tests/unit/test_schema_builder.py:79-81`) |
| Structured types | `_schema.py:220-322` | shared `$defs` + `{"$ref":"#/$defs/Name"}` | already `$defs`, never `definitions` — except the legacy hoist at `:230` |
| Defaults | `_schema.py:269`, `:330-332` | `default` copied onto the property | fine |
| Constraints | `_schema.py:65-73`, `:344-347` | `minimum`/`exclusiveMinimum`/`maxLength`/`multipleOf`/`pattern` | fine |
| Object closure | everywhere | never `additionalProperties: false`, never `unevaluatedProperties` | objects open by accident, not choice |

The first hard defect is reproducible in six lines — any recursive Pydantic model (trees, comment
threads, expression ASTs):

```json
{"$ref": "#/$defs/Node"}                 // returned to the caller
{"Node": {"$ref": "#/$defs/Node"}}       // the $defs entry: a $ref that resolves to itself, forever
```

The cause is `server/_schema.py:230-233`:

```python
# src/lauren_mcp/server/_schema.py  lines 230-233
for key in ("$defs", "definitions"):
    for def_name, def_schema in model_schema.pop(key, {}).items():
        self.defs.setdefault(def_name, def_schema)
self.defs[name] = model_schema
```

When Pydantic's root *is* a `$ref`, `model_schema` after the `pop` is `{"$ref": "#/$defs/Node"}`, and
line 233 overwrites the real definition line 232 just hoisted. A client that resolves `$ref` before
use loops on that graph until it hits its own resource bound. The dataclass path is fine (it reserves
the slot at `_schema.py:256-258` and fills it in place), so the same tree annotation behaves
differently depending on which structured-type family the user picked.

Second inconsistency, same family — `_schema.py:176-181` deliberately drops the null branch (absence
of `required` is the optionality signal), so `name: str | None` emits `{"type":"string"}` as a tool
parameter but `{"anyOf":[{"type":"string"},{"type":"null"}],"default":null}` inside a model.

### 1.2 Why P2 and not P1

Nothing we emit is rejected by a compliant validator: the schemas are valid, just unlabelled, and
`$schema` is not demonstrably a MUST on tool schemas (Q1). The only shape that breaks a client is the
recursive-`$ref` loop, reachable through a recursive Pydantic model. Drift plus one real defect, both
fixable inside the module that owns them — the brief's P2 test.

Secondary: with no dialect declared we cannot validate what we emit. There is no `jsonschema`
dependency and no test asks "is this legal 2020-12?"; the seven `tests/unit/test_schema_*.py` files
assert exact dict literals for hand-picked annotations and thereby pin today's spellings.

---

## lauren-mcp Advantages

**The dialect is ours to change in one commit.** FastMCP and the official SDK inherit whatever
`pydantic.json_schema()` emits, so their dialect is a function of their Pydantic floor: bump Pydantic,
and the wire format moves. Here, `server/_schema.py:47-63` is a 16-line table and `:65-73` a
constraint map; every keyword on the wire is a literal in our source. Declaring `$schema`, switching
`format: byte` to `contentEncoding`, or closing objects are three reviewable edits in one file, with
no upstream release to wait for.

**The two-dependency posture survives.** `pyproject.toml:27-30` still declares only `lauren` and
`anyio`; validation (§4.7) is an optional `[jsonschema]` extra nobody must install to serve tools,
matching `ws`/`http`/`pydantic`/`msgspec`/`cli` (`:32-37`, **E-223**). A Pydantic-based framework cannot
offer "validate my schemas, but don't make me install a validator".

**The hard half is already right.** `$defs` (not `definitions`), `prefixItems` (not tuple `items`),
shared-definition dedup with a reserved slot for recursion, `uniqueItems` for sets and
`additionalProperties: V` for `dict[K,V]` predate the mandate; the remaining deltas are small and
enumerable — that is the whole of §4.

**A policy object is possible only because we emit the schema ourselves.** `mcp_tool` already carries
`output_schema` and tri-state `structured_output` (`_decorators.py:766-767`, inventory §6.1); one more
keyword in that slot lets an operator keep legacy spellings for one legacy client while shipping
2020-12 to everyone else.

---

## 2. Goals

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

---

## 3. Non-Goals

- **Not a schema compiler, not a validation framework.** We do not replace the visitor with
  `pydantic.TypeAdapter` or a third-party generator — ownership of `_schema.py` is what keeps the
  Pydantic floor at zero — and we validate schemas against the metaschema (§4.7) rather than making
  `jsonschema` request validation a default: clients validate, and servers that reject on annotation
  drift break deployments.
- **Not a re-dialect of user dicts.** `output_schema={"$schema": "…draft-07…"}` is returned verbatim
  (`_decorators.py:664-665`); rejecting it is a `strict` option (Q3).
- **Not the `2026-07-28` schema *content* changes** — any new field on `Tool` itself belongs to the
  tools-surface PRD.
- **Not a migration of the elicitation flatness rule** — `_context.py:148-184` still refuses nested
  objects (Q4).

---

## 4. Design

### 4.1 A dialect module with a policy object

New `src/lauren_mcp/server/_dialect.py`, stdlib only:

```python
# src/lauren_mcp/server/_dialect.py  (new)
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

# 2020-12 §10.3: $ref siblings must be annotations; validation keywords compose.
_REF_SIBLING_ANNOTATIONS = frozenset({
    "$comment", "$id", "$schema", "title", "description", "default",
    "deprecated", "readOnly", "writeOnly", "examples"})

@dataclass(frozen=True)
class SchemaPolicy:
    dialect: str | None = JSON_SCHEMA_DIALECT
    nullable: typing.Literal["omit", "type-null", "anyof"] = "omit"
    close_objects: bool = False
    strict_refs: bool = True
    max_ref_depth: int = 64
    honor_user_dialect: bool = True

LEGACY_POLICY, DEFAULT_POLICY = SchemaPolicy(dialect=None), SchemaPolicy()

def finalize_object_schema(schema: dict, policy: SchemaPolicy = DEFAULT_POLICY) -> dict:
    """Stamp the dialect at the root only; enforce the SEP-2106 $ref bounds."""
    out = copy.deepcopy(schema)
    normalize_defs(out)                 # definitions -> $defs, rewrite #/definitions/
    check_ref_siblings(out, policy)     # composition keywords beside $ref
    check_ref_targets(out, policy)      # every $ref resolves in-document
    check_ref_depth(out, policy)        # bounded resolution, cycles detected
    if policy.dialect is not None:
        out.setdefault("$schema", policy.dialect)
    return out
```

`normalize_defs` rewrites `#/definitions/X` → `#/$defs/X` and moves any `definitions` map into `$defs`,
so a Pydantic-v1 model (`_schema.py:227-229`) cannot leak a draft-07 shape through the modern path.
`check_ref_siblings` raises on `$ref` siblings outside `_REF_SIBLING_ANNOTATIONS`;
`check_ref_targets` compares `#/$defs/<name>` targets with `$defs` keys; `check_ref_depth` catches
§1.1's loop (§4.6).

### 4.2 Wire it into the four emission sites

The finalizer runs at the **edges**, so `SchemaBuilder` keeps returning bare fragments.

```python
# src/lauren_mcp/server/_decorators.py  — inputSchema, lines 633-641
    if builder.defs:
        schema["$defs"] = builder.defs
    return (name, description, finalize_object_schema(schema, policy), ...)

# src/lauren_mcp/server/_decorators.py  — _resolve_output_schema, lines 656-685
    if isinstance(output_schema, dict):
        declared = output_schema.get("$schema")
        if declared and declared != JSON_SCHEMA_DIALECT and policy.honor_user_dialect:
            return copy.deepcopy(output_schema)          # the user's dialect wins, untouched
        return finalize_object_schema(output_schema, policy)
    if hasattr(output_schema, "model_json_schema"):
        return finalize_object_schema(dict(output_schema.model_json_schema()), policy)

```

The elicitation builder (`_context.py:181-184`) returns `finalize_object_schema(...)` the same way, and
`_server/_handlers.py:568-572` keeps copying `t.input_schema`/`t.output_schema` into the `tools/list`
entry unchanged: the dialect is already inside the dict, so the handler carries no policy.

### 4.3 Deltas in the visitor

```python
# src/lauren_mcp/server/_schema.py  — _PRIMITIVES, lines 47-63
    pathlib.Path: {"type": "string", "format": "path"},
    # 2020-12 §8.4: binary payloads are annotated, not formatted. "byte" is an
    # OpenAPI 2.0 format and means nothing to a JSON Schema validator.
    bytes: {
        "type": "string",
        "contentEncoding": "base64",
        "contentMediaType": "application/octet-stream",
    },
```

- **`format` stays annotation-only** (asserted only by a format checker), so `format: "path"` (`:59`) is
  legal output no validator knows; the optional validator uses the canonical set, so `path` is ignored,
  not rejected.
- **`$defs` vs `definitions`** — the visitor already writes `$defs`; the only `definitions` reference is
  the legacy hoist at `:230`, removed in §4.4. `normalize_defs` is belt-and-braces for Pydantic v1.
- **`prefixItems`** — already emitted at `:205`; the addition is `"items": False` when `close_objects` is
  on, saying "nothing past `prefixItems`" declaratively; `minItems`/`maxItems` (`:206-207`) stay for
  clients that only read those.
- **`dependentRequired`/`dependentSchemas`** are not derivable from an annotation, so they enter via the
  public helper (§5) and a `json_schema_extra` branch in `_apply_metadata` (`_schema.py:325-335`).
- **`unevaluatedProperties`** only matters beside composition: `allOf`+`properties` defeats
  `additionalProperties` (it cannot see properties declared in the sibling), so under `close_objects`
  the finalizer writes `unevaluatedProperties: false` and drops `additionalProperties: false` — the one
  place a silently-wrong closure could appear.
- **`additionalProperties`** — the single write site `:138` (`dict[K,V]`) is correct; new `false`
  writes happen in the structured-type builders (`:220-322`), never for `dict`/`Mapping`.

### 4.4 Fix the recursive-`$ref` clobber

```python
# src/lauren_mcp/server/_schema.py  — _build_pydantic, lines 220-234
        for key in ("$defs", "definitions"):
            for def_name, def_schema in model_schema.pop(key, {}).items():
                self.defs.setdefault(def_name, def_schema)
        # A recursive root is itself {"$ref": "#/$defs/<name>"}. Never let the
        # wrapper overwrite the definition just hoisted (was: self.defs[name] =
        # model_schema, which left $defs.<name> == {"$ref": ...} forever).
        if set(model_schema) == {"$ref"} and self.defs.get(name):
            return {"$ref": f"#/$defs/{name}"}
        self.defs[name] = model_schema
```

Invariant pinned by test: **no `$defs` value is a lone `$ref` to itself.** `check_ref_depth` re-asserts
it at the edge for user-supplied dicts.

### 4.5 `$schema` on every emitted object schema — the matrix

| Route | Code today | Object emitted | `$schema`? |
|---|---|---|---|
| Tool parameters (`inputSchema`) | `_decorators.py:633-641` → `_handlers.py:568` | `{"type":"object","properties":…,"$defs":…}` | yes, root |
| `structured_output=True`, primitive return | `_decorators.py:717-721` | `{"properties":{"result":…},"required":["result"]}` | yes, root |
| auto, Pydantic/typed return | `:723-726` → `_resolve_output_schema:666-667` | Pydantic dict + `$defs` | yes, root; `$defs` untouched |
| auto, dataclass/TypedDict/msgspec | `_resolve_output_schema:671-680` | inlined definition + residual `$defs` | yes, root |
| `output_schema=<dict>` | `_decorators.py:664-665` | verbatim | only if the user declared one; else stamped, unless a foreign dialect is declared |
| Elicitation `requestedSchema` | `_context.py:181-184`, sent at `:576` | `{"type":"object","properties":…}` | yes, root |
| `$defs` entries | `_schema.py:220-322` | fragments | **never** (root only) |

Precedence (`_decorators.py:812-822`): an explicit `output_schema` resolves **before** `structured_output`
is consulted, so `False` suppresses only *auto-detection* (`:786-789`), not a caller-supplied schema;
whichever branch wins gets the same finalizer.

### 4.6 The `$ref` bounds rule (SEP-2106) and a violating schema

The modern revision bounds the resources a client spends resolving `$ref`. Two shapes violate it, and
a hand-rolled emitter can produce both by accident; both are now rejected at decoration time
(`strict_refs=True`) instead of at the client.

**(a) A `$ref` loop with no content** — what we emit today for a recursive Pydantic model. The only
definition's target is the reference itself, so resolution never terminates:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {"root": {"$ref": "#/$defs/Node"}},
  "$defs": {"Node": {"$ref": "#/$defs/Node"}}
}
```

`check_ref_depth` walks `$defs` as a graph, keeps a `(name, depth)` stack, and raises
`SchemaDialectError("$ref cycle at #/$defs/Node with no lexical content")` when a node is revisited
without having emitted any keyword other than `$ref`. A genuine tree (`items: {"$ref": …}` under a
definition that also has `properties`) is allowed up to `max_ref_depth` hops (default 64).

**(b) Composition keywords beside `$ref`** — §10.3 makes `$ref` siblings annotation-only, so these
`properties`/`required` are at best ignored, at worst applied inconsistently:

```json
{"addr": {"$ref": "#/$defs/Address",
          "properties": {"zip": {"type": "string"}}, "required": ["zip"]}}
```

The finalizer rewrites that to
`{"allOf": [{"$ref": "#/$defs/Address"}], "properties": {"zip": {"type": "string"}}, "required": ["zip"],
"unevaluatedProperties": false}`. We never emit (b) today (`_schema.py:234` returns a bare `{"$ref": …}`), but `output_schema` accepts
arbitrary dicts (`_decorators.py:664-665`), so user input can carry it — as would any future change
that adds a description to a referenced model.

### 4.7 Validation without a required dependency

Three layers, none a hard dependency:

1. **In-repo invariants, stdlib only.** `check_ref_siblings`/`_targets`/`_depth` and the `$schema`/
   `definitions` rules are pure Python and always run at decoration time; this layer fixes §1.1.
2. **Metaschema validation, optional.** `jsonschema` is not stdlib (there is no validator in the
   standard library), so it goes behind the extras pattern:

   ```toml
   # pyproject.toml  lines 32-38
   jsonschema = ["jsonschema>=4.18"]
   all = ["lauren-mcp[ws,http,pydantic,msgspec,jsonschema,cli]"]
   ```

   With it installed, `server/_validate.py` lazily imports `Draft202012Validator`, calls `check_schema`
   once per schema at startup, and validates with a `format_checker` limited to canonical formats:

   ```python
   # src/lauren_mcp/server/_validate.py  (new)
   try:
       from jsonschema import Draft202012Validator      # optional extra
   except ImportError:
       if mode == "strict":
           raise ImportError("schema validation is 'strict' but [jsonschema] is not "
                             "installed: pip install 'lauren-mcp[jsonschema]'") from None
       _log.warning("schema validation skipped: pip install 'lauren-mcp[jsonschema]'")
       return []
   ```

3. **Fail-open by default, fail-closed on request.** `warn` logs one structured warning per offending
   tool plus an OTel event; `strict` raises at startup; `off` does nothing. Selection order:
   `schema_validation=` on `mcp_server(...)`, else `LAUREN_MCP_SCHEMA_VALIDATION`, else `warn` —
   mirroring the existing `strict=` flag on `mcp_tool` (`_decorators.py:769`). Cost without the extra:
   one `try: import` at startup; with it, O(tools) at startup and zero per request.

---

## 5. Server-side Changes

Three new modules: `server/_dialect.py` (~140 lines, stdlib only — constant, `SchemaPolicy`,
`SchemaDialectError`, `finalize_object_schema`, the four §4.1 checks); `server/_validate.py` (~60 lines,
the lazy gate of §4.7); and public `schema.py` (~80 lines — `object_schema()`, `array_schema()`,
`binary_schema()`, so a user can hand `output_schema=` a correct 2020-12 object without knowing the
keyword rules). Four edits in existing files: `_schema.py` (the rows of §1.1), `_decorators.py`
(finalizer at both assembly points, plus `schema_policy`), `_context.py` (elicitation, `_scalar_schema`),
`pyproject.toml` (the extra). `_types.py` needs nothing — `ToolSchema.inputSchema`/`outputSchema`
(`:285-286`) already hold arbitrary dicts.

---

## 6. Exact Lines to Change

### 6.1 `src/lauren_mcp/server/_schema.py`

| Lines | Today | Change |
|---|---|---|
| `47-63` | `_PRIMITIVES`; `:60` `bytes → format: "byte"` | `contentEncoding: base64` + `contentMediaType` |
| `59` | `Path → format: "path"` | keep; document as annotation-only |
| `88-97`, `117-139` | `build()` dispatch; `list`/`set`/`dict` builders | unchanged; `dict` never closed |
| `175-185` | `_build_union` drops the null branch | read `policy.nullable`: `omit`/`type-null`/`anyof` |
| `198-208` | `_build_tuple` → `prefixItems` + min/max | add `"items": False` when `close_objects` |
| `220-234` | `_build_pydantic`; `:233` clobbers hoisted defs | guard the lone-`$ref` root (§4.4) |
| `236-322` | msgspec/dataclass/TypedDict builders | `additionalProperties: false` under `close_objects` |
| `324-352` | `_apply_metadata` | `json_schema_extra` before the loop at `:344-347` |

### 6.2 `src/lauren_mcp/server/_decorators.py`

| Lines | Today | Change |
|---|---|---|
| `633-641` | inputSchema assembly, `$defs` at `:639-641` | wrap in `finalize_object_schema` |
| `656-685` | `_resolve_output_schema`: dict `:664-665`, Pydantic `:666-667`, inline `:671-680` | take `policy`; honour foreign dialect; finalize |
| `687-735` | `_auto_output_schema`; wrapper `:717-721` | finalize the wrapper object |
| `758-769` | `mcp_tool` signature | add `schema_policy: SchemaPolicy \| None = None` |
| `784-792` | docstring | document the policy and tri-state interaction |
| `812-822` | explicit `output_schema` wins | thread `policy` through both branches |

### 6.3 `src/lauren_mcp/_server/_context.py` and `server/_handlers.py`

| File / lines | Today | Change |
|---|---|---|
| `_context.py:148-184` | elicitation builder; object at `:181-184` | finalize before returning |
| `_context.py:214-235`, `:566-580` | `_scalar_schema`; `requestedSchema` on params (`:576`) | `bytes` → `contentEncoding`; send site unchanged |
| `_handlers.py:563-572` | `_tool_list_entry`; `inputSchema` `:568`, `outputSchema` `:571-572` | none — policy lives upstream |

### 6.4 `pyproject.toml`

`27-30` unchanged (`lauren`, `anyio` — goal 9); `32-37` add `jsonschema = ["jsonschema>=4.18"]`, extend
`all`.

---

## 7. Backward Compatibility

**Unchanged:** `type`, `properties`, `required`, `$defs`, `$ref`, `prefixItems`, `uniqueItems`, `enum`,
`const`, `default` and every constraint keyword keep their exact spellings. A client that ignores
`$schema` sees byte-identical output for non-recursive, non-binary tools.

**Changed, deliberately — two entries:**

1. `bytes`: `{"type":"string","format":"byte"}` →
   `{"type":"string","contentEncoding":"base64","contentMediaType":"application/octet-stream"}`. A
   client that read `format == "byte"` must key on `contentEncoding`; the value domain is unchanged
   (both say "base64 text"), which is why this is P2. `LEGACY_POLICY` restores the old spelling.
2. Recursive Pydantic models: previously an unsatisfiable `$defs` entry; now the real definition.
   Nothing that worked before breaks — nothing could have, since the definition had no content.

**Opt-outs:** `mcp_tool(schema_policy=LEGACY_POLICY)` (or on `mcp_server`) reproduces today's output
including the missing `$schema`; `LAUREN_MCP_SCHEMA_POLICY=legacy` does it globally.

**Migration notes for users:** none required. A draft-07 dict passed to `output_schema=` keeps its
declared dialect (`honor_user_dialect=True`); a bare 2020-12 dict gains a `$schema` key the user did
not write — harmless, reversible with `LEGACY_POLICY`.

---

## 8. Test Plan

### 8.1 `tests/unit/test_schema_dialect.py` (new)

`test_inputschema_declares_dialect`; `test_defs_entries_have_no_schema_key`;
`test_recursive_pydantic_model_terminates` (`defs["Node"]` has `properties`, its `items` is
`{"$ref": "#/$defs/Node"}`); `test_bytes_uses_content_encoding`;
`test_path_format_survives_as_annotation`; `test_nullable_policies` (three policies × parameter and
`$defs`); `test_definitions_are_rewritten` (a Pydantic-v1 shape → `$defs`);
`test_ref_sibling_rejected`; `test_ref_cycle_rejected`; `test_ref_depth_cap` (70 fails, 60 passes);
`test_close_objects` (dataclass closed, `dict[str,int]` not); `test_dependent_required_passthrough`; `test_foreign_user_dialect_preserved`.

### 8.2 Additions to existing files

`test_schema_builder.py` — the `bytes` case in the `_PRIMITIVES` parametrize block (`:30-70`); `tuple`
assertions at `:79-81` unchanged. `test_schema_builder_pydantic.py` —
`test_self_referential_root`, `test_mutually_recursive_pair` (`A`→`B`→`A`).
`test_schema_structured_types.py` — `test_dataclass_recursion_unchanged`; `test_schema_msgspec.py` —
`test_struct_closure_under_policy`.

### 8.3 `tests/unit/test_output_schema_dialect.py` (new)

The §4.5 matrix, one test per cell: `structured_output` ∈ {`None`, `True`, `False`} × `output_schema` ∈
{`None`, dict, Pydantic model, dataclass} — asserting what is emitted, exactly one `$schema` at the root,
and that the primitive wrapper (`_decorators.py:717-721`) is stamped.

### 8.4 `tests/integration/test_schema_dialect_integration.py` (new)

`tools/list` over the in-memory transport: every `inputSchema` and present `outputSchema` carries the
dialect and survives a `json.dumps`→`json.loads` round trip; with the extra installed,
`Draft202012Validator.check_schema` passes for each; `ctx.elicit(...)` stamps `requestedSchema`
(`_context.py:576`); `strict` refuses to start on an `output_schema` with a dangling `$ref`.

---

## 9. Open Questions

**Q1 — does `2026-07-28` make `$schema` a MUST on `tools.inputSchema`?** The brief attributes a `$ref`
bounds rule and a conformance tightening to SEP-2106 (§6.2/§8.10), but `_research/spec.md` has no
`$ref`/SEP-2106 text I can quote, and **E-30** is the deprecation row, not a schema row. Read goal 1 as
"declare it because ambiguity is worse", not "declare it or fail conformance": we stamp
unconditionally, which satisfies both readings.

**Q2 — why not validate arguments against `inputSchema` on every `tools/call`?** Cost per call, and
every object we emit is open, so rejecting unknown keys would break clients. Follow-up PRD?

**Q3 — should `strict_refs` reject a user-supplied draft-07 dict?** Today `honor_user_dialect=True`
passes it through; rejecting anything non-2020-12 would remove the only escape hatch for hand-written
schemas.

**Q4 — does `2026-07-28` relax elicitation's flatness rule?** `_context.py:169-175` raises on nested
objects. If nesting is allowed now, `dependentSchemas` becomes far more useful for elicitation.

---

## 10. References

**Repository evidence** — `server/_schema.py:47-63`, `:65-73`, `:88-97`, `:117-139`, `:175-185`,
`:198-208`, `:220-234`, `:236-322`, `:324-352`; `server/_decorators.py:633-641`, `:656-685`, `:687-735`,
`:758-769`, `:784-792`, `:812-822`; `_context.py:148-184`, `:214-235`, `:566-580`;
`server/_handlers.py:563-572`; `_types.py:280-289`; `pyproject.toml:27-37`;
`tests/unit/test_schema_builder.py:30-70`, `:79-81`; `_research/lauren-mcp-inventory.md` §1 (hand-rolled
352-line schema path, two runtime deps) and §6.1 (`mcp_tool` surface incl. `output_schema`/
`structured_output`).

**External evidence** — **E-13** (SEP-1613: 2020-12 is the default dialect from `2025-11-25`);
**E-30** (`2026-07-28` changes; cited by the brief for the schema tightening, not quotable from the
corpus — Q1); **E-223** (optional-extras pattern); **E-21…E-27** (`tools.inputSchema`/`outputSchema` are
the only schema-bearing fields); **E-222** (two-dependency posture). Spec §6.2, §8.4 (content encoding),
§8.10, §10.3 (`$ref` siblings).
