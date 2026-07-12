from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np
import pytest

from cube_app.vision import _score_face_candidate, assess_detected_face_quality, detect_cube_face


ROOT = Path(__file__).resolve().parents[1]
FACE_ORDER = "URFDLB"
AVAILABLE_GROUPS = tuple(
    group
    for group in ("1", "2", "3", "4", "5", "6", "7")
    if all((ROOT / "initial" / f"{face}{group}.jpg").is_file() for face in FACE_ORDER)
)


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


@pytest.mark.vision_real
@unittest.skipUnless(AVAILABLE_GROUPS, "需要 initial/ 目录中的一组完整实拍图片")
class RealImageRegressionTests(unittest.TestCase):
    def test_initial_images_locate_the_complete_cube_face(self) -> None:
        failures = []
        confidences = []
        for group in AVAILABLE_GROUPS:
            for face in FACE_ORDER:
                image = frontend_image(ROOT / "initial" / f"{face}{group}.jpg")
                grid_size = 2 if group in {"3", "4", "6", "7"} else 3
                result = detect_cube_face(image, grid_size=grid_size)
                if result is None:
                    failures.append(f"{face}{group}: no detection")
                    continue
                corners = np.array(result.corners, np.float32)
                confidences.append(result.confidence)
                quality = assess_detected_face_quality(image, result)
                if not quality["valid"]:
                    failures.append(f"{face}{group}: capture quality rejected: {quality}")
                area = abs(float(cv2.contourArea(corners)))
                minimum_area = 0.08 if grid_size == 2 else 0.10
                if result.score < 0.50 or area < minimum_area or np.any(corners < 0) or np.any(corners > 1):
                    failures.append(
                        f"{face}{group}: score={result.score}, area={area:.3f}, "
                        f"method={result.method}, corners={result.corners}"
                    )
        self.assertFalse(failures, "\n".join(failures))
        self.assertGreater(
            max(confidences) - min(confidences),
            10,
            "真实图片置信度应能区分稳定识别和较弱识别",
        )

    def test_two_by_two_complete_face_beats_half_cell_down_crop(self) -> None:
        image = frontend_image(ROOT / "initial" / "D3.jpg")
        result = detect_cube_face(image, grid_size=2)
        self.assertIsNotNone(result)
        height, width = image.shape[:2]
        corners = np.array(
            [[x * width, y * height] for x, y in result.corners],
            dtype=np.float32,
        )
        vertical_axis = ((corners[3] - corners[0]) + (corners[2] - corners[1])) / 2
        shifted_down = corners + vertical_axis / 2
        correct_score = _score_face_candidate(image, corners, grid_size=2)
        shifted_score = _score_face_candidate(image, shifted_down, grid_size=2)
        self.assertGreater(
            correct_score,
            shifted_score + 0.04,
            f"完整 D 面应明显优于下移半格候选：{correct_score:.4f} vs {shifted_score:.4f}",
        )

    @unittest.skipUnless(shutil.which("node"), "需要 Node.js 验证前端颜色分类")
    def test_real_groups_are_classified_into_legal_facelets(self) -> None:
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        for group in AVAILABLE_GROUPS:
            extracted = subprocess.run(
                [sys.executable, str(ROOT / "tests" / "extract_real_patches.py"), "--group", group],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
            )
            classified = subprocess.run(
                ["node", str(ROOT / "tests" / "real_color.test.js"), "--group", group],
                cwd=ROOT,
                env=environment,
                input=extracted.stdout,
                check=False,
                capture_output=True,
            )
            self.assertEqual(
                classified.returncode,
                0,
                classified.stderr.decode("utf-8", errors="replace"),
            )


if __name__ == "__main__":
    unittest.main()
