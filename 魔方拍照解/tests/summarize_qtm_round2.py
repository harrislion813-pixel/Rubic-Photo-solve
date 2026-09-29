"""Summarize frozen QTM proof runs without treating timeouts as successful proofs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def metadata(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def proof_summary(path: Path) -> dict:
    source = json.loads(path.read_text(encoding="utf-8"))
    runs = source["runs"]
    if (source["metric"] != "QTM" or source["timeout_seconds"] != 60 or
            source["threads"] != "4" or source["repeats"] != 3 or
            source["native_flags"] != ["--no-native-candidate"] or
            source["proof_cache_reuse"] is not False):
        raise ValueError(f"proof conditions differ: {path}")
    grouped = defaultdict(list)
    for run in runs:
        if run["threads"] != 4 or run["metric"] != "QTM" or run["candidates"]:
            raise ValueError(f"mixed conditions in {path}")
        grouped[run["case"]].append(run)
    if any(len(group) != 3 for group in grouped.values()):
        raise ValueError(f"every case needs three repetitions: {path}")
    if any(run["result"].get("asset_profile") != "strong" for run in runs):
        raise ValueError(f"a run did not use the complete strong profile: {path}")
    success = [run for run in runs if run["result"]["optimal"]]
    cases = {}
    for name, group in grouped.items():
        times = [run["wall_seconds"] for run in group if run["result"]["optimal"]]
        cases[name] = {
            "completed": len(times),
            "completed_wall_median": statistics.median(times) if times else None,
            "par2": statistics.mean(run["wall_seconds"] if run["result"]["optimal"] else 120
                                    for run in group),
            "runs": [{"repeat": run["repeat"], "optimal": run["result"]["optimal"],
                      "wall_seconds": run["wall_seconds"], "completed_depth": run["completed_depth"],
                      "depth": run["result"]["depth"],
                      "generated_candidates": run["result"].get("generated_candidates"),
                      "inverse_direction": run["result"].get("inverse_direction")}
                     for run in sorted(group, key=lambda item: item["repeat"])],
        }
    return {
        "raw": metadata(path),
        "binary": source["binary"],
        "pdbs": source["pdbs"],
        "cases_file": source["cases_file"],
        "profile": source["profile"],
        "cases": len(cases),
        "runs": len(runs),
        "completed": len(success),
        "random_completed": sum(run["result"]["optimal"] for run in runs
                                if run["case"].startswith(("legal-", "unseen-"))),
        "par2_seconds": statistics.mean(run["wall_seconds"] if run["result"]["optimal"] else 120
                                        for run in runs),
        "peak_working_set_bytes": max((run["process_peak_memory_bytes"] or 0) for run in runs),
        "startup_median_seconds": statistics.median(item["seconds"] for item in source["cold_starts"]),
        "inverse_runs": sum(bool(run["result"].get("inverse_direction")) for run in runs),
        "cases_detail": cases,
    }


def compare(historical: dict, current: dict) -> dict:
    if set(historical["cases_detail"]) != set(current["cases_detail"]):
        raise ValueError("public baseline and final run use different cases")
    ratios = {}
    for name, old in historical["cases_detail"].items():
        new = current["cases_detail"][name]
        if old["completed"] == new["completed"] == 3 and old["completed_wall_median"] >= 1:
            ratios[name] = old["completed_wall_median"] / new["completed_wall_median"]
    values = list(ratios.values())
    return {
        "shared_hard_case_count": len(values),
        "hard_case_threshold_seconds": 1,
        "hard_case_speedup_geomean": statistics.geometric_mean(values) if values else None,
        "hard_case_speedup_min": min(values) if values else None,
        "hard_case_speedup_max": max(values) if values else None,
        "hard_case_speedup_ratios": ratios,
        "par2_improvement_ratio": historical["par2_seconds"] / current["par2_seconds"],
        "additional_completed": current["completed"] - historical["completed"],
    }


def candidate_summary(path: Path) -> dict:
    source = json.loads(path.read_text(encoding="utf-8"))
    runs = source["runs"]
    arrival = [run["first_candidate_seconds"] for run in runs if run["first_candidate_seconds"] is not None]
    costs = [run["candidate_cost"] for run in runs if run["candidate_cost"] is not None]
    proof_busy = [run["proof_worker_busy_seconds"] for run in runs
                  if run.get("proof_worker_busy_seconds") is not None]
    return {"raw": metadata(path), "runs": len(runs), "candidate_present": len(costs),
            "candidate_cost_median": statistics.median(costs) if costs else None,
            "first_candidate_p95_seconds": nearest_rank(arrival, .95) if arrival else None,
            "proof_worker_busy_median_seconds": statistics.median(proof_busy) if proof_busy else None,
            "asset_profiles": {name: sum(run.get("asset_profile") == name for run in runs)
                               for name in sorted({run.get("asset_profile") for run in runs
                                                   if run.get("asset_profile") is not None})},
            "proofs": sum(run["status"] == "complete" for run in runs),
            "first_request": source["first_request"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--unseen", type=Path, required=True)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    historical = proof_summary(args.historical)
    public = proof_summary(args.public)
    unseen = proof_summary(args.unseen)
    if public["cases"] != 48 or unseen["cases"] != 32:
        raise ValueError("expected 48 public and 32 unseen states")
    if historical["binary"]["sha256"] != "261d0afff67d1641d985d2587843c11c7130ca2edf9d4623eb69b5d6d04422fb":
        raise ValueError("historical run is not the frozen strong build")
    if (public["binary"]["sha256"] != unseen["binary"]["sha256"] or
            [(item["sha256"], item["bytes"]) for item in public["pdbs"]] !=
            [(item["sha256"], item["bytes"]) for item in unseen["pdbs"]]):
        raise ValueError("public and unseen runs used different binaries or assets")
    output = {"schema_version": 1, "historical": historical, "public": public,
              "unseen": unseen, "comparison": compare(historical, public)}
    if args.candidates:
        output["candidates"] = candidate_summary(args.candidates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"historical_completed": historical["completed"],
                      "public_completed": public["completed"], "public_par2": public["par2_seconds"],
                      "unseen_completed": unseen["completed"], "unseen_par2": unseen["par2_seconds"]}))


if __name__ == "__main__":
    main()
