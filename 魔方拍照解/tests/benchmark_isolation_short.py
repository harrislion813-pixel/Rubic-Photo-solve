"""Fixed two-state, three-repeat native proof-layer comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from benchmark_native import case_state
from cube_app.cubie import to_facelets

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--metric", choices=("HTM", "QTM"), required=True)
    parser.add_argument("--bound", type=int, required=True)
    parser.add_argument("--bound-pgo", type=int)
    parser.add_argument("--bound-known", type=int)
    parser.add_argument("--cases", default="pgo16,known18")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--threads", type=int, default=min(32, max(1, (os.cpu_count() or 1) - 1)))
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.timeout > 5 or args.timeout <= 0 or not 1 <= args.threads <= 32:
        parser.error("repeats must be positive and timeout must be at most 5 seconds")
    binary = args.binary.resolve()
    asset_root = ROOT / "assets" / ("htm" if args.metric == "HTM" else "qtm") / "v1"
    paths = {
        "corner": asset_root / "corner_htm_v2.pdb",
        "phase1": asset_root / "phase1_sym_htm_v2.pdb",
        "tail": asset_root / "tail_depth6_v4.pdb",
    }
    command = [str(binary), "serve", "--pdb", str(paths["corner"]),
               "--phase1-pdb", str(paths["phase1"]), "--tail-pdb", str(paths["tail"])]
    if args.metric == "QTM":
        paths.update({
            "qtm_corner": asset_root / "corner_qtm_v3.pdb",
            "qtm_phase1": asset_root / "phase1_qtm_v3.pdb",
            "strong": asset_root / "strong_qtm_v4_nibble.pdb",
            "qtm_tail": asset_root / "tail_qtm_depth8_v5.pdb",
        })
        command += [
            "--qtm-pdb", str(paths["qtm_corner"]),
            "--qtm-phase1-pdb", str(paths["qtm_phase1"]),
            "--strong-pdb", str(paths["strong"]),
            "--qtm-tail-pdb", str(paths["qtm_tail"]),
            "--asset-loading=eager", "--no-proof-cache",
        ]
    cache = ROOT / ".cache" / args.metric.lower() / (
        "coordinates_htm_v1.bin" if args.metric == "HTM" else "coordinates_dual_v2.bin"
    )
    environment = os.environ.copy()
    environment["CUBE_NATIVE_COORDINATE_CACHE"] = str(cache)
    started = time.perf_counter()
    process = subprocess.Popen(
        command, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: queue.Queue[str | None] = queue.Queue()
    errors: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    def read_stderr() -> None:
        assert process.stderr is not None
        errors.extend(process.stderr)

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()

    def event(timeout: float) -> dict:
        raw = lines.get(timeout=timeout)
        if raw is None:
            raise RuntimeError("service exited: " + "".join(errors[-5:]))
        return json.loads(raw)

    selected = set(args.cases.split(","))
    cases = [
        item for item in json.loads((ROOT / "tests/native_cases.json").read_text(encoding="utf-8"))
        if item["name"] in selected
    ]
    if selected != {item["name"] for item in cases} or not selected <= {"pgo16", "known18"}:
        parser.error("select pgo16 and/or known18")
    output = {
        "label": args.label, "metric": args.metric, "bound": args.bound,
        "case_bounds": {"pgo16": args.bound_pgo or args.bound, "known18": args.bound_known or args.bound},
        "timeout_seconds": args.timeout, "threads": args.threads, "binary": str(binary),
        "binary_sha256": sha256(binary),
        "assets": {name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                   for name, path in paths.items()},
        "cases": [], "startup_seconds": None, "ready": None, "runs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        ready = event(40)
        if ready.get("type") != "ready" or not ready.get("ok"):
            raise RuntimeError(f"bad native ready: {ready}")
        if args.metric == "HTM" and ready.get("protocol_version", 0) < 2:
            raise RuntimeError("HTM protocol v2 unavailable")
        if args.metric == "QTM" and "QTM" not in ready.get("metrics", []):
            raise RuntimeError("QTM protocol unavailable")
        output["startup_seconds"] = time.perf_counter() - started
        output["ready"] = ready
        for case in cases:
            state, _ = case_state(case)
            output["cases"].append({"name": case["name"], "facelets": to_facelets(state)})
        for repeat in range(args.repeats):
            for case in cases if repeat % 2 == 0 else reversed(cases):
                state, _ = case_state(case)
                request_id = f"{case['name']}-{repeat}"
                bound = output["case_bounds"][case["name"]]
                fields = ["solve", request_id, to_facelets(state),
                          str(bound), str(args.timeout), str(args.threads)]
                if args.metric == "QTM":
                    fields += ["QTM", ""]
                else:
                    fields += [""]
                assert process.stdin is not None
                before = time.perf_counter()
                process.stdin.write("\t".join(fields) + "\n")
                process.stdin.flush()
                progress = []
                while True:
                    item = event(args.timeout + 10)
                    if item.get("request_id") != request_id:
                        continue
                    if item.get("type") in {"progress", "candidate", "asset_ready"}:
                        progress.append(item)
                        continue
                    run = {
                        "case": case["name"], "repeat": repeat,
                        "bound": bound,
                        "wall_seconds": time.perf_counter() - before,
                        "result": item, "progress": progress,
                    }
                    output["runs"].append(run)
                    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps({"case": case["name"], "repeat": repeat,
                                      "wall_seconds": run["wall_seconds"],
                                      "status": item.get("status"),
                                      "completed_depth": item.get("completed_depth")}), flush=True)
                    break
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output["stderr"] = errors
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
