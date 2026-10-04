"""One leased candidate worker, using HTM-only native tables and move costs."""
from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import threading
import time
import uuid

from ...cubie import MOVE_INDEX, to_facelets
from .native import NATIVE_EXE, ROOT
from .optimal import SearchCancelled, SearchTimeout, SolveResult


class NativeHtmCandidate:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.lines = None
        self.last_result = None

    def close(self):
        with self.lock:
            self._stop()

    def _stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    @staticmethod
    def _check(deadline, cancel):
        if cancel is not None and cancel.is_set():
            raise SearchCancelled("HTM 原生候选搜索已取消。")
        if deadline is not None and time.monotonic() >= deadline:
            raise SearchTimeout("HTM 原生候选搜索超时。")

    def _start(self, deadline, cancel):
        environment = os.environ.copy()
        environment["CUBE_NATIVE_COORDINATE_CACHE"] = str(ROOT / ".cache/htm/coordinates_htm_v1.bin")
        process = subprocess.Popen([str(NATIVE_EXE), "candidate-serve"], cwd=ROOT, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.process = process
        lines = self.lines = queue.Queue()

        def reader():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=reader, daemon=True, name="htm-native-candidate-output").start()
        try:
            while True:
                self._check(deadline, cancel)
                try:
                    line = lines.get(timeout=0.01)
                except queue.Empty:
                    continue
                ready = json.loads(line) if line is not None else {}
                if ready.get("type") != "ready" or ready.get("metric") != "HTM" or not ready.get("ok"):
                    raise RuntimeError("HTM native candidate service did not become ready")
                return
        except BaseException:
            self._stop()
            raise

    def solve(self, cube, *, timeout_seconds, candidate_callback, cancel_event, deadline,
              directions=1, max_phase1_depth=12, max_phase2_depth=14):
        started = time.monotonic()
        budget = 1.5 if timeout_seconds is None else timeout_seconds
        deadline = min(deadline, started + budget) if deadline is not None else started + budget
        self._check(deadline, cancel_event)
        while not self.lock.acquire(timeout=0.01):
            self._check(deadline, cancel_event)
        try:
            self._check(deadline, cancel_event)
            if self.process is None or self.process.poll() is not None:
                self._stop()
                self._start(deadline, cancel_event)
            process = self.process
            request_id = uuid.uuid4().hex
            remaining = max(0.000001, deadline - time.monotonic())
            process.stdin.write(f"candidate\t{request_id}\t{to_facelets(cube)}\t{remaining}\t{directions}\t"
                                f"{max_phase1_depth}\t{max_phase2_depth}\n")
            process.stdin.flush()
            best = None
            stop_sent = None
            cancelled = False
            while True:
                if stop_sent is None and ((cancel_event is not None and cancel_event.is_set()) or
                                           time.monotonic() >= deadline):
                    cancelled = cancel_event is not None and cancel_event.is_set()
                    process.stdin.write(f"cancel\t{request_id}\n")
                    process.stdin.flush()
                    stop_sent = time.monotonic()
                if stop_sent is not None and time.monotonic() - stop_sent > 2:
                    self._stop()
                    raise SearchTimeout("HTM 原生候选服务未及时退出。")
                try:
                    line = self.lines.get(timeout=0.01)
                except queue.Empty:
                    continue
                if line is None:
                    self._stop()
                    raise RuntimeError("HTM native candidate service exited unexpectedly")
                event = json.loads(line)
                if event.get("request_id") != request_id:
                    continue
                if not event.get("ok"):
                    raise RuntimeError(event.get("error", "HTM candidate failed"))
                if event.get("type") == "candidate" and stop_sent is None:
                    moves = event["moves"]
                    verified = cube
                    for name in moves:
                        verified = verified.apply_move_index(MOVE_INDEX[name])
                    if event.get("metric") != "HTM" or event["depth"] != len(moves) or not verified.is_solved():
                        raise RuntimeError("HTM native candidate failed replay or metric validation")
                    result = SolveResult(moves, len(moves), "HTM", time.monotonic() - started, False)
                    if best is None or result.depth < best.depth:
                        best = result
                        if candidate_callback is not None:
                            candidate_callback(result)
                if event.get("type") == "result":
                    self.last_result = event
                    if cancelled or (cancel_event is not None and cancel_event.is_set()):
                        raise SearchCancelled("HTM 原生候选搜索已取消。")
                    if best is not None:
                        return best
                    raise SearchTimeout("HTM 原生候选搜索未在预算内找到解。")
        except BaseException:
            # Callback failures must not leave an unowned search running.
            if self.process is not None and self.process.poll() is None:
                self._stop()
            raise
        finally:
            self.lock.release()


NATIVE_CANDIDATE = NativeHtmCandidate()
atexit.register(NATIVE_CANDIDATE.close)
