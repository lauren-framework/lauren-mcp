"""Nox sessions for lauren-mcp."""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import nox

PRIMARY_PYTHON = "3.12"
SUPPORTED_PYTHONS = ["3.11", "3.12", "3.13", "3.14"]
ROOT = pathlib.Path(__file__).parent.resolve()

nox.options.sessions = ["lint", "tests", "format", "build", "build_check", "llms_check", "prek"]
nox.options.reuse_venv = "yes"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_dev(session: nox.Session) -> None:
    # All nox session venvs in this repo may be root-owned, preventing uv from
    # installing into them.  Sync into the project .venv (no --active) so all
    # tools (ruff, prek, twine, mypy, …) are available in .venv/bin/.
    # Sessions use external=True to find tools there via PATH, and pytest
    # sessions use pythonpath=["src"] in pyproject.toml to import lauren_mcp.
    session.run("uv", "sync", "--dev", external=True)


def _install_all(session: nox.Session) -> None:
    session.run("uv", "sync", "--extra", "all", "--dev", external=True)


# ---------------------------------------------------------------------------
# Test sessions
# ---------------------------------------------------------------------------


@nox.session(python=SUPPORTED_PYTHONS, name="tests")
def tests(session: nox.Session) -> None:
    """Run full test suite (parametrised across supported Python versions)."""
    _install_dev(session)
    session.run("uv", "run", "--dev", "pytest", "-W", "ignore", *session.posargs, external=True)


@nox.session(python=PRIMARY_PYTHON, name="tests_unit")
def tests_unit(session: nox.Session) -> None:
    """Run only unit tests on the primary Python version."""
    _install_dev(session)
    session.run("uv", "run", "--dev", "pytest", "tests/unit", *session.posargs, external=True)


@nox.session(python=PRIMARY_PYTHON, name="tests_integration")
def tests_integration(session: nox.Session) -> None:
    """Run integration tests (installs 'all' extra)."""
    _install_all(session)
    session.run(
        "uv",
        "run",
        "--extra",
        "all",
        "pytest",
        "tests/integration",
        *session.posargs,
        external=True,
    )


@nox.session(python=PRIMARY_PYTHON, name="tests_extras")
def tests_extras(session: nox.Session) -> None:
    """Check that import guards work correctly for bare/ws/http/all installs."""
    extras = ("", "ws", "http", "all")
    for extra in extras:
        session.log(f"--- Testing extra: {extra!r} ---")
        if extra:
            session.run(
                "uv",
                "sync",
                "--extra",
                extra,
                "--extra",
                "dev",
                "--active",
                external=True,
            )
        else:
            # bare install: only core deps + dev, no optional transports
            session.run("uv", "sync", "--extra", "dev", "--active", external=True)

        # unit tests must always pass
        session.run("pytest", "tests/unit", "-q", *session.posargs)

        if extra == "":
            # in the bare case, importing the ws transport module must raise ImportError
            session.run(
                "python",
                "-c",
                (
                    "import importlib, sys; "
                    "spec = importlib.util.find_spec('lauren_mcp._client._ws'); "
                    "assert spec is not None, 'module not found — cannot test import guard'; "
                    "import subprocess, sys; "
                    "r = subprocess.run([sys.executable, '-c', "
                    "    'from lauren_mcp._client._ws import WsClient'], "
                    "    capture_output=True); "
                    "assert r.returncode != 0, 'Expected ImportError for bare install but got returncode 0'; "  # noqa: E501
                    "print('OK: WsClient raises ImportError in bare install')"
                ),
                external=False,
            )


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


@nox.session(python=PRIMARY_PYTHON, name="coverage")
def coverage(session: nox.Session) -> None:
    """Run full suite with coverage and produce a report."""
    _install_all(session)
    session.run(
        "uv",
        "run",
        "--dev",
        "python",
        "-m",
        "pytest",
        "--cov=src/lauren_mcp",
        "--cov-report=term-missing",
        "--cov-report=html:htmlcov",
        "--cov-report=xml:coverage.xml",
        *session.posargs,
    )


# ---------------------------------------------------------------------------
# Linting / formatting / type-checking
# ---------------------------------------------------------------------------


