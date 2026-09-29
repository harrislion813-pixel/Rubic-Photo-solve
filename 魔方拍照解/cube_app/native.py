from __future__ import annotations

import atexit
import json
import os
import queue
import struct
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from .cubie import CubieCube, MOVE_INDEX, to_facelets
from .metrics import normalize_metric, resolve_max_depth, solution_cost
from .runtime import application_root


ROOT = application_root()
NATIVE_ROOT = ROOT / "native"
NATIVE_EXE = ROOT / os.environ["CUBE_NATIVE_EXE"] if os.environ.get("CUBE_NATIVE_EXE") else NATIVE_ROOT / "build" / "cube_solver.exe"
NATIVE_CACHE = ROOT / ".cache" / "native"
CORNER_PDB = NATIVE_CACHE / "corner_htm_v2.pdb"
PHASE1_PDB = NATIVE_CACHE / "phase1_sym_htm_v2.pdb"
QTM_CORNER_PDB = NATIVE_CACHE / "corner_qtm_v3.pdb"
QTM_PHASE1_PDB = NATIVE_CACHE / "phase1_qtm_v3.pdb"
QTM_EDGE_PDB_A = NATIVE_CACHE / "edge_a_qtm_v3.pdb"
QTM_EDGE_PDB_B = NATIVE_CACHE / "edge_b_qtm_v3.pdb"
QTM_STRONG_PDB = NATIVE_CACHE / "strong_qtm_v3.pdb"
QTM_STRONG_PDB_NIBBLE = NATIVE_CACHE / "strong_qtm_v4_nibble.pdb"
QTM_TAIL_PDB_8 = NATIVE_CACHE / "tail_qtm_depth8_v5.pdb"
QTM_TAIL_PDB_7 = NATIVE_CACHE / "tail_qtm_depth7_v5.pdb"
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
QTM_TAIL_PDB = next((path for path in (QTM_TAIL_PDB_8, QTM_TAIL_PDB_7) if path.is_file()), None)


