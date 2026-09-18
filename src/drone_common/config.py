from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def load_config(path: str | Path = "/app/config.yaml") -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {p}")
    return data


def get_drone_ids(config: Dict[str, Any]) -> list[int]:
    return [int(x) for x in config.get("drones", {}).get("ids", [1, 2, 3])]
