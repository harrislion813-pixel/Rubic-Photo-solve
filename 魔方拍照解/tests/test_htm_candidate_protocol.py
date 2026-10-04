"""Cross-platform protocol and ownership contracts without a native executable."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time

import pytest

from cube_app.cubie import CubieCube, MOVE_INDEX
from cube_app.solvers.htm import native_fast
from cube_app.solvers.htm.optimal import SearchCancelled, SearchTimeout


class OutputPipe:
    def __init__(self):
        self.lines = queue.Queue()

    def __iter__(self):
        while True:
            value = self.lines.get()
            if value is None:
                return
            yield value

    def send(self, value):
        self.lines.put(value if isinstance(value, str) else json.dumps(value) + "\n")

    def close(self):
        self.lines.put(None)


class InputPipe:
    def __init__(self, owner):
        self.owner = owner
        self.pending = ""
        self.commands = []

    def write(self, value):
        self.pending += value

    def flush(self):
        for command in self.pending.splitlines():
            fields = command.split("\t")
            self.commands.append(fields)
            if fields[0] == "candidate":
                self.owner.respond(fields[1])
            elif fields[0] == "cancel":
                self.owner.stdout.send({"type": "result", "ok": True, "request_id": fields[1]})
        self.pending = ""

    def close(self):
        pass


class CandidateService:
    def __init__(self, frames=(), *, ready=None, ignore_terminate=False, quiet=False):
        self.stdout = OutputPipe()
        self.stdin = InputPipe(self)
        self.stderr = OutputPipe()
        self.frames = frames
        self.ignore_terminate = ignore_terminate
        self.quiet = quiet
        self.returncode = None
        self.terminated = 0
        self.killed = 0
        self.stdout.send(ready if ready is not None else {"type": "ready", "ok": True, "metric": "HTM"})

    def respond(self, request_id):
        # A stale request must never publish into the current owner's callback.
        self.stdout.send({"type": "candidate", "ok": True, "request_id": "stale", "moves": ["U"],
                          "metric": "QTM", "depth": 1})
        for frame in self.frames:
            self.stdout.send({**frame, "request_id": request_id} if isinstance(frame, dict) else frame)
        if not self.quiet:
            self.stdout.send({"type": "result", "ok": True, "request_id": request_id})

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        if not self.ignore_terminate:
            self.returncode = 0

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("candidate-service", timeout)
        return self.returncode

    def kill(self):
        self.killed += 1
        self.returncode = 0


def candidate(moves, *, metric="HTM", depth=None):
    return {"type": "candidate", "ok": True, "metric": metric,
            "moves": moves, "depth": len(moves) if depth is None else depth}


def solve(solver, **changes):
    options = dict(timeout_seconds=1.5, candidate_callback=None, cancel_event=None, deadline=None, directions=6)
    options.update(changes)
    return solver.solve(CubieCube().apply_move_index(MOVE_INDEX["R2"]), **options)


def install(monkeypatch, service):
    def start(command, **options):
        assert command[1] == "candidate-serve"
        assert options["encoding"] == "utf-8"
        assert options["env"]["CUBE_NATIVE_COORDINATE_CACHE"].endswith("coordinates_htm_v1.bin")
        return service

    monkeypatch.setattr(native_fast.subprocess, "Popen", start)
    return native_fast.NativeHtmCandidate()


def test_only_valid_strict_improvements_publish_and_service_reuses(monkeypatch):
    service = CandidateService([candidate(["R2", "U", "U'"]), candidate(["R2"]),
                                candidate(["R2"]), candidate(["R2", "U", "U'"])])
    solver = install(monkeypatch, service)
    received = []
    try:
        best = solve(solver, candidate_callback=received.append)
        assert best.moves == ["R2"] and best.depth == 1 and not best.optimal
        assert [item.depth for item in received] == [3, 1]
        assert solve(solver).moves == ["R2"] and solver.process is service
        commands = service.stdin.commands
        assert len(commands) == 2 and all(command[0] == "candidate" for command in commands)
        assert all(command[4:] == ["6", "12", "14"] and 0 < float(command[3]) <= 1.5 for command in commands)
    finally:
        solver.close()
    assert solver.process is None and service.terminated == 1


@pytest.mark.parametrize("frame", [candidate(["R2"], metric="QTM"), candidate(["R2"], depth=2),
                                   candidate(["U"]), {"type": "candidate", "ok": False, "error": "rejected"},
                                   "not-json\n"])
def test_invalid_or_error_responses_never_publish_and_release_owner(monkeypatch, frame):
    service = CandidateService([frame])
    solver = install(monkeypatch, service)
    received = []
    with pytest.raises((RuntimeError, json.JSONDecodeError)):
        solve(solver, candidate_callback=received.append)
    assert received == [] and solver.process is None and service.terminated == 1
    assert solver.lock.acquire(blocking=False)
    solver.lock.release()


def test_callback_failure_and_active_cancel_end_owned_search(monkeypatch):
    service = CandidateService([candidate(["R2"])])
    solver = install(monkeypatch, service)

    def failed_callback(result):
        raise ValueError("owner callback failed")

    with pytest.raises(ValueError, match="owner callback failed"):
        solve(solver, candidate_callback=failed_callback)
    assert solver.process is None and service.terminated == 1
    cancel_service = CandidateService([candidate(["R2"])])
    solver = install(monkeypatch, cancel_service)
    cancel = threading.Event()
    with pytest.raises(SearchCancelled):
        solve(solver, candidate_callback=lambda result: cancel.set(), cancel_event=cancel)
    assert any(command[0] == "cancel" for command in cancel_service.stdin.commands)
    assert solver.process is None and cancel_service.terminated == 1


def test_queue_wait_and_pre_cancel_cannot_extend_deadline_or_stop_another_owner():
    solver = native_fast.NativeHtmCandidate()
    service = solver.process = CandidateService()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(SearchCancelled):
        solve(solver, cancel_event=cancel)
    with pytest.raises(SearchTimeout):
        solve(solver, deadline=time.monotonic() - 1)
    solver.lock.acquire()
    try:
        with pytest.raises(SearchTimeout):
            solve(solver, timeout_seconds=.02)
        assert solver.process is service and service.terminated == 0 and solver.lock.locked()
    finally:
        solver.lock.release()
        solver.close()


def test_budget_cancellation_without_candidate_releases_service(monkeypatch):
    service = CandidateService(quiet=True)
    solver = install(monkeypatch, service)
    with pytest.raises(SearchTimeout):
        solve(solver, timeout_seconds=.1)
    assert any(command[0] == "cancel" for command in service.stdin.commands)
    assert solver.process is None and service.terminated == 1


def test_invalid_startup_kills_unresponsive_process(monkeypatch):
    service = CandidateService(ready={"type": "ready", "ok": True, "metric": "QTM"}, ignore_terminate=True)
    solver = install(monkeypatch, service)
    with pytest.raises(RuntimeError, match="did not become ready"):
        solve(solver)
    assert solver.process is None and service.terminated == 1 and service.killed == 1
