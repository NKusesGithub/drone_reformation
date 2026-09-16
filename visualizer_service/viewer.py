from __future__ import annotations

import argparse
import os
import time
from typing import Dict, Tuple

import cv2
import numpy as np
import requests

DRONE_CONTROL_URL = os.getenv("DRONE_CONTROL_URL", "http://drone-control:8000").rstrip("/")


def world_to_pixel(x: float, y: float, width: int, height: int, scale: float) -> Tuple[int, int]:
    px = int(width / 2 + x * scale)
    py = int(height / 2 - y * scale)
    return px, py


def draw_cross(img: np.ndarray, center: Tuple[int, int], radius: int, color: Tuple[int, int, int], thickness: int = 2) -> None:
    x, y = center
    cv2.line(img, (x - radius, y - radius), (x + radius, y + radius), color, thickness)
    cv2.line(img, (x - radius, y + radius), (x + radius, y - radius), color, thickness)


def fetch_states(url: str) -> Dict[int, dict]:
    resp = requests.get(f"{url.rstrip('/')}/states_vis", timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return {int(k): v for k, v in data.items()}


def draw_frame(states: Dict[int, dict], width: int, height: int, scale: float, safety_gap: float) -> np.ndarray:
    img = np.full((height, width, 3), 245, dtype=np.uint8)

    # Grid axes.
    cv2.line(img, (width // 2, 0), (width // 2, height), (220, 220, 220), 1)
    cv2.line(img, (0, height // 2), (width, height // 2), (220, 220, 220), 1)

    for drone_id, st in sorted(states.items()):
        x = float(st.get("x", 0.0))
        y = float(st.get("y", 0.0))
        downed = str(st.get("status", "")).lower() == "down" or bool(st.get("downed") or st.get("landed"))
        px, py = world_to_pixel(x, y, width, height, scale)
        safety_r_px = max(1, int(float(safety_gap) * scale))
        cv2.circle(img, (px, py), safety_r_px, (205, 205, 205), 1)

        if downed:
            draw_cross(img, (px, py), 10, (0, 0, 255), 3)
            label = f"D{drone_id} DOWN"
            color = (0, 0, 255)
        else:
            cv2.circle(img, (px, py), 8, (0, 160, 0), -1)
            label = f"D{drone_id}"
            color = (0, 120, 0)
        cv2.putText(img, label, (px + 12, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    cv2.putText(
        img,
        "Docker 6 visualizer: polling Docker 1 /states | green=active, red cross=downed",
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (20, 20, 20),
        1,
        cv2.LINE_AA,
    )
    return img


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCV visualizer for centralized drone-control service")
    parser.add_argument("--control-url", default=DRONE_CONTROL_URL)
    parser.add_argument("--width", type=int, default=int(os.getenv("VIS_WIDTH", "900")))
    parser.add_argument("--height", type=int, default=int(os.getenv("VIS_HEIGHT", "700")))
    parser.add_argument("--scale", type=float, default=float(os.getenv("VIS_SCALE", "8.0")))
    parser.add_argument("--safety-gap", type=float, default=float(os.getenv("SAFETY_GAP", "5.0")))
    parser.add_argument("--fps", type=float, default=float(os.getenv("VIS_FPS", "5.0")))
    parser.add_argument("--headless-output", default=os.getenv("VIS_HEADLESS_OUTPUT", ""))
    args = parser.parse_args()

    delay = max(1, int(1000.0 / max(args.fps, 0.1)))
    while True:
        try:
            states = fetch_states(args.control_url)
            frame = draw_frame(states, args.width, args.height, args.scale, args.safety_gap)
        except Exception as exc:
            frame = np.full((args.height, args.width, 3), 245, dtype=np.uint8)
            cv2.putText(frame, f"Visualizer error: {exc}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        if args.headless_output:
            cv2.imwrite(args.headless_output, frame)
        else:
            cv2.imshow("Drone Reformation Status", frame)
            key = cv2.waitKey(delay) & 0xFF
            if key in {27, ord("q"), ord("c")}:
                break
        time.sleep(max(0.0, 1.0 / max(args.fps, 0.1)))

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
