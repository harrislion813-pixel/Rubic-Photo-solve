from __future__ import annotations

import json
import math
import os
import logging
import mimetypes
import errno
import socket
import threading
import time
import uuid
import importlib.util
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cube_app import __version__
from cube_app.cubie import CubeStateError, CubieCube, MOVE_INDEX, from_facelets, to_facelets
from cube_app.solvers.htm.fast import FastTwoPhaseSolver
from cube_app.solvers.htm.native import (
    NativeSolverCancelled,
    NativeSolverError,
    NativeSolverTimeout,
    native_solver_available,
    solve_native,
)
from cube_app.solvers.htm.optimal import OptimalSolver, SearchCancelled, SearchTimeout
from cube_app.runtime import application_root
from cube_app.solvers.htm.two_by_two import TwoByTwoSolver
from cube_app.solvers.resource_broker import BROKER, ResourceCancelled

try:
    from cube_app.detection import DetectionPipeline
    from cube_app.vision import assess_detected_face_quality, decode_data_url
except ImportError:  # The browser detector remains available without OpenCV.
    DetectionPipeline = None
    assess_detected_face_quality = None
    decode_data_url = None


ROOT = application_root()
WEB_ROOT = ROOT / "web"
HOST = "127.0.0.1"
PORT = 8765
APP_VERSION = __version__

SOLVER = OptimalSolver(ROOT / ".cache" / "htm", parallel=True)
PROBE_SOLVER = OptimalSolver(ROOT / ".cache" / "htm", parallel=False)
FAST_SOLVER = FastTwoPhaseSolver(ROOT / ".cache" / "htm")
TWO_BY_TWO_SOLVER = TwoByTwoSolver(ROOT / ".cache" / "htm")
QUICK_OPTIMAL_PROBE_SECONDS = 0.75
QUICK_SOLVE_SECONDS = 1.5
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
OPTIMAL_SEARCH_LOCK = threading.Lock()
QUICK_SEARCH_LOCK = threading.Lock()
MAX_JOBS = 100
TERMINAL_STATUSES = {"complete", "timeout", "error", "cancelled"}
DETECTION_PIPELINE = DetectionPipeline() if DetectionPipeline is not None else None


def qtm_installed() -> bool:
    assets = ROOT / "assets" / "qtm" / "v1"
    return (
        (ROOT / "native" / "qtm" / "build" / "cube_solver_qtm.exe").is_file()
        and (assets / "corner_qtm_v3.pdb").is_file()
        and (assets / "phase1_qtm_v3.pdb").is_file()
    )


def qtm_module_installed() -> bool:
    try:
        return importlib.util.find_spec("cube_app.solvers.qtm") is not None
    except (ImportError, ValueError):
        return False


def qtm_capabilities() -> dict:
    assets = ROOT / "assets" / "qtm" / "v1"
    exact = ROOT / ".cache" / "qtm" / "two_by_two_qtm_v1.bin"
    return {
        "2": {"available": qtm_module_installed(), "profile": "exact-2x2",
              "asset_state": "unverified" if exact.is_file() else "not_loaded", "adopted_profile": None},
        "3": {"available": qtm_installed(),
              "base_asset_state": "unverified" if qtm_installed() else "missing",
              "strong_asset_state": "unverified" if any((assets / name).is_file() for name in
                                     ("strong_qtm_v4_nibble.pdb", "strong_qtm_v3.pdb")) else "missing",
              "adopted_profile": None},
    }


class JobCapacityError(RuntimeError):
    """Raised when no more background proof jobs can be retained."""


def result_payload(result) -> dict:
    return {
        "moves": result.moves,
        "solution": result.text,
        "depth": result.depth,
        "metric": result.metric,
        "optimal": result.optimal,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
    }


