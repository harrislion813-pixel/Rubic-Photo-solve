"""Build and certify QTM base PDBs with reproducible resource measurements."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
ASSETS = (
    ("corner", "corner_qtm_v3.pdb", "build-corner-pdb", "corner", None),
    ("phase1", "phase1_qtm_v3.pdb", "build-phase1-pdb", "phase1", None),
    ("edge_a", "edge_a_qtm_v3.pdb", "build-edge-pdb", "edge", 0),
    ("edge_b", "edge_b_qtm_v3.pdb", "build-edge-pdb", "edge", 1),
)


class Counters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
            "PagefileUsage", "PeakPagefileUsage",
        )
    ]


def process_memory(process: subprocess.Popen) -> dict[str, int] | None:
    if os.name != "nt":
        return None
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not get_memory(int(process._handle), ctypes.byref(counters), counters.cb):
        return None
    return {"peak_working_set_bytes": int(counters.PeakWorkingSetSize),
            "peak_commit_bytes": int(counters.PeakPagefileUsage)}


def file_metadata(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def measured_run(command: list[str], memory_limit_bytes: int) -> dict:
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    peak_working = 0
    peak_commit = 0
    while process.poll() is None:
        sample = process_memory(process)
        if sample:
            peak_working = max(peak_working, sample["peak_working_set_bytes"])
            peak_commit = max(peak_commit, sample["peak_commit_bytes"])
            if peak_commit > memory_limit_bytes:
                process.kill()
                process.communicate()
                raise RuntimeError(f"build exceeded commit limit: {peak_commit} > {memory_limit_bytes}")
        time.sleep(0.02)
    sample = process_memory(process)
    if sample:
        peak_working = max(peak_working, sample["peak_working_set_bytes"])
        peak_commit = max(peak_commit, sample["peak_commit_bytes"])
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"{command!r} failed ({process.returncode}): {stderr[-3000:]}")
    return {"wall_seconds": time.perf_counter() - started,
            "peak_working_set_bytes": peak_working or None,
            "peak_commit_bytes": peak_commit or None,
            "result": json.loads(stdout), "build_log": stderr.splitlines()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "native/build/cube_solver.exe")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit-gib", type=float, default=12)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/benchmarks/qtm-base-pdb-build-2026-09-28.json")
    args = parser.parse_args()
    if args.threads < 1 or args.memory_limit_gib <= 0:
        parser.error("threads and memory limit must be positive")
    binary = args.binary.resolve()
    memory_limit = int(args.memory_limit_gib * 1024**3)
    output = {"metric": "QTM", "builder": file_metadata(binary),
              "build_info": file_metadata(binary.with_name("build-info.json")),
              "threads": args.threads, "memory_limit_bytes": memory_limit, "assets": {}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for key, filename, build_command, pattern, group in ASSETS:
        path = ROOT / ".cache/native" / filename
        command = [str(binary), build_command, str(path), "--metric", "QTM", "--threads", str(args.threads),
                   "--force"]
        if group is not None:
            command += ["--group", str(group)]
        build = measured_run(command, memory_limit)
        verify_command = [str(binary), "verify-pdb", str(path), "--pattern", pattern,
                          "--threads", str(args.threads), "--full"]
        if group is not None:
            verify_command += ["--group", str(group)]
        verify = measured_run(verify_command, memory_limit)
        output["assets"][key] = {"file": file_metadata(path), "build": build, "verify": verify,
                                 "command": command, "verify_command": verify_command}
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{key}: {build['wall_seconds']:.3f}s build, {verify['wall_seconds']:.3f}s verify",
              flush=True)


if __name__ == "__main__":
    main()
