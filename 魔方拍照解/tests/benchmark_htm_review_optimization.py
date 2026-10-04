"""Serial, reproducible HTM review gates; never overwrite earlier evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark_next_speed_pair import Service, TREE_COUNTERS, ORDER  # noqa: E402
from cube_app.cubie import from_facelets, MOVE_INDEX  # noqa: E402


def replay(facelets, moves):
    state = from_facelets(facelets)
    for move in moves:
        state = state.apply_move_index(MOVE_INDEX[move])
    assert state.is_solved()


def request(service, name, facelets, moves, threads, timeout, on_event=None):
    started = time.perf_counter()
    fields = ["solve", name, facelets, "20", str(timeout), str(threads), " ".join(moves)]
    service.process.stdin.write("\t".join(fields) + "\n")
    service.process.stdin.flush()
    events = []
    while True:
        event = service.event(timeout + 10)
        if event.get("request_id") != name:
            continue
        events.append({"received_seconds": time.perf_counter() - started, **event})
        if on_event:
            on_event(event)
        if event.get("type") in {"result", "error"}:
            return {"events": events, "result": event, "wall_seconds": time.perf_counter() - started}


def incumbent_gate(binary, report, save):
    cases = json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))
    facelets = next(case["facelets"] for case in cases if case["name"] == "initial-12")
    source = json.loads((ROOT / "docs/benchmarks/htm-review-2026-10-05/incumbent-probe.json").read_text(encoding="utf-8"))
    moves = source["moves"]
    replay(facelets, moves)
    for inverse in (False, True):
        service = Service(binary, "HTM", ["--no-direction-probe"] + (["--inverse-direction"] if inverse else []))
        try:
            seed = request(service, "seed", facelets, moves, 15, 10)
            assert seed["result"]["optimal"] and seed["result"]["completed_depth"] == 16
            report["runs"].append({"kind": "seed", "inverse": inverse, **seed})
            save()
            for threads in (1, 2, 3, 15):
                for mode in ("bound_met", "cancel_race", "deadline_race", "unproved"):
                    sent = False
                    name = f"late-{inverse}-{threads}-{mode}"
                    candidate = moves if mode != "unproved" else [*moves, "U", "U'"]
                    timeout = 0.005 if mode == "deadline_race" else 0.6 if mode == "unproved" else 2

                    def update(event):
                        nonlocal sent
                        if not sent and event.get("type") == "progress" and event["current_depth"] == 17:
                            if mode in {"bound_met", "cancel_race"} and event["elapsed_seconds"] < 0.20:
                                return
                            sent = True
                            commands = f"incumbent\t{name}\t{' '.join(candidate)}\n"
                            if mode == "cancel_race":
                                commands += f"cancel\t{name}\n"
                            service.process.stdin.write(commands)
                            service.process.stdin.flush()

                    row = request(service, name, facelets, [], threads, timeout, update)
                    result = row["result"]
                    assert sent and result.get("ok"), row
                    assert result["completed_depth"] == 16, row
                    if mode == "bound_met":
                        assert result["optimal"] and result["depth"] == 17, row
                        assert result["stop_reason"] == "bound_met", row
                        stages = [e["stage"] for e in row["events"] if e["type"] == "incumbent"]
                        assert stages == ["received", "validated", "adopted"], stages
                        adopted = next(e["received_seconds"] for e in row["events"] if e.get("stage") == "adopted")
                        assert row["wall_seconds"] - adopted < 0.25, row
                        replay(facelets, result["moves"])
                    else:
                        assert not result["optimal"], row
                        assert result["status"] == ("cancelled" if mode == "cancel_race" else "timeout"), row
                        if mode == "unproved":
                            assert result["incumbent_adoptions"] == 1 and result["depth"] == 19, row
                            replay(facelets, result["moves"])
                    report["runs"].append({"kind": mode, "inverse": inverse, "threads": threads, **row})
                    print(json.dumps({"kind": mode, "inverse": inverse, "threads": threads,
                                      "seconds": row["wall_seconds"], "status": result["status"]}), flush=True)
                    save()
        finally:
            service.close()


def pair_gate(baseline, current, report, save, current_extra):
    cases = {c["name"]: c for c in json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}
    services = {}
    try:
        services["baseline"] = Service(baseline, "HTM", ["--no-direction-probe"])
        services["current"] = Service(current, "HTM", ["--no-direction-probe", *current_extra])
        for repeat, labels in enumerate(ORDER):
            for name in ("initial-1", "initial-12"):
                for label in labels:
                    row = services[label].solve(cases[name]["facelets"], 16, 10, 15, "unused")
                    assert row["result"].get("type") == "error", row
                    assert row["progress"][-1]["completed_depth"] == 16, row
                    row.update(binary=label, case=name, repeat=repeat)
                    report["runs"].append(row)
                    print(json.dumps({"case": name, "binary": label, "seconds": row["wall_seconds"]}), flush=True)
                    save()
        report["summary"] = {}
        for name in ("initial-1", "initial-12"):
            rows = [r for r in report["runs"] if r["case"] == name]
            frames = [r["progress"][-1] for r in rows]
            for key in TREE_COUNTERS:
                assert len({json.dumps(f.get(key), sort_keys=True) for f in frames}) == 1, (name, key)
            medians = {label: statistics.median(r["wall_seconds"] for r in rows if r["binary"] == label)
                       for label in services}
            report["summary"][name] = {"median_seconds": medians,
                "current_over_baseline": medians["current"] / medians["baseline"],
                "generated": frames[0]["generated_candidates"],
                "tree_counters": {k: frames[0].get(k) for k in TREE_COUNTERS}}
        report["adopt"] = all(r["current_over_baseline"] <= 0.95 for r in report["summary"].values())
        print(json.dumps(report["summary"], indent=2), flush=True)
    finally:
        for service in services.values():
            service.close()


def candidate_gate(binary, report, save):
    import cube_app.solvers.htm.native_fast as native_fast
    from cube_app.solvers.htm.fast import FastTwoPhaseSolver
    from cube_app.solvers.htm.tables import load_or_build_tables
    native_fast.NATIVE_EXE = binary.resolve()
    native = native_fast.NativeHtmCandidate()
    python = FastTwoPhaseSolver(tables=load_or_build_tables(ROOT / ".cache/htm"))
    cases = {c["name"]: c for c in json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}
    known = {"initial-1": 18, "initial-12": 17}
    try:
        for repeat in range(3):
            for name in ("initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16"):
                for label in (("python", "native-single", "native-six") if repeat % 2 == 0 else
                              ("native-six", "native-single", "python")):
                    curve = []
                    start = time.monotonic()
                    cube = from_facelets(cases[name]["facelets"])

                    def observe(result):
                        replay(cases[name]["facelets"], result.moves)
                        assert result.depth == len(result.moves) and result.metric == "HTM" and not result.optimal
                        curve.append({"seconds": time.monotonic() - start, "depth": result.depth, "moves": result.moves})

                    if label == "python":
                        result = python.solve_cube(cube, timeout_seconds=1.5, candidate_callback=observe)
                    else:
                        result = native.solve(cube, timeout_seconds=1.5, candidate_callback=observe, cancel_event=None,
                                              deadline=None, directions=6 if label == "native-six" else 1)
                    replay(cases[name]["facelets"], result.moves)
                    row = {"repeat": repeat, "case": name, "label": label, "curve": curve,
                           "seconds": time.monotonic() - start, "depth": result.depth,
                           "reached_known_optimum": result.depth == known.get(name)}
                    report["runs"].append(row)
                    save()
                    print(json.dumps({k: row[k] for k in ("repeat", "case", "label", "seconds", "depth")}), flush=True)
        report["summary"] = {label: {"median_depth": statistics.median(r["depth"] for r in report["runs"] if r["label"] == label),
            "known_optimum_hits": sum(r["reached_known_optimum"] for r in report["runs"] if r["label"] == label)}
            for label in ("python", "native-single", "native-six")}
    finally:
        native.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("incumbent", "pair", "candidate"))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--current-extra", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite earlier evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"mode": args.mode, "runs": [], "identity": {}}
    for label in ("baseline", "current"):
        binary = getattr(args, label)
        if binary:
            report["identity"][label] = {"path": str(binary.resolve()),
                                        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}

    def save():
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        if args.mode == "incumbent":
            incumbent_gate(args.current, report, save)
        elif args.mode == "candidate":
            candidate_gate(args.current, report, save)
        else:
            if not args.baseline:
                parser.error("pair requires --baseline")
            pair_gate(args.baseline, args.current, report, save, args.current_extra)
        report["passed"] = True
    except BaseException as error:
        report["error"] = repr(error)
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
