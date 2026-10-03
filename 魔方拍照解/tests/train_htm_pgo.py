"""Independent HTM PGO workload with normal Python candidates and native proof."""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

from benchmark_isolation_short import sha256
from benchmark_native import ROOT, Service
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.metrics import solution_cost
from cube_app.solvers.htm.fast import FastTwoPhaseSolver
from cube_app.solvers.htm.optimal import SearchCancelled, SearchTimeout

EXCLUDED_INITIALS = {f"initial-{number}" for number in (1, 2, 5, 8, 12, 16)}


def training_states(cases: list[dict], initial_cases: list[dict]):
    selected = {case["name"]: case for case in initial_cases if case["name"] in EXCLUDED_INITIALS}
    if set(selected) != EXCLUDED_INITIALS:
        raise ValueError("PGO exclusion requires all six frozen initial states")
    excluded = {case["facelets"] for case in selected.values()}
    states, seen = [], set()
    for case in cases:
        if case["name"] in EXCLUDED_INITIALS or not case.get("scramble"):
            raise ValueError("PGO uses independent explicit scrambles only")
        state = CubieCube()
        for move in case["scramble"].split():
            state = state.apply_move_index(MOVE_INDEX[move])
        facelets = to_facelets(state)
        if facelets in excluded or facelets in seen:
            raise ValueError("PGO training overlaps an acceptance state or duplicates another training state")
        seen.add(facelets)
        states.append((case, state))
    if not states:
        raise ValueError("PGO training set is empty")
    return states


def verify_moves(state, moves):
    verified = state
    for move in moves:
        verified = verified.apply_move_index(MOVE_INDEX[move])
    if not verified.is_solved():
        raise AssertionError("HTM PGO candidate does not solve its independent state")
    return solution_cost(moves, "HTM")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/htm_pgo_cases.json")
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--threads", type=int, default=15)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.timeout <= 5 or not 2 <= args.threads <= 15:
        parser.error("training timeout must be within 0..5 seconds and threads within 2..15")
    initial_path = ROOT / "tests/initial_solver_cases.json"
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    states = training_states(cases, json.loads(initial_path.read_text(encoding="utf-8")))
    assets = ROOT / "assets/htm/v1"
    paths = [assets / name for name in ("corner_htm_v2.pdb", "phase1_sym_htm_v2.pdb", "tail_depth6_v4.pdb")]
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError("PGO training requires all production HTM assets")
    flags = ["--pdb", str(paths[0]), "--phase1-pdb", str(paths[1]), "--tail-pdb", str(paths[2])]
    report = {"binary_sha256": sha256(args.binary), "training_cases_sha256": sha256(args.cases),
              "initial_cases_sha256": sha256(initial_path), "excluded_initials": sorted(EXCLUDED_INITIALS),
              "asset_sha256": {path.name: sha256(path) for path in paths}, "flags": flags,
              "candidate_source_sha256": sha256(ROOT / "cube_app/solvers/htm/fast.py"),
              "threads": args.threads, "native_proof_threads": args.threads - 1, "candidate_threads": 1,
              "timeout_seconds": args.timeout, "candidate_budget_seconds": min(1.5, args.timeout),
              "runs": [], "proof_cache": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous_cache = os.environ.get("CUBE_NATIVE_COORDINATE_CACHE")
    os.environ["CUBE_NATIVE_COORDINATE_CACHE"] = str(ROOT / ".cache/htm/coordinates_htm_v1.bin")
    candidate_solver = FastTwoPhaseSolver(ROOT / ".cache/htm")
    # Load once before per-request budgets, as the production candidate worker does.
    candidate_solver.tables
    service = None
    clean_exit = False
    try:
        service = Service(args.binary.resolve(), [], flags)
        report["ready"] = service.ready
        for case, state in states:
            cancel = threading.Event()
            finished = threading.Event()
            write_lock = threading.Lock()
            candidates, candidate_errors = [], []
            started = time.perf_counter()

            def publish(candidate):
                cost = verify_moves(state, candidate.moves)
                with write_lock:
                    if finished.is_set() or cancel.is_set() or time.perf_counter() - started >= args.timeout:
                        return
                    candidates.append({"moves": candidate.moves, "cost": cost,
                                       "seconds": time.perf_counter() - started})
                    # Legacy framing reruns proof; its active request ID is empty.
                    service.process.stdin.write("incumbent\t\t" + " ".join(candidate.moves) + "\n")
                    service.process.stdin.flush()

            def find_candidate():
                try:
                    candidate_solver.solve_cube(state, timeout_seconds=min(1.5, args.timeout),
                                                candidate_callback=publish, cancel_event=cancel)
                except (SearchTimeout, SearchCancelled):
                    pass
                except Exception as error:
                    candidate_errors.append(repr(error))

            service.process.stdin.write(f"{to_facelets(state)}\t20\t{args.timeout}\t{args.threads - 1}\t\n")
            service.process.stdin.flush()
            worker = threading.Thread(target=find_candidate)
            worker.start()
            events = []
            try:
                while True:
                    event = service.event(args.timeout + 10)
                    events.append(event)
                    if event.get("type") not in {"progress", "candidate"}:
                        break
            finally:
                with write_lock:
                    finished.set()
                    cancel.set()
                worker.join(timeout=5)
                if worker.is_alive():
                    raise RuntimeError("HTM PGO candidate did not stop within its original request budget")
            if candidate_errors:
                raise RuntimeError(candidate_errors)
            if event.get("moves"):
                cost = verify_moves(state, event["moves"])
                assert cost == event.get("depth"), "native HTM result cost mismatch"
            if not event.get("ok") and event.get("error") != "no solution found within max depth":
                raise RuntimeError(event)
            report["runs"].append({"case": case, "facelets": to_facelets(state),
                                   "candidates": candidates, "events": events})
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        assert any(run["candidates"] for run in report["runs"]), "training missed normal HTM candidates"
        assert any(event.get("generated_candidates", 0) for run in report["runs"] for event in run["events"]), "training missed native HTM proof"
        service.process.stdin.close()
        assert service.process.wait(timeout=10) == 0
        clean_exit = True
    finally:
        report["clean_profile_exit"] = clean_exit
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if service is not None:
            if service.process.poll() is None:
                service.process.terminate()
                service.process.wait(timeout=5)
            service.reader.join(2)
            service.error_reader.join(2)
            for stream in (service.process.stdin, service.process.stdout, service.process.stderr):
                stream.close()
        if previous_cache is None:
            os.environ.pop("CUBE_NATIVE_COORDINATE_CACHE", None)
        else:
            os.environ["CUBE_NATIVE_COORDINATE_CACHE"] = previous_cache


if __name__ == "__main__":
    main()