def _strong_pdb_is_complete(path: os.PathLike[str]) -> bool:
    try:
        with open(path, "rb") as source:
            header = source.read(80)
        return (len(header) == 80 and header[:8] == b"RCPDB01\0"
                and struct.unpack_from("<I", header, 40)[0] & 1 != 0)
    except OSError:
        return False


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
        self._ready: dict | None = None

    @staticmethod
    def _command() -> list[str]:
        profile = os.environ.get("CUBE_QTM_ASSET_PROFILE", "strong").strip().lower()
        if profile not in {"base", "standard", "strong", "partial", "fallback"}:
            raise NativeSolverError(f"unknown QTM asset profile: {profile}")
        loading = os.environ.get("CUBE_NATIVE_ASSET_LOADING", "staged").strip().lower()
        if loading not in {"eager", "staged"}:
            raise NativeSolverError(f"unknown native asset loading mode: {loading}")
        command = [
            str(NATIVE_EXE),
            "serve",
            "--pdb",
            str(CORNER_PDB.relative_to(ROOT)),
            f"--asset-loading={loading}",
        ]
        if PHASE1_PDB.is_file():
            command.extend(("--phase1-pdb", str(PHASE1_PDB.relative_to(ROOT))))
        qtm_corner = NATIVE_CACHE / "corner_qtm_depth3_v3.pdb" if profile == "partial" else QTM_CORNER_PDB
        qtm_phase1 = NATIVE_CACHE / "phase1_qtm_depth3_v3.pdb" if profile == "partial" else QTM_PHASE1_PDB
        if profile != "fallback" and qtm_corner.is_file():
            command.extend(("--qtm-pdb", str(qtm_corner.relative_to(ROOT))))
        if profile != "fallback" and qtm_phase1.is_file():
            command.extend(("--qtm-phase1-pdb", str(qtm_phase1.relative_to(ROOT))))
        if profile == "strong":
            preferred = os.environ.get("CUBE_QTM_STRONG_FORMAT", "auto").strip().lower()
            if preferred not in {"auto", "byte", "nibble"}:
                raise NativeSolverError(f"unknown strong PDB encoding: {preferred}")
            choices = (QTM_STRONG_PDB_NIBBLE, QTM_STRONG_PDB) if preferred == "auto" else (
                (QTM_STRONG_PDB_NIBBLE,) if preferred == "nibble" else (QTM_STRONG_PDB,))
            strong = next((path for path in choices if path.is_file() and _strong_pdb_is_complete(path)), None)
            if strong is not None:
                command.extend(("--strong-pdb", str(strong.relative_to(ROOT))))
                if (preferred == "auto" and strong == QTM_STRONG_PDB_NIBBLE and QTM_STRONG_PDB.is_file()
                        and _strong_pdb_is_complete(QTM_STRONG_PDB)):
                    command.extend(("--strong-pdb-fallback", str(QTM_STRONG_PDB.relative_to(ROOT))))
        if TAIL_PDB.is_file():
            command.extend(("--tail-pdb", str(TAIL_PDB.relative_to(ROOT))))
        qtm_tail = (QTM_TAIL_PDB_8 if profile == "strong" else QTM_TAIL_PDB_7
                    if profile == "standard" else None)
        if qtm_tail is not None and qtm_tail.is_file():
            command.extend(("--qtm-tail-pdb", str(qtm_tail.relative_to(ROOT))))
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
        for flag, path in (("--qtm-edge-pdb-a", QTM_EDGE_PDB_A),
                           ("--qtm-edge-pdb-b", QTM_EDGE_PDB_B)):
            if use_edge_pdbs and path.is_file():
                command.extend((flag, str(path.relative_to(ROOT))))
        return command

    def _start_locked(self, deadline: float | None, cancel_event: threading.Event | None) -> None:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
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
        supported_metrics = ready.get("metrics")
        if (
            ready.get("protocol_version", 0) != 3
            or ready.get("proof_version", 0) != 3
            or not isinstance(supported_metrics, list)
            or any(not isinstance(item, str) for item in supported_metrics)
            or not {"HTM", "QTM"}.issubset(supported_metrics)
        ):
            self._stop_locked()
            raise NativeSolverError("native service HTM/QTM capabilities do not match protocol 3 / proof 3; rebuild native/build.ps1")
        self._ready = ready

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._ready = None
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
        metric: str = "HTM",
    ) -> dict:
        if deadline is None and timeout_seconds is not None:
            deadline = time.monotonic() + timeout_seconds
        while not self._lock.acquire(timeout=0.05):
            if cancel_event is not None and cancel_event.is_set():
                raise NativeSolverCancelled("native solver search was cancelled while queued")
            if deadline is not None and time.monotonic() >= deadline:
                raise NativeSolverTimeout("native solver deadline expired while queued")
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise NativeSolverCancelled("native solver search was cancelled")
            if deadline is not None and time.monotonic() >= deadline:
                raise NativeSolverTimeout("native solver deadline expired")
            if self._process is None or self._process.poll() is not None:
                self._stop_locked()
                self._start_locked(deadline, cancel_event)
            assert self._process is not None and self._process.stdin is not None and self._lines is not None
            incumbent = " ".join(incumbent_moves or [])
            request_id = uuid.uuid4().hex
            remaining = 0 if deadline is None else max(0.000001, deadline - time.monotonic())
            request = (
                f"solve\t{request_id}\t{to_facelets(cube)}\t{max_depth}\t{remaining}\t{worker_count}\t{metric}\t{incumbent}\n"
            )
            self._send_locked(request)

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
                    if candidate_text and candidate_text != incumbent and (
                        not incumbent or solution_cost(candidate or [], metric) < solution_cost(incumbent, metric)
                    ):
                        self._send_locked(f"incumbent\t{request_id}\t{candidate_text}\n")
                        incumbent = candidate_text
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
                if event.get("type") == "asset_ready" and self._ready is not None:
                    assets = self._ready.setdefault("assets", {}).setdefault("QTM", {})
                    assets.update(profile=event.get("profile"), strong=event.get("strong"),
                                  tail_depth=event.get("tail_depth"))
                    continue
                if event.get("request_id") != request_id:
                    continue
                if event.get("type") == "candidate":
                    moves = event.get("moves")
                    if event.get("metric") != metric or not isinstance(moves, list) or any(
                        not isinstance(move, str) or move not in MOVE_INDEX for move in moves
                    ):
                        self._stop_locked()
                        raise NativeSolverError("native candidate frame is invalid")
                    verified = cube
                    for move in moves:
                        verified = verified.apply_move_index(MOVE_INDEX[move])
                    if not verified.is_solved() or event.get("cost") != solution_cost(moves, metric):
                        self._stop_locked()
                        raise NativeSolverError("native candidate failed whole-cube verification")
                    if progress_callback is not None:
                        profile = event.get("asset_profile") or ((self._ready or {}).get("assets") or {}).get(metric, {}).get("profile")
                        progress_callback({**event, "engine": "native-cpp", "asset_profile": profile})
                    continue
                if event.get("type") == "progress":
                    if event.get("metric") != metric:
                        self._stop_locked()
                        raise NativeSolverError("native solver progress metric does not match the request")
                    if progress_callback is not None:
                        profile = event.get("asset_profile") or ((self._ready or {}).get("assets") or {}).get(metric, {}).get("profile")
                        progress_callback({**event, "engine": "native-cpp", "asset_profile": profile})
                    continue
                if event.get("type") == "error" or not event.get("ok"):
                    raise NativeSolverError(str(event.get("error", "native solver failed")))
                if event.get("type") == "result":
                    if stop_reason is not None:
                        raise stop_reason
                    return event
        finally:
            self._lock.release()

    def close(self) -> None:
        with self._lock:
            self._stop_locked()


