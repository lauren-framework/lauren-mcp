# Release Process

`lauren-mcp` uses `setuptools-scm` for version management. Tags on `main` drive the
full release pipeline via GitHub Actions.

---

## Step-by-step

1. **Review the diff** — make sure `main` is ahead of the last tag by exactly the
   intended changes:

   ```bash
   git log v0.1.0..HEAD --oneline
   ```

2. **Update docs** — verify that all new public symbols appear in `llms-full.txt`:

   ```bash
   nox -s llms_check
   ```

3. **Update `README.md`** — check that the feature list and installation table are
   current.

4. **Update `CHANGELOG.md`** — move all items from `[Unreleased]` to a new versioned
   section:

   ```markdown
   ## [0.2.0] - 2025-07-01

   ### Added
   - ...

   ## [Unreleased]
   ```

5. **Commit the release prep**:

   ```bash
   git add CHANGELOG.md README.md llms-full.txt
   git commit -m "chore(release): prepare v0.2.0"
   ```

6. **Tag the commit**:

   ```bash
   git tag -a v0.2.0 -m "Release v0.2.0"
   ```

7. **Push tag and commit**:

   ```bash
   git push origin main --follow-tags
   ```

8. **GitHub Actions takes over** — the `release.yml` workflow:
   - Runs `llms_check`, `build`, `build_check`
   - Uploads the wheel and sdist as artifacts
   - Publishes to **TestPyPI** automatically
   - Publishes to **PyPI** after the `pypi` environment approval
   - Creates a **GitHub Release** with the built artifacts attached

9. **Verify** — install from PyPI in a fresh venv and smoke-test:

   ```bash
   uv run --with lauren-mcp==0.2.0 python -c "import lauren_mcp; print(lauren_mcp.__version__)"
   ```

---

## Hotfix releases

For critical bug fixes on an already-released version:

1. Branch from the release tag: `git checkout -b fix/critical-bug v0.1.0`
2. Apply the fix and add tests.
3. Cherry-pick to `main` and `dev` if needed.
4. Tag as a patch release: `v0.1.1`
5. Follow the same push-and-tag flow above.
