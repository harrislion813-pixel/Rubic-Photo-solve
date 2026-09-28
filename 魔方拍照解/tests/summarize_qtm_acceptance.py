"""Summarize paired QTM proof runs without dropping timed-out states."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def run_key(run: dict) -> tuple[str, int]:
    return run["case"], run["repeat"]


def summarize(path: Path, timeout: float) -> tuple[dict, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data["metric"] != "QTM" or data["proof_cache_reuse"]
            or data.get("timeout_seconds", timeout) != timeout):
        raise AssertionError(f"invalid QTM acceptance configuration: {path}")
    runs = {run_key(run): run for run in data["runs"]}
    if len(runs) != 144 or set(run["case"] for run in runs.values()) != {
        case["name"] for case in data["selected_cases"]
    }:
        raise AssertionError(f"incomplete acceptance run: {path}")
    if (data["incumbent_mode"] != "fixed" or data["proof_cache_reuse"]
            or any(run["threads"] != 4 or run["variant"] != "staged" or
                   run["metric"] != "QTM" or run["max_cost"] != 26 for run in runs.values())):
        raise AssertionError(f"acceptance configurations differ from the frozen protocol: {path}")
    durations = [run["wall_seconds"] for run in runs.values()]
    successes = [run for run in runs.values() if run["result"].get("optimal")]
    par2 = statistics.mean(run["wall_seconds"] if run["result"].get("optimal") else 2 * timeout
                           for run in runs.values())
    memory = [run["process_peak_memory_bytes"] for run in runs.values()
              if run.get("process_peak_memory_bytes") is not None]
    worker_idle = []
    worker_balance = []
    for run in runs.values():
        workers = run["result"].get("workers") or []
        if len(workers) < 2 or not all(worker.get("nodes", 0) > 0 for worker in workers):
            continue
        busy = sum(worker.get("busy_seconds", 0) for worker in workers)
        idle = sum(worker.get("idle_seconds", 0) for worker in workers)
        if busy + idle > 0:
            worker_idle.append(idle / (busy + idle))
        worker_balance.append(max(worker["nodes"] for worker in workers) /
                              min(worker["nodes"] for worker in workers))
    summary = {"profile": data["profile"], "native_flags": data["native_flags"],
               "binary": data["binary"], "cases_file": data["cases_file"],
               "raw_path": str(path), "raw_sha256": sha256(path), "runs": len(runs),
               "proof_successes": len(successes), "proof_success_rate": len(successes) / len(runs),
               "par2_seconds": par2, "wall_p50_seconds": statistics.median(durations),
               "wall_p95_seconds": percentile(durations, .95),
               "peak_working_set_bytes": max(memory) if memory else None,
               "worker_idle_fraction_p50": statistics.median(worker_idle) if worker_idle else None,
               "worker_node_balance_p95": percentile(worker_balance, .95),
               "cold_start_p50_seconds": statistics.median(start["seconds"] for start in data["cold_starts"]),
               "cases": {}}
    for case in data["selected_cases"]:
        subset = [runs[(case["name"], repeat)] for repeat in range(3)]
        summary["cases"][case["name"]] = {
            "completed": sum(bool(run["result"].get("optimal")) for run in subset),
            "median_wall_seconds": statistics.median(run["wall_seconds"] for run in subset),
            "depths": [run["result"].get("depth") for run in subset],
            "completed_depths": [run["completed_depth"] for run in subset],
        }
    return summary, runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("strong", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    baseline, baseline_runs = summarize(args.baseline, args.timeout)
    strong, strong_runs = summarize(args.strong, args.timeout)
    if baseline["native_flags"] or strong["native_flags"] != ["--no-native-candidate"]:
        raise AssertionError("core comparison requires equal fixed incumbents and no new candidate generator")
    if baseline["cases_file"]["sha256"] != strong["cases_file"]["sha256"] or set(baseline_runs) != set(strong_runs):
        raise AssertionError("acceptance cases or run keys differ")
    paired = []
    for name in baseline["cases"]:
        old = baseline["cases"][name]
        new = strong["cases"][name]
        if old["completed"] == new["completed"] == 3 and old["median_wall_seconds"] >= .1:
            paired.append({"case": name, "baseline_seconds": old["median_wall_seconds"],
                           "strong_seconds": new["median_wall_seconds"],
                           "ratio": old["median_wall_seconds"] / new["median_wall_seconds"]})
    geometric = math.exp(statistics.mean(math.log(row["ratio"]) for row in paired)) if paired else None
    same_depth = []
    for key, old in baseline_runs.items():
        new = strong_runs[key]
        if old["completed_depth"] == new["completed_depth"]:
            same_depth.append({"case": key[0], "repeat": key[1], "completed_depth": old["completed_depth"],
                               "baseline_generated": old["result"].get("generated_candidates"),
                               "strong_generated": new["result"].get("generated_candidates")})
    output = {"schema_version": 1, "metric": "QTM", "threads": 4, "timeout_seconds": args.timeout,
              "baseline": baseline, "strong": strong,
              "paired_proof_speedup": {"eligible_cases": len(paired), "geometric_mean": geometric,
                                       "cases": paired},
              "success_rate_gain_percentage_points": 100 * (strong["proof_success_rate"] -
                                                             baseline["proof_success_rate"]),
              "par2_improvement": baseline["par2_seconds"] / strong["par2_seconds"],
              "same_completed_depth_generated": same_depth}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"baseline_successes": baseline["proof_successes"],
                      "strong_successes": strong["proof_successes"],
                      "paired_cases": len(paired), "geometric_speedup": geometric,
                      "par2_improvement": output["par2_improvement"]}))


if __name__ == "__main__":
    main()
