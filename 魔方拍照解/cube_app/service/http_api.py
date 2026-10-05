"""HTTP transport; dependencies are supplied by the application facade."""

from __future__ import annotations

import socket
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from cube_app import __version__ as APP_VERSION


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class AppHandler(BaseHTTPRequestHandler):
    server_version = f"CubeOptimalApp/{APP_VERSION}"

    def do_GET(self) -> None:
        ctx = self.runtime
        parsed = ctx.urlparse(self.path)
        path = parsed.path
        if path == "/api/version":
            self._send_json({"ok": True, "version": ctx.APP_VERSION})
            return
        if path == "/api/capabilities":
            qtm_available = ctx.qtm_installed()
            self._send_json(
                {
                    "ok": True,
                    "HTM": True,
                    "QTM": qtm_available,
                    "QTM_status": "stable" if qtm_available else "unavailable",
                    "QTM_sizes": ctx.qtm_capabilities(),
                }
            )
            return
        if path.startswith("/api/solve/"):
            job_id = path.removeprefix("/api/solve/").strip("/")
            if job_id.startswith("qtm-"):
                if not ctx.qtm_module_installed():
                    self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
                    return
                from cube_app.solvers.qtm.backend import BACKEND

                snapshot = BACKEND.snapshot(job_id)
                self._send_json(
                    {"ok": True, **snapshot}
                    if snapshot is not None
                    else {"ok": False, "error": "求解任务不存在或已过期"},
                    status=200 if snapshot is not None else 404,
                )
                if snapshot is not None:
                    BACKEND.mark_http_return(
                        job_id, candidate_included=snapshot.get("candidate_result") is not None, initial=False
                    )
                return
            with ctx.JOBS_LOCK:
                job = ctx.JOBS.get(job_id)
                snapshot = (
                    None
                    if job is None
                    else {
                        key: value
                        for key, value in job.items()
                        if key not in {"created_at", "updated_at"} and (not key.startswith("_"))
                    }
                )
                if snapshot is not None:
                    snapshot["timing_events"] = list(job["timing_events"])
                    snapshot["timings"] = dict(job["timings"])
                if snapshot is not None and snapshot.get("status") == "queued":
                    queued = sorted(
                        (
                            (value.get("created_at", 0.0), key)
                            for key, value in ctx.JOBS.items()
                            if value.get("status") == "queued"
                        )
                    )
                    snapshot["queue_position"] = next(
                        (index + 1 for index, (_, key) in enumerate(queued) if key == job_id), 1
                    )
            if snapshot is None:
                self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
            else:
                self._send_json({"ok": True, **snapshot})
                ctx.mark_htm_http_return(
                    job_id,
                    candidate_included=snapshot.get("candidate_result") is not None
                    or snapshot.get("result") is not None,
                    initial=False,
                )
            return
        if path in ("", "/"):
            self._send_file(ctx.WEB_ROOT / "index.html")
            return
        candidate = (ctx.WEB_ROOT / path.lstrip("/")).resolve()
        if ctx.WEB_ROOT.resolve() not in candidate.parents and candidate != ctx.WEB_ROOT.resolve():
            self._send_json({"error": "Forbidden"}, status=403)
            return
        if candidate.exists() and candidate.is_file():
            self._send_file(candidate)
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        ctx = self.runtime
        parsed = ctx.urlparse(self.path)
        if parsed.path.startswith("/api/solve/") and parsed.path.endswith("/cancel"):
            job_id = parsed.path.removeprefix("/api/solve/").removesuffix("/cancel").strip("/")
            if job_id.startswith("qtm-"):
                if not ctx.qtm_module_installed():
                    self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
                    return
                from cube_app.solvers.qtm.backend import BACKEND

                snapshot = BACKEND.cancel(job_id)
                self._send_json(
                    {"ok": True, **snapshot}
                    if snapshot is not None
                    else {"ok": False, "error": "求解任务不存在或已过期"},
                    status=200 if snapshot is not None else 404,
                )
                return
            with ctx.JOBS_LOCK:
                job = ctx.JOBS.get(job_id)
                if job is None:
                    status = None
                else:
                    status = str(job.get("status", "queued"))
                    if status not in {"complete", "timeout", "error", "cancelled"}:
                        cancel_event = job.get("_cancel_event")
                        if isinstance(cancel_event, ctx.threading.Event):
                            cancel_event.set()
                        status = "cancelled"
                        job["status"] = status
                        job["message"] = "搜索已取消。"
                        job["updated_at"] = ctx.time.time()
                        ctx._record_job_event_locked(job, "terminal", status="cancelled")
                        job["_candidate_stop"].set()
                        job["_delivery_ready"].set()
            if status is None:
                self._send_json({"ok": False, "error": "求解任务不存在或已过期"}, status=404)
            else:
                self._send_json({"ok": True, "job_id": job_id, "status": status})
            return
        if parsed.path == "/api/detect":
            try:
                if (
                    ctx.decode_data_url is None
                    or ctx.DETECTION_PIPELINE is None
                    or ctx.assess_detected_face_quality is None
                ):
                    self._send_json({"ok": False, "error": "OpenCV 检测器不可用"}, status=503)
                    return
                payload = self._read_json()
                grid_size = int(payload.get("cube_size", 3))
                if grid_size not in (2, 3):
                    raise ValueError("cube_size 只能是 2 或 3。")
                image = ctx.decode_data_url(str(payload.get("image", "")))
                detection_batch = ctx.DETECTION_PIPELINE.detect(image, grid_size=grid_size, limit=3)
                candidates = detection_batch.candidates
                if not candidates:
                    self._send_json({"ok": True, "detected": False, "app_version": ctx.APP_VERSION})
                else:
                    self._send_json(
                        {
                            "ok": True,
                            "detected": True,
                            "corners": candidates[0].corners,
                            "confidence": candidates[0].confidence,
                            "method": candidates[0].method,
                            "score": candidates[0].score,
                            "quality": ctx.assess_detected_face_quality(image, candidates[0]),
                            "candidates": [
                                {
                                    "corners": candidate.corners,
                                    "confidence": candidate.confidence,
                                    "method": candidate.method,
                                    "score": candidate.score,
                                    "quality": ctx.assess_detected_face_quality(image, candidate),
                                }
                                for candidate in candidates
                            ],
                            "app_version": ctx.APP_VERSION,
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
        request_started = ctx.time.monotonic()
        try:
            payload = self._read_json()
            facelets = str(payload.get("facelets", ""))
            cube_size = int(payload.get("cube_size", 3))
            if cube_size not in (2, 3):
                raise ValueError("cube_size 只能是 2 或 3。")
            metric = str(payload.get("metric", "HTM")).upper()
            if metric not in {"HTM", "QTM"}:
                raise ValueError("metric 必须是 HTM 或 QTM。")
            default_depth = (11 if cube_size == 2 else 20) if metric == "HTM" else 14 if cube_size == 2 else 40
            max_depth = int(payload.get("max_depth", default_depth))
            if not 0 <= max_depth <= (20 if metric == "HTM" else 40):
                raise ValueError("max_depth 超出所选计步方式的范围。")
            timeout = payload.get("timeout_seconds", 180)
            timeout_seconds = None if timeout in (None, 0, "0", "none") else float(timeout)
            if timeout_seconds is not None and (
                not ctx.math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 3600
            ):
                raise ValueError("timeout_seconds 必须在 0.1 到 3600 秒之间。")
            deadline = None if timeout_seconds is None else request_started + timeout_seconds
            if metric == "QTM":
                if not ctx.qtm_module_installed() or (cube_size == 3 and (not ctx.qtm_installed())):
                    self._send_json(
                        {
                            "ok": False,
                            "metric": "QTM",
                            "error": "QTM 组件未安装，请按 README 生成运行表或使用完整便携包。",
                        },
                        status=503,
                    )
                    return
                from cube_app.solvers.qtm.backend import BACKEND, QtmUnavailable, QtmJobCapacityError

                try:
                    result = BACKEND.submit(facelets, cube_size, max_depth, timeout_seconds, started=request_started)
                except (QtmUnavailable, QtmJobCapacityError) as exc:
                    self._send_json({"ok": False, "metric": "QTM", "error": str(exc)}, status=503)
                    return
                self._send_json(result)
                if result.get("job_id"):
                    BACKEND.mark_http_return(result["job_id"], candidate_included=result.get("depth") is not None)
                return
            resource_wait_seconds = ctx.BROKER.enter_htm(deadline=deadline)
            htm_claimed = True
            ctx.remaining_seconds(deadline)
            if cube_size == 2:
                result = ctx.TWO_BY_TWO_SOLVER.solve_facelets(
                    facelets, max_depth=min(max_depth, 11), timeout_seconds=ctx.remaining_seconds(deadline)
                )
                self._send_json(
                    {
                        "ok": True,
                        **ctx.result_payload(result),
                        "proof_status": "complete",
                        "resource_wait_seconds": resource_wait_seconds,
                    }
                )
                return
            cube = ctx.from_facelets(facelets)
            if ctx.native_solver_available():
                candidate_enabled = not cube.is_solved()
                job_id, worker = ctx.prepare_optimal_job(
                    cube,
                    None,
                    max_depth,
                    timeout_seconds,
                    deadline=deadline,
                    started=request_started,
                    candidate_enabled=candidate_enabled,
                )
                ctx.start_optimal_job(job_id, worker)
                with ctx.JOBS_LOCK:
                    ready = ctx.JOBS[job_id]["_delivery_ready"]
                    serial_candidate = ctx.JOBS[job_id]["_serial_candidate"]
                # Keep the original quick-proof window. A one-thread request
                # serializes candidate generation before proof to avoid oversubscription.
                if not serial_candidate:
                    ready.wait(
                        min(
                            ctx.QUICK_OPTIMAL_PROBE_SECONDS,
                            ctx.remaining_seconds(deadline) or ctx.QUICK_OPTIMAL_PROBE_SECONDS,
                        )
                    )
                snapshot = ctx.job_snapshot(job_id)
                if candidate_enabled and snapshot["status"] not in ctx.TERMINAL_STATUSES:
                    ctx.start_candidate_job(job_id, cube)
                    ready.wait(ctx.remaining_seconds(deadline))
            else:
                probe_budget = min(
                    ctx.QUICK_OPTIMAL_PROBE_SECONDS, ctx.remaining_seconds(deadline) or ctx.QUICK_OPTIMAL_PROBE_SECONDS
                )
                probe_deadline = ctx.time.monotonic() + probe_budget
                try:
                    result = ctx.PROBE_SOLVER.solve_cube(
                        cube,
                        max_depth=max_depth,
                        timeout_seconds=probe_budget,
                        deadline=min(deadline, probe_deadline) if deadline else probe_deadline,
                    )
                except ctx.SearchTimeout:
                    result = None
                if result is not None:
                    self._send_json(
                        {
                            "ok": True,
                            **ctx.result_payload(result),
                            "engine": "python",
                            "proof_status": "complete",
                            "resource_wait_seconds": resource_wait_seconds,
                        }
                    )
                    return
                job_id, worker = ctx.prepare_optimal_job(
                    cube,
                    None,
                    max_depth,
                    timeout_seconds,
                    deadline=deadline,
                    started=request_started,
                    candidate_enabled=True,
                )
                ctx.start_optimal_job(job_id, worker)
                ctx.start_candidate_job(job_id, cube)
                with ctx.JOBS_LOCK:
                    ready = ctx.JOBS[job_id]["_delivery_ready"]
                ready.wait(ctx.remaining_seconds(deadline))
            snapshot = ctx.job_snapshot(job_id)
            quick_payload = snapshot.get("candidate_result")
            response = {
                "ok": True,
                "job_id": job_id,
                "proof_status": snapshot["status"],
                "optimal": False,
                "engine": snapshot["engine"],
                "solution_generation_seconds": snapshot.get("solution_generation_seconds", 0.0),
                "request_elapsed_seconds": round(ctx.time.monotonic() - request_started, 3),
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
            ctx.mark_htm_http_return(job_id, candidate_included=response.get("depth") is not None, initial=True)
        except ctx.JobCapacityError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=503)
        except (ctx.CubeStateError, ctx.SearchTimeout, TimeoutError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # pragma: no cover - keeps the local app friendly.
            self._send_json({"ok": False, "error": f"服务器内部错误：{exc}"}, status=500)
        finally:
            if htm_claimed:
                ctx.BROKER.leave_htm()

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict:
        ctx = self.runtime
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0:
            raise ValueError("Content-Length 不能为负数")
        if length > 25 * 1024 * 1024:
            raise ValueError("请求内容超过 25 MB")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        payload = ctx.json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求 JSON 必须是对象")
        return payload

    def _send_json(self, payload: dict, status: int = 200) -> None:
        ctx = self.runtime
        body = ctx.json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send_file(self, path: Path) -> None:
        ctx = self.runtime
        if path.suffix == ".html":
            body = path.read_text(encoding="utf-8").replace("__APP_VERSION__", ctx.APP_VERSION).encode("utf-8")
        else:
            body = path.read_bytes()
        content_type = ctx.mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif path.suffix in (".html", ".css"):
            content_type = f"{content_type}; charset=utf-8"
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Cube-App-Version", ctx.APP_VERSION)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
