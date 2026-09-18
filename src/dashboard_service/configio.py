"""Read and edit config.yaml without disturbing it.

Modelled on the mission console in CrazySwarm2-with-Mocap
(console/mission_console/configio.py): a small indentation-driven text editor
rather than a yaml.safe_load / yaml.dump round-trip, because a round-trip throws
away every comment and reflows the file. Edits here rewrite only the lines they
touch, and every write is parse-checked, backed up and returned as a diff.

Only what this config actually uses is understood: nested block mappings with
scalar values. Lists (ids, old_formation) are handled by swarm_sync instead.
"""

from __future__ import annotations

import difflib
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

CONFIG_YAML = Path(os.getenv("CONFIG_YAML", "/app/config.yaml"))
CRAZYFLIES_YAML = Path(os.getenv("CRAZYFLIES_YAML", "/app/crazyswarm_config/crazyflies.yaml"))
BACKUP_DIR = Path(os.getenv("CONFIG_BACKUP_DIR", "/app/config_backups"))

RESTART_HINT = "docker compose restart drone-control mission downed-simulator"


class ConfigError(Exception):
    """Something the user can fix, shown on the page instead of a 500."""


# --------------------------------------------------------------------------
# The settings the services actually read
# --------------------------------------------------------------------------
# Each entry: key path, what it means, and which service reads it. Anything not
# listed here is still editable in the raw editor; this is the guided list.
PARAMETERS: List[Dict[str, Any]] = [
    # drones: -- read by Docker 1
    {"keys": ["drones", "hover_z"], "label": "Hover height", "unit": "m", "type": "float",
     "read_by": "Docker 1, mission", "help": "How high drones sit after takeoff. Positive is up."},
    {"keys": ["drones", "takeoff_duration"], "label": "Takeoff time", "unit": "s", "type": "float",
     "read_by": "Docker 1", "help": "How long the takeoff command is given to finish."},
    {"keys": ["drones", "land_height"], "label": "Land height", "unit": "m", "type": "float",
     "read_by": "Docker 1", "help": "Height the drone is lowered to before the motors stop."},
    {"keys": ["drones", "land_duration"], "label": "Land time", "unit": "s", "type": "float",
     "read_by": "Docker 1", "help": "How long the landing command is given to finish."},
    {"keys": ["drones", "command_settle_seconds"], "label": "Settle after command", "unit": "s",
     "type": "float", "read_by": "Docker 1",
     "help": "Extra pause after takeoff or landing before the next command."},
    {"keys": ["drones", "group_mask"], "label": "Group mask", "unit": "", "type": "int",
     "read_by": "Docker 1", "help": "CrazySwarm group mask. 0 means every drone."},
    {"keys": ["drones", "control_timeout"], "label": "Bridge timeout", "unit": "s", "type": "float",
     "read_by": "Docker 1", "help": "How long Docker 1 waits for the CrazySwarm bridge to reply."},

    # mission: -- read by Docker 4
    {"keys": ["mission", "formation_spacing"], "label": "Spacing between spots", "unit": "m",
     "type": "float", "read_by": "mission",
     "help": "Gap between drones in a row, and between rows."},
    {"keys": ["mission", "safety_gap"], "label": "Safety gap", "unit": "m", "type": "float",
     "read_by": "mission",
     "help": "Closest two drones may come. A hop that would break this is not sent."},
    {"keys": ["mission", "waypoint_step"], "label": "Hop length", "unit": "m", "type": "float",
     "read_by": "mission", "help": "How far a drone moves per hop when flying to its new spot."},
    {"keys": ["mission", "move_velocity"], "label": "Speed", "unit": "m/s", "type": "float",
     "read_by": "mission", "help": "Speed asked for on each hop."},
    {"keys": ["mission", "target_tolerance"], "label": "Arrived within", "unit": "m",
     "type": "float", "read_by": "mission", "help": "How close counts as arrived."},
    {"keys": ["mission", "poll_interval"], "label": "Check for losses every", "unit": "s",
     "type": "float", "read_by": "mission", "help": "How often mission looks for a downed drone."},
    {"keys": ["mission", "movement_poll_interval"], "label": "Check position every", "unit": "s",
     "type": "float", "read_by": "mission", "help": "How often mission re-reads a drone mid-move."},
    {"keys": ["mission", "anchor_policy"], "label": "Where the formation sits", "unit": "",
     "type": "choice", "choices": ["initial_anchor", "active_centroid", "origin"],
     "read_by": "mission",
     "help": "initial_anchor keeps the first position. active_centroid re-centres on the "
             "survivors. origin puts the front row's middle at (0, 0)."},
    {"keys": ["mission", "include_downed_in_safety"], "label": "Avoid downed drones",
     "unit": "", "type": "bool", "read_by": "mission",
     "help": "Whether a drone on the floor still counts for the safety gap."},
    {"keys": ["mission", "command_timeout_margin"], "label": "Hop timeout margin", "unit": "s",
     "type": "float", "read_by": "mission",
     "help": "Added to the expected hop time before mission calls it stuck."},
    {"keys": ["mission", "control_ready_timeout"], "label": "Wait for Docker 1", "unit": "s",
     "type": "float", "read_by": "mission",
     "help": "How long mission waits for the backend before giving up at startup."},
    {"keys": ["mission", "max_move_seconds_per_drone"], "label": "Give up moving after",
     "unit": "s", "type": "float", "read_by": "mission",
     "help": "Longest a single drone may take to reach its spot."},
    {"keys": ["mission", "control_timeout"], "label": "Docker 1 request timeout", "unit": "s",
     "type": "float", "read_by": "mission", "help": "How long mission waits for a Docker 1 reply."},
    {"keys": ["mission", "backward_penalty"], "label": "Backward penalty", "unit": "",
     "type": "float", "read_by": "hungarian, via mission",
     "help": "Extra cost for sending a drone backwards. 0 turns it off."},
    {"keys": ["mission", "backward_threshold"], "label": "Backward allowance", "unit": "m",
     "type": "float", "read_by": "hungarian, via mission",
     "help": "How far backwards is free before the penalty applies."},
]