@nox.session(python=PRIMARY_PYTHON, name="lint")
def lint(session: nox.Session) -> None:
    """Run ruff linter."""
    _install_dev(session)
    # Redirect cache to /tmp so root-owned .ruff_cache doesn't block ci-slave runs.
    session.run(
        "ruff",
        "check",
        "--fix",
        "src",
        "noxfile.py",
        "scripts",
        *session.posargs,
        external=True,
    )


@nox.session(python=PRIMARY_PYTHON, name="format")
def format_(session: nox.Session) -> None:
    """Run ruff formatter and auto-fix lint issues."""
    _install_dev(session)
    session.run(
        "uv",
        "run",
        "--dev",
        "ruff",
        "format",
        "src",
        "tests",
        "noxfile.py",
        "scripts",
        *session.posargs,
        external=True,
    )


@nox.session(python=PRIMARY_PYTHON, name="typecheck")
def typecheck(session: nox.Session) -> None:
    """Run mypy type-checker."""
    _install_dev(session)
    session.run("uv", "run", "--dev", "mypy", "src/lauren_mcp", *session.posargs, external=True)


# ---------------------------------------------------------------------------
# Auxiliary checks
# ---------------------------------------------------------------------------


@nox.session(python=PRIMARY_PYTHON, name="llms_check")
def llms_check(session: nox.Session) -> None:
    """Verify that llms-full.txt covers all public symbols."""
    _install_dev(session)
    # Add src/ to PYTHONPATH so lauren_mcp is importable directly from source
    # without requiring an editable install in the session venv.
    session.run(
        "uv",
        "run",
        "--dev",
        "python",
        "scripts/check_llms_full.py",
        *session.posargs,
        env={"PYTHONPATH": "src"},
    )


@nox.session(python=PRIMARY_PYTHON, name="prek")
def prek(session: nox.Session) -> None:
    """Run prek pre-release checks."""
    _install_dev(session)
    # --all-files avoids the git stash step (which requires writing git objects
    # that may be owned by root in this environment).
    args = session.posargs or ("--all-files",)
    session.run("uv", "run", "--dev", "prek", "run", *args, external=True)


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------


def _docs_prev(session: nox.Session) -> None:
    """Build the MkDocs documentation (non-strict mode)."""
    _install_dev(session)
    import shutil

    readme_str = "README.md"
    src = pathlib.Path("examples") / "filesystem" / readme_str
    dest_dir = pathlib.Path("docs") / "examples" / "filesystem"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest_dir / readme_str)
    session.log(f"Copied {src} to {dest_dir / readme_str}")


@nox.session(python=PRIMARY_PYTHON, name="docs")
def docs(session: nox.Session) -> None:
    """Build the MkDocs documentation (strict mode)."""
    _install_dev(session)
    _docs_prev(session)
    session.run(
        "uv", "run", "--dev", "mkdocs", "build", "--strict", *session.posargs, external=True
    )


@nox.session(python=PRIMARY_PYTHON, name="docs_serve")
def docs_serve(session: nox.Session) -> None:
    """Serve the MkDocs documentation locally."""
    _install_dev(session)
    _docs_prev(session)
    session.run("uv", "run", "--dev", "mkdocs", "serve", *session.posargs, external=True)


# ---------------------------------------------------------------------------
# Build & release
# ---------------------------------------------------------------------------


@nox.session(python=PRIMARY_PYTHON, name="build")
def build(session: nox.Session) -> None:
    """Wipe dist/ and build wheel + sdist."""
    dist = pathlib.Path("dist")
    if dist.exists():
        shutil.rmtree(dist)
    _install_dev(session)
    out_dir = str(dist)
    session.run(
        "uv", "build", "--wheel", "--sdist", "--out-dir", out_dir, *session.posargs, external=True
    )


@nox.session(python=PRIMARY_PYTHON, name="build_check")
def build_check(session: nox.Session) -> None:
    """Check the built distributions with twine."""
    _install_dev(session)
    session.run("uv", "run", "twine", "check", "dist/*", *session.posargs, external=True)


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------


