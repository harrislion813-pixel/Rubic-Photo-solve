from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from server import AppHandler, ExclusiveThreadingHTTPServer, HOST


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
