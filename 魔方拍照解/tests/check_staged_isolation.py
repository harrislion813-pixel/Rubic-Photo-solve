"""A five-second default staged HTTP request and a bounded reuse diagnostic.

Reuse is a measurement-only prototype. The production backend still releases
the process after every request. No native process is left alive by this script.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from benchmark_native import peak_memory  # noqa: E402
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets  # noqa: E402
from cube_app.solvers.qtm import backend, native  # noqa: E402
from cube_app.solvers.htm import native as htm_native  # noqa: E402
from cube_app.solvers.resource_broker import BROKER  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-diagnostic", action="store_true")
    args = parser.parse_args()
    # Exercise the adapter default by removing the eager override from old runners.
    os.environ.pop("CUBE_NATIVE_ASSET_LOADING", None)
    http_server, port = server.create_server()
    worker = threading.Thread(target=lambda: http_server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    events = []
    original_solve = native.solve_native

    def traced_solve(*positional, **kwargs):
        original_progress = kwargs.get("progress_callback")

        def progress(event):
            events.append({"observed_at": time.monotonic(), "event": event})
            if original_progress:
                original_progress(event)

        kwargs["progress_callback"] = progress
        return original_solve(*positional, **kwargs)

    native.solve_native = traced_solve
    report = {"asset_loading": "adapter-default-staged", "threads": BROKER.threads, "events": events}

    def post(payload):
        request = Request(f"http://127.0.0.1:{port}/api/solve", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    try:
        assert native._PERSISTENT_SOLVER._process is None
        case = json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))[0]
        report["case"] = case["name"]
        report["initial"] = post({"metric": "QTM", "facelets": case["facelets"], "timeout_seconds": 5})
        job_id = report["initial"]["job_id"]
        job = backend.BACKEND._jobs[job_id]
        until = time.monotonic() + 8
        while not job["_done"].is_set() and time.monotonic() < until:
            with urlopen(f"http://127.0.0.1:{port}/api/solve/{job_id}", timeout=2) as response:
                json.load(response)
            job["_done"].wait(0.05)
        if not job["_done"].is_set():
            raise TimeoutError("staged request did not release within bounded cleanup time")
        report["final"] = backend.BACKEND.snapshot(job_id)
        report["after_default"] = BROKER.snapshot()
        assert report["final"]["status"] in {"timeout", "complete", "budget_exhausted"}
        assert not report["after_default"]["qtm_active"]
        assert native._PERSISTENT_SOLVER._process is None
        assert any(item["event"].get("asset_loading") == "staged" for item in events)
        cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        facelets = to_facelets(cube)
        report["immediate_release"] = []
        for _ in range(2):
            started = time.monotonic()
            first = post({"metric": "QTM", "facelets": facelets, "max_depth": 2, "timeout_seconds": 5})
            assert backend.BACKEND._jobs[first["job_id"]]["_done"].wait(7)
            final = backend.BACKEND.snapshot(first["job_id"])
            assert final["optimal"] and final["result"]["depth"] == 2
            report["immediate_release"].append({"wall_seconds": time.monotonic() - started, "job": final})

        def htm_easy():
            first = post({"metric": "HTM", "facelets": facelets, "max_depth": 1, "timeout_seconds": 5})
            if first.get("job_id"):
                assert server.JOBS[first["job_id"]]["_done"].wait(7)
                first = server.JOBS[first["job_id"]]["result"]
            assert first["optimal"] and first["depth"] == 1
            return first

        report["htm_warmup"] = htm_easy()
        qtm_first = post({"metric": "QTM", "facelets": case["facelets"], "timeout_seconds": 5})
        ready_until = time.monotonic() + 3
        while native._PERSISTENT_SOLVER._ready is None and time.monotonic() < ready_until:
            time.sleep(0.01)
        assert native._PERSISTENT_SOLVER._ready is not None, "preemption must interrupt a ready engine"
        preempt_started = time.monotonic()
        report["htm_preempt_result"] = htm_easy()
        preempted = backend.BACKEND._jobs[qtm_first["job_id"]]
        assert preempted["_done"].wait(4)
        report["preemption"] = {"htm_wall_seconds": time.monotonic() - preempt_started,
                                "resource_wait_seconds": report["htm_preempt_result"]["resource_wait_seconds"],
                                "broker": BROKER.snapshot(),
                                "qtm": backend.BACKEND.snapshot(qtm_first["job_id"])}
        assert report["preemption"]["qtm"]["status"] == "cancelled"
        assert report["preemption"]["broker"]["yield_faults"] == 0
        assert native._PERSISTENT_SOLVER._process is None

        if args.reuse_diagnostic:
            # One resource lease contains two subrequests. This measures warm-process
            # benefit and cleanup cost, not a production scheduler implementation.
            cancel = threading.Event()
            assert BROKER.acquire_qtm(cancel, native.force_yield, time.monotonic() + 5)
            idle_until = time.monotonic() + 20
            max_memory = 1024 * 1024 * 1024
            expiry = threading.Timer(20, native.force_yield)
            expiry.daemon = True
            expiry.start()
            reuse = {"idle_limit_seconds": 20, "memory_limit_bytes": max_memory, "runs": []}
            report["reuse_prototype"] = reuse
            try:
                for _ in range(2):
                    started = time.monotonic()
                    result = native.solve_native(cube, max_depth=2, timeout_seconds=5,
                                                 incumbent_moves=None, cancel_event=cancel, threads=BROKER.threads)
                    process = native._PERSISTENT_SOLVER._process
                    memory = peak_memory(process) if process is not None else None
                    reuse["runs"].append({"wall_seconds": time.monotonic() - started,
                                          "result": result, "peak_memory_bytes": memory})
                    assert result and result["optimal"] and result["depth"] == 2
                    if time.monotonic() >= idle_until or memory is None or memory > max_memory:
                        native.release_assets()
                        reuse["evicted_for_limit"] = True
                cleanup_started = time.monotonic()
                native.release_assets()
                reuse["htm_cleanup_extra_seconds"] = time.monotonic() - cleanup_started
            finally:
                expiry.cancel()
                native.release_assets()
                BROKER.release_qtm()
            # HTM-only search follows the measured QTM release. Include the separate
            # broker wait and final process count, not HTM initialization as yield time.
            claimed = False
            try:
                reuse["htm_broker_wait_seconds"] = BROKER.enter_htm(deadline=time.monotonic() + 5)
                claimed = True
                reuse["htm_result"] = htm_native.solve_native(
                    cube, max_depth=1, timeout_seconds=5, incumbent_moves=None, cancel_event=None,
                    threads=BROKER.threads,
                )
                assert reuse["htm_result"]["optimal"] and reuse["htm_result"]["depth"] == 1
            finally:
                if claimed:
                    BROKER.leave_htm()
            assert native._PERSISTENT_SOLVER._process is None
    finally:
        native.solve_native = original_solve
        native.release_assets()
        http_server.shutdown()
        http_server.server_close()
        worker.join(2)
        report["broker_final"] = BROKER.snapshot()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["final"]["status"], "candidate": report["final"]["first_candidate_seconds"],
                      "staged": True, "released": not report["broker_final"]["qtm_active"]}))


if __name__ == "__main__":
    main()
