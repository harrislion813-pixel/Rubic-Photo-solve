"""Read-only HTM diagnostics: current binary, no solver modifications."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from benchmark_next_speed_pair import Service
from benchmark_isolation_short import fixed_layer
from cube_app.cubie import from_facelets
from cube_app.solvers.htm.fast import FastTwoPhaseSolver
from cube_app.solvers.htm.tables import load_or_build_tables

if len(sys.argv) != 2:
    raise SystemExit("usage: diagnose.py NEW_OUTPUT_JSON")
OUT = Path(sys.argv[1]).resolve()
if OUT.exists():
    raise SystemExit("refusing to overwrite existing diagnostics")
OUT.parent.mkdir(parents=True, exist_ok=True)
BINARY = ROOT / "native/htm/build/cube_solver_htm.exe"
ASSETS = ROOT / "assets/htm/v1"
CASES = {c["name"]: c for c in json.loads((ROOT / "tests/initial_solver_cases.json").read_text(encoding="utf-8"))}
report = {"scope": "Diagnostic only, not an optimization A/B or default HTTP benchmark. Warm OS cache; no candidates/cache/direction probe during exclusion runs.",
          "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest(),
          "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
          "startup": [], "layers": [], "candidates": []}

def save():
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

def startup(label, flags, repeat):
    env = os.environ.copy()
    env["CUBE_NATIVE_COORDINATE_CACHE"] = str(ROOT / ".cache/htm/coordinates_htm_v1.bin")
    start = time.perf_counter()
    process = subprocess.Popen([str(BINARY), "serve", *map(str, flags)], cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    try:
        ready = json.loads(lines.get(timeout=40))
        row = {"label": label, "repeat": repeat, "seconds": time.perf_counter() - start, "ready": ready}
        assert ready.get("ok") and ready.get("type") == "ready", ready
        report["startup"].append(row)
        print(json.dumps({k: row[k] for k in ("label", "repeat", "seconds")}), flush=True)
    finally:
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout, process.stderr): stream.close()
        save()

flags = {"coordinate_only": [], "corner_only": ["--pdb", ASSETS / "corner_htm_v2.pdb"],
    "phase1_only": ["--phase1-pdb", ASSETS / "phase1_sym_htm_v2.pdb"],
    "tail_only": ["--tail-pdb", ASSETS / "tail_depth6_v4.pdb"]}
flags["full"] = [arg for label in ("phase1_only", "corner_only", "tail_only") for arg in flags[label]]
for repeat in range(3):
    for label in list(flags) if repeat % 2 == 0 else list(reversed(flags)):
        startup(label, flags[label], repeat)

for direction in ("forward", "inverse"):
    service = Service(BINARY, "HTM", ["--no-direction-probe"] + (["--inverse-direction"] if direction == "inverse" else []))
    try:
        for repeat in range(3):
            names = ("initial-1", "initial-12") if repeat % 2 == 0 else ("initial-12", "initial-1")
            for name in names:
                run = service.solve(CASES[name]["facelets"], 16, 5, 15, "unused")
                run.update(case=name, direction=direction, repeat=repeat, threads=15)
                report["layers"].append(run)
                try: run["fixed_layer"] = fixed_layer(run)
                except AssertionError as exc: run["incomplete"] = str(exc)
                save()
                frame = run["progress"][-1] if run["result"].get("type") == "error" else run["result"]
                print(json.dumps({"case": name, "direction": direction, "repeat": repeat,
                    "wall": run["wall_seconds"], "generated": frame.get("generated_candidates"),
                    "tail": frame.get("tail_queries"), "completed": frame.get("completed_depth")}), flush=True)
        if direction == "forward":
            for repeat in range(2):
                for threads in (1, 4, 8, 15) if repeat == 0 else (15, 8, 4, 1):
                    run = service.solve(CASES["initial-1"]["facelets"], 15, 5, threads, "unused")
                    run.update(case="initial-1", direction=direction, repeat=repeat, threads=threads, scaling=True)
                    report["layers"].append(run)
                    try: run["fixed_layer"] = fixed_layer(run)
                    except AssertionError as exc: run["incomplete"] = str(exc)
                    save()
                    print(json.dumps({"scaling_threads": threads, "repeat": repeat, "wall": run["wall_seconds"]}), flush=True)
    finally: service.close()

start = time.perf_counter()
tables = load_or_build_tables(ROOT / ".cache/htm")
report["python_table_load_seconds"] = time.perf_counter() - start
solver = FastTwoPhaseSolver(tables=tables)
for name in ("initial-1", "initial-12", "initial-2", "initial-5", "initial-8", "initial-16"):
    events = []
    start = time.perf_counter()
    try:
        result = solver.solve_cube(from_facelets(CASES[name]["facelets"]), timeout_seconds=1.5,
            candidate_callback=lambda r: events.append({"seconds": time.perf_counter() - start, "cost": r.depth, "moves": r.moves}))
        row = {"case": name, "seconds": time.perf_counter() - start, "cost": result.depth, "moves": result.moves, "events": events}
    except Exception as exc:
        row = {"case": name, "seconds": time.perf_counter() - start, "error": str(exc), "events": events}
    report["candidates"].append(row)
    print(json.dumps(row), flush=True)
    save()

print("saved " + str(OUT), flush=True)