_PERSISTENT_SOLVER = _PersistentNativeSolver()
atexit.register(_PERSISTENT_SOLVER.close)


def native_solver_available() -> bool:
    return NATIVE_EXE.is_file() and all(path.is_file() for path in (CORNER_PDB, PHASE1_PDB))


def native_qtm_candidate_available() -> bool:
    return native_solver_available() and QTM_PHASE1_PDB.is_file()


def _validated_result(cube: CubieCube, payload: dict, metric: str = "HTM") -> dict:
    metric = normalize_metric(metric)
    if payload.get("metric") != metric:
        raise NativeSolverError("native solver result metric does not match the request")
    if payload.get("status") == "timeout":
        raise NativeSolverTimeout("native optimal proof timed out")
    if payload.get("status") == "cancelled":
        raise NativeSolverCancelled("native solver search was cancelled")
    moves = payload.get("moves")
    if not isinstance(moves, list) or any(not isinstance(move, str) for move in moves):
        raise NativeSolverError("native solver returned invalid move data")
    no_solution = payload.get("status") == "budget_exhausted" and type(payload.get("depth")) is int and payload["depth"] == -1
    if no_solution and (moves or payload.get("optimal")):
        raise NativeSolverError("native solver returned an inconsistent exhausted-budget result")
    verified = cube
    try:
        for move in moves:
            verified = verified.apply_move_index(MOVE_INDEX[move])
    except KeyError as exc:
        raise NativeSolverError(f"native solver returned unknown move: {exc.args[0]}") from exc
    if not no_solution and not verified.is_solved():
        raise NativeSolverError("native solver returned an invalid solution")
    cost = solution_cost(moves, metric)
    if not no_solution and (type(payload.get("depth")) is not int or payload["depth"] != cost):
        raise NativeSolverError("native solver result depth does not match its move cost")
    return {
        "moves": moves,
        "solution": " ".join(moves),
        "depth": None if no_solution else cost,
        "metric": metric,
        "status": payload.get("status", "complete"),
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
        "candidate_phase1_nodes": int(payload.get("candidate_phase1_nodes", 0)),
        "candidate_phase2_nodes": int(payload.get("candidate_phase2_nodes", 0)),
        "candidate_worker_done_seconds": payload.get("candidate_worker_done_seconds"),
        "proof_worker_return_seconds": payload.get("proof_worker_return_seconds"),
        "proof_worker_busy_seconds": round(sum(float(worker.get("busy_seconds", 0.0))
                                               for worker in payload.get("workers", [])), 3),
        "engine": "native-cpp",
        "asset_profile": payload.get("asset_profile"),
    }


def solve_native(
    cube: CubieCube,
    *,
    max_depth: int | None = None,
    timeout_seconds: float | None,
    incumbent_moves: list[str] | None,
    cancel_event: threading.Event | None,
    threads: int | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    deadline: float | None = None,
    incumbent_provider: Callable[[], list[str] | None] | None = None,
    metric: str = "HTM",
) -> dict | None:
    metric = normalize_metric(metric)
    max_depth = resolve_max_depth(3, metric, max_depth)
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
        deadline,
        incumbent_provider,
        metric,
    )
    return _validated_result(cube, payload, metric)