def prepare_optimal_job(
    cube: CubieCube,
    quick_result,
    max_depth: int,
    timeout_seconds: float | None,
    *,
    deadline: float | None = None,
    started: float | None = None,
    candidate_enabled: bool = False,
) -> tuple[str, threading.Thread]:
    created = time.monotonic() if started is None else started
    if deadline is None and timeout_seconds is not None:
        deadline = created + timeout_seconds
    state_key = (to_facelets(cube), max_depth, "HTM", 1)
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    with JOBS_LOCK:
        for existing_id, existing in JOBS.items():
            if existing.get("_state_key") == state_key and existing.get("status") in {"queued", "running"}:
                return existing_id, existing["_worker"]
        if len(JOBS) >= MAX_JOBS:
            terminal = [
                (key, value.get("updated_at", 0.0))
                for key, value in JOBS.items()
                if value.get("status") in {"complete", "timeout", "error", "cancelled"}
                and not value["_worker"].is_alive()
                and not (value.get("_candidate_worker") and value["_candidate_worker"].is_alive())
            ]
            remove_count = len(JOBS) - MAX_JOBS + 1
            for key, _ in sorted(terminal, key=lambda item: item[1])[:remove_count]:
                JOBS.pop(key, None)
        if len(JOBS) >= MAX_JOBS:
            raise JobCapacityError("后台求解任务过多，请取消旧任务后重试。")
        JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "_cancel_event": cancel_event,
            "_broker": BROKER,
            "incumbent_depth": quick_result.depth if quick_result is not None else None,
            "_state_key": state_key,
            "_deadline": deadline,
            "_started_at": created,
            "_done": threading.Event(),
            "_delivery_ready": threading.Event(),
            "_candidate_stop": threading.Event(),
            "_generation_done": threading.Event(),
            "_proof_lease": threading.Event(),
            "_serial_candidate": candidate_enabled and BROKER.threads == 1,
            "_proof_threads": max(1, BROKER.threads - int(candidate_enabled and BROKER.threads > 1)),
            "_incumbent_moves": quick_result.moves if quick_result is not None else None,
            "engine": "pending",
            "solution_generation_seconds": 0.0,
            "timing_events": [],
            "timings": {},
            "thread_quota": BROKER.threads,
            "candidate_thread_quota": int(candidate_enabled),
            "candidate_search_running": False,
            "early_candidate_delivery": os.environ.get("CUBE_HTM_EARLY_CANDIDATE", "off").lower() in {"1", "true", "on"},
        }
        if not candidate_enabled:
            JOBS[job_id]["_generation_done"].set()
        JOBS[job_id]["proof_threads"] = JOBS[job_id]["_proof_threads"]
        _record_job_event_locked(JOBS[job_id], "request_created", at=created)
        if quick_result is not None:
            JOBS[job_id]["candidate_result"] = result_payload(quick_result)
            JOBS[job_id]["_delivery_ready"].set()

        proof_max_depth = min(max_depth, quick_result.depth) if quick_result is not None else max_depth
        upper_bound = quick_result.depth if quick_result is not None else None
        incumbent_moves = quick_result.moves if quick_result is not None else None
        thread = threading.Thread(
            target=run_optimal_job,
            args=(job_id, cube, proof_max_depth, timeout_seconds, upper_bound, incumbent_moves, cancel_event, deadline),
            name=f"cube-optimal-{job_id[:8]}",
            daemon=True,
        )
        JOBS[job_id]["_worker"] = thread
        return job_id, thread


def start_optimal_job(job_id: str, worker: threading.Thread) -> None:
    with JOBS_LOCK:
        if not JOBS[job_id].get("_started"):
            JOBS[job_id]["_started"] = True
            if worker.ident is None:
                worker.start()


