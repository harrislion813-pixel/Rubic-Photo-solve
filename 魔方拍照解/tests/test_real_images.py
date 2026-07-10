from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

from cube_app.vision import detect_cube_face


ROOT = Path(__file__).resolve().parents[1]
FACE_ORDER = "URFDLB"
AVAILABLE_GROUPS = tuple(
    group
    for group in ("1", "2")
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


@unittest.skipUnless(AVAILABLE_GROUPS, "需要 initial/ 目录中的一组完整实拍图片")
class RealImageRegressionTests(unittest.TestCase):
    def test_initial_images_locate_the_complete_cube_face(self) -> None:
        failures = []
        for group in AVAILABLE_GROUPS:
            for face in FACE_ORDER:
                image = frontend_image(ROOT / "initial" / f"{face}{group}.jpg")
                result = detect_cube_face(image)
                if result is None:
                    failures.append(f"{face}{group}: no detection")
                    continue
                corners = np.array(result.corners, np.float32)
                area = abs(float(cv2.contourArea(corners)))
                if result.score < 0.80 or area < 0.20 or np.any(corners < 0) or np.any(corners > 1):
                    failures.append(
                        f"{face}{group}: score={result.score}, area={area:.3f}, "
                        f"method={result.method}, corners={result.corners}"
                    )
        self.assertFalse(failures, "\n".join(failures))

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
