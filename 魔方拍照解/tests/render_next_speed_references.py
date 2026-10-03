"""Render unlabeled real-photo evidence for independent human annotation.

No color classifier is imported. The grid is top-left to bottom-right without
rotation, matching the page's URFDLB photo slots and 3x3 sticker order. OpenCV
sampling approximates browser Canvas; verify_next_speed_photos.cjs records the
actual browser pipeline separately.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from extract_real_patches import FACE_ORDER, ROOT, read_frontend_image
from cube_app.vision import detect_cube_face


def render_group(group: str, output: Path) -> None:
    raw_panels, grid_panels = [], []
    for face in FACE_ORDER:
        path = ROOT / "initial" / f"{face}{group}.jpg"
        image = read_frontend_image(path)
        height, width = image.shape[:2]
        detection = detect_cube_face(image, grid_size=3)
        if detection is None:
            raise RuntimeError(f"Detection failed: {path}")
        corners = np.array([[x * width, y * height] for x, y in detection.corners], np.float32)
        target = np.array([[0, 0], [299, 0], [299, 299], [0, 299]], np.float32)
        warped = cv2.warpPerspective(image, cv2.getPerspectiveTransform(corners, target), (300, 300))
        for coordinate in (100, 200):
            cv2.line(warped, (coordinate, 0), (coordinate, 299), (0, 0, 0), 2)
            cv2.line(warped, (0, coordinate), (299, coordinate), (0, 0, 0), 2)
        grid_panel = np.full((340, 300, 3), 240, np.uint8)
        grid_panel[40:] = warped
        cv2.putText(grid_panel, f"{face}{group}", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        grid_panels.append(grid_panel)
        raw_panel = np.full((440, 300, 3), 240, np.uint8)
        scale = min(300 / width, 400 / height)
        thumbnail = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        marked = image.copy()
        cv2.polylines(marked, [corners.astype(np.int32)], True, (255, 255, 255), 6)
        thumbnail = cv2.resize(marked, (thumbnail.shape[1], thumbnail.shape[0]), interpolation=cv2.INTER_AREA)
        x = (300 - thumbnail.shape[1]) // 2
        raw_panel[40:40 + thumbnail.shape[0], x:x + thumbnail.shape[1]] = thumbnail
        cv2.putText(raw_panel, f"{face}{group}", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        raw_panels.append(raw_panel)
    output.mkdir(parents=True, exist_ok=True)
    for suffix, panels in (("reference-grid", grid_panels), ("photo-overview", raw_panels)):
        montage = np.concatenate([np.concatenate(panels[:3], axis=1), np.concatenate(panels[3:], axis=1)])
        target = output / f"initial-{group}-{suffix}.png"
        cv2.imencode(".png", montage)[1].tofile(str(target))
        print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", nargs="+", default=["1", "12", "2", "5", "8", "16"])
    parser.add_argument("--output", type=Path, default=ROOT / "docs/benchmarks/next-speed-2026-10-02")
    args = parser.parse_args()
    for group in args.groups:
        render_group(group, args.output)
