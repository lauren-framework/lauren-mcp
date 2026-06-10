"""Pytest configuration for filesystem example tests.

Adds the repository root to sys.path so that ``examples.filesystem.server``
can be imported by both test files and e2e subprocess scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path

# examples/filesystem/tests/conftest.py → repo root is four levels up
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
