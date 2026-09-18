from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

# The container layout mirrors the repo layout -- src/drone_common/ sits two
# levels below config.yaml in both -- so this one expression resolves correctly
# in each: /app/config.yaml inside a container, <repo root>/config.yaml on the
# host. That is what lets a service be imported outside Docker, e.g. by tests.
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


def default_config_path() -> Path:
    """Where load_config() reads from when no explicit path is given.

    Set CONFIG_PATH to override, e.g. to point a test at a fixture.
    """
    override = os.getenv("CONFIG_PATH", "").strip()
    return Path(override) if override else _DEFAULT_CONFIG_PATH


def load_config(path: str | Path | None = None) -> Dict[str, Any]:
    requested = path is not None or bool(os.getenv("CONFIG_PATH", "").strip())
    p = Path(path) if path is not None else default_config_path()
    if not p.exists():
        # A file someone asked for by name and that isn't there is a typo, not
        # an optional config. Only the implicit default may be absent, which is
        # what keeps `--mock` smoke runs working on a bare checkout.
        if requested:
            raise FileNotFoundError(f"Config file not found: {p}")
        return {}
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {p}")
    return data


def get_drone_ids(config: Dict[str, Any]) -> list[int]:
    return [int(x) for x in config.get("drones", {}).get("ids", [1, 2, 3])]
