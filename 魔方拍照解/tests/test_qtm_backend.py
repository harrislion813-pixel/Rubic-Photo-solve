from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import server
from cube_app.cubie import CubieCube, MOVE_INDEX, to_facelets
from cube_app.solvers.qtm import backend as qtm
from cube_app.solvers.qtm import native
from cube_app.solvers.qtm.two_by_two import TwoByTwoSolver
from cube_app.solvers.resource_broker import ResourceBroker

STATE = to_facelets(CubieCube().apply_move_index(MOVE_INDEX["R2"]))


@pytest.fixture
def held_backend(monkeypatch):
    instance = qtm.QtmBackend(max_jobs=2)
    release = threading.Event()
    calls = []
    monkeypatch.setattr(instance, "available", lambda: True)

    def run(job_id, cube, max_depth):
        job = instance._jobs[job_id]
        calls.append(job_id)
        job["_response_ready"].set()
        assert release.wait(3)
        instance._update(job_id, status="cancelled" if job["_cancel"].is_set() else "complete")
        job["_done"].set()

    monkeypatch.setattr(instance, "_run", run)
    yield instance, calls, release
    release.set()
    for job in list(instance._jobs.values()):
        assert job["_done"].wait(2)


def test_equivalent_concurrent_retries_share_original_deadline(held_backend):
    instance, calls, release = held_backend
    started = time.monotonic() - 2
    first = instance.submit(STATE, 3, 26, 30, started=started)
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(lambda _: instance.submit(STATE, 3, 26, 30), range(8)))
    assert {item["job_id"] for item in responses} == {first["job_id"]}
    assert calls == [first["job_id"]]
    assert instance._jobs[first["job_id"]]["_deadline"] == started + 30
    assert all(item["request_elapsed_seconds"] >= 2 for item in responses)
    assert instance.snapshot(first["job_id"])["request_elapsed_seconds"] >= 2
    assert instance.submit(STATE.lower(), 3, 26, 30)["job_id"] == first["job_id"]


def test_different_timeout_and_cancelled_cleanup_still_use_capacity(held_backend):
    instance, calls, release = held_backend
    first = instance.submit(STATE, 3, 26, 30)
    second = instance.submit(STATE, 3, 26, None)
    assert first["job_id"] != second["job_id"]
    assert instance._jobs[second["job_id"]]["_deadline"] is None
    instance.cancel(first["job_id"])
    with pytest.raises(qtm.QtmJobCapacityError):
        instance.submit(STATE, 3, 26, 5)
    release.set()
    for job in instance._jobs.values():
        assert job["_done"].wait(1)
    third = instance.submit(STATE, 3, 26, 5)
    assert len(instance._jobs) == 2 and third["job_id"] not in {first["job_id"], second["job_id"]}


def test_expired_terminal_job_is_removed_after_cleanup(held_backend):
    instance, calls, release = held_backend
    response = instance.submit(STATE, 3, 26, 30)
    release.set()
    job = instance._jobs[response["job_id"]]
    assert job["_done"].wait(1)
    job["_updated"] = time.monotonic() - qtm.TERMINAL_TTL_SECONDS - 1
    assert instance.snapshot(response["job_id"]) is None


def test_lower_bound_uses_completed_cost_and_snapshots_are_detached(held_backend):
    instance, calls, release = held_backend
    response = instance.submit(STATE, 3, 26, 30)
    job_id = response["job_id"]
    instance._update(job_id, progress={"current_depth": 20, "completed_depth": 17},
                     candidate_result={"cost": 24, "moves": ["R2"], "optimal": False})
    snapshot = instance.snapshot(job_id)
    assert snapshot["proven_lower_bound"] == 18 and snapshot["proof_gap"] == 6
    snapshot["progress"]["completed_depth"] = 21
    assert instance.snapshot(job_id)["proven_lower_bound"] == 18
    instance._update(job_id, optimal=True, result={"cost": 20})
    snapshot = instance.snapshot(job_id)
    assert snapshot["candidate_cost"] == 20 and snapshot["proof_gap"] == 0


def test_terminal_diagnostics_have_bounded_retention(monkeypatch):
    instance = qtm.QtmBackend()
    monkeypatch.setattr(instance, "available", lambda: True)
    monkeypatch.setattr(qtm, "BROKER", ResourceBroker(1))
    release = qtm.BROKER.release_qtm

    release_started = threading.Event()
    finish_release = threading.Event()

    def delayed_release():
        release_started.set()
        assert finish_release.wait(2)
        release()

    monkeypatch.setattr(qtm.BROKER, "release_qtm", delayed_release)
    monkeypatch.setattr(native, "release_assets", lambda: None)
    monkeypatch.setattr(native, "retain_assets", lambda: False)
    monkeypatch.setattr(native, "service_diagnostics", lambda: {
        "service_events": [{"event": {"type": "test"}}] * 1000,
        "memory_samples": [{"working_set": 100}] * 1000,
    })
    monkeypatch.setattr(native, "solve_native", lambda *args, **kwargs: {
        "moves": ["R2"], "solution": "R2", "depth": 2, "optimal": True, "metric": "QTM", "asset_profile": "base",
    })
    response = instance.submit(STATE, 3, 26, 1)
    try:
        assert release_started.wait(1)
        assert not instance._jobs[response["job_id"]]["_done"].is_set()
        assert qtm.BROKER.snapshot()["qtm_active"]
    finally:
        finish_release.set()
    assert instance._jobs[response["job_id"]]["_done"].wait(2)
    residency = instance.snapshot(response["job_id"])["residency"]
    assert len(residency["service_events"]) == len(residency["memory_samples"]) == qtm.MAX_DIAGNOSTIC_ITEMS
    assert not qtm.BROKER.snapshot()["qtm_active"]
    assert instance.snapshot(response["job_id"])["resource_hold_seconds"] >= 0
    snapshot = instance.snapshot(response["job_id"])
    assert snapshot["terminal_seconds"] == snapshot["strict_confirmed_seconds"]
    assert snapshot["request_elapsed_seconds"] - snapshot["terminal_seconds"] >= .025


def test_two_by_two_does_not_require_three_by_three_assets(monkeypatch):
    instance = qtm.QtmBackend()
    monkeypatch.setattr(instance, "available", lambda: False)
    monkeypatch.setattr(qtm, "BROKER", ResourceBroker(1))
    monkeypatch.setattr(TwoByTwoSolver, "solve_facelets", lambda *args, **kwargs: SimpleNamespace(
        moves=["R2"], text="R2", depth=2))
    result = instance.submit(STATE, 2, 14, 1)
    assert result["optimal"] and result["asset_profile"] == "exact-2x2"
    monkeypatch.setattr(server, "qtm_installed", lambda: False)
    capabilities = server.qtm_capabilities()
    assert capabilities["2"]["available"] and not capabilities["3"]["available"]
    assert capabilities["2"]["adopted_profile"] is None
