"""Nox sessions for lauren-mcp."""

from __future__ import annotations

import pathlib
import shutil

import nox

PRIMARY_PYTHON = "3.12"
SUPPORTED_PYTHONS = ["3.11", "3.12", "3.13", "3.14"]

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
    session.run("uv", "sync", "--extra", "dev", external=True)


def _install_all(session: nox.Session) -> None:
    session.run("uv", "sync", "--extra", "all", "--extra", "dev", external=True)


# ---------------------------------------------------------------------------
# Test sessions
# ---------------------------------------------------------------------------


@nox.session(python=SUPPORTED_PYTHONS, name="tests")
def tests(session: nox.Session) -> None:
    """Run full test suite (parametrised across supported Python versions)."""
    _install_dev(session)
    session.run("pytest", "-W", "ignore", *session.posargs)


@nox.session(python=PRIMARY_PYTHON, name="tests_unit")
def tests_unit(session: nox.Session) -> None:
    """Run only unit tests on the primary Python version."""
    _install_dev(session)
    session.run("pytest", "tests/unit", *session.posargs)


@nox.session(python=PRIMARY_PYTHON, name="tests_integration")
def tests_integration(session: nox.Session) -> None:
    """Run integration tests (installs 'all' extra)."""
    _install_all(session)
    session.run("pytest", "tests/integration", *session.posargs)


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
        "ruff", "format", "src", "tests", "noxfile.py", "scripts", *session.posargs, external=True
    )


@nox.session(python=PRIMARY_PYTHON, name="typecheck")
def typecheck(session: nox.Session) -> None:
    """Run mypy type-checker."""
    _install_dev(session)
    session.run("mypy", "src/lauren_mcp", *session.posargs, external=True)


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
    session.run("prek", "run", *args, external=True)


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------


@nox.session(python=PRIMARY_PYTHON, name="docs")
def docs(session: nox.Session) -> None:
    """Build the MkDocs documentation (strict mode)."""
    _install_dev(session)
    session.run("mkdocs", "build", "--strict", *session.posargs, external=True)


@nox.session(python=PRIMARY_PYTHON, name="docs_serve")
def docs_serve(session: nox.Session) -> None:
    """Serve the MkDocs documentation locally."""
    _install_dev(session)
    session.run("mkdocs", "serve", *session.posargs, external=True)


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
    # pyproject-build is the CLI entry-point for the build package, installed
    # in .venv/bin/ — use it directly rather than python -m build so the
    # package doesn't need to be installed in the (root-owned) session venv.
    session.run("pyproject-build", "--wheel", "--sdist", *session.posargs, external=True)


@nox.session(python=PRIMARY_PYTHON, name="build_check")
def build_check(session: nox.Session) -> None:
    """Check the built distributions with twine."""
    _install_dev(session)
    session.run("twine", "check", "dist/*", *session.posargs, external=True)


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
