"""Record the limited deep-state Edge PDB ablation without claiming paired speedup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".cache/qtm-acceptance-strong-public48x3x60.json"
EDGE = ROOT / ".cache/qtm-edge-deep-3x60.json"
OUTPUT = ROOT / "docs/benchmarks/qtm-q8-edge-deep-2026-09-29.json"


def source(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    edge = json.loads(EDGE.read_text(encoding="utf-8"))
    names = {"legal-20271005", "legal-20271013", "legal-20271014"}
    if (baseline["binary"]["sha256"] != edge["binary"]["sha256"] or
            baseline["cases_file"]["sha256"] != edge["cases_file"]["sha256"] or
            baseline["metric"] != "QTM" or edge["metric"] != "QTM" or
            baseline["native_flags"] != ["--no-native-candidate"] or
            edge["native_flags"] != ["--no-native-candidate"] or
            baseline["threads"] != "4" or edge["threads"] != "4" or
            baseline["timeout_seconds"] != 60 or edge["timeout_seconds"] != 60 or
            {row["case"] for row in edge["runs"]} != names or len(edge["runs"]) != 3):
        raise AssertionError("deep Edge comparison conditions differ")
    rows = []
    for name in sorted(names):
        base_three = [row for row in baseline["runs"] if row["case"] == name]
        with_edge = next(row for row in edge["runs"] if row["case"] == name)
        if len(base_three) != 3 or any(row["completed_depth"] != with_edge["completed_depth"]
                                       for row in base_three) or with_edge["incumbent"] or any(
                                           row["incumbent"] for row in base_three):
            raise AssertionError(f"incompatible completed depth: {name}")
        rows.append({"case": name, "completed_depth": with_edge["completed_depth"],
                     "baseline_wall_seconds": [row["wall_seconds"] for row in base_three],
                     "baseline_median_wall_seconds": statistics.median(row["wall_seconds"]
                                                                        for row in base_three),
                     "edge_wall_seconds": with_edge["wall_seconds"],
                     "baseline_generated_candidates": [row["result"]["generated_candidates"]
                                                       for row in base_three],
                     "edge_generated_candidates": with_edge["result"]["generated_candidates"],
                     "baseline_optimal": [bool(row["result"].get("optimal")) for row in base_three],
                     "edge_optimal": bool(with_edge["result"].get("optimal"))})
    result = {"schema_version": 1, "baseline_raw": source(BASELINE), "edge_raw": source(EDGE),
              "edge_repeats": 1, "interpretation": "screening only; no paired speedup estimate", "cases": rows}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({row["case"]: {"baseline_median": row["baseline_median_wall_seconds"],
                                    "with_edge": row["edge_wall_seconds"]} for row in rows}))


if __name__ == "__main__":
    main()
