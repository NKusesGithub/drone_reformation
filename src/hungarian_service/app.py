from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from scipy.optimize import linear_sum_assignment

app = FastAPI(title="Docker 2 - Hungarian Assignment Service")


class AssignmentRequest(BaseModel):
    active_ids: List[int]
    old_positions: Dict[int, Tuple[float, float]]
    target_positions: List[Tuple[float, float]]
    backward_penalty: float = 0.0
    backward_threshold: float = 0.0
    cascade_front_first: bool = True
    spacing: float = 50.0
    forward_jump_penalty: float = 100.0
    forward_jump_threshold_multiplier: float = 2.0

def _as_pos_dict(data: Dict[int, Tuple[float, float]]) -> Dict[int, np.ndarray]:
    return {int(k): np.asarray(v, dtype=float) for k, v in data.items()}


@app.get("/health")
def health():
    return {"status": "ok", "service": "hungarian"}


@app.post("/assign")
def assign(req: AssignmentRequest):
    active_ids = [int(x) for x in req.active_ids]
    old_pos = _as_pos_dict(req.old_positions)
    missing = [i for i in active_ids if i not in old_pos]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing old_positions for active drone IDs: {missing}")

    if len(req.target_positions) < len(active_ids):
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {len(active_ids)} target positions, got {len(req.target_positions)}",
        )

    cur = np.asarray([old_pos[i] for i in active_ids], dtype=float)
    targets = np.asarray(req.target_positions, dtype=float)
    cost = np.linalg.norm(cur[:, None, :] - targets[None, :, :], axis=2)

    # Option C: penalize large forward jumps
    #
    # Coordinate convention:
    #   front rows have larger y, e.g. y = 0
    #   rear rows have smaller y, e.g. y = -10, -20, ...
    #
    # Therefore, moving forward means:
    #   target_y > current_y
    #
    # This discourages rear drones from jumping all the way to front-row slots.
    forward_jump_threshold = float(req.forward_jump_threshold_multiplier) * float(req.spacing)

    for ri in range(len(active_ids)):
        cur_y = float(cur[ri, 1])

        for si in range(len(targets)):
            target_y = float(targets[si, 1])
            forward_delta = target_y - cur_y

            if forward_delta > forward_jump_threshold:
                cost[ri, si] += req.forward_jump_penalty

    # Optional: discourage assignments that move a drone backward too far.
    if req.backward_penalty > 0.0:
        for ri, drone_id in enumerate(active_ids):
            for si in range(len(targets)):
                if targets[si, 1] < cur[ri, 1] - float(req.backward_threshold):
                    cost[ri, si] += float(req.backward_penalty)

    row_ind, col_ind = linear_sum_assignment(cost)

    assignment = []
    for r, c in zip(row_ind, col_ind):
        drone_id = active_ids[int(r)]
        target = targets[int(c)]
        current = cur[int(r)]
        assignment.append(
            {
                "drone_id": int(drone_id),
                "slot_idx": int(c),
                "current_position": current.tolist(),
                "target_position": target.tolist(),
                "travel_distance": float(np.linalg.norm(current - target)),
                "delta_y": float(target[1] - current[1]),
            }
        )

    if req.cascade_front_first:
        assignment.sort(key=lambda item: -old_pos[int(item["drone_id"])][1])
    for rank, item in enumerate(assignment):
        item["cascade_rank"] = rank + 1

    return {
        "active_ids": active_ids,
        "target_positions": targets.tolist(),
        "assignment": assignment,
        "summary": {
            "num_active_drones": len(active_ids),
            "num_target_positions": len(targets),
            "total_travel_distance": float(sum(x["travel_distance"] for x in assignment)),
        },
    }
