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


def read_frontend_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"cannot decode {path}")
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


def extract_patches(face: str, group: str | None = None, browser_report: Path | None = None) -> list[str]:
    suffix = group or ""
    grid_size = 2 if group in {"3", "4", "6", "7"} else 3
    if browser_report is not None:
        # PNG previews are the lossless pixels read by the actual page's sampler,
        # including its Canvas scaling, detector input and pixel-center homography.
        # They are never re-JPEG-encoded, resized, rotated or re-detected here.
        report = json.loads(browser_report.read_text(encoding="utf-8"))
        case = next(item for item in report["cases"] if item["name"] == f"initial-{group}")
        path = browser_report.parent / case["previewPaths"][face]
        warped = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if warped is None or warped.shape[:2] != (240, 240):
            raise RuntimeError(f"invalid actual browser preview {path}")
    else:
        image = read_frontend_image(ROOT / "initial" / f"{face}{suffix}.jpg")
        detection = detect_cube_face(image, grid_size=grid_size)
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
    points = tuple((index + 0.5) / grid_size for index in range(grid_size))
    for row, y_ratio in enumerate(points):
        for column, x_ratio in enumerate(points):
            center_x = round(240 * x_ratio)
            center_y = round(240 * y_ratio)
            if grid_size == 3 and row == 1 and column == 1:
                patch = rgba[center_y - 33 : center_y + 34, center_x - 33 : center_x + 34]
                yy, xx = np.ogrid[-33:34, -33:34]
                patch = patch[np.maximum(np.abs(xx), np.abs(yy)) >= 21]
            else:
                patch = rgba[center_y - 35 : center_y + 36, center_x - 35 : center_x + 36]
            patches.append(base64.b64encode(patch.tobytes()).decode("ascii"))
    return patches


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=("1", "2", "3", "4", "5", "6", "7", "8", "12", "16"), default=None)
    parser.add_argument("--browser-report", type=Path, help="Use saved actual Canvas pixels instead of the OpenCV approximation")
    args = parser.parse_args()
    print(json.dumps({face: extract_patches(face, args.group, args.browser_report) for face in FACE_ORDER}, ensure_ascii=True))
