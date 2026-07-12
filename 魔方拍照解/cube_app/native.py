from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from .cubie import CubieCube, MOVE_INDEX, to_facelets


ROOT = Path(__file__).resolve().parents[1]
NATIVE_ROOT = ROOT / "native"
NATIVE_EXE = NATIVE_ROOT / "build" / "cube_solver.exe"
NATIVE_CACHE = ROOT / ".cache" / "native"
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


class _PersistentNativeSolver:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stderr_lines: list[str] = []

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
                "--edge-pdb-a", "--edge-pdb-b", "--edge-pdb-c", "--edge-pdb-d",
                "--edge-pdb-e", "--edge-pdb-f", "--edge-pdb-g", "--edge-pdb-h",
            ),
            (EDGE_PDB_A, EDGE_PDB_B, EDGE_PDB_C, EDGE_PDB_D, EDGE_PDB_E, EDGE_PDB_F, EDGE_PDB_G, EDGE_PDB_H),
        ):
            if use_edge_pdbs and path.is_file():
                command.extend((flag, str(path.relative_to(ROOT))))
        return command

    def _start_locked(self) -> None:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
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
        )
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
        try:
            ready_line = lines.get(timeout=30)
        except queue.Empty as exc:
            self._stop_locked()
            raise NativeSolverError("native solver service did not become ready") from exc
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

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
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

    def solve(
        self,
        cube: CubieCube,
        max_depth: int,
        timeout_seconds: float,
        worker_count: int,
        incumbent_moves: list[str] | None,
        cancel_event: threading.Event | None,
        progress_callback: Callable[[dict], None] | None,
    ) -> dict:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._stop_locked()
                self._start_locked()
            assert self._process is not None and self._process.stdin is not None and self._lines is not None
            incumbent = " ".join(incumbent_moves or [])
            request = f"{to_facelets(cube)}\t{max_depth}\t{timeout_seconds}\t{worker_count}\t{incumbent}\n"
            try:
                self._process.stdin.write(request)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._stop_locked()
                raise NativeSolverError("native solver service stopped unexpectedly") from exc

            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._stop_locked()
                    raise NativeSolverCancelled("native solver search was cancelled")
                try:
                    line = self._lines.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    message = self._stderr_lines[-1] if self._stderr_lines else "native solver service stopped unexpectedly"
                    self._stop_locked()
                    raise NativeSolverError(message)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._stop_locked()
                    raise NativeSolverError("native solver service returned invalid JSON") from exc
                if event.get("type") == "progress":
                    if progress_callback is not None:
                        progress_callback(event)
                    continue
                if event.get("type") == "error" or not event.get("ok"):
                    raise NativeSolverError(str(event.get("error", "native solver failed")))
                if event.get("type") == "result":
                    return event

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
        "engine": "native-cpp",
    }


def solve_native(
    cube: CubieCube,
    *,
    max_depth: int,
    timeout_seconds: float,
    incumbent_moves: list[str] | None,
    cancel_event: threading.Event | None,
    threads: int | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict | None:
    if not native_solver_available():
        return None

    worker_count = threads or min(32, max(1, os.cpu_count() or 1))
    payload = _PERSISTENT_SOLVER.solve(
        cube,
        max_depth,
        timeout_seconds,
        worker_count,
        incumbent_moves,
        cancel_event,
        progress_callback,
    )
    return _validated_result(cube, payload)
