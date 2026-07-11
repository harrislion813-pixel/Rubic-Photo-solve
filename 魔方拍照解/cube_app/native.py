from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from .cubie import CubieCube, MOVE_INDEX, to_facelets


ROOT = Path(__file__).resolve().parents[1]
NATIVE_ROOT = ROOT / "native"
NATIVE_EXE = NATIVE_ROOT / "build" / "cube_solver.exe"
NATIVE_CACHE = ROOT / ".cache" / "native"
CORNER_PDB = NATIVE_CACHE / "corner_htm_v2.pdb"
PHASE1_PDB = NATIVE_CACHE / "phase1_sym_htm_v2.pdb"
EDGE_PDB_A = NATIVE_CACHE / "edge_a_htm_v2.pdb"
EDGE_PDB_B = NATIVE_CACHE / "edge_b_htm_v2.pdb"
EDGE_PDB_C = NATIVE_CACHE / "edge_c_htm_v2.pdb"
EDGE_PDB_D = NATIVE_CACHE / "edge_d_htm_v2.pdb"
EDGE_PDB_E = NATIVE_CACHE / "edge_e_htm_v2.pdb"
EDGE_PDB_F = NATIVE_CACHE / "edge_f_htm_v2.pdb"
EDGE_PDB_G = NATIVE_CACHE / "edge_g_htm_v2.pdb"
EDGE_PDB_H = NATIVE_CACHE / "edge_h_htm_v2.pdb"
TAIL_PDB = NATIVE_CACHE / "tail_depth6_v2.pdb"


class NativeSolverError(RuntimeError):
    pass


class NativeSolverCancelled(NativeSolverError):
    pass


class NativeSolverTimeout(NativeSolverError):
    pass


def native_solver_available() -> bool:
    return NATIVE_EXE.is_file() and all(path.is_file() for path in (CORNER_PDB, PHASE1_PDB))


def solve_native(
    cube: CubieCube,
    *,
    max_depth: int,
    timeout_seconds: float,
    incumbent_moves: list[str] | None,
    cancel_event: threading.Event | None,
    threads: int | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict | None:
    if not native_solver_available():
        return None

    worker_count = threads or min(32, max(1, (os.cpu_count() or 1) - 1))
    command = [
        str(NATIVE_EXE),
        "solve",
        to_facelets(cube),
        "--max-depth",
        str(max_depth),
        "--timeout",
        str(timeout_seconds),
        "--threads",
        str(worker_count),
        "--pdb",
        str(CORNER_PDB.relative_to(ROOT)),
    ]
    if PHASE1_PDB.is_file():
        command.extend(("--phase1-pdb", str(PHASE1_PDB.relative_to(ROOT))))
    if TAIL_PDB.is_file():
        command.extend(("--tail-pdb", str(TAIL_PDB.relative_to(ROOT))))
    use_edge_pdbs = os.environ.get("CUBE_NATIVE_EDGE_PDBS", "").strip().lower() in {"1", "true", "yes"}
    if use_edge_pdbs and EDGE_PDB_A.is_file() and EDGE_PDB_B.is_file():
        command.extend(
            (
                "--edge-pdb-a",
                str(EDGE_PDB_A.relative_to(ROOT)),
                "--edge-pdb-b",
                str(EDGE_PDB_B.relative_to(ROOT)),
            )
        )
    if use_edge_pdbs and EDGE_PDB_C.is_file() and EDGE_PDB_D.is_file():
        command.extend(
            (
                "--edge-pdb-c",
                str(EDGE_PDB_C.relative_to(ROOT)),
                "--edge-pdb-d",
                str(EDGE_PDB_D.relative_to(ROOT)),
            )
        )
    for flag, path in zip(
        ("--edge-pdb-e", "--edge-pdb-f", "--edge-pdb-g", "--edge-pdb-h"),
        (EDGE_PDB_E, EDGE_PDB_F, EDGE_PDB_G, EDGE_PDB_H),
    ):
        if use_edge_pdbs and path.is_file():
            command.extend((flag, str(path.relative_to(ROOT))))
    if incumbent_moves:
        command.extend(("--incumbent", " ".join(incumbent_moves)))

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=creation_flags,
    )
    stdout_parts: list[str] = []
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        stdout_parts.append(process.stdout.read())

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                stderr_lines.append(stripped)
                continue
            if event.get("type") == "progress":
                if progress_callback is not None:
                    progress_callback(event)
            else:
                stderr_lines.append(stripped)

    output_thread = threading.Thread(target=read_stdout, name="cube-native-stdout", daemon=True)
    progress_thread = threading.Thread(target=read_stderr, name="cube-native-stderr", daemon=True)
    output_thread.start()
    progress_thread.start()
    cancelled = False
    while process.poll() is None:
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    output_thread.join(timeout=2)
    progress_thread.join(timeout=2)
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()
    stdout = "".join(stdout_parts)
    stderr = "\n".join(stderr_lines)
    if cancelled:
        raise NativeSolverCancelled("搜索已取消。")

    if process.returncode != 0:
        message = stderr.strip().splitlines()[-1] if stderr.strip() else "native solver failed"
        try:
            message = json.loads(message).get("error", message)
        except json.JSONDecodeError:
            pass
        raise NativeSolverError(str(message))

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise NativeSolverError("native solver returned invalid JSON") from exc
    if not payload.get("ok"):
        raise NativeSolverError(str(payload.get("error", "native solver failed")))
    if payload.get("status") == "timeout":
        raise NativeSolverTimeout("原生最短性证明超时。")

    moves = [str(move) for move in payload.get("moves", [])]
    verified = cube
    try:
        for move in moves:
            verified = verified.apply_move_index(MOVE_INDEX[move])
    except KeyError as exc:
        raise NativeSolverError(f"native solver returned unknown move: {exc.args[0]}") from exc
    if not verified.is_solved():
        raise NativeSolverError("native solver returned an invalid solution")

    return {
        "moves": moves,
        "solution": " ".join(moves),
        "depth": len(moves),
        "metric": "HTM",
        "optimal": bool(payload.get("optimal")),
        "elapsed_seconds": round(float(payload.get("elapsed_seconds", 0.0)), 3),
        "nodes": int(payload.get("nodes", 0)),
        "engine": "native-cpp",
    }
