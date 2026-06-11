"""Unit test configuration — ensure optional extras are importable.

The nox test venv does not include [http] or [ws] extras. This conftest
adds the project .venv site-packages (which does include them) to
sys.path so that tests that mock httpx/websockets can import those modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Location of the project .venv that has httpx, httpx-sse, websockets installed.
_VENV_SITE = Path(__file__).parents[2] / ".venv" / "lib" / "python3.12" / "site-packages"

if _VENV_SITE.is_dir() and str(_VENV_SITE) not in sys.path:
    sys.path.insert(0, str(_VENV_SITE))
