"""Required H1 real protocol gate with at most two seconds per search."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets  # noqa: E402
from cube_app.solvers.htm.native import (  # noqa: E402
    NATIVE_EXE,
    NativeSolverCancelled,
    _PersistentNativeSolver,
    _validated_result,
    native_solver_available,
)


def run_gate() -> dict:
    assert native_solver_available(), "required HTM binary and complete base PDB assets are missing"
    cube = CubieCube()
    for move in "U' F L R' D' B' F U' B2 L D R2 B2 L2 U2 L' U2 R'".split():
        cube = cube.apply_move_index(MOVE_INDEX[move])
    records = []
    for quota in (1, 2, 3):
        bridge = _PersistentNativeSolver()
        events = []
        progress = []
        cancel = threading.Event()
        requested = max(1, quota - 1)
        initial = requested

        def on_event(event):
            events.append({"monotonic": time.monotonic(), **event})

        def on_progress(event):
            nonlocal requested
            progress.append({"monotonic": time.monotonic(), **event})
            requested = quota
            if event["threads"] == quota and event.get("nodes", 0) > 0:
                cancel.set()

        try:
            startup = time.monotonic()
            with bridge._lock:
                bridge._start_locked(startup + 10, None)
            startup_seconds = time.monotonic() - startup
            assert bridge._dynamic_threads, "HTM binary lacks the required dynamic thread capability"
            search_started = time.monotonic()
            try:
                bridge.solve(cube, 20, 2, initial, None, cancel, on_progress,
                             event_callback=on_event, threads_provider=lambda: requested)
            except NativeSolverCancelled:
                status = "cancelled"
            else:
                raise AssertionError("the progress-driven cancellation did not stop the search")
            elapsed = time.monotonic() - search_started
            assert any(event["threads"] == quota and event.get("nodes", 0) > 0 for event in progress), \
                f"no search progress at the restored {quota}-thread quota"
            cancelled_payload = next(event["result"] for event in events
                                     if event["type"] == "native_result_received")
            assert cancelled_payload["status"] == "cancelled" and not cancelled_payload["optimal"]
            assert len(cancelled_payload["workers"]) == quota, "native worker quota was not restored"
            assert cancelled_payload["completed_depth"] < progress[-1]["current_depth"], \
                "an interrupted layer was reported as a complete exclusion proof"
            if quota > 1:
                assert any(event["type"] == "native_threads_sent" and event["threads"] == quota
                           for event in events), "candidate allowance was not returned through the protocol"
            assert bridge._process.poll() is None, "cancellation killed the reusable native process"
            restored_pid = bridge._process.pid
            # A different shallow state avoids any completed-depth certificate
            # from the cancelled search and proves bounded process reuse.
            shallow = CubieCube().apply_move_index(MOVE_INDEX["R"])
            payload = bridge.solve(shallow, 1, 2, quota, None, None, None, event_callback=on_event)
            result = _validated_result(shallow, payload)
            assert result["optimal"] and result["depth"] == 1
            assert bridge._process.pid == restored_pid
            memory_events = [event for event in events if event["type"] in
                             {"native_ready", "native_result_received", "native_request_finished"}]
            assert all(event["native_pid"] == restored_pid for event in memory_events)
            assert all(event["peak_working_set_bytes"] > 0 for event in memory_events), \
                "required Windows native process memory samples are unavailable"
            records.append({"thread_quota": quota, "initial_proof_threads": initial,
                            "startup_seconds": startup_seconds, "search_wall_seconds": elapsed,
                            "status": status, "progress": progress, "events": events,
                            "reuse_result": result})
        finally:
            bridge.close()
    return {"ok": True, "gate": "H1 dynamic threads 1/2/3, cancellation and reuse",
            "exe": str(NATIVE_EXE), "exe_sha256": hashlib.sha256(NATIVE_EXE.read_bytes()).hexdigest(),
            "facelets": to_facelets(cube), "search_timeout_seconds": 2, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_gate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "quotas": [record["thread_quota"] for record in result["records"]],
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
