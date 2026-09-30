from __future__ import annotations

import time
from unittest.mock import patch
import json
import threading
from urllib.request import Request, urlopen
from pathlib import Path

import pytest

from cube_app.cubie import CubieCube, MOVE_INDEX
from cube_app.solvers.htm.native import NativeSolverError, NativeSolverTimeout, _PersistentNativeSolver
from cube_app.solvers.htm.optimal import SolveResult
import server


def test_benchmark_acceptance_and_training_states_are_legal():
    from benchmark_native import case_state
    from cube_app.cubie import from_facelets, to_facelets

    for filename in ("native_cases.json", "native_pgo_cases.json"):
        cases = json.loads(Path(__file__).with_name(filename).read_text(encoding="utf-8"))
        for case in cases:
            state, incumbent = case_state(case)
            assert from_facelets(to_facelets(state)) == state
            if incumbent:
                for name in incumbent:
                    state = state.apply_move_index(MOVE_INDEX[name])
                assert state.is_solved()


def test_native_launch_failure_is_reported_as_engine_error():
    bridge = _PersistentNativeSolver()
    with patch("cube_app.solvers.htm.native.subprocess.Popen", side_effect=OSError("unable to launch executable")):
        with pytest.raises(NativeSolverError, match="could not start"):
            bridge.solve(CubieCube(), 0, 1, 1, None, None, None)


def cube_after(sequence: str) -> CubieCube:
    cube = CubieCube()
    for move in sequence.split():
        cube = cube.apply_move_index(MOVE_INDEX[move])
    return cube


@pytest.fixture
def jobs():
    with server.JOBS_LOCK:
        before = set(server.JOBS)
    yield
    with server.JOBS_LOCK:
        for key in set(server.JOBS) - before:
            server.JOBS.pop(key, None)


def test_unlimited_proof_uses_native(jobs):
    result = {"moves": ["R'"], "depth": 1, "optimal": True, "engine": "native-cpp"}
    with patch.object(server, "solve_native", return_value=result) as native:
        job_id, worker = server.prepare_optimal_job(cube_after("R"), None, 20, None)
        worker.start()
        worker.join(2)
    assert not worker.is_alive()
    assert native.call_args.kwargs["timeout_seconds"] is None
    assert native.call_args.kwargs["deadline"] is None
    assert server.JOBS[job_id]["result"]["engine"] == "native-cpp"


@pytest.mark.parametrize("timeout", [None, 0, "none"])
def test_http_unlimited_aliases_start_native_without_python_probe(jobs, timeout):
    result = {
        "moves": ["R'"],
        "solution": "R'",
        "depth": 1,
        "metric": "HTM",
        "optimal": True,
        "engine": "native-cpp",
        "elapsed_seconds": 0.001,
    }
    http_server = server.ExclusiveThreadingHTTPServer((server.HOST, 0), server.AppHandler)
    worker = threading.Thread(target=http_server.serve_forever, daemon=True)
    worker.start()
    try:
        with (
            patch.object(server, "native_solver_available", return_value=True),
            patch.object(server, "solve_native", return_value=result) as native,
            patch.object(server.PROBE_SOLVER, "solve_cube") as python,
        ):
            from cube_app.cubie import to_facelets

            request = Request(
                f"http://{server.HOST}:{http_server.server_address[1]}/api/solve",
                data=json.dumps({"facelets": to_facelets(cube_after("R")), "timeout_seconds": timeout}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read())
            assert payload["optimal"]
            assert payload["engine"] == "native-cpp"
            assert native.call_args.kwargs["timeout_seconds"] is None
            python.assert_not_called()
    finally:
        http_server.shutdown()
        http_server.server_close()
        worker.join(2)


def test_native_failure_uses_remaining_budget_and_exposes_reason(jobs):
    def failed_native(*args, **kwargs):
        time.sleep(0.06)
        raise NativeSolverError("PDB checksum mismatch")

    solved = SolveResult(["R'"], 1, "HTM", 0.001, True)
    with (
        patch.object(server, "solve_native", side_effect=failed_native),
        patch.object(server.SOLVER, "solve_cube", return_value=solved) as python,
    ):
        job_id, worker = server.prepare_optimal_job(cube_after("R"), None, 20, 0.2)
        worker.start()
        worker.join(2)
    assert not worker.is_alive()
    assert 0 < python.call_args.kwargs["timeout_seconds"] < 0.16
    assert python.call_args.kwargs["deadline"] == server.JOBS[job_id]["_deadline"]
    assert server.JOBS[job_id]["fallback_reason"] == "PDB checksum mismatch"
    assert server.JOBS[job_id]["engine"] == "python"


def test_queue_time_consumes_deadline_without_search(jobs):
    server.OPTIMAL_SEARCH_LOCK.acquire()
    try:
        with patch.object(server, "solve_native") as native:
            job_id, worker = server.prepare_optimal_job(cube_after("R U"), None, 20, 0.05)
            worker.start()
            worker.join(1)
            assert not worker.is_alive()
            assert server.JOBS[job_id]["status"] == "timeout"
            native.assert_not_called()
    finally:
        server.OPTIMAL_SEARCH_LOCK.release()


def test_queued_cancel_does_not_wait_for_cpu_lock(jobs):
    server.OPTIMAL_SEARCH_LOCK.acquire()
    try:
        job_id, worker = server.prepare_optimal_job(cube_after("R U"), None, 20, None)
        worker.start()
        server.JOBS[job_id]["_cancel_event"].set()
        worker.join(1)
        assert not worker.is_alive()
        assert server.JOBS[job_id]["status"] == "cancelled"
    finally:
        server.OPTIMAL_SEARCH_LOCK.release()


def test_same_active_state_reuses_worker(jobs):
    cube = cube_after("R U F")
    first, worker = server.prepare_optimal_job(cube, None, 20, 3)
    second, duplicate = server.prepare_optimal_job(cube, None, 20, 3)
    assert first == second
    assert worker is duplicate
    different_depth, _ = server.prepare_optimal_job(cube, None, 2, 3)
    assert different_depth != first


def test_native_timeout_does_not_restart_in_python(jobs):
    with (
        patch.object(server, "solve_native", side_effect=NativeSolverTimeout("deadline")),
        patch.object(server.SOLVER, "solve_cube") as python,
    ):
        job_id, worker = server.prepare_optimal_job(cube_after("R"), None, 20, 0.2)
        worker.start()
        worker.join(2)
    assert server.JOBS[job_id]["status"] == "timeout"
    python.assert_not_called()
