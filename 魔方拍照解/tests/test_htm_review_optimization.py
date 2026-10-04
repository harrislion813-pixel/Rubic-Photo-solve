"""Real native regressions for the 2026-10-05 HTM review changes."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from urllib.request import Request, urlopen

import pytest

from benchmark_htm_review_optimization import incumbent_gate
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.solvers.htm.native import NATIVE_EXE, native_solver_available
from cube_app.solvers.htm.native_fast import NativeHtmCandidate
from cube_app.solvers.htm.optimal import SearchCancelled, SearchTimeout

pytestmark = pytest.mark.native_pdb


@pytest.fixture(autouse=True)
def require_native():
    if not native_solver_available():
        pytest.skip("HTM native binary and PDBs required")


def test_live_candidates_preserve_complete_proofs_and_stop_reasons():
    report = {"runs": []}
    incumbent_gate(NATIVE_EXE, report, lambda: None)
    assert len(report["runs"]) == 34


def test_symmetry_cache_identity_corruption_and_exhaustive_mapping(tmp_path):
    cache = tmp_path / "对称 缓存🧩.bin"
    env = {**os.environ, "CUBE_HTM_SYMMETRY_CACHE": str(cache)}

    def run(command="symmetry-info"):
        return json.loads(subprocess.check_output([str(NATIVE_EXE), command], env=env, text=True, encoding="utf-8"))

    assert run()["cache_loaded"] is False
    original = cache.read_bytes()
    assert run()["cache_loaded"] is True
    result = run("check-symmetry")
    assert result["checked"] == 1_013_760 and result["digest"] == 8672954801269671621
    for data in (b"truncated", original[:-1], original[:100] + b"corrupt" + original[107:]):
        cache.write_bytes(data)
        assert run()["cache_loaded"] is False
        assert cache.read_bytes() == original
        assert run()["cache_loaded"] is True


def test_native_candidate_replay_cancel_reuse_and_original_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("CUBE_HTM_PHASE2_CACHE", str(tmp_path / "phase2.bin"))
    solver = NativeHtmCandidate()
    cube = CubieCube()
    for name in "R U F2 L D B' R2 U'".split():
        cube = cube.apply_move_index(MOVE_INDEX[name])
    candidates = []
    try:
        result = solver.solve(cube, timeout_seconds=1.5, candidate_callback=candidates.append,
                              cancel_event=None, deadline=None, directions=6)
        assert candidates and not result.optimal and result.metric == "HTM"
        assert all(a.depth > b.depth for a, b in zip(candidates, candidates[1:]))
        for candidate in candidates:
            state = cube
            for name in candidate.moves:
                state = state.apply_move_index(MOVE_INDEX[name])
            assert state.is_solved() and candidate.depth == len(candidate.moves)
        process = solver.process
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(SearchCancelled):
            solver.solve(cube, timeout_seconds=1.5, candidate_callback=None, cancel_event=cancel, deadline=None)
        assert solver.process is process
        state = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        short = solver.solve(state, timeout_seconds=1.5, candidate_callback=None, cancel_event=None,
                             deadline=time.monotonic() + 0.2)
        assert short.moves == ["R2"] and short.depth == 1 and solver.process is process
        with pytest.raises(SearchTimeout):
            solver.solve(cube, timeout_seconds=5, candidate_callback=None, cancel_event=None,
                         deadline=time.monotonic() - 0.001)
        assert solver.process is process
        cancel.clear()
        with pytest.raises(SearchCancelled):
            solver.solve(cube, timeout_seconds=1.5, candidate_callback=lambda result: cancel.set(),
                         cancel_event=cancel, deadline=None, directions=6)
        assert solver.process is None
    finally:
        solver.close()
    original = (tmp_path / "phase2.bin").read_bytes()
    (tmp_path / "phase2.bin").write_bytes(b"corrupt")
    command = [str(NATIVE_EXE), "candidate", to_facelets(CubieCube()), "--timeout", "0.001"]
    output = json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))
    assert output["depth"] == 0
    assert (tmp_path / "phase2.bin").read_bytes() == original


@pytest.mark.parametrize("threads", [1, 2, 3, 15])
def test_real_http_native_candidate_quota_deadline_and_cleanup(monkeypatch, threads):
    import server
    from cube_app.solvers.resource_broker import ResourceBroker
    monkeypatch.setenv("CUBE_HTM_NATIVE_CANDIDATE", "six")
    monkeypatch.setenv("CUBE_HTM_EARLY_CANDIDATE", "off")
    monkeypatch.setattr(server, "BROKER", ResourceBroker(threads))
    monkeypatch.setattr(server.AppHandler, "log_message", lambda *args: None)
    cube = CubieCube()
    for name in "U' F L R' D' B' F U' B2 L D R2 B2 L2 U2 L' U2 R'".split():
        cube = cube.apply_move_index(MOVE_INDEX[name])
    http = server.ExclusiveThreadingHTTPServer((server.HOST, 0), server.AppHandler)
    listener = threading.Thread(target=lambda: http.serve_forever(poll_interval=0.01), daemon=True)
    listener.start()
    job = None
    try:
        body = json.dumps({"facelets": to_facelets(cube), "timeout_seconds": 1.8}).encode()
        url = f"http://{server.HOST}:{http.server_address[1]}/api/solve"
        request = Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
        job = server.JOBS[result["job_id"]]
        assert job["_done"].wait(2)
        worker = job.get("_candidate_worker")
        if worker:
            worker.join(2)
            assert not worker.is_alive()
        assert job["status"] == "timeout" and not (job.get("result") or {}).get("optimal")
        assert not job.get("candidate_error") and not job.get("fallback_reason")
        assert job["thread_quota"] == threads and job["_proof_threads"] == max(1, threads - 1)
        assert server.BROKER.snapshot()["htm_holders"] == 0
        assert not job["early_candidate_delivery"]
    finally:
        if job is not None:
            job["_cancel_event"].set()
            job["_candidate_stop"].set()
        http.shutdown()
        http.server_close()
