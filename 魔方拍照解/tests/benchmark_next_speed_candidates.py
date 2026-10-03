"""Isolate Q2 candidate scheduling under the same three-second native budget."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

from benchmark_isolation_short import sha256
from cube_app.cubie import MOVE_INDEX, from_facelets
from cube_app.metrics import solution_cost

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", default="initial-1,initial-12")
    args = parser.parse_args()
    wanted = args.cases.split(",")
    fixtures = {case["name"]: case for case in json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}
    report = {"binary_sha256": sha256(args.binary), "budget_seconds": 3, "candidate_threads": 1,
              "cases": wanted, "order": [["legacy", "short-slices"], ["short-slices", "legacy"], ["legacy", "short-slices"]],
              "scope": "isolated candidate scheduling; candidate quality alone does not demonstrate proof acceleration", "runs": [], "failures": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CUBE_NATIVE_COORDINATE_CACHE"] = str(ROOT / ".cache/qtm/coordinates_dual_v2.bin")
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for repeat, order in enumerate(report["order"]):
            for name in wanted:
                for schedule in order:
                    command = [str(args.binary.resolve()), "fast-solve", fixtures[name]["facelets"],
                               "--qtm-phase1-pdb", str(ROOT / "assets/qtm/v1/phase1_qtm_v3.pdb"),
                               "--qtm-tail-pdb", str(ROOT / "assets/qtm/v1/tail_qtm_depth8_v5.pdb"),
                               "--timeout", "3", f"--candidate-schedule={schedule}"]
                    started = time.perf_counter()
                    completed = subprocess.run(command, env=env, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15,
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    run = {"name": name, "schedule": schedule, "repeat": repeat,
                           "wall_seconds": time.perf_counter() - started, "command": command,
                           "stdout": completed.stdout, "stderr": completed.stderr, "exit_code": completed.returncode}
                    report["runs"].append(run)
                    save()
                    assert completed.returncode == 0, completed.stderr
                    result = json.loads(completed.stdout)
                    run["result"] = result
                    cube = from_facelets(fixtures[name]["facelets"])
                    for move in result["moves"]:
                        cube = cube.apply_move_index(MOVE_INDEX[move])
                    assert cube.is_solved() and solution_cost(result["moves"], "QTM") == result["cost"]
                    run["replay"] = {"solved": True, "cost": result["cost"]}
                    run["first_candidate_seconds"] = min((d["first_candidate_seconds"] for d in result["candidate_directions"]
                                                           if d["first_candidate_seconds"] >= 0), default=None)
                    print(json.dumps({key: run[key] for key in ("name", "schedule", "repeat", "first_candidate_seconds")}
                                     | {"cost": result["cost"]}), flush=True)
                    save()
        report["summary"] = {name: {schedule: {
            "costs": [r["result"]["cost"] for r in report["runs"] if r["name"] == name and r["schedule"] == schedule],
            "first_candidate_median_seconds": statistics.median(r["first_candidate_seconds"] for r in report["runs"]
                                                               if r["name"] == name and r["schedule"] == schedule)}
            for schedule in ("legacy", "short-slices")} for name in wanted}
    except BaseException as error:
        report["failures"].append({"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        save()
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
