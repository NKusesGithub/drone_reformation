from __future__ import annotations

from typing import List

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Docker 3 - Formation Service")


class FormationRequest(BaseModel):
    old_formation: List[int] = Field(default_factory=lambda: [1, 3, 4, 3, 2, 1])
    downed_drones: int = 0
    spacing: float = 10.0
    policy: str = "front_compact"


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


def make_slots(rows: List[int], spacing: float) -> np.ndarray:
    slots = []
    for row_idx, count in enumerate(rows):
        y = -float(row_idx) * float(spacing)
        if count == 1:
            xs = [0.0]
        else:
            start_x = -0.5 * float(spacing) * (int(count) - 1)
            xs = [start_x + i * float(spacing) for i in range(int(count))]
        for x in xs:
            slots.append([float(x), float(y)])
    return np.asarray(slots, dtype=float)


@app.get("/health")
def health():
    return {"status": "ok", "service": "formation"}


@app.post("/formation")
def formation(req: FormationRequest):
    if req.policy != "front_compact":
        raise HTTPException(status_code=400, detail="Only policy='front_compact' is currently implemented")
    try:
        rows = compact_rows(req.old_formation, req.downed_drones)
        slots = make_slots(rows, req.spacing)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "old_formation": req.old_formation,
        "downed_drones": int(req.downed_drones),
        "new_formation": rows,
        "spacing": float(req.spacing),
        "slots_relative": slots.tolist(),
        "num_slots": int(len(slots)),
    }
