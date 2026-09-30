"""Validate complete-layer counters and summarize the small review diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
import statistics

from benchmark_isolation_short import fixed_layer

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/benchmarks"


def read(name):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def main() -> None:
    summary = {"metrics": {}, "limits": "2 states, 3 repeats each, at most 5 seconds per search"}
    for metric, before_name, after_name in (
        ("HTM", "htm-h0-portable-review.json", "htm-h1-portable-review.json"),
        ("QTM", "qtm-q0-fixed-layer-review.json", "qtm-q1-fixed-layer-review.json"),
    ):
        before, after = read(before_name), read(after_name)
        assert before["assets"] == after["assets"], "asset hashes changed across comparison"
        assert before["threads"] == after["threads"] == 15
        rows = []
        for case in ("pgo16", "known18"):
            old = [run for run in before["runs"] if run["case"] == case]
            new = [run for run in after["runs"] if run["case"] == case]
            assert len(old) == len(new) == 3
            layers = [fixed_layer(run) for run in old + new]
            counters = {key: layers[0][key] for key in ("completed_depth", "generated_candidates")}
            for layer in layers:
                assert all(layer[key] == value for key, value in counters.items()), (metric, case, layers)
            old_wall = statistics.median(run["wall_seconds"] for run in old)
            new_wall = statistics.median(run["wall_seconds"] for run in new)
            rows.append({"case": case, "bound": old[0]["bound"], "complete_counters": counters,
                         "other_counter_ranges": {
                             key: [min(layer[key] for layer in layers), max(layer[key] for layer in layers)]
                             for key in ("nodes", "split_nodes", "phase1_queries", "corner_queries", "strong_queries")
                             if all(layer[key] is not None for layer in layers)
                         },
                         "before_wall_median": old_wall, "after_wall_median": new_wall,
                         "wall_change_percent": 100 * (new_wall / old_wall - 1),
                         "before_native_median": statistics.median(layer["elapsed_seconds"] for layer in layers[:3]),
                         "after_native_median": statistics.median(layer["elapsed_seconds"] for layer in layers[3:])})
        summary["metrics"][metric] = {"before": before_name, "after": after_name, "rows": rows}
    reference = read("qtm-q1-fixed-layer-review.json")
    summary["qtm_ablations"] = {}
    for name in ("qtm-direction-bounded-review.json", "qtm-dual-root-review.json", "qtm-query-order-legacy-review.json"):
        variant = read(name)
        assert variant["assets"] == reference["assets"]
        assert variant["binary_sha256"] == reference["binary_sha256"]
        assert variant["threads"] == reference["threads"]
        rows = []
        for case in ("pgo16", "known18"):
            runs = [run for run in variant["runs"] if run["case"] == case]
            base_runs = [run for run in reference["runs"] if run["case"] == case]
            assert len(runs) == len(base_runs) == 3
            layers = [fixed_layer(run) for run in runs]
            assert len({layer["generated_candidates"] for layer in layers}) == 1
            wall = statistics.median(run["wall_seconds"] for run in runs)
            base_wall = statistics.median(run["wall_seconds"] for run in base_runs)
            rows.append({"case": case, "wall_median": wall, "wall_change_percent": 100 * (wall / base_wall - 1),
                         "generated_candidates": layers[0]["generated_candidates"],
                         "inverse_directions": [run["result"].get("inverse_direction") for run in runs],
                         "direction_probe_seconds": [run["result"].get("direction_probe_seconds") for run in runs]})
        summary["qtm_ablations"][name] = rows
    lifecycle = read("qtm-staged-preemption-ready-review.json")
    job = lifecycle["final"]
    summary["default_staged"] = {key: job[key] for key in (
        "status", "optimal", "base_ready_seconds", "strong_ready_seconds", "tail_ready_seconds",
        "strong_adopted_seconds", "tail_adopted_seconds", "first_candidate_seconds",
        "candidate_delivery_seconds", "native_search_seconds", "resource_hold_seconds", "request_elapsed_seconds")}
    summary["preemption"] = {"resource_wait_seconds": lifecycle["preemption"]["resource_wait_seconds"],
                             "htm_wall_seconds": lifecycle["preemption"]["htm_wall_seconds"],
                             "qtm_status": lifecycle["preemption"]["qtm"]["status"],
                             "yield_faults": lifecycle["preemption"]["broker"]["yield_faults"]}
    reuse = read("qtm-staged-lifecycle-review.json")
    summary["reuse_prototype"] = {"immediate_release_walls": [row["wall_seconds"] for row in reuse["immediate_release"]],
                                  **reuse["reuse_prototype"],
                                  "production_policy_changed": False}
    output = EVIDENCE / "qtm-isolation-review-summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
