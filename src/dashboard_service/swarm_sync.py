"""Copy the enabled drones from CrazySwarm's crazyflies.yaml into config.yaml.

The real work is done by scripts/swarm_config.py, which already knows how to read
crazyflies.yaml, turn a radio address into the drone id the bridge reports, and
rewrite config.yaml line by line without disturbing comments or layout. This
module is a thin, read-only-on-the-CrazySwarm-side wrapper around it:

* crazyflies.yaml is only ever read
* config.yaml is only written by apply(), and a timestamped backup is kept
* swarm_config.die() calls sys.exit, which would stop the web server, so every
  call goes through _guard() and comes back as a SyncError the page can show
"""

from __future__ import annotations

import difflib
import importlib.util
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

CRAZYFLIES_YAML = Path(os.getenv("CRAZYFLIES_YAML", "/app/crazyswarm_config/crazyflies.yaml"))
CONFIG_YAML = Path(os.getenv("CONFIG_YAML", "/app/config.yaml"))
BACKUP_DIR = Path(os.getenv("CONFIG_BACKUP_DIR", "/app/config_backups"))

RESTART_HINT = "docker compose restart drone-control mission downed-simulator"


class SyncError(Exception):
    """Something the user can fix, shown on the page instead of a 500."""


_module = None


def swarm_config():
    """Import scripts/swarm_config.py, from the image or from a checkout."""
    global _module
    if _module is not None:
        return _module

    candidates = [
        os.getenv("SWARM_CONFIG_PY"),
        "/app/tools/swarm_config.py",
        str(Path(__file__).resolve().parents[2] / "scripts" / "swarm_config.py"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            spec = importlib.util.spec_from_file_location("swarm_config", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _module = module
            return _module
    raise SyncError("swarm_config.py was not found; the dashboard image may be out of date")


def _guard(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except SystemExit as exc:  # swarm_config.die()
        message = str(exc.code if exc.code is not None else exc)
        raise SyncError(message.removeprefix("error: ")) from exc


def suggest_formation(count: int) -> List[int]:
    """Rows, front first, that add up to `count` and always widen.

    A row that repeats or narrows can leave drones stuck during reformation
    (README_EXPLAINED 12.10), so every row here is strictly wider than the one in
    front of it: 4 -> [1, 3], 5 -> [2, 3], 9 -> [2, 3, 4]. More rows is better,
    so this picks the deepest shape that still fits.
    """
    if count <= 0:
        return []
    best = [count]
    for rows in range(2, count + 1):
        base = count - rows * (rows - 1) // 2
        if base < rows:
            break
        width, extra = divmod(base, rows)
        shape = [width + i for i in range(rows)]
        for i in range(extra):  # widen from the back, which keeps rows increasing
            shape[rows - 1 - i] += 1
        best = shape
    return best


def _plan(formation_override: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    sc = swarm_config()

    if not CRAZYFLIES_YAML.exists():
        raise SyncError(
            f"crazyflies.yaml not found at {CRAZYFLIES_YAML}. "
            "Set CRAZYFLIES_DIR in .env to the CrazySwarm config folder, then recreate the dashboard."
        )
    if not CONFIG_YAML.exists():
        raise SyncError(f"config.yaml not found at {CONFIG_YAML}")

    cf_lines = _guard(sc.load, str(CRAZYFLIES_YAML))
    robots = _guard(sc.parse_robots, cf_lines)
    enabled = sorted((r for r in robots.values() if r.enabled), key=lambda r: sc.api_id(r.uri))
    if not enabled:
        raise SyncError("no drones are enabled in crazyflies.yaml")

    ids = [sc.api_id(r.uri) for r in enabled]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SyncError(
            f"two enabled drones share drone id {duplicates}; fix their radio addresses first"
        )

    old_lines = _guard(sc.load, str(CONFIG_YAML))
    current_ids, current_formation = _guard(sc.read_reformation, old_lines)

    warnings: List[str] = []
    if formation_override is not None:
        formation = [int(v) for v in formation_override]
        source = "yours"
    elif current_formation is not None and sum(current_formation) == len(ids):
        formation = list(current_formation)
        source = "unchanged"
    else:
        formation = suggest_formation(len(ids))
        source = "suggested"

    if any(v < 1 for v in formation):
        raise SyncError("every row needs at least one drone")
    if sum(formation) != len(ids):
        raise SyncError(
            f"rows {formation} make {sum(formation)} spots, but there are {len(ids)} drones. "
            f"Try {', '.join(str(v) for v in suggest_formation(len(ids)))}"
        )
    if any(b <= a for a, b in zip(formation, formation[1:])):
        warnings.append(
            f"rows {formation} repeat or narrow. Shapes like this can leave drones stuck "
            "during reformation (README_EXPLAINED 12.10)."
        )

    new_lines = list(old_lines)
    _guard(sc.write_reformation, new_lines, enabled, formation)
    # swarm_config re-parses the edited text as YAML and checks it says what we meant.
    _guard(sc.validate, cf_lines, new_lines, enabled, formation)

    diff = "".join(
        difflib.unified_diff(old_lines, new_lines, "config.yaml (before)", "config.yaml (after)")
    )
    return {
        "crazyflies_path": str(CRAZYFLIES_YAML),
        "config_path": str(CONFIG_YAML),
        "drones": [
            {
                "name": r.name,
                "uri": r.uri,
                "id": sc.api_id(r.uri),
                "initial_position": r.value("initial_position"),
            }
            for r in enabled
        ],
        "current": {"ids": current_ids, "formation": current_formation},
        "proposed": {"ids": ids, "formation": formation, "formation_source": source},
        "warnings": warnings,
        "changed": new_lines != old_lines,
        "diff": diff,
        "restart": RESTART_HINT,
        "_old_lines": old_lines,
        "_new_lines": new_lines,
    }


def _public(plan: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in plan.items() if not k.startswith("_")}


def preview(formation: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    return _public(_plan(formation))


def apply(formation: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    plan = _plan(formation)
    result = _public(plan)
    if not plan["changed"]:
        result["backup"] = None
        return result

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"config.yaml.{time.strftime('%Y-%m-%dT%H-%M-%S')}.bak"
    backup.write_text("".join(plan["_old_lines"]), encoding="utf-8")
    # Written in place: config.yaml is bind-mounted as a single file, so it must
    # not be replaced by a rename.
    CONFIG_YAML.write_text("".join(plan["_new_lines"]), encoding="utf-8")

    result["backup"] = str(backup)
    return result
