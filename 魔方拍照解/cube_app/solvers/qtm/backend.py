"""Optional QTM request backend, loaded only for QTM HTTP requests."""

from __future__ import annotations

import threading
import time
import uuid

from ... import __version__
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

    def submit(
        self, facelets: str, cube_size: int, max_depth: int | None, timeout: float | None,
        *, started: float | None = None,
    ) -> dict:
        started = time.monotonic() if started is None else started
        deadline = None if timeout is None else started + timeout
        if not self.available():
            raise QtmUnavailable("QTM 实验组件未安装或基础表不完整。")
        max_depth = resolve_max_depth(cube_size, "QTM", max_depth)
        if cube_size == 2:
            from .two_by_two import TwoByTwoSolver
            from .optimal import SearchCancelled, SearchTimeout
            cancel = threading.Event()
            if not BROKER.acquire_qtm(cancel, cancel.set, deadline):
                raise TimeoutError("QTM 二阶请求排队超时。")
            try:
                result = TwoByTwoSolver(application_root() / ".cache" / "qtm").solve_facelets(
                    facelets, max_depth=max_depth,
                    timeout_seconds=self._remaining(deadline),
                    metric="QTM", cancel_event=cancel,
                )
            except (SearchCancelled, SearchTimeout) as exc:
                raise TimeoutError(str(exc)) from exc
            finally:
                BROKER.release_qtm()
            return {
                "ok": True, "metric": "QTM", "moves": result.moves, "solution": result.text,
                "depth": result.depth, "cost": result.depth, "optimal": True,
                "proof_status": "complete", "engine_id": "qtm-python-2x2",
                "engine_version": __version__, "asset_profile": "exact-2x2",
            }
        cube = from_facelets(facelets)
        job_id = "qtm-" + uuid.uuid4().hex
        cancel = threading.Event()
        job = {
            "job_id": job_id, "metric": "QTM", "status": "queued", "optimal": False,
            "candidate_result": None, "result": None, "progress": None,
            "engine_id": "qtm-native", "engine_version": __version__,
            "asset_profile": "pending", "ready_asset_profile": "pending",
            "queue_seconds": None, "startup_seconds": None,
            "base_ready_seconds": None, "strong_ready_seconds": None, "tail_ready_seconds": None,
            "strong_adopted_seconds": None, "tail_adopted_seconds": None,
            "search_started_seconds": None, "first_candidate_seconds": None,
            "native_search_seconds": None, "proof_wall_seconds": None,
            "native_proof_busy_seconds": None,
            "resource_hold_seconds": None, "python_fallback_seconds": None,
            "http_return_seconds": None, "candidate_delivery_seconds": None,
            "request_elapsed_seconds": 0.0, "_cancel": cancel, "_deadline": deadline,
            "_started": started, "_response_ready": threading.Event(), "_done": threading.Event(),
        }
        with self._lock:
            self._jobs[job_id] = job
        worker = threading.Thread(
            target=self._run, args=(job_id, cube, max_depth), name=f"qtm-{job_id[-8:]}",
            daemon=True,
        )
        worker.start()
        # Deliver a verified candidate as soon as it arrives, even while proof continues.
        wait_budget = 0.75 if deadline is None else min(0.75, max(0.0, deadline - time.monotonic()))
        job["_response_ready"].wait(timeout=wait_budget)
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

    @staticmethod
    def _remaining(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("QTM request deadline expired")
        return remaining

    def mark_http_return(self, job_id: str, *, candidate_included: bool = True, initial: bool = True) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            elapsed = time.monotonic() - job["_started"]
            if initial:
                job["http_return_seconds"] = elapsed
            candidate_ready = job["first_candidate_seconds"]
            if candidate_included and candidate_ready is not None and job["candidate_delivery_seconds"] is None:
                job["candidate_delivery_seconds"] = elapsed - candidate_ready

    def _run(self, job_id: str, cube, max_depth: int) -> None:
        with self._lock:
            job = self._jobs[job_id]
            cancel = job["_cancel"]
            deadline = job["_deadline"]
            started = job["_started"]
        acquired = BROKER.acquire_qtm(cancel, native.force_yield, deadline)
        if not acquired:
            self._update(job_id, status="cancelled" if cancel.is_set() else "timeout",
                         request_elapsed_seconds=time.monotonic() - started)
            job["_done"].set()
            job["_response_ready"].set()
            return
        admitted = time.monotonic()
        self._update(job_id, status="running", queue_seconds=admitted - started)

        def progress(event: dict) -> None:
            now = time.monotonic()
            if event.get("type") == "engine_ready":
                with self._lock:
                    job = self._jobs[job_id]
                    job["startup_seconds"] = event.get("client_request_startup_seconds", event.get("client_startup_seconds"))
                    process_started = event.get("client_process_started_at")
                    if process_started is not None:
                        for stage in ("base", "strong", "tail"):
                            elapsed = event.get(stage + "_ready_elapsed_seconds")
                            if elapsed is not None and job[stage + "_ready_seconds"] is None:
                                job[stage + "_ready_seconds"] = max(0.0, process_started + elapsed - started)
                    job["asset_profile"] = event.get("assets", {}).get("QTM", {}).get("profile", "pending")
                    job["ready_asset_profile"] = job["asset_profile"]
            elif event.get("type") == "candidate":
                moves = event["moves"]
                candidate = {
                    "moves": moves, "solution": " ".join(moves),
                    "depth": solution_cost(moves, "QTM"), "cost": solution_cost(moves, "QTM"),
                    "metric": "QTM", "optimal": False, "status": "candidate",
                    "asset_profile": event.get("asset_profile"),
                }
                with self._lock:
                    job = self._jobs[job_id]
                    existing = job.get("candidate_result")
                    if existing is None or candidate["cost"] < existing["cost"]:
                        job["candidate_result"] = candidate
                    if job["first_candidate_seconds"] is None:
                        job["first_candidate_seconds"] = now - started
                    job["_response_ready"].set()
            elif event.get("type") == "asset_ready":
                stage = event.get("stage")
                if stage in {"base", "strong", "tail"}:
                    with self._lock:
                        job = self._jobs[job_id]
                        field = stage + "_ready_seconds"
                        if job[field] is None:
                            job[field] = now - started
                        job["ready_asset_profile"] = event.get("profile", job["ready_asset_profile"])
            elif event.get("type") == "asset_adopted":
                with self._lock:
                    job = self._jobs[job_id]
                    for stage, present in (("strong", event.get("strong")), ("tail", event.get("tail_depth", 0) > 0)):
                        field = stage + "_adopted_seconds"
                        if present and job[field] is None:
                            job[field] = now - started
                    job["asset_profile"] = event.get("profile", job["asset_profile"])
            else:
                self._update(job_id, progress=event)
                if event.get("type") == "progress" and event.get("asset_profile"):
                    self._update(job_id, asset_profile=event["asset_profile"])

        try:
            result = native.solve_native(
                cube, max_depth=max_depth, timeout_seconds=self._remaining(deadline),
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
                asset_profile=result.get("asset_profile", "unknown"),
                native_search_seconds=result.get("elapsed_seconds"),
                proof_wall_seconds=result.get("elapsed_seconds"),
                result={**result, "cost": result["depth"], "engine_id": "qtm-native",
                        "engine_version": __version__},
            )
        except (native.NativeSolverTimeout, TimeoutError):
            self._update(job_id, status="timeout")
        except native.NativeSolverCancelled:
            self._update(job_id, status="cancelled")
        except native.NativeSolverResourceLimit as exc:
            self._update(job_id, status="error", message=str(exc))
        except Exception as exc:
            if cancel.is_set():
                self._update(job_id, status="cancelled", message=str(exc))
            else:
                self._python_fallback(job_id, cube, max_depth, deadline, cancel, exc)
        finally:
            diagnostics = native.service_diagnostics()
            with self._lock:
                job = self._jobs[job_id]
                job["startup_seconds"] = diagnostics.get("client_request_startup_seconds", diagnostics.get("client_startup_seconds"))
                process_started = diagnostics.get("client_process_started_at")
                if process_started is not None:
                    for stage in ("base", "strong", "tail"):
                        elapsed = diagnostics.get(stage + "_ready_elapsed_seconds")
                        field = stage + "_ready_seconds"
                        if elapsed is not None and job[field] is None:
                            job[field] = max(0.0, process_started + elapsed - started)
                search_started = diagnostics.get("client_search_started_at")
                if search_started is not None:
                    job["search_started_seconds"] = search_started - started
                if job["native_search_seconds"] is None:
                    job["native_search_seconds"] = diagnostics.get("native_search_seconds")
                    job["proof_wall_seconds"] = diagnostics.get("native_search_seconds")
                job["native_proof_busy_seconds"] = diagnostics.get("native_proof_busy_seconds")
            retained = False
            try:
                if not cancel.is_set() and job['engine_id'] == 'qtm-native' and job['status'] != 'error':
                    retained = native.retain_assets()
                if not retained:
                    native.release_assets()
                job['resident_retained'] = retained
                job['residency'] = native.service_diagnostics()
            finally:
                self._update(job_id, resource_hold_seconds=time.monotonic() - admitted,
                             request_elapsed_seconds=time.monotonic() - started)
                if retained:
                    BROKER.release_qtm(native.resident_callback(BROKER))
                else:
                    BROKER.release_qtm()
                job["_done"].set()
                job["_response_ready"].set()

    def _python_fallback(self, job_id, cube, max_depth, deadline, cancel, native_error) -> None:
        from .optimal import OptimalSolver, SearchCancelled, SearchTimeout

        self._update(job_id, engine_id="qtm-python", message=f"native fallback: {native_error}")
        fallback_started = time.monotonic()
        try:
            result = OptimalSolver(application_root() / ".cache" / "qtm", parallel=False).solve_cube(
                cube, max_depth=max_depth, timeout_seconds=self._remaining(deadline),
                deadline=deadline, cancel_event=cancel, metric="QTM"
            )
            self._update(
                job_id, status="complete", optimal=True,
                result={
                    "moves": result.moves, "solution": result.text, "depth": result.depth,
                    "cost": result.depth, "metric": "QTM", "optimal": True,
                    "engine_id": "qtm-python", "engine_version": __version__,
                },
            )
        except (SearchTimeout, TimeoutError):
            self._update(job_id, status="timeout")
        except SearchCancelled:
            self._update(job_id, status="cancelled")
        except Exception as exc:
            self._update(job_id, status="error", message=str(exc))
        finally:
            self._update(job_id, python_fallback_seconds=time.monotonic() - fallback_started)


BACKEND = QtmBackend()
