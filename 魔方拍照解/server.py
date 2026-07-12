from __future__ import annotations

import json
import math
import mimetypes
import errno
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cube_app.cubie import CubeStateError, CubieCube, from_facelets
from cube_app.fast import FastTwoPhaseSolver
from cube_app.native import (
    NativeSolverCancelled,
    NativeSolverError,
    NativeSolverTimeout,
    solve_native,
)
from cube_app.optimal import OptimalSolver, SearchCancelled, SearchTimeout
from cube_app.two_by_two import TwoByTwoSolver

try:
    from cube_app.detection import DetectionPipeline
    from cube_app.vision import assess_detected_face_quality, decode_data_url
except ImportError:  # The browser detector remains available without OpenCV.
    DetectionPipeline = None
    assess_detected_face_quality = None
    decode_data_url = None


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
HOST = "127.0.0.1"
PORT = 8765
APP_VERSION = "2026.07.11.9"

SOLVER = OptimalSolver(ROOT / ".cache", parallel=True)
PROBE_SOLVER = OptimalSolver(ROOT / ".cache", parallel=False)
FAST_SOLVER = FastTwoPhaseSolver(ROOT / ".cache")
TWO_BY_TWO_SOLVER = TwoByTwoSolver()
QUICK_OPTIMAL_PROBE_SECONDS = 0.75
QUICK_SOLVE_SECONDS = 1.5
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
OPTIMAL_SEARCH_LOCK = threading.Lock()
MAX_JOBS = 100
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
) -> tuple[str, threading.Thread]:
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    with JOBS_LOCK:
        if len(JOBS) >= MAX_JOBS:
            terminal = [
                (key, value.get("updated_at", 0.0))
                for key, value in JOBS.items()
                if value.get("status") in {"complete", "timeout", "error", "cancelled"}
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
            "incumbent_depth": quick_result.depth if quick_result is not None else None,
        }

    proof_max_depth = min(max_depth, quick_result.depth) if quick_result is not None else max_depth
    upper_bound = quick_result.depth if quick_result is not None else None
    incumbent_moves = quick_result.moves if quick_result is not None else None
    thread = threading.Thread(
        target=run_optimal_job,
        args=(job_id, cube, proof_max_depth, timeout_seconds, upper_bound, incumbent_moves, cancel_event),
        name=f"cube-optimal-{job_id[:8]}",
        daemon=True,
    )
    return job_id, thread


def update_job(job_id: str, **values: object) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        job.update(values)
        job["updated_at"] = time.time()


