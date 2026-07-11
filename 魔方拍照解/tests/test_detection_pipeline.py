from __future__ import annotations

import unittest

import numpy as np

from cube_app.detection import DetectionPipeline
from cube_app.vision import FaceDetection


def detection(confidence: int, offset: float = 0.0, method: str = "test") -> FaceDetection:
    return FaceDetection(
        corners=[
            [0.1 + offset, 0.1],
            [0.9 + offset, 0.1],
            [0.9 + offset, 0.9],
            [0.1 + offset, 0.9],
        ],
        confidence=confidence,
        method=method,
        score=confidence / 100,
    )


class DetectionPipelineTests(unittest.TestCase):
    def test_high_confidence_primary_skips_model(self) -> None:
        calls = []
        pipeline = DetectionPipeline(
            primary=lambda image, grid, limit: [detection(80)],
            fallback=lambda image, grid, limit: calls.append(True) or [detection(90, method="model")],
        )
        result = pipeline.detect(np.zeros((8, 8, 3), np.uint8), 3)
        self.assertFalse(result.fallback_used)
        self.assertEqual(calls, [])

    def test_low_confidence_primary_uses_and_merges_model_candidates(self) -> None:
        pipeline = DetectionPipeline(
            primary=lambda image, grid, limit: [detection(30)],
            fallback=lambda image, grid, limit: [detection(85, 0.08, "model")],
        )
        result = pipeline.detect(np.zeros((8, 8, 3), np.uint8), 3)
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.candidates[0].method, "model")
        self.assertEqual(len(result.candidates), 2)


if __name__ == "__main__":
    unittest.main()
