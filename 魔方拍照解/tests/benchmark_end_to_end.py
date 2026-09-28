"""Measure hot HTTP QTM requests, including first candidate and three-second quality."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from benchmark_native import case_state, file_metadata
from cube_app.cubie import MOVE_INDEX, to_facelets
from cube_app.metrics import solution_cost


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"complete", "budget_exhausted", "timeout", "error", "cancelled"}


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def valid_cost(cube, payload: dict, metric: str) -> int | None:
    moves = payload.get("moves")
    if not isinstance(moves, list) or not moves:
        return None
    state = cube
    for name in moves:
        state = state.apply_move_index(MOVE_INDEX[name])
    cost = solution_cost(moves, metric)
    if not state.is_solved() or cost != payload.get("depth"):
        raise AssertionError("HTTP candidate failed whole-cube or metric verification")
    return cost


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-file", type=Path, default=ROOT / "tests/qtm_acceptance_cases.json")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/qtm-end-to-end.json")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--metric", choices=("HTM", "QTM"), default="QTM")
    parser.add_argument("--profile", choices=("base", "standard", "strong", "partial", "fallback"),
                        default="strong")
    args = parser.parse_args()
    if not 0.1 <= args.timeout <= 3600:
        parser.error("timeout must be 0.1..3600 seconds")
    cases = [case for case in json.loads(args.cases_file.read_text(encoding="utf-8"))
             if case["source"]["kind"] == "independent_legal_state_rng"]
    if len(cases) != 32:
        raise AssertionError(f"expected 32 independent random states, got {len(cases)}")
    port_file = ROOT / ".cache/server_port.txt"
    old_mtime = port_file.stat().st_mtime_ns if port_file.exists() else -1
    started = time.monotonic()
    process = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "server.py"], cwd=ROOT,
                               env={**os.environ, "CUBE_NO_BROWSER": "1"},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = started + 120
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"HTTP server exited with {process.returncode}")
            if port_file.is_file() and port_file.stat().st_mtime_ns != old_mtime:
                base = port_file.read_text(encoding="utf-8").strip().rstrip("/")
                break
            time.sleep(0.05)
        else:
            raise TimeoutError("HTTP server did not create a new port file")
        if not get(base + "/api/version").get("ok"):
            raise AssertionError("HTTP version check failed")
        output = {"schema_version": 1, "metric": args.metric, "profile": args.profile,
                  "timeout": args.timeout,
                  "cases_file": file_metadata(args.cases_file),
                  "native_binary": file_metadata(ROOT / "native/build/cube_solver.exe"),
                  "server_startup_seconds": time.monotonic() - started, "runs": []}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        oracle = next(case for case in json.loads(args.cases_file.read_text(encoding="utf-8"))
                      if case.get("expected_qtm_depth") is not None)
        cold_cube, _ = case_state(oracle)
        cold_started = time.monotonic()
        cold = post(base + "/api/solve", {"facelets": to_facelets(cold_cube), "cube_size": 3,
                                            "metric": args.metric, "timeout_seconds": 20})
        cold_job_id = cold.get("job_id")
        cold_status = cold.get("proof_status")
        while cold_job_id and cold_status not in TERMINAL:
            time.sleep(0.05)
            cold = get(base + "/api/solve/" + cold_job_id)
            cold_status = cold.get("status")
        cold_result = cold.get("result") or cold
        if valid_cost(cold_cube, cold_result, args.metric) is None or cold_status != "complete":
            raise AssertionError(f"cold native warmup failed: {cold}")
        if cold_result.get("asset_profile") != args.profile:
            raise AssertionError(f"unexpected cold asset profile: {cold_result.get('asset_profile')}")
        output["first_request"] = {"case": oracle["name"], "seconds": time.monotonic() - cold_started,
                                   "status": cold_status, "depth": cold_result["depth"],
                                   "asset_profile": cold_result.get("asset_profile")}
        args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
        for case in cases:
            cube, _ = case_state(case)
            request_started = time.monotonic()
            response = post(base + "/api/solve", {"facelets": to_facelets(cube), "cube_size": 3,
                                                   "metric": args.metric, "max_depth": 26 if args.metric == "QTM" else 20,
                                                   "timeout_seconds": args.timeout})
            request_seconds = time.monotonic() - request_started
            if not response.get("ok"):
                raise AssertionError(response)
            best_cost = valid_cost(cube, response, args.metric)
            first_candidate = request_seconds if best_cost is not None else None
            job_id = response.get("job_id")
            status = response.get("proof_status")
            final = response
            while job_id and status not in TERMINAL:
                time.sleep(0.05)
                final = get(base + "/api/solve/" + job_id)
                status = final.get("status")
                candidate = final.get("candidate_result") or final.get("result") or {}
                cost = valid_cost(cube, candidate, args.metric)
                if cost is not None:
                    best_cost = cost if best_cost is None else min(best_cost, cost)
                    if first_candidate is None:
                        first_candidate = time.monotonic() - request_started
            run = {"case": case["name"], "status": status, "request_seconds": request_seconds,
                   "total_seconds": time.monotonic() - request_started, "first_candidate_seconds": first_candidate,
                   "candidate_cost": best_cost, "engine": final.get("engine"),
                   "asset_profile": (final.get("result") or final).get("asset_profile") or final.get("asset_profile"),
                   "proof_depth": (final.get("result") or final).get("depth") if status == "complete" else None}
            if run["asset_profile"] != args.profile:
                raise AssertionError(f"unexpected asset profile for {case['name']}: {run['asset_profile']}")
            output["runs"].append(run)
            args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
            print(json.dumps(run), flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
