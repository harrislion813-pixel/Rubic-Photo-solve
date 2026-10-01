"""One bounded source-HTTP request with explicit, reproducible QTM scheduling."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--schedule", choices=("overlap", "strong-first"), default="strong-first")
    parser.add_argument("--loading", choices=("staged", "eager"), default="staged")
    parser.add_argument("--loader-threads", type=int, choices=(4, 8), default=4)
    parser.add_argument("--validation", choices=("legacy", "fused", "split"), default="legacy")
    parser.add_argument("--case", choices=("initial-1", "initial-12"), default="initial-12")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = {
        "CUBE_QTM_ASSET_PROFILE": "strong", "CUBE_QTM_STRONG_FORMAT": "nibble",
        "CUBE_NATIVE_ASSET_LOADING": args.loading, "CUBE_QTM_REUSE": "off",
        "CUBE_QTM_STRONG_UPGRADE": "boundary", "CUBE_QTM_STRONG_SLICE": "keep",
        "CUBE_QTM_PREFETCH": "off", "CUBE_QTM_LOADER_THREADS": str(args.loader_threads),
        "CUBE_QTM_LOADER_BUDGET": "shared", "CUBE_NATIVE_EDGE_PDBS": "off",
        "CUBE_QTM_PROOF_SCHEDULE": args.schedule, "CUBE_QTM_BASE_PROOF_WINDOW": "0.3",
        "CUBE_QTM_STRONG_VALIDATION": args.validation,
        "CUBE_QTM_BASE_IDLE_BYTES": str(1 << 30), "CUBE_QTM_STRONG_IDLE_BYTES": str(8 << 30),
        "CUBE_QTM_MEMORY_RESERVE_BYTES": str(2 << 30),
    }
    os.environ.update(settings)
    import server
    from cube_app.cubie import from_facelets, MOVE_INDEX
    from cube_app.metrics import solution_cost
    from cube_app.solvers.qtm import backend, native
    from cube_app.solvers.resource_broker import BROKER

    if args.binary:
        native.NATIVE_EXE = args.binary.resolve()
    events = []
    original = native.solve_native
    started = time.monotonic()

    def traced(*positional, **kwargs):
        callback = kwargs.get("progress_callback")

        def progress(event):
            events.append({"seconds": time.monotonic() - started, "event": event})
            if callback:
                callback(event)

        kwargs["progress_callback"] = progress
        return original(*positional, **kwargs)

    native.solve_native = traced
    server.AppHandler.log_message = lambda *unused: None
    http, port = server.create_server()
    worker = threading.Thread(target=lambda: http.serve_forever(poll_interval=.05), daemon=True)
    worker.start()
    case = next(item for item in json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))
                if item["name"] == args.case)
    report = {
        "case": case, "timeout": 30, "threads": BROKER.threads, "settings": settings,
        "binary_sha256": hashlib.sha256(native.NATIVE_EXE.read_bytes()).hexdigest(), "events": events,
        "cold_or_warm": "new process; OS file cache not cleared; prior asset reads",
        "scope": "source HTTP; 100 ms observation; production browser acceptance is separate",
    }
    try:
        started = time.monotonic()
        request = Request(f"http://127.0.0.1:{port}/api/solve",
                          data=json.dumps({"metric": "QTM", "facelets": case["facelets"],
                                           "timeout_seconds": 30}).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            first = json.load(response)
        report["initial"] = first
        job = backend.BACKEND._jobs[first["job_id"]]
        while not job["_done"].is_set() and time.monotonic() < started + 36:
            with urlopen(f"http://127.0.0.1:{port}/api/solve/{first['job_id']}", timeout=2) as response:
                json.load(response)
            job["_done"].wait(.1)
        assert job["_done"].is_set(), "request cleanup did not finish"
        report["final"] = final = backend.BACKEND.snapshot(first["job_id"])
        answer = final.get("result") or final.get("candidate_result")
        if answer and answer.get("depth") is not None:
            cube = from_facelets(case["facelets"])
            for move in answer["moves"]:
                cube = cube.apply_move_index(MOVE_INDEX[move])
            report["replay"] = {"solved": cube.is_solved(), "cost": solution_cost(answer["moves"], "QTM")}
            assert report["replay"]["solved"] and report["replay"]["cost"] == answer["depth"]
        print(json.dumps({key: final.get(key) for key in (
            "status", "optimal", "startup_seconds", "first_candidate_seconds", "strong_ready_seconds",
            "strong_adopted_seconds", "tail_adopted_seconds", "request_elapsed_seconds", "asset_profile"
        )}, ensure_ascii=False), flush=True)
    finally:
        native.solve_native = original
        native.release_assets()
        http.shutdown()
        http.server_close()
        worker.join(2)
        report["broker_after_cleanup"] = BROKER.snapshot()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
