"""Optional QTM request backend, loaded only for QTM HTTP requests."""

from __future__ import annotations

import threading
import time
import uuid

from ...cubie import from_facelets
from ...metrics import resolve_max_depth, solution_cost
from ...runtime import application_root
from ..resource_broker import BROKER
from . import native


class QtmUnavailable(RuntimeError):
    pass


class QtmBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    @staticmethod
    def available() -> bool:
        return native.native_solver_available()

    def _update(self, job_id: str, **changes: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(changes)

    def snapshot(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {key: value for key, value in job.items() if not key.startswith("_")}

    def cancel(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job["status"] not in {"complete", "timeout", "cancelled", "error", "budget_exhausted"}:
                job["_cancel"].set()
                job["status"] = "cancelled"
                job["message"] = "搜索已取消。"
            return {key: value for key, value in job.items() if not key.startswith("_")}

    def submit(self, facelets: str, cube_size: int, max_depth: int | None, timeout: float) -> dict:
        if not self.available():
            raise QtmUnavailable("QTM 实验组件未安装或基础表不完整。")
        max_depth = resolve_max_depth(cube_size, "QTM", max_depth)
        if cube_size == 2:
            from .two_by_two import TwoByTwoSolver
            cancel = threading.Event()
            deadline = time.monotonic() + timeout
            if not BROKER.acquire_qtm(cancel, cancel.set, deadline):
                raise TimeoutError("QTM 二阶请求排队超时。")
            try:
                result = TwoByTwoSolver(application_root() / ".cache" / "qtm").solve_facelets(
                    facelets, max_depth=max_depth,
                    timeout_seconds=max(0.1, deadline - time.monotonic()),
                    metric="QTM", cancel_event=cancel,
                )
            finally:
                BROKER.release_qtm()
            return {
                "ok": True, "metric": "QTM", "moves": result.moves, "solution": result.text,
                "depth": result.depth, "cost": result.depth, "optimal": True,
                "proof_status": "complete", "engine_id": "qtm-python-2x2",
                "engine_version": "c01d90d", "asset_profile": "exact-2x2",
            }
        cube = from_facelets(facelets)
        started = time.monotonic()
        deadline = started + timeout
        job_id = "qtm-" + uuid.uuid4().hex
        cancel = threading.Event()
        job = {
            "job_id": job_id, "metric": "QTM", "status": "queued", "optimal": False,
            "candidate_result": None, "result": None, "progress": None,
            "engine_id": "qtm-native", "engine_version": "c01d90d",
            "asset_profile": "pending", "queue_seconds": None, "startup_seconds": None,
            "base_ready_seconds": None, "strong_ready_seconds": None,
            "first_candidate_seconds": None, "proof_wall_seconds": None,
            "request_elapsed_seconds": 0.0, "_cancel": cancel, "_deadline": deadline,
            "_started": started,
        }
        with self._lock:
            self._jobs[job_id] = job
        worker = threading.Thread(
            target=self._run, args=(job_id, cube, max_depth), name=f"qtm-{job_id[-8:]}",
            daemon=True,
        )
        worker.start()
        # A short probe allows easy requests to return a candidate without delaying long proofs.
        worker.join(timeout=min(0.75, timeout))
        snapshot = self.snapshot(job_id)
        assert snapshot is not None
        response = {
            "ok": True, "job_id": job_id, "metric": "QTM",
            "proof_status": snapshot["status"], "optimal": snapshot["optimal"],
            "engine": snapshot["engine_id"], "engine_id": snapshot["engine_id"],
            "engine_version": snapshot["engine_version"],
            "asset_profile": snapshot["asset_profile"],
            "request_elapsed_seconds": time.monotonic() - started,
        }
        if snapshot["result"] is not None:
            response.update(snapshot["result"])
        elif snapshot["candidate_result"] is not None:
            response.update(snapshot["candidate_result"])
        else:
            response.update(moves=[], solution="", depth=None, cost=None)
        return response

    def _run(self, job_id: str, cube, max_depth: int) -> None:
        with self._lock:
            job = self._jobs[job_id]
            cancel = job["_cancel"]
            deadline = job["_deadline"]
            started = job["_started"]
        acquired = BROKER.acquire_qtm(cancel, native.force_yield, deadline)
        if not acquired:
            self._update(job_id, status="cancelled" if cancel.is_set() else "timeout")
            return
        admitted = time.monotonic()
        self._update(job_id, status="running", queue_seconds=admitted - started)

        def progress(event: dict) -> None:
            now = time.monotonic()
            if event.get("type") == "candidate":
                moves = event["moves"]
                candidate = {
                    "moves": moves, "solution": " ".join(moves),
                    "depth": solution_cost(moves, "QTM"), "cost": solution_cost(moves, "QTM"),
                    "metric": "QTM", "optimal": False, "status": "candidate",
                }
                with self._lock:
                    job = self._jobs[job_id]
                    existing = job.get("candidate_result")
                    if existing is None or candidate["cost"] < existing["cost"]:
                        job["candidate_result"] = candidate
                    if job["first_candidate_seconds"] is None:
                        job["first_candidate_seconds"] = now - started
            elif event.get("type") == "asset_ready":
                self._update(job_id, strong_ready_seconds=now - started,
                             asset_profile=event.get("profile", "unknown"))
            else:
                self._update(job_id, progress=event, asset_profile=event.get("asset_profile", "pending"))

        try:
            result = native.solve_native(
                cube, max_depth=max_depth, timeout_seconds=max(0.1, deadline - time.monotonic()),
                incumbent_moves=None, cancel_event=cancel, threads=BROKER.threads,
                progress_callback=progress, deadline=deadline, metric="QTM",
            )
            if result is None:
                raise native.NativeSolverError("QTM native service unavailable")
            if cancel.is_set():
                self._update(job_id, status="cancelled")
                return
            status = "complete" if result["optimal"] else result.get("status", "budget_exhausted")
            self._update(
                job_id, status=status, optimal=result["optimal"],
                result={**result, "cost": result["depth"], "engine_id": "qtm-native",
                        "engine_version": "c01d90d"},
            )
        except native.NativeSolverTimeout:
            self._update(job_id, status="timeout")
        except native.NativeSolverCancelled:
            self._update(job_id, status="cancelled")
        except Exception as exc:
            if cancel.is_set():
                self._update(job_id, status="cancelled", message=str(exc))
            else:
                self._python_fallback(job_id, cube, max_depth, deadline, cancel, exc)
        finally:
            diagnostics = native.service_diagnostics()
            ready_assets = diagnostics.get("assets") or {}
            qtm_assets = ready_assets.get("QTM") or {}
            queue_seconds = admitted - started
            base_duration = diagnostics.get("base_initialization_seconds")
            strong_elapsed = diagnostics.get("strong_ready_elapsed_seconds")
            startup_duration = diagnostics.get("client_startup_seconds")
            if strong_elapsed is None and qtm_assets.get("strong") and startup_duration is not None:
                strong_elapsed = startup_duration
            self._update(
                job_id,
                startup_seconds=startup_duration,
                base_ready_seconds=(queue_seconds + base_duration if base_duration is not None else None),
                strong_ready_seconds=(queue_seconds + strong_elapsed if strong_elapsed is not None else None),
                asset_profile=qtm_assets.get("profile", "unavailable"),
            )
            self._update(job_id, proof_wall_seconds=time.monotonic() - admitted,
                         request_elapsed_seconds=time.monotonic() - started)
            try:
                native.force_yield()
            finally:
                BROKER.release_qtm()
                native.release_assets()

    def _python_fallback(self, job_id, cube, max_depth, deadline, cancel, native_error) -> None:
        from .optimal import OptimalSolver, SearchCancelled, SearchTimeout

        self._update(job_id, engine_id="qtm-python", message=f"native fallback: {native_error}")
        try:
            result = OptimalSolver(application_root() / ".cache" / "qtm", parallel=False).solve_cube(
                cube, max_depth=max_depth, deadline=deadline, cancel_event=cancel, metric="QTM"
            )
            self._update(
                job_id, status="complete", optimal=True,
                result={
                    "moves": result.moves, "solution": result.text, "depth": result.depth,
                    "cost": result.depth, "metric": "QTM", "optimal": True,
                    "engine_id": "qtm-python", "engine_version": "c01d90d",
                },
            )
        except SearchTimeout:
            self._update(job_id, status="timeout")
        except SearchCancelled:
            self._update(job_id, status="cancelled")
        except Exception as exc:
            self._update(job_id, status="error", message=str(exc))


BACKEND = QtmBackend()
