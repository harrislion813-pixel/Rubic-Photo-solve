from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
import unittest
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.native import native_solver_available
from cube_app.optimal import SolveResult, invert_moves
from server import AppHandler, ExclusiveThreadingHTTPServer, HOST, JOBS, JOBS_LOCK, PROBE_SOLVER, prepare_optimal_job


def request_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


class HybridSolveApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # The latency assertion measures search/API time, not one-off table generation.
        _ = PROBE_SOLVER.tables

    def test_queued_job_can_be_cancelled(self) -> None:
        server = ExclusiveThreadingHTTPServer((HOST, 0), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        job_id, _ = prepare_optimal_job(CubieCube(), None, 20, 3)
        try:
            port = server.server_address[1]
            response = request_json(f"http://{HOST}:{port}/api/solve/{job_id}/cancel", {})
            self.assertTrue(response["ok"])
            self.assertEqual(response["status"], "cancelled")

            job = request_json(f"http://{HOST}:{port}/api/solve/{job_id}")
            self.assertEqual(job["status"], "cancelled")
        finally:
            with JOBS_LOCK:
                JOBS.pop(job_id, None)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @pytest.mark.native_pdb
    @unittest.skipUnless(native_solver_available(), "原生求解器或模式数据库尚未构建")
    def test_native_job_proves_an_incumbent_solution(self) -> None:
        cube = CubieCube()
        scramble = "R U F2 L D"
        for move in scramble.split():
            cube = cube.apply_move_index(MOVE_INDEX[move])
        incumbent = invert_moves(scramble.split())
        quick_result = SolveResult(incumbent, len(incumbent), "HTM", 0.0, False)
        job_id, worker = prepare_optimal_job(cube, quick_result, 20, 10)
        try:
            worker.start()
            worker.join(timeout=15)
            self.assertFalse(worker.is_alive())
            with JOBS_LOCK:
                job = dict(JOBS[job_id])
            self.assertEqual(job["status"], "complete")
            self.assertTrue(job["result"]["optimal"])
            self.assertEqual(job["result"]["engine"], "native-cpp")
        finally:
            with JOBS_LOCK:
                JOBS.pop(job_id, None)

    def test_quick_result_arrives_before_optimal_job_finishes(self) -> None:
        server = ExclusiveThreadingHTTPServer((HOST, 0), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            cube = CubieCube()
            scramble = "B' U' L' U2 F L' F2 U2 R' U L D2 F2 D' L D'"
            for move in scramble.split():
                cube = cube.apply_move_index(MOVE_INDEX[move])

            port = server.server_address[1]
            started = time.perf_counter()
            response = request_json(
                f"http://{HOST}:{port}/api/solve",
                {
                    "facelets": to_facelets(cube),
                    "max_depth": 20,
                    "timeout_seconds": 3,
                },
            )
            quick_elapsed = time.perf_counter() - started
            self.assertTrue(response["ok"])
            self.assertFalse(response["optimal"])
            self.assertTrue(response["job_id"])
            self.assertTrue(response["solution"])
            self.assertLess(quick_elapsed, 2.5)

            solved = cube
            for move in response["moves"]:
                solved = solved.apply_move_index(MOVE_INDEX[move])
            self.assertTrue(solved.is_solved())

            deadline = time.monotonic() + 6
            while True:
                job = request_json(f"http://{HOST}:{port}/api/solve/{response['job_id']}")
                if job["status"] in {"complete", "timeout", "error"}:
                    break
                if time.monotonic() >= deadline:
                    self.fail(f"Optimal job did not reach a terminal state: {job}")
                time.sleep(0.1)
            self.assertIn(job["status"], {"complete", "timeout"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
