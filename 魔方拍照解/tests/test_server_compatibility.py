from __future__ import annotations

import json
from pathlib import Path

import server
from cube_app.cubie import CubieCube, MOVE_INDEX
from cube_app.solvers.resource_broker import ResourceBroker


def test_facade_preserves_existing_public_names_and_shared_state():
    expected = json.loads((Path(__file__).with_name("server-public-api.json")).read_text(encoding="utf-8"))
    assert set(expected) <= set(vars(server))
    assert server._runtime.JOBS is server.JOBS
    assert server._runtime.JOBS_LOCK is server.JOBS_LOCK
    assert server.AppHandler.runtime is server._runtime


def test_whole_broker_replacement_and_solver_patch_reach_extracted_workers(monkeypatch):
    original = ResourceBroker(3)
    replacement = ResourceBroker(5)
    calls = []

    def native(cube, **options):
        calls.append(options["threads"])
        return {"moves": ["R'"], "depth": 1, "metric": "HTM", "optimal": True, "engine": "native-cpp"}

    monkeypatch.setattr(server, "solve_native", native)
    monkeypatch.setattr(server, "BROKER", original)
    cube = CubieCube().apply_move_index(MOVE_INDEX["R"])
    first, worker = server.prepare_optimal_job(cube, None, 20, 2)
    monkeypatch.setattr(server, "BROKER", replacement)
    second, next_worker = server.prepare_optimal_job(cube, None, 19, 2)
    try:
        assert server.JOBS[first]["_broker"] is original
        assert server.JOBS[second]["_broker"] is replacement
        worker.start()
        assert server.JOBS[first]["_done"].wait(3)
        next_worker.start()
        assert server.JOBS[second]["_done"].wait(3)
        assert calls == [3, 5]
        assert server.job_snapshot(first)["status"] == "complete"
        assert server.job_snapshot(second)["status"] == "complete"
        assert original.snapshot()["htm_holders"] == 0
        assert replacement.snapshot()["htm_holders"] == 0
    finally:
        with server.JOBS_LOCK:
            server.JOBS.pop(first, None)
            server.JOBS.pop(second, None)
