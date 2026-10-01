from __future__ import annotations

import json
import queue
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

import server
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.solvers.qtm import backend as qtm
from cube_app.solvers.qtm import native
from cube_app.solvers.qtm.two_by_two import TwoByTwoSolver
from cube_app.solvers.resource_broker import ResourceBroker, ResourceCancelled


def exact_result():
    return {"moves": ["R2"], "solution": "R2", "depth": 2, "optimal": True,
            "metric": "QTM", "elapsed_seconds": 0.02, "asset_profile": "base"}


@pytest.fixture
def backend(monkeypatch):
    instance = qtm.QtmBackend()
    monkeypatch.setattr(qtm, "BACKEND", instance)
    monkeypatch.setattr(qtm, "BROKER", ResourceBroker(1))
    monkeypatch.setattr(native, "native_solver_available", lambda: True)
    monkeypatch.setattr(native, "release_assets", lambda: None)
    monkeypatch.setattr(native, "service_diagnostics", lambda: {})
    yield instance
    for job in instance._jobs.values():
        job["_cancel"].set()
        assert job["_done"].wait(2), "QTM worker leaked beyond test"


@pytest.fixture
def http(monkeypatch):
    monkeypatch.setattr(server, "qtm_installed", lambda: True)
    http_server = server.ExclusiveThreadingHTTPServer((server.HOST, 0), server.AppHandler)
    worker = threading.Thread(target=lambda: http_server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()

    def post(payload):
        request = Request(f"http://{server.HOST}:{http_server.server_address[1]}/api/solve",
                          data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    yield post
    http_server.shutdown()
    http_server.server_close()
    worker.join(2)


@pytest.mark.parametrize("alias", [None, 0, "0", "none"])
@pytest.mark.parametrize("cube_size", [2, 3])
def test_qtm_http_unlimited_preserves_deadline(backend, http, monkeypatch, alias, cube_size):
    observed = {}

    def solve(*args, **kwargs):
        observed.update(kwargs)
        return exact_result()

    def solve_2x2(*args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(moves=["R2"], text="R2", depth=2)

    monkeypatch.setattr(native, "solve_native", solve)
    monkeypatch.setattr(TwoByTwoSolver, "solve_facelets", solve_2x2)
    result = http({"metric": "QTM", "cube_size": cube_size, "facelets": to_facelets(CubieCube()),
                   "timeout_seconds": alias})
    assert result["optimal"]
    assert observed["timeout_seconds"] is None
    if cube_size == 3:
        assert observed["deadline"] is None
        assert backend._jobs[result["job_id"]]["_deadline"] is None


def test_qtm_missing_timeout_uses_default(backend, http, monkeypatch):
    observed = {}

    def solve(*args, **kwargs):
        observed.update(kwargs)
        return exact_result()

    monkeypatch.setattr(native, "solve_native", solve)
    http({"metric": "QTM", "facelets": to_facelets(CubieCube())})
    assert 179 < observed["timeout_seconds"] <= 180 + 1e-6
    assert observed["deadline"] is not None


@pytest.mark.parametrize("cube_size", [2, 3])
def test_htm_http_resource_wait_consumes_budget(http, monkeypatch, cube_size):
    observed = {}
    broker = ResourceBroker(1)
    original_enter = broker.enter_htm
    original_leave = broker.leave_htm
    released = threading.Event()

    def leave_htm():
        original_leave()
        if broker.snapshot()["htm_holders"] == 0:
            released.set()

    def delayed_enter(**kwargs):
        time.sleep(0.06)
        observed["deadline"] = kwargs["deadline"]
        return original_enter(**kwargs)

    def solve_2x2(*args, **kwargs):
        observed["timeout"] = kwargs["timeout_seconds"]
        return SimpleNamespace(moves=[], text="", depth=0, metric="HTM", elapsed_seconds=0, optimal=True)

    def solve_native(*args, **kwargs):
        observed["timeout"] = kwargs["timeout_seconds"]
        assert kwargs["deadline"] == observed["deadline"]
        return {"moves": [], "solution": "", "depth": 0, "optimal": True, "metric": "HTM"}

    monkeypatch.setattr(broker, "enter_htm", delayed_enter)
    monkeypatch.setattr(broker, "leave_htm", leave_htm)
    monkeypatch.setattr(server, "BROKER", broker)
    monkeypatch.setattr(server.TWO_BY_TWO_SOLVER, "solve_facelets", solve_2x2)
    monkeypatch.setattr(server, "native_solver_available", lambda: True)
    monkeypatch.setattr(server, "solve_native", solve_native)
    result = http({"cube_size": cube_size, "facelets": to_facelets(CubieCube()), "timeout_seconds": 0.2})
    assert result["optimal"]
    # Windows monotonic readings can be quantized; the original bug passes 0.2.
    assert 0 < observed["timeout"] < 0.18
    # The HTTP body can arrive before the handler's finally block runs.
    assert released.wait(2), "HTM claim was not released after the response"
    assert broker.snapshot()["htm_holders"] == 0


def test_resource_wait_timeout_and_cancel_leave_no_claim():
    broker = ResourceBroker(1)
    cancel = threading.Event()
    assert broker.acquire_qtm(cancel, lambda: None, None)
    try:
        with pytest.raises(TimeoutError):
            broker.enter_htm(deadline=time.monotonic() + 0.03)
        assert cancel.is_set()
        assert broker.snapshot()["htm_holders"] == 0
        cancelled = threading.Event()
        cancelled.set()
        with pytest.raises(ResourceCancelled):
            broker.enter_htm(cancel_event=cancelled)
        assert broker.snapshot()["htm_holders"] == 0
    finally:
        broker.release_qtm()
    assert not broker.acquire_qtm(threading.Event(), lambda: None, time.monotonic() - 1)


def test_qtm_queue_timeout_never_starts_search(backend, monkeypatch):
    qtm.BROKER.enter_htm()
    calls = []
    monkeypatch.setattr(native, "solve_native", lambda *args, **kwargs: calls.append(kwargs))
    try:
        result = backend.submit(to_facelets(CubieCube()), 3, 2, 0.03)
        assert backend._jobs[result["job_id"]]["_done"].wait(1)
        assert backend.snapshot(result["job_id"])["status"] == "timeout"
        assert calls == []
    finally:
        qtm.BROKER.leave_htm()


def test_qtm_python_fallback_keeps_unlimited_budget(backend, monkeypatch):
    from cube_app.solvers.qtm import optimal

    observed = {}

    class Fallback:
        def __init__(self, *args, **kwargs):
            pass

        def solve_cube(self, *args, **kwargs):
            observed.update(kwargs)
            return SimpleNamespace(moves=["R2"], text="R2", depth=2)

    def fail(*args, **kwargs):
        raise native.NativeSolverError("injected fault")

    monkeypatch.setattr(native, "solve_native", fail)
    monkeypatch.setattr(optimal, "OptimalSolver", Fallback)
    result = backend.submit(to_facelets(CubieCube()), 3, 2, None)
    assert backend._jobs[result["job_id"]]["_done"].wait(1)
    assert observed["deadline"] is None and observed["timeout_seconds"] is None
    assert backend.snapshot(result["job_id"])["engine_id"] == "qtm-python"


def test_qtm_native_timeout_never_restarts_python(backend, monkeypatch):
    def expire(*args, **kwargs):
        raise native.NativeSolverTimeout("injected deadline")

    def fallback(*args, **kwargs):
        pytest.fail("native timeout restarted in Python")

    monkeypatch.setattr(native, "solve_native", expire)
    monkeypatch.setattr(backend, "_python_fallback", fallback)
    result = backend.submit(to_facelets(CubieCube()), 3, 2, 0.2)
    assert backend._jobs[result["job_id"]]["_done"].wait(1)
    assert backend.snapshot(result["job_id"])["status"] == "timeout"


def test_candidate_wakes_http_before_proof_finishes_and_stages_stay_distinct(backend, monkeypatch):
    finish = threading.Event()

    def solve(*args, **kwargs):
        progress = kwargs["progress_callback"]
        progress({"type": "asset_ready", "stage": "strong", "profile": "strong-no-tail"})
        progress({"type": "asset_ready", "stage": "tail", "profile": "strong"})
        assert backend.snapshot(next(iter(backend._jobs)))["asset_profile"] == "pending"
        progress({"type": "asset_adopted", "strong": True, "tail_depth": 8, "profile": "strong"})
        progress({"type": "candidate", "moves": ["R2"], "asset_profile": "strong"})
        assert finish.wait(2)
        return exact_result()

    monkeypatch.setattr(native, "solve_native", solve)
    try:
        before = time.monotonic()
        cube = CubieCube().apply_move_index(MOVE_INDEX["R2"])
        result = backend.submit(to_facelets(cube), 3, 2, None)
        assert time.monotonic() - before < 0.5
        assert result["moves"] == ["R2"]
        job_id = result["job_id"]
        assert not backend._jobs[job_id]["_done"].is_set()
        backend.mark_http_return(job_id)
        snapshot = backend.snapshot(job_id)
        assert snapshot["strong_ready_seconds"] <= snapshot["tail_ready_seconds"]
        assert snapshot["strong_adopted_seconds"] >= snapshot["strong_ready_seconds"]
        assert snapshot["candidate_delivery_seconds"] >= 0
    finally:
        finish.set()
    assert backend._jobs[job_id]["_done"].wait(1)
    snapshot = backend.snapshot(job_id)
    assert snapshot["native_search_seconds"] == snapshot["proof_wall_seconds"] == 0.02
    assert snapshot["resource_hold_seconds"] is not None


def test_native_ready_stage_records_only_first_arrival(monkeypatch):
    bridge = native._PersistentNativeSolver()
    bridge._ready = {}
    bridge._started_at = 10
    values = iter([11, 12, 13])
    monkeypatch.setattr(native.time, "monotonic", lambda: next(values))
    bridge._record_asset_ready({"stage": "strong", "strong": True})
    bridge._record_asset_ready({"stage": "tail", "strong": True, "tail_depth": 8})
    bridge._record_asset_ready({"stage": "strong", "strong": True})
    assert bridge.diagnostics()["strong_ready_elapsed_seconds"] == 1
    assert bridge.diagnostics()["tail_ready_elapsed_seconds"] == 2


def test_qtm_native_wire_preserves_unlimited_and_timeout_search_timing(monkeypatch):
    bridge = native._PersistentNativeSolver()
    bridge._process = SimpleNamespace(poll=lambda: None, stdin=True)
    bridge._lines = queue.Queue()
    bridge._ready = {}

    def send(message):
        fields = message.rstrip("\n").split("\t")
        assert fields[4] == "0", "unlimited was converted to a finite native budget"
        bridge._lines.put(json.dumps({"type": "result", "request_id": fields[1], "ok": True,
                                      "metric": "QTM", "status": "timeout", "elapsed_seconds": 0.125,
                                      "workers": [{"busy_seconds": 0.2}]}))

    monkeypatch.setattr(bridge, "_send_locked", send)
    payload = bridge.solve(CubieCube(), 2, None, 1, None, None, None, metric="QTM")
    with pytest.raises(native.NativeSolverTimeout):
        native._validated_result(CubieCube(), payload, "QTM")
    assert bridge.diagnostics()["native_search_seconds"] == 0.125
    assert bridge.diagnostics()["native_proof_busy_seconds"] == 0.2


def test_resource_release_follows_complete_native_cleanup(backend, monkeypatch):
    cleanup_started = threading.Event()
    cleanup_allowed = threading.Event()

    def cleanup():
        cleanup_started.set()
        assert cleanup_allowed.wait(2)

    monkeypatch.setattr(native, "solve_native", lambda *args, **kwargs: exact_result())
    monkeypatch.setattr(native, "release_assets", cleanup)
    try:
        result = backend.submit(to_facelets(CubieCube()), 3, 2, None)
        assert cleanup_started.is_set()
        assert qtm.BROKER.snapshot()["qtm_active"]
        assert not qtm.BROKER.acquire_qtm(threading.Event(), lambda: None, time.monotonic() + 0.02)
    finally:
        cleanup_allowed.set()
    assert backend._jobs[result["job_id"]]["_done"].wait(1)
    assert not qtm.BROKER.snapshot()["qtm_active"]
