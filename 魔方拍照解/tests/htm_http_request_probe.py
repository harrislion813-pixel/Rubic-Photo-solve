"""One fresh, real HTTP request, run from an explicitly selected source root."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--facelets", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=15)
    args = parser.parse_args()
    sys.path.insert(0, str(args.root.resolve()))
    import server
    from cube_app.cubie import from_facelets, MOVE_INDEX
    from cube_app.solvers.htm.native import _PERSISTENT_SOLVER, _native_process_stats
    from cube_app.solvers.resource_broker import ResourceBroker

    server.BROKER = ResourceBroker(args.threads)
    server.AppHandler.log_message = lambda *args: None
    http = server.ExclusiveThreadingHTTPServer((server.HOST, 0), server.AppHandler)
    listener = threading.Thread(target=lambda: http.serve_forever(poll_interval=0.01), daemon=True)
    listener.start()
    base = f"http://{server.HOST}:{http.server_address[1]}"
    started = time.monotonic()
    payload = {"facelets": args.facelets, "cube_size": 3, "metric": "HTM", "max_depth": 20, "timeout_seconds": 30}
    request = Request(base + "/api/solve", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    report = {"request": payload, "native_candidate_policy": os.environ.get(
        "CUBE_HTM_NATIVE_CANDIDATE", getattr(server.FAST_SOLVER, "native_policy", "off"))}
    try:
        with urlopen(request, timeout=35) as response:
            first = json.loads(response.read())
        report["initial"] = first
        report["initial_http_seconds"] = time.monotonic() - started
        assert first["ok"] and first.get("job_id"), first
        snapshots = []
        while True:
            with urlopen(base + "/api/solve/" + first["job_id"], timeout=5) as response:
                snapshot = json.loads(response.read())
            snapshots.append({"seconds": time.monotonic() - started, "status": snapshot["status"],
                              "progress": snapshot.get("progress")})
            if snapshot["status"] in server.TERMINAL_STATUSES:
                break
            assert time.monotonic() - started < 34
            time.sleep(0.1)
        job = server.JOBS[first["job_id"]]
        assert job["_done"].wait(3)
        candidate_worker = job.get("_candidate_worker")
        if candidate_worker is not None:
            candidate_worker.join(3)
            assert not candidate_worker.is_alive()
        report["terminal"] = server.job_snapshot(first["job_id"])
        report["polls"] = snapshots
        report["wall_seconds"] = time.monotonic() - started
        formulas = [first, report["terminal"].get("candidate_result"), report["terminal"].get("result")]
        formulas += [e for e in report["terminal"]["timing_events"] if e.get("moves") is not None]
        report["replayed_formulas"] = 0
        for formula in formulas:
            if formula is None or formula.get("moves") is None or formula.get("depth") is None and formula.get("cost") is None:
                continue
            state = from_facelets(args.facelets)
            for move in formula["moves"]:
                state = state.apply_move_index(MOVE_INDEX[move])
            assert state.is_solved() and len(formula["moves"]) == formula.get("depth", formula.get("cost")), formula
            report["replayed_formulas"] += 1
        assert report["terminal"]["status"] in {"complete", "timeout"}, report["terminal"]
        assert not report["terminal"].get("fallback_reason") and not report["terminal"].get("candidate_error")
        assert report["terminal"]["early_candidate_delivery"] is False
        processes = {"proof": _PERSISTENT_SOLVER._process,
                     "python": SimpleNamespace(_handle=ctypes.windll.kernel32.GetCurrentProcess(), pid=os.getpid())}
        candidate_module = sys.modules.get("cube_app.solvers.htm.native_fast")
        if candidate_module:
            processes["candidate"] = candidate_module.NATIVE_CANDIDATE.process
        resources = {}
        for label, process in processes.items():
            if process is None:
                continue
            create, finish, kernel, user = [ctypes.c_uint64() for _ in range(4)]
            handle = ctypes.c_void_p(int(process._handle))
            assert ctypes.windll.kernel32.GetProcessTimes(handle, *[ctypes.byref(v) for v in (create, finish, kernel, user)])
            resources[label] = {**_native_process_stats(process), "cpu_seconds": (kernel.value + user.value) / 10_000_000}
        report["resources"] = resources
        report["broker_after_cleanup"] = server.BROKER.snapshot()
        assert report["broker_after_cleanup"]["htm_holders"] == 0
    finally:
        http.shutdown()
        http.server_close()
        _PERSISTENT_SOLVER.close()
        candidate_module = sys.modules.get("cube_app.solvers.htm.native_fast")
        if candidate_module:
            candidate_module.NATIVE_CANDIDATE.close()
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