# --------------------------------------------------------------------------
# Indentation-driven YAML text editing
# --------------------------------------------------------------------------
class YamlText:
    """Set scalar values in well-formed block YAML, leaving everything else alone."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        self.original = "".join(self.lines)

    @staticmethod
    def _indent(line: str) -> int:
        return len(line) - len(line.lstrip())

    @staticmethod
    def _is_content(line: str) -> bool:
        stripped = line.strip()
        return bool(stripped) and not stripped.startswith("#")

    def _child_indent(self, lo: int, hi: int) -> Optional[int]:
        for i in range(lo, hi):
            if self._is_content(self.lines[i]):
                return self._indent(self.lines[i])
        return None

    def find(self, keys: Sequence[str]) -> Optional[int]:
        """Line index of the active line for this key path, or None."""
        lo, hi = 0, len(self.lines)
        hit = None
        for key in keys:
            indent = self._child_indent(lo, hi)
            if indent is None:
                return None
            pattern = re.compile(r"^\s{%d}%s:\s*(.*)$" % (indent, re.escape(key)))
            hit = None
            for i in range(lo, hi):
                line = self.lines[i]
                if not self._is_content(line) or self._indent(line) != indent:
                    continue
                if pattern.match(line):
                    hit = i
                    break
            if hit is None:
                return None
            # The block under this key ends at the next line indented no further.
            lo = hit + 1
            end = hi
            for i in range(hit + 1, hi):
                if self._is_content(self.lines[i]) and self._indent(self.lines[i]) <= indent:
                    end = i
                    break
            hi = end
        return hit

    def value(self, keys: Sequence[str]) -> Optional[str]:
        index = self.find(keys)
        if index is None:
            return None
        raw = self.lines[index].split(":", 1)[1]
        raw = re.sub(r"\s+#.*$", "", raw.rstrip("\n"))
        return raw.strip()

    def set_value(self, keys: Sequence[str], text: str) -> None:
        index = self.find(keys)
        if index is None:
            raise ConfigError(
                f"{'.'.join(keys)} is not in {self.path.name}; add the line by hand first"
            )
        line = self.lines[index].rstrip("\n")
        indent = " " * self._indent(line)
        comment = re.search(r"\s+#.*$", line)
        self.lines[index] = f"{indent}{keys[-1]}: {text}{comment.group(0) if comment else ''}\n"

    def text(self) -> str:
        return "".join(self.lines)

    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.original.splitlines(keepends=True),
                self.text().splitlines(keepends=True),
                f"{self.path.name} (before)",
                f"{self.path.name} (after)",
            )
        )


# --------------------------------------------------------------------------
# read / write
# --------------------------------------------------------------------------
def _format(value: Any, spec: Dict[str, Any]) -> str:
    kind = spec["type"]
    if kind == "bool":
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered not in {"true", "false"}:
                raise ConfigError(f"{spec['label']}: use true or false")
            return lowered
        return "true" if value else "false"
    if kind == "choice":
        text = str(value).strip()
        if text not in spec["choices"]:
            raise ConfigError(f"{spec['label']}: pick one of {', '.join(spec['choices'])}")
        return text
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{spec['label']}: '{value}' is not a number") from exc
    if kind == "int":
        if number != int(number):
            raise ConfigError(f"{spec['label']}: must be a whole number")
        return str(int(number))
    if number < 0:
        raise ConfigError(f"{spec['label']}: must not be negative")
    out = f"{number:g}"
    return out if ("." in out or "e" in out) else out + ".0"


def backup(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H-%M-%S")
    destination = BACKUP_DIR / f"{path.name}.{stamp}.bak"
    destination.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def _check(text: str) -> Dict[str, Any]:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"that is not valid YAML, nothing was written:\n{exc}") from exc
    if not isinstance(doc, dict):
        raise ConfigError("config.yaml must be a mapping, nothing was written")
    return doc


def warnings_for(doc: Dict[str, Any]) -> List[str]:
    """Checks nothing in the stack makes for itself."""
    out: List[str] = []
    drones = doc.get("drones") or {}
    mission = doc.get("mission") or {}
    ids = drones.get("ids") or []
    rows = mission.get("old_formation") or []
    if ids and rows and sum(rows) != len(ids):
        out.append(
            f"rows {rows} make {sum(rows)} spots but there are {len(ids)} drones; "
            "reforming will fail or leave spots empty (README_EXPLAINED 12.1)"
        )
    if rows and any(b <= a for a, b in zip(rows, rows[1:])):
        out.append(
            f"rows {rows} repeat or narrow; shapes like this can leave drones stuck "
            "during reformation (README_EXPLAINED 12.10)"
        )
    gap = mission.get("safety_gap")
    spacing = mission.get("formation_spacing")
    if isinstance(gap, (int, float)) and isinstance(spacing, (int, float)) and gap > spacing:
        out.append(
            f"safety gap {gap} m is wider than the spacing between spots {spacing} m; "
            "drones will block each other and stop short"
        )
    step = mission.get("waypoint_step")
    if isinstance(gap, (int, float)) and isinstance(step, (int, float)) and step > gap:
        out.append(f"hop length {step} m is longer than the safety gap {gap} m")
    names = drones.get("vehicle_names") or {}
    missing = [i for i in ids if str(i) not in {str(k) for k in names}]
    if missing:
        out.append(f"no vehicle_names entry for drone {missing}")
    return out


def _write(path: Path, text: str) -> Tuple[Optional[str], str]:
    """Parse-check, back up, write in place. -> (backup path, diff)."""
    before = path.read_text(encoding="utf-8")
    if before == text:
        return None, ""
    saved = backup(path)
    # Written in place: config.yaml is bind-mounted as a single file, so it must
    # not be replaced by a rename.
    path.write_text(text, encoding="utf-8")
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            text.splitlines(keepends=True),
            f"{path.name} (before)",
            f"{path.name} (after)",
        )
    )
    return str(saved), diff


FILES = {
    "config": {"path": CONFIG_YAML, "label": "config.yaml", "editable": True,
               "blurb": "This stack's settings. Read once, when each service starts."},
    "crazyflies": {"path": CRAZYFLIES_YAML, "label": "crazyflies.yaml", "editable": False,
                   "blurb": "CrazySwarm's fleet list. Shown read-only; edit it with "
                            "./scripts/swarm_config.py or the CrazySwarm console."},
}


def read_file(key: str) -> Dict[str, Any]:
    spec = FILES.get(key)
    if spec is None:
        raise ConfigError(f"unknown file '{key}'")
    path = Path(spec["path"])
    if not path.exists():
        raise ConfigError(f"{spec['label']} not found at {path}")
    text = path.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text)
        parse_error = None
    except yaml.YAMLError as exc:
        doc, parse_error = None, str(exc)
    return {
        "key": key,
        "path": str(path),
        "label": spec["label"],
        "blurb": spec["blurb"],
        "editable": spec["editable"],
        "text": text,
        "parse_error": parse_error,
        "warnings": warnings_for(doc) if key == "config" and isinstance(doc, dict) else [],
    }


def write_raw(text: str) -> Dict[str, Any]:
    doc = _check(text)
    saved, diff = _write(Path(CONFIG_YAML), text)
    return {
        "changed": bool(diff),
        "diff": diff,
        "backup": saved,
        "warnings": warnings_for(doc),
        "restart": RESTART_HINT,
    }


def read_parameters() -> Dict[str, Any]:
    editor = YamlText(Path(CONFIG_YAML))
    doc = yaml.safe_load(editor.original)
    items = []
    for spec in PARAMETERS:
        raw = editor.value(spec["keys"])
        items.append({
            "id": ".".join(spec["keys"]),
            "keys": spec["keys"],
            "section": spec["keys"][0],
            "label": spec["label"],
            "unit": spec["unit"],
            "type": spec["type"],
            "choices": spec.get("choices"),
            "read_by": spec["read_by"],
            "help": spec["help"],
            "value": raw,
            "present": raw is not None,
        })
    return {
        "path": str(CONFIG_YAML),
        "parameters": items,
        "warnings": warnings_for(doc) if isinstance(doc, dict) else [],
        "restart": RESTART_HINT,
    }


def write_parameters(edits: Iterable[Dict[str, Any]], dry_run: bool = False) -> Dict[str, Any]:
    by_id = {".".join(spec["keys"]): spec for spec in PARAMETERS}
    editor = YamlText(Path(CONFIG_YAML))
    touched = []
    for edit in edits:
        spec = by_id.get(str(edit.get("id")))
        if spec is None:
            raise ConfigError(f"unknown setting '{edit.get('id')}'")
        editor.set_value(spec["keys"], _format(edit.get("value"), spec))
        touched.append(spec["label"])

    text = editor.text()
    doc = _check(text)
    diff = editor.diff()
    if dry_run:
        return {"changed": bool(diff), "diff": diff, "backup": None,
                "warnings": warnings_for(doc), "restart": RESTART_HINT, "changed_settings": touched}

    saved, written_diff = _write(Path(CONFIG_YAML), text)
    return {
        "changed": bool(written_diff),
        "diff": written_diff,
        "backup": saved,
        "warnings": warnings_for(doc),
        "restart": RESTART_HINT,
        "changed_settings": touched,
    }
