"""Application startup and compatible facade for HTTP and job services.

Existing callers may replace module-level dependencies. The runtime view reads
this namespace at invocation time; jobs retain their admitted broker instance.
"""

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
from cube_app.service import http_api as _http, jobs as _jobs, solving as _solving
from cube_app.service.dependencies import Dependencies

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
FAST_SOLVER = FastTwoPhaseSolver(ROOT / ".cache" / "htm", native_policy="six")
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
_runtime = Dependencies(globals())
__all__ = [
    "APP_VERSION",
    "AppHandler",
    "BROKER",
    "BaseHTTPRequestHandler",
    "CubeStateError",
    "CubieCube",
    "DETECTION_PIPELINE",
    "DetectionPipeline",
    "ExclusiveThreadingHTTPServer",
    "FAST_SOLVER",
    "FastTwoPhaseSolver",
    "HOST",
    "JOBS",
    "JOBS_LOCK",
    "JobCapacityError",
    "MAX_JOBS",
    "MOVE_INDEX",
    "NativeSolverCancelled",
    "NativeSolverError",
    "NativeSolverTimeout",
    "OPTIMAL_SEARCH_LOCK",
    "OptimalSolver",
    "PORT",
    "PROBE_SOLVER",
    "Path",
    "QUICK_OPTIMAL_PROBE_SECONDS",
    "QUICK_SEARCH_LOCK",
    "QUICK_SOLVE_SECONDS",
    "ROOT",
    "ResourceCancelled",
    "SOLVER",
    "SearchCancelled",
    "SearchTimeout",
    "TERMINAL_STATUSES",
    "TWO_BY_TWO_SOLVER",
    "ThreadingHTTPServer",
    "TwoByTwoSolver",
    "WEB_ROOT",
    "annotations",
    "application_root",
    "assess_detected_face_quality",
    "create_server",
    "decode_data_url",
    "errno",
    "from_facelets",
    "generate_quick_solution",
    "importlib",
    "job_snapshot",
    "json",
    "logging",
    "main",
    "mark_htm_http_return",
    "math",
    "mimetypes",
    "native_solver_available",
    "os",
    "prepare_optimal_job",
    "publish_htm_candidate",
    "qtm_capabilities",
    "qtm_installed",
    "qtm_module_installed",
    "record_job_event",
    "remaining_seconds",
    "result_payload",
    "run_optimal_job",
    "socket",
    "solve_native",
    "start_candidate_job",
    "start_optimal_job",
    "threading",
    "time",
    "to_facelets",
    "update_job",
    "urlparse",
    "uuid",
    "webbrowser",
    "write_port_file",
]


def qtm_installed() -> bool:
    return _solving.qtm_installed(_runtime)


def qtm_module_installed() -> bool:
    return _solving.qtm_module_installed(_runtime)


def qtm_capabilities() -> dict:
    return _solving.qtm_capabilities(_runtime)


class JobCapacityError(RuntimeError):
    """Raised when no more background proof jobs can be retained."""


def result_payload(result) -> dict:
    return _solving.result_payload(_runtime, result)


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
    return _jobs.prepare_optimal_job(
        _runtime,
        cube,
        quick_result,
        max_depth,
        timeout_seconds,
        deadline=deadline,
        started=started,
        candidate_enabled=candidate_enabled,
    )


def start_optimal_job(job_id: str, worker: threading.Thread) -> None:
    return _jobs.start_optimal_job(_runtime, job_id, worker)


def remaining_seconds(deadline: float | None) -> float | None:
    return _solving.remaining_seconds(_runtime, deadline)


def generate_quick_solution(
    cube: CubieCube, deadline: float | None, *, candidate_callback=None, cancel_event: threading.Event | None = None
):
    return _solving.generate_quick_solution(
        _runtime, cube, deadline, candidate_callback=candidate_callback, cancel_event=cancel_event
    )


def _record_job_event_locked(job: dict, event: str, *, at: float | None = None, **values) -> None:
    return _jobs._record_job_event_locked(_runtime, job, event, at=at, **values)


def record_job_event(job_id: str, event: str, **values) -> None:
    return _jobs.record_job_event(_runtime, job_id, event, **values)


def job_snapshot(job_id: str) -> dict | None:
    return _jobs.job_snapshot(_runtime, job_id)


def mark_htm_http_return(job_id: str, *, candidate_included: bool, initial: bool) -> None:
    return _jobs.mark_htm_http_return(_runtime, job_id, candidate_included=candidate_included, initial=initial)


def publish_htm_candidate(
    job_id: str, expected_job: dict, cube: CubieCube, result, *, publish: bool = True, record_generated: bool = True
) -> bool:
    return _jobs.publish_htm_candidate(
        _runtime, job_id, expected_job, cube, result, publish=publish, record_generated=record_generated
    )


def start_candidate_job(job_id: str, cube: CubieCube) -> bool:
    return _jobs.start_candidate_job(_runtime, job_id, cube)


def update_job(job_id: str, **values: object) -> None:
    return _jobs.update_job(_runtime, job_id, **values)


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
    return _solving.run_optimal_job(
        _runtime, job_id, cube, max_depth, timeout_seconds, upper_bound, incumbent_moves, cancel_event, deadline
    )


ExclusiveThreadingHTTPServer = _http.ExclusiveThreadingHTTPServer


class AppHandler(_http.AppHandler):
    runtime = _runtime


def main(*, open_browser: bool = False) -> None:
    server, port = create_server()
    write_port_file(port)
    url = f"http://{HOST}:{port}/"
    print(f"魔方最短解应用 {APP_VERSION} 已启动: {url}", flush=True)
    if port != PORT:
        print(
            f"警告：默认端口 {PORT} 已被其他进程占用，可能仍有旧版服务在运行。请使用上面的 {port} 端口，或停止旧进程后重新启动。",
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
            return (ExclusiveThreadingHTTPServer((HOST, port), AppHandler), port)
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
