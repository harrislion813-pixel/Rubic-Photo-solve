"""HTM job ownership, candidate publication and observable lifecycle."""

from __future__ import annotations

import threading
from cube_app.cubie import CubieCube
from .dependencies import Dependencies


def prepare_optimal_job(
    ctx: Dependencies,
    cube: CubieCube,
    quick_result,
    max_depth: int,
    timeout_seconds: float | None,
    *,
    deadline: float | None = None,
    started: float | None = None,
    candidate_enabled: bool = False,
) -> tuple[str, threading.Thread]:
    created = ctx.time.monotonic() if started is None else started
    if deadline is None and timeout_seconds is not None:
        deadline = created + timeout_seconds
    state_key = (ctx.to_facelets(cube), max_depth, "HTM", 1)
    job_id = ctx.uuid.uuid4().hex
    cancel_event = ctx.threading.Event()
    with ctx.JOBS_LOCK:
        for existing_id, existing in ctx.JOBS.items():
            if existing.get("_state_key") == state_key and existing.get("status") in {"queued", "running"}:
                return (existing_id, existing["_worker"])
        if len(ctx.JOBS) >= ctx.MAX_JOBS:
            terminal = [
                (key, value.get("updated_at", 0.0))
                for key, value in ctx.JOBS.items()
                if value.get("status") in {"complete", "timeout", "error", "cancelled"}
                and (not value["_worker"].is_alive())
                and (not (value.get("_candidate_worker") and value["_candidate_worker"].is_alive()))
            ]
            remove_count = len(ctx.JOBS) - ctx.MAX_JOBS + 1
            for key, _ in sorted(terminal, key=lambda item: item[1])[:remove_count]:
                ctx.JOBS.pop(key, None)
        if len(ctx.JOBS) >= ctx.MAX_JOBS:
            raise ctx.JobCapacityError("后台求解任务过多，请取消旧任务后重试。")
        # Retain one broker for this job even if the facade is replaced later.
        broker = ctx.BROKER
        ctx.JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": ctx.time.time(),
            "updated_at": ctx.time.time(),
            "_cancel_event": cancel_event,
            "_broker": broker,
            "incumbent_depth": quick_result.depth if quick_result is not None else None,
            "_state_key": state_key,
            "_deadline": deadline,
            "_started_at": created,
            "_done": ctx.threading.Event(),
            "_delivery_ready": ctx.threading.Event(),
            "_candidate_stop": ctx.threading.Event(),
            "_generation_done": ctx.threading.Event(),
            "_proof_lease": ctx.threading.Event(),
            "_serial_candidate": candidate_enabled and broker.threads == 1,
            "_proof_threads": max(1, broker.threads - int(candidate_enabled and broker.threads > 1)),
            "_incumbent_moves": quick_result.moves if quick_result is not None else None,
            "engine": "pending",
            "solution_generation_seconds": 0.0,
            "timing_events": [],
            "timings": {},
            "thread_quota": broker.threads,
            "candidate_thread_quota": int(candidate_enabled),
            "candidate_search_running": False,
            "early_candidate_delivery": ctx.os.environ.get("CUBE_HTM_EARLY_CANDIDATE", "off").lower()
            in {"1", "true", "on"},
        }
        if not candidate_enabled:
            ctx.JOBS[job_id]["_generation_done"].set()
        ctx.JOBS[job_id]["proof_threads"] = ctx.JOBS[job_id]["_proof_threads"]
        ctx._record_job_event_locked(ctx.JOBS[job_id], "request_created", at=created)
        if quick_result is not None:
            ctx.JOBS[job_id]["candidate_result"] = ctx.result_payload(quick_result)
            ctx.JOBS[job_id]["_delivery_ready"].set()
        proof_max_depth = min(max_depth, quick_result.depth) if quick_result is not None else max_depth
        upper_bound = quick_result.depth if quick_result is not None else None
        incumbent_moves = quick_result.moves if quick_result is not None else None
        thread = ctx.threading.Thread(
            target=ctx.run_optimal_job,
            args=(job_id, cube, proof_max_depth, timeout_seconds, upper_bound, incumbent_moves, cancel_event, deadline),
            name=f"cube-optimal-{job_id[:8]}",
            daemon=True,
        )
        ctx.JOBS[job_id]["_worker"] = thread
        return (job_id, thread)


