"""Fresh staged requests isolate Q2's one-shot late-Tail improvement."""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import time
from pathlib import Path

from benchmark_isolation_short import sha256
from cube_app.cubie import MOVE_INDEX, from_facelets
from cube_app.metrics import solution_cost
from cube_app.solvers.htm.native import _native_process_stats
from cube_app.solvers.qtm import native

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expansion", choices=("generic", "full-strong"), default="generic",
                        help="use full-strong explicitly to reproduce the original experimental configuration")
    args = parser.parse_args()
    # Use the production bridge's actual default asset/loading/search flags.
    for key in list(os.environ):
        if key.startswith("CUBE_"):
            del os.environ[key]
    os.environ["CUBE_QTM_EXPANSION"] = args.expansion
    native.NATIVE_EXE = args.binary.resolve()
    command = native._PersistentNativeSolver()._command()
    flags = [f for f in command[2:] if not f.startswith("--late-tail-improvement=")]
    fixtures = {c["name"]: c for c in json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}
    report = {"binary_sha256": sha256(args.binary), "flags": flags, "expansion": args.expansion,
              "threads": 15, "timeout_seconds": 30,
              "order": [["off", "on"], ["on", "off"], ["off", "on"]], "runs": [], "failures": [],
              "scope": "fresh production Python bridge including managed loader admission; normal staged flags; no incumbent or proof cache reuse; warm OS file cache"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for repeat, order in enumerate(report["order"]):
            for name in ("initial-1", "initial-12"):
                for mode in order:
                    native.release_assets()
                    os.environ["CUBE_QTM_LATE_TAIL_IMPROVEMENT"] = mode
                    started = time.monotonic()
                    run = {"name": name, "mode": mode, "repeat": repeat, "events": [],
                           "facelets_sha256": fixtures[name]["facelets_sha256"], "memory_samples": []}
                    report["runs"].append(run)
                    def observe(event):
                        event = copy.deepcopy(event)
                        run["events"].append({"seconds": time.monotonic() - started, "event": event})
                        if event.get("type") in {"engine_ready", "native_result"}:
                            run["memory_samples"].append(_native_process_stats(native._PERSISTENT_SOLVER._process))
                        if event.get("type") == "engine_ready":
                            run["ready"] = event
                            run["startup_seconds"] = time.monotonic() - started
                        if event.get("type") == "native_result":
                            run["result"] = event
                            run["request_seconds"] = event["client_terminal_at"] - started

                    try:
                        try:
                            native.solve_native(from_facelets(fixtures[name]["facelets"]), max_depth=26,
                                                timeout_seconds=30, deadline=started + 30, threads=15,
                                                incumbent_moves=None, cancel_event=None,
                                                progress_callback=observe, metric="QTM")
                        except native.NativeSolverTimeout as error:
                            run["deadline_exception"] = str(error)
                            assert "result" in run, "bridge timed out without a terminal native frame"
                        run["bridge_return_seconds"] = time.monotonic() - started
                        assert run["bridge_return_seconds"] <= 35, "production bridge exceeded cancellation watchdog"
                        run["diagnostics"] = native.service_diagnostics()
                        run["stderr"] = list(native._PERSISTENT_SOLVER._stderr_lines)
                    finally:
                        native.release_assets()
                    # A proof that still needs strong must have exercised the
                    # production managed-loader handshake, unlike a thin protocol
                    # fixture that leaves loader admission permanently pending.
                    result = run["result"]
                    assert run["ready"].get("warm_reused") is False, "native process was reused"
                    run["loader_admissions"] = [frame["event"] for frame in run["diagnostics"].get("service_events", [])
                                                if frame.get("event", {}).get("type") == "memory_admission"]
                    run["asset_ready_events"] = [frame["event"] for frame in run["events"]
                                                if frame["event"].get("type") == "asset_ready"]
                    run["asset_adopted_events"] = [frame["event"] for frame in run["events"]
                                                  if frame["event"].get("type") == "asset_adopted"]
                    strong_used = (result.get("strong_queries", 0) > 0
                                   or result.get("full_strong_expansions", 0) > 0)
                    run["managed_loader_valid"] = bool(strong_used or result.get("optimal") is True)
                    if strong_used:
                        assert any(event.get("admitted") is True for event in run["loader_admissions"]), "no recorded production loader admission"
                        assert run["asset_ready_events"] and run["asset_adopted_events"], "missing strong ready/adoption evidence"
                    assert run["managed_loader_valid"], "strong never adopted and no early optimal proof"
                    save()
                    # Independently replay every candidate and terminal formula.
                    for frame in run["events"]:
                        event = frame["event"]
                        if event.get("type") == "thread_activity":
                            assert sum(event.get(key, 0) for key in ("loader_reserved", "candidate", "proof")) <= 15
                            assert event.get("candidate", 0) <= 1
                        moves = event.get("moves")
                        if event.get("type") not in {"candidate", "native_result"}:
                            continue
                        assert event.get("metric") == "QTM"
                        assert isinstance(moves, list) and all(isinstance(move, str) and move in MOVE_INDEX for move in moves)
                        if not moves and event.get("depth") == -1 and not event.get("optimal"):
                            continue
                        state = from_facelets(fixtures[name]["facelets"])
                        for move in moves:
                            state = state.apply_move_index(MOVE_INDEX[move])
                        assert state.is_solved()
                        cost = solution_cost(moves, "QTM")
                        for field in ("cost", "depth"):
                            if event.get(field) is not None:
                                assert event[field] == cost, f"invalid QTM {field}: {event}"
                        expected = fixtures[name]["known_optimal_costs"]["QTM"]
                        assert cost >= expected, "candidate shorter than the independently known optimum"
                        if event.get("optimal"):
                            assert cost == expected, "incorrect known QTM optimum"
                    result = run["result"]
                    assert result.get("late_tail_attempts", 0) <= (1 if mode == "on" else 0)
                    run["replay_valid"] = True
                    run["strict_success"] = (result.get("status") == "complete" and result.get("optimal") is True
                                             and "deadline_exception" not in run
                                             and run["request_seconds"] <= 30)
                    run["par2_seconds"] = run["request_seconds"] if run["strict_success"] else 60
                    run["peak_working_set_bytes"] = max((sample.get("peak_working_set_bytes") or 0
                                                         for sample in run["memory_samples"]), default=0) or None
                    run["memory_scope"] = "native_process_lifetime_peak"
                    print(json.dumps({key: run[key] for key in ("name", "mode", "repeat", "request_seconds")}
                                     | {key: result.get(key) for key in ("depth", "optimal", "late_tail_attempts", "late_tail_improvements", "late_tail_seconds")}), flush=True)
        report["summary"] = {}
        for name in ("initial-1", "initial-12"):
            selected = [r for r in report["runs"] if r["name"] == name]
            medians = {mode: statistics.median(r["par2_seconds"] for r in selected if r["mode"] == mode) for mode in ("off", "on")}
            report["summary"][name] = {"par2_medians": medians, "on_over_off": medians["on"] / medians["off"],
                                       "par2_means": {mode: statistics.mean(r["par2_seconds"] for r in selected
                                                                           if r["mode"] == mode) for mode in ("off", "on")},
                                       "new_timeouts": [r["repeat"] for r in selected if r["mode"] == "on"
                                           and not r["strict_success"] and any(old["repeat"] == r["repeat"]
                                           and old["mode"] == "off" and old["strict_success"] for old in selected)],
                                       "attempts": [r["result"].get("late_tail_attempts", 0) for r in selected if r["mode"] == "on"],
                                       "improvements": [r["result"].get("late_tail_improvements", 0) for r in selected if r["mode"] == "on"]}
    except BaseException as error:
        if report["runs"]:
            report["runs"][-1].update(failure={"type": type(error).__name__, "message": str(error)},
                                      strict_success=False, par2_seconds=60)
        report["failures"].append({"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        native.release_assets()
        save()
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
