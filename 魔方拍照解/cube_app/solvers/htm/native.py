from __future__ import annotations

import atexit
import ctypes
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from ...cubie import CubieCube, MOVE_INDEX, to_facelets
from ...runtime import application_root


ROOT = application_root()
NATIVE_ROOT = ROOT / "native" / "htm"
NATIVE_EXE = NATIVE_ROOT / "build" / "cube_solver_htm.exe"
NATIVE_CACHE = ROOT / "assets" / "htm" / "v1"
CORNER_PDB = NATIVE_CACHE / "corner_htm_v2.pdb"
PHASE1_PDB = NATIVE_CACHE / "phase1_sym_htm_v2.pdb"
EDGE_PDB_A = NATIVE_CACHE / "edge_a_htm_v2.pdb"
EDGE_PDB_B = NATIVE_CACHE / "edge_b_htm_v2.pdb"
EDGE_PDB_C = NATIVE_CACHE / "edge_c_htm_v2.pdb"
EDGE_PDB_D = NATIVE_CACHE / "edge_d_htm_v2.pdb"
EDGE_PDB_E = NATIVE_CACHE / "edge_e_htm_v2.pdb"
EDGE_PDB_F = NATIVE_CACHE / "edge_f_htm_v2.pdb"
EDGE_PDB_G = NATIVE_CACHE / "edge_g_htm_v2.pdb"
EDGE_PDB_H = NATIVE_CACHE / "edge_h_htm_v2.pdb"
TAIL_PDB_V4 = NATIVE_CACHE / "tail_depth6_v4.pdb"
TAIL_PDB_V3 = NATIVE_CACHE / "tail_depth6_v3.pdb"
TAIL_PDB_V2 = NATIVE_CACHE / "tail_depth6_v2.pdb"
TAIL_PDB = next((path for path in (TAIL_PDB_V4, TAIL_PDB_V3, TAIL_PDB_V2) if path.is_file()), TAIL_PDB_V2)


class NativeSolverError(RuntimeError):
    pass


class NativeSolverCancelled(NativeSolverError):
    pass


class NativeSolverTimeout(NativeSolverError):
    pass


def _native_process_stats(process) -> dict:
    """Windows lifetime peak for this native process, not an application sum."""
    peak = None
    handle = getattr(process, "_handle", None)
    if os.name == "nt" and handle is not None:
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if get_memory(int(handle), ctypes.byref(counters), counters.cb):
            peak = int(counters.PeakWorkingSetSize)
    return {"native_pid": getattr(process, "pid", None), "peak_working_set_bytes": peak,
            "memory_scope": "native_process_lifetime_peak"}