def run_optimal_job(
    job_id: str,
    cube: CubieCube,
    max_depth: int,
    timeout_seconds: float | None,
    upper_bound: int | None = None,
    incumbent_moves: list[str] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    with OPTIMAL_SEARCH_LOCK:
        if cancel_event is not None and cancel_event.is_set():
            update_job(job_id, status="cancelled", message="搜索已取消。")
            return
        update_job(job_id, status="running")
        started = time.monotonic()
        try:
            def report_progress(progress: dict) -> None:
                update_job(job_id, progress=progress)

            if timeout_seconds is not None:
                try:
                    native_result = solve_native(
                        cube,
                        max_depth=max_depth,
                        timeout_seconds=timeout_seconds,
                        incumbent_moves=incumbent_moves,
                        cancel_event=cancel_event,
                        progress_callback=report_progress,
                    )
                except NativeSolverCancelled as exc:
                    raise SearchCancelled(str(exc)) from exc
                except NativeSolverTimeout as exc:
                    raise SearchTimeout(str(exc)) from exc
                except NativeSolverError:
                    native_result = None
                if native_result is not None:
                    if cancel_event is not None and cancel_event.is_set():
                        raise SearchCancelled("搜索已取消。")
                    update_job(job_id, status="complete", result=native_result)
                    return

            try:
                result = SOLVER.solve_cube(
                    cube,
                    max_depth=max_depth,
                    timeout_seconds=timeout_seconds,
                    upper_bound=upper_bound,
                    incumbent_moves=incumbent_moves,
                    cancel_event=cancel_event,
                    progress_callback=report_progress,
                )
            except PermissionError:
                remaining = None
                if timeout_seconds is not None:
                    remaining = max(0.0, timeout_seconds - (time.monotonic() - started))
                    if remaining == 0.0:
                        raise SearchTimeout("搜索超时。")
                result = PROBE_SOLVER.solve_cube(
                    cube,
                    max_depth=max_depth,
                    timeout_seconds=remaining,
                    upper_bound=upper_bound,
                    incumbent_moves=incumbent_moves,
                    cancel_event=cancel_event,
                    progress_callback=report_progress,
                )
            if cancel_event is not None and cancel_event.is_set():
                raise SearchCancelled("搜索已取消。")
            update_job(job_id, status="complete", result=result_payload(result))
        except SearchCancelled as exc:
            update_job(job_id, status="cancelled", message=str(exc))
        except SearchTimeout as exc:
            update_job(job_id, status="timeout", message=str(exc))
        except Exception as exc:  # pragma: no cover - background safety net.
            update_job(job_id, status="error", message=str(exc))


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "CubeOptimalApp/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/solve/"):
            job_id = path.removeprefix("/api/solve/").strip("/")
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                snapshot = None if job is None else {
                    key: value
                    for key, value in job.items()
                    if key not in {"created_at", "updated_at"} and not key.startswith("_")
                }
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
                    if status not in {"complete", "timeout", "error", "cancelled"}:
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
                self._send_json({"ok": True, "job_id": job_id, "status": status})
            return
        if parsed.path == "/api/detect":
            try:
                if (
                    decode_data_url is None
                    or DETECTION_PIPELINE is None
                    or assess_detected_face_quality is None
                ):
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
        try:
            payload = self._read_json()
            facelets = str(payload.get("facelets", ""))
            cube_size = int(payload.get("cube_size", 3))
            if cube_size not in (2, 3):
                raise ValueError("cube_size 只能是 2 或 3。")
            max_depth = int(payload.get("max_depth", 11 if cube_size == 2 else 20))
            if not 0 <= max_depth <= 20:
                raise ValueError("max_depth 必须在 0 到 20 之间。")
            timeout = payload.get("timeout_seconds", 180)
            timeout_seconds = None if timeout in (None, 0, "0", "none") else float(timeout)
            if timeout_seconds is not None and (
                not math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 3600
            ):
                raise ValueError("timeout_seconds 必须在 0.1 到 3600 秒之间。")
            if cube_size == 2:
                result = TWO_BY_TWO_SOLVER.solve_facelets(
                    facelets,
                    max_depth=min(max_depth, 11),
                    timeout_seconds=timeout_seconds,
                )
                self._send_json({"ok": True, **result_payload(result), "proof_status": "complete"})
                return

            cube = from_facelets(facelets)

            shared_tables = PROBE_SOLVER.tables
            if SOLVER._tables is None:
                SOLVER._tables = shared_tables
            if FAST_SOLVER._tables is None:
                FAST_SOLVER._tables = shared_tables

            probe_seconds = QUICK_OPTIMAL_PROBE_SECONDS
            if timeout_seconds is not None:
                probe_seconds = min(probe_seconds, timeout_seconds)
            try:
                result = PROBE_SOLVER.solve_cube(cube, max_depth=max_depth, timeout_seconds=probe_seconds)
            except SearchTimeout:
                result = None

            if result is not None:
                self._send_json({"ok": True, **result_payload(result), "proof_status": "complete"})
                return

            quick_seconds = QUICK_SOLVE_SECONDS
            if timeout_seconds is not None:
                quick_seconds = min(quick_seconds, max(0.1, timeout_seconds - probe_seconds))
            try:
                quick_result = FAST_SOLVER.solve_cube(cube, timeout_seconds=quick_seconds)
            except SearchTimeout:
                quick_result = None

            job_id, thread = prepare_optimal_job(cube, quick_result, max_depth, timeout_seconds)
            thread.start()
            response = {
                "ok": True,
                "job_id": job_id,
                "proof_status": "queued",
                "optimal": False,
            }
            if quick_result is not None:
                response.update(result_payload(quick_result))
            else:
                response.update(
                    {
                        "moves": [],
                        "solution": "",
                        "depth": None,
                        "metric": "HTM",
                        "elapsed_seconds": round(probe_seconds + quick_seconds, 3),
                        "message": "快速搜索暂未找到解法，正在后台继续严格搜索。",
                    }
                )
            self._send_json(response)
        except JobCapacityError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=503)
        except (CubeStateError, SearchTimeout, TimeoutError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # pragma: no cover - keeps the local app friendly.
            self._send_json({"ok": False, "error": f"服务器内部错误：{exc}"}, status=500)

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


def main() -> None:
    server, port = create_server()
    write_port_file(port)
    print(f"魔方最短解应用 {APP_VERSION} 已启动: http://{HOST}:{port}/", flush=True)
    if port != PORT:
        print(
            f"警告：默认端口 {PORT} 已被其他进程占用，可能仍有旧版服务在运行。"
            f"请使用上面的 {port} 端口，或停止旧进程后重新启动。",
            flush=True,
        )
    print("首次求解会生成 HTM 剪枝表，请耐心等待。按 Ctrl+C 停止。", flush=True)
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
