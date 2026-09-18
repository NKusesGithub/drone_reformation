"""Shared test setup.

Two things have to happen before any service module is imported:

1. src/ goes on sys.path. The services are top-level packages under src/ that
   rely on PYTHONPATH=/app/src inside their containers; there is no installed
   package, so tests have to reproduce that.
2. CONFIG_PATH is pinned to a fixture. Services read config.yaml at import
   time into module-level globals, so the value has to be set before the
   import, and pinning it keeps the suite independent of whatever config.yaml
   the developer happens to have locally.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "config.yaml"

# Forced, not setdefault: a developer with CONFIG_PATH already exported should
# still get the fixture, or the suite is not reproducible.
os.environ["CONFIG_PATH"] = str(FIXTURE_CONFIG)
os.environ["DRONE_MODE"] = "mock"
