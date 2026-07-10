from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np

from cube_app.vision import detect_cube_face


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CORNERS = {
    "U": [[0.10, 0.20], [0.80, 0.21], [0.80, 0.61], [0.10, 0.61]],
    "R": [[0.09, 0.27], [0.87, 0.29], [0.80, 0.81], [0.06, 0.72]],
    "F": [[0.16, 0.33], [0.90, 0.33], [0.90, 0.74], [0.16, 0.74]],
    "D": [[0.10, 0.35], [0.87, 0.36], [0.87, 0.79], [0.10, 0.79]],
    "L": [[0.14, 0.36], [0.92, 0.35], [0.95, 0.78], [0.16, 0.80]],
    "B": [[0.11, 0.33], [0.93, 0.32], [0.89, 0.76], [0.14, 0.77]],
}


def frontend_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise AssertionError(f"cannot read {path}")
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
        raise AssertionError(f"cannot encode {path}")
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def corner_error(actual: np.ndarray, expected: np.ndarray) -> float:
    variants = []
    for points in (actual, actual[::-1]):
        for shift in range(4):
            variants.append(float(np.mean(np.linalg.norm(np.roll(points, shift, axis=0) - expected, axis=1))))
    return min(variants)


class RealImageRegressionTests(unittest.TestCase):
    def test_initial_images_locate_the_complete_cube_face(self) -> None:
        failures = []
        for face, expected_values in EXPECTED_CORNERS.items():
            image = frontend_image(ROOT / "initial" / f"{face}.jpg")
            result = detect_cube_face(image)
            if result is None:
                failures.append(f"{face}: no detection")
                continue
            actual = np.array(result.corners, np.float32)
            expected = np.array(expected_values, np.float32)
            error = corner_error(actual, expected)
            if error >= 0.065:
                failures.append(
                    f"{face}: corner error {error:.3f}, method={result.method}, corners={result.corners}"
                )
        self.assertFalse(failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