def start_optimal_job(ctx: Dependencies, job_id: str, worker: threading.Thread) -> None:
    with ctx.JOBS_LOCK:
        if not ctx.JOBS[job_id].get("_started"):
            ctx.JOBS[job_id]["_started"] = True
            if worker.ident is None:
                worker.start()


def _record_job_event_locked(ctx: Dependencies, job: dict, event: str, *, at: float | None = None, **values) -> None:
    """Raw request-relative events; monotonic timestamps are never rounded."""
    at = ctx.time.monotonic() if at is None else at
    elapsed = at - job["_started_at"]
    job["timing_events"].append({"event": event, "monotonic": at, "elapsed_seconds": elapsed, **values})
    job["timings"].setdefault(event + "_seconds", elapsed)


def record_job_event(ctx: Dependencies, job_id: str, event: str, **values) -> None:
    with ctx.JOBS_LOCK:
        job = ctx.JOBS.get(job_id)
        if job is not None:
            ctx._record_job_event_locked(job, event, **values)


def job_snapshot(ctx: Dependencies, job_id: str) -> dict | None:
    with ctx.JOBS_LOCK:
        job = ctx.JOBS.get(job_id)
        if job is None:
            return None
        snapshot = {
            key: value
            for key, value in job.items()
            if key not in {"created_at", "updated_at"} and (not key.startswith("_"))
        }
        snapshot["timing_events"] = list(job["timing_events"])
        snapshot["timings"] = dict(job["timings"])
        return snapshot


def mark_htm_http_return(ctx: Dependencies, job_id: str, *, candidate_included: bool, initial: bool) -> None:
    with ctx.JOBS_LOCK:
        job = ctx.JOBS.get(job_id)
        if job is None:
            return
        event = "http_initial_return" if initial else "http_poll_return"
        ctx._record_job_event_locked(job, event, candidate_included=candidate_included)
        if candidate_included:
            job["timings"].setdefault("first_candidate_http_seconds", ctx.time.monotonic() - job["_started_at"])


def publish_htm_candidate(
    ctx: Dependencies,
    job_id: str,
    expected_job: dict,
    cube: CubieCube,
    result,
    *,
    publish: bool = True,
    record_generated: bool = True,
) -> bool:
    generated_at = ctx.time.monotonic()
    moves = list(result.moves)
    verified = cube
    for move in moves:
        if move not in ctx.MOVE_INDEX:
            raise ValueError("HTM 候选包含未知动作。")
        verified = verified.apply_move_index(ctx.MOVE_INDEX[move])
    if not verified.is_solved() or result.metric != "HTM" or result.depth != len(moves):
        raise ValueError("HTM 候选动作回放或计步不正确。")
    with ctx.JOBS_LOCK:
        job = ctx.JOBS.get(job_id)
        if job is not expected_job:
            return False
        deadline = job["_deadline"]
        if (
            job["status"] in ctx.TERMINAL_STATUSES
            or job["_cancel_event"].is_set()
            or job["_candidate_stop"].is_set()
            or (deadline is not None and ctx.time.monotonic() >= deadline)
        ):
            return False
        if record_generated:
            ctx._record_job_event_locked(
                job,
                "candidate_generated",
                at=generated_at,
                cost=len(moves),
                moves=moves,
                solver_elapsed_seconds=result.elapsed_seconds,
            )
        internal = job.get("_incumbent_moves")
        if internal is None or len(moves) < len(internal):
            job["_incumbent_moves"] = moves
            job["incumbent_depth"] = len(moves)
            ctx._record_job_event_locked(job, "candidate_upper_bound_available", cost=len(moves), moves=moves)
        if not publish:
            return True
        previous = (job.get("candidate_result") or {}).get("depth")
        if previous is not None and len(moves) >= previous:
            return False
        job["candidate_result"] = {**ctx.result_payload(result), "moves": moves}
        job["solution_generation_seconds"] = round(generated_at - job.get("_candidate_started_at", generated_at), 3)
        job["updated_at"] = ctx.time.time()
        ctx._record_job_event_locked(job, "candidate_published", cost=len(moves), moves=moves)
        job["_delivery_ready"].set()
        return True


