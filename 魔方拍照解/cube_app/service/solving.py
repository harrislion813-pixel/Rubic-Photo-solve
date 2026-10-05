"""HTM proof/candidate orchestration and QTM capability discovery."""

from __future__ import annotations

import threading
from cube_app.cubie import CubieCube
from .dependencies import Dependencies


def qtm_installed(ctx: Dependencies) -> bool:
    assets = ctx.ROOT / "assets" / "qtm" / "v1"
    return (
        (ctx.ROOT / "native" / "qtm" / "build" / "cube_solver_qtm.exe").is_file()
        and (assets / "corner_qtm_v3.pdb").is_file()
        and (assets / "phase1_qtm_v3.pdb").is_file()
    )


def qtm_module_installed(ctx: Dependencies) -> bool:
    try:
        return ctx.importlib.util.find_spec("cube_app.solvers.qtm") is not None
    except (ImportError, ValueError):
        return False


def qtm_capabilities(ctx: Dependencies) -> dict:
    assets = ctx.ROOT / "assets" / "qtm" / "v1"
    exact = ctx.ROOT / ".cache" / "qtm" / "two_by_two_qtm_v1.bin"
    return {
        "2": {
            "available": ctx.qtm_module_installed(),
            "profile": "exact-2x2",
            "asset_state": "unverified" if exact.is_file() else "not_loaded",
            "adopted_profile": None,
        },
        "3": {
            "available": ctx.qtm_installed(),
            "base_asset_state": "unverified" if ctx.qtm_installed() else "missing",
            "strong_asset_state": "unverified"
            if any(((assets / name).is_file() for name in ("strong_qtm_v4_nibble.pdb", "strong_qtm_v3.pdb")))
            else "missing",
            "adopted_profile": None,
        },
    }


def result_payload(ctx: Dependencies, result) -> dict:
    return {
        "moves": result.moves,
        "solution": result.text,
        "depth": result.depth,
        "metric": result.metric,
        "optimal": result.optimal,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
    }


def remaining_seconds(ctx: Dependencies, deadline: float | None) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - ctx.time.monotonic()
    if remaining <= 0:
        raise ctx.SearchTimeout("搜索超时。")
    return remaining


def generate_quick_solution(
    ctx: Dependencies,
    cube: CubieCube,
    deadline: float | None,
    *,
    candidate_callback=None,
    cancel_event: threading.Event | None = None,
):
    while not ctx.QUICK_SEARCH_LOCK.acquire(timeout=0.05):
        if cancel_event is not None and cancel_event.is_set():
            raise ctx.SearchCancelled("快速两阶段搜索已取消。")
        ctx.remaining_seconds(deadline)
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise ctx.SearchCancelled("快速两阶段搜索已取消。")
        if ctx.FAST_SOLVER._tables is None and ctx.PROBE_SOLVER._tables is not None:
            ctx.FAST_SOLVER._tables = ctx.PROBE_SOLVER._tables
        budget = min(ctx.QUICK_SOLVE_SECONDS, ctx.remaining_seconds(deadline) or ctx.QUICK_SOLVE_SECONDS)
        return ctx.FAST_SOLVER.solve_cube(
            cube,
            timeout_seconds=budget,
            candidate_callback=candidate_callback,
            cancel_event=cancel_event,
            deadline=deadline,
        )
    finally:
        ctx.QUICK_SEARCH_LOCK.release()


