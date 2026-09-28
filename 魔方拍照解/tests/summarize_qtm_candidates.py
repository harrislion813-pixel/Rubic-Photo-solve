"""Summarize 32-state hot HTTP QTM candidates against HTM repricing."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def median_with_missing_infinite(values: list[int | None]) -> float | None:
    median = statistics.median(value if value is not None else math.inf for value in values)
    return median if math.isfinite(median) else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legacy", type=Path)
    parser.add_argument("native_http", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    legacy_rows = json.loads(args.legacy.read_text(encoding="utf-8"))
    native_data = json.loads(args.native_http.read_text(encoding="utf-8"))
    native_rows = native_data["runs"]
    legacy = {row["case"]: row for row in legacy_rows}
    native = {row["case"]: row for row in native_rows}
    if len(legacy) != len(native) or len(native) != 32 or set(legacy) != set(native):
        raise AssertionError("candidate comparison needs the same 32 frozen random states")
    paired = [{"case": name, "legacy_cost": legacy[name]["legacy_qtm_cost"],
               "native_cost": native[name]["candidate_cost"],
               "first_candidate_seconds": native[name]["first_candidate_seconds"]}
              for name in sorted(native)]
    first = [row["first_candidate_seconds"] for row in paired]
    first_p95 = sorted(value if value is not None else math.inf for value in first)[math.ceil(.95 * len(first)) - 1]
    output = {"schema_version": 1, "metric": "QTM", "budget_seconds": 3,
              "legacy_raw": {"path": str(args.legacy), "sha256": sha256(args.legacy)},
              "native_http_raw": {"path": str(args.native_http), "sha256": sha256(args.native_http)},
              "cold_first_request": native_data.get("first_request"),
              "legacy_candidate_count": sum(row["legacy_cost"] is not None for row in paired),
              "native_candidate_count": sum(row["native_cost"] is not None for row in paired),
              "missing_candidate_treatment": "infinite cost",
              "legacy_cost_median_all_32": median_with_missing_infinite([row["legacy_cost"] for row in paired]),
              "native_cost_median_all_32": median_with_missing_infinite([row["native_cost"] for row in paired]),
              "native_first_candidate_p95_seconds": first_p95 if math.isfinite(first_p95) else None,
              "native_first_candidate_missing": sum(value is None for value in first),
              "paired": paired}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("legacy_candidate_count", "native_candidate_count",
                                                   "legacy_cost_median_all_32", "native_cost_median_all_32",
                                                   "native_first_candidate_p95_seconds")}))


if __name__ == "__main__":
    main()
