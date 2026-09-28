"""Compare the legacy HTM candidate repriced in QTM with the native QTM candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from benchmark_native import case_state
from cube_app.cubie import MOVE_INDEX, to_facelets
from cube_app.fast import FastTwoPhaseSolver
from cube_app.metrics import solution_cost
from cube_app.optimal import SearchTimeout


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-file", type=Path, default=ROOT / "tests/native_cases.json")
    parser.add_argument("--cases", default="repo14,pgo16,seed18,known18")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--legacy-only", action="store_true")
    parser.add_argument("--random-only", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/qtm-candidate-comparison.json")
    args = parser.parse_args()
    names = None if args.cases == "all" else set(args.cases.split(","))
    legacy = FastTwoPhaseSolver(ROOT / ".cache")
    results = []
    for case in json.loads(args.cases_file.read_text(encoding="utf-8")):
        if names is not None and case["name"] not in names:
            continue
        if args.random_only and case.get("source", {}).get("kind") != "independent_legal_state_rng":
            continue
        cube, _ = case_state(case)
        started = time.perf_counter()
        try:
            old = legacy.solve_cube(cube, timeout_seconds=args.timeout)
            old_cost = solution_cost(old.moves, "QTM")
            old_moves = old.moves
        except SearchTimeout:
            old_cost = None
            old_moves = None
        old_seconds = time.perf_counter() - started
        native = None
        native_seconds = None
        if not args.legacy_only:
            started = time.perf_counter()
            process = subprocess.run(
                [str(ROOT / "native/build/cube_solver.exe"), "fast-solve", to_facelets(cube),
                 "--qtm-phase1-pdb", str(ROOT / ".cache/native/phase1_qtm_v3.pdb"),
                 "--timeout", str(args.timeout)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
            )
            native = json.loads(process.stdout)
            native_seconds = time.perf_counter() - started
            verified = cube
            for move in native["moves"]:
                verified = verified.apply_move_index(MOVE_INDEX[move])
            if native["cost"] >= 0 and (not verified.is_solved() or
                                        solution_cost(native["moves"], "QTM") != native["cost"]):
                raise AssertionError(f"invalid native candidate for {case['name']}")
        record = {
            "case": case["name"], "legacy_qtm_cost": old_cost, "legacy_moves": old_moves,
            "legacy_seconds": old_seconds, "native_qtm_cost": native["cost"] if native else None,
            "native_moves": native["moves"] if native else None, "native_seconds": native_seconds,
            "native_phase1_nodes": native["phase1_nodes"] if native else None,
            "native_phase2_nodes": native["phase2_nodes"] if native else None,
            "native_improvements": native["improvements"] if native else None,
        }
        results.append(record)
        print(json.dumps({"case": case["name"], "legacy_qtm_cost": old_cost,
                          "native_qtm_cost": native["cost"] if native else None}, ensure_ascii=False), flush=True)
    if args.random_only and len(results) != 32:
        raise AssertionError(f"expected 32 independent random candidates, got {len(results)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
