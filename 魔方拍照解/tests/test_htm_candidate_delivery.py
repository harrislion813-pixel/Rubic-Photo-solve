"""H1 notification, deadline, replay, and ownership tests without native search."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

import server
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.solvers.htm.fast import FastTwoPhaseSolver
from cube_app.solvers.htm.native import NativeSolverCancelled, _PersistentNativeSolver
from cube_app.solvers.htm.optimal import SearchCancelled, SearchTimeout, SolveResult
from cube_app.solvers.resource_broker import ResourceBroker


@pytest.fixture(autouse=True)
def experimental_delivery(monkeypatch):
    monkeypatch.setenv("CUBE_HTM_EARLY_CANDIDATE", "on")


def candidate(moves):
    return SolveResult(moves, len(moves), "HTM", 0.01, False)


@pytest.fixture
def jobs():
    with server.JOBS_LOCK:
        before = set(server.JOBS)
    yield
    with server.JOBS_LOCK:
        created = [(key, job) for key, job in server.JOBS.items() if key not in before]
        for _, job in created:
            job["_cancel_event"].set()
            job["_candidate_stop"].set()
    for _, job in created:
        for name in ("_worker", "_candidate_worker"):
            worker = job.get(name)
            if worker is not None and worker.ident is not None:
                worker.join(2)
    with server.JOBS_LOCK:
        for key, _ in created:
            server.JOBS.pop(key, None)


def test_default_delivery_waits_for_best_candidate(jobs, monkeypatch):
    monkeypatch.delenv("CUBE_HTM_EARLY_CANDIDATE", raising=False)
    cube = CubieCube().apply_move_index(MOVE_INDEX["R"])
    job_id, _ = server.prepare_optimal_job(cube, None, 20, 3)
    job = server.JOBS[job_id]
    assert job["early_candidate_delivery"] is False
    job["_proof_lease"].set()
    found, finish = threading.Event(), threading.Event()

    def quick(*args, candidate_callback, **kwargs):
        candidate_callback(candidate(["R'", "U", "U'"]))
        found.set()
        assert finish.wait(1)
        best = candidate(["R'"])
        candidate_callback(best)
        return best

    monkeypatch.setattr(server, "generate_quick_solution", quick)
    assert server.start_candidate_job(job_id, cube)
    try:
        assert found.wait(1)
        assert job.get("candidate_result") is None
        assert job["_incumbent_moves"] is None
        assert not job["_delivery_ready"].is_set()
    finally:
        finish.set()
        job["_candidate_worker"].join(2)
    assert job["_generation_done"].is_set()
    assert job["candidate_result"]["depth"] == 1
    assert [event["cost"] for event in job["timing_events"] if event["event"] == "candidate_generated"] == [3, 1]
    assert [event["cost"] for event in job["timing_events"] if event["event"] == "candidate_published"] == [1]


def test_fast_notifies_first_and_improved_before_return():
    class SyntheticFast(FastTwoPhaseSolver):
        @staticmethod
        def _phase1_heuristic(*args):
            return 0

        def _search_phase1(self, *args):
            return [MOVE_INDEX[name] for name in ("R'", "U", "U'")]

        def _improve_phase1(self, *args):
            holder, notify = args[-4], args[-1]
            assert seen == [3]
            holder[0] = [MOVE_INDEX["R'"]]
            notify(holder[0])
            assert seen == [3, 1]
            raise SearchTimeout("bounded improvement ends")

    seen = []
    solver = SyntheticFast(tables=SimpleNamespace(), max_phase1_depth=0)
    result = solver.solve_cube(CubieCube().apply_move_index(MOVE_INDEX["R"]),
                               candidate_callback=lambda result: seen.append(result.depth))
    assert seen == [3, 1]
    assert result.depth == 1


def test_fast_cancel_precedes_table_loading():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(SearchCancelled):
        FastTwoPhaseSolver().solve_cube(CubieCube(), cancel_event=cancel)


def test_candidate_replay_monotonic_terminal_deadline_and_identity(jobs):
    cube = CubieCube().apply_move_index(MOVE_INDEX["R"])
    job_id, _ = server.prepare_optimal_job(cube, None, 20, 10)
    job = server.JOBS[job_id]
    with pytest.raises(ValueError, match="回放"):
        server.publish_htm_candidate(job_id, job, cube, candidate(["U"]))
    assert server.publish_htm_candidate(job_id, job, cube, candidate(["R'", "U", "U'"]))
    assert server.publish_htm_candidate(job_id, job, cube, candidate(["R'"]))
    assert not server.publish_htm_candidate(job_id, job, cube, candidate(["R'", "U", "U'"]))
    assert job["incumbent_depth"] == 1
    assert [event["cost"] for event in job["timing_events"] if event["event"] == "candidate_published"] == [3, 1]
    assert not server.publish_htm_candidate(job_id, dict(job), cube, candidate(["R'"]))
    server.update_job(job_id, status="complete", result={"depth": 1})
    assert not server.publish_htm_candidate(job_id, job, cube, candidate(["R'"]))
    server.update_job(job_id, status="running", incumbent_depth=99)
    assert job["status"] == "complete" and job["incumbent_depth"] == 1
    later_id, _ = server.prepare_optimal_job(cube, None, 20, 10)
    later = server.JOBS[later_id]
    later["_deadline"] = time.monotonic() - 1
    assert not server.publish_htm_candidate(later_id, later, cube, candidate(["R'"]))
    later["_deadline"] = None
    later["_cancel_event"].set()
    assert not server.publish_htm_candidate(later_id, later, cube, candidate(["R'"]))


@pytest.mark.parametrize("threads", [1, 2, 3])
def test_http_returns_first_candidate_while_improvement_continues(jobs, monkeypatch, threads):
    broker = ResourceBroker(threads)
    monkeypatch.setattr(server, "BROKER", broker)
    monkeypatch.setattr(server, "QUICK_OPTIMAL_PROBE_SECONDS", 0.005)
    monkeypatch.setattr(server, "native_solver_available", lambda: True)
    monkeypatch.setattr(server.AppHandler, "log_message", lambda *args: None)
    improve = threading.Event()
    generated = threading.Event()
    improved = threading.Event()
    proof_started = threading.Event()
    proof_calls = []

    def fast(cube, *, timeout_seconds, candidate_callback, cancel_event, deadline):
        assert 0 < timeout_seconds <= server.QUICK_SOLVE_SECONDS
        assert deadline > time.monotonic()
        candidate_callback(candidate(["R'", "U", "U'"]))
        generated.set()
        while not improve.wait(0.01):
            if cancel_event.is_set():
                raise SearchCancelled("candidate stopped")
        result = candidate(["R'"])
        candidate_callback(result)
        improved.set()
        return result

    def native(cube, **kwargs):
        proof_calls.append(kwargs)
        proof_started.set()
        while not kwargs["cancel_event"].wait(0.01):
            pass
        raise NativeSolverCancelled("cancelled")

    monkeypatch.setattr(server.FAST_SOLVER, "solve_cube", fast)
    monkeypatch.setattr(server, "solve_native", native)
    http = server.ExclusiveThreadingHTTPServer((server.HOST, 0), server.AppHandler)
    listener = threading.Thread(target=lambda: http.serve_forever(poll_interval=0.01), daemon=True)
    listener.start()
    try:
        payload = {"facelets": to_facelets(CubieCube().apply_move_index(MOVE_INDEX["R"])),
                   "timeout_seconds": 5}
        request = Request(f"http://{server.HOST}:{http.server_address[1]}/api/solve",
                          data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=2) as response:
            first = json.loads(response.read())
        assert generated.is_set() and not improved.is_set()
        assert first["depth"] == 3 and not first["optimal"]
        job = server.JOBS[first["job_id"]]
        assert job["_candidate_worker"].is_alive()
        assert first["proof_threads"] == max(1, threads - 1)
        assert proof_started.is_set() == (threads > 1)
        improve.set()
        assert improved.wait(1)
        assert proof_started.wait(1)
        assert proof_calls[0]["threads"] == max(1, threads - 1)
        assert proof_calls[0]["deadline"] == job["_deadline"]
        assert proof_calls[0]["incumbent_provider"]() == ["R'"]
        assert job["_generation_done"].wait(1)
        assert proof_calls[0]["threads_provider"]() == threads
        job["_cancel_event"].set()
        assert job["_done"].wait(1)
        assert job["status"] == "cancelled"
        assert proof_calls[0]["threads_provider"]() is None
        sent_after_terminal = []
        assert not proof_calls[0]["threads_update_guard"](lambda: sent_after_terminal.append(True))
        assert sent_after_terminal == []
        assert job["incumbent_depth"] == 1
        events = [event["event"] for event in job["timing_events"]]
        assert events.index("candidate_published") < events.index("http_initial_return")
        assert "terminal" in events
    finally:
        improve.set()
        http.shutdown()
        http.server_close()
        listener.join(1)


def test_native_refreshes_initial_incumbent_and_records_pipe_send(monkeypatch):
    import queue

    bridge = _PersistentNativeSolver()
    bridge._process = SimpleNamespace(poll=lambda: None, stdin=object())
    bridge._lines = queue.Queue()
    sent = []
    events = []

    def send(message):
        sent.append(message)
        if message.startswith("solve\t"):
            request_id = message.split("\t")[1]
            bridge._lines.put(json.dumps({"type": "result", "request_id": request_id, "ok": True}))

    monkeypatch.setattr(bridge, "_send_locked", send)
    bridge.solve(CubieCube(), 20, 1, 2, ["R", "R'"], None, None,
                 incumbent_provider=lambda: [], event_callback=events.append)
    assert sent[0].rstrip("\n").endswith("\t2\t")
    assert [event["type"] for event in events] == ["native_ready", "native_request_sent",
                                                 "native_incumbent_sent", "native_result_received",
                                                 "native_request_finished"]
    assert events[2]["cost"] == 0


@pytest.mark.parametrize("active", [True, False])
def test_native_dynamic_threads_restore_only_for_active_job(monkeypatch, active):
    import queue

    bridge = _PersistentNativeSolver()
    bridge._process = SimpleNamespace(poll=lambda: None, stdin=object())
    bridge._lines = queue.Queue()
    bridge._dynamic_threads = True
    sent = []
    events = []
    allowance = iter([2, 3 if active else None])
    request_id = None

    def send(message):
        nonlocal request_id
        sent.append(message)
        if message.startswith("solve\t"):
            request_id = message.split("\t")[1]
            bridge._lines.put(json.dumps({"type": "result", "request_id": request_id, "ok": True}))

    monkeypatch.setattr(bridge, "_send_locked", send)
    bridge.solve(CubieCube(), 20, 1, 2, None, None, None,
                 threads_provider=lambda: next(allowance), event_callback=events.append)
    if active:
        assert sent[1] == f"threads\t{request_id}\t3\n"
        assert any(event["type"] == "native_threads_sent" and event["threads"] == 3 for event in events)
    else:
        assert len(sent) == 1
        assert not any(event["type"] == "native_threads_sent" for event in events)


def test_queued_candidate_waits_for_its_proof_lease(jobs, monkeypatch):
    monkeypatch.setattr(server, "BROKER", ResourceBroker(3))
    started = [threading.Event(), threading.Event()]
    observed = []
    first_cube = CubieCube().apply_move_index(MOVE_INDEX["R"])
    second_cube = CubieCube().apply_move_index(MOVE_INDEX["U"])

    def native(cube, **kwargs):
        index = int(cube == second_cube)
        started[index].set()
        while not kwargs["cancel_event"].wait(0.01):
            pass
        raise NativeSolverCancelled("cancelled")

    def fast(cube, **kwargs):
        observed.append(cube)
        result = candidate(["R'"] if cube == first_cube else ["U'"])
        kwargs["candidate_callback"](result)
        return result

    monkeypatch.setattr(server, "solve_native", native)
    monkeypatch.setattr(server.FAST_SOLVER, "solve_cube", fast)
    first_id, first_worker = server.prepare_optimal_job(first_cube, None, 20, 3, candidate_enabled=True)
    server.start_optimal_job(first_id, first_worker)
    assert started[0].wait(1)
    assert server.start_candidate_job(first_id, first_cube)
    assert server.JOBS[first_id]["_generation_done"].wait(1)
    second_id, second_worker = server.prepare_optimal_job(second_cube, None, 20, 3, candidate_enabled=True)
    server.start_optimal_job(second_id, second_worker)
    assert server.start_candidate_job(second_id, second_cube)
    assert not server.JOBS[second_id]["_proof_lease"].wait(0.08)
    assert observed == [first_cube]
    assert not server.JOBS[second_id]["_generation_done"].is_set()
    server.JOBS[first_id]["_cancel_event"].set()
    assert server.JOBS[first_id]["_done"].wait(1)
    assert started[1].wait(1)
    assert server.JOBS[second_id]["_generation_done"].wait(1)
    assert observed == [first_cube, second_cube]
    assert not server.publish_htm_candidate(first_id, server.JOBS[first_id], first_cube, candidate(["R'"]))
    server.JOBS[second_id]["_cancel_event"].set()
    assert server.JOBS[second_id]["_done"].wait(1)


@pytest.mark.parametrize("cache_state", ["missing", "corrupt"])
@pytest.mark.parametrize("stop_reason", ["deadline", "cancel"])
def test_fast_cold_tables_preserve_original_deadline_and_release_build_lock(
        tmp_path, monkeypatch, cache_state, stop_reason):
    import cube_app.solvers.htm.tables as tables

    cache = tmp_path / f"solver_tables_v{tables.CACHE_VERSION}.pkl"
    if cache_state == "corrupt":
        cache.write_bytes(b"corrupt cache")
    cancel = threading.Event()
    original_deadline = time.monotonic() + 0.02

    def blocked_build(*, cancel_check):
        if stop_reason == "cancel":
            cancel.set()
        while True:
            cancel_check()
            cancel.wait(0.002)

    monkeypatch.setattr(tables, "build_tables", blocked_build)
    solver = FastTwoPhaseSolver(tmp_path)
    cube = CubieCube().apply_move_index(MOVE_INDEX["R"])
    with pytest.raises(SearchTimeout if stop_reason == "deadline" else SearchCancelled):
        # A long local budget must not reset the original request deadline.
        solver.solve_cube(cube, timeout_seconds=5, deadline=original_deadline, cancel_event=cancel)
    assert tables._TABLE_BUILD_LOCK.acquire(blocking=False)
    tables._TABLE_BUILD_LOCK.release()
    assert list(tmp_path.iterdir()) == ([cache] if cache_state == "corrupt" else [])
    if cache_state == "corrupt":
        assert cache.read_bytes() == b"corrupt cache"
    assert solver._tables is None


def test_cache_deadline_exception_is_not_swallowed_as_corruption(tmp_path):
    import pickle
    import cube_app.solvers.htm.tables as tables

    cache = tmp_path / "tables.pkl"
    cache.write_bytes(pickle.dumps({"version": tables.CACHE_VERSION}))
    checks = 0

    def expire_after_read():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise SearchTimeout("expired during cache loading")

    with pytest.raises(SearchTimeout, match="cache loading"):
        tables._load_cached_tables(cache, cancel_check=expire_after_read)


def test_table_build_lock_wait_preserves_cancellation(tmp_path, monkeypatch):
    import cube_app.solvers.htm.tables as tables

    cancel = threading.Event()
    errors = []
    checks = threading.Event()

    def check():
        checks.set()
        if cancel.is_set():
            raise SearchCancelled("cancel while queued")

    def load():
        try:
            tables.load_or_build_tables(tmp_path, cancel_check=check)
        except SearchCancelled as exc:
            errors.append(exc)

    monkeypatch.setattr(tables, "build_tables", lambda **kwargs: pytest.fail("queued build ran"))
    with tables._TABLE_BUILD_LOCK:
        worker = threading.Thread(target=load)
        worker.start()
        assert checks.wait(1)
        cancel.set()
        worker.join(1)
        assert not worker.is_alive()
        assert len(errors) == 1
    assert not list(tmp_path.iterdir())


def test_table_builder_checks_cancel_before_move_work():
    from cube_app.solvers.htm.tables import build_move_table

    def cancel():
        raise SearchCancelled("cancel table initialization")

    with pytest.raises(SearchCancelled):
        build_move_table(100, lambda index: pytest.fail("work ran after cancellation"),
                         lambda cube: 0, range(18), cancel_check=cancel)


def test_native_ready_result_and_finish_record_process_memory(monkeypatch):
    import queue
    import cube_app.solvers.htm.native as native

    bridge = _PersistentNativeSolver()
    bridge._process = SimpleNamespace(poll=lambda: None, stdin=object(), pid=42)
    bridge._lines = queue.Queue()
    events = []
    peaks = iter([100, 200, 300])

    def stats(process):
        assert process.pid == 42
        return {"native_pid": process.pid, "peak_working_set_bytes": next(peaks),
                "memory_scope": "native_process_lifetime_peak"}

    def send(message):
        request_id = message.split("\t")[1]
        bridge._lines.put(json.dumps({"type": "result", "request_id": request_id, "ok": True}))

    monkeypatch.setattr(native, "_native_process_stats", stats)
    monkeypatch.setattr(bridge, "_send_locked", send)
    bridge.solve(CubieCube(), 0, 1, 1, None, None, None, event_callback=events.append)
    samples = [event for event in events if "memory_scope" in event]
    assert [event["type"] for event in samples] == ["native_ready", "native_result_received",
                                                   "native_request_finished"]
    assert [event["peak_working_set_bytes"] for event in samples] == [100, 200, 300]
    assert all(event["native_pid"] == 42 for event in samples)


def test_native_memory_events_reach_http_terminal_snapshot(jobs, monkeypatch):
    def native(cube, **kwargs):
        callback = kwargs["event_callback"]
        for kind, peak in (("native_ready", 100), ("native_result_received", 200),
                           ("native_request_finished", 150)):
            callback({"type": kind, "native_pid": 42, "peak_working_set_bytes": peak,
                      "memory_scope": "native_process_lifetime_peak"})
        return {**server.result_payload(candidate([])), "optimal": True}

    monkeypatch.setattr(server, "solve_native", native)
    job_id, worker = server.prepare_optimal_job(CubieCube(), None, 0, 1)
    server.start_optimal_job(job_id, worker)
    assert server.JOBS[job_id]["_done"].wait(1)
    snapshot = server.job_snapshot(job_id)
    assert snapshot["status"] == "complete"
    assert snapshot["native_pid"] == 42
    assert snapshot["peak_working_set_bytes"] == 200
    terminal = next(event for event in snapshot["timing_events"] if event["event"] == "terminal")
    assert terminal["peak_working_set_bytes"] == 200
    assert terminal["memory_scope"] == "native_process_lifetime_peak"
