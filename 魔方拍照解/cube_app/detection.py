from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .vision import FaceDetection, detect_cube_face_candidates


CandidateDetector = Callable[[np.ndarray, int, int], list[FaceDetection]]


@dataclass(frozen=True)
class DetectionBatch:
    candidates: list[FaceDetection]
    fallback_used: bool


class DetectionPipeline:
    """Run OpenCV first and an optional learned detector only when it adds value."""

    def __init__(
        self,
        primary: CandidateDetector | None = None,
        fallback: CandidateDetector | None = None,
        *,
        fallback_confidence: int = 55,
    ) -> None:
        self.primary = primary or (
            lambda image, grid_size, limit: detect_cube_face_candidates(
                image,
                grid_size=grid_size,
                limit=limit,
            )
        )
        self.fallback = fallback
        self.fallback_confidence = fallback_confidence

    def set_fallback(self, detector: CandidateDetector | None) -> None:
        """Install a model adapter without coupling the server to a framework."""
        self.fallback = detector

    def detect(self, image: np.ndarray, grid_size: int, limit: int = 3) -> DetectionBatch:
        primary = self.primary(image, grid_size, limit)
        should_fallback = not primary or primary[0].confidence < self.fallback_confidence
        if self.fallback is None or not should_fallback:
            return DetectionBatch(primary[:limit], False)

        learned = self.fallback(image, grid_size, limit)
        merged = sorted([*primary, *learned], key=lambda item: item.confidence, reverse=True)
        distinct: list[FaceDetection] = []
        for candidate in merged:
            points = np.asarray(candidate.corners, dtype=np.float32)
            if any(
                float(np.mean(np.linalg.norm(points - np.asarray(existing.corners), axis=1))) < 0.035
                for existing in distinct
            ):
                continue
            distinct.append(candidate)
            if len(distinct) >= limit:
                break
        return DetectionBatch(distinct, bool(learned))
