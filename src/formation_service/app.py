from __future__ import annotations

from typing import List

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Docker 3 - Formation Service")

# Which world direction the formation faces. "+y" is the original convention:
# the front row sits at y=0 and the rows behind it step down in y. "+x" is the
# same shape given a quarter turn, for a flight area whose long side is x.
FRONT_AXES = ("+y", "+x")


class FormationRequest(BaseModel):
    old_formation: List[int] = Field(default_factory=lambda: [1, 3, 4, 3, 2, 1])
    downed_drones: int = 0
    spacing: float = 10.0
    policy: str = "front_compact"
    front_axis: str = "+y"


def compact_rows(old_formation: List[int], downed_drones: int) -> List[int]:
    total = int(sum(old_formation))
    active = total - int(downed_drones)
    if active < 0:
        raise ValueError(f"downed_drones={downed_drones} exceeds total drones={total}")
    if active == 0:
        return []

    # Fill from the front rows while keeping the original maximum capacity per row.
    rows: List[int] = []
    remaining = active
    for capacity in old_formation:
        if remaining <= 0:
            break
        use = min(int(capacity), remaining)
        rows.append(use)
        remaining -= use
    return rows


def make_slots(rows: List[int], spacing: float, front_axis: str = "+y") -> np.ndarray:
    """Turn row widths into relative (x, y) slots.

    Each row is centred on the line through the front row, and every row after
    the first sits one spacing further back. `front_axis` picks which way that
    is: with "+y" the rows step back along -y and spread along x, with "+x"
    they step back along -x and spread along y.
    """
    if front_axis not in FRONT_AXES:
        raise ValueError(
            f"front_axis={front_axis!r} is not one of {', '.join(FRONT_AXES)}"
        )

    slots = []
    for row_idx, count in enumerate(rows):
        depth = -float(row_idx) * float(spacing)
        if count == 1:
            offsets = [0.0]
        else:
            start = -0.5 * float(spacing) * (int(count) - 1)
            offsets = [start + i * float(spacing) for i in range(int(count))]
        for offset in offsets:
            if front_axis == "+x":
                slots.append([depth, float(offset)])
            else:
                slots.append([float(offset), depth])
    return np.asarray(slots, dtype=float)


@app.get("/health")
def health():
    return {"status": "ok", "service": "formation"}


@app.post("/formation")
def formation(req: FormationRequest):
    if req.policy != "front_compact":
        raise HTTPException(status_code=400, detail="Only policy='front_compact' is currently implemented")
    if req.front_axis not in FRONT_AXES:
        raise HTTPException(
            status_code=400,
            detail=f"front_axis must be one of {', '.join(FRONT_AXES)}, got {req.front_axis!r}",
        )
    try:
        rows = compact_rows(req.old_formation, req.downed_drones)
        slots = make_slots(rows, req.spacing, req.front_axis)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "old_formation": req.old_formation,
        "downed_drones": int(req.downed_drones),
        "new_formation": rows,
        "spacing": float(req.spacing),
        "front_axis": req.front_axis,
        "slots_relative": slots.tolist(),
        "num_slots": int(len(slots)),
    }
