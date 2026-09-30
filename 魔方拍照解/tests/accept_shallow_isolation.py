"""Eight exact shallow answers against one isolated package's native service."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cube_app.cubie import CubieCube, MOVE_INDEX, MOVE_NAMES, to_facelets  # noqa: E402
from cube_app.metrics import move_cost, solution_cost  # noqa: E402


SCRAMBLES = (
    "", "R", "R2", "R U", "F2 D", "R U R'", "L2 B", "U F' R",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exact_costs(metric: str, targets: set[CubieCube]) -> dict[CubieCube, int]:
    pending = [(0, 0, CubieCube())]
    best = {CubieCube(): 0}
    found = {}
    serial = 0
    while pending and len(found) < len(targets):
        cost, _, cube = heapq.heappop(pending)
        if cost != best[cube]:
            continue
        if cube in targets:
            found[cube] = cost
        for move, name in enumerate(MOVE_NAMES):
            next_cost = cost + move_cost(move, metric)
            if next_cost > 3:
                continue
            neighbor = cube.apply_move_index(move)
            if next_cost < best.get(neighbor, 100):
                best[neighbor] = next_cost
                serial += 1
                heapq.heappush(pending, (next_cost, serial, neighbor))
    if len(found) != len(targets):
        raise RuntimeError("a selected shallow state exceeds cost 3")
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--metric", choices=("HTM", "QTM"), required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve()
    if (package / "native" / args.metric.lower() / "build").is_dir():
        binary = package / "native" / args.metric.lower() / "build" / f"cube_solver_{args.metric.lower()}.exe"
        assets = package / "assets" / args.metric.lower() / "v1"
        cache = package / ".cache" / args.metric.lower() / (
            "coordinates_dual_v2.bin" if args.metric == "QTM" else "coordinates_htm_v1.bin"
        )
    else:
        binary = package / "native" / "build" / "cube_solver.exe"
        assets = package / ".cache" / "native"
        cache = assets / ("coordinates_dual_v2.bin" if args.metric == "QTM" else "coordinates_htm_v1.bin")
    command = [str(binary), "serve", "--pdb", str(assets / "corner_htm_v2.pdb"),
               "--phase1-pdb", str(assets / "phase1_sym_htm_v2.pdb"),
               "--tail-pdb", str(assets / "tail_depth6_v4.pdb")]
    if args.metric == "QTM":
        command += ["--qtm-pdb", str(assets / "corner_qtm_v3.pdb"),
                    "--qtm-phase1-pdb", str(assets / "phase1_qtm_v3.pdb"),
                    "--strong-pdb", str(assets / "strong_qtm_v4_nibble.pdb"),
                    "--qtm-tail-pdb", str(assets / "tail_qtm_depth8_v5.pdb"),
                    "--asset-loading=eager", "--no-proof-cache"]
    states = []
    for scramble in SCRAMBLES:
        cube = CubieCube()
        for name in scramble.split():
            cube = cube.apply_move_index(MOVE_INDEX[name])
        states.append(cube)
    reference = exact_costs(args.metric, set(states))
    lines: queue.Queue[str | None] = queue.Queue()
    errors: list[str] = []
    environment = os.environ.copy()
    environment["CUBE_NATIVE_COORDINATE_CACHE"] = str(cache)
    process = subprocess.Popen(
        command, cwd=package, env=environment, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

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
            raise RuntimeError("native service exited: " + "".join(errors[-5:]))
        return json.loads(raw)

    threads = min(32, max(1, (os.cpu_count() or 1) - 1))
    output = {"label": args.label, "metric": args.metric, "package": str(package),
              "binary_sha256": sha256(binary), "threads": threads, "runs": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        ready = event(45)
        if ready.get("type") != "ready" or not ready.get("ok"):
            raise RuntimeError(f"native ready failed: {ready}")
        output["ready"] = ready
        for index, (scramble, cube) in enumerate(zip(SCRAMBLES, states)):
            request_id = f"shallow-{index}"
            fields = ["solve", request_id, to_facelets(cube), "3", "5", str(threads)]
            fields += ["QTM", ""] if args.metric == "QTM" else [""]
            assert process.stdin is not None
            before = time.perf_counter()
            process.stdin.write("\t".join(fields) + "\n")
            process.stdin.flush()
            frames = []
            while True:
                item = event(8)
                if item.get("request_id") != request_id:
                    continue
                if item.get("type") in {"progress", "candidate", "asset_ready"}:
                    frames.append(item)
                    continue
                if item.get("type") != "result":
                    raise RuntimeError(f"native failed: {item}")
                verified = cube
                for move in item["moves"]:
                    verified = verified.apply_move_index(MOVE_INDEX[move])
                expected = reference[cube]
                actual = solution_cost(item["moves"], args.metric)
                if not verified.is_solved() or actual != expected or item.get("optimal") is not True:
                    raise AssertionError((scramble, expected, item))
                run = {"scramble": scramble, "facelets": to_facelets(cube),
                       "expected_cost": expected, "wall_seconds": time.perf_counter() - before,
                       "result": item, "frames": frames}
                output["runs"].append(run)
                args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"label": args.label, "scramble": scramble,
                                  "cost": actual, "wall_seconds": run["wall_seconds"]}), flush=True)
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