def remaining_seconds(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SearchTimeout("搜索超时。")
    return remaining


def generate_quick_solution(cube: CubieCube, deadline: float | None, *,
                            candidate_callback=None, cancel_event: threading.Event | None = None):
    while not QUICK_SEARCH_LOCK.acquire(timeout=0.05):
        if cancel_event is not None and cancel_event.is_set():
            raise SearchCancelled("快速两阶段搜索已取消。")
        remaining_seconds(deadline)
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise SearchCancelled("快速两阶段搜索已取消。")
        if FAST_SOLVER._tables is None and PROBE_SOLVER._tables is not None:
            FAST_SOLVER._tables = PROBE_SOLVER._tables
        budget = min(QUICK_SOLVE_SECONDS, remaining_seconds(deadline) or QUICK_SOLVE_SECONDS)
        return FAST_SOLVER.solve_cube(cube, timeout_seconds=budget,
                                      candidate_callback=candidate_callback, cancel_event=cancel_event, deadline=deadline)
    finally:
        QUICK_SEARCH_LOCK.release()


def _record_job_event_locked(job: dict, event: str, *, at: float | None = None, **values) -> None:
    """Raw request-relative events; monotonic timestamps are never rounded."""
    at = time.monotonic() if at is None else at
    elapsed = at - job["_started_at"]
    job["timing_events"].append({"event": event, "monotonic": at, "elapsed_seconds": elapsed, **values})
    job["timings"].setdefault(event + "_seconds", elapsed)


def record_job_event(job_id: str, event: str, **values) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is not None:
            _record_job_event_locked(job, event, **values)


def job_snapshot(job_id: str) -> dict | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        snapshot = {key: value for key, value in job.items()
                    if key not in {"created_at", "updated_at"} and not key.startswith("_")}
        snapshot["timing_events"] = list(job["timing_events"])
        snapshot["timings"] = dict(job["timings"])
        return snapshot


def mark_htm_http_return(job_id: str, *, candidate_included: bool, initial: bool) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        event = "http_initial_return" if initial else "http_poll_return"
        _record_job_event_locked(job, event, candidate_included=candidate_included)
        if candidate_included:
            job["timings"].setdefault("first_candidate_http_seconds", time.monotonic() - job["_started_at"])


def publish_htm_candidate(job_id: str, expected_job: dict, cube: CubieCube, result, *,
                          publish: bool = True, record_generated: bool = True) -> bool:
    generated_at = time.monotonic()
    moves = list(result.moves)
    verified = cube
    for move in moves:
        if move not in MOVE_INDEX:
            raise ValueError("HTM 候选包含未知动作。")
        verified = verified.apply_move_index(MOVE_INDEX[move])
    if not verified.is_solved() or result.metric != "HTM" or result.depth != len(moves):
        raise ValueError("HTM 候选动作回放或计步不正确。")
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is not expected_job:
            return False
        deadline = job["_deadline"]
        if (job["status"] in TERMINAL_STATUSES or job["_cancel_event"].is_set()
                or job["_candidate_stop"].is_set()
                or (deadline is not None and time.monotonic() >= deadline)):
            return False
        if record_generated:
            _record_job_event_locked(job, "candidate_generated", at=generated_at, cost=len(moves), moves=moves,
                                     solver_elapsed_seconds=result.elapsed_seconds)
        if not publish:
            return True
        previous = job.get("incumbent_depth")
        if previous is not None and len(moves) >= previous:
            return False
        job["_incumbent_moves"] = moves
        job["incumbent_depth"] = len(moves)
        job["candidate_result"] = {**result_payload(result), "moves": moves}
        job["solution_generation_seconds"] = round(generated_at - job.get("_candidate_started_at", generated_at), 3)
        job["updated_at"] = time.time()
        _record_job_event_locked(job, "candidate_published", cost=len(moves), moves=moves)
        job["_delivery_ready"].set()
        return True


def start_candidate_job(job_id: str, cube: CubieCube) -> bool:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None or job.get("_generator_started") or job["status"] in TERMINAL_STATUSES:
            return False
        job["_generator_started"] = True
        stop = job["_candidate_stop"]
        deadline = job["_deadline"]

        def generate() -> None:
            generation_started = time.monotonic()
            claimed = False
            try:
                # Only the job owning the proof slot may spend the candidate
                # allowance. This also makes restoring its full proof quota safe.
                while not job["_proof_lease"].wait(0.05):
                    if stop.is_set():
                        raise SearchCancelled("快速两阶段搜索已取消。")
                    remaining_seconds(deadline)
                job["_broker"].enter_htm(deadline=deadline, cancel_event=stop)
                claimed = True
                with JOBS_LOCK:
                    if JOBS.get(job_id) is job:
                        job["candidate_search_running"] = True
                        job["_candidate_started_at"] = time.monotonic()
                record_job_event(job_id, "candidate_search_started")
                early = job["early_candidate_delivery"]
                result = generate_quick_solution(cube, deadline, cancel_event=stop,
                    candidate_callback=lambda result: publish_htm_candidate(job_id, job, cube, result, publish=early))
                if result is not None and not early:
                    # The failed default-request gate keeps the original delivery
                    # policy: publish the best result only after the same budget.
                    publish_htm_candidate(job_id, job, cube, result, record_generated=False)
            except (SearchTimeout, SearchCancelled, TimeoutError, ResourceCancelled):
                pass
            except Exception as exc:  # Candidate failure leaves the independent proof running.
                logging.warning("HTM 候选搜索失败: %s", exc)
                with JOBS_LOCK:
                    if JOBS.get(job_id) is job:
                        job["candidate_error"] = str(exc)
            finally:
                with JOBS_LOCK:
                    if JOBS.get(job_id) is job:
                        job["solution_generation_seconds"] = round(time.monotonic() - generation_started, 3)
                        job["candidate_search_running"] = False
                        _record_job_event_locked(job, "candidate_search_finished")
                        job["_generation_done"].set()
                        job["_delivery_ready"].set()
                if claimed:
                    job["_broker"].leave_htm()

        candidate_worker = threading.Thread(target=generate, name=f"cube-candidate-{job_id[:8]}", daemon=True)
        job["_candidate_worker"] = candidate_worker
        candidate_worker.start()
        return True


def update_job(job_id: str, **values: object) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        if job["status"] in TERMINAL_STATUSES:
            return
        job.update(values)
        job["updated_at"] = time.time()
        if job["status"] in TERMINAL_STATUSES:
            _record_job_event_locked(job, "terminal", status=job["status"], result=job.get("result"),
                native_pid=job.get("native_pid"), peak_working_set_bytes=job.get("peak_working_set_bytes"),
                memory_scope=job.get("memory_scope"))
            job["_candidate_stop"].set()
            job["_delivery_ready"].set()


def run_optimal_job(
    job_id: str,
    cube: CubieCube,
    max_depth: int,
    timeout_seconds: float | None,
    upper_bound: int | None = None,
    incumbent_moves: list[str] | None = None,
    cancel_event: threading.Event | None = None,
    deadline: float | None = None,
) -> None:
    started = time.monotonic()
    if deadline is None and timeout_seconds is not None:
        deadline = started + timeout_seconds
    acquired = False
    htm_claimed = False
    job = None
    broker = BROKER
    try:
        with JOBS_LOCK:
            job = JOBS[job_id]
            broker = job["_broker"]
            generation_done = job["_generation_done"]
            serial_candidate = job["_serial_candidate"]
            proof_threads = job["_proof_threads"]
        broker.enter_htm(deadline=deadline, cancel_event=cancel_event)
        htm_claimed = True
        while not acquired:
            if cancel_event is not None and cancel_event.is_set():
                raise SearchCancelled("搜索已取消。")
            remaining_seconds(deadline)
            acquired = OPTIMAL_SEARCH_LOCK.acquire(timeout=0.05)
        if cancel_event is not None and cancel_event.is_set():
            raise SearchCancelled("搜索已取消。")
        job["_proof_lease"].set()
        if serial_candidate:
            record_job_event(job_id, "proof_waiting_for_candidate", threads=proof_threads)
            while not generation_done.wait(0.05):
                if cancel_event is not None and cancel_event.is_set():
                    raise SearchCancelled("搜索已取消。")
                remaining_seconds(deadline)
        update_job(job_id, status="running")
        record_job_event(job_id, "proof_started", threads=proof_threads)

        def report_progress(progress: dict) -> None:
            values = {"progress": progress, "engine": progress.get("engine", "python")}
            if "threads" in progress:
                values["proof_threads"] = progress["threads"]
            update_job(job_id, **values)
            record_job_event(job_id, "proof_progress", progress=dict(progress))

        def incumbent_provider() -> list[str] | None:
            with JOBS_LOCK:
                current = JOBS.get(job_id)
                if current is not job or current["status"] in TERMINAL_STATUSES:
                    return None
                moves = current.get("_incumbent_moves", incumbent_moves)
                return None if moves is None else list(moves)

        def report_native_event(event: dict) -> None:
            details = dict(event)
            kind = str(details.pop("type"))
            with JOBS_LOCK:
                current = JOBS.get(job_id)
                if current is job:
                    if details.get("native_pid") is not None:
                        current["native_pid"] = details["native_pid"]
                    if details.get("peak_working_set_bytes") is not None:
                        current["peak_working_set_bytes"] = max(current.get("peak_working_set_bytes", 0),
                                                                 details["peak_working_set_bytes"])
                        current["memory_scope"] = details["memory_scope"]
            record_job_event(job_id, kind, **details)

        def proof_threads_provider() -> int | None:
            with JOBS_LOCK:
                current = JOBS.get(job_id)
                if (current is not job or current["status"] in TERMINAL_STATUSES
                        or current["_cancel_event"].is_set()
                        or (deadline is not None and time.monotonic() >= deadline)):
                    return None
                return current["thread_quota"] if current["_generation_done"].is_set() else proof_threads

        def guard_thread_update(send) -> bool:
            # Commit the protocol write while holding the same lock used to
            # publish terminal/cancel state, closing the provider-to-write race.
            with JOBS_LOCK:
                current = JOBS.get(job_id)
                if (current is not job or current["status"] in TERMINAL_STATUSES
                        or current["_cancel_event"].is_set()
                        or (deadline is not None and time.monotonic() >= deadline)):
                    return False
                send()
                return True

        try:
            update_job(job_id, engine="native-cpp")
            native_result = solve_native(
                cube,
                max_depth=max_depth,
                timeout_seconds=remaining_seconds(deadline),
                incumbent_moves=incumbent_moves,
                cancel_event=cancel_event,
                progress_callback=report_progress,
                deadline=deadline,
                incumbent_provider=incumbent_provider,
                threads=proof_threads,
                event_callback=report_native_event,
                threads_provider=proof_threads_provider,
                threads_update_guard=guard_thread_update,
            )
        except NativeSolverCancelled as exc:
            raise SearchCancelled(str(exc)) from exc
        except NativeSolverTimeout as exc:
            raise SearchTimeout(str(exc)) from exc
        except NativeSolverError as exc:
            logging.warning("原生求解失败，使用剩余预算回退 Python: %s", exc)
            update_job(job_id, fallback_reason=str(exc))
            native_result = None
        if native_result is not None:
            if cancel_event is not None and cancel_event.is_set():
                raise SearchCancelled("搜索已取消。")
            update_job(job_id, status="complete", result=native_result)
            return
        update_job(job_id, engine="python")
        with JOBS_LOCK:
            if "fallback_reason" not in JOBS.get(job_id, {}):
                update_reason = "原生程序或必需的 PDB 文件不可用。"
            else:
                update_reason = None
        if update_reason:
            update_job(job_id, fallback_reason=update_reason)
        incumbent_moves = incumbent_provider()
        upper_bound = len(incumbent_moves) if incumbent_moves else upper_bound

        original_workers = SOLVER.max_workers
        SOLVER.max_workers = min(original_workers, proof_threads)
        try:
            try:
                result = SOLVER.solve_cube(
                    cube,
                    max_depth=max_depth,
                    timeout_seconds=remaining_seconds(deadline),
                    deadline=deadline,
                    upper_bound=upper_bound,
                    incumbent_moves=incumbent_moves,
                    cancel_event=cancel_event,
                    progress_callback=report_progress,
                )
            except PermissionError:
                result = PROBE_SOLVER.solve_cube(
                    cube,
                    max_depth=max_depth,
                    timeout_seconds=remaining_seconds(deadline),
                    deadline=deadline,
                    upper_bound=upper_bound,
                    incumbent_moves=incumbent_moves,
                    cancel_event=cancel_event,
                    progress_callback=report_progress,
                )
        finally:
            SOLVER.max_workers = original_workers
        if cancel_event is not None and cancel_event.is_set():
            raise SearchCancelled("搜索已取消。")
        update_job(job_id, status="complete", result={**result_payload(result), "engine": "python"})
    except (SearchCancelled, ResourceCancelled) as exc:
        update_job(job_id, status="cancelled", message=str(exc))
    except (SearchTimeout, TimeoutError) as exc:
        update_job(job_id, status="timeout", message=str(exc))
    except Exception as exc:  # pragma: no cover - background safety net.
        update_job(job_id, status="error", message=str(exc))
    finally:
        if job is not None:
            job["_candidate_stop"].set()
            candidate_worker = job.get("_candidate_worker")
            if candidate_worker is not None and candidate_worker.ident is not None:
                candidate_worker.join()
        if htm_claimed:
            broker.leave_htm()
        if acquired:
            OPTIMAL_SEARCH_LOCK.release()
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job is not None:
                job["proof_elapsed_seconds"] = round(time.monotonic() - started, 3)
                job["_done"].set()


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class AppHandler(BaseHTTPRequestHandler):
    server_version = f"CubeOptimalApp/{APP_VERSION}"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/version":
            self._send_json({"ok": True, "version": APP_VERSION})
            return
        if path == "/api/capabilities":
            qtm_available = qtm_installed()
            self._send_json({"ok": True, "HTM": True, "QTM": qtm_available,
                             "QTM_status": "stable" if qtm_available else "unavailable",
                             "QTM_sizes": qtm_capabilities()})
            return
        if path.startswith("/api/solve/"):
            job_id = path.removeprefix("/api/solve/").strip("/")
            if job_id.startswith("qtm-"):
                if not qtm_module_installed():
                    self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
                    return
                from cube_app.solvers.qtm.backend import BACKEND

                snapshot = BACKEND.snapshot(job_id)
                self._send_json({"ok": True, **snapshot} if snapshot is not None
                                else {"ok": False, "error": "求解任务不存在或已过期"},
                                status=200 if snapshot is not None else 404)
                if snapshot is not None:
                    BACKEND.mark_http_return(job_id, candidate_included=snapshot.get("candidate_result") is not None,
                                             initial=False)
                return
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                snapshot = (
                    None
                    if job is None
                    else {
                        key: value
                        for key, value in job.items()
                        if key not in {"created_at", "updated_at"} and not key.startswith("_")
                    }
                )
                if snapshot is not None:
                    snapshot["timing_events"] = list(job["timing_events"])
                    snapshot["timings"] = dict(job["timings"])
                if snapshot is not None and snapshot.get("status") == "queued":
                    queued = sorted(
                        (value.get("created_at", 0.0), key)
                        for key, value in JOBS.items()
                        if value.get("status") == "queued"
                    )
                    snapshot["queue_position"] = next(
                        (index + 1 for index, (_, key) in enumerate(queued) if key == job_id),
                        1,
                    )
            if snapshot is None:
                self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
            else:
                self._send_json({"ok": True, **snapshot})
                mark_htm_http_return(job_id, candidate_included=snapshot.get("candidate_result") is not None
                                     or snapshot.get("result") is not None, initial=False)
            return
        if path in ("", "/"):
            self._send_file(WEB_ROOT / "index.html")
            return
        candidate = (WEB_ROOT / path.lstrip("/")).resolve()
        if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
            self._send_json({"error": "Forbidden"}, status=403)
            return
        if candidate.exists() and candidate.is_file():
            self._send_file(candidate)
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/solve/") and parsed.path.endswith("/cancel"):
            job_id = parsed.path.removeprefix("/api/solve/").removesuffix("/cancel").strip("/")
            if job_id.startswith("qtm-"):
                if not qtm_module_installed():
                    self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
                    return
                from cube_app.solvers.qtm.backend import BACKEND

                snapshot = BACKEND.cancel(job_id)
                self._send_json({"ok": True, **snapshot} if snapshot is not None
                                else {"ok": False, "error": "求解任务不存在或已过期"},
                                status=200 if snapshot is not None else 404)
                return
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if job is None:
                    status = None
                else:
                    status = str(job.get("status", "queued"))
                    if status not in {"complete", "timeout", "error", "cancelled"}:
                        cancel_event = job.get("_cancel_event")
                        if isinstance(cancel_event, threading.Event):
                            cancel_event.set()
                        status = "cancelled"
                        job["status"] = status
                        job["message"] = "搜索已取消。"
                        job["updated_at"] = time.time()
                        _record_job_event_locked(job, "terminal", status="cancelled")
                        job["_candidate_stop"].set()
                        job["_delivery_ready"].set()
            if status is None:
                self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
            else:
                self._send_json({"ok": True, "job_id": job_id, "status": status})
            return
        if parsed.path == "/api/detect":
            try:
                if decode_data_url is None or DETECTION_PIPELINE is None or assess_detected_face_quality is None:
                    self._send_json({"ok": False, "error": "OpenCV 检测器不可用"}, status=503)
                    return
                payload = self._read_json()
                grid_size = int(payload.get("cube_size", 3))
                if grid_size not in (2, 3):
                    raise ValueError("cube_size 只能是 2 或 3。")
                image = decode_data_url(str(payload.get("image", "")))
                detection_batch = DETECTION_PIPELINE.detect(image, grid_size=grid_size, limit=3)
                candidates = detection_batch.candidates
                if not candidates:
                    self._send_json({"ok": True, "detected": False, "app_version": APP_VERSION})
                else:
                    self._send_json(
                        {
                            "ok": True,
                            "detected": True,
                            "corners": candidates[0].corners,
                            "confidence": candidates[0].confidence,
                            "method": candidates[0].method,
                            "score": candidates[0].score,
                            "quality": assess_detected_face_quality(image, candidates[0]),
                            "candidates": [
                                {
                                    "corners": candidate.corners,
                                    "confidence": candidate.confidence,
                                    "method": candidate.method,
                                    "score": candidate.score,
                                    "quality": assess_detected_face_quality(image, candidate),
                                }
                                for candidate in candidates
                            ],
                            "app_version": APP_VERSION,
                            "fallback_used": detection_batch.fallback_used,
                        }
                    )
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover - keeps the local app friendly.
                self._send_json({"ok": False, "error": f"图像检测失败：{exc}"}, status=500)
            return
        if parsed.path != "/api/solve":
            self._send_json({"error": "Not found"}, status=404)
            return
        htm_claimed = False
        request_started = time.monotonic()
        try:
            payload = self._read_json()
            facelets = str(payload.get("facelets", ""))
            cube_size = int(payload.get("cube_size", 3))
            if cube_size not in (2, 3):
                raise ValueError("cube_size 只能是 2 或 3。")
            metric = str(payload.get("metric", "HTM")).upper()
            if metric not in {"HTM", "QTM"}:
                raise ValueError("metric 必须是 HTM 或 QTM。")
            default_depth = (11 if cube_size == 2 else 20) if metric == "HTM" else (14 if cube_size == 2 else 40)
            max_depth = int(payload.get("max_depth", default_depth))
            if not 0 <= max_depth <= (20 if metric == "HTM" else 40):
                raise ValueError("max_depth 超出所选计步方式的范围。")
            timeout = payload.get("timeout_seconds", 180)
            timeout_seconds = None if timeout in (None, 0, "0", "none") else float(timeout)
            if timeout_seconds is not None and (
                not math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 3600
            ):
                raise ValueError("timeout_seconds 必须在 0.1 到 3600 秒之间。")
            deadline = None if timeout_seconds is None else request_started + timeout_seconds
            if metric == "QTM":
                if not qtm_module_installed() or (cube_size == 3 and not qtm_installed()):
                    self._send_json({"ok": False, "metric": "QTM",
                                     "error": "QTM 组件未安装，请按 README 生成运行表或使用完整便携包。"}, status=503)
                    return
                from cube_app.solvers.qtm.backend import BACKEND, QtmUnavailable, QtmJobCapacityError

                try:
                    result = BACKEND.submit(facelets, cube_size, max_depth, timeout_seconds,
                                            started=request_started)
                except (QtmUnavailable, QtmJobCapacityError) as exc:
                    self._send_json({"ok": False, "metric": "QTM", "error": str(exc)}, status=503)
                    return
                self._send_json(result)
                if result.get("job_id"):
                    BACKEND.mark_http_return(result["job_id"], candidate_included=result.get("depth") is not None)
                return
            resource_wait_seconds = BROKER.enter_htm(deadline=deadline)
            htm_claimed = True
            remaining_seconds(deadline)
            if cube_size == 2:
                result = TWO_BY_TWO_SOLVER.solve_facelets(
                    facelets,
                    max_depth=min(max_depth, 11),
                    timeout_seconds=remaining_seconds(deadline),
                )
                self._send_json({"ok": True, **result_payload(result), "proof_status": "complete",
                                 "resource_wait_seconds": resource_wait_seconds})
                return

            cube = from_facelets(facelets)

            if native_solver_available():
                candidate_enabled = not cube.is_solved()
                job_id, worker = prepare_optimal_job(cube, None, max_depth, timeout_seconds, deadline=deadline,
                                                     started=request_started, candidate_enabled=candidate_enabled)
                start_optimal_job(job_id, worker)
                with JOBS_LOCK:
                    ready = JOBS[job_id]["_delivery_ready"]
                    serial_candidate = JOBS[job_id]["_serial_candidate"]
                # Retain the original quick-proof window. A one-thread request
                # serializes the candidate budget before proof instead of oversubscribing.
                if not serial_candidate:
                    ready.wait(min(QUICK_OPTIMAL_PROBE_SECONDS,
                                   remaining_seconds(deadline) or QUICK_OPTIMAL_PROBE_SECONDS))
                snapshot = job_snapshot(job_id)
                if candidate_enabled and snapshot["status"] not in TERMINAL_STATUSES:
                    start_candidate_job(job_id, cube)
                    ready.wait(remaining_seconds(deadline))
            else:
                probe_budget = min(
                    QUICK_OPTIMAL_PROBE_SECONDS, remaining_seconds(deadline) or QUICK_OPTIMAL_PROBE_SECONDS
                )
                probe_deadline = time.monotonic() + probe_budget
                try:
                    result = PROBE_SOLVER.solve_cube(
                        cube,
                        max_depth=max_depth,
                        timeout_seconds=probe_budget,
                        deadline=min(deadline, probe_deadline) if deadline else probe_deadline,
                    )
                except SearchTimeout:
                    result = None
                if result is not None:
                    self._send_json(
                        {"ok": True, **result_payload(result), "engine": "python", "proof_status": "complete",
                         "resource_wait_seconds": resource_wait_seconds}
                    )
                    return
                job_id, worker = prepare_optimal_job(cube, None, max_depth, timeout_seconds, deadline=deadline,
                                                     started=request_started, candidate_enabled=True)
                start_optimal_job(job_id, worker)
                start_candidate_job(job_id, cube)
                with JOBS_LOCK:
                    ready = JOBS[job_id]["_delivery_ready"]
                ready.wait(remaining_seconds(deadline))
            snapshot = job_snapshot(job_id)
            quick_payload = snapshot.get("candidate_result")
            response = {
                "ok": True,
                "job_id": job_id,
                "proof_status": snapshot["status"],
                "optimal": False,
                "engine": snapshot["engine"],
                "solution_generation_seconds": snapshot.get("solution_generation_seconds", 0.0),
                "request_elapsed_seconds": round(time.monotonic() - request_started, 3),
                "resource_wait_seconds": resource_wait_seconds,
                "timing_events": snapshot["timing_events"],
                "timings": snapshot["timings"],
                "thread_quota": snapshot["thread_quota"],
                "proof_threads": snapshot["proof_threads"],
            }
            if snapshot["status"] == "complete":
                response.update(snapshot["result"])
                response["proof_elapsed_seconds"] = snapshot.get("proof_elapsed_seconds", 0.0)
            elif quick_payload:
                response.update(quick_payload)
            else:
                response.update(
                    {
                        "moves": [],
                        "solution": "",
                        "depth": None,
                        "metric": "HTM",
                        "elapsed_seconds": 0.0,
                        "message": "正在后台严格搜索。",
                    }
                )
            self._send_json(response)
            mark_htm_http_return(job_id, candidate_included=response.get("depth") is not None, initial=True)
        except JobCapacityError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=503)
        except (CubeStateError, SearchTimeout, TimeoutError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # pragma: no cover - keeps the local app friendly.
            self._send_json({"ok": False, "error": f"服务器内部错误：{exc}"}, status=500)
        finally:
            if htm_claimed:
                BROKER.leave_htm()

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0:
            raise ValueError("Content-Length 不能为负数")
        if length > 25 * 1024 * 1024:
            raise ValueError("请求内容超过 25 MB")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求 JSON 必须是对象")
        return payload

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send_file(self, path: Path) -> None:
        if path.suffix == ".html":
            body = path.read_text(encoding="utf-8").replace("__APP_VERSION__", APP_VERSION).encode("utf-8")
        else:
            body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif path.suffix in (".html", ".css"):
            content_type = f"{content_type}; charset=utf-8"
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Cube-App-Version", APP_VERSION)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return


def main(*, open_browser: bool = False) -> None:
    server, port = create_server()
    write_port_file(port)
    url = f"http://{HOST}:{port}/"
    print(f"魔方最短解应用 {APP_VERSION} 已启动: {url}", flush=True)
    if port != PORT:
        print(
            f"警告：默认端口 {PORT} 已被其他进程占用，可能仍有旧版服务在运行。"
            f"请使用上面的 {port} 端口，或停止旧进程后重新启动。",
            flush=True,
        )
    print("首次求解会生成 HTM 剪枝表，请耐心等待。按 Ctrl+C 停止。", flush=True)
    if open_browser:
        browser_timer = threading.Timer(0.4, webbrowser.open, args=(url,))
        browser_timer.daemon = True
        browser_timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


def create_server() -> tuple[ExclusiveThreadingHTTPServer, int]:
    for port in range(PORT, PORT + 20):
        try:
            return ExclusiveThreadingHTTPServer((HOST, port), AppHandler), port
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, 10048):
                raise
    raise OSError("没有找到可用端口。")


def write_port_file(port: int) -> None:
    cache_dir = ROOT / ".cache"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / "server_port.txt").write_text(f"http://{HOST}:{port}/", encoding="utf-8")


if __name__ == "__main__":
    main()
