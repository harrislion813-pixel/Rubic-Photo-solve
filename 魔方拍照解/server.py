from __future__ import annotations

import json
import math
import logging
import os
import mimetypes
import errno
import socket
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cube_app import __version__
from cube_app.cubie import CubeStateError, CubieCube, MOVE_NAMES, from_facelets, to_facelets
from cube_app.fast import FastTwoPhaseSolver
from cube_app.metrics import normalize_metric, resolve_max_depth, solution_cost
from cube_app.native import (
    NativeSolverCancelled,
    NativeSolverError,
    NativeSolverTimeout,
    native_solver_available,
    native_qtm_candidate_available,
    solve_native,
)
from cube_app.optimal import OptimalSolver, SearchCancelled, SearchTimeout, SolveResult
from cube_app.runtime import application_root
from cube_app.two_by_two import TwoByTwoSolver

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

SOLVER = OptimalSolver(ROOT / ".cache", parallel=True)
PROBE_SOLVER = OptimalSolver(ROOT / ".cache", parallel=False)
FAST_SOLVER = FastTwoPhaseSolver(ROOT / ".cache")
TWO_BY_TWO_SOLVER = TwoByTwoSolver()
QUICK_OPTIMAL_PROBE_SECONDS = 0.75
QUICK_SOLVE_SECONDS = 1.5
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
OPTIMAL_SEARCH_LOCK = threading.Lock()
QUICK_SEARCH_LOCK = threading.Lock()
MAX_JOBS = 100
PROOF_VERSION = 3
DETECTION_PIPELINE = DetectionPipeline() if DetectionPipeline is not None else None


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
    metric: str = "HTM",
    dedupe: bool = True,
) -> tuple[str, threading.Thread]:
    metric = normalize_metric(metric)
    max_depth = resolve_max_depth(3, metric, max_depth)
    if quick_result is not None:
        quick_result = candidate_for_metric(quick_result, metric)
    created = time.monotonic()
    if deadline is None and timeout_seconds is not None:
        deadline = created + timeout_seconds
    state_key = (to_facelets(cube), 3, max_depth, metric, PROOF_VERSION)
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    with JOBS_LOCK:
        if dedupe:
            for existing_id, existing in JOBS.items():
                if existing.get("_state_key") == state_key and existing.get("status") in {"queued", "running"}:
                    return existing_id, existing["_worker"]
        if len(JOBS) >= MAX_JOBS:
            terminal = [
                (key, value.get("updated_at", 0.0))
                for key, value in JOBS.items()
                if value.get("status") in {"complete", "timeout", "error", "cancelled", "budget_exhausted"}
                and not value["_worker"].is_alive()
            ]
            remove_count = len(JOBS) - MAX_JOBS + 1
            for key, _ in sorted(terminal, key=lambda item: item[1])[:remove_count]:
                JOBS.pop(key, None)
        if len(JOBS) >= MAX_JOBS:
            raise JobCapacityError("后台求解任务过多，请取消旧任务后重试。")
        JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "metric": metric,
            "cube_size": 3,
            "max_depth": max_depth,
            "proof_version": PROOF_VERSION,
            "created_at": time.time(),
            "updated_at": time.time(),
            "_cancel_event": cancel_event,
            "incumbent_depth": quick_result.depth if quick_result is not None else None,
            "_state_key": state_key,
            "_deadline": deadline,
            "_started_at": created,
            "_done": threading.Event(),
            "_incumbent_moves": quick_result.moves if quick_result is not None else None,
            "engine": "pending",
            "solution_generation_seconds": 0.0,
        }
        if quick_result is not None:
            JOBS[job_id]["candidate_result"] = result_payload(quick_result)

        proof_max_depth = min(max_depth, quick_result.depth) if quick_result is not None else max_depth
        upper_bound = quick_result.depth if quick_result is not None else None
        incumbent_moves = quick_result.moves if quick_result is not None else None
        thread = threading.Thread(
            target=run_optimal_job,
            args=(job_id, cube, proof_max_depth, timeout_seconds, upper_bound, incumbent_moves, cancel_event, deadline,
                  metric),
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


def candidate_for_metric(result, metric: str) -> SolveResult:
    """The HTM two-phase generator supplies a feasible bound in either metric."""
    return SolveResult(list(result.moves), solution_cost(result.moves, metric), metric,
                       result.elapsed_seconds, not result.moves)


def generate_quick_solution(cube: CubieCube, deadline: float | None, metric: str = "HTM",
                            *, force_python: bool = False):
    if metric == "QTM" and native_qtm_candidate_available() and not force_python:
        return None  # The native proof request publishes QTM candidates as they improve.
    while not QUICK_SEARCH_LOCK.acquire(timeout=0.05):
        remaining_seconds(deadline)
    try:
        if FAST_SOLVER._tables is None and PROBE_SOLVER._tables is not None:
            FAST_SOLVER._tables = PROBE_SOLVER._tables
        budget = min(QUICK_SOLVE_SECONDS, remaining_seconds(deadline) or QUICK_SOLVE_SECONDS)
        return candidate_for_metric(FAST_SOLVER.solve_cube(cube, timeout_seconds=budget, metric=metric), metric)
    finally:
        QUICK_SEARCH_LOCK.release()


def update_job(job_id: str, **values: object) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        job.update(values)
        job["updated_at"] = time.time()


def update_job_candidate(job_id: str, result) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        candidate = candidate_for_metric(result, job["metric"])
        previous = job.get("incumbent_depth")
        if previous is None or candidate.depth < previous:
            job.update(_incumbent_moves=candidate.moves, incumbent_depth=candidate.depth,
                       candidate_result=result_payload(candidate), updated_at=time.time())
            if job.get("first_candidate_seconds") is None:
                job["first_candidate_seconds"] = round(time.monotonic() - job["_started_at"], 3)


def run_optimal_job(
    job_id: str,
    cube: CubieCube,
    max_depth: int,
    timeout_seconds: float | None,
    upper_bound: int | None = None,
    incumbent_moves: list[str] | None = None,
    cancel_event: threading.Event | None = None,
    deadline: float | None = None,
    metric: str = "HTM",
) -> None:
    metric = normalize_metric(metric)
    started = time.monotonic()
    if deadline is None and timeout_seconds is not None:
        deadline = started + timeout_seconds
    acquired = False
    try:
        while not acquired:
            if cancel_event is not None and cancel_event.is_set():
                raise SearchCancelled("搜索已取消。")
            remaining_seconds(deadline)
            acquired = OPTIMAL_SEARCH_LOCK.acquire(timeout=0.05)
        if cancel_event is not None and cancel_event.is_set():
            raise SearchCancelled("搜索已取消。")
        update_job(job_id, status="running")

        def report_progress(progress: dict) -> None:
            if progress.get("type") == "candidate":
                update_job_candidate(job_id, SolveResult(progress["moves"], progress["cost"], metric,
                                                         time.monotonic() - started, False))
                if progress.get("asset_profile"):
                    update_job(job_id, asset_profile=progress["asset_profile"])
                return
            update_job(job_id, progress={**progress, "metric": metric}, engine=progress.get("engine", "python"),
                       asset_profile=progress.get("asset_profile", "python"))

        def incumbent_provider() -> list[str] | None:
            with JOBS_LOCK:
                return JOBS.get(job_id, {}).get("_incumbent_moves", incumbent_moves)

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
                threads=min(32, max(1, (os.cpu_count() or 1) - 1)),
                metric=metric,
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
            status = "complete" if native_result["optimal"] else "budget_exhausted"
            update_job(job_id, status=status, result=native_result)
            return
        update_job(job_id, engine="python")
        if metric == "QTM" and incumbent_provider() is None and (
            deadline is None or deadline - time.monotonic() > 1.0
        ):
            try:
                fallback_candidate = generate_quick_solution(cube, deadline, metric, force_python=True)
            except SearchTimeout:
                fallback_candidate = None
            if fallback_candidate is not None:
                update_job_candidate(job_id, fallback_candidate)
        with JOBS_LOCK:
            if "fallback_reason" not in JOBS.get(job_id, {}):
                update_reason = "原生程序或必需的 PDB 文件不可用。"
            else:
                update_reason = None
        if update_reason:
            update_job(job_id, fallback_reason=update_reason)
        incumbent_moves = incumbent_provider()
        upper_bound = solution_cost(incumbent_moves, metric) if incumbent_moves else upper_bound

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
                metric=metric,
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
                metric=metric,
            )
        if cancel_event is not None and cancel_event.is_set():
            raise SearchCancelled("搜索已取消。")
        status = "complete" if result.optimal else "budget_exhausted"
        update_job(job_id, status=status, result={**result_payload(result), "engine": "python",
                                                  "asset_profile": "python"})
    except SearchCancelled as exc:
        update_job(job_id, status="cancelled", message=str(exc))
    except SearchTimeout as exc:
        update_job(job_id, status="timeout", message=str(exc))
    except CubeStateError as exc:
        # Input has already passed from_facelets validation before this worker.
        update_job(job_id, status="budget_exhausted", message=str(exc))
    except Exception as exc:  # pragma: no cover - background safety net.
        update_job(job_id, status="error", message=str(exc))
    finally:
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
        if path.startswith("/api/solve/"):
            job_id = path.removeprefix("/api/solve/").strip("/")
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
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if job is None:
                    status = None
                else:
                    status = str(job.get("status", "queued"))
                    if status not in {"complete", "timeout", "error", "cancelled", "budget_exhausted"}:
                        cancel_event = job.get("_cancel_event")
                        if isinstance(cancel_event, threading.Event):
                            cancel_event.set()
                        status = "cancelled"
                        job["status"] = status
                        job["message"] = "搜索已取消。"
                        job["updated_at"] = time.time()
            if status is None:
                self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
            else:
                self._send_json({"ok": True, "job_id": job_id, "status": status, "metric": job["metric"]})
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
        metric = "HTM"
        try:
            payload = self._read_json()
            facelets = str(payload.get("facelets", ""))
            metric = normalize_metric(payload.get("metric", "HTM"))
            cube_size = int(payload.get("cube_size", 3))
            if cube_size not in (2, 3):
                raise ValueError("cube_size 只能是 2 或 3。")
            max_depth = resolve_max_depth(cube_size, metric, payload.get("max_depth"))
            timeout = payload.get("timeout_seconds", 180)
            timeout_seconds = None if timeout in (None, 0, "0", "none") else float(timeout)
            if timeout_seconds is not None and (
                not math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 3600
            ):
                raise ValueError("timeout_seconds 必须在 0.1 到 3600 秒之间。")
            if cube_size == 2:
                result = TWO_BY_TWO_SOLVER.solve_facelets(
                    facelets,
                    max_depth=max_depth,
                    timeout_seconds=timeout_seconds,
                    metric=metric,
                )
                self._send_json({"ok": True, **result_payload(result), "proof_status": "complete"})
                return

            cube = from_facelets(facelets)

            if max_depth <= 1:
                shallow_moves = [] if cube.is_solved() else [
                    MOVE_NAMES[move] for move in range(18)
                    if solution_cost([move], metric) <= max_depth and cube.apply_move_index(move).is_solved()
                ]
                if cube.is_solved() or shallow_moves:
                    moves = [] if cube.is_solved() else [shallow_moves[0]]
                    direct = SolveResult(moves, solution_cost(moves, metric), metric, 0.0, True)
                    self._send_json({"ok": True, **result_payload(direct), "engine": "direct",
                                     "asset_profile": "direct", "proof_status": "complete"})
                    return
                job_id, _ = prepare_optimal_job(cube, None, max_depth, timeout_seconds, metric=metric,
                                                dedupe=False)
                exhausted = {"moves": [], "solution": "", "depth": None, "metric": metric,
                             "optimal": False, "elapsed_seconds": 0.0, "engine": "direct",
                             "asset_profile": "direct"}
                with JOBS_LOCK:
                    job = JOBS[job_id]
                    job.update(status="budget_exhausted", result=exhausted, engine="direct",
                               proof_elapsed_seconds=0.0, _started=True)
                    job["_done"].set()
                self._send_json({"ok": True, "job_id": job_id, "proof_status": "budget_exhausted",
                                 "max_depth": max_depth, **exhausted})
                return

            request_started = time.monotonic()
            deadline = None if timeout_seconds is None else request_started + timeout_seconds
            quick_result = None
            if native_solver_available():
                job_id, worker = prepare_optimal_job(cube, None, max_depth, timeout_seconds, deadline=deadline,
                                                     metric=metric)
                start_optimal_job(job_id, worker)
                with JOBS_LOCK:
                    done = JOBS[job_id]["_done"]
                done.wait(min(QUICK_OPTIMAL_PROBE_SECONDS, timeout_seconds or QUICK_OPTIMAL_PROBE_SECONDS))
                with JOBS_LOCK:
                    snapshot = dict(JOBS[job_id])
                    generate = not snapshot.get("_generator_started") and snapshot["status"] in {"queued", "running"}
                    if generate:
                        JOBS[job_id]["_generator_started"] = True
                if snapshot["status"] == "complete":
                    self._send_json(
                        {
                            "ok": True,
                            **snapshot["result"],
                            "proof_status": "complete",
                            "solution_generation_seconds": 0.0,
                            "proof_elapsed_seconds": snapshot.get("proof_elapsed_seconds", 0.0),
                        }
                    )
                    return
                if generate:
                    generation_started = time.monotonic()
                    try:
                        quick_result = generate_quick_solution(cube, deadline, metric)
                    except SearchTimeout:
                        pass
                    generation_seconds = round(time.monotonic() - generation_started, 3)
                    if quick_result is not None:
                        update_job_candidate(job_id, quick_result)
                    update_job(job_id, solution_generation_seconds=generation_seconds)
                    if quick_result is None and metric == "QTM" and native_qtm_candidate_available():
                        probe_remaining = 0.2 if deadline is None else max(0.0, min(0.2, deadline - time.monotonic()))
                        done.wait(probe_remaining)
                with JOBS_LOCK:
                    snapshot = dict(JOBS[job_id])
                if snapshot["status"] == "complete":
                    self._send_json(
                        {
                            "ok": True,
                            **snapshot["result"],
                            "proof_status": "complete",
                            "solution_generation_seconds": snapshot["solution_generation_seconds"],
                            "proof_elapsed_seconds": snapshot.get("proof_elapsed_seconds", 0.0),
                        }
                    )
                    return
                quick_payload = snapshot.get("result") or snapshot.get("candidate_result")
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
                        metric=metric,
                    )
                except SearchTimeout:
                    result = None
                except CubeStateError as exc:
                    self._send_json({
                        "ok": True, "metric": metric, "max_depth": max_depth,
                        "moves": [], "solution": "", "depth": None, "optimal": False,
                        "engine": "python", "asset_profile": "python",
                        "proof_status": "budget_exhausted", "message": str(exc),
                    })
                    return
                if result is not None:
                    self._send_json(
                        {"ok": True, **result_payload(result), "engine": "python", "asset_profile": "python",
                         "proof_status": "complete"}
                    )
                    return
                try:
                    quick_result = generate_quick_solution(cube, deadline, metric)
                except SearchTimeout:
                    pass
                job_id, worker = prepare_optimal_job(cube, quick_result, max_depth, timeout_seconds, deadline=deadline,
                                                     metric=metric)
                start_optimal_job(job_id, worker)
                with JOBS_LOCK:
                    snapshot = dict(JOBS[job_id])
                quick_payload = result_payload(quick_result) if quick_result else None
            response = {
                "ok": True,
                "job_id": job_id,
                "proof_status": snapshot["status"],
                "optimal": False,
                "metric": metric,
                "max_depth": max_depth,
                "engine": snapshot["engine"],
                "asset_profile": snapshot.get("asset_profile") or (snapshot.get("result") or {}).get("asset_profile"),
                "solution_generation_seconds": snapshot.get("solution_generation_seconds", 0.0),
                "first_candidate_seconds": snapshot.get("first_candidate_seconds"),
                "request_elapsed_seconds": round(time.monotonic() - request_started, 3),
            }
            if quick_payload:
                response.update(quick_payload)
                response["optimal"] = False
            else:
                response.update(
                    {
                        "moves": [],
                        "solution": "",
                        "depth": None,
                        "metric": metric,
                        "elapsed_seconds": 0.0,
                        "message": "正在后台严格搜索。",
                    }
                )
            self._send_json(response)
        except JobCapacityError as exc:
            self._send_json({"ok": False, "error": str(exc), "metric": metric}, status=503)
        except (CubeStateError, SearchTimeout, TimeoutError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc), "metric": metric}, status=400)
        except Exception as exc:  # pragma: no cover - keeps the local app friendly.
            self._send_json({"ok": False, "error": f"服务器内部错误：{exc}", "metric": metric}, status=500)

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
