"""Render the six detected faces for a human reference-label check."""

from pathlib import Path

import cv2
import numpy as np

from cube_app.vision import detect_cube_face

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "benchmarks" / "initial12-reference-grid.png"
panels = []
for face in "URFDLB":
    path = ROOT / "initial" / f"{face}12.jpg"
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    height, width = image.shape[:2]
    scale = min(1.0, 1600 / max(width, height))
    if scale < 1:
        image = cv2.resize(image, (round(width * scale), round(height * scale)))
    detection = detect_cube_face(image, grid_size=3)
    if detection is None:
        raise RuntimeError(f"Detection failed: {path}")
    height, width = image.shape[:2]
    corners = np.array([[x * width, y * height] for x, y in detection.corners], np.float32)
    target = np.array([[0, 0], [299, 0], [299, 299], [0, 299]], np.float32)
    warped = cv2.warpPerspective(image, cv2.getPerspectiveTransform(corners, target), (300, 300))
    for coordinate in (100, 200):
        cv2.line(warped, (coordinate, 0), (coordinate, 299), (0, 0, 0), 2)
        cv2.line(warped, (0, coordinate), (299, coordinate), (0, 0, 0), 2)
    panel = np.full((340, 300, 3), 240, np.uint8)
    panel[40:, :] = warped
    cv2.putText(panel, face, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    panels.append(panel)
montage = np.concatenate([np.concatenate(panels[:3], axis=1), np.concatenate(panels[3:], axis=1)], axis=0)
OUT.parent.mkdir(parents=True, exist_ok=True)
cv2.imencode(".png", montage)[1].tofile(str(OUT))
print(OUT)