def start_candidate_job(ctx: Dependencies, job_id: str, cube: CubieCube) -> bool:
    with ctx.JOBS_LOCK:
        job = ctx.JOBS.get(job_id)
        if job is None or job.get("_generator_started") or job["status"] in ctx.TERMINAL_STATUSES:
            return False
        job["_generator_started"] = True
        stop = job["_candidate_stop"]
        deadline = job["_deadline"]

        def generate() -> None:
            generation_started = ctx.time.monotonic()
            claimed = False
            try:
                # Only the job owning the proof slot may spend the candidate
                # allowance. This also makes restoring its full proof quota safe.
                while not job["_proof_lease"].wait(0.05):
                    if stop.is_set():
                        raise ctx.SearchCancelled("快速两阶段搜索已取消。")
                    ctx.remaining_seconds(deadline)
                job["_broker"].enter_htm(deadline=deadline, cancel_event=stop)
                claimed = True
                with ctx.JOBS_LOCK:
                    if ctx.JOBS.get(job_id) is job:
                        job["candidate_search_running"] = True
                        job["_candidate_started_at"] = ctx.time.monotonic()
                ctx.record_job_event(job_id, "candidate_search_started")
                early = job["early_candidate_delivery"]
                result = ctx.generate_quick_solution(
                    cube,
                    deadline,
                    cancel_event=stop,
                    candidate_callback=lambda result: ctx.publish_htm_candidate(
                        job_id, job, cube, result, publish=early
                    ),
                )
                if result is not None and (not early):
                    # Preserve the default policy: publish the best result only
                    # after the same candidate budget has finished.
                    ctx.publish_htm_candidate(job_id, job, cube, result, record_generated=False)
            except (ctx.SearchTimeout, ctx.SearchCancelled, TimeoutError, ctx.ResourceCancelled):
                pass
            except Exception as exc:  # Candidate failure leaves the independent proof running.
                ctx.logging.warning("HTM 候选搜索失败: %s", exc)
                with ctx.JOBS_LOCK:
                    if ctx.JOBS.get(job_id) is job:
                        job["candidate_error"] = str(exc)
            finally:
                with ctx.JOBS_LOCK:
                    if ctx.JOBS.get(job_id) is job:
                        job["solution_generation_seconds"] = round(ctx.time.monotonic() - generation_started, 3)
                        job["candidate_search_running"] = False
                        ctx._record_job_event_locked(job, "candidate_search_finished")
                        job["_generation_done"].set()
                        job["_delivery_ready"].set()
                if claimed:
                    job["_broker"].leave_htm()

        candidate_worker = ctx.threading.Thread(target=generate, name=f"cube-candidate-{job_id[:8]}", daemon=True)
        job["_candidate_worker"] = candidate_worker
        candidate_worker.start()
        return True


def update_job(ctx: Dependencies, job_id: str, **values: object) -> None:
    with ctx.JOBS_LOCK:
        job = ctx.JOBS.get(job_id)
        if job is None:
            return
        if job["status"] in ctx.TERMINAL_STATUSES:
            return
        job.update(values)
        job["updated_at"] = ctx.time.time()
        if job["status"] in ctx.TERMINAL_STATUSES:
            ctx._record_job_event_locked(
                job,
                "terminal",
                status=job["status"],
                result=job.get("result"),
                native_pid=job.get("native_pid"),
                peak_working_set_bytes=job.get("peak_working_set_bytes"),
                memory_scope=job.get("memory_scope"),
            )
            job["_candidate_stop"].set()
            job["_delivery_ready"].set()