class _PersistentNativeSolver:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._dynamic_threads = False
        self._process_event_callback: Callable[[dict], None] | None = None

    @staticmethod
    def _command() -> list[str]:
        command = [
            str(NATIVE_EXE),
            "serve",
            "--pdb",
            str(CORNER_PDB.relative_to(ROOT)),
        ]
        if PHASE1_PDB.is_file():
            command.extend(("--phase1-pdb", str(PHASE1_PDB.relative_to(ROOT))))
        if TAIL_PDB.is_file():
            command.extend(("--tail-pdb", str(TAIL_PDB.relative_to(ROOT))))
        use_edge_pdbs = os.environ.get("CUBE_NATIVE_EDGE_PDBS", "").strip().lower() in {"1", "true", "yes"}
        for flag, path in zip(
            (
                "--edge-pdb-a",
                "--edge-pdb-b",
                "--edge-pdb-c",
                "--edge-pdb-d",
                "--edge-pdb-e",
                "--edge-pdb-f",
                "--edge-pdb-g",
                "--edge-pdb-h",
            ),
            (EDGE_PDB_A, EDGE_PDB_B, EDGE_PDB_C, EDGE_PDB_D, EDGE_PDB_E, EDGE_PDB_F, EDGE_PDB_G, EDGE_PDB_H),
        ):
            if use_edge_pdbs and path.is_file():
                command.extend((flag, str(path.relative_to(ROOT))))
        return command

    def _start_locked(self, deadline: float | None, cancel_event: threading.Event | None) -> None:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            environment = os.environ.copy()
            cache = ROOT / ".cache" / "htm" / "coordinates_htm_v1.bin"
            cache.parent.mkdir(parents=True, exist_ok=True)
            environment["CUBE_NATIVE_COORDINATE_CACHE"] = str(cache)
            process = subprocess.Popen(
                self._command(),
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=creation_flags,
                env=environment,
            )
        except OSError as exc:
            raise NativeSolverError(f"native solver service could not start: {exc}") from exc
        lines: queue.Queue[str | None] = queue.Queue()
        self._process = process
        self._lines = lines
        self._stderr_lines = []

        def read_stdout() -> None:
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    lines.put(line.strip())
            finally:
                lines.put(None)

        def read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                stripped = line.strip()
                if stripped:
                    self._stderr_lines.append(stripped)

        self._reader = threading.Thread(target=read_stdout, name="cube-native-service-stdout", daemon=True)
        self._stderr_reader = threading.Thread(target=read_stderr, name="cube-native-service-stderr", daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        startup_deadline = min(time.monotonic() + 30, deadline) if deadline is not None else time.monotonic() + 30
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self._stop_locked()
                raise NativeSolverCancelled("native solver startup was cancelled")
            if time.monotonic() >= startup_deadline:
                self._stop_locked()
                if deadline is not None and time.monotonic() >= deadline:
                    raise NativeSolverTimeout("native solver initialization exceeded the deadline")
                raise NativeSolverError("native solver service did not become ready")
            try:
                ready_line = lines.get(timeout=0.05)
                break
            except queue.Empty:
                continue
        if ready_line is None:
            message = self._stderr_lines[-1] if self._stderr_lines else "native solver service failed to start"
            self._stop_locked()
            raise NativeSolverError(message)
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as exc:
            self._stop_locked()
            raise NativeSolverError("native solver service returned invalid startup data") from exc
        if ready.get("type") != "ready" or not ready.get("ok"):
            self._stop_locked()
            raise NativeSolverError(str(ready.get("error", "native solver service failed to start")))
        if ready.get("protocol_version", 0) < 2:
            self._stop_locked()
            raise NativeSolverError("native service protocol is outdated; rebuild native/build.ps1")
        self._dynamic_threads = bool(ready.get("dynamic_threads"))

    def _stop_locked(self) -> None:
        process = self._process
        if process is not None and self._process_event_callback is not None:
            self._process_event_callback({"type": "native_process_stopping", **_native_process_stats(process)})
        self._process = None
        self._dynamic_threads = False
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
        if self._reader is not None:
            self._reader.join(timeout=2)
        if self._stderr_reader is not None:
            self._stderr_reader.join(timeout=2)
        self._lines = None

    def _send_locked(self, message: str) -> None:
        assert self._process is not None and self._process.stdin is not None
        try:
            self._process.stdin.write(message)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._stop_locked()
            raise NativeSolverError("native solver service stopped unexpectedly") from exc

    def solve(
        self,
        cube: CubieCube,
        max_depth: int,
        timeout_seconds: float | None,
        worker_count: int,
        incumbent_moves: list[str] | None,
        cancel_event: threading.Event | None,
        progress_callback: Callable[[dict], None] | None,
        deadline: float | None = None,
        incumbent_provider: Callable[[], list[str] | None] | None = None,
        event_callback: Callable[[dict], None] | None = None,
        threads_provider: Callable[[], int | None] | None = None,
        threads_update_guard: Callable[[Callable[[], None]], bool] | None = None,
    ) -> dict:
        if deadline is None and timeout_seconds is not None:
            deadline = time.monotonic() + timeout_seconds
        while not self._lock.acquire(timeout=0.05):
            if cancel_event is not None and cancel_event.is_set():
                raise NativeSolverCancelled("native solver search was cancelled while queued")
            if deadline is not None and time.monotonic() >= deadline:
                raise NativeSolverTimeout("native solver deadline expired while queued")
        try:
            self._process_event_callback = event_callback
            if cancel_event is not None and cancel_event.is_set():
                raise NativeSolverCancelled("native solver search was cancelled")
            if deadline is not None and time.monotonic() >= deadline:
                raise NativeSolverTimeout("native solver deadline expired")
            reused = self._process is not None and self._process.poll() is None
            if not reused:
                self._stop_locked()
                if event_callback is not None:
                    event_callback({"type": "native_startup_started"})
                self._start_locked(deadline, cancel_event)
            if event_callback is not None:
                event_callback({"type": "native_ready", "reused": reused,
                                "dynamic_threads": self._dynamic_threads, **_native_process_stats(self._process)})
            assert self._process is not None and self._process.stdin is not None and self._lines is not None
            if incumbent_provider is not None:
                current = incumbent_provider()
                if current is not None and (incumbent_moves is None or len(current) < len(incumbent_moves)):
                    incumbent_moves = current
            incumbent = " ".join(incumbent_moves or [])
            if threads_provider is not None and self._dynamic_threads:
                requested = threads_provider()
                if requested is not None:
                    worker_count = max(1, min(64, int(requested)))
            request_id = uuid.uuid4().hex
            remaining = 0 if deadline is None else max(0.000001, deadline - time.monotonic())
            request = (
                f"solve\t{request_id}\t{to_facelets(cube)}\t{max_depth}\t{remaining}\t{worker_count}\t{incumbent}\n"
            )
            self._send_locked(request)
            if event_callback is not None:
                event_callback({"type": "native_request_sent", "threads": worker_count})
                if incumbent_moves is not None:
                    event_callback({"type": "native_incumbent_sent", "cost": len(incumbent_moves),
                                    "moves": list(incumbent_moves), "via": "solve"})

            stop_reason = None
            stop_sent_at = None
            while True:
                if stop_reason is None:
                    if cancel_event is not None and cancel_event.is_set():
                        stop_reason = NativeSolverCancelled("native solver search was cancelled")
                    elif deadline is not None and time.monotonic() >= deadline:
                        stop_reason = NativeSolverTimeout("native optimal proof timed out")
                    if stop_reason is not None:
                        self._send_locked(f"cancel\t{request_id}\n")
                        stop_sent_at = time.monotonic()
                if stop_sent_at is not None and time.monotonic() - stop_sent_at > 5:
                    self._stop_locked()
                    raise NativeSolverError("native service did not acknowledge cancellation")
                if stop_reason is None and incumbent_provider is not None:
                    candidate = incumbent_provider()
                    candidate_text = " ".join(candidate or [])
                    if candidate_text and (not incumbent or len(candidate) < len(incumbent.split())):
                        self._send_locked(f"incumbent\t{request_id}\t{candidate_text}\n")
                        incumbent = candidate_text
                        if event_callback is not None:
                            event_callback({"type": "native_incumbent_sent", "cost": len(candidate),
                                            "moves": list(candidate), "via": "incumbent"})
                if stop_reason is None and threads_provider is not None and self._dynamic_threads:
                    requested = threads_provider()
                    requested_threads = None if requested is None else max(1, min(64, int(requested)))
                    if (requested_threads is not None and requested_threads != worker_count
                            and (cancel_event is None or not cancel_event.is_set())
                            and (deadline is None or time.monotonic() < deadline)):
                        def send_threads() -> None:
                            self._send_locked(f"threads\t{request_id}\t{requested_threads}\n")

                        if threads_update_guard is None:
                            send_threads()
                            sent = True
                        else:
                            sent = threads_update_guard(send_threads)
                        if sent:
                            worker_count = requested_threads
                            if event_callback is not None:
                                event_callback({"type": "native_threads_sent", "threads": requested_threads})
                try:
                    line = self._lines.get(timeout=0.05)
                except queue.Empty:
                    continue
                if line is None:
                    message = (
                        self._stderr_lines[-1] if self._stderr_lines else "native solver service stopped unexpectedly"
                    )
                    self._stop_locked()
                    raise NativeSolverError(message)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._stop_locked()
                    raise NativeSolverError("native solver service returned invalid JSON") from exc
                if event.get("request_id") != request_id:
                    continue
                if event.get("type") == "progress":
                    if progress_callback is not None:
                        progress_callback({**event, "engine": "native-cpp"})
                    continue
                if event.get("type") == "error" or not event.get("ok"):
                    raise NativeSolverError(str(event.get("error", "native solver failed")))
                if event.get("type") == "result":
                    if event_callback is not None:
                        event_callback({"type": "native_result_received", "result": event,
                                        **_native_process_stats(self._process)})
                    if stop_reason is not None:
                        raise stop_reason
                    return event
        finally:
            if event_callback is not None:
                event_callback({"type": "native_request_finished", **_native_process_stats(self._process)})
            self._process_event_callback = None
            self._lock.release()

    def close(self) -> None:
        with self._lock:
            self._stop_locked()


_PERSISTENT_SOLVER = _PersistentNativeSolver()
atexit.register(_PERSISTENT_SOLVER.close)


def native_solver_available() -> bool:
    return NATIVE_EXE.is_file() and all(path.is_file() for path in (CORNER_PDB, PHASE1_PDB))


def _validated_result(cube: CubieCube, payload: dict) -> dict:
    if payload.get("status") == "timeout":
        raise NativeSolverTimeout("native optimal proof timed out")
    if payload.get("status") == "cancelled":
        raise NativeSolverCancelled("native solver search was cancelled")
    moves = [str(move) for move in payload.get("moves", [])]
    verified = cube
    try:
        for move in moves:
            verified = verified.apply_move_index(MOVE_INDEX[move])
    except KeyError as exc:
        raise NativeSolverError(f"native solver returned unknown move: {exc.args[0]}") from exc
    if not verified.is_solved():
        raise NativeSolverError("native solver returned an invalid solution")
    return {
        "moves": moves,
        "solution": " ".join(moves),
        "depth": len(moves),
        "metric": "HTM",
        "optimal": bool(payload.get("optimal")),
        "inverse_direction": bool(payload.get("inverse_direction")),
        "elapsed_seconds": round(float(payload.get("elapsed_seconds", 0.0)), 3),
        "nodes": int(payload.get("nodes", 0)),
        "split_nodes": int(payload.get("split_nodes", 0)),
        "tail_queries": int(payload.get("tail_queries", 0)),
        "tail_bloom_rejects": int(payload.get("tail_bloom_rejects", 0)),
        "tail_exact_queries": int(payload.get("tail_exact_queries", 0)),
        "tail_probes": int(payload.get("tail_probes", 0)),
        "tail_hits": int(payload.get("tail_hits", 0)),
        "completed_depth": int(payload.get("completed_depth", -1)),
        "generated_candidates": int(payload.get("generated_candidates", 0)),
        "phase1_queries": int(payload.get("phase1_queries", 0)),
        "corner_queries": int(payload.get("corner_queries", 0)),
        "engine": "native-cpp",
    }


def solve_native(
    cube: CubieCube,
    *,
    max_depth: int,
    timeout_seconds: float | None,
    incumbent_moves: list[str] | None,
    cancel_event: threading.Event | None,
    threads: int | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    deadline: float | None = None,
    incumbent_provider: Callable[[], list[str] | None] | None = None,
    event_callback: Callable[[dict], None] | None = None,
    threads_provider: Callable[[], int | None] | None = None,
    threads_update_guard: Callable[[Callable[[], None]], bool] | None = None,
) -> dict | None:
    if not native_solver_available():
        return None

    worker_count = threads or min(4, max(1, os.cpu_count() or 1))
    payload = _PERSISTENT_SOLVER.solve(
        cube,
        max_depth,
        timeout_seconds,
        worker_count,
        incumbent_moves,
        cancel_event,
        progress_callback,
        deadline,
        incumbent_provider,
        event_callback,
        threads_provider,
        threads_update_guard,
    )
    return _validated_result(cube, payload)