@nox.session(python=False, name="clean")
def clean(session: nox.Session) -> None:
    """Remove all build/test/coverage artifacts."""
    artifacts = [
        "dist",
        "build",
        "htmlcov",
        ".coverage",
        "coverage.xml",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "site",
        "src/lauren_mcp/__pycache__",
    ]
    for artifact in artifacts:
        p = pathlib.Path(artifact)
        if p.is_dir():
            session.log(f"Removing directory: {artifact}")
            shutil.rmtree(p)
        elif p.is_file():
            session.log(f"Removing file: {artifact}")
            p.unlink()
    # remove __pycache__ directories recursively
    for pycache in pathlib.Path("src").rglob("__pycache__"):
        shutil.rmtree(pycache)
    for pycache in pathlib.Path("tests").rglob("__pycache__"):
        shutil.rmtree(pycache)


# ---------------------------------------------------------------------------
# Build & release
# ---------------------------------------------------------------------------
_SEMVER_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _latest_release_tag() -> tuple[str, tuple[int, int, int]]:
    result = subprocess.run(
        ["git", "tag", "--list", "v*"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tags = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    parsed: list[tuple[tuple[int, int, int], str]] = []
    for tag in tags:
        match = _SEMVER_TAG_RE.fullmatch(tag)
        if match is None:
            continue
        parsed.append(((int(match.group(1)), int(match.group(2)), int(match.group(3))), tag))
    if not parsed:
        raise RuntimeError(
            "No release tags matching v<major>.<minor>.<patch> were found. "
            "Create an initial tag such as v0.1.0 first."
        )
    version, tag = max(parsed, key=lambda item: item[0])
    return tag, version


def _version_bump_kind(session: nox.Session) -> str:
    allowed = {"--major": "major", "--minor": "minor", "--patch": "patch"}
    selected = [allowed[arg] for arg in session.posargs if arg in allowed]
    if not selected:
        return "patch"
    if len(selected) > 1:
        session.error("Choose exactly one of --major, --minor, or --patch.")
    return selected[0]


def _adjust_version(
    version: tuple[int, int, int], kind: str, *, delta: int
) -> tuple[int, int, int]:
    major, minor, patch = version
    if kind == "major":
        major += delta
        if major < 0:
            raise ValueError("Cannot decrement major below 0.")
        return major, 0, 0
    if kind == "minor":
        minor += delta
        if minor < 0:
            raise ValueError("Cannot decrement minor below 0.")
        return major, minor, 0
    if kind == "patch":
        patch += delta
        if patch < 0:
            raise ValueError("Cannot decrement patch below 0.")
        return major, minor, patch
    raise ValueError(f"Unsupported version bump kind: {kind}")


def _render_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def _log_version_suggestion(session: nox.Session, *, action: str, delta: int) -> None:
    current_tag, current_version = _latest_release_tag()
    kind = _version_bump_kind(session)
    try:
        next_version = _adjust_version(current_version, kind, delta=delta)
    except ValueError as exc:
        session.error(str(exc))
    next_version_str = _render_version(next_version)
    next_tag = f"v{next_version_str}"
    session.log(f"Latest release tag: {current_tag}")
    session.log(f"{action} {kind}: {current_tag} -> {next_tag}")
    session.log("")
    session.log("Copy/paste:")
    session.log(f'  git tag -a {next_tag} -m "Release {next_tag}"')
    session.log("")
    session.log("Then push it with:")
    session.log(f"  git push origin {next_tag}")
    session.log("")
    session.log("Together:")
    session.log(f"  git tag -a {next_tag} -m 'Release {next_tag}' && git push origin {next_tag}")


@nox.session(python=PRIMARY_PYTHON, name="ver_inc")
def ver_inc(session: nox.Session) -> None:
    """Print the next release tag after incrementing major/minor/patch.

    Examples::

        nox -s ver_inc
        nox -s ver_inc -- --minor
        nox -s ver_inc -- --major
    """
    _log_version_suggestion(session, action="Increment", delta=1)


@nox.session(python=PRIMARY_PYTHON, name="ver_dec")
def ver_dec(session: nox.Session) -> None:
    """Print the previous release tag after decrementing major/minor/patch.

    Examples::

        nox -s ver_dec -- --patch
        nox -s ver_dec -- --minor
        nox -s ver_dec -- --major
    """
    _log_version_suggestion(session, action="Decrement", delta=-1)
