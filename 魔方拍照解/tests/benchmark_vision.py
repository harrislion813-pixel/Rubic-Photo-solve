from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import cv2
import numpy as np

from cube_app.vision import detect_cube_face


def corner_error(predicted: np.ndarray, expected: np.ndarray) -> float:
    variants = []
    for points in (predicted, predicted[::-1]):
        for shift in range(4):
            variants.append(float(np.mean(np.linalg.norm(np.roll(points, shift, axis=0) - expected, axis=1))))
    return min(variants)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen, annotated face-detection benchmark.")
    parser.add_argument("annotations", type=Path, help="JSON file containing image/grid_size/corners or reject entries")
    parser.add_argument("--critical-error", type=float, default=0.05, help="normalized mean corner error threshold")
    args = parser.parse_args()
    entries = json.loads(args.annotations.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise SystemExit("annotations must be a non-empty JSON array")

    errors: list[float] = []
    latencies: list[float] = []
    misses = 0
    false_accepts = 0
    critical = 0
    positives = 0
    negatives = 0
    by_tag: dict[str, dict[str, int]] = {}
    for entry in entries:
        path = (args.annotations.parent / entry["image"]).resolve()
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise SystemExit(f"cannot read benchmark image: {path}")
        started = time.perf_counter()
        result = detect_cube_face(image, grid_size=int(entry.get("grid_size", 3)))
        latencies.append((time.perf_counter() - started) * 1000)
        tags = entry.get("tags", ["untagged"])
        for tag in tags:
            by_tag.setdefault(tag, {"total": 0, "failures": 0})["total"] += 1

        if entry.get("reject", False):
            negatives += 1
            if result is not None:
                false_accepts += 1
                for tag in tags:
                    by_tag[tag]["failures"] += 1
            continue

        positives += 1
        if result is None:
            misses += 1
            critical += 1
            for tag in tags:
                by_tag[tag]["failures"] += 1
            continue
        predicted = np.asarray(result.corners, dtype=np.float32)
        expected = np.asarray(entry["corners"], dtype=np.float32)
        error = corner_error(predicted, expected)
        errors.append(error)
        if error > args.critical_error:
            critical += 1
            for tag in tags:
                by_tag[tag]["failures"] += 1

    report = {
        "images": len(entries),
        "positives": positives,
        "negatives": negatives,
        "misses": misses,
        "false_accepts": false_accepts,
        "critical_error_threshold": args.critical_error,
        "critical_failure_rate": round((critical + false_accepts) / len(entries), 4),
        "mean_corner_error": round(statistics.fmean(errors), 5) if errors else None,
        "p95_corner_error": round(percentile(errors, 0.95), 5) if errors else None,
        "median_latency_ms": round(statistics.median(latencies), 2),
        "p95_latency_ms": round(percentile(latencies, 0.95), 2),
        "by_tag": by_tag,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
