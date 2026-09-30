"""Small request lifecycle check for lazy QTM, release, and HTM preemption."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets  # noqa: E402
from cube_app.solvers.resource_broker import BROKER  # noqa: E402

os.environ["CUBE_NATIVE_ASSET_LOADING"] = "eager"

import server  # noqa: E402


def request(base: str, route: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + route, data=data, method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def wait_job(base: str, first: dict, deadline: float = 35) -> dict:
    if not first.get("job_id"):
        return first
    until = time.monotonic() + deadline
    while time.monotonic() < until:
        latest = request(base, "/api/solve/" + first["job_id"])
        if latest.get("status") in {"complete", "timeout", "cancelled", "error", "budget_exhausted"}:
            return latest
        time.sleep(0.1)
    raise TimeoutError("job did not finish within lifecycle budget")


def main() -> None:
    from cube_app.solvers.qtm import native as qtm_native

    server.AppHandler.log_message = lambda self, *args: None
    server_instance, port = server.create_server()
    worker = threading.Thread(target=server_instance.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{port}"
    report = {"threads": BROKER.threads, "before": BROKER.snapshot()}
    if qtm_native._PERSISTENT_SOLVER._process is not None or report["before"]["qtm_active"]:
        raise AssertionError("QTM was preheated before a QTM request")
    try:
        cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        easy = request(base, "/api/solve", {
            "facelets": to_facelets(cube), "cube_size": 3, "metric": "QTM",
            "max_depth": 2, "timeout_seconds": 30,
        })
        report["qtm_shallow_initial"] = easy
        done = wait_job(base, easy)
        report["qtm_shallow_final"] = done
        result = done.get("result") or done
        if done.get("status", done.get("proof_status")) != "complete" or result.get("depth") != 2 or not result.get("optimal"):
            raise AssertionError("QTM shallow exact answer failed")
        until = time.monotonic() + 5
        while (BROKER.snapshot()["qtm_active"]
               or (qtm_native._PERSISTENT_SOLVER._process is not None
                   and qtm_native._PERSISTENT_SOLVER._process.poll() is None)) and time.monotonic() < until:
            time.sleep(0.05)
        report["after_shallow"] = BROKER.snapshot()
        current = qtm_native._PERSISTENT_SOLVER._process
        if (current is not None and current.poll() is None) or report["after_shallow"]["qtm_active"]:
            raise AssertionError("QTM native assets stayed resident after a request")

        hard = json.loads((ROOT / "tests" / "initial_solver_cases.json").read_text(encoding="utf-8"))[0]
        first = request(base, "/api/solve", {
            "facelets": hard["facelets"], "cube_size": 3, "metric": "QTM",
            "max_depth": 26, "timeout_seconds": 30,
        })
        report["qtm_preempt_initial"] = first
        until = time.monotonic() + 10
        while (qtm_native._PERSISTENT_SOLVER._process is None
               or qtm_native._PERSISTENT_SOLVER._process.poll() is not None) and time.monotonic() < until:
            time.sleep(0.05)
        current = qtm_native._PERSISTENT_SOLVER._process
        if current is None or current.poll() is not None:
            raise AssertionError("QTM did not start for preemption check")
        before_htm = time.monotonic()
        htm = request(base, "/api/solve", {
            "facelets": to_facelets(cube), "cube_size": 3, "metric": "HTM",
            "max_depth": 1, "timeout_seconds": 10,
        })
        report["htm_after_preempt"] = {"response": htm, "wall_seconds": time.monotonic() - before_htm}
        htm_done = wait_job(base, htm, 10)
        if (htm_done.get("status", htm_done.get("proof_status")) != "complete"
                or (htm_done.get("result") or htm_done).get("depth") != 1):
            raise AssertionError("HTM did not solve after QTM cancellation")
        report["qtm_after_preempt"] = wait_job(base, first, 10)
        if report["qtm_after_preempt"].get("status") != "cancelled":
            raise AssertionError("QTM did not yield to HTM")
        report["after_preempt"] = BROKER.snapshot()
        if report["after_preempt"]["yield_faults"]:
            raise AssertionError("QTM resource yield fault")

        original_solve = qtm_native.solve_native

        def injected_failure(*args, **kwargs):
            raise qtm_native.NativeSolverError("injected QTM native failure")

        qtm_native.solve_native = injected_failure
        try:
            fault = request(base, "/api/solve", {
                "facelets": to_facelets(cube), "cube_size": 3, "metric": "QTM",
                "max_depth": 2, "timeout_seconds": 8,
            })
            report["qtm_fault_final"] = wait_job(base, fault, 8)
        finally:
            qtm_native.solve_native = original_solve
        recovered = request(base, "/api/solve", {
            "facelets": to_facelets(cube), "cube_size": 3, "metric": "HTM",
            "max_depth": 1, "timeout_seconds": 5,
        })
        report["htm_after_qtm_fault"] = wait_job(base, recovered, 5)
        if (report["htm_after_qtm_fault"].get("status", report["htm_after_qtm_fault"].get("proof_status"))
                != "complete"):
            raise AssertionError("QTM failure affected an HTM request")
    finally:
        server_instance.shutdown()
        server_instance.server_close()
        qtm_native.release_assets()
        report["final"] = BROKER.snapshot()
        output = ROOT / "docs" / "benchmarks" / "isolation-api-lifecycle.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"qtm_shallow": report["qtm_shallow_final"].get("status"),
                      "qtm_yield": report["qtm_after_preempt"].get("status"),
                      "htm_after_yield_seconds": report["htm_after_preempt"]["wall_seconds"]}))


if __name__ == "__main__":
    main()
