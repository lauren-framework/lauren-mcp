# Versioning

`lauren-mcp` follows **Semantic Versioning 2.0.0** (SemVer) and uses
`setuptools-scm` to derive version strings from git tags automatically.

---

## SemVer rules

Given a version `MAJOR.MINOR.PATCH`:

| Component | When to increment |
|---|---|
| `MAJOR` | Incompatible API change (removing/renaming a public symbol, changing a type) |
| `MINOR` | New backwards-compatible functionality (new decorator, new transport) |
| `PATCH` | Backwards-compatible bug fix |

`0.x.y` releases (alpha/beta phase) may have breaking changes between minor versions.
Once `1.0.0` is released, the full SemVer guarantee applies.

---

## setuptools-scm

The `pyproject.toml` configuration:

```toml
[tool.setuptools_scm]
fallback_version = "0.0.0+unknown"
version_scheme   = "post-release"
local_scheme     = "dirty-tag"
```

`setuptools-scm` reads the version from the most recent git tag:

| Situation | Version string |
|---|---|
| Exactly on tag `v0.1.0` | `0.1.0` |
| 3 commits after `v0.1.0` | `0.1.0.post3+g1a2b3c4` |
| 3 commits after + uncommitted changes | `0.1.0.post3+g1a2b3c4.d20250601` |
| No tags in repository | `0.0.0+unknown` (fallback) |

The version string is written to `src/lauren_mcp/_version.py` at build time and
exposed as `lauren_mcp.__version__`.

---

## Tag format

All release tags must follow the `v{MAJOR}.{MINOR}.{PATCH}` format:

```
v0.1.0
v0.2.0
v1.0.0
v1.0.1
```

Pre-release tags:

```
v0.1.0a1   # alpha 1
v0.1.0b2   # beta 2
v0.1.0rc1  # release candidate 1
```

---

## Dev builds

When you install directly from the repository (`uv sync`), the version will include a
local identifier (e.g. `0.1.0.post1+d20250601`). This is harmless for development and
clearly indicates it is not a PyPI release.

You can always check the installed version:

```bash
python -c "import lauren_mcp; print(lauren_mcp.__version__)"
```
