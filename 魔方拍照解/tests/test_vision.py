from __future__ import annotations

import unittest

import cv2
import numpy as np

from cube_app.vision import detect_cube_face, detect_cube_face_candidates


COLORS = [
    (235, 235, 235),
    (45, 65, 210),
    (70, 165, 55),
    (55, 210, 235),
    (35, 125, 235),
    (205, 105, 40),
    (45, 65, 210),
    (70, 165, 55),
    (235, 235, 235),
]


def quad_point(corners: np.ndarray, u: float, v: float) -> np.ndarray:
    top = corners[0] * (1 - u) + corners[1] * u
    bottom = corners[3] * (1 - u) + corners[2] * u
    return top * (1 - v) + bottom * v


def make_photo(width: int, height: int, corners: np.ndarray, *, light: bool) -> np.ndarray:
    rng = np.random.default_rng(42)
    base = 205 if light else 48
    image = np.full((height, width, 3), base, np.float32)
    gradient = np.linspace(-18, 20, width, dtype=np.float32)[None, :, None]
    image += gradient
    image += rng.normal(0, 5, image.shape)
    image = np.clip(image, 0, 255).astype(np.uint8)

    cv2.rectangle(image, (35, 80), (175, 260), (85, 55, 35), -1)
    cv2.rectangle(image, (width - 190, 55), (width - 45, 145), (130, 80, 25), -1)
    cv2.fillConvexPoly(image, corners.astype(np.int32), (15, 17, 18))
    gap = 0.022
    for row in range(3):
        for column in range(3):
            patch = np.array(
                [
                    quad_point(corners, column / 3 + gap, row / 3 + gap),
                    quad_point(corners, (column + 1) / 3 - gap, row / 3 + gap),
                    quad_point(corners, (column + 1) / 3 - gap, (row + 1) / 3 - gap),
                    quad_point(corners, column / 3 + gap, (row + 1) / 3 - gap),
                ],
                np.int32,
            )
            cv2.fillConvexPoly(image, patch, COLORS[row * 3 + column])

    overlay = image.copy()
    for row, column in ((0, 1), (1, 1), (2, 0)):
        center = quad_point(corners, (column + 0.58) / 3, (row + 0.38) / 3).astype(int)
        cv2.ellipse(overlay, tuple(center), (30, 16), -22, 0, 360, (255, 255, 255), -1)
    image = cv2.addWeighted(overlay, 0.48, image, 0.52, 0)
    return cv2.GaussianBlur(image, (3, 3), 0.5)


def mean_corner_error(detected: np.ndarray, expected: np.ndarray) -> float:
    variants = []
    for points in (detected, detected[::-1]):
        for shift in range(4):
            variants.append(np.mean(np.linalg.norm(np.roll(points, shift, axis=0) - expected, axis=1)))
    return float(min(variants))


class VisionDetectionTests(unittest.TestCase):
    def test_detects_perspective_face_with_glare_and_distractors(self) -> None:
        corners = np.array([[280, 105], [745, 142], [790, 568], [235, 535]], np.float32)
        image = make_photo(1050, 680, corners, light=False)
        result = detect_cube_face(image)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.score, 0)
        self.assertLessEqual(result.score, 1)
        self.assertGreaterEqual(result.confidence, 0)
        self.assertLessEqual(result.confidence, 100)
        detected = np.array(
            [[x * image.shape[1], y * image.shape[0]] for x, y in result.corners],
            np.float32,
        )
        self.assertLess(mean_corner_error(detected, corners), 55)

    def test_detects_small_face_on_light_background(self) -> None:
        corners = np.array([[440, 135], [665, 155], [682, 382], [418, 365]], np.float32)
        image = make_photo(1100, 560, corners, light=True)
        result = detect_cube_face(image)
        self.assertIsNotNone(result)
        detected = np.array(
            [[x * image.shape[1], y * image.shape[0]] for x, y in result.corners],
            np.float32,
        )
        self.assertLess(mean_corner_error(detected, corners), 45)

    def test_blank_photo_returns_no_detection(self) -> None:
        image = np.full((420, 720, 3), 62, np.uint8)
        self.assertIsNone(detect_cube_face(image))
        self.assertEqual(detect_cube_face_candidates(image), [])

    def test_candidate_api_keeps_best_detection_first(self) -> None:
        corners = np.array([[280, 105], [745, 142], [790, 568], [235, 535]], np.float32)
        image = make_photo(1050, 680, corners, light=False)
        best = detect_cube_face(image)
        candidates = detect_cube_face_candidates(image, limit=3)
        self.assertIsNotNone(best)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0], best)
        self.assertLessEqual(len(candidates), 3)


if __name__ == "__main__":
    unittest.main()
