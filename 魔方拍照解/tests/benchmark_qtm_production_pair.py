"""Interleaved old/final comparison of the plan's two fixed exclusion trees."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from benchmark_isolation_short import sha256
from benchmark_native import case_state
from test_native_qtm import ROOT, Service


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assets = ROOT / "assets/qtm/v1"
    flags = ["--pdb", assets / "corner_htm_v2.pdb", "--phase1-pdb", assets / "phase1_sym_htm_v2.pdb",
             "--tail-pdb", assets / "tail_depth6_v4.pdb", "--qtm-pdb", assets / "corner_qtm_v3.pdb",
             "--qtm-phase1-pdb", assets / "phase1_qtm_v3.pdb", "--strong-pdb", assets / "strong_qtm_v4_nibble.pdb",
             "--qtm-tail-pdb", assets / "tail_qtm_depth8_v5.pdb", "--asset-loading=eager",
             "--no-proof-cache", "--no-native-candidate", "--direction-policy=off", "--dual-policy=off",
             "--pdb-query-order=strong-first", "--loader-threads", "8"]
    cases = {case["name"]: case for case in json.loads((ROOT / "tests/native_cases.json").read_text(encoding="utf8"))}
    report = {"binary_sha256": {"baseline": sha256(args.baseline), "current": sha256(args.current)},
              "assets": {path.name: sha256(path) for path in assets.glob("*.pdb")},
              "flags": list(map(str, flags)), "threads": 15, "timeout_seconds": 5,
              "scope": "complete exclusion trees; sequential searches, interleaved binaries; OS cache not cleared",
              "ready": {}, "runs": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")

    try:
        with Service(args.baseline.resolve(), *flags) as old, Service(args.current.resolve(), *flags) as new:
            report["ready"] = {"baseline": old.event("ready"), "current": new.event("ready")}
            for repeat, order in enumerate((('baseline', 'current'), ('current', 'baseline'), ('baseline', 'current'))):
                for name, bound in (("pgo16", 19), ("known18", 18)):
                    state, _ = case_state(cases[name])
                    for label in order:
                        service = old if label == "baseline" else new
                        started = time.perf_counter()
                        result = service.solve(state, bound=bound, timeout=5, threads=15,
                                               request_id=f"{label}-{name}-{repeat}")
                        wall = time.perf_counter() - started
                        assert result["status"] == "budget_exhausted" and not result["optimal"]
                        assert result["completed_depth"] >= bound and wall < 5
                        report["runs"].append({"binary": label, "case": name, "bound": bound,
                                               "repeat": repeat, "wall_seconds": wall, "result": result})
                        save()
    finally:
        save()
    report["summary"] = {}
    for name in ("pgo16", "known18"):
        selected = [run for run in report["runs"] if run["case"] == name]
        generated = {run["result"]["generated_candidates"] for run in selected}
        assert len(generated) == 1, f"fixed exclusion tree changed: {name}"
        medians = {label: statistics.median(run["wall_seconds"] for run in selected if run["binary"] == label)
                   for label in ("baseline", "current")}
        ratio = medians["current"] / medians["baseline"]
        report["summary"][name] = {"median_seconds": medians, "current_over_baseline": ratio,
                                  "generated_candidates": generated.pop(),
                                  "completed_depth": sorted({run["result"]["completed_depth"] for run in selected})}
        assert ratio <= 1.05, f"final QTM fixed-layer regression exceeds 5%: {name}"
    save()
    print(json.dumps(report["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
