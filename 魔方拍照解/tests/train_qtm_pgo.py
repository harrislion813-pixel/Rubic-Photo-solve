"""Fixed independent QTM PGO workload; normal candidates plus the complete strong proof path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_isolation_short import sha256
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.metrics import solution_cost
from test_native_qtm import ROOT, Service

EXCLUDED_INITIALS = {f"initial-{number}" for number in (1, 2, 5, 8, 12, 16)}


def training_states(cases: list[dict], initial_cases: list[dict]):
    selected = {case["name"]: case for case in initial_cases if case["name"] in EXCLUDED_INITIALS}
    if set(selected) != EXCLUDED_INITIALS:
        raise ValueError("PGO exclusion requires all six frozen initial states")
    excluded = {case["facelets"] for case in selected.values()}
    states = []
    for case in cases:
        if case["name"] in EXCLUDED_INITIALS or not case.get("scramble"):
            raise ValueError("PGO uses independent explicit scrambles only")
        state = CubieCube()
        for move in case["scramble"].split():
            state = state.apply_move_index(MOVE_INDEX[move])
        if to_facelets(state) in excluded:
            raise ValueError("PGO training overlaps a frozen acceptance state")
        states.append((case, state))
    if not states:
        raise ValueError("PGO training set is empty")
    return states


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/qtm_pgo_cases.json")
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--threads", type=int, default=15)
    parser.add_argument("--expansion", choices=("generic", "full-strong"), default="generic")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.timeout <= 5 or not 1 <= args.threads <= 15:
        parser.error("training timeout must be within 0..5 seconds and threads within 1..15")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    initial_path = ROOT / "tests/initial_solver_cases.json"
    states = training_states(cases, json.loads(initial_path.read_text(encoding="utf-8")))
    assets = ROOT / "assets/qtm/v1"
    paths = [assets / name for name in ("corner_qtm_v3.pdb", "phase1_qtm_v3.pdb",
                                      "strong_qtm_v4_nibble.pdb", "tail_qtm_depth8_v5.pdb")]
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError("PGO training requires all complete QTM strong assets")
    flags = ["--qtm-pdb", paths[0], "--qtm-phase1-pdb", paths[1], "--strong-pdb", paths[2],
             "--qtm-tail-pdb", paths[3], "--asset-loading=eager", "--no-proof-cache",
             "--candidate-schedule=legacy", "--late-tail-improvement=off", f"--qtm-expansion={args.expansion}",
             "--dual-policy=off", "--pdb-query-order=strong-first", "--pdb-prefetch=off", "--strong-slice=keep"]
    report = {"binary_sha256": sha256(args.binary), "training_cases_sha256": sha256(args.cases),
              "initial_cases_sha256": sha256(initial_path), "excluded_initials": sorted(EXCLUDED_INITIALS),
              "asset_sha256": {path.name: sha256(path) for path in paths}, "flags": list(map(str, flags)),
              "threads": args.threads, "timeout_seconds": args.timeout, "runs": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    service = Service(args.binary.resolve(), *flags)
    clean_exit = False
    try:
        report["ready"] = service.event("ready", timeout=60)
        assert report["ready"]["assets"]["QTM"]["profile"] == "strong"
        for case, state in states:
            service.send("solve", case["name"], to_facelets(state), 26, args.timeout, args.threads, "QTM", "")
            events = []
            while True:
                event = service.event(timeout=15)
                events.append(event)
                if event.get("type") == "result":
                    break
                if event.get("type") == "error":
                    raise RuntimeError(event)
            for event in events:
                if event.get("type") not in {"candidate", "result"} or not event.get("moves"):
                    continue
                verified = state
                for move in event["moves"]:
                    verified = verified.apply_move_index(MOVE_INDEX[move])
                assert verified.is_solved()
                assert solution_cost(event["moves"], "QTM") == event.get("cost", event.get("depth"))
            report["runs"].append({"case": case, "facelets": to_facelets(state), "events": events})
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        assert any(event.get("type") == "candidate" for run in report["runs"] for event in run["events"]), "training missed native candidates"
        assert any(event.get("strong_queries", 0) for run in report["runs"] for event in run["events"]), "training missed complete strong queries"
        if args.expansion == "full-strong":
            assert any(event.get("full_strong_expansions", 0) for run in report["runs"] for event in run["events"]), "training missed the experimental full-strong path"
        # GCC writes .gcda on normal process exit. TerminateProcess would discard the profile.
        service.process.stdin.close()
        assert service.process.wait(timeout=10) == 0
        clean_exit = True
    finally:
        report["clean_profile_exit"] = clean_exit
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if service.process.poll() is None:
            service.process.terminate()
            service.process.wait(timeout=5)
        service.reader.join(2)
        service.error_reader.join(2)
        for stream in (service.process.stdin, service.process.stdout, service.process.stderr):
            stream.close()


if __name__ == "__main__":
    main()