def run_optimal_job(
    ctx: Dependencies,
    job_id: str,
    cube: CubieCube,
    max_depth: int,
    timeout_seconds: float | None,
    upper_bound: int | None = None,
    incumbent_moves: list[str] | None = None,
    cancel_event: threading.Event | None = None,
    deadline: float | None = None,
) -> None:
    started = ctx.time.monotonic()
    if deadline is None and timeout_seconds is not None:
        deadline = started + timeout_seconds
    acquired = False
    htm_claimed = False
    job = None
    broker = ctx.BROKER
    try:
        with ctx.JOBS_LOCK:
            job = ctx.JOBS[job_id]
            broker = job["_broker"]
            generation_done = job["_generation_done"]
            serial_candidate = job["_serial_candidate"]
            proof_threads = job["_proof_threads"]
        broker.enter_htm(deadline=deadline, cancel_event=cancel_event)
        htm_claimed = True
        while not acquired:
            if cancel_event is not None and cancel_event.is_set():
                raise ctx.SearchCancelled("搜索已取消。")
            ctx.remaining_seconds(deadline)
            acquired = ctx.OPTIMAL_SEARCH_LOCK.acquire(timeout=0.05)
        if cancel_event is not None and cancel_event.is_set():
            raise ctx.SearchCancelled("搜索已取消。")
        job["_proof_lease"].set()
        if serial_candidate:
            ctx.record_job_event(job_id, "proof_waiting_for_candidate", threads=proof_threads)
            while not generation_done.wait(0.05):
                if cancel_event is not None and cancel_event.is_set():
                    raise ctx.SearchCancelled("搜索已取消。")
                ctx.remaining_seconds(deadline)
        ctx.update_job(job_id, status="running")
        ctx.record_job_event(job_id, "proof_started", threads=proof_threads)

        def report_progress(progress: dict) -> None:
            values = {"progress": progress, "engine": progress.get("engine", "python")}
            if "threads" in progress:
                values["proof_threads"] = progress["threads"]
            ctx.update_job(job_id, **values)
            ctx.record_job_event(job_id, "proof_progress", progress=dict(progress))

        def incumbent_provider() -> list[str] | None:
            with ctx.JOBS_LOCK:
                current = ctx.JOBS.get(job_id)
                if current is not job or current["status"] in ctx.TERMINAL_STATUSES:
                    return None
                moves = current.get("_incumbent_moves", incumbent_moves)
                return None if moves is None else list(moves)

        def report_native_event(event: dict) -> None:
            details = dict(event)
            kind = str(details.pop("type"))
            with ctx.JOBS_LOCK:
                current = ctx.JOBS.get(job_id)
                if current is job:
                    if details.get("native_pid") is not None:
                        current["native_pid"] = details["native_pid"]
                    if details.get("peak_working_set_bytes") is not None:
                        current["peak_working_set_bytes"] = max(
                            current.get("peak_working_set_bytes", 0), details["peak_working_set_bytes"]
                        )
                        current["memory_scope"] = details["memory_scope"]
            ctx.record_job_event(job_id, kind, **details)

        def proof_threads_provider() -> int | None:
            with ctx.JOBS_LOCK:
                current = ctx.JOBS.get(job_id)
                if (
                    current is not job
                    or current["status"] in ctx.TERMINAL_STATUSES
                    or current["_cancel_event"].is_set()
                    or (deadline is not None and ctx.time.monotonic() >= deadline)
                ):
                    return None
                return current["thread_quota"] if current["_generation_done"].is_set() else proof_threads

        def guard_thread_update(send) -> bool:
            # Commit the protocol write under the terminal/cancel state lock,
            # closing the provider-to-write race.
            with ctx.JOBS_LOCK:
                current = ctx.JOBS.get(job_id)
                if (
                    current is not job
                    or current["status"] in ctx.TERMINAL_STATUSES
                    or current["_cancel_event"].is_set()
                    or (deadline is not None and ctx.time.monotonic() >= deadline)
                ):
                    return False
                send()
                return True

        try:
            ctx.update_job(job_id, engine="native-cpp")
            native_result = ctx.solve_native(
                cube,
                max_depth=max_depth,
                timeout_seconds=ctx.remaining_seconds(deadline),
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
        except ctx.NativeSolverCancelled as exc:
            raise ctx.SearchCancelled(str(exc)) from exc
        except ctx.NativeSolverTimeout as exc:
            raise ctx.SearchTimeout(str(exc)) from exc
        except ctx.NativeSolverError as exc:
            ctx.logging.warning("原生求解失败，使用剩余预算回退 Python: %s", exc)
            ctx.update_job(job_id, fallback_reason=str(exc))
            native_result = None
        if native_result is not None:
            if cancel_event is not None and cancel_event.is_set():
                raise ctx.SearchCancelled("搜索已取消。")
            ctx.update_job(job_id, status="complete", result=native_result)
            return
        ctx.update_job(job_id, engine="python")
        with ctx.JOBS_LOCK:
            if "fallback_reason" not in ctx.JOBS.get(job_id, {}):
                update_reason = "原生程序或必需的 PDB 文件不可用。"
            else:
                update_reason = None
        if update_reason:
            ctx.update_job(job_id, fallback_reason=update_reason)
        incumbent_moves = incumbent_provider()
        upper_bound = len(incumbent_moves) if incumbent_moves else upper_bound
        original_workers = ctx.SOLVER.max_workers
        ctx.SOLVER.max_workers = min(original_workers, proof_threads)
        try:
            try:
                result = ctx.SOLVER.solve_cube(
                    cube,
                    max_depth=max_depth,
                    timeout_seconds=ctx.remaining_seconds(deadline),
                    deadline=deadline,
                    upper_bound=upper_bound,
                    incumbent_moves=incumbent_moves,
                    cancel_event=cancel_event,
                    progress_callback=report_progress,
                )
            except PermissionError:
                result = ctx.PROBE_SOLVER.solve_cube(
                    cube,
                    max_depth=max_depth,
                    timeout_seconds=ctx.remaining_seconds(deadline),
                    deadline=deadline,
                    upper_bound=upper_bound,
                    incumbent_moves=incumbent_moves,
                    cancel_event=cancel_event,
                    progress_callback=report_progress,
                )
        finally:
            ctx.SOLVER.max_workers = original_workers
        if cancel_event is not None and cancel_event.is_set():
            raise ctx.SearchCancelled("搜索已取消。")
        ctx.update_job(job_id, status="complete", result={**ctx.result_payload(result), "engine": "python"})
    except (ctx.SearchCancelled, ctx.ResourceCancelled) as exc:
        ctx.update_job(job_id, status="cancelled", message=str(exc))
    except (ctx.SearchTimeout, TimeoutError) as exc:
        ctx.update_job(job_id, status="timeout", message=str(exc))
    except Exception as exc:  # pragma: no cover - background safety net.
        ctx.update_job(job_id, status="error", message=str(exc))
    finally:
        if job is not None:
            job["_candidate_stop"].set()
            candidate_worker = job.get("_candidate_worker")
            if candidate_worker is not None and candidate_worker.ident is not None:
                candidate_worker.join()
        if htm_claimed:
            broker.leave_htm()
        if acquired:
            ctx.OPTIMAL_SEARCH_LOCK.release()
        with ctx.JOBS_LOCK:
            job = ctx.JOBS.get(job_id)
            if job is not None:
                job["proof_elapsed_seconds"] = round(ctx.time.monotonic() - started, 3)
                job["_done"].set()
