from __future__ import annotations

import base64
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from cube_app.vision import detect_cube_face


FACE_ORDER = "URFDLB"


parser = argparse.ArgumentParser()
parser.add_argument("--group", choices=("1", "2"), default=None)
args = parser.parse_args()


def read_frontend_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    height, width = image.shape[:2]
    scale = min(1.0, 1600 / max(width, height))
    if scale < 1:
        image = cv2.resize(
            image,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError(f"cannot encode {path}")
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def extract_patches(face: str) -> list[str]:
    suffix = args.group or ""
    image = read_frontend_image(ROOT / "initial" / f"{face}{suffix}.jpg")
    detection = detect_cube_face(image)
    if detection is None:
        raise RuntimeError(f"cannot detect {face}")
    height, width = image.shape[:2]
    corners = np.array(
        [[x * width, y * height] for x, y in detection.corners],
        dtype=np.float32,
    )
    target = np.array([[0, 0], [239, 0], [239, 239], [0, 239]], np.float32)
    transform = cv2.getPerspectiveTransform(corners, target)
    warped = cv2.warpPerspective(image, transform, (240, 240), flags=cv2.INTER_LINEAR)
    rgba = cv2.cvtColor(warped, cv2.COLOR_BGR2RGBA)
    patches = []
    for row, y_ratio in enumerate((1 / 6, 1 / 2, 5 / 6)):
        for column, x_ratio in enumerate((1 / 6, 1 / 2, 5 / 6)):
            center_x = round(240 * x_ratio)
            center_y = round(240 * y_ratio)
            if row == 1 and column == 1:
                patch = rgba[center_y - 33 : center_y + 34, center_x - 33 : center_x + 34]
                yy, xx = np.ogrid[-33:34, -33:34]
                patch = patch[np.maximum(np.abs(xx), np.abs(yy)) >= 21]
            else:
                patch = rgba[center_y - 35 : center_y + 36, center_x - 35 : center_x + 36]
            patches.append(base64.b64encode(patch.tobytes()).decode("ascii"))
    return patches


print(json.dumps({face: extract_patches(face) for face in FACE_ORDER}, ensure_ascii=True))
