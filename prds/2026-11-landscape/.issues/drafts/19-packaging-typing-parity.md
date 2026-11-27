**PRD:** [`prd-packaging-typing-parity.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-packaging-typing-parity.md)
**Priority:** P3 — The differentiator is supply chain - two runtime dependencies, a Python floor matching CI, no upstream `mcp` dependency - and our own metadata fails that scrutiny in five places
**Theme:** Ecosystem
**Key evidence:** E-105, E-106, E-109 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp`'s differentiation is not a protocol feature. It is a **supply-chain shape**: two runtime
dependencies, a Python floor that matches the CI matrix exactly, an installed `py.typed`, and extras that
keep the core importable on a machine with no HTTP stack. The research for this series found three of
seven surveyed Python agent frameworks pinned to a superseded `mcp` SDK line, and 17 OSV advisories
against the upstream `mcp` package, 7 HIGH (E-105, E-106, E-109, E-160, E-168). "We do not depend on it"
is therefore both a compatibility claim and a security claim — **but only if our own metadata survives the
same scrutiny.** It does not, in five places, each read off this branch and confirmed with `grep -n`.

| # | Field | Declared value | Line | Verdict |
|---|---|---|---|---|
| 1 | `requires-python` | `">=3.11"` | `11` | matches `noxfile.py:13` and `tests.yml:23` exactly (§4.4) |
| 2 | `keywords` | `lauren`, `mcp`, `model-context-protocol`, `ai`, `llm` | `13` | `mcp` is present, so PyPI search surfaces us on the same query as the SDK we don't depend on |
| 3 | `classifiers` | 12 entries: Beta (`15`), MIT (`17`), `Python :: 3`…`3.14` (`18`–`22`), two `Topic ::` (`23`–`24`), `Typing :: Typed` (`25`) | `14`–`26` | `Typing :: Typed` is a claim — §1.3 shows it is half-enforced |
| 4 | runtime deps | `lauren>=1.7.0`, `anyio>=4.0` | `27`–`30` | the asset itself (E-222) |
| 5 | extras | `ws`, `http`, `pydantic`, `msgspec`, `all`, `cli` | `32`–`45` | **two extras referenced by shipped code and docs do not exist** (§1.2) |
| 6 | wheel payload | `packages = ["src/lauren_mcp"]` (`61`); `artifacts` names `py.typed`, `llms-full.txt`, **`llms.txt`** (`62`) | | `src/lauren_mcp/llms.txt` does not exist (§1.3) |
| 7 | sdist | `include` (`72`–`75`) names `llms.txt`; `exclude` (`76`–`82`) drops `prds/`, `skills/`, `tests/`, `examples/`, `docs/`, `.github/` | | correct — this PRD is excluded from the shipped artifact |

## Goals

1. **Every install instruction resolves to a real extra**: zero `lauren-mcp[sse]`/`[otel]` in `src/`,
   `README.md`, `docs/`; one canonical name per capability, enforced by a test.
2. **Every optional-import failure is one sentence** naming capability, extra and fix — the existing
   `ws`/`http` pattern (E-223), applied uniformly, with the two missing extras added (§4.3).
3. **PEP 561 is a guarantee**: `py.typed` ships; the four decorators preserve the wrapped signature under
   `mypy --strict`; a consumer fixture in CI proves it (§4.2).
4. **Metadata and payload agree**: no `artifacts` entry naming a missing file; CI asserts wheel contents
   both ways (§4.4).
5. **A written dependency-advice policy** (supported majors, the rule for adding an upper bound, and
   the documented justification for *no* `anyio` upper bound today, §4.1) and a **changelog/versioning
   policy** separating additive modern-era support from legacy-path behaviour changes (§4.5).

### 2.1 Acceptance criteria

Each item is a command with an expected result; together they seed the CI jobs in §4.4.

- [ ] `grep -rn "lauren-mcp\[sse\]\|lauren-mcp\[otel\]" src/ README.md docs/ | wc -l` → `0` (currently `12 + 1 + 1`).
- [ ] `python -c "import tomllib;print(sorted(tomllib.load(open('pyproject.toml','rb'))['project']['optional-dependencies']))"` → `['all','cli','http','msgspec','otel','pydantic','sse','ws']` (`sse` only as a deprecated alias, §4.3).
- [ ] For every extra `X` in that list: `pip install --dry-run "lauren-mcp[$X]"` emits no `does not provide the extra`.
- [ ] `nox -s build` then `python -c "import zipfile,glob;z=zipfile.ZipFile(glob.glob('dist/lauren_mcp-*.whl')[0]);print([n for n in z.namelist() if 'py.typed' in n or 'llms' in n])"` → `lauren_mcp/py.typed` and `lauren_mcp/llms-full.txt`, no `llms.txt`.
- [ ] `grep -c "llms.txt" pyproject.toml` → `1` (sdist `include` only; today `62` and `73`).
- [ ] `mypy --strict tests/typing/test_public_api.py` → exit `0`, and `reveal_type(add)` there shows `def (a: int, b: int) -> int`.
- [ ] `grep -c "TypeVar" src/lauren_mcp/server/_decorators.py` → `≥ 1` (currently `0`).
- [ ] `grep -c '^## \[Unreleased\]' CHANGELOG.md` → `1`; `grep -c '^## \[1\.' CHANGELOG.md` → `5`.
- [ ] `test -f SECURITY.md` and it contains `anyio`, `lauren`, `mcp` and a 90-day disclosure window.
- [ ] `grep -rn "from mcp import\|mcp>=\|mcp==" pyproject.toml src/ | wc -l` → `0` (§4.6).
- [ ] `.github/workflows/tests.yml` has jobs `floor`, `ceiling`, `prerelease`, `extras`, `typing`, `wheel-contents`, all green on the PR branch.
- [ ] `README.md:86`–`95` and `docs/getting-started/installation.md:11`–`18` list the same extras in the same order (asserted by `tests/docs/test_reference_docs.py`).
- [ ] `grep -n 'lauren-mcp Advantages' prds/2026-11-landscape/prd-packaging-typing-parity.md` → hit (§8).

## Acceptance criteria

Each item is a command with an expected result; together they seed the CI jobs in §4.4.

- [ ] `grep -rn "lauren-mcp\[sse\]\|lauren-mcp\[otel\]" src/ README.md docs/ | wc -l` → `0` (currently `12 + 1 + 1`).
- [ ] `python -c "import tomllib;print(sorted(tomllib.load(open('pyproject.toml','rb'))['project']['optional-dependencies']))"` → `['all','cli','http','msgspec','otel','pydantic','sse','ws']` (`sse` only as a deprecated alias, §4.3).
- [ ] For every extra `X` in that list: `pip install --dry-run "lauren-mcp[$X]"` emits no `does not provide the extra`.
- [ ] `nox -s build` then `python -c "import zipfile,glob;z=zipfile.ZipFile(glob.glob('dist/lauren_mcp-*.whl')[0]);print([n for n in z.namelist() if 'py.typed' in n or 'llms' in n])"` → `lauren_mcp/py.typed` and `lauren_mcp/llms-full.txt`, no `llms.txt`.
- [ ] `grep -c "llms.txt" pyproject.toml` → `1` (sdist `include` only; today `62` and `73`).
- [ ] `mypy --strict tests/typing/test_public_api.py` → exit `0`, and `reveal_type(add)` there shows `def (a: int, b: int) -> int`.
- [ ] `grep -c "TypeVar" src/lauren_mcp/server/_decorators.py` → `≥ 1` (currently `0`).
- [ ] `grep -c '^## \[Unreleased\]' CHANGELOG.md` → `1`; `grep -c '^## \[1\.' CHANGELOG.md` → `5`.
- [ ] `test -f SECURITY.md` and it contains `anyio`, `lauren`, `mcp` and a 90-day disclosure window.
- [ ] `grep -rn "from mcp import\|mcp>=\|mcp==" pyproject.toml src/ | wc -l` → `0` (§4.6).
- [ ] `.github/workflows/tests.yml` has jobs `floor`, `ceiling`, `prerelease`, `extras`, `typing`, `wheel-contents`, all green on the PR branch.
- [ ] `README.md:86`–`95` and `docs/getting-started/installation.md:11`–`18` list the same extras in the same order (asserted by `tests/docs/test_reference_docs.py`).
- [ ] `grep -n 'lauren-mcp Advantages' prds/2026-11-landscape/prd-packaging-typing-parity.md` → hit (§8).

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
